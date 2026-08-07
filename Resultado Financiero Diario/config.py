"""Configuración del reporte "Resultado Financiero diario" PROAN — cuadre contable por
sociedad (Balance vs. Estado de Resultados), NO confundir con el reporte de las 4 cuentas
contables en "Reportes diarios contables" (carpeta hermana, PDF y plantilla distintos).

Ver memoria del proyecto (resultado-financiero-diario-proyecto, faglflext-clasificacion-
cuentas, faglflext-query-notas-tecnicas) para el detalle de por qué la clasificación de
cuentas es la que es y qué queda pendiente de validar contra SAP ZF01.
"""

import os

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))

PROJECT_ID = "proan-quantrue"
TABLE_FQN = "`proan-quantrue.D30_INTEGRATION.sap_faglflext`"

# Tolerancia para considerar Dif. == 0 (evita falsos positivos por redondeo de centavos).
# Pedido explícito del usuario para este reporte: "> 0.01".
TOLERANCIA_DIF_MXN = 0.01

# Paleta corporativa premium (2026-08-07, rediseño completo pedido por el usuario -- "actúa
# como Senior UI/UX Designer... dashboard financiero para CFOs"). Hex EXACTOS dados por el
# usuario, no reinterpretados. Reemplaza la paleta navy/ámbar anterior (esta carpeta ya no
# comparte paleta con "Reportes diarios contables").
#
# Regla explícita del usuario, respetada en todo el código que usa estos colores (pdf.py,
# graficos.py, enviar_reporte.py): "Rojo únicamente para diferencias negativas. Verde
# únicamente para conciliaciones correctas. Nunca colores saturados." -- por eso "good"/
# "critical" son tonos apagados (misma familia que ya estaba validada en el otro reporte,
# no un rojo/verde de semáforo puro), y ningún otro elemento del reporte usa rojo o verde.
COLORS = {
    "primary": "#12355B",     # azul oscuro -- header, texto de máximo peso, cabecera de tabla
    "secondary": "#2F6FED",   # azul medio -- acento, barras del gráfico, enlaces/CTA
    "support": "#EAF2FF",     # azul muy claro -- fondos de tarjeta, franjas zebra
    "surface": "#FFFFFF",
    "bg": "#F7F9FC",
    "border": "#E5E7EB",
    "muted": "#6B7280",       # texto secundario/etiquetas
    "text_secondary": "#374151",  # texto de cifras positivas (nunca negro puro, pide el usuario "gris oscuro")
    "text_primary": "#12355B",    # texto de máximo contraste (reutiliza el primary, no negro puro)
    "good": "#1B7F4C",        # verde apagado -- SOLO conciliaciones correctas (Dif. == 0)
    "good_bg": "#EAF6EF",
    "critical": "#B3261E",    # rojo apagado -- SOLO diferencias negativas / Dif. != 0
    "critical_bg": "#FBEAE9",
    # Alias retrocompatibles (mismo nombre que usaba el código anterior, valor nuevo) --
    # evita tener que tocar cada referencia de golpe.
    "grid": "#E5E7EB",
    "tile_bg": "#F7F9FC",
    "kpi_border": "#E5E7EB",
}

LOGO_PNG = os.path.join(_BASE_DIR, "..", "Cambio divisa", "proan.png")  # logo real de Proan,
# ya usado en la automatización "Cambio divisa" -- se reutiliza tal cual, no se fabrica uno.

# Catálogo RBUKRS -> nombre comercial. Copiado del mismo catálogo ya validado en "Reportes
# diarios contables/config.py" (contra el árbol de SAP y el Excel de finanzas, ver ese
# archivo para el detalle) -- se agregó explícitamente a pedido del usuario (2026-08-07,
# "quiero que se vean los nombres completos", tanto en el gráfico como en la tabla).
#
# SCO1 no estaba en el catálogo original (esa carpeta no maneja plan PCSD). Se confirmó vía
# D20_DIMENSION.dm_company (2026-08-07): SCO1 = "Superdoña Comercial" -- de paso resuelve una
# duda que quedó abierta en el otro reporte (el código de Superdoña Comercial nunca se había
# podido confirmar contra RBUKRS, ver nota en "Reportes diarios contables/config.py").
SOCIEDADES = {
    "ABP": "Alimentos Balanceados Proan",
    "AME": "Avibel de México",
    "BAG": "Bio Agrofert",
    "CCP": "CCP Productos",
    "DBC": "Distribuidora de Básicos",
    "GSI": "Granos y Servicios Integrales",
    "HEGP": "Pedro Pastor Hernández Guerrero",
    "ISE": "Integradora de Servicios",
    "MAL": "Maxim Alimentos",
    "MPE": "Maka Pet",
    "PAL": "Panovo Alimentaria",
    "PAN": "Proteína Animal",
    "PAT": "Procesadora de Aves",
    "PRA": "Proan Alimentos",
    "ROMM": "Romo Muñoz Manuel",
    "SAP": "Servicios y Alimentos Proteínicos",
    "FAG": "Ferma Agropecuaria",
    "PIN": "Sociedad no identificada (PIN)",  # importe residual histórico, revisar si sigue activa
    "SCO1": "Superdoña Comercial",  # confirmado 2026-08-07 vía dm_company (plan PCSD)
}

# Mismas fuentes IBM Plex que "Reportes diarios contables" (copiadas a esta carpeta para que
# esta automatización sea independiente en el despliegue, ver README del repo). Fallback a
# Helvetica/Courier si faltan los archivos.
FONT_REGULAR_TTF = os.path.join(_BASE_DIR, "fonts", "IBMPlexSans-Regular.ttf")
FONT_BOLD_TTF = os.path.join(_BASE_DIR, "fonts", "IBMPlexSans-Bold.ttf")
FONT_MONO_TTF = os.path.join(_BASE_DIR, "fonts", "IBMPlexMono-Regular.ttf")
FONT_MONO_BOLD_TTF = os.path.join(_BASE_DIR, "fonts", "IBMPlexMono-Bold.ttf")

# Misma carpeta de salida que el resto de reportes (Windows local / Cloud Run vía OUTPUT_DIR).
OUTPUT_DIR = os.environ.get("OUTPUT_DIR", r"C:\Users\Lucia\proan_reporte_diario\salidas")

# --- Envío de correo (NO usado todavía) --------------------------------------------------
# Deliberadamente sin terminar de definir: el usuario pidió confirmar antes de tocar envío
# si el destinatario es el mismo que REPORTE_EMAIL_TO (4 cuentas contables) u otro distinto,
# y si va en un segundo Cloud Run Job o en el mismo. No crear enviar_reporte.py ni deploy.sh
# para esta carpeta hasta tener esa confirmación (ver briefing 2026-08-07).
EMAIL_ASUNTO_TEMPLATE = "Resultado Financiero Diario PROAN - {fecha}"
