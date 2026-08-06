"""Configuración del reporte diario de cuentas contables PROAN."""

PROJECT_ID = "proan-quantrue"
TABLE_FQN = "`proan-quantrue.D30_INTEGRATION.sap_faglflext`"

# Filtros fijos usados en la consulta validada por el usuario para Gastos no Deducibles.
# Verificado en BigQuery (2026-08): las 417,443 filas de sap_faglflext tienen exactamente
# esta combinación (0L / 0 / 001) -- la tabla no trae otra, así que estos filtros son
# redundantes hoy. Se dejan de todos modos por seguridad ante un cambio futuro de datos.
LEDGER = "0L"
RECORD_TYPE = "0"
VERSION = "001"

# --- Formato único de reporte por cuenta contable (dashboard) ----------------------
# Estándar visual para TODOS los reportes de cuenta única (Gastos no Deducibles, Mermas,
# Variación de Precios): banner + 4 KPI tiles + gráfico combinado (barras + % variación) +
# tabla Sociedad/actual/anterior/Diferencias/%Variac. Referencia:
# "reporte-cuentas-actual.png" (fuera del repo, en Reportes documentos/), prototipo
# "Reporte Pasivo Temporal". Implementado en pdf.py (_header, _stat_tiles, _tabla_sociedades,
# build_section) y reutilizado por todas las cuentas de este tipo -- NO hay funciones
# especiales por cuenta (el formato "Empresa/Año ant/Año actual/Dif" que se probó para
# Variación de Precios quedó retirado). Descuentos y Bonificaciones sigue con su propio
# mecanismo (rango + clasificación por signo, ver más abajo) porque su naturaleza es
# distinta (no es una sola cuenta de mayor) y el usuario pidió no tocarlo.
#
# Convención de % cuando el periodo base (normalmente "anterior") es ~0 (por debajo de
# UMBRAL_MATERIALIDAD_MXN): en vez de "N/A" se muestra +100.00%/-100.00% (ver
# pdf._pct_o_100). No hay división por cero real que reportar como N/A -- simplemente no
# había base el periodo anterior.
#
# Snapshot para "periodo anterior" (último cierre): PENDIENTE. Se confirmó que
# D10_POSTPROCESSING solo tiene snapshots diarios sap_faglflext2_YYYYMMDD desde 2026-05-06
# en adelante -- no existe ningún snapshot del cierre de 2024 ni de 2025 (la tabla de
# snapshots se empezó a llenar después de que ambos cierres ya habían pasado). Por decisión
# del usuario, mientras tanto "anterior" se sigue calculando desde la tabla viva
# sap_faglflext (mismo mecanismo de siempre, fetch_cuenta), con el riesgo ya documentado de
# reclasificación de ejercicios cerrados (ver nota de Variación de Precios). Corregir esto
# usando un snapshot real en cuanto exista uno tomado en un cierre (el próximo: dic. 2026).
#
# Ninguno de estos reportes está validado contra SAP en vivo todavía más allá de lo ya
# documentado por cuenta abajo -- toda validación adicional hasta ahora es autoconsistencia
# interna de BigQuery. No marcar ningún reporte como "confirmado" sin ese cruce.

# Cuentas contables. Editable: para agregar una cuenta nueva basta con añadir una
# entrada aquí (nombre -> lista de RACCT). No se necesita tocar el resto del código.
CUENTAS = {
    "Mermas": ["0005010628"],
    "Variación de Precios": ["0005010632"],
    "Gastos no Deducibles": ["0005020000"],
}

# Solo se generan las cuentas listadas aquí. El usuario pidió limitarse a
# "Gastos no Deducibles" por ahora porque es la única consulta 100% corroborada;
# las demás se activan a medida que se validen sus queries.
CUENTAS_ACTIVAS = ["Gastos no Deducibles"]

# El mapeo RBUKRS -> nombre de sociedad ya NO se hardcodea aquí: se carga en tiempo de
# ejecución desde D20_DIMENSION.dm_company (ver datos.fetch_sociedades). SKAT es el
# catálogo de cuentas contables, no de sociedades, así que no aplica para esto.

# --- Variación de Precios ----------------------------------------------------------
# Usa el mismo mecanismo genérico que Gastos no Deducibles (fetch_cuenta: neto directo,
# sin ajustar signo por DRCRK) y el mismo formato único de reporte (build_section, ver
# arriba) -- cuenta 0005010632 (ya en CUENTAS de arriba). No se agregó a CUENTAS_ACTIVAS:
# generar_reporte.py y enviar_reporte.py la insertan explícitamente al final (después de
# Descuentos y Bonificaciones) para mantener el orden de secciones Gastos no Deducibles ->
# Descuentos y Bonificaciones -> Variación de Precios. A diferencia de Gastos no Deducibles,
# usa el catálogo SOCIEDADES de abajo (no fetch_sociedades/dm_company) para el nombre de
# empresa, por instrucción explícita del usuario.
#
# Validación: a diferencia de Gastos no Deducibles y Descuentos (validados contra el Excel
# de finanzas), el Excel de "Variación de precios" de finanzas NO es fiable para esta cuenta:
# hay sociedades exactas (PAT, MPE) y otras a cientos de millones de distancia o con signo
# contrario (GSI, PAN, AME), sin un patrón explicable por fecha de corte. La fuente de verdad
# validada es el árbol nativo de SAP ("Estado financiero Pérdidas y ganancias", columna
# TotPerComp/TotPerInf), donde esta fórmula coincidió al centavo en las 17 sociedades para
# el año cerrado 2023. Si hace falta re-validar esta cuenta, comparar contra ese árbol de
# SAP, no contra el Excel de finanzas.
#
# Limitación conocida (sin confirmar del todo): hay indicios de que esta cuenta podría
# reclasificarse/sanearse en el cierre anual, lo que podría hacer que el saldo del año en
# curso baje o llegue a cero después del cierre. No afecta al reporte diario en producción
# (que siempre mira el año aún no cerrado), pero si se detectan saltos raros en la columna
# "año actual" al pasar de un año a otro, revisar este comportamiento antes de asumir un bug.

# --- Descuentos y Bonificaciones -------------------------------------------------
# No usa CUENTAS/CUENTAS_ACTIVAS: en vez de una lista fija de RACCT, cubre un RANGO
# de cuentas de Ventas y clasifica cada cuenta como Ingreso o Descuento según el signo
# de su saldo neto (ver datos.fetch_descuentos). Se genera siempre, junto con las
# cuentas activas de arriba, en el mismo PDF.
RACCT_PREFIX_DESCUENTOS = "000401"

# Catálogo RBUKRS -> nombre comercial, confirmado contra el árbol de SAP y validado
# específicamente para este reporte (13-14 de 17 sociedades exactas contra el Excel
# de finanzas en 2022 y 2023). No se usa fetch_sociedades/dm_company aquí porque ese
# catálogo trae nombres en mayúsculas y a veces truncados (BUTXT a 25 caracteres).
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
    "PIN": "Sociedad no identificada (PIN)",  # importe residual histórico, revisar si sigue activa
}
# Nota: el código real de "Superdoña Comercial" (aparece en el Excel de finanzas) no se
# ha podido confirmar contra RBUKRS. No inventar un código; añadir aquí cuando se identifique.

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

# --- Envío de correo ---------------------------------------------------------------
EMAIL_DESTINATARIO_DEFAULT = "luciaggx4@gmail.com"
EMAIL_ASUNTO_TEMPLATE = "Reporte diario cuentas contables PROAN - {fecha}"
EMAIL_CUERPO_TEMPLATE = (
    "Hola Luis Enrique,\n\n"
    "Adjunto el reporte diario de cuentas contables PROAN correspondiente al {fecha}, "
    "con las secciones de Gastos no Deducibles, Descuentos y Bonificaciones y Variación "
    "de Precios.\n\n"
    "Saludos."
)

# Doble uso:
# 1) Filtro de fila (datos.fetch_cuenta): una sociedad sin actividad material ni en el
#    periodo actual ni en el anterior (por debajo de este umbral en ambos) no aparece en
#    el reporte del día.
# 2) Base para el % de variación (pdf._pct_o_100): si |anterior| está por debajo de este
#    umbral, la división produciría un % absurdo (ej. -18,725,722,200%) o directamente no
#    hay base -- en ese caso se muestra +100.00%/-100.00% en vez de calcularlo (ver nota
#    de "Formato único" arriba). Ya NO se muestra "N/A" en la tabla/tarjetas por esta causa.
UMBRAL_MATERIALIDAD_MXN = 1000

OUTPUT_DIR = r"C:\Users\Lucia\proan_reporte_diario\salidas"
