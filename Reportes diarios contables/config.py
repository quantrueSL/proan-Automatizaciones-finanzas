"""Configuración del reporte diario de cuentas contables PROAN."""

PROJECT_ID = "proan-quantrue"
TABLE_FQN = "`proan-quantrue.D30_INTEGRATION.sap_faglflext`"

# Filtros fijos usados en la consulta validada por el usuario para Gastos no Deducibles.
LEDGER = "0L"
RECORD_TYPE = "0"
VERSION = "001"

# Cuentas contables. Editable: para agregar una cuenta nueva basta con añadir una
# entrada aquí (nombre -> lista de RACCT). No se necesita tocar el resto del código.
CUENTAS = {
    "Mermas": ["0005010628"],
    "Variación de Precios": ["0005010632"],
    "Gastos no Deducibles": ["0005020000"],
    "Descuentos y Bonificaciones": ["0004018001", "0004018003", "0004018178"],
}

# Solo se generan las cuentas listadas aquí. El usuario pidió limitarse a
# "Gastos no Deducibles" por ahora porque es la única consulta 100% corroborada;
# las demás se activan a medida que se validen sus queries.
CUENTAS_ACTIVAS = ["Gastos no Deducibles"]

# El mapeo RBUKRS -> nombre de sociedad ya NO se hardcodea aquí: se carga en tiempo de
# ejecución desde D20_DIMENSION.dm_company (ver datos.fetch_sociedades). SKAT es el
# catálogo de cuentas contables, no de sociedades, así que no aplica para esto.

# Paleta validada con scripts/validate_palette.js (skill dataviz) contra el fondo claro #fcfcfb.
# Sustituir aquí si Proan tiene hex de marca oficiales distintos.
COLORS = {
    "header_bg": "#0d2a4a",       # banda de encabezado (chrome, no dato)
    "header_accent": "#d03b3b",   # franja roja bajo el encabezado
    "actual": "#184F95",          # serie "periodo actual" (validado)
    "anterior": "#5598E7",        # serie "periodo anterior" (validado)
    "good": "#0ca30c",            # variación positiva (verde)
    "critical": "#d03b3b",        # variación negativa (rojo)
    "text_primary": "#0b0b0b",
    "text_secondary": "#52514e",
    "muted": "#898781",
    "grid": "#e1e0d9",
    "surface": "#fcfcfb",
    "tile_bg": "#f5f7fa",
}

# Fuente para un look más moderno. Se registra desde C:\Windows\Fonts si existe;
# si no, pdf.py hace fallback a Helvetica automáticamente.
FONT_REGULAR_TTF = r"C:\Windows\Fonts\segoeui.ttf"
FONT_BOLD_TTF = r"C:\Windows\Fonts\segoeuib.ttf"

MAX_SOCIEDADES_EN_GRAFICO = 20

# Si |anterior| es menor a esto, el % de variación se considera no significativo
# (base casi cero produce porcentajes absurdos, ej. -18,725,722,200%) y se muestra "N/A".
UMBRAL_MATERIALIDAD_MXN = 1000

OUTPUT_DIR = r"C:\Users\Lucia\proan_reporte_diario\salidas"
