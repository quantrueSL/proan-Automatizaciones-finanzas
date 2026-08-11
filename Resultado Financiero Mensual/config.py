"""Configuración del reporte "Resultado Financiero Mensual" PROAN -- Ingresos/Egresos/
Resultado por sociedad, para los ÚLTIMOS 2 MESES YA CERRADOS (reducido de 3 a 2 meses el
2026-08-07, y corregido el mismo día para que el mes en curso NO aparezca -- solo meses
cerrados). Ambos meses llevan chequeo de estabilidad contra un snapshot de ~14 días atrás.

Reporte SEPARADO del "Resultado Financiero Diario" (cuadre Balance vs. Estado de Resultados)
y de "Reportes diarios contables" (las 4 cuentas). No comparte PDF ni envío de correo con
ninguno de los dos.
"""

import os

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))

PROJECT_ID = "proan-quantrue"

# Paleta: IDÉNTICA a "Reportes diarios contables/config.py" (navy monocromático, v2 -- NO el
# acento dorado #B8860B que tenía la versión anterior a ese cambio). Confirmado con el usuario
# (2026-08-07) que el sistema "ya aprobado" a reutilizar es este, el vigente hoy, no el dorado
# retirado -- por eso se copia tal cual, sin reinterpretar la instrucción original del brief.
COLORS = {
    "header_bg": "#0d2a4a",
    "header_accent": "#184F95",
    "actual": "#0d2a4a",
    "anterior": "#8CA5C4",
    "pct_line": "#184F95",
    "good": "#1B7F4C",
    "critical": "#B3261E",
    "text_primary": "#0b0b0b",
    "text_secondary": "#3F4550",
    "muted": "#6B7280",
    "grid": "#EDEEF1",
    "surface": "#FFFFFF",
    "tile_bg": "#F5F7FA",
    "kpi_border": "#C9D6E5",
    # Nuevo en este reporte (no existía en los otros 3): color de los ÍCONOS de estatus (ya
    # no fondo de celda, ver pdf.py -- cambiado 2026-08-07 a pedido del usuario, "reemplaza el
    # resaltado amarillo de fondo por un ícono"). Ámbar para PROVISIONAL, gris para
    # SIN_REFERENCIA -- dos situaciones distintas (mes recién cerrado que aún puede moverse
    # vs. sociedad sin snapshot de referencia disponible), no deben verse igual ni con el
    # mismo ícono.
    "provisional_text": "#7A5B00",
    "sin_referencia_text": "#6B7280",
}

# Catálogo RBUKRS -> nombre comercial. Copiado tal cual de "Reportes diarios contables/
# config.py" (mismo catálogo validado, ver ese archivo para el detalle de la validación).
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
    "PFO": "Panita Foods",
    "PRA": "Proan Alimentos",
    "ROMM": "Romo Muñoz Manuel",
    "SAP": "Servicios y Alimentos Proteínicos",
    "FAG": "Ferma Agropecuaria",
    "PIN": "Sociedad no identificada (PIN)",
    # Agregados 2026-08-07 al construir este reporte (no estaban en el catálogo original
    # porque no participan en el reporte diario de 2026): confirmados vía dm_company.
    "ADE": "Aves en Desarrollo",
    "SCO": "Superdoña Comercial (código legado, ver nota)",  # distinto de SCO1, ambas con el
    # mismo nombre en dm_company -- SCO solo tuvo actividad 2014-2015, reemplazada por SCO1.
    "SCO1": "Superdoña Comercial",
}

# La query trae de la tabla viva SIN filtrar RYEAR (a propósito, así el ORDER BY sociedad
# incluye cualquier código que haya tenido actividad de Ingresos/Egresos en cualquier año),
# así que aparecen sociedades sin ninguna fila en los 3 meses mostrados -- todas sus columnas
# NULL, no por error sino porque su actividad es de años anteriores (confirmado 2026-08-07:
# ADE 2010-2011, GSI último año con datos 2025 -no 2026-, PFO hasta 2024, SCO 2014-2015).
# Se filtran del reporte (no de la query) las sociedades sin NINGÚN dato en los 3 meses --
# de 21 códigos devueltos, deja 17 activas, el número que esperaba el usuario. No se aplica
# a PIN: esa sociedad sí tiene postings reales (aunque sumen $0) en el periodo mostrado, así
# que no es "sin datos", es "datos en cero" -- casos distintos, ver datos.py.
FILTRAR_SOCIEDADES_SIN_ACTIVIDAD_RECIENTE = True

# Snapshot de referencia para el chequeo de estabilidad: ventana de búsqueda (días atrás desde
# hoy). Igual que en la query del usuario -- ver datos.get_snapshot_table().
SNAPSHOT_DIAS_OBJETIVO = 14
SNAPSHOT_DIAS_LIMITE = 24

# Piso de "base ~0" para la columna % Variación (evita un % disparatado cuando el Resultado
# del mes anterior es casi cero pero no exactamente 0.0) -- mismo valor y mismo criterio que
# UMBRAL_MATERIALIDAD_MXN en "Reportes diarios contables/config.py", pedido explícito del
# usuario de reusar "la misma convención que ya usamos en los otros reportes".
UMBRAL_MATERIALIDAD_MXN = 1000

FONT_REGULAR_TTF = os.path.join(_BASE_DIR, "fonts", "IBMPlexSans-Regular.ttf")
FONT_BOLD_TTF = os.path.join(_BASE_DIR, "fonts", "IBMPlexSans-Bold.ttf")
FONT_MONO_TTF = os.path.join(_BASE_DIR, "fonts", "IBMPlexMono-Regular.ttf")
FONT_MONO_BOLD_TTF = os.path.join(_BASE_DIR, "fonts", "IBMPlexMono-Bold.ttf")

OUTPUT_DIR = os.environ.get("OUTPUT_DIR", r"C:\Users\Lucia\proan_reporte_diario\salidas")

MAX_SOCIEDADES_EN_GRAFICO = 20

# --- Envío de correo: cascada de destinatarios vía Firestore -----------------------------
# Mismo patrón que "Cambio divisa/divisa.py" -- Firestore -> variable de entorno -> tupla
# hardcodeada. Horario de Cloud Scheduler: 08:00 America/Mexico_City, día 1 de cada mes.
FIRESTORE_DATABASE_ID = os.environ.get("FIRESTORE_DATABASE_ID", "proan-lista-mails").strip()
FIRESTORE_LISTS_COLLECTION = os.environ.get("FIRESTORE_LISTS_COLLECTION", "lists").strip()
RESULTADO_MENSUAL_LIST_ID = os.environ.get("RESULTADO_MENSUAL_LIST_ID", "resultado_financiero_mensual").strip()
EMAIL_ASUNTO_TEMPLATE = "Resultado Financiero Mensual PROAN - {mes1_str} y {mes2_str}"
EMAIL_DESTINATARIO_DEFAULT = "lucigo30@ucm.es"
DEFAULT_EMAIL_RECIPIENTS = (EMAIL_DESTINATARIO_DEFAULT,)
