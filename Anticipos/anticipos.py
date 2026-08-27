"""
Reporte diario de anticipos a proveedores por sociedad.

Que se considera un anticipo
----------------------------
ANTICIPOS A PROVEEDORES (UMSKZ = 'A'). Operaciones en cuenta especial que alguien
registro en SAP declarandolas como anticipo, contabilizadas en cuentas de activo
(10801xx, 0000140110). Son los anticipos canonicos.

Hasta 2026-08-27 el reporte tambien incluia los SALDOS DEUDORES EN CUENTAS DE PROVEEDOR
(UMSKZ vacio: partidas normales de acreedor cuyo saldo neto salia positivo, es decir
pagos de mas sin declarar como anticipo). Se quitaron a peticion del usuario: el reporte
ahora es solo de los anticipos formales.

El calculo es el saldo neto de las partidas abiertas de UMSKZ = 'A', agrupadas por
sociedad + cuenta + proveedor, con el signo que marca SHKZG ('S' debe suma, 'H' haber
resta). Entran tanto los saldos positivos como los negativos: el cliente quiere ver
tambien los anticipos formales que salen en negativo (antes se descartaban junto con el
resto de negativos; solo se excluye un saldo exactamente en cero, que no es nada que
reportar).

Decisiones tomadas, con su motivo
---------------------------------
1. Se filtra UMSKZ = 'A' en el propio WHERE, no en el GROUP BY.

   Antes el reporte tambien mostraba UMSKZ vacio (saldos deudores) y necesitaba UMSKZ en
   el GROUP BY para no mezclar un anticipo formal ('A') con su propia solicitud ('F'),
   que comparte cuenta de mayor. Al filtrar ya en el WHERE a solo 'A', las filas 'F' ni
   entran en el calculo, asi que ese GROUP BY ya no hace falta.

2. Se excluyen UMSKZ = 'F' y 'H' (y ahora tambien UMSKZ vacio).

   'F' es una SOLICITUD de anticipo: un apunte estadistico para planificar pagos, no
   dinero movido. 'H' son otros indicadores especiales, ajenos a este reporte. El vacio
   (saldos deudores) se excluyo el 2026-08-27 a peticion del usuario.

3. No se filtra por cuenta de mayor.

   El anticipo lo define el signo del saldo, no la cuenta. Las cuentas que aparecen en un
   reporte concreto son las que tenian saldo ese dia en esa sociedad, no una lista
   cerrada. La cuenta se muestra como columna informativa.

4. El nombre del proveedor sale de D20_DIMENSION.dm_vendors, no de LFA1.

   dm_vendors cubre el 100% de los proveedores de BSIK y tiene un nombre de tabla
   estable. LFA1 vive en snapshots con la fecha en el nombre (proan_LFA1_20260728), que
   obligaria a construir el nombre de tabla en cada ejecucion.

   dm_vendors tiene una fila por direccion, no por proveedor: 25.147 filas para 23.155
   proveedores. Por eso se deduplica antes de cruzar. Sin ese GROUP BY el cruce
   multiplicaria filas de anticipo e inflaria los totales del correo.

   El nombre de la sociedad sale de D20_DIMENSION.dm_company (company_code ->
   company_name). Ahi company_code SI es unico —87 filas, 87 codigos— asi que no hace
   falta deduplicar. La columna `company` de esa tabla esta vacia en las 87 filas: la
   buena es company_name.

5. DMBTR se convierte a NUMERIC antes de sumar.

   En la tabla espejo DMBTR es FLOAT. Sumar importes en coma flotante arrastra error;
   NUMERIC es aritmetica decimal exacta, que es lo que corresponde a dinero.

6. Se aborta si el espejo esta caducado.

   bsik_real_time no la carga el Airflow del DWH: es un espejo que un replicador
   externo reescribe entera cada dos horas (todas las filas comparten marca de
   _ingested_at). Si ese replicador se para, la tabla se queda con datos viejos sin
   avisar. Antes de enviar nada se comprueba la antiguedad de la ultima carga y el
   proceso falla en vez de mandar un reporte caducado como si fuera del dia.

Persistencia
------------
Se guarda una foto diaria en D60_REPORTING.Anticipos_evolucion, particionada por dia.

La columna `tipo` sigue existiendo y siempre vale 'anticipo': se conserva por
continuidad historica con las filas de antes de 2026-08-27, que si distinguian
'saldo_deudor'. No se ha borrado esa columna de la tabla ni se ha tocado el historico.

Es la unica historia que existe: BSIK solo contiene partidas ABIERTAS, cuando un
anticipo se compensa la fila desaparece, el espejo se reescribe cada dos horas y
bsak_real_time (donde SAP guardaria las compensadas) esta vacia en BigQuery. Sin esta
tabla no hay forma de saber que un anticipo existio ni cuanto tiempo estuvo abierto.

La escritura usa el decorador de particion con WRITE_TRUNCATE, asi que reejecutar el
proceso el mismo dia reemplaza la foto del dia entera, sin duplicar ni dejar restos.

Esta misma tabla es tambien la fuente del "Total ayer" que aparece en el resumen del
correo consolidado y en el bloque de cada sociedad (consolidado e individual): se relee
(fecha_reporte = ayer) para comparar contra el total de hoy. Una sociedad sin fila para
ayer se trata como que no tenia anticipos ese dia (0), no como un error. Si la relectura
entera falla, la columna sale con "-" en vez de un 0 enganoso.

Destinatarios
-------------
Documento Firestore lists/anticipos, con dos bloques:

- globales: direcciones que estan en todas las sociedades. Reciben UN unico correo con
  todas las sociedades juntas.
- por_sociedad: mapa sociedad -> correos, un correo por sociedad.

Quien esta en globales se declara, no se deduce de por_sociedad, para que el
comportamiento no cambie solo porque alguien entre o salga de una sociedad.

Si Firestore no esta disponible se cae a ANTICIPOS_EMAIL_TO y luego a los
destinatarios por defecto, y en ese caso se envia SOLO el correo global: nunca se
adivina quien debe recibir los datos de una sociedad concreta.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from html import escape
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


PROJECT_ID = "proan-quantrue"
ORIGEN_BSIK = f"{PROJECT_ID}.D00_SANDBOX.bsik_real_time"
ORIGEN_PROVEEDORES = f"{PROJECT_ID}.D20_DIMENSION.dm_vendors"
ORIGEN_SOCIEDADES = f"{PROJECT_ID}.D20_DIMENSION.dm_company"
DESTINO = f"{PROJECT_ID}.D60_REPORTING.Anticipos_evolucion"

# Las 16 sociedades del reporte, en el orden de las columnas del Excel de correos.
SOCIEDADES = (
    "PAN", "DBC", "ROMM", "PRA", "MPE", "MAL", "HEGP", "ISE",
    "PIN", "SAP", "ABP", "AME", "CCP", "PAL", "PAT", "BAG",
)

# El unico tipo que reporta este proceso: el anticipo declarado en SAP (UMSKZ = 'A').
# Se conserva como columna en BigQuery por continuidad historica (ver docstring del
# modulo); ya no hay un segundo tipo en el correo desde que se quitaron los saldos
# deudores el 2026-08-27.
TIPO_ANTICIPO = "anticipo"
TITULO_ANTICIPOS = "Anticipos a proveedores"
NOTA_ANTICIPOS = "Registrados en SAP como anticipo, en cuentas de activo."

ZONA_MEXICO = ZoneInfo("America/Mexico_City")
SIN_NOMBRE = "(sin nombre en la maestra)"
SIN_NOMBRE_SOCIEDAD = "(sin nombre en la maestra)"
SIN_CUENTA = "(sin cuenta)"
DESTINATARIOS_POR_DEFECTO = ("pcoma@quantrue.com",)

FIRESTORE_DATABASE_ID = os.environ.get("FIRESTORE_DATABASE_ID", "proan-lista-mails").strip()
FIRESTORE_LISTS_COLLECTION = os.environ.get("FIRESTORE_LISTS_COLLECTION", "lists").strip()
ANTICIPOS_LIST_ID = os.environ.get("ANTICIPOS_LIST_ID", "anticipos").strip()

# Colores corporativos, los mismos que el correo de cambio de divisa.
AZUL = "#2A2B5F"
BORDE = "#d9dee5"

# El PDF adjunto se genera con el MISMO HTML del correo mas una hoja de estilos de
# impresion. Es lo que evita que el correo y el adjunto se separen con el tiempo: hay una
# sola definicion del layout, no dos.
PDF_ORIENTACION = "portrait"  # 4 columnas: cabe de sobra en vertical
AVISO_SIN_PDF = (
    "No se pudo generar el PDF adjunto de este reporte. El detalle completo esta en "
    "este correo."
)


# --------------------------------------------------------------------------- #
# Configuracion
# --------------------------------------------------------------------------- #

def _es_verdadero(valor: str) -> bool:
    return valor.strip().lower() in {"1", "true", "yes", "si"}


def sociedades_objetivo() -> tuple[str, ...]:
    """Sociedades a reportar, recortables por entorno para las pruebas."""
    crudo = os.environ.get("ANTICIPOS_ONLY_SOCIEDADES", "").strip()
    if not crudo:
        return SOCIEDADES

    pedidas = [s.strip().upper() for s in crudo.split(",") if s.strip()]
    desconocidas = [s for s in pedidas if s not in SOCIEDADES]
    if desconocidas:
        raise ValueError(
            f"ANTICIPOS_ONLY_SOCIEDADES contiene sociedades que no son del reporte: "
            f"{', '.join(desconocidas)}"
        )

    # Se respeta el orden canonico, no el que venga en la variable.
    seleccion = tuple(s for s in SOCIEDADES if s in pedidas)
    logging.warning("Ejecucion limitada a %s por ANTICIPOS_ONLY_SOCIEDADES", ", ".join(seleccion))
    return seleccion


# --------------------------------------------------------------------------- #
# Origen de datos
# --------------------------------------------------------------------------- #

def verificar_frescura(client) -> datetime:
    """Comprueba que el espejo de BSIK no esta caducado. Falla si lo esta."""
    horas_maximas = int(os.environ.get("ANTICIPOS_MAX_ANTIGUEDAD_HORAS", "6"))

    consulta = f"SELECT MAX(_ingested_at) AS ultima_carga FROM `{ORIGEN_BSIK}`"
    fila = next(client.query(consulta).result(), None)
    ultima_carga = fila["ultima_carga"] if fila is not None else None
    if ultima_carga is None:
        raise RuntimeError(f"La tabla {ORIGEN_BSIK} esta vacia: no hay nada que reportar.")

    antiguedad = datetime.now(timezone.utc) - ultima_carga
    logging.info(
        "Ultima carga del espejo: %s (hace %.1f horas)",
        ultima_carga.isoformat(),
        antiguedad.total_seconds() / 3600,
    )

    if antiguedad > timedelta(hours=horas_maximas):
        raise RuntimeError(
            f"El espejo {ORIGEN_BSIK} tiene {antiguedad.total_seconds() / 3600:.1f} horas de "
            f"antiguedad, mas del maximo de {horas_maximas}. El replicador de SAP puede estar "
            f"parado. No se envia el reporte para no dar por bueno un dato caducado."
        )

    return ultima_carga


def consultar_anticipos(client, sociedades: tuple[str, ...]) -> list[dict[str, Any]]:
    """
    Anticipos formales (UMSKZ = 'A') por sociedad, cuenta y proveedor, con su nombre.

    Se filtra UMSKZ = 'A' ya en el WHERE de la CTE, asi que las filas 'F' (solicitud de
    anticipo, comparte cuenta con 'A') ni entran en el calculo: no hace falta UMSKZ en
    el GROUP BY para separarlas.
    """
    from google.cloud import bigquery

    consulta = f"""
        WITH saldos AS (
          SELECT
            BUKRS AS sociedad,
            IFNULL(HKONT, '') AS cuenta,
            LTRIM(LIFNR, '0') AS proveedor,
            ROUND(SUM(
              CASE WHEN SHKZG = 'S'
                   THEN CAST(DMBTR AS NUMERIC)
                   ELSE -CAST(DMBTR AS NUMERIC)
              END
            ), 2) AS saldo_neto
          FROM `{ORIGEN_BSIK}`
          WHERE UMSKZ = 'A'
            AND BUKRS IN UNNEST(@sociedades)
          GROUP BY sociedad, cuenta, proveedor
        ),
        proveedores AS (
          SELECT
            LTRIM(id_proveedor, '0') AS proveedor,
            ANY_VALUE(razon_social) AS razon_social
          FROM `{ORIGEN_PROVEEDORES}`
          WHERE razon_social IS NOT NULL AND razon_social != ''
          GROUP BY proveedor
        )
        SELECT
          s.sociedad,
          @tipo_anticipo AS tipo,
          s.cuenta,
          s.proveedor,
          IFNULL(p.razon_social, @sin_nombre) AS nombre_proveedor,
          s.saldo_neto
        FROM saldos s
        LEFT JOIN proveedores p USING (proveedor)
        -- Entran positivos y negativos: el cliente quiere ver tambien los anticipos
        -- formales que salen en negativo. Solo se excluye el saldo exactamente en
        -- cero, que no es nada que reportar.
        WHERE s.saldo_neto != 0
        ORDER BY s.sociedad, s.saldo_neto DESC
    """
    configuracion = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ArrayQueryParameter("sociedades", "STRING", list(sociedades)),
            bigquery.ScalarQueryParameter("tipo_anticipo", "STRING", TIPO_ANTICIPO),
            bigquery.ScalarQueryParameter("sin_nombre", "STRING", SIN_NOMBRE),
        ]
    )

    filas = [
        {
            "sociedad": fila["sociedad"],
            "tipo": fila["tipo"],
            "cuenta": fila["cuenta"],
            "proveedor": fila["proveedor"],
            "nombre_proveedor": fila["nombre_proveedor"],
            "saldo_neto": fila["saldo_neto"],
        }
        for fila in client.query(consulta, job_config=configuracion).result()
    ]

    sin_nombre = sum(1 for f in filas if f["nombre_proveedor"] == SIN_NOMBRE)
    if sin_nombre:
        logging.warning("%s filas sin nombre de proveedor en dm_vendors", sin_nombre)

    return filas


def consultar_nombres_sociedad(client, sociedades: tuple[str, ...]) -> dict[str, str]:
    """
    Codigo de sociedad -> razon social, desde el maestro de empresas.

    No hace falta deduplicar: se comprobo que company_code es unico en dm_company, 87
    filas y 87 codigos distintos. Es lo contrario de dm_vendors, que tiene una fila por
    direccion y si obliga a agrupar antes de cruzar.

    Si el maestro falla se devuelve un diccionario vacio y el reporte sale con los
    codigos a secas. El nombre es una comodidad de lectura, no un dato del reporte: no
    tiene sentido dejar a finanzas sin su correo porque una tabla de referencia no
    responda.
    """
    from google.cloud import bigquery

    consulta = f"""
        SELECT company_code, company_name
        FROM `{ORIGEN_SOCIEDADES}`
        WHERE company_code IN UNNEST(@sociedades)
    """
    configuracion = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ArrayQueryParameter("sociedades", "STRING", list(sociedades)),
        ]
    )

    try:
        nombres = {
            fila["company_code"]: fila["company_name"]
            for fila in client.query(consulta, job_config=configuracion).result()
            if fila["company_name"]
        }
    except Exception as exc:
        logging.warning("No se pudieron leer los nombres de sociedad: %s", exc)
        return {}

    faltan = [s for s in sociedades if s not in nombres]
    if faltan:
        logging.warning("Sociedades sin nombre en el maestro: %s", ", ".join(faltan))
    return nombres


def consultar_totales_ayer(
    client, sociedades: tuple[str, ...], fecha_ayer
) -> dict[str, Decimal] | None:
    """
    Total de saldo_neto por sociedad en la foto de ayer (DESTINO), para la columna
    "Total ayer" del resumen del correo consolidado.

    Una sociedad sin fila para esa fecha no tenia anticipos ese dia: se trata como 0,
    igual que hace el resto del reporte con "sin anticipos". Si la consulta entera falla,
    se devuelve None y el resumen muestra "-" en vez de un 0 enganoso: no es lo mismo no
    tener dato que tener un total de cero.
    """
    from google.cloud import bigquery

    consulta = f"""
        SELECT sociedad, SUM(saldo_neto) AS total
        FROM `{DESTINO}`
        WHERE fecha_reporte = @fecha
          AND sociedad IN UNNEST(@sociedades)
        GROUP BY sociedad
    """
    configuracion = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("fecha", "DATE", fecha_ayer.isoformat()),
            bigquery.ArrayQueryParameter("sociedades", "STRING", list(sociedades)),
        ]
    )

    try:
        return {
            fila["sociedad"]: fila["total"]
            for fila in client.query(consulta, job_config=configuracion).result()
        }
    except Exception as exc:
        logging.warning("No se pudo leer el total de ayer: %s", exc)
        return None


def _etiqueta_sociedad(codigo: str, nombres: dict[str, str]) -> str:
    """'PAN - Proteina Animal SA de CV', o solo el codigo si no hay nombre."""
    if not nombres:
        # El maestro entero fallo. Mejor el codigo a secas que repetir dieciseis veces
        # que falta el nombre.
        return codigo
    return f"{codigo} - {nombres.get(codigo, SIN_NOMBRE_SOCIEDAD)}"


def agrupar_por_sociedad(
    filas: list[dict[str, Any]], sociedades: tuple[str, ...]
) -> dict[str, list[dict[str, Any]]]:
    """
    Una entrada por sociedad pedida, aunque este vacia.

    Asi el correo de una sociedad sin nada no es un caso especial: se recorre igual y
    sale con su mensaje de "sin anticipos".
    """
    agrupado: dict[str, list[dict[str, Any]]] = {sociedad: [] for sociedad in sociedades}
    for fila in filas:
        agrupado[fila["sociedad"]].append(fila)
    return agrupado


def _total(filas: list[dict[str, Any]]) -> Decimal:
    return sum((fila["saldo_neto"] for fila in filas), Decimal("0"))


# --------------------------------------------------------------------------- #
# Persistencia
# --------------------------------------------------------------------------- #

def _esquema_destino():
    from google.cloud import bigquery

    return [
        bigquery.SchemaField("fecha_reporte", "DATE", mode="REQUIRED"),
        bigquery.SchemaField("sociedad", "STRING", mode="REQUIRED"),
        # NULLABLE porque una columna anadida con ALTER TABLE no puede ser REQUIRED, y
        # esta se anadio despues de que la tabla existiera. El proceso siempre la rellena.
        bigquery.SchemaField("tipo", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("cuenta", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("proveedor", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("nombre_proveedor", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("saldo_neto", "NUMERIC", mode="REQUIRED"),
        bigquery.SchemaField("actualizado_en", "DATETIME", mode="REQUIRED"),
    ]


def asegurar_tabla(client) -> None:
    from google.cloud import bigquery

    tabla = bigquery.Table(DESTINO, schema=_esquema_destino())
    tabla.time_partitioning = bigquery.TimePartitioning(
        type_=bigquery.TimePartitioningType.DAY, field="fecha_reporte"
    )
    tabla.clustering_fields = ["sociedad"]
    client.create_table(tabla, exists_ok=True)
    # Para las tablas creadas antes de que existiera la columna tipo.
    client.query(
        f"ALTER TABLE `{DESTINO}` ADD COLUMN IF NOT EXISTS tipo STRING"
    ).result()


def guardar_foto(
    client, filas: list[dict[str, Any]], fecha_reporte, actualizado_en: datetime
) -> None:
    """
    Reemplaza la foto del dia completa.

    Se carga contra el decorador de particion (tabla$YYYYMMDD) con WRITE_TRUNCATE, que
    sustituye solo ese dia de forma atomica. Asi el proceso es idempotente: ejecutarlo
    dos veces el mismo dia deja el resultado de la segunda, sin duplicados ni filas
    huerfanas de un calculo anterior.
    """
    from google.cloud import bigquery

    fecha_iso = fecha_reporte.isoformat()
    marca = actualizado_en.strftime("%Y-%m-%dT%H:%M:%S")

    if not filas:
        # Un dia sin ningun anticipo en ninguna sociedad. Un load job vacio no vale
        # para vaciar la particion, asi que se borra explicitamente.
        logging.warning("Ningun anticipo hoy: se vacia la particion %s", fecha_iso)
        consulta = f"DELETE FROM `{DESTINO}` WHERE fecha_reporte = @fecha"
        configuracion = bigquery.QueryJobConfig(
            query_parameters=[bigquery.ScalarQueryParameter("fecha", "DATE", fecha_iso)]
        )
        client.query(consulta, job_config=configuracion).result()
        return

    registros = [
        {
            "fecha_reporte": fecha_iso,
            "sociedad": fila["sociedad"],
            "tipo": fila["tipo"],
            "cuenta": fila["cuenta"],
            "proveedor": fila["proveedor"],
            "nombre_proveedor": fila["nombre_proveedor"],
            "saldo_neto": str(fila["saldo_neto"]),
            "actualizado_en": marca,
        }
        for fila in filas
    ]

    destino_particion = f"{DESTINO}${fecha_reporte.strftime('%Y%m%d')}"
    configuracion = bigquery.LoadJobConfig(
        schema=_esquema_destino(),
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
        source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
    )
    client.load_table_from_json(registros, destino_particion, job_config=configuracion).result()
    logging.info("Guardadas %s filas en la particion %s", len(registros), fecha_iso)


# --------------------------------------------------------------------------- #
# Destinatarios
# --------------------------------------------------------------------------- #

def _normalizar_correos(crudos: Any) -> list[str]:
    """
    Deja una lista de direcciones limpias, sin repetidos y en el orden original.

    Acepta tanto 'alguien@proan.com' como 'Nombre Apellido <alguien@proan.com>', que es
    el formato en el que estaban en el Excel de origen.
    """
    if not isinstance(crudos, (list, tuple)):
        return []

    correos: list[str] = []
    vistos: set[str] = set()
    for crudo in crudos:
        texto = str(crudo or "").strip().strip(",").strip('"').strip()
        if "<" in texto and ">" in texto:
            texto = texto[texto.rfind("<") + 1 : texto.rfind(">")].strip()
        if not texto or "@" not in texto:
            continue
        clave = texto.lower()
        if clave in vistos:
            continue
        vistos.add(clave)
        correos.append(texto)
    return correos


def _destinatarios_firestore() -> tuple[list[str], dict[str, list[str]]]:
    from google.cloud import firestore

    client = firestore.Client(project=PROJECT_ID, database=FIRESTORE_DATABASE_ID)
    documento = (
        client.collection(FIRESTORE_LISTS_COLLECTION).document(ANTICIPOS_LIST_ID).get()
    )
    if not documento.exists:
        logging.warning(
            "No existe el documento Firestore %s/%s en la base %s",
            FIRESTORE_LISTS_COLLECTION,
            ANTICIPOS_LIST_ID,
            FIRESTORE_DATABASE_ID,
        )
        return [], {}

    datos = documento.to_dict() or {}
    if not datos.get("enabled", True):
        logging.warning("La lista Firestore %s esta deshabilitada", ANTICIPOS_LIST_ID)
        return [], {}

    globales = _normalizar_correos(datos.get("globales"))

    crudo_por_sociedad = datos.get("por_sociedad")
    por_sociedad: dict[str, list[str]] = {}
    if isinstance(crudo_por_sociedad, dict):
        for sociedad, correos in crudo_por_sociedad.items():
            limpios = _normalizar_correos(correos)
            if limpios:
                por_sociedad[str(sociedad).strip().upper()] = limpios
    elif crudo_por_sociedad is not None:
        logging.warning("El campo por_sociedad de %s no es un mapa", ANTICIPOS_LIST_ID)

    return globales, por_sociedad


def resolver_destinatarios() -> tuple[list[str], dict[str, list[str]], str]:
    try:
        globales, por_sociedad = _destinatarios_firestore()
    except Exception as exc:
        logging.warning("No se pudieron leer destinatarios de Firestore: %s", exc)
        globales, por_sociedad = [], {}

    if globales or por_sociedad:
        return globales, por_sociedad, "firestore"

    del_entorno = _normalizar_correos(
        [c for c in os.environ.get("ANTICIPOS_EMAIL_TO", "").split(",") if c.strip()]
    )
    if del_entorno:
        logging.warning(
            "Sin destinatarios en Firestore: se usa ANTICIPOS_EMAIL_TO y solo se envia "
            "el correo global."
        )
        return del_entorno, {}, "env"

    logging.warning(
        "Sin destinatarios en Firestore ni en entorno: se usan los de por defecto y "
        "solo se envia el correo global."
    )
    return list(DESTINATARIOS_POR_DEFECTO), {}, "default"


# --------------------------------------------------------------------------- #
# Correo
# --------------------------------------------------------------------------- #

def _importe(valor: Decimal) -> str:
    return f"{valor:,.2f}"


def _celda(contenido: str, *, derecha: bool = False, fuerte: bool = False) -> str:
    alineacion = "right" if derecha else "left"
    peso = "700" if fuerte else "400"
    color = AZUL if fuerte else "#374151"
    return (
        f'<td style="padding:10px 12px;text-align:{alineacion};font-size:12px;'
        f'font-weight:{peso};color:{color};border-bottom:1px solid {BORDE};">{contenido}</td>'
    )


def _encabezado(titulos: list[tuple[str, bool]]) -> str:
    """Fila de encabezado. Cada titulo va con un booleano de alineado a la derecha."""
    celdas = "".join(
        f'<th style="padding:9px 12px;text-align:{"right" if derecha else "left"};'
        f'font-family:Barlow,\'Segoe UI\',Arial,sans-serif;font-size:10px;font-weight:700;'
        f'color:#ffffff;text-transform:uppercase;letter-spacing:.5px;">{escape(titulo)}</th>'
        for titulo, derecha in titulos
    )
    return f'<tr style="background:{AZUL};">{celdas}</tr>'


def _fila_total(etiqueta: str, valores: list[Decimal | None], columnas_previas: int) -> str:
    """Fila de total. Una celda de valor por cada elemento de `valores`; `None` sale como "-"."""
    celdas_valor = "".join(
        f'<td style="padding:10px 12px;text-align:right;font-size:13px;font-weight:800;'
        f'color:{AZUL};">{escape(_importe(valor) if valor is not None else "-")}</td>'
        for valor in valores
    )
    return (
        "<tr>"
        f'<td colspan="{columnas_previas}" style="padding:10px 12px;text-align:right;'
        f'font-size:11px;font-weight:700;color:{AZUL};text-transform:uppercase;'
        f'letter-spacing:.5px;">{escape(etiqueta)}</td>'
        f"{celdas_valor}"
        "</tr>"
    )


def _tabla_detalle(filas: list[dict[str, Any]], etiqueta_total: str) -> str:
    cuerpo = []
    for fila in filas:
        cuenta = fila["cuenta"] or SIN_CUENTA
        cuerpo.append(
            "<tr>"
            + _celda(escape(cuenta))
            + _celda(escape(fila["proveedor"]), fuerte=True)
            + _celda(escape(fila["nombre_proveedor"]))
            + _celda(escape(_importe(fila["saldo_neto"])), derecha=True, fuerte=True)
            + "</tr>"
        )

    encabezado = _encabezado(
        [("Cuenta", False), ("Proveedor", False), ("Nombre", False), ("Saldo", True)]
    )
    return (
        f'<table width="100%" cellpadding="0" cellspacing="0" '
        f'style="border-collapse:collapse;border:1px solid {BORDE};border-radius:8px;'
        f'overflow:hidden;">'
        f"<thead>{encabezado}</thead>"
        f"<tbody>{''.join(cuerpo)}"
        f"{_fila_total(etiqueta_total, [_total(filas)], 3)}</tbody></table>"
    )


def _bloque_sociedad(
    sociedad: str,
    filas: list[dict[str, Any]],
    nombres: dict[str, str],
    totales_ayer: dict[str, Decimal] | None,
) -> str:
    """
    Bloque de una sociedad: titulo, la tabla de anticipos si hay alguno, y el total de
    ayer. Se usa tanto en el correo por sociedad como, una vez por cada una, dentro del
    consolidado.

    El total de ayer se muestra siempre, incluso sin anticipos hoy: que hoy este vacio y
    ayer no lo estuviera es justo el tipo de cambio que se quiere ver de un vistazo.
    """
    partes = [
        f'<p class="titulo-sociedad" style="font-family:Barlow,\'Segoe UI\',Arial,sans-serif;'
        f'font-size:16px;color:{AZUL};font-weight:800;margin:28px 0 2px;">'
        f"Sociedad {escape(_etiqueta_sociedad(sociedad, nombres))}</p>"
    ]

    if not filas:
        partes.append(
            '<p style="font-size:13px;color:#4b5563;margin:4px 0 8px;">'
            "Sin anticipos pendientes.</p>"
        )
    else:
        partes.append(
            f'<p class="titulo-seccion" style="font-size:13px;color:{AZUL};font-weight:700;'
            f'margin:16px 0 2px;">{escape(TITULO_ANTICIPOS)}</p>'
            f'<p class="titulo-seccion" style="font-size:11px;color:#6b7280;margin:0 0 8px;">'
            f"{escape(NOTA_ANTICIPOS)}</p>"
        )
        partes.append(_tabla_detalle(filas, f"Total {TITULO_ANTICIPOS.lower()}"))

    total_ayer = totales_ayer.get(sociedad, Decimal("0")) if totales_ayer is not None else None
    texto_ayer = _importe(total_ayer) if total_ayer is not None else "-"
    partes.append(
        f'<p style="font-size:12px;color:{AZUL};font-weight:700;margin:6px 0 0;'
        f'text-align:right;">Total ayer: {escape(texto_ayer)}</p>'
    )

    return "".join(partes)


def _celda_sociedad(codigo: str, nombres: dict[str, str]) -> str:
    """Codigo en negrita y razon social al lado, atenuada, en una sola celda.

    En una sola celda y no en dos columnas: los nombres rondan los 23 caracteres y una
    columna propia estrecharia las de importes, que son las que se leen."""
    nombre = "" if not nombres else nombres.get(codigo, SIN_NOMBRE_SOCIEDAD)
    extra = (
        f' <span style="font-weight:400;color:#6b7280;">{escape(nombre)}</span>'
        if nombre
        else ""
    )
    return _celda(f"{escape(codigo)}{extra}", fuerte=True)


def _resumen_sociedades(
    agrupado: dict[str, list[dict[str, Any]]],
    nombres: dict[str, str],
    totales_ayer: dict[str, Decimal] | None,
) -> str:
    """
    Tabla de totales por sociedad, solo para el correo global.

    `totales_ayer` es None cuando la consulta de ayer fallo entera (ver
    consultar_totales_ayer): en ese caso la columna "Total ayer" sale con "-" en vez de
    un 0 que se confundiria con "ayer no habia anticipos".
    """
    filas = []
    gran_total = Decimal("0")
    gran_total_ayer: Decimal | None = Decimal("0") if totales_ayer is not None else None

    for sociedad, partidas in agrupado.items():
        total = _total(partidas)
        gran_total += total

        total_ayer = totales_ayer.get(sociedad, Decimal("0")) if totales_ayer is not None else None
        if gran_total_ayer is not None and total_ayer is not None:
            gran_total_ayer += total_ayer

        filas.append(
            "<tr>"
            + _celda_sociedad(sociedad, nombres)
            + _celda(escape(_importe(total)), derecha=True, fuerte=True)
            + _celda(
                escape(_importe(total_ayer) if total_ayer is not None else "-"), derecha=True
            )
            + "</tr>"
        )

    encabezado = _encabezado(
        [
            ("Sociedad", False),
            (TITULO_ANTICIPOS, True),
            ("Total ayer", True),
        ]
    )
    return (
        f'<table width="100%" cellpadding="0" cellspacing="0" '
        f'style="border-collapse:collapse;border:1px solid {BORDE};border-radius:8px;'
        f'overflow:hidden;margin-bottom:8px;">'
        f"<thead>{encabezado}</thead>"
        f"<tbody>{''.join(filas)}"
        f"{_fila_total('Total general', [gran_total, gran_total_ayer], 1)}</tbody></table>"
    )


def _estilos_pdf() -> str:
    """
    Hoja de estilos que solo se aplica al PDF.

    El correo esta pensado para clientes de correo: tarjeta con sombra y ancho fijo. En
    papel eso estorba y roba ancho, asi que aqui se desmonta el marco y se anaden las
    cosas que un PDF necesita y un correo no: margenes de pagina, numeracion, y sobre
    todo repetir la fila de encabezado en cada hoja.
    """
    return f"""<style>
    @page {{
      size: A4 {PDF_ORIENTACION};
      margin: 14mm 12mm 16mm;
      @bottom-right {{
        content: "Pagina " counter(page) " de " counter(pages);
        font-family: "Liberation Sans", Arial, sans-serif;
        font-size: 8pt;
        color: #6b7280;
      }}
    }}
    /* Barlow y Segoe UI no existen en el contenedor. Liberation Sans es compatible en
       metricas con Arial, el ultimo recurso de la pila del correo, asi que el PDF sale
       con las mismas proporciones que se ven en el navegador. */
    body, td, th, div, p {{ font-family: "Liberation Sans", Arial, sans-serif !important; }}
    .lienzo {{ padding: 0 !important; }}
    .tarjeta {{
      width: 100% !important; max-width: none !important;
      border: 0 !important; border-radius: 0 !important;
    }}
    /* Sin esto, a partir de la segunda hoja las columnas quedan sin nombre. */
    thead {{ display: table-header-group; }}
    tr {{ break-inside: avoid; }}
    /* Que un titulo no se quede solo al final de una pagina, con su tabla en la siguiente. */
    .titulo-sociedad, .titulo-seccion {{ break-after: avoid; }}
    </style>"""


def construir_html(
    titulo: str,
    subtitulo: str,
    contenido: str,
    *,
    para_pdf: bool = False,
    aviso: str | None = None,
) -> str:
    estilos = _estilos_pdf() if para_pdf else ""
    # WeasyPrint no soporta box-shadow y avisa cada vez que la encuentra. En el PDF la
    # sombra se quita de todas formas, asi que no se emite: mejor no generar el aviso que
    # tener que silenciarlo y perder de vista los avisos que si importan.
    sombra = "" if para_pdf else "box-shadow:0 8px 24px rgba(15,23,42,.08);"
    bloque_aviso = (
        f'<tr><td style="padding:0 28px;">'
        f'<p style="margin:12px 0 0;padding:10px 12px;border-left:3px solid #a12626;'
        f'background:rgba(161,38,38,.06);font-size:12px;color:#7a1d1d;">'
        f"{escape(aviso)}</p></td></tr>"
        if aviso
        else ""
    )
    return f"""<!DOCTYPE html>
<html lang="es"><head><meta charset="UTF-8">{estilos}</head>
<body style="margin:0;padding:0;background:#ffffff;font-family:'Segoe UI',Arial,sans-serif;color:#111827;">
  <table class="lienzo" width="100%" cellpadding="0" cellspacing="0" style="background:#ffffff;padding:32px 16px;">
    <tr><td align="center">
      <table class="tarjeta" width="800" cellpadding="0" cellspacing="0"
             style="background:#ffffff;border-radius:12px;{sombra}
                    border:1px solid {BORDE};overflow:hidden;max-width:800px;width:100%;">
        <tr style="border-bottom:1px solid {BORDE};">
          <td style="padding:24px 28px;">
            <div style="font-family:Barlow,'Segoe UI',Arial,sans-serif;font-size:28px;font-weight:800;color:{AZUL};letter-spacing:-0.8px;">
              {escape(titulo)}
            </div>
            <p style="font-size:13px;color:#4b5563;margin:6px 0 0;">{escape(subtitulo)}</p>
          </td>
        </tr>
        {bloque_aviso}
        <tr><td style="padding:8px 28px 28px;">{contenido}</td></tr>
        <tr><td style="padding:0 28px 24px;">
          <p style="font-size:11px;color:#6b7280;margin:0;line-height:1.6;">
            <b>Anticipos a proveedores</b>: registrados en SAP como anticipo, en cuentas
            de activo. Importes en pesos mexicanos.
          </p>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body></html>"""


def generar_pdf(html: str) -> bytes | None:
    """
    Convierte a PDF el mismo HTML del correo, con WeasyPrint.

    Si falla devuelve None y el correo sale sin adjunto: el reporte vale mas que el
    adjunto, y un problema de tipografias o de librerias del sistema no deberia dejar a
    finanzas sin su dato del dia. Se registra el motivo en el log para poder arreglarlo.
    """
    try:
        # WeasyPrint registra en INFO cada paso y CADA PAGINA del documento. Con un
        # consolidado de quince paginas por diecisiete correos, eso son cientos de lineas
        # que ahogan los mensajes del proceso, que son los que sirven para diagnosticar.
        #
        # El nivel se sube ANTES del import, no despues: al importarse, WeasyPrint parsea
        # sus hojas de estilo por defecto y ya escribe en el log. Con el setLevel debajo
        # del import esas primeras lineas se colaban igual.
        logging.getLogger("weasyprint").setLevel(logging.WARNING)
        logging.getLogger("fontTools").setLevel(logging.WARNING)

        from weasyprint import HTML

        return HTML(string=html).write_pdf()
    except Exception as exc:
        logging.warning("No se pudo generar el PDF: %s", exc)
        return None


def _guardar_pdf_local(nombre: str, pdf: bytes) -> None:
    directorio = Path(os.environ.get("ANTICIPOS_DRY_RUN_DIR", "salida_dry_run"))
    try:
        directorio.mkdir(parents=True, exist_ok=True)
        destino = directorio / f"{nombre}.pdf"
        destino.write_bytes(pdf)
        logging.info("PDF de prueba en %s (%s KB)", destino, round(len(pdf) / 1024, 1))
    except OSError as exc:
        logging.warning("No se pudo escribir el PDF local de %s: %s", nombre, exc)


def _guardar_copia_local(nombre: str, html: str) -> None:
    """En dry run deja el HTML en disco para poder abrirlo en el navegador."""
    directorio = Path(os.environ.get("ANTICIPOS_DRY_RUN_DIR", "salida_dry_run"))
    try:
        directorio.mkdir(parents=True, exist_ok=True)
        destino = directorio / f"{nombre}.html"
        destino.write_text(html, encoding="utf-8")
        logging.info("HTML de prueba en %s", destino)
    except OSError as exc:
        # No es motivo para fallar: el dry run ya ha calculado y registrado todo. En
        # Cloud Run, ademas, el fichero se escribe pero muere con el contenedor: alli el
        # dry run sirve para validar el log, no para revisar el HTML.
        logging.warning("No se pudo escribir la copia local de %s: %s", nombre, exc)


def enviar_correo(
    asunto: str,
    html: str,
    destinatarios: list[str],
    nombre_copia: str,
    pdf: bytes | None = None,
    nombre_pdf: str = "",
) -> dict[str, Any]:
    remitente = os.environ.get("SENDGRID_FROM_EMAIL", "noreply@proan.com").strip()

    if _es_verdadero(os.environ.get("ANTICIPOS_EMAIL_DRY_RUN", "false")):
        _guardar_copia_local(nombre_copia, html)
        if pdf:
            _guardar_pdf_local(nombre_copia, pdf)
        return {
            "asunto": asunto,
            "cc": destinatarios,
            "estado": "dry_run",
            "adjunto": nombre_pdf if pdf else None,
            "mensaje": "Envio simulado por ANTICIPOS_EMAIL_DRY_RUN=true.",
        }

    api_key = os.environ.get("SENDGRID_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError(
            "SENDGRID_API_KEY no esta configurada. Definela en .env y vuelve a ejecutar "
            "deploy.sh: ejecutar el Cloud Run Job a mano usa la configuracion ya desplegada."
        )

    import base64

    import sendgrid
    from sendgrid.helpers.mail import (
        Attachment, Cc, Disposition, FileContent, FileName, FileType, Mail,
    )

    mensaje = Mail(
        from_email=remitente,
        to_emails=remitente,
        subject=asunto,
        html_content=html,
    )
    for destinatario in destinatarios:
        mensaje.add_cc(Cc(destinatario))

    if pdf:
        mensaje.attachment = Attachment(
            FileContent(base64.b64encode(pdf).decode()),
            FileName(nombre_pdf),
            FileType("application/pdf"),
            Disposition("attachment"),
        )

    respuesta = sendgrid.SendGridAPIClient(api_key).send(mensaje)
    return {
        "asunto": asunto,
        "cc": destinatarios,
        "estado": "enviado",
        "adjunto": nombre_pdf if pdf else None,
        "codigo": respuesta.status_code,
    }


def enviar_reportes(
    agrupado: dict[str, list[dict[str, Any]]],
    fecha_reporte,
    globales: list[str],
    por_sociedad: dict[str, list[str]],
    nombres: dict[str, str],
    totales_ayer: dict[str, Decimal] | None,
) -> list[dict[str, Any]]:
    fecha_texto = fecha_reporte.strftime("%d/%m/%Y")
    sufijo_fichero = fecha_reporte.strftime("%Y%m%d")
    resultados = []

    def preparar(titulo_sub: str, contenido: str, nombre: str) -> tuple[str, bytes | None, str]:
        """
        Devuelve el HTML del correo, el PDF y su nombre de fichero.

        El PDF se genera ANTES de construir el HTML del correo, no despues, porque si
        falla hay que poder avisarlo dentro del propio correo.
        """
        pdf = generar_pdf(
            construir_html("Reporte de anticipos", titulo_sub, contenido, para_pdf=True)
        )
        html = construir_html(
            "Reporte de anticipos",
            titulo_sub,
            contenido,
            aviso=None if pdf else AVISO_SIN_PDF,
        )
        return html, pdf, f"{nombre}_{sufijo_fichero}.pdf"

    # Un unico correo con todas las sociedades para quien las sigue todas.
    if globales:
        bloques = "".join(
            _bloque_sociedad(sociedad, filas_sociedad, nombres, totales_ayer)
            for sociedad, filas_sociedad in agrupado.items()
        )
        html, pdf, nombre_pdf = preparar(
            f"Todas las sociedades. Fecha de consulta {fecha_texto}.",
            _resumen_sociedades(agrupado, nombres, totales_ayer) + bloques,
            "anticipos_todas_las_sociedades",
        )
        resultados.append(
            enviar_correo(
                f"Anticipos - todas las sociedades - {fecha_texto}",
                html,
                globales,
                "anticipos_global",
                pdf=pdf,
                nombre_pdf=nombre_pdf,
            )
        )
    else:
        logging.warning("Sin destinatarios globales: no se envia el correo consolidado")

    # Un correo por sociedad.
    for sociedad, filas_sociedad in agrupado.items():
        destinatarios = por_sociedad.get(sociedad, [])
        if not destinatarios:
            logging.warning(
                "La sociedad %s no tiene destinatarios en por_sociedad: no se envia", sociedad
            )
            continue

        html, pdf, nombre_pdf = preparar(
            f"Sociedad {_etiqueta_sociedad(sociedad, nombres)}. "
            f"Fecha de consulta {fecha_texto}.",
            _bloque_sociedad(sociedad, filas_sociedad, nombres, totales_ayer),
            # El nombre del fichero se queda con el codigo: corto y sin caracteres raros.
            f"anticipos_{sociedad}",
        )
        resultados.append(
            enviar_correo(
                f"Anticipos {sociedad} - {fecha_texto}",
                html,
                destinatarios,
                f"anticipos_{sociedad.lower()}",
                pdf=pdf,
                nombre_pdf=nombre_pdf,
            )
        )

    return resultados


# --------------------------------------------------------------------------- #

def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    from google.cloud import bigquery

    sociedades = sociedades_objetivo()
    client = bigquery.Client(project=PROJECT_ID)

    logging.info("Comprobando frescura del espejo de BSIK")
    verificar_frescura(client)

    logging.info("Consultando anticipos de %s sociedades", len(sociedades))
    filas = consultar_anticipos(client, sociedades)
    agrupado = agrupar_por_sociedad(filas, sociedades)
    nombres = consultar_nombres_sociedad(client, sociedades)
    logging.info("Nombres de sociedad resueltos: %s de %s", len(nombres), len(sociedades))

    logging.info(
        "%s: %s filas por %s", TITULO_ANTICIPOS, len(filas), _importe(_total(filas))
    )

    ahora = datetime.now(ZONA_MEXICO)
    fecha_reporte = ahora.date()

    logging.info("Guardando la foto del dia en %s", DESTINO)
    asegurar_tabla(client)
    guardar_foto(client, filas, fecha_reporte, ahora)

    totales_ayer = consultar_totales_ayer(client, sociedades, fecha_reporte - timedelta(days=1))
    if totales_ayer is None:
        logging.warning("No se pudo obtener el total de ayer para el resumen consolidado")

    globales, por_sociedad, origen = resolver_destinatarios()
    logging.info(
        "Destinatarios desde %s: %s globales, %s sociedades con lista propia",
        origen,
        len(globales),
        len(por_sociedad),
    )

    resultados = enviar_reportes(
        agrupado, fecha_reporte, globales, por_sociedad, nombres, totales_ayer
    )
    for resultado in resultados:
        logging.info("Correo: %s", resultado)

    logging.info("Proceso completado: %s correos", len(resultados))


if __name__ == "__main__":
    main()
