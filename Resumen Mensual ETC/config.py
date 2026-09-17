"""Configuración del Resumen Ejecutivo Mensual de ETC (Enlaces Terrestres Comerciales).

Todas las cifras y agrupaciones de aquí se validaron al centavo contra el mockup real
(mockup_resumen_mensual.html, datos de agosto 2026) antes de escribir una sola query --
ver datos.py para el detalle de cada verificación. Nada de esto es "a ojo".
"""

import os

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))

PROJECT_ID = "proan-quantrue"
BQ_LOCATION = "us-west4"

TABLA_INGRESOS = "D60_REPORTING.rentabilidad_ETC_ingresos"
TABLA_GASTOS = "D60_REPORTING.rentabilidad_ETC_gastos"
TABLA_ORIGEN_APLICACION = "D60_REPORTING.rentabilidad_ETC_origen_aplicacion"
TABLA_DASHBOARD = "D60_REPORTING.rentabilidad_ETC_dashboard"       # flotilla + unidad motriz
TABLA_DASHBOARD2 = "D60_REPORTING.rentabilidad_ETC_dashboard2"     # por ruta

EMPRESA_NOMBRE = "Enlaces Terrestres Comerciales"
EMPRESA_SIGLAS = "ETC"

# --- Umbrales de materialidad para "Rentabilidad por Segmento" ------------------------
# Confirmados EXACTOS contra el mockup (2026-09-03): con estos tres umbrales, el
# mejor/peor margen que sale de sap_faglflext... (perdón, de las tablas de ETC) coincide
# al décimo de punto porcentual con cada valor del mockup -- no son un punto de partida
# razonable, son los que de verdad se usaron para construirlo.
UMBRAL_INGRESO_FLOTILLA = 500_000
UMBRAL_INGRESO_UNIDAD = 100_000
UMBRAL_INGRESO_RUTA = 200_000

# --- Composición de Ingresos: mapeo descripcion -> categoría del donut ----------------
# Las 9 `descripcion` distintas de rentabilidad_ETC_ingresos se mapean 1:1 a estas 5
# categorías. "Venta de Activos" se decide por la columna `es_venta_de_activos` (no por
# texto) porque agrupa dos descripciones (0% y 16%). Verificado contra agosto 2026: los
# 5 porcentajes resultantes coinciden al décimo con el mockup (75.3/19.4/3.1/1.8/0.4).
# VENTAS FLETES FORANEOS/LOCALES *PF* (pasajero, no aparecen en el mockup) dieron $0 en
# agosto -- si algún mes tienen movimiento, caen en "Otros" para no perder el ingreso.
CATEGORIA_INGRESO_ORDEN = [
    "Fletes Foráneos PM",
    "Servicios Dedicados",
    "Fletes Locales PM",
    "Venta de Activos",
    "Otros (demoras, maniobras)",
]


def categoria_ingreso(descripcion, es_venta_de_activos):
    if es_venta_de_activos:
        return "Venta de Activos"
    d = descripcion.upper()
    if "FLETES FORANEOS PM" in d:
        return "Fletes Foráneos PM"
    if "SERVICIOS DEDICADOS" in d:
        return "Servicios Dedicados"
    if "FLETES LOCALES PM" in d:
        return "Fletes Locales PM"
    if "DEMORAS" in d or "MANIOBRAS" in d:
        return "Otros (demoras, maniobras)"
    # Cualquier otra cosa (ej. Fletes *PF* si algún mes tiene movimiento) -- no se
    # pierde el ingreso, se muestra igual dentro de "Otros" en vez de desaparecer.
    return "Otros (demoras, maniobras)"


# --- Principales Gastos ----------------------------------------------------------------
TOP_N_GASTOS = 5

# --- Depreciación: caveat de datos (ver briefing 2026-09, documento_dashboard_gastos.md)
# Desde mayo 2026 las 9 cuentas de depreciación caen a $0 exacto (problema de origen en
# SAP, no de este pipeline) -- infla la utilidad calculada. Se compara el gasto de
# depreciación del mes contra el promedio de los N meses anteriores; si el mes actual es
# ~0 y el promedio anterior no lo era, se agrega una advertencia dinámica al Mensaje Clave.
MESES_PROMEDIO_DEPRECIACION = 4
UMBRAL_DEPRECIACION_CERO = 1_000  # por debajo de esto se considera "en $0"

# --- Origen y Aplicación de Recursos ---------------------------------------------------
# `linea` es un catálogo fijo de 19 líneas (ver origen_aplicacion en BigQuery). Estas son
# las que el mockup siempre muestra por nombre propio -- el resto de líneas con
# origen_mes/aplicacion_mes != 0 se suman en una fila "Otros orígenes"/"Otros aplicación".
# Confirmado exacto contra agosto 2026: de 8 líneas de origen con movimiento, estas 3 son
# las que se muestran solas y las otras 5 sí caen en "Otros orígenes" ($4.6M, coincide);
# de 5 líneas de aplicación con movimiento, las 5 son justo estas (no hubo "Otros" ese
# mes). Es una lista curada del catálogo real, no un umbral inventado -- si algún mes
# cambia cuáles líneas tienen movimiento, "Otros" simplemente absorbe lo que no esté aquí.
ORIGEN_LINEAS_DESTACADAS = [
    "Utilidad/Perdida del Ejercicio",
    "Creditos Bancarios",
    "Anticipos / IVA por Pagar",
]
APLICACION_LINEAS_DESTACADAS = [
    "Bancos",
    "Cuentas por Cobrar",
    "IVA Acreditable",
    "Activo Fijo",
    "Otros Activos Fijos (fuera de F.01)",
]

# --- Serie mensual del gráfico de Desempeño Financiero ---------------------------------
MESES_SERIE_DESEMPENO = 8

# --- Paleta (idéntica a :root del mockup_resumen_mensual.html) -------------------------
COLORS = {
    "ink": "#16233a", "muted": "#667085", "muted2": "#8b93a3",
    "line": "#e3e1d7", "line2": "#eceae1",
    "navy": "#14263f", "navy2": "#1c3350",
    "gold": "#96742a", "gold_soft": "#c9a86a",
    "good": "#1f7a4d", "bad": "#a33636", "warn": "#96721f",
    "paper": "#efece4", "card": "#fdfcfa",
    # Colores de línea del gráfico SVG (más saturados que --navy/--gold para que se vean
    # bien a 2.5px de trazo sobre fondo claro -- mismos tonos que ya trae el mockup).
    "chart_ingresos": "#1f4e79", "chart_gastos": "#a8722e",
    # Donut de Composición de Ingresos: navy, gold, y 3 grises descendentes (mismos hex
    # que el conic-gradient hardcodeado del mockup).
    "donut": ["#14263f", "#96742a", "#8f97a4", "#b9bfc9", "#d8dce2"],
}

# --- Firestore: lista de destinatarios --------------------------------------------------
FIRESTORE_DATABASE_ID = os.environ.get("FIRESTORE_DATABASE_ID", "proan-lista-mails").strip()
FIRESTORE_LISTS_COLLECTION = os.environ.get("FIRESTORE_LISTS_COLLECTION", "lists").strip()
RESUMEN_MENSUAL_ETC_LIST_ID = os.environ.get("RESUMEN_MENSUAL_ETC_LIST_ID", "reporte_mensual_etc").strip()

OUTPUT_DIR = os.environ.get("OUTPUT_DIR", r"C:\Users\Lucia\proan_reporte_diario\salidas")
TEMPLATE_PATH = os.path.join(_BASE_DIR, "plantilla_resumen_mensual.html")

EMAIL_ASUNTO_TEMPLATE = "Resumen Ejecutivo Mensual ETC - {mes_nombre} {anio}"
