"""
Reporte diario de anticipos a proveedores por sociedad.

Que se considera un anticipo
----------------------------
Dos cosas distintas, y el reporte incluye las dos en secciones separadas:

1. ANTICIPOS A PROVEEDORES (UMSKZ = 'A'). Operaciones en cuenta especial que alguien
   registro en SAP declarandolas como anticipo, contabilizadas en cuentas de activo
   (10801xx, 0000140110). Son los anticipos canonicos.

2. SALDOS DEUDORES EN CUENTAS DE PROVEEDOR (UMSKZ vacio). Partidas normales de acreedor
   cuyo saldo neto sale positivo: se ha pagado al proveedor mas de lo que se le debia.
   Anticipos de hecho, aunque nadie los declarara como tal.

En los dos casos el calculo es el mismo: saldo neto de las partidas abiertas agrupadas
por sociedad + indicador + cuenta + proveedor, con el signo que marca SHKZG ('S' debe
suma, 'H' haber resta), quedandose con los positivos.

Decisiones tomadas, con su motivo
---------------------------------
1. Entran los dos tipos, en secciones separadas del correo.

   El reporte manual de SAP solo mostraba los saldos deudores. Los UMSKZ = 'A' son varias
   veces mas importe, y hay sociedades sin ningun pago de mas que si tienen anticipos
   declarados: dejarlos fuera daba una foto incompleta.

   No se suman en un unico total para que la cifra del reporte de siempre siga siendo
   reconocible en su propia seccion.

2. Se excluyen UMSKZ = 'F' y 'H'.

   'F' es una SOLICITUD de anticipo: un apunte estadistico para planificar pagos, no
   dinero movido. Sumarla a un saldo real es contar dos veces. 'H' son otros indicadores
   especiales, ajenos a este reporte.

3. UMSKZ forma parte del GROUP BY.

   Es lo que impide que un anticipo formal se sume con su propia solicitud: 'A' y 'F'
   comparten cuenta de mayor, asi que agrupar solo por cuenta las mezclaria. Se comprobo
   sobre una foto de la tabla que pasaria en 42 grupos. Con UMSKZ en el GROUP BY el
   problema no puede darse, independientemente de las cuentas que use contabilidad.

4. No se filtra por cuenta de mayor.

   El anticipo lo define el signo del saldo, no la cuenta. Las cuentas que aparecen en un
   reporte concreto son las que tenian saldo deudor ese dia en esa sociedad, no una lista
   cerrada. La cuenta se muestra como columna informativa.

5. El nombre del proveedor sale de D20_DIMENSION.dm_vendors, no de LFA1.

   dm_vendors cubre el 100% de los proveedores de BSIK y tiene un nombre de tabla
   estable. LFA1 vive en snapshots con la fecha en el nombre (proan_LFA1_20260728), que
   obligaria a construir el nombre de tabla en cada ejecucion.

   dm_vendors tiene una fila por direccion, no por proveedor: 25.147 filas para 23.155
   proveedores. Por eso se deduplica antes de cruzar. Sin ese GROUP BY el cruce
   multiplicaria filas de anticipo e inflaria los totales del correo.

6. DMBTR se convierte a NUMERIC antes de sumar.

   En la tabla espejo DMBTR es FLOAT. Sumar importes en coma flotante arrastra error;
   NUMERIC es aritmetica decimal exacta, que es lo que corresponde a dinero.

7. Se aborta si el espejo esta caducado.

   bsik_real_time no la carga el Airflow del DWH: es un espejo que un replicador
   externo reescribe entera cada dos horas (todas las filas comparten marca de
   _ingested_at). Si ese replicador se para, la tabla se queda con datos viejos sin
   avisar. Antes de enviar nada se comprueba la antiguedad de la ultima carga y el
   proceso falla en vez de mandar un reporte caducado como si fuera del dia.

Persistencia
------------
Se guarda una foto diaria en D60_REPORTING.Anticipos_evolucion, particionada por dia.

Es la unica historia que existe: BSIK solo contiene partidas ABIERTAS, cuando un
anticipo se compensa la fila desaparece, el espejo se reescribe cada dos horas y
bsak_real_time (donde SAP guardaria las compensadas) esta vacia en BigQuery. Sin esta
tabla no hay forma de saber que un anticipo existio ni cuanto tiempo estuvo abierto.

La escritura usa el decorador de particion con WRITE_TRUNCATE, asi que reejecutar el
proceso el mismo dia reemplaza la foto del dia entera, sin duplicar ni dejar restos.

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
DESTINO = f"{PROJECT_ID}.D60_REPORTING.Anticipos_evolucion"

# Las 16 sociedades del reporte, en el orden de las columnas del Excel de correos.
SOCIEDADES = (
    "PAN", "DBC", "ROMM", "PRA", "MPE", "MAL", "HEGP", "ISE",
    "PIN", "SAP", "ABP", "AME", "CCP", "PAL", "PAT", "BAG",
)

# Los dos tipos de anticipo, en el orden en que aparecen en el correo. El primero es el
# anticipo declarado en SAP; el segundo, el pago de mas en una cuenta de proveedor.
TIPO_ANTICIPO = "anticipo"
TIPO_SALDO_DEUDOR = "saldo_deudor"
TIPOS = (
    (
        TIPO_ANTICIPO,
        "Anticipos a proveedores",
        "Registrados en SAP como anticipo, en cuentas de activo.",
    ),
    (
        TIPO_SALDO_DEUDOR,
        "Saldos deudores en cuentas de proveedor",
        "Sin indicador especial: se ha pagado mas de lo que se debia.",
    ),
)
ETIQUETAS_TIPO = {clave: etiqueta for clave, etiqueta, _ in TIPOS}

ZONA_MEXICO = ZoneInfo("America/Mexico_City")
SIN_NOMBRE = "(sin nombre en la maestra)"
SIN_CUENTA = "(sin cuenta)"
DESTINATARIOS_POR_DEFECTO = ("pcoma@quantrue.com",)

FIRESTORE_DATABASE_ID = os.environ.get("FIRESTORE_DATABASE_ID", "proan-lista-mails").strip()
FIRESTORE_LISTS_COLLECTION = os.environ.get("FIRESTORE_LISTS_COLLECTION", "lists").strip()
ANTICIPOS_LIST_ID = os.environ.get("ANTICIPOS_LIST_ID", "anticipos").strip()

# Colores corporativos, los mismos que el correo de cambio de divisa.
AZUL = "#2A2B5F"
BORDE = "#d9dee5"


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
    Saldos deudores por sociedad, tipo, cuenta y proveedor, con el nombre del proveedor.

    UMSKZ esta en el GROUP BY, no solo en el WHERE: es lo que garantiza que un anticipo
    formal ('A') nunca se sume con su propia solicitud ('F'), que comparte cuenta.
    """
    from google.cloud import bigquery

    consulta = f"""
        WITH saldos AS (
          SELECT
            BUKRS AS sociedad,
            IFNULL(UMSKZ, '') AS umskz,
            IFNULL(HKONT, '') AS cuenta,
            LTRIM(LIFNR, '0') AS proveedor,
            ROUND(SUM(
              CASE WHEN SHKZG = 'S'
                   THEN CAST(DMBTR AS NUMERIC)
                   ELSE -CAST(DMBTR AS NUMERIC)
              END
            ), 2) AS saldo_neto
          FROM `{ORIGEN_BSIK}`
          WHERE IFNULL(UMSKZ, '') IN ('', 'A')
            AND BUKRS IN UNNEST(@sociedades)
          GROUP BY sociedad, umskz, cuenta, proveedor
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
          IF(s.umskz = 'A', @tipo_anticipo, @tipo_saldo_deudor) AS tipo,
          s.cuenta,
          s.proveedor,
          IFNULL(p.razon_social, @sin_nombre) AS nombre_proveedor,
          s.saldo_neto
        FROM saldos s
        LEFT JOIN proveedores p USING (proveedor)
        WHERE s.saldo_neto > 0
        ORDER BY s.sociedad, tipo, s.saldo_neto DESC
    """
    configuracion = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ArrayQueryParameter("sociedades", "STRING", list(sociedades)),
            bigquery.ScalarQueryParameter("tipo_anticipo", "STRING", TIPO_ANTICIPO),
            bigquery.ScalarQueryParameter("tipo_saldo_deudor", "STRING", TIPO_SALDO_DEUDOR),
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


def agrupar_por_sociedad(
    filas: list[dict[str, Any]], sociedades: tuple[str, ...]
) -> dict[str, dict[str, list[dict[str, Any]]]]:
    """
    Una entrada por sociedad pedida, y dentro una por tipo, aunque esten vacias.

    Asi el correo de una sociedad sin nada no es un caso especial: se recorre igual y
    sale con su mensaje de "sin anticipos".
    """
    agrupado = {
        sociedad: {clave: [] for clave, _, _ in TIPOS} for sociedad in sociedades
    }
    for fila in filas:
        agrupado[fila["sociedad"]][fila["tipo"]].append(fila)
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


def _fila_total(etiqueta: str, valor: Decimal, columnas_previas: int) -> str:
    return (
        "<tr>"
        f'<td colspan="{columnas_previas}" style="padding:10px 12px;text-align:right;'
        f'font-size:11px;font-weight:700;color:{AZUL};text-transform:uppercase;'
        f'letter-spacing:.5px;">{escape(etiqueta)}</td>'
        f'<td style="padding:10px 12px;text-align:right;font-size:13px;font-weight:800;'
        f'color:{AZUL};">{escape(_importe(valor))}</td>'
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
        f"{_fila_total(etiqueta_total, _total(filas), 3)}</tbody></table>"
    )


def _bloque_sociedad(sociedad: str, por_tipo: dict[str, list[dict[str, Any]]]) -> str:
    """Bloque de una sociedad: una seccion por tipo de anticipo, y el total combinado."""
    partes = [
        f'<p style="font-family:Barlow,\'Segoe UI\',Arial,sans-serif;font-size:16px;'
        f'color:{AZUL};font-weight:800;margin:28px 0 2px;">Sociedad {escape(sociedad)}</p>'
    ]

    con_datos = [(clave, etiqueta, nota) for clave, etiqueta, nota in TIPOS if por_tipo[clave]]

    if not con_datos:
        partes.append(
            '<p style="font-size:13px;color:#4b5563;margin:4px 0 8px;">'
            "Sin anticipos pendientes.</p>"
        )
        return "".join(partes)

    for clave, etiqueta, nota in con_datos:
        partes.append(
            f'<p style="font-size:13px;color:{AZUL};font-weight:700;margin:16px 0 2px;">'
            f"{escape(etiqueta)}</p>"
            f'<p style="font-size:11px;color:#6b7280;margin:0 0 8px;">{escape(nota)}</p>'
        )
        partes.append(_tabla_detalle(por_tipo[clave], f"Total {etiqueta.lower()}"))

    # El total combinado solo aporta si hay dos secciones que sumar.
    if len(con_datos) > 1:
        combinado = sum((_total(por_tipo[clave]) for clave, _, _ in con_datos), Decimal("0"))
        partes.append(
            f'<p style="font-size:13px;color:{AZUL};font-weight:800;margin:12px 0 0;'
            f'text-align:right;">Total {escape(sociedad)}: {escape(_importe(combinado))}</p>'
        )

    return "".join(partes)


def _resumen_sociedades(agrupado: dict[str, dict[str, list[dict[str, Any]]]]) -> str:
    """Tabla de totales por sociedad y tipo, solo para el correo global."""
    filas = []
    totales_generales = {clave: Decimal("0") for clave, _, _ in TIPOS}

    for sociedad, por_tipo in agrupado.items():
        totales = {clave: _total(por_tipo[clave]) for clave, _, _ in TIPOS}
        for clave, valor in totales.items():
            totales_generales[clave] += valor
        combinado = sum(totales.values(), Decimal("0"))
        filas.append(
            "<tr>"
            + _celda(escape(sociedad), fuerte=True)
            + _celda(escape(_importe(totales[TIPO_ANTICIPO])), derecha=True)
            + _celda(escape(_importe(totales[TIPO_SALDO_DEUDOR])), derecha=True)
            + _celda(escape(_importe(combinado)), derecha=True, fuerte=True)
            + "</tr>"
        )

    gran_total = sum(totales_generales.values(), Decimal("0"))
    encabezado = _encabezado(
        [
            ("Sociedad", False),
            ("Anticipos a proveedores", True),
            ("Saldos deudores", True),
            ("Total", True),
        ]
    )
    return (
        f'<table width="100%" cellpadding="0" cellspacing="0" '
        f'style="border-collapse:collapse;border:1px solid {BORDE};border-radius:8px;'
        f'overflow:hidden;margin-bottom:8px;">'
        f"<thead>{encabezado}</thead>"
        f"<tbody>{''.join(filas)}"
        f"{_fila_total('Total general', gran_total, 3)}</tbody></table>"
    )


def construir_html(titulo: str, subtitulo: str, contenido: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="es"><head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#ffffff;font-family:'Segoe UI',Arial,sans-serif;color:#111827;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#ffffff;padding:32px 16px;">
    <tr><td align="center">
      <table width="800" cellpadding="0" cellspacing="0"
             style="background:#ffffff;border-radius:12px;box-shadow:0 8px 24px rgba(15,23,42,.08);
                    border:1px solid {BORDE};overflow:hidden;max-width:800px;width:100%;">
        <tr style="border-bottom:1px solid {BORDE};">
          <td style="padding:24px 28px;">
            <div style="font-family:Barlow,'Segoe UI',Arial,sans-serif;font-size:28px;font-weight:800;color:{AZUL};letter-spacing:-0.8px;">
              {escape(titulo)}
            </div>
            <p style="font-size:13px;color:#4b5563;margin:6px 0 0;">{escape(subtitulo)}</p>
          </td>
        </tr>
        <tr><td style="padding:8px 28px 28px;">{contenido}</td></tr>
        <tr><td style="padding:0 28px 24px;">
          <p style="font-size:11px;color:#6b7280;margin:0;line-height:1.6;">
            Se reportan dos conceptos. <b>Anticipos a proveedores</b>: registrados en SAP
            como anticipo, en cuentas de activo. <b>Saldos deudores en cuentas de
            proveedor</b>: importe pagado por encima de lo que se debia, sin indicador
            especial. Importes en pesos mexicanos.
          </p>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body></html>"""


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
    asunto: str, html: str, destinatarios: list[str], nombre_copia: str
) -> dict[str, Any]:
    remitente = os.environ.get("SENDGRID_FROM_EMAIL", "noreply@proan.com").strip()

    if _es_verdadero(os.environ.get("ANTICIPOS_EMAIL_DRY_RUN", "false")):
        _guardar_copia_local(nombre_copia, html)
        return {
            "asunto": asunto,
            "cc": destinatarios,
            "estado": "dry_run",
            "mensaje": "Envio simulado por ANTICIPOS_EMAIL_DRY_RUN=true.",
        }

    api_key = os.environ.get("SENDGRID_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError(
            "SENDGRID_API_KEY no esta configurada. Definela en .env y vuelve a ejecutar "
            "deploy.sh: ejecutar el Cloud Run Job a mano usa la configuracion ya desplegada."
        )

    import sendgrid
    from sendgrid.helpers.mail import Cc, Mail

    mensaje = Mail(
        from_email=remitente,
        to_emails=remitente,
        subject=asunto,
        html_content=html,
    )
    for destinatario in destinatarios:
        mensaje.add_cc(Cc(destinatario))

    respuesta = sendgrid.SendGridAPIClient(api_key).send(mensaje)
    return {
        "asunto": asunto,
        "cc": destinatarios,
        "estado": "enviado",
        "codigo": respuesta.status_code,
    }


def enviar_reportes(
    agrupado: dict[str, dict[str, list[dict[str, Any]]]],
    fecha_reporte,
    globales: list[str],
    por_sociedad: dict[str, list[str]],
) -> list[dict[str, Any]]:
    fecha_texto = fecha_reporte.strftime("%d/%m/%Y")
    resultados = []

    # Un unico correo con todas las sociedades para quien las sigue todas.
    if globales:
        bloques = "".join(
            _bloque_sociedad(sociedad, por_tipo) for sociedad, por_tipo in agrupado.items()
        )
        html = construir_html(
            "Reporte de anticipos",
            f"Todas las sociedades. Fecha de consulta {fecha_texto}.",
            _resumen_sociedades(agrupado) + bloques,
        )
        resultados.append(
            enviar_correo(
                f"Anticipos - todas las sociedades - {fecha_texto}",
                html,
                globales,
                "anticipos_global",
            )
        )
    else:
        logging.warning("Sin destinatarios globales: no se envia el correo consolidado")

    # Un correo por sociedad.
    for sociedad, por_tipo in agrupado.items():
        destinatarios = por_sociedad.get(sociedad, [])
        if not destinatarios:
            logging.warning(
                "La sociedad %s no tiene destinatarios en por_sociedad: no se envia", sociedad
            )
            continue

        html = construir_html(
            "Reporte de anticipos",
            f"Sociedad {sociedad}. Fecha de consulta {fecha_texto}.",
            _bloque_sociedad(sociedad, por_tipo),
        )
        resultados.append(
            enviar_correo(
                f"Anticipos {sociedad} - {fecha_texto}",
                html,
                destinatarios,
                f"anticipos_{sociedad.lower()}",
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

    for clave, etiqueta, _ in TIPOS:
        del_tipo = [f for f in filas if f["tipo"] == clave]
        logging.info("%s: %s filas por %s", etiqueta, len(del_tipo), _importe(_total(del_tipo)))
    logging.info("Total: %s filas por %s", len(filas), _importe(_total(filas)))

    ahora = datetime.now(ZONA_MEXICO)
    fecha_reporte = ahora.date()

    logging.info("Guardando la foto del dia en %s", DESTINO)
    asegurar_tabla(client)
    guardar_foto(client, filas, fecha_reporte, ahora)

    globales, por_sociedad, origen = resolver_destinatarios()
    logging.info(
        "Destinatarios desde %s: %s globales, %s sociedades con lista propia",
        origen,
        len(globales),
        len(por_sociedad),
    )

    resultados = enviar_reportes(agrupado, fecha_reporte, globales, por_sociedad)
    for resultado in resultados:
        logging.info("Correo: %s", resultado)

    logging.info("Proceso completado: %s correos", len(resultados))


if __name__ == "__main__":
    main()
