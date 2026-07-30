"""
Reporte diario de anticipos a proveedores por sociedad.

Que es un anticipo aqui
-----------------------
El reporte que se hacia a mano en SAP (reportesEspeciales > reportePartidasPendientes)
lista, por sociedad, los proveedores con SALDO DEUDOR en partidas abiertas: proveedores
a los que se ha pagado mas de lo que se les debe. Eso es lo que este proceso reproduce.

El calculo es el saldo neto de las partidas abiertas de acreedores agrupadas por
sociedad + cuenta de mayor + proveedor, con el signo que marca SHKZG ('S' debe suma,
'H' haber resta), y se queda solo con los saldos positivos.

Decisiones tomadas, con su motivo
---------------------------------
1. Se filtra UMSKZ vacio, es decir solo partidas normales de proveedor.

   SAP tiene un segundo concepto de anticipo: las operaciones en cuenta especial,
   UMSKZ = 'A' (anticipo formal, en cuentas de activo 1080102/1080103) y UMSKZ = 'F'
   (solicitud de anticipo, que es un apunte estadistico y no un saldo real). El reporte
   manual NO los incluye, y este proceso tampoco, para dar el mismo numero que hoy
   circula por finanzas.

   Si contabilidad decide que deben entrar, es anadir una seccion, no rehacer el
   proceso. Ojo al hacerlo: 'A' y 'F' comparten cuenta de mayor, asi que agrupar sin
   distinguir UMSKZ sumaria un anticipo con su propia solicitud y contaria doble.

2. No se filtra por cuenta de mayor.

   El reporte manual muestra 2010102/2010103/2010104, pero esas son simplemente las
   cuentas donde caen los saldos deudores hoy. Filtrar por lista dejaria fuera saldos
   legitimos en otras cuentas y obligaria a tocar el codigo cada vez que contabilidad
   abra una cuenta nueva. Se filtra por signo y la cuenta se muestra como columna.

3. El nombre del proveedor sale de D20_DIMENSION.dm_vendors, no de LFA1.

   dm_vendors cubre el 100% de los proveedores de BSIK y tiene un nombre de tabla
   estable. LFA1 vive en snapshots con la fecha en el nombre (proan_LFA1_20260728),
   que obligaria a construir el nombre de tabla en cada ejecucion.

   dm_vendors tiene una fila por direccion, no por proveedor: 25.147 filas para 23.155
   proveedores. Por eso se deduplica antes de cruzar. Sin ese GROUP BY el cruce
   multiplicaria filas de anticipo e inflaria los totales del correo.

4. DMBTR se convierte a NUMERIC antes de sumar.

   En la tabla espejo DMBTR es FLOAT. Sumar importes en coma flotante arrastra error;
   NUMERIC es aritmetica decimal exacta, que es lo que corresponde a dinero.

5. Se aborta si el espejo esta caducado.

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
Documento Firestore lists/anticipos, con dos bloques declarados de forma explicita:

- globales: reciben UN correo con las 16 sociedades.
- por_sociedad: mapa sociedad -> correos, un correo por sociedad.

Se declara en vez de deducirse. La alternativa era mirar quien aparece en las 16
sociedades y mandarle uno solo, pero entonces el dia que alguien sale de una sociedad
su comportamiento cambiaria en silencio de un correo a quince.

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
    """Saldos deudores por sociedad, cuenta y proveedor, con el nombre del proveedor."""
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
          WHERE IFNULL(UMSKZ, '') = ''
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
          s.cuenta,
          s.proveedor,
          IFNULL(p.razon_social, @sin_nombre) AS nombre_proveedor,
          s.saldo_neto
        FROM saldos s
        LEFT JOIN proveedores p USING (proveedor)
        WHERE s.saldo_neto > 0
        ORDER BY s.sociedad, s.saldo_neto DESC
    """
    configuracion = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ArrayQueryParameter("sociedades", "STRING", list(sociedades)),
            bigquery.ScalarQueryParameter("sin_nombre", "STRING", SIN_NOMBRE),
        ]
    )

    filas = [
        {
            "sociedad": fila["sociedad"],
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
) -> dict[str, list[dict[str, Any]]]:
    """Una entrada por sociedad pedida, aunque no tenga anticipos."""
    agrupado: dict[str, list[dict[str, Any]]] = {s: [] for s in sociedades}
    for fila in filas:
        agrupado[fila["sociedad"]].append(fila)
    return agrupado


# --------------------------------------------------------------------------- #
# Persistencia
# --------------------------------------------------------------------------- #

def _esquema_destino():
    from google.cloud import bigquery

    return [
        bigquery.SchemaField("fecha_reporte", "DATE", mode="REQUIRED"),
        bigquery.SchemaField("sociedad", "STRING", mode="REQUIRED"),
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


def _bloque_sociedad(sociedad: str, filas: list[dict[str, Any]]) -> str:
    """Un bloque de correo por sociedad: titulo, tabla y total."""
    titulo = (
        f'<p style="font-family:Barlow,\'Segoe UI\',Arial,sans-serif;font-size:15px;'
        f'color:{AZUL};font-weight:700;margin:24px 0 8px;">Sociedad {escape(sociedad)}</p>'
    )

    if not filas:
        return titulo + (
            '<p style="font-size:13px;color:#4b5563;margin:0 0 8px;">'
            "Sin anticipos pendientes.</p>"
        )

    encabezados = ["Cuenta", "Proveedor", "Nombre", "Saldo"]
    celdas_encabezado = "".join(
        f'<th style="padding:9px 12px;text-align:{"right" if h == "Saldo" else "left"};'
        f'font-family:Barlow,\'Segoe UI\',Arial,sans-serif;font-size:10px;font-weight:700;'
        f'color:#ffffff;text-transform:uppercase;letter-spacing:.5px;">{h}</th>'
        for h in encabezados
    )

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

    total = sum((fila["saldo_neto"] for fila in filas), Decimal("0"))
    pie = (
        "<tr>"
        f'<td colspan="3" style="padding:10px 12px;text-align:right;font-size:11px;'
        f'font-weight:700;color:{AZUL};text-transform:uppercase;letter-spacing:.5px;">'
        f"Total {escape(sociedad)}</td>"
        f'<td style="padding:10px 12px;text-align:right;font-size:13px;font-weight:800;'
        f'color:{AZUL};">{escape(_importe(total))}</td>'
        "</tr>"
    )

    return titulo + (
        f'<table width="100%" cellpadding="0" cellspacing="0" '
        f'style="border-collapse:collapse;border:1px solid {BORDE};border-radius:8px;'
        f'overflow:hidden;">'
        f'<thead><tr style="background:{AZUL};">{celdas_encabezado}</tr></thead>'
        f"<tbody>{''.join(cuerpo)}{pie}</tbody></table>"
    )


def _resumen_sociedades(agrupado: dict[str, list[dict[str, Any]]]) -> str:
    """Tabla de totales por sociedad, solo para el correo global."""
    filas = []
    gran_total = Decimal("0")
    for sociedad, anticipos in agrupado.items():
        total = sum((f["saldo_neto"] for f in anticipos), Decimal("0"))
        gran_total += total
        filas.append(
            "<tr>"
            + _celda(escape(sociedad), fuerte=True)
            + _celda(str(len(anticipos)), derecha=True)
            + _celda(escape(_importe(total)), derecha=True, fuerte=True)
            + "</tr>"
        )

    pie = (
        "<tr>"
        f'<td colspan="2" style="padding:10px 12px;text-align:right;font-size:11px;'
        f'font-weight:700;color:{AZUL};text-transform:uppercase;letter-spacing:.5px;">'
        f"Total general</td>"
        f'<td style="padding:10px 12px;text-align:right;font-size:13px;font-weight:800;'
        f'color:{AZUL};">{escape(_importe(gran_total))}</td>'
        "</tr>"
    )

    encabezados = ["Sociedad", "Anticipos", "Saldo total"]
    celdas_encabezado = "".join(
        f'<th style="padding:9px 12px;text-align:{"left" if h == "Sociedad" else "right"};'
        f'font-family:Barlow,\'Segoe UI\',Arial,sans-serif;font-size:10px;font-weight:700;'
        f'color:#ffffff;text-transform:uppercase;letter-spacing:.5px;">{h}</th>'
        for h in encabezados
    )

    return (
        f'<table width="100%" cellpadding="0" cellspacing="0" '
        f'style="border-collapse:collapse;border:1px solid {BORDE};border-radius:8px;'
        f'overflow:hidden;margin-bottom:8px;">'
        f'<thead><tr style="background:{AZUL};">{celdas_encabezado}</tr></thead>'
        f"<tbody>{''.join(filas)}{pie}</tbody></table>"
    )


def construir_html(titulo: str, subtitulo: str, contenido: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="es"><head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#ffffff;font-family:'Segoe UI',Arial,sans-serif;color:#111827;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#ffffff;padding:32px 16px;">
    <tr><td align="center">
      <table width="760" cellpadding="0" cellspacing="0"
             style="background:#ffffff;border-radius:12px;box-shadow:0 8px 24px rgba(15,23,42,.08);
                    border:1px solid {BORDE};overflow:hidden;max-width:760px;width:100%;">
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
            Anticipo: saldo deudor de un proveedor en partidas abiertas, es decir importe
            pagado por encima de lo que se le debe. Importes en pesos mexicanos.
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
        # En Cloud Run el sistema de ficheros es de solo lectura fuera de /tmp. No es
        # motivo para fallar: el dry run ya ha calculado y registrado todo.
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
    agrupado: dict[str, list[dict[str, Any]]],
    fecha_reporte,
    globales: list[str],
    por_sociedad: dict[str, list[str]],
) -> list[dict[str, Any]]:
    fecha_texto = fecha_reporte.strftime("%d/%m/%Y")
    resultados = []

    # Un unico correo con las 16 sociedades para quien las sigue todas.
    if globales:
        bloques = "".join(
            _bloque_sociedad(sociedad, filas) for sociedad, filas in agrupado.items()
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
    for sociedad, filas in agrupado.items():
        destinatarios = por_sociedad.get(sociedad, [])
        if not destinatarios:
            logging.warning(
                "La sociedad %s no tiene destinatarios en por_sociedad: no se envia", sociedad
            )
            continue

        html = construir_html(
            "Reporte de anticipos",
            f"Sociedad {sociedad}. Fecha de consulta {fecha_texto}.",
            _bloque_sociedad(sociedad, filas),
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
    total = sum((f["saldo_neto"] for f in filas), Decimal("0"))
    logging.info("%s anticipos por un total de %s", len(filas), _importe(total))

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
