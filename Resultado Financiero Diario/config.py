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
# Cambiado 2026-08-21: antes `sap_faglflext`. `sap_faglflext_rt` es la misma tabla (esquema
# idéntico, mismo filtro 0L/0/001, mismos saldos verificados por sociedad) pero se actualiza
# con mayor frecuencia. NOTA: esta constante no se usaba en datos.py (la query tenía la tabla
# hardcodeada aparte) -- ver datos.py, también actualizado.
TABLE_FQN = "`proan-quantrue.D30_INTEGRATION.sap_faglflext_rt`"

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

# Logo real de Proan, copiado LOCALMENTE a esta carpeta (2026-08-07, corregido) -- antes
# apuntaba a "../Cambio divisa/proan.png", una ruta FUERA del contexto de build de Docker
# ("gcloud builds submit ." solo manda el contenido de esta carpeta). En producción esa ruta
# nunca existía: no rompía nada (el código ya comprueba os.path.exists antes de usarlo) pero
# el logo nunca aparecía en el PDF ni en el correo. Ahora viaja con el código, como fonts/.
LOGO_PNG = os.path.join(_BASE_DIR, "proan.png")

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
    "PIN": "Perfil Integral",  # identificada 2026-08-17 vía dm_company ("PERFIL INTEGRAL SA DE CV");
    # antes figuraba como "Sociedad no identificada (PIN)". Importes mínimos (~$3,500/año) pero
    # aparece en el reporte, así que conviene que salga con su nombre real.
    "PFO": "Panita Foods",  # faltaba: en el cuadre de 2024 la sociedad salía como código crudo
    # "PFO" porque no estaba en este catálogo (sí lo estaba en "Reportes diarios contables").
    # Sin filas en 2026 (dejó de operar), pero sigue apareciendo al correr años anteriores.
    "SCO1": "Superdoña Comercial",  # confirmado 2026-08-07 vía dm_company (plan PCSD)
}

# Hueco de cobertura conocido (2026-08-17): "Procesadora Tecnológica de Polímeros", que SÍ es
# una fila de la tabla de referencia del PDF "Resultado financiero diario.pdf", no existe ni en
# D20_DIMENSION.dm_company ni en sap_faglflext_rt -- no hay ningún RBUKRS que le corresponda. Este
# reporte nunca la va a mostrar, y no es un error del código: la sociedad no está replicada en
# BigQuery. Si finanzas la necesita en el cuadre, hay que pedir su alta a sistemas.

# Mismas fuentes IBM Plex que "Reportes diarios contables" (copiadas a esta carpeta para que
# esta automatización sea independiente en el despliegue, ver README del repo). Fallback a
# Helvetica/Courier si faltan los archivos.
FONT_REGULAR_TTF = os.path.join(_BASE_DIR, "fonts", "IBMPlexSans-Regular.ttf")
FONT_BOLD_TTF = os.path.join(_BASE_DIR, "fonts", "IBMPlexSans-Bold.ttf")
FONT_MONO_TTF = os.path.join(_BASE_DIR, "fonts", "IBMPlexMono-Regular.ttf")
FONT_MONO_BOLD_TTF = os.path.join(_BASE_DIR, "fonts", "IBMPlexMono-Bold.ttf")

# Misma carpeta de salida que el resto de reportes (Windows local / Cloud Run vía OUTPUT_DIR).
OUTPUT_DIR = os.environ.get("OUTPUT_DIR", r"C:\Users\Lucia\proan_reporte_diario\salidas")

# --- Destinatarios: lista administrada en Firestore ---------------------------------------
# Fuente unica: el documento lists/reportes-financieros de la base proan-lista-mails
# (compartido por los tres reportes financieros). Se lee con get_mailing_list() en
# enviar_reporte.py. Ya no hay cascada a variable de entorno ni tupla hardcodeada.
FIRESTORE_DATABASE_ID = os.environ.get("FIRESTORE_DATABASE_ID", "proan-lista-mails").strip()
FIRESTORE_LISTS_COLLECTION = os.environ.get("FIRESTORE_LISTS_COLLECTION", "lists").strip()
RESULTADO_DIARIO_LIST_ID = os.environ.get("RESULTADO_DIARIO_LIST_ID", "reportes-financieros").strip()
EMAIL_ASUNTO_TEMPLATE = "Resultado Financiero Diario PROAN - {fecha}"
# Los destinatarios ya NO viven en el codigo: se administran en el documento de
# Firestore lists/reportes-financieros (base proan-lista-mails). Ver get_mailing_list()
# en enviar_reporte.py. Se retiraron EMAIL_DESTINATARIO_DEFAULT y
# DEFAULT_EMAIL_RECIPIENTS el 2026-08-20 para que no quede una copia de los correos
# aqui que pueda desincronizarse de la lista real.
