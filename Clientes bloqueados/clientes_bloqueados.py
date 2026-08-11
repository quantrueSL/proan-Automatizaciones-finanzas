"""
Reporte diario de clientes en riesgo de bloqueo de credito, por sociedad.

Que es un bloqueo de credito
-----------------------------
Cuando un cliente acumula facturas vencidas, SAP puede cortarle el credito: mientras
este bloqueado no se le puede facturar ni entregar mercancia nueva. El indicador vive en
la maestra de clientes, KNA1.AUFSD = '01'.

Hay clientes que nunca se bloquean aunque deban, porque su clave de grupo (KNA1.KONZS)
los declara exentos: 'GRUPO' (empresas del propio grupo Proan) o 'AUTO'/'ADMON' (otro
tipo de excepcion administrativa). KONZS tambien se usa para clasificar clientes por
zona o sucursal (hay mas de 90 valores distintos, la mayoria nombres de plaza), asi que
solo esos tres valores concretos importan para el bloqueo.

Con eso, cada cliente cae en una de cinco categorias, calculadas ya en el origen:

1. bloqueado          - AUFSD = '01' y no esta en un grupo exento. Credito cortado hoy.
2. bloqueo_esperado    - Vencido hace mas de un dia, no esta en grupo exento, pero SAP
                         todavia no lo bloqueo. Deberia estar en el caso 1 y no esta.
3. proximo_bloqueo     - Acaba de vencer (0 o 1 dias) y tiene alguna factura vencida.
                         Al borde de caer en el caso 2.
4. no_bloqueado_grupo  - KONZS = 'GRUPO'. No se bloquea nunca, sea cual sea su mora.
5. no_bloqueado        - KONZS en ('AUTO', 'ADMON'). Tampoco se bloquea, por otro motivo.

Son mutuamente excluyentes por construccion (KONZS solo puede tener un valor, y AUFSD
solo entra en el caso 1). Un cliente sin ninguna factura vencida y sin grupo exento no
cae en ninguna: no tiene nada que reportar, y este proceso lo descarta.

De donde sale el dato, y por que este proceso no escribe nada en BigQuery
--------------------------------------------------------------------------
Todo el calculo (deuda vencida, dias de demora, las cinco categorias) ya esta hecho y
persistido en D60_REPORTING.clientes_bloqueados por OTRO proceso (a juzgar por el
CREATE OR REPLACE TABLE con plantilla de Airflow del backup, un DAG ajeno a este repo).
Esa tabla no esta particionada: cada corrida la reemplaza entera, sin historia.

A diferencia de Anticipos y Partidas, aqui no se construye una tabla propia de
evolucion. Es una decision explicita: el dato ya tiene un dueno (el DAG que lo calcula),
y anadir una segunda tabla solo para historizar algo que este proceso ni calcula habria
sido una automatizacion sobre otra automatizacion. Si algun dia hace falta ver la
evolucion de un cliente en el tiempo, hay que fotografiar clientes_bloqueados desde
fuera de este script.

Este proceso solo LEE dos tablas y envia correos:
- D60_REPORTING.clientes_bloqueados: las cinco categorias, ya calculadas.
- D20_DIMENSION.dm_company: el nombre completo de cada sociedad (company_name), para
  que el correo diga "Sociedad PAN - Proteina Animal SA de CV" y no solo el codigo.
  Mismo patron que nombre_proveedor via dm_vendors en Anticipos.

Decisiones tomadas, con su motivo
----------------------------------
1. Se descartan los clientes con company_code = '-'.

   Son clientes de KNA1 sin ninguna partida en BSID: no tienen sociedad asignable, y un
   correo "por sociedad" no tiene donde meterlos. Son la mayoria de las filas de la
   tabla origen (unas 20.000 de 23.500) precisamente por eso.

2. Solo entran los clientes con alguna de las cinco categorias activa.

   Un cliente sin factura vencida y sin grupo exento no tiene nada que decir en este
   reporte: no aparece.

3. Las sociedades son una lista fija de 23 codigos, no la que traiga la tabla ese dia.

   La tabla trae actividad en 22 codigos ese dia (comprobado por consulta agregada), mas
   PFO sin ninguna fila hoy. Se decidio incluir los 23 para que una sociedad sin clientes
   en riesgo hoy no desaparezca del reporte sin explicacion, igual que hacen Anticipos y
   Partidas con sus sociedades sin datos. La lista es mas amplia que la de Anticipos (16):
   aqui GSI, SCO, SCO1, ADE, FAG y FEF si tienen actividad real y entran.

4. SCO y SCO1 van como sociedades separadas, con su propio correo cada una.

   Comparten el mismo nombre comercial en dm_company ("Superdoña Comercial") pero son
   codigos de sociedad distintos con datos independientes.

5. No hay un total combinado entre categorias.

   Sumar el saldo vencido de un bloqueado con el de un cliente exento por grupo mezclaria
   poblaciones que no son comparables. Cada categoria lleva su propio subtotal y nada mas.

6. Control de frescura sobre la fecha de modificacion de la tabla, no sobre una columna.

   clientes_bloqueados no tiene _ingested_at: la sustituye entera un CREATE OR REPLACE
   TABLE externo, asi que la metadata de BigQuery (client.get_table().modified) hace las
   veces de esa columna. Se desconoce el ritmo real de esa carga (a diferencia de BSIK,
   que se comprobo que recarga cada dos horas): el umbral por defecto es generoso (30
   horas) hasta que se observe el patron real durante unos dias, igual que se hizo con
   BSIS en Partidas.

Destinatarios
-------------
Documento Firestore lists/clientes_bloqueados, con el mismo modelo que Anticipos y
Partidas: globales (un unico correo con las 23 sociedades) y por_sociedad (un correo por
sociedad). Si Firestore no esta disponible se cae a BLOQUEADOS_EMAIL_TO y luego a los
destinatarios por defecto, y en ese caso se envia SOLO el correo global.
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
ORIGEN = f"{PROJECT_ID}.D60_REPORTING.clientes_bloqueados"
ORIGEN_SOCIEDADES = f"{PROJECT_ID}.D20_DIMENSION.dm_company"

# Las 23 sociedades del reporte. Mas amplia que la de Anticipos (16): aqui GSI, SCO,
# SCO1, ADE, FAG y FEF si tienen clientes en riesgo real. PFO entra igual sin actividad
# hoy, para que su correo diga "sin clientes en riesgo" en vez de desaparecer.
SOCIEDADES = (
    "ABP", "ADE", "AME", "BAG", "CCP", "DBC", "FAG", "FEF", "GSI", "HEGP",
    "ISE", "MAL", "MPE", "PAL", "PAN", "PAT", "PFO", "PIN", "PRA", "ROMM",
    "SAP", "SCO", "SCO1",
)

# Las cinco categorias, en el orden de urgencia en que aparecen en el correo: primero
# los problemas reales, luego las dos exenciones (informativas, no accionables).
CAT_BLOQUEADO = "bloqueado"
CAT_BLOQUEO_ESPERADO = "bloqueo_esperado"
CAT_PROXIMO_BLOQUEO = "proximo_bloqueo"
CAT_NO_BLOQUEADO_GRUPO = "no_bloqueado_grupo"
CAT_NO_BLOQUEADO = "no_bloqueado"
CATEGORIAS = (
    (CAT_BLOQUEADO, "Bloqueados", "Credito cortado en SAP (AUFSD = 01)."),
    (
        CAT_BLOQUEO_ESPERADO,
        "Bloqueo esperado",
        "Vencido hace mas de un dia; SAP todavia no lo ha bloqueado.",
    ),
    (
        CAT_PROXIMO_BLOQUEO,
        "Proximos a bloqueo",
        "Acaba de vencer: al borde de que SAP lo bloquee.",
    ),
    (
        CAT_NO_BLOQUEADO_GRUPO,
        "No bloqueados por grupo",
        "Clave de grupo GRUPO: no se bloquea nunca, sea cual sea su mora.",
    ),
    (
        CAT_NO_BLOQUEADO,
        "No bloqueados",
        "Clave de grupo AUTO o ADMON: exento de bloqueo.",
    ),
)
ETIQUETAS_CATEGORIA = {clave: etiqueta for clave, etiqueta, _ in CATEGORIAS}

ZONA_MEXICO = ZoneInfo("America/Mexico_City")
SIN_NOMBRE_SOCIEDAD = "(sin nombre en la maestra)"
SIN_AREA = "(sin area)"
DESTINATARIOS_POR_DEFECTO = ("pcoma@quantrue.com",)

FIRESTORE_DATABASE_ID = os.environ.get("FIRESTORE_DATABASE_ID", "proan-lista-mails").strip()
FIRESTORE_LISTS_COLLECTION = os.environ.get("FIRESTORE_LISTS_COLLECTION", "lists").strip()
BLOQUEADOS_LIST_ID = os.environ.get("BLOQUEADOS_LIST_ID", "clientes_bloqueados").strip()

AZUL = "#2A2B5F"
BORDE = "#d9dee5"

PDF_ORIENTACION = "landscape"  # seis columnas: en vertical saldrian demasiado prietas
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
    crudo = os.environ.get("BLOQUEADOS_ONLY_SOCIEDADES", "").strip()
    if not crudo:
        return SOCIEDADES

    pedidas = [s.strip().upper() for s in crudo.split(",") if s.strip()]
    desconocidas = [s for s in pedidas if s not in SOCIEDADES]
    if desconocidas:
        raise ValueError(
            f"BLOQUEADOS_ONLY_SOCIEDADES contiene sociedades que no son del reporte: "
            f"{', '.join(desconocidas)}"
        )

    seleccion = tuple(s for s in SOCIEDADES if s in pedidas)
    logging.warning("Ejecucion limitada a %s por BLOQUEADOS_ONLY_SOCIEDADES", ", ".join(seleccion))
    return seleccion


# --------------------------------------------------------------------------- #
# Origen de datos
# --------------------------------------------------------------------------- #

def verificar_frescura(client) -> datetime:
    """
    Comprueba que clientes_bloqueados no esta caducada. Falla si lo esta.

    No hay columna _ingested_at: la tabla la reemplaza entera un CREATE OR REPLACE
    externo, asi que su propia fecha de modificacion (metadata de BigQuery) hace de
    sustituto. El umbral por defecto es generoso porque no se conoce el ritmo real de
    esa carga.
    """
    horas_maximas = int(os.environ.get("BLOQUEADOS_MAX_ANTIGUEDAD_HORAS", "30"))

    tabla = client.get_table(ORIGEN)
    ultima_carga = tabla.modified
    if ultima_carga is None:
        raise RuntimeError(f"No se pudo leer la fecha de modificacion de {ORIGEN}.")

    antiguedad = datetime.now(timezone.utc) - ultima_carga
    logging.info(
        "Ultima carga de %s: %s (hace %.1f horas)",
        ORIGEN,
        ultima_carga.isoformat(),
        antiguedad.total_seconds() / 3600,
    )

    if antiguedad > timedelta(hours=horas_maximas):
        raise RuntimeError(
            f"La tabla {ORIGEN} tiene {antiguedad.total_seconds() / 3600:.1f} horas de "
            f"antiguedad, mas del maximo de {horas_maximas}. El proceso que la mantiene "
            f"puede estar parado. No se envia el reporte para no dar por bueno un dato "
            f"caducado."
        )

    return ultima_carga


def nombres_sociedades(client, sociedades: tuple[str, ...]) -> dict[str, str]:
    """Nombre completo de cada sociedad, para titular los correos y bloques."""
    from google.cloud import bigquery

    consulta = f"""
        SELECT company_code, company_name
        FROM `{ORIGEN_SOCIEDADES}`
        WHERE company_code IN UNNEST(@sociedades)
    """
    configuracion = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ArrayQueryParameter("sociedades", "STRING", list(sociedades))]
    )
    nombres = {
        fila["company_code"]: fila["company_name"]
        for fila in client.query(consulta, job_config=configuracion).result()
    }

    faltantes = [s for s in sociedades if s not in nombres]
    if faltantes:
        logging.warning("Sin nombre en dm_company para: %s", ", ".join(faltantes))

    return nombres


def nombre_sociedad(nombres: dict[str, str], sociedad: str) -> str:
    return nombres.get(sociedad, SIN_NOMBRE_SOCIEDAD)


def consultar_clientes_bloqueados(client, sociedades: tuple[str, ...]) -> list[dict[str, Any]]:
    """
    Clientes con alguna de las cinco categorias activa, por sociedad.

    Las cinco categorias ya vienen calculadas como columnas booleanas en el origen; aqui
    solo se colapsan en una columna categoria (son mutuamente excluyentes) y se descartan
    los clientes sin ninguna activa, que no tienen nada que reportar.
    """
    from google.cloud import bigquery

    consulta = f"""
        SELECT
          company_code AS sociedad,
          customer AS cliente,
          IFNULL(business_area_name, IFNULL(business_area, @sin_area)) AS area,
          CASE
            WHEN bloqueado THEN @cat_bloqueado
            WHEN bloqueo_esperado THEN @cat_bloqueo_esperado
            WHEN proximo_bloqueo THEN @cat_proximo_bloqueo
            WHEN no_bloqueado_grupo THEN @cat_no_bloqueado_grupo
            WHEN no_bloqueado THEN @cat_no_bloqueado
          END AS categoria,
          demora_max,
          facturas_vencidas,
          dias_credito,
          saldo_vencido
        FROM `{ORIGEN}`
        WHERE company_code IN UNNEST(@sociedades)
          AND (bloqueado OR bloqueo_esperado OR proximo_bloqueo OR no_bloqueado_grupo OR no_bloqueado)
        ORDER BY sociedad, categoria, saldo_vencido DESC
    """
    configuracion = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ArrayQueryParameter("sociedades", "STRING", list(sociedades)),
            bigquery.ScalarQueryParameter("sin_area", "STRING", SIN_AREA),
            bigquery.ScalarQueryParameter("cat_bloqueado", "STRING", CAT_BLOQUEADO),
            bigquery.ScalarQueryParameter("cat_bloqueo_esperado", "STRING", CAT_BLOQUEO_ESPERADO),
            bigquery.ScalarQueryParameter("cat_proximo_bloqueo", "STRING", CAT_PROXIMO_BLOQUEO),
            bigquery.ScalarQueryParameter("cat_no_bloqueado_grupo", "STRING", CAT_NO_BLOQUEADO_GRUPO),
            bigquery.ScalarQueryParameter("cat_no_bloqueado", "STRING", CAT_NO_BLOQUEADO),
        ]
    )

    return [
        {
            "sociedad": fila["sociedad"],
            "cliente": fila["cliente"],
            "area": fila["area"],
            "categoria": fila["categoria"],
            "demora_max": fila["demora_max"],
            "facturas_vencidas": fila["facturas_vencidas"],
            "dias_credito": fila["dias_credito"],
            "saldo_vencido": fila["saldo_vencido"],
        }
        for fila in client.query(consulta, job_config=configuracion).result()
    ]


def agrupar_por_sociedad(
    filas: list[dict[str, Any]], sociedades: tuple[str, ...]
) -> dict[str, dict[str, list[dict[str, Any]]]]:
    """Una entrada por sociedad pedida, y dentro una por categoria, aunque esten vacias."""
    agrupado = {
        sociedad: {clave: [] for clave, _, _ in CATEGORIAS} for sociedad in sociedades
    }
    for fila in filas:
        agrupado[fila["sociedad"]][fila["categoria"]].append(fila)
    return agrupado


def _total(filas: list[dict[str, Any]]) -> Decimal:
    return sum((fila["saldo_vencido"] for fila in filas), Decimal("0"))


def _entero(valor: Any) -> str:
    return "-" if valor is None else str(int(valor))


# --------------------------------------------------------------------------- #
# Destinatarios
# --------------------------------------------------------------------------- #

def _normalizar_correos(crudos: Any) -> list[str]:
    """Deja una lista de direcciones limpias, sin repetidos y en el orden original."""
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
        client.collection(FIRESTORE_LISTS_COLLECTION).document(BLOQUEADOS_LIST_ID).get()
    )
    if not documento.exists:
        logging.warning(
            "No existe el documento Firestore %s/%s en la base %s",
            FIRESTORE_LISTS_COLLECTION,
            BLOQUEADOS_LIST_ID,
            FIRESTORE_DATABASE_ID,
        )
        return [], {}

    datos = documento.to_dict() or {}
    if not datos.get("enabled", True):
        logging.warning("La lista Firestore %s esta deshabilitada", BLOQUEADOS_LIST_ID)
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
        logging.warning("El campo por_sociedad de %s no es un mapa", BLOQUEADOS_LIST_ID)

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
        [c for c in os.environ.get("BLOQUEADOS_EMAIL_TO", "").split(",") if c.strip()]
    )
    if del_entorno:
        logging.warning(
            "Sin destinatarios en Firestore: se usa BLOQUEADOS_EMAIL_TO y solo se envia "
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
        cuerpo.append(
            "<tr>"
            + _celda(escape(fila["cliente"]), fuerte=True)
            + _celda(escape(fila["area"]))
            + _celda(escape(_entero(fila["demora_max"])), derecha=True)
            + _celda(escape(_entero(fila["facturas_vencidas"])), derecha=True)
            + _celda(escape(_entero(fila["dias_credito"])), derecha=True)
            + _celda(escape(_importe(fila["saldo_vencido"])), derecha=True, fuerte=True)
            + "</tr>"
        )

    encabezado = _encabezado(
        [
            ("Cliente", False),
            ("Area", False),
            ("Dias demora", True),
            ("Facturas vencidas", True),
            ("Dias credito", True),
            ("Saldo vencido", True),
        ]
    )
    etiqueta = f"{etiqueta_total} ({len(filas)} clientes)"
    return (
        f'<table width="100%" cellpadding="0" cellspacing="0" '
        f'style="border-collapse:collapse;border:1px solid {BORDE};border-radius:8px;'
        f'overflow:hidden;">'
        f"<thead>{encabezado}</thead>"
        f"<tbody>{''.join(cuerpo)}"
        f"{_fila_total(etiqueta, _total(filas), 5)}</tbody></table>"
    )


def _bloque_sociedad(
    sociedad: str, nombre: str, por_categoria: dict[str, list[dict[str, Any]]]
) -> str:
    """Bloque de una sociedad: una seccion por categoria activa, sin total combinado."""
    partes = [
        f'<p class="titulo-sociedad" style="font-family:Barlow,\'Segoe UI\',Arial,sans-serif;'
        f'font-size:16px;color:{AZUL};font-weight:800;margin:28px 0 2px;">'
        f"Sociedad {escape(sociedad)} - {escape(nombre)}</p>"
    ]

    con_datos = [
        (clave, etiqueta, nota) for clave, etiqueta, nota in CATEGORIAS if por_categoria[clave]
    ]

    if not con_datos:
        partes.append(
            '<p style="font-size:13px;color:#4b5563;margin:4px 0 8px;">'
            "Sin clientes en riesgo ni exentos con mora.</p>"
        )
        return "".join(partes)

    for clave, etiqueta, nota in con_datos:
        partes.append(
            f'<p class="titulo-seccion" style="font-size:13px;color:{AZUL};font-weight:700;'
            f'margin:16px 0 2px;">{escape(etiqueta)}</p>'
            f'<p class="titulo-seccion" style="font-size:11px;color:#6b7280;margin:0 0 8px;">'
            f"{escape(nota)}</p>"
        )
        partes.append(_tabla_detalle(por_categoria[clave], f"Total {etiqueta.lower()}"))

    return "".join(partes)


def _resumen_sociedades(
    agrupado: dict[str, dict[str, list[dict[str, Any]]]], nombres: dict[str, str]
) -> str:
    """Tabla de conteos por sociedad y categoria, mas el saldo vencido en riesgo real."""
    filas = []
    totales_generales = {clave: 0 for clave, _, _ in CATEGORIAS}
    total_riesgo_general = Decimal("0")

    for sociedad, por_categoria in agrupado.items():
        conteos = {clave: len(por_categoria[clave]) for clave, _, _ in CATEGORIAS}
        for clave, valor in conteos.items():
            totales_generales[clave] += valor

        riesgo = (
            por_categoria[CAT_BLOQUEADO]
            + por_categoria[CAT_BLOQUEO_ESPERADO]
            + por_categoria[CAT_PROXIMO_BLOQUEO]
        )
        saldo_riesgo = _total(riesgo)
        total_riesgo_general += saldo_riesgo

        filas.append(
            "<tr>"
            + _celda(escape(f"{sociedad} - {nombre_sociedad(nombres, sociedad)}"), fuerte=True)
            + "".join(
                _celda(escape(str(conteos[clave])), derecha=True) for clave, _, _ in CATEGORIAS
            )
            + _celda(escape(_importe(saldo_riesgo)), derecha=True, fuerte=True)
            + "</tr>"
        )

    encabezado = _encabezado(
        [("Sociedad", False)]
        + [(etiqueta, True) for _, etiqueta, _ in CATEGORIAS]
        + [("Saldo vencido en riesgo", True)]
    )
    fila_total = (
        "<tr>"
        f'<td style="padding:10px 12px;text-align:right;font-size:11px;font-weight:700;'
        f'color:{AZUL};text-transform:uppercase;letter-spacing:.5px;">Total general</td>'
        + "".join(
            _celda(escape(str(totales_generales[clave])), derecha=True, fuerte=True)
            for clave, _, _ in CATEGORIAS
        )
        + _celda(escape(_importe(total_riesgo_general)), derecha=True, fuerte=True)
        + "</tr>"
    )
    return (
        f'<table width="100%" cellpadding="0" cellspacing="0" '
        f'style="border-collapse:collapse;border:1px solid {BORDE};border-radius:8px;'
        f'overflow:hidden;margin-bottom:8px;">'
        f"<thead>{encabezado}</thead>"
        f"<tbody>{''.join(filas)}{fila_total}</tbody></table>"
    )


def _estilos_pdf() -> str:
    """Hoja de estilos que solo se aplica al PDF. Ver el mismo bloque en anticipos.py."""
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
    body, td, th, div, p {{ font-family: "Liberation Sans", Arial, sans-serif !important; }}
    .lienzo {{ padding: 0 !important; }}
    .tarjeta {{
      width: 100% !important; max-width: none !important;
      border: 0 !important; border-radius: 0 !important;
    }}
    thead {{ display: table-header-group; }}
    tr {{ break-inside: avoid; }}
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
            Cinco categorias: <b>bloqueados</b> (credito cortado hoy en SAP),
            <b>bloqueo esperado</b> (vencido hace mas de un dia, SAP aun no lo bloquea),
            <b>proximos a bloqueo</b> (recien vencido), <b>no bloqueados por grupo</b> y
            <b>no bloqueados</b> (exentos por clave de grupo). Importes en pesos mexicanos.
          </p>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body></html>"""


def generar_pdf(html: str) -> bytes | None:
    """Convierte a PDF el mismo HTML del correo, con WeasyPrint. Ver detalle en anticipos.py."""
    try:
        logging.getLogger("weasyprint").setLevel(logging.WARNING)
        logging.getLogger("fontTools").setLevel(logging.WARNING)

        from weasyprint import HTML

        return HTML(string=html).write_pdf()
    except Exception as exc:
        logging.warning("No se pudo generar el PDF: %s", exc)
        return None


def _guardar_pdf_local(nombre: str, pdf: bytes) -> None:
    directorio = Path(os.environ.get("BLOQUEADOS_DRY_RUN_DIR", "salida_dry_run"))
    try:
        directorio.mkdir(parents=True, exist_ok=True)
        destino = directorio / f"{nombre}.pdf"
        destino.write_bytes(pdf)
        logging.info("PDF de prueba en %s (%s KB)", destino, round(len(pdf) / 1024, 1))
    except OSError as exc:
        logging.warning("No se pudo escribir el PDF local de %s: %s", nombre, exc)


def _guardar_copia_local(nombre: str, html: str) -> None:
    directorio = Path(os.environ.get("BLOQUEADOS_DRY_RUN_DIR", "salida_dry_run"))
    try:
        directorio.mkdir(parents=True, exist_ok=True)
        destino = directorio / f"{nombre}.html"
        destino.write_text(html, encoding="utf-8")
        logging.info("HTML de prueba en %s", destino)
    except OSError as exc:
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

    if _es_verdadero(os.environ.get("BLOQUEADOS_EMAIL_DRY_RUN", "false")):
        _guardar_copia_local(nombre_copia, html)
        if pdf:
            _guardar_pdf_local(nombre_copia, pdf)
        return {
            "asunto": asunto,
            "cc": destinatarios,
            "estado": "dry_run",
            "adjunto": nombre_pdf if pdf else None,
            "mensaje": "Envio simulado por BLOQUEADOS_EMAIL_DRY_RUN=true.",
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
    nombres: dict[str, str],
    fecha_reporte,
    globales: list[str],
    por_sociedad: dict[str, list[str]],
) -> list[dict[str, Any]]:
    fecha_texto = fecha_reporte.strftime("%d/%m/%Y")
    sufijo_fichero = fecha_reporte.strftime("%Y%m%d")
    resultados = []

    def preparar(titulo_sub: str, contenido: str, nombre: str) -> tuple[str, bytes | None, str]:
        pdf = generar_pdf(
            construir_html("Reporte de clientes bloqueados", titulo_sub, contenido, para_pdf=True)
        )
        html = construir_html(
            "Reporte de clientes bloqueados",
            titulo_sub,
            contenido,
            aviso=None if pdf else AVISO_SIN_PDF,
        )
        return html, pdf, f"{nombre}_{sufijo_fichero}.pdf"

    if globales:
        bloques = "".join(
            _bloque_sociedad(sociedad, nombre_sociedad(nombres, sociedad), por_categoria)
            for sociedad, por_categoria in agrupado.items()
        )
        html, pdf, nombre_pdf = preparar(
            f"Todas las sociedades. Fecha de consulta {fecha_texto}.",
            _resumen_sociedades(agrupado, nombres) + bloques,
            "clientes_bloqueados_todas_las_sociedades",
        )
        resultados.append(
            enviar_correo(
                f"Clientes bloqueados - todas las sociedades - {fecha_texto}",
                html,
                globales,
                "clientes_bloqueados_global",
                pdf=pdf,
                nombre_pdf=nombre_pdf,
            )
        )
    else:
        logging.warning("Sin destinatarios globales: no se envia el correo consolidado")

    for sociedad, por_categoria in agrupado.items():
        destinatarios = por_sociedad.get(sociedad, [])
        if not destinatarios:
            logging.warning(
                "La sociedad %s no tiene destinatarios en por_sociedad: no se envia", sociedad
            )
            continue

        nombre_larga = nombre_sociedad(nombres, sociedad)
        html, pdf, nombre_pdf = preparar(
            f"Sociedad {sociedad} - {nombre_larga}. Fecha de consulta {fecha_texto}.",
            _bloque_sociedad(sociedad, nombre_larga, por_categoria),
            f"clientes_bloqueados_{sociedad}",
        )
        resultados.append(
            enviar_correo(
                f"Clientes bloqueados {sociedad} - {fecha_texto}",
                html,
                destinatarios,
                f"clientes_bloqueados_{sociedad.lower()}",
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

    logging.info("Comprobando frescura de clientes_bloqueados")
    verificar_frescura(client)

    logging.info("Resolviendo nombres de sociedad")
    nombres = nombres_sociedades(client, sociedades)

    logging.info("Consultando clientes en riesgo de %s sociedades", len(sociedades))
    filas = consultar_clientes_bloqueados(client, sociedades)
    agrupado = agrupar_por_sociedad(filas, sociedades)

    for clave, etiqueta, _ in CATEGORIAS:
        de_categoria = [f for f in filas if f["categoria"] == clave]
        logging.info(
            "%s: %s clientes por %s", etiqueta, len(de_categoria), _importe(_total(de_categoria))
        )
    logging.info("Total: %s filas por %s", len(filas), _importe(_total(filas)))

    ahora = datetime.now(ZONA_MEXICO)
    fecha_reporte = ahora.date()

    globales, por_sociedad, origen = resolver_destinatarios()
    logging.info(
        "Destinatarios desde %s: %s globales, %s sociedades con lista propia",
        origen,
        len(globales),
        len(por_sociedad),
    )

    resultados = enviar_reportes(agrupado, nombres, fecha_reporte, globales, por_sociedad)
    for resultado in resultados:
        logging.info("Correo: %s", resultado)

    logging.info("Proceso completado: %s correos", len(resultados))


if __name__ == "__main__":
    main()
