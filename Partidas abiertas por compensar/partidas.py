"""
Reporte diario de partidas pendientes de compensar por sociedad.

Que es compensar
----------------
Compensar es casar dos o mas apuntes que deben anularse entre si. El caso tipico es
una factura y su pago: cuando SAP los empareja escribe en ambos el documento de
compensacion (AUGBL) y los dos SALEN de la tabla de partidas abiertas.

En cuentas de mayor esto se usa para las cuentas que funcionan por parejas: traspasos
entre bancos, cuentas puente, devengos de intereses, retenciones. Una partida que
sigue abierta es una pata sin su contraparte: o el movimiento no llego, o se registro
dos veces, o nadie las emparejo.

Por eso este reporte no es de saldos, es de TRABAJO PENDIENTE: cada linea es algo que
alguien tiene que perseguir. De ahi que lo importante sea la antiguedad.

De donde sale
-------------
D00_SANDBOX.bsis_real_time, espejo de BSIS: el indice de partidas ABIERTAS de cuentas
de mayor. Es el hermano de BSIK, que indexa por proveedor; este indexa por cuenta
contable.

Entran todas las clases de documento (BLART): antes solo se mostraba 'ZR' (traspasos y
movimientos de banco), pero el cliente quiere ver el resto tambien. BLART se muestra en
el reporte como columna Clase, para poder distinguirlas.

No hace falta filtrar por AUGBL: se comprobo que de las 1.487 filas de la tabla solo
una tiene documento de compensacion. El espejo no arrastra partidas ya compensadas.

El nombre de cada sociedad sale de D20_DIMENSION.dm_company (company_code ->
company_name), para que el correo diga "Sociedad PAN - Proteina Animal SA de CV" y no
solo el codigo. Ahi company_code es unico —87 filas, 87 codigos— asi que el cruce no
necesita deduplicar. La columna `company` de esa tabla esta vacia en las 87 filas.

Decisiones tomadas, con su motivo
---------------------------------
1. No se filtra por sufijo de cuenta.

   Las cuentas terminadas en 'E' son egresos y las terminadas en 'I' son ingresos.
   Entran las dos, y en las ZR no hay ninguna cuenta con otro sufijo, asi que filtrar
   no descartaria ruido: solo quitaria la mitad del reporte. El sufijo se usa para
   derivar la columna Tipo. Esta convencion solo se verifico para ZR: al entrar el
   resto de clases de documento, puede haber cuentas que no sigan el patron E/I y aun
   asi se clasifiquen como Egreso por defecto. Se deja asi a proposito.

2. Es un listado, no un motor de conciliacion.

   Se estudio si ZUONR (el campo de asignacion) permitia emparejar automaticamente las
   dos patas de cada operacion. No: de 182 asignaciones, NINGUNA tiene pata 'E' e 'I' a
   la vez dentro de la misma sociedad. Ignorando la sociedad aparecen dos, y son
   traspasos entre empresas del grupo. ZUONR es un campo libre: unas veces es una
   fecha, otras una referencia bancaria. Este analisis es de cuando el reporte solo
   cubria ZR; no se ha repetido tras ampliar a todas las clases de documento.

   Asi que se agrupa por cuenta y se listan las partidas, como el reporte manual.
   Emparejarlas es trabajo de la persona. Se ordena dentro de cada cuenta por
   antiguedad porque el valor esta en lo viejo, no en lo de ayer.

3. GJAHR forma parte de la clave.

   Hay un par de lineas que comparten sociedad, documento y posicion en ejercicios
   distintos. Sin GJAHR, un SELECT DISTINCT las colapsaria y una desapareceria en
   silencio.

4. Div. sale de GSBER.

   En las partidas ZR, GSBER (y WERKS, PRCTR, KOSTL) estaban vacios al 100%, por eso
   antes no habia columna de division. Ahora que entran todas las clases de documento
   se muestra GSBER como columna Div., pero no esta verificado que porcentaje de las
   otras clases lo traiga relleno: puede seguir saliendo en blanco para muchas filas.

5. No hay columna de moneda.

   DMBTR es el importe en moneda local, siempre pesos mexicanos. Hay tres documentos
   emitidos en USD, y el reporte manual muestra su importe en pesos con la etiqueta USD
   al lado, lo que induce a error. Se dice una vez en el pie del correo y se quita la
   columna.

6. Se aborta si el espejo esta caducado, con un umbral distinto al de anticipos.

   bsis_real_time se reescribe entera desde SAP, pero NO al mismo ritmo que bsik: BSIK y
   BSID se recargan cada dos horas, BSIS carga de madrugada y no se mueve el resto del
   dia. Por eso aqui el umbral son 20 horas y alli 6. El detalle esta en la docstring de
   verificar_frescura.

   Si el replicador se para, la tabla se queda con datos viejos sin avisar. Antes de
   enviar nada se comprueba la antiguedad de la ultima carga y el proceso falla, en vez
   de mandar un reporte caducado como si fuera del dia.

Persistencia
------------
Foto diaria en D60_REPORTING.Partidas_pendientes_evolucion, particionada por dia.

Cuando una partida se compensa DESAPARECE de BSIS, sin dejar marca. Sin esta tabla no
hay forma de saber cuanto tiempo estuvo abierta ni cuando se resolvio, ni de ver como
evoluciona la bolsa de pendientes.

La escritura usa el decorador de particion con WRITE_TRUNCATE, asi que reejecutar el
proceso el mismo dia reemplaza la foto entera, sin duplicar ni dejar restos.

Destinatarios
-------------
Documento Firestore lists/partidas_pendientes, con dos bloques:

- globales: direcciones que estan en todas las sociedades. Reciben UN unico correo con
  todas las sociedades juntas.
- por_sociedad: mapa sociedad -> correos, un correo por sociedad.

Si Firestore no esta disponible se cae a PARTIDAS_EMAIL_TO y luego a los destinatarios
por defecto, y en ese caso se envia SOLO el correo global: nunca se adivina quien debe
recibir los datos de una sociedad concreta.

Correo y PDF
------------
Cada bloque (resumen, seccion de sociedad, tabla de cuenta) tiene una sola definicion de
HTML, compartida entre correo y PDF: un cambio ahi nunca puede dejar al uno con una
columna que al otro le falte. Lo que si difiere es que bloques entran en cada uno:

- Correo por sociedad: el bloque de esa sociedad, igual en el cuerpo del correo y en el
  PDF adjunto.
- Correo consolidado: el cuerpo del correo lleva SOLO el resumen (con una nota de que el
  detalle esta en el adjunto). El PDF adjunto lleva el resumen y los 16 bloques
  completos. Se separo asi para no mandar un correo kilometrico a quien sigue las 16
  sociedades a la vez -- el PDF sigue teniendo todo, para quien lo necesite.

Grafico de evolucion
---------------------
Ademas del detalle de hoy, cada correo lleva un grafico de linea con los ultimos
EVOL_DIAS dias CON foto (consultar_evolucion_reciente): el importe neto total en el
consolidado (mas una rejilla con un mini-grafico por sociedad, cada uno a su propia
escala) y la serie propia en el correo por sociedad.

Se genera como PNG con matplotlib, no como SVG inline: es lo que se ve igual en el
cuerpo del correo (donde SVG inline no es fiable en todos los clientes, Outlook de
escritorio el primero) y en el PDF de WeasyPrint, con una sola imagen en vez de dos
definiciones que se puedan desincronizar.

El eje encuadra el rango real de los valores, sin forzar que el cero entre en la vista.
La linea de referencia en cero solo se dibuja si el cero cae dentro de ese rango -- ahi
si importa, porque marca un cruce real (el signo sigue al debe y al haber, asi que un
importe neto puede pasar de positivo a negativo).
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
ORIGEN_BSIS = f"{PROJECT_ID}.D00_SANDBOX.bsis_real_time"
ORIGEN_SOCIEDADES = f"{PROJECT_ID}.D20_DIMENSION.dm_company"
DESTINO = f"{PROJECT_ID}.D60_REPORTING.Partidas_pendientes_evolucion"

# Las 16 sociedades del reporte, en el orden de las columnas del Excel de correos.
# ADE queda fuera a proposito aunque tenga partidas abiertas: no esta en el Excel.
SOCIEDADES = (
    "PAN", "DBC", "ROMM", "PRA", "MPE", "MAL", "HEGP", "ISE",
    "PIN", "SAP", "ABP", "AME", "CCP", "PAL", "PAT", "BAG",
)

# A partir de aqui una partida se marca en el correo. No es una regla contable, es un
# umbral para que lo viejo salte a la vista en un listado largo.
DIAS_PARA_AVISAR = 90

# Cuantos dias con foto entran en el grafico de evolucion (ver consultar_evolucion_reciente).
EVOL_DIAS = 7

ZONA_MEXICO = ZoneInfo("America/Mexico_City")
SIN_CUENTA = "(sin cuenta)"
SIN_NOMBRE_SOCIEDAD = "(sin nombre en la maestra)"
SIN_TEXTO = "—"
DESTINATARIOS_POR_DEFECTO = ("pcoma@quantrue.com",)

FIRESTORE_DATABASE_ID = os.environ.get("FIRESTORE_DATABASE_ID", "proan-lista-mails").strip()
FIRESTORE_LISTS_COLLECTION = os.environ.get("FIRESTORE_LISTS_COLLECTION", "lists").strip()
PARTIDAS_LIST_ID = os.environ.get("PARTIDAS_LIST_ID", "partidas_pendientes").strip()

AZUL = "#2A2B5F"
BORDE = "#d9dee5"
AVISO = "#a12626"

# El PDF adjunto se genera con el MISMO HTML del correo mas una hoja de estilos de
# impresion. Es lo que evita que el correo y el adjunto se separen con el tiempo: hay una
# sola definicion del layout, no dos.
#
# Horizontal, al contrario que anticipos: son nueve columnas y una de ellas es texto libre.
# En vertical el texto de los apuntes saldria partido en tres lineas.
PDF_ORIENTACION = "landscape"
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
    crudo = os.environ.get("PARTIDAS_ONLY_SOCIEDADES", "").strip()
    if not crudo:
        return SOCIEDADES

    pedidas = [s.strip().upper() for s in crudo.split(",") if s.strip()]
    desconocidas = [s for s in pedidas if s not in SOCIEDADES]
    if desconocidas:
        raise ValueError(
            f"PARTIDAS_ONLY_SOCIEDADES contiene sociedades que no son del reporte: "
            f"{', '.join(desconocidas)}"
        )

    seleccion = tuple(s for s in SOCIEDADES if s in pedidas)
    logging.warning("Ejecucion limitada a %s por PARTIDAS_ONLY_SOCIEDADES", ", ".join(seleccion))
    return seleccion


# --------------------------------------------------------------------------- #
# Origen de datos
# --------------------------------------------------------------------------- #

def verificar_frescura(client) -> datetime:
    """
    Comprueba que el espejo de BSIS no esta caducado. Falla si lo esta.

    El umbral por defecto son 20 horas, no 6 como en el reporte de anticipos, porque
    BSIS y BSIK NO se recargan al mismo ritmo. BSIK y BSID se reescriben cada dos horas
    (a los minutos :06 y :02); BSIS se cargo a las 06:57 UTC, o sea las 00:57 de Mexico,
    y no se movio en el resto del dia. Minuto distinto, pipeline distinto.

    Con eso, a las 10:00 de Mexico el dato de BSIS tiene unas 9 horas de vida, asi que un
    umbral de 6 lo rechazaria siempre. 20 horas funciona igual si la carga es diaria o si
    fuera mas frecuente, y sigue cazando un dia entero sin carga: a la hora del reporte
    eso serian unas 33 horas.
    """
    horas_maximas = int(os.environ.get("PARTIDAS_MAX_ANTIGUEDAD_HORAS", "20"))

    consulta = f"SELECT MAX(_ingested_at) AS ultima_carga FROM `{ORIGEN_BSIS}`"
    fila = next(client.query(consulta).result(), None)
    ultima_carga = fila["ultima_carga"] if fila is not None else None
    if ultima_carga is None:
        raise RuntimeError(f"La tabla {ORIGEN_BSIS} esta vacia: no hay nada que reportar.")

    antiguedad = datetime.now(timezone.utc) - ultima_carga
    logging.info(
        "Ultima carga del espejo: %s (hace %.1f horas)",
        ultima_carga.isoformat(),
        antiguedad.total_seconds() / 3600,
    )

    if antiguedad > timedelta(hours=horas_maximas):
        raise RuntimeError(
            f"El espejo {ORIGEN_BSIS} tiene {antiguedad.total_seconds() / 3600:.1f} horas de "
            f"antiguedad, mas del maximo de {horas_maximas}. El replicador de SAP puede estar "
            f"parado. No se envia el reporte para no dar por bueno un dato caducado."
        )

    return ultima_carga


def consultar_partidas(client, sociedades: tuple[str, ...]) -> list[dict[str, Any]]:
    """
    Una fila por partida abierta, de cualquier clase de documento.

    Las fechas vienen como texto YYYYMMDD, y se leen con SAFE.PARSE_DATE porque SAP
    admite valores como '00000000' en fechas no informadas: con PARSE_DATE normal, una
    sola fila mal formada tumbaria la consulta entera.
    """
    from google.cloud import bigquery

    consulta = f"""
        SELECT
          BUKRS AS sociedad,
          IFNULL(HKONT, '') AS cuenta,
          IF(ENDS_WITH(IFNULL(HKONT, ''), 'I'), 'Ingreso', 'Egreso') AS tipo,
          IFNULL(BLART, '') AS clase,
          GJAHR AS ejercicio,
          BELNR AS documento,
          BUZEI AS posicion,
          IFNULL(GSBER, '') AS division,
          IFNULL(ZUONR, '') AS asignacion,
          SAFE.PARSE_DATE('%Y%m%d', BUDAT) AS fecha_contabilizacion,
          DATE_DIFF(
            CURRENT_DATE('America/Mexico_City'),
            SAFE.PARSE_DATE('%Y%m%d', BUDAT),
            DAY
          ) AS dias_abierta,
          ROUND(
            CASE WHEN SHKZG = 'S'
                 THEN  CAST(DMBTR AS NUMERIC)
                 ELSE -CAST(DMBTR AS NUMERIC)
            END, 2
          ) AS importe,
          IFNULL(SGTXT, '') AS texto
        FROM `{ORIGEN_BSIS}`
        WHERE BUKRS IN UNNEST(@sociedades)
        ORDER BY sociedad, cuenta, dias_abierta DESC, documento, posicion
    """
    configuracion = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ArrayQueryParameter("sociedades", "STRING", list(sociedades)),
        ]
    )

    filas = [dict(fila) for fila in client.query(consulta, job_config=configuracion).result()]

    sin_fecha = sum(1 for f in filas if f["fecha_contabilizacion"] is None)
    if sin_fecha:
        logging.warning("%s partidas con fecha de contabilizacion no interpretable", sin_fecha)

    return filas


def consultar_nombres_sociedad(client, sociedades: tuple[str, ...]) -> dict[str, str]:
    """
    Codigo de sociedad -> razon social, desde el maestro de empresas.

    No hace falta deduplicar: company_code es unico en dm_company, 87 filas y 87 codigos
    distintos. La columna `company` de esa tabla esta vacia en las 87 filas; la buena es
    company_name.

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


def consultar_evolucion_reciente(
    client, sociedades: tuple[str, ...], dias: int = EVOL_DIAS
) -> tuple[list[Any], dict[str, list[Decimal]]] | tuple[None, None]:
    """
    Ultimos `dias` CON foto (no `dias` de calendario) por sociedad, para el grafico de
    evolucion del correo.

    Se piden `dias + 3` de margen de calendario y se recorta a los ultimos `dias` que
    de verdad tienen fila: asi un domingo sin foto (el Job corre de lunes a sabado) o un
    dia con el run caido no cuentan como un punto mas, y la ventana sigue teniendo
    `dias` puntos reales en vez de encogerse.

    Una sociedad sin fila un dia que SI tiene foto es 0 ese dia (sin partidas
    pendientes), igual que en el resto del reporte. Si la consulta entera falla se
    devuelve (None, None) y el correo sale sin la seccion de evolucion: es un
    complemento, no un dato que valga la pena bloquear el envio por el.
    """
    from google.cloud import bigquery

    consulta = f"""
        SELECT fecha_reporte, sociedad, SUM(importe) AS total
        FROM `{DESTINO}`
        WHERE fecha_reporte >= DATE_SUB(CURRENT_DATE('America/Mexico_City'), INTERVAL @margen DAY)
          AND sociedad IN UNNEST(@sociedades)
        GROUP BY fecha_reporte, sociedad
    """
    configuracion = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("margen", "INT64", dias + 3),
            bigquery.ArrayQueryParameter("sociedades", "STRING", list(sociedades)),
        ]
    )

    try:
        por_dia: dict[Any, dict[str, Decimal]] = {}
        for fila in client.query(consulta, job_config=configuracion).result():
            por_dia.setdefault(fila["fecha_reporte"], {})[fila["sociedad"]] = fila["total"]
    except Exception as exc:
        logging.warning("No se pudo leer la evolucion reciente: %s", exc)
        return None, None

    fechas = sorted(por_dia.keys())[-dias:]
    series = {
        cod: [por_dia[fecha].get(cod, Decimal("0")) for fecha in fechas]
        for cod in sociedades
    }
    return fechas, series


def _etiqueta_sociedad(codigo: str, nombres: dict[str, str]) -> str:
    """'PAN - Proteina Animal SA de CV', o solo el codigo si no hay nombre."""
    if not nombres:
        # El maestro entero fallo. Mejor el codigo a secas que repetir dieciseis veces
        # que falta el nombre.
        return codigo
    return f"{codigo} - {nombres.get(codigo, SIN_NOMBRE_SOCIEDAD)}"


def agrupar(
    filas: list[dict[str, Any]], sociedades: tuple[str, ...]
) -> dict[str, dict[str, list[dict[str, Any]]]]:
    """
    Sociedad -> cuenta -> partidas, respetando el orden de la consulta.

    Se crea una entrada por sociedad pedida aunque no tenga partidas, para que el correo
    de una sociedad vacia no sea un caso especial.
    """
    agrupado: dict[str, dict[str, list[dict[str, Any]]]] = {s: {} for s in sociedades}
    for fila in filas:
        cuentas = agrupado[fila["sociedad"]]
        cuentas.setdefault(fila["cuenta"], []).append(fila)
    return agrupado


def _total(filas: list[dict[str, Any]]) -> Decimal:
    return sum((fila["importe"] for fila in filas), Decimal("0"))


def _partidas_de(cuentas: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    return [fila for partidas in cuentas.values() for fila in partidas]


def _dias_max(filas: list[dict[str, Any]]) -> int:
    dias = [f["dias_abierta"] for f in filas if f["dias_abierta"] is not None]
    return max(dias) if dias else 0


# --------------------------------------------------------------------------- #
# Persistencia
# --------------------------------------------------------------------------- #

def _esquema_destino():
    from google.cloud import bigquery

    return [
        bigquery.SchemaField("fecha_reporte", "DATE", mode="REQUIRED"),
        bigquery.SchemaField("sociedad", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("cuenta", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("tipo", "STRING", mode="REQUIRED"),
        # NULLABLE porque una columna anadida con ALTER TABLE no puede ser REQUIRED.
        bigquery.SchemaField("clase_documento", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("ejercicio", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("documento", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("posicion", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("division", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("asignacion", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("fecha_contabilizacion", "DATE", mode="NULLABLE"),
        bigquery.SchemaField("dias_abierta", "INT64", mode="NULLABLE"),
        bigquery.SchemaField("importe", "NUMERIC", mode="REQUIRED"),
        bigquery.SchemaField("texto", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("actualizado_en", "DATETIME", mode="REQUIRED"),
    ]


def asegurar_tabla(client) -> None:
    from google.cloud import bigquery

    tabla = bigquery.Table(DESTINO, schema=_esquema_destino())
    tabla.time_partitioning = bigquery.TimePartitioning(
        type_=bigquery.TimePartitioningType.DAY, field="fecha_reporte"
    )
    tabla.clustering_fields = ["sociedad", "cuenta"]
    client.create_table(tabla, exists_ok=True)
    # Para las tablas creadas antes de que existieran estas columnas.
    client.query(
        f"ALTER TABLE `{DESTINO}` ADD COLUMN IF NOT EXISTS clase_documento STRING"
    ).result()
    client.query(
        f"ALTER TABLE `{DESTINO}` ADD COLUMN IF NOT EXISTS division STRING"
    ).result()


def guardar_foto(
    client, filas: list[dict[str, Any]], fecha_reporte, actualizado_en: datetime
) -> None:
    """
    Reemplaza la foto del dia completa.

    Con el decorador de particion (tabla$YYYYMMDD) y WRITE_TRUNCATE, que sustituye solo
    ese dia de forma atomica. Reejecutar el proceso el mismo dia deja el resultado de la
    ultima ejecucion: una partida que se compenso a media manana tiene que desaparecer
    de la foto, no quedarse ahi.
    """
    from google.cloud import bigquery

    fecha_iso = fecha_reporte.isoformat()
    marca = actualizado_en.strftime("%Y-%m-%dT%H:%M:%S")

    if not filas:
        logging.warning("Ninguna partida pendiente hoy: se vacia la particion %s", fecha_iso)
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
            "cuenta": fila["cuenta"],
            "tipo": fila["tipo"],
            "clase_documento": fila["clase"],
            "ejercicio": fila["ejercicio"],
            "documento": fila["documento"],
            "posicion": fila["posicion"],
            "division": fila["division"],
            "asignacion": fila["asignacion"],
            "fecha_contabilizacion": (
                fila["fecha_contabilizacion"].isoformat()
                if fila["fecha_contabilizacion"] is not None
                else None
            ),
            "dias_abierta": fila["dias_abierta"],
            "importe": str(fila["importe"]),
            "texto": fila["texto"],
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
    """Acepta 'alguien@proan.com' y 'Nombre Apellido <alguien@proan.com>'."""
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
        client.collection(FIRESTORE_LISTS_COLLECTION).document(PARTIDAS_LIST_ID).get()
    )
    if not documento.exists:
        logging.warning(
            "No existe el documento Firestore %s/%s en la base %s",
            FIRESTORE_LISTS_COLLECTION,
            PARTIDAS_LIST_ID,
            FIRESTORE_DATABASE_ID,
        )
        return [], {}

    datos = documento.to_dict() or {}
    if not datos.get("enabled", True):
        logging.warning("La lista Firestore %s esta deshabilitada", PARTIDAS_LIST_ID)
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
        logging.warning("El campo por_sociedad de %s no es un mapa", PARTIDAS_LIST_ID)

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
        [c for c in os.environ.get("PARTIDAS_EMAIL_TO", "").split(",") if c.strip()]
    )
    if del_entorno:
        logging.warning(
            "Sin destinatarios en Firestore: se usa PARTIDAS_EMAIL_TO y solo se envia el "
            "correo global."
        )
        return del_entorno, {}, "env"

    logging.warning(
        "Sin destinatarios en Firestore ni en entorno: se usan los de por defecto y solo "
        "se envia el correo global."
    )
    return list(DESTINATARIOS_POR_DEFECTO), {}, "default"


# --------------------------------------------------------------------------- #
# Correo
# --------------------------------------------------------------------------- #

def _importe(valor: Decimal) -> str:
    return f"{valor:,.2f}"


def _celda(contenido: str, *, derecha: bool = False, fuerte: bool = False,
           color: str | None = None) -> str:
    alineacion = "right" if derecha else "left"
    peso = "700" if fuerte else "400"
    tono = color or (AZUL if fuerte else "#374151")
    return (
        f'<td style="padding:8px 10px;text-align:{alineacion};font-size:12px;'
        f'font-weight:{peso};color:{tono};border-bottom:1px solid {BORDE};">{contenido}</td>'
    )


def _encabezado(titulos: list[tuple[str, bool]]) -> str:
    celdas = "".join(
        f'<th style="padding:9px 10px;text-align:{"right" if derecha else "left"};'
        f'font-family:Barlow,\'Segoe UI\',Arial,sans-serif;font-size:10px;font-weight:700;'
        f'color:#ffffff;text-transform:uppercase;letter-spacing:.5px;">{escape(titulo)}</th>'
        for titulo, derecha in titulos
    )
    return f'<tr style="background:{AZUL};">{celdas}</tr>'


def _fila_total(etiqueta: str, valor: Decimal, columnas_previas: int) -> str:
    return (
        "<tr>"
        f'<td colspan="{columnas_previas}" style="padding:9px 10px;text-align:right;'
        f'font-size:11px;font-weight:700;color:{AZUL};text-transform:uppercase;'
        f'letter-spacing:.5px;">{escape(etiqueta)}</td>'
        f'<td style="padding:9px 10px;text-align:right;font-size:13px;font-weight:800;'
        f'color:{AZUL};">{escape(_importe(valor))}</td>'
        "</tr>"
    )


def _tabla_cuenta(partidas: list[dict[str, Any]]) -> str:
    cuerpo = []
    for fila in partidas:
        dias = fila["dias_abierta"]
        viejo = dias is not None and dias >= DIAS_PARA_AVISAR
        fecha = (
            fila["fecha_contabilizacion"].strftime("%d/%m/%Y")
            if fila["fecha_contabilizacion"] is not None
            else "—"
        )
        cuerpo.append(
            "<tr>"
            + _celda(escape(fecha))
            + _celda(
                escape("—" if dias is None else str(dias)),
                derecha=True,
                fuerte=viejo,
                color=AVISO if viejo else None,
            )
            + _celda(escape(fila["tipo"]))
            + _celda(escape(fila["clase"] or "—"))
            + _celda(escape(fila["documento"]), fuerte=True)
            + _celda(escape(fila["division"] or "—"))
            + _celda(escape(fila["asignacion"] or "—"))
            + _celda(escape(fila["texto"] or SIN_TEXTO))
            + _celda(escape(_importe(fila["importe"])), derecha=True, fuerte=True)
            + "</tr>"
        )

    encabezado = _encabezado([
        ("Fecha", False), ("Dias", True), ("Tipo", False), ("Clase", False),
        ("Documento", False), ("Div.", False), ("Asignacion", False), ("Texto", False),
        ("Importe", True),
    ])
    return (
        f'<table width="100%" cellpadding="0" cellspacing="0" '
        f'style="border-collapse:collapse;border:1px solid {BORDE};border-radius:8px;'
        f'overflow:hidden;">'
        f"<thead>{encabezado}</thead>"
        f"<tbody>{''.join(cuerpo)}"
        f"{_fila_total('Subtotal', _total(partidas), 8)}</tbody></table>"
    )


def _bloque_sociedad(
    sociedad: str,
    cuentas: dict[str, list[dict[str, Any]]],
    nombres: dict[str, str],
) -> str:
    partes = [
        f'<p class="titulo-sociedad" style="font-family:Barlow,\'Segoe UI\',Arial,sans-serif;'
        f'font-size:16px;color:{AZUL};font-weight:800;margin:28px 0 2px;">'
        f"Sociedad {escape(_etiqueta_sociedad(sociedad, nombres))}</p>"
    ]

    if not cuentas:
        partes.append(
            '<p style="font-size:13px;color:#4b5563;margin:4px 0 8px;">'
            "Sin partidas pendientes de compensar.</p>"
        )
        return "".join(partes)

    todas = _partidas_de(cuentas)
    dias = _dias_max(todas)
    resumen = f"{len(todas)} {'partida' if len(todas) == 1 else 'partidas'}"
    if dias >= DIAS_PARA_AVISAR:
        resumen += f", la mas antigua de hace {dias} dias"
    partes.append(
        f'<p style="font-size:12px;color:#6b7280;margin:0 0 6px;">{escape(resumen)}</p>'
    )

    for cuenta in sorted(cuentas):
        partes.append(
            f'<p class="titulo-seccion" style="font-size:13px;color:{AZUL};font-weight:700;'
            f'margin:16px 0 8px;">Cuenta {escape(cuenta or SIN_CUENTA)}</p>'
        )
        partes.append(_tabla_cuenta(cuentas[cuenta]))

    if len(cuentas) > 1:
        partes.append(
            f'<p style="font-size:13px;color:{AZUL};font-weight:800;margin:12px 0 0;'
            f'text-align:right;">Total {escape(sociedad)}: '
            f'{escape(_importe(_total(todas)))}</p>'
        )

    return "".join(partes)


def _celda_sociedad(codigo: str, nombres: dict[str, str]) -> str:
    """Codigo en negrita y razon social al lado, atenuada, en una sola celda.

    En una sola celda y no en dos columnas: los nombres rondan los 23 caracteres y una
    columna propia estrecharia las de importes y dias, que son las que se leen."""
    nombre = "" if not nombres else nombres.get(codigo, SIN_NOMBRE_SOCIEDAD)
    extra = (
        f' <span style="font-weight:400;color:#6b7280;">{escape(nombre)}</span>'
        if nombre
        else ""
    )
    return _celda(f"{escape(codigo)}{extra}", fuerte=True)


def _resumen_sociedades(
    agrupado: dict[str, dict[str, list[dict[str, Any]]]],
    nombres: dict[str, str],
) -> str:
    """Tabla de una linea por sociedad, solo para el correo global."""
    filas = []
    gran_total = Decimal("0")
    for sociedad, cuentas in agrupado.items():
        todas = _partidas_de(cuentas)
        total = _total(todas)
        gran_total += total
        dias = _dias_max(todas)
        viejo = dias >= DIAS_PARA_AVISAR
        filas.append(
            "<tr>"
            + _celda_sociedad(sociedad, nombres)
            + _celda(str(len(todas)), derecha=True)
            + _celda(str(len(cuentas)), derecha=True)
            + _celda(
                escape("—" if not todas else str(dias)),
                derecha=True,
                fuerte=viejo,
                color=AVISO if viejo else None,
            )
            + _celda(escape(_importe(total)), derecha=True, fuerte=True)
            + "</tr>"
        )

    encabezado = _encabezado([
        ("Sociedad", False), ("Partidas", True), ("Cuentas", True),
        ("Dias de la mas antigua", True), ("Importe neto", True),
    ])
    return (
        f'<table width="100%" cellpadding="0" cellspacing="0" '
        f'style="border-collapse:collapse;border:1px solid {BORDE};border-radius:8px;'
        f'overflow:hidden;margin-bottom:8px;">'
        f"<thead>{encabezado}</thead>"
        f"<tbody>{''.join(filas)}"
        f"{_fila_total('Total general', gran_total, 4)}</tbody></table>"
    )


def _grafico_evolucion_png(valores: list[Decimal], *, ancho: int, alto: int, mini: bool) -> bytes:
    """
    PNG de linea + area con la evolucion (sin ejes, sin fechas: esas van en el HTML de
    alrededor, como texto normal en vez de dentro de la imagen).

    Se genera como imagen, no como SVG inline, para que se vea igual en el cuerpo del
    correo y en el PDF: el SVG inline no es fiable en todos los clientes de correo
    (Outlook de escritorio el primero), y una sola imagen generada una vez evita que
    las dos representaciones se desincronicen.
    """
    import io

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    escala = 2  # exporta al doble de resolucion; el <img> fija el tamano real en pantalla
    dpi = 100
    fig, ax = plt.subplots(figsize=(ancho * escala / dpi, alto * escala / dpi), dpi=dpi)

    y = [float(v) for v in valores]
    x = list(range(len(y)))

    # El eje encuadra el RANGO real de los datos, no se fuerza a incluir el cero: una
    # serie que se mueve poco en terminos relativos tiene que verse como una linea que
    # sube y baja, no como un hilo aplastado contra el techo de un eje que llega hasta
    # 0. Se rellena hasta el propio suelo del grafico (no hasta el cero) por la misma
    # razon -- eso solo pinta peso visual bajo la linea, no afirma nada sobre la
    # distancia a cero.
    minimo, maximo = min(y), max(y)
    rango = (maximo - minimo) or (abs(maximo) * 0.1) or 1.0
    colchon = rango * 0.14
    y_min, y_max = minimo - colchon, maximo + colchon

    ax.fill_between(x, y, y_min, color=AZUL, alpha=0.12 if mini else 0.09, linewidth=0)
    ax.plot(x, y, color=AZUL, linewidth=2.6 if mini else 3.2,
             solid_capstyle="round", solid_joinstyle="round")
    ax.plot(x[-1], y[-1], "o", color=AZUL, markersize=5.5 if mini else 7)

    # La linea de referencia en cero solo tiene sentido si el cero cae dentro de lo que
    # se ve: es para marcar un cruce real (el signo sigue al debe y al haber, asi que un
    # subtotal puede pasar de positivo a negativo), no una decoracion fija.
    if y_min < 0 < y_max:
        ax.axhline(0, color="#9aa0b4", linewidth=1, linestyle=(0, (3, 3)))

    ax.set_xlim(-0.15, len(x) - 1 + 0.15)
    ax.set_ylim(y_min, y_max)

    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.set_xticks([])
    ax.set_yticks([])
    ax.margins(0)
    fig.subplots_adjust(left=0.01, right=0.99, top=0.95, bottom=0.05)

    buf = io.BytesIO()
    fig.savefig(buf, format="png", transparent=True, dpi=dpi)
    plt.close(fig)
    return buf.getvalue()


def _img_grafico(png: bytes, ancho: int, alto: int, alt: str) -> str:
    import base64

    b64 = base64.b64encode(png).decode()
    return (
        f'<img src="data:image/png;base64,{b64}" width="{ancho}" height="{alto}" '
        f'alt="{escape(alt)}" style="display:block;max-width:100%;height:auto;">'
    )


def _rango_fechas(fechas: list[Any]) -> str:
    return f"{fechas[0].strftime('%d/%m')} - {fechas[-1].strftime('%d/%m')}"


def _bloque_evolucion(titulo: str, fechas: list[Any], valores: list[Decimal]) -> str:
    """
    Grafico de linea de una sola serie: el importe neto total, o el de una sociedad.

    Si hay menos de dos puntos (arranque del historico, o toda la ventana caida por un
    fallo de consultar_evolucion_reciente) no se dibuja nada: una linea con un solo
    punto no cuenta nada que el numero de al lado ya no diga.
    """
    if len(fechas) < 2:
        return ""

    png = _grafico_evolucion_png(valores, ancho=820, alto=180, mini=False)
    img = _img_grafico(png, 820, 180, f"Evolucion — {titulo}")
    return (
        f'<p class="titulo-seccion" style="font-size:13px;color:{AZUL};font-weight:700;'
        f'margin:20px 0 8px;">Evolucion — {escape(titulo)} '
        f'<span style="font-weight:400;color:#6b7280;font-size:11px;">'
        f"(ultimos {len(fechas)} dias con dato)</span></p>"
        f"{img}"
        f'<p style="font-size:11px;color:#6b7280;margin:4px 0 0;">{escape(_rango_fechas(fechas))}</p>'
    )


def _grid_evolucion(
    fechas: list[Any], series: dict[str, list[Decimal]], sociedades: tuple[str, ...] | list[str]
) -> str:
    """
    Rejilla de un mini-grafico por sociedad, cada uno a su propia escala.

    Una tabla HTML, no CSS grid/flex: es lo que funciona igual en todos los clientes de
    correo. Una sociedad sin ninguna partida en toda la ventana se salta, igual que hoy
    sale "Sin partidas pendientes de compensar" en el detalle.
    """
    if len(fechas) < 2:
        return ""

    paneles = []
    for cod in sociedades:
        valores = series.get(cod)
        if not valores or all(v == 0 for v in valores):
            continue
        png = _grafico_evolucion_png(valores, ancho=190, alto=56, mini=True)
        img = _img_grafico(png, 190, 56, f"Evolucion {cod}")
        paneles.append(
            f'<td style="padding:5px;width:25%;">'
            f'<div style="border:1px solid {BORDE};border-radius:7px;padding:8px 10px 6px;">'
            f'<div style="display:flex;justify-content:space-between;align-items:baseline;'
            f'font-family:Barlow,\'Segoe UI\',Arial,sans-serif;">'
            f'<b style="font-size:13px;color:{AZUL};">{escape(cod)}</b>'
            f'<span style="font-size:10.5px;color:#6b7280;">{escape(_importe(valores[-1]))}</span>'
            f"</div>{img}</div></td>"
        )

    if not paneles:
        return ""

    filas_html = []
    por_fila = 4
    for i in range(0, len(paneles), por_fila):
        fila = paneles[i:i + por_fila]
        while len(fila) < por_fila:
            fila.append('<td style="padding:5px;width:25%;"></td>')
        filas_html.append("<tr>" + "".join(fila) + "</tr>")

    return (
        f'<p class="titulo-seccion" style="font-size:13px;color:{AZUL};font-weight:700;'
        f'margin:20px 0 8px;">Evolucion por sociedad '
        f'<span style="font-weight:400;color:#6b7280;font-size:11px;">'
        f"(ultimos {len(fechas)} dias con dato)</span></p>"
        f'<table width="100%" cellpadding="0" cellspacing="0">{"".join(filas_html)}</table>'
    )


def _estilos_pdf() -> str:
    """
    Hoja de estilos que solo se aplica al PDF.

    El correo esta pensado para clientes de correo: tarjeta con sombra y ancho fijo. En
    papel eso estorba y roba ancho, asi que aqui se desmonta el marco y se anaden las
    cosas que un PDF necesita y un correo no: margenes de pagina, numeracion, y sobre
    todo repetir la fila de encabezado en cada hoja, que en un listado de cien filas es
    la diferencia entre poder leerlo y no.
    """
    return f"""<style>
    @page {{
      size: A4 {PDF_ORIENTACION};
      margin: 12mm 10mm 14mm;
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
        f'<p style="margin:12px 0 0;padding:10px 12px;border-left:3px solid {AVISO};'
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
      <table class="tarjeta" width="900" cellpadding="0" cellspacing="0"
             style="background:#ffffff;border-radius:12px;{sombra}
                    border:1px solid {BORDE};overflow:hidden;max-width:900px;width:100%;">
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
            Apuntes de cuentas de mayor que siguen sin compensar: cada linea es una pata
            sin su contraparte. Se listan todas las clases de documento, de mas antigua a
            mas reciente. Las de {DIAS_PARA_AVISAR} dias o mas van
            destacadas. El signo sigue al debe y al haber, asi que un subtotal puede salir
            negativo. <b>Todos los importes en pesos mexicanos.</b>
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
        # consolidado de varias decenas de paginas por diecisiete correos, eso son cientos
        # de lineas que ahogan los mensajes del proceso, que son los que sirven para
        # diagnosticar.
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
    directorio = Path(os.environ.get("PARTIDAS_DRY_RUN_DIR", "salida_dry_run"))
    try:
        directorio.mkdir(parents=True, exist_ok=True)
        destino = directorio / f"{nombre}.pdf"
        destino.write_bytes(pdf)
        logging.info("PDF de prueba en %s (%s KB)", destino, round(len(pdf) / 1024, 1))
    except OSError as exc:
        logging.warning("No se pudo escribir el PDF local de %s: %s", nombre, exc)


def _guardar_copia_local(nombre: str, html: str) -> None:
    directorio = Path(os.environ.get("PARTIDAS_DRY_RUN_DIR", "salida_dry_run"))
    try:
        directorio.mkdir(parents=True, exist_ok=True)
        destino = directorio / f"{nombre}.html"
        destino.write_text(html, encoding="utf-8")
        logging.info("HTML de prueba en %s", destino)
    except OSError as exc:
        # En Cloud Run el fichero se escribe pero muere con el contenedor: alli el dry
        # run sirve para validar el log, no para revisar el HTML.
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

    if _es_verdadero(os.environ.get("PARTIDAS_EMAIL_DRY_RUN", "false")):
        _guardar_copia_local(nombre_copia, html)
        if pdf:
            _guardar_pdf_local(nombre_copia, pdf)
        return {
            "asunto": asunto,
            "cc": destinatarios,
            "estado": "dry_run",
            "adjunto": nombre_pdf if pdf else None,
            "mensaje": "Envio simulado por PARTIDAS_EMAIL_DRY_RUN=true.",
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
    agrupado: dict[str, dict[str, list[dict[str, Any]]]],
    fecha_reporte,
    globales: list[str],
    por_sociedad: dict[str, list[str]],
    nombres: dict[str, str],
    fechas_evol: list[Any] | None,
    series_evol: dict[str, list[Decimal]] | None,
) -> list[dict[str, Any]]:
    fecha_texto = fecha_reporte.strftime("%d/%m/%Y")
    sufijo_fichero = fecha_reporte.strftime("%Y%m%d")
    titulo = "Partidas pendientes de compensar"
    resultados = []

    def preparar(
        titulo_sub: str, contenido: str, nombre: str, *, contenido_html: str | None = None
    ) -> tuple[str, bytes | None, str]:
        """
        Devuelve el HTML del correo, el PDF y su nombre de fichero.

        El PDF se genera ANTES de construir el HTML del correo, no despues, porque si
        falla hay que poder avisarlo dentro del propio correo.

        `contenido_html`, si se pasa, sustituye a `contenido` solo en el cuerpo del
        correo: el PDF sigue saliendo de `contenido`. Se usa en el consolidado, donde el
        correo lleva solo el resumen y el PDF lleva el detalle completo (ver
        enviar_reportes). Sin `contenido_html` ambos salen del mismo `contenido`, como en
        el correo por sociedad.
        """
        pdf = generar_pdf(construir_html(titulo, titulo_sub, contenido, para_pdf=True))
        html = construir_html(
            titulo,
            titulo_sub,
            contenido_html if contenido_html is not None else contenido,
            aviso=None if pdf else AVISO_SIN_PDF,
        )
        return html, pdf, f"{nombre}_{sufijo_fichero}.pdf"

    # El cuerpo del correo lleva solo el resumen; el detalle completo por sociedad va
    # unicamente en el PDF adjunto, para no mandar un correo kilometrico a quien sigue
    # las 16 a la vez.
    if globales:
        resumen = _resumen_sociedades(agrupado, nombres)

        evolucion = ""
        if fechas_evol and series_evol:
            total_evol = [
                sum((series_evol[cod][i] for cod in agrupado), Decimal("0"))
                for i in range(len(fechas_evol))
            ]
            evolucion = _bloque_evolucion("total", fechas_evol, total_evol) + _grid_evolucion(
                fechas_evol, series_evol, list(agrupado.keys())
            )

        bloques = "".join(
            _bloque_sociedad(sociedad, cuentas, nombres)
            for sociedad, cuentas in agrupado.items()
        )
        nota_detalle = (
            '<p style="font-size:12px;color:#6b7280;margin:12px 0 0;">'
            "El detalle por sociedad va en el PDF adjunto.</p>"
        )
        html, pdf, nombre_pdf = preparar(
            f"Todas las sociedades. Fecha de consulta {fecha_texto}.",
            resumen + evolucion + bloques,
            "partidas_pendientes_todas_las_sociedades",
            contenido_html=resumen + evolucion + nota_detalle,
        )
        resultados.append(
            enviar_correo(
                f"{titulo} - todas las sociedades - {fecha_texto}",
                html,
                globales,
                "partidas_global",
                pdf=pdf,
                nombre_pdf=nombre_pdf,
            )
        )
    else:
        logging.warning("Sin destinatarios globales: no se envia el correo consolidado")

    for sociedad, cuentas in agrupado.items():
        destinatarios = por_sociedad.get(sociedad, [])
        if not destinatarios:
            logging.warning(
                "La sociedad %s no tiene destinatarios en por_sociedad: no se envia", sociedad
            )
            continue

        evolucion_ind = ""
        if fechas_evol and series_evol and sociedad in series_evol:
            evolucion_ind = _bloque_evolucion(sociedad, fechas_evol, series_evol[sociedad])

        html, pdf, nombre_pdf = preparar(
            f"Sociedad {_etiqueta_sociedad(sociedad, nombres)}. "
            f"Fecha de consulta {fecha_texto}.",
            _bloque_sociedad(sociedad, cuentas, nombres) + evolucion_ind,
            # El nombre del fichero se queda con el codigo: corto y sin caracteres raros.
            f"partidas_pendientes_{sociedad}",
        )
        resultados.append(
            enviar_correo(
                f"Partidas pendientes {sociedad} - {fecha_texto}",
                html,
                destinatarios,
                f"partidas_{sociedad.lower()}",
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

    logging.info("Comprobando frescura del espejo de BSIS")
    verificar_frescura(client)

    logging.info("Consultando partidas de %s sociedades", len(sociedades))
    filas = consultar_partidas(client, sociedades)
    agrupado = agrupar(filas, sociedades)
    nombres = consultar_nombres_sociedad(client, sociedades)
    logging.info("Nombres de sociedad resueltos: %s de %s", len(nombres), len(sociedades))

    viejas = sum(
        1 for f in filas
        if f["dias_abierta"] is not None and f["dias_abierta"] >= DIAS_PARA_AVISAR
    )
    logging.info(
        "%s partidas por %s, en %s sociedades con datos. %s con %s dias o mas",
        len(filas),
        _importe(_total(filas)),
        sum(1 for cuentas in agrupado.values() if cuentas),
        viejas,
        DIAS_PARA_AVISAR,
    )

    ahora = datetime.now(ZONA_MEXICO)
    fecha_reporte = ahora.date()

    logging.info("Guardando la foto del dia en %s", DESTINO)
    asegurar_tabla(client)
    guardar_foto(client, filas, fecha_reporte, ahora)

    fechas_evol, series_evol = consultar_evolucion_reciente(client, sociedades)
    if fechas_evol is None:
        logging.warning("No se pudo obtener la evolucion reciente: el correo sale sin grafico")
    else:
        logging.info("Evolucion reciente: %s dias con dato", len(fechas_evol))

    globales, por_sociedad, origen = resolver_destinatarios()
    logging.info(
        "Destinatarios desde %s: %s globales, %s sociedades con lista propia",
        origen,
        len(globales),
        len(por_sociedad),
    )

    resultados = enviar_reportes(
        agrupado, fecha_reporte, globales, por_sociedad, nombres, fechas_evol, series_evol
    )
    for resultado in resultados:
        logging.info("Correo: %s", resultado)

    logging.info("Proceso completado: %s correos", len(resultados))


if __name__ == "__main__":
    main()
