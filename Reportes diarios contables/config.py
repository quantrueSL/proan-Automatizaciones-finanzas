"""Configuración del reporte diario de cuentas contables PROAN."""

import os

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))

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

# Solo se generan las cuentas listadas aquí; las demás se activan a medida que se validen
# sus queries. Mermas (0005010628) se activó como "Plantilla A" (cuenta única, igual
# formato que Gastos no Deducibles) -- se abandonó el reporte de razón Mermas/Costo Total
# porque nunca se logró confirmar con certeza qué cuentas conforman "Costo Total" (varias
# hipótesis probadas, ninguna validada). Mejor un dato de Mermas solo, correcto y
# validable, que un % apoyado en un denominador no confirmado. Si en el futuro se
# confirma el denominador, se puede agregar esa razón como reporte aparte -- no reemplaza
# a este. Igual que Gastos no Deducibles: dígito 5 (egresos), sin ABS(), tabla viva (mismo
# criterio que el resto -- ver nota de snapshot pendiente más abajo).
CUENTAS_ACTIVAS = ["Gastos no Deducibles", "Mermas"]

# Cuentas que deben sumarse SOLO Debe (DRCRK='S'), no neto Debe-Haber (ver datos.build_query).
# Confirmado con datos reales (2026-08) para Mermas (0005010628): esta cuenta recibe
# reclasificaciones/correcciones en Haber que casi cancelan el Debe original -- ej. Proteína
# Animal 2025: Debe $274,816,762 vs. Haber -$274,759,261 -> neto solo $57,501; en
# DBC/HEGP/PAL/SAP el Debe y el Haber son EXACTAMENTE iguales -> neto $0 pese a haber varios
# millones de mermas reales. Es la causa real de los % disparatados (+57,573% etc.) del
# primer PDF de Mermas: no es que las mermas hayan crecido tanto, es que "anterior" (neto)
# estaba mal calculado -- le faltaba casi todo el Debe real. El proceso manual de referencia
# (FS10N, "sumo las columnas del Debe") nunca resta el Haber, por eso daba números
# completamente distintos al reporte automático -- no por redondeo, sino porque se estaban
# calculando cosas diferentes. No se aplica a Gastos no Deducibles ni Variación de Precios:
# esas sí se validaron con la fórmula neta contra Excel/árbol de SAP -- cambiarles esto
# rompería esa validación. Si en el futuro se ve un patrón raro similar en Variación de
# Precios (ver su nota de "reclasificación en cierre" más abajo), vale la pena revisar si es
# el mismo fenómeno -- pero no se asuma sin repetir esta misma verificación con datos reales.
CUENTAS_SOLO_DEBE = {"Mermas"}

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

# Paleta "navy" (2026-08, v2 -- reemplaza la "firma dorada" anterior por pedido explícito del
# usuario de un tema monocromático azul marino), validada con scripts/validate_palette.js
# (skill dataviz) contra fondo blanco puro #FFFFFF. Sustituir aquí si Proan tiene hex de marca
# oficiales distintos. Notas de validación:
# - actual/anterior (barras): separación CVD ΔE ~43 (protan/tritan), muy por encima del piso
#   de 6-8 -- el contraste de luminosidad (navy profundo vs. azul grisáceo claro) es enorme,
#   así que se distinguen bien incluso para daltonismo. El validador marca "chroma floor" y
#   "lightness band" como FAIL, pero esos checks asumen dos colores igual de vívidos para
#   codificar identidad (categórico); aquí es intencional que uno sea oscuro sólido y el otro
#   claro/neutro (jerarquía "periodo actual" vs. "periodo anterior", no dos identidades pares).
# - good/critical (semáforo verde/rojo, sin cambios respecto a la paleta dorada): la separación
#   CVD da ΔE 5.8, por debajo del piso de 6.0 -- limitación conocida e inherente al par
#   rojo/verde en sí. Mitigado con signo explícito en texto + barra lateral por fila (ver
#   pdf._tabla_sociedades), nunca color solo.
# - pct_line (línea de % variación): antes reutilizaba "critical" (rojo) -- se separó en su
#   propio token porque un color de serie de datos no debe doblar como color de estado
#   (good/critical quedan reservados para signo, nunca para identidad de serie).
COLORS = {
    "header_bg": "#0d2a4a",       # banda de encabezado (chrome, no dato) -- sin cambios
    "header_accent": "#184F95",   # navy medio: borde superior de tarjetas KPI + línea bajo
                                   # el header (antes dorado #B8860B; el usuario pidió tema
                                   # monocromático navy, sin acento dorado)
    "actual": "#0d2a4a",          # barra "periodo actual/hoy": navy profundo (antes #184F95,
                                   # ese tono pasó a pct_line)
    "anterior": "#8CA5C4",        # barra "periodo anterior": azul grisáceo claro (antes #4E7AB5)
    "pct_line": "#184F95",        # línea de % variación + círculos "N/A" + anotaciones de
                                   # recorte en el gráfico: navy medio (antes "critical"/rojo)
    "good": "#1B7F4C",            # verde tinta contable -- sin cambios
    "critical": "#B3261E",        # rojo sobrio -- sin cambios; reservado para signo, ya no
                                   # se usa para la línea del gráfico (ver pct_line)
    "text_primary": "#0b0b0b",
    "text_secondary": "#3F4550",  # gris grafito, frío
    "muted": "#6B7280",           # gris grafito claro, frío
    "grid": "#EDEEF1",            # línea guía horizontal muy tenue
    "surface": "#FFFFFF",         # blanco puro -- fondo de página, sin cambios
    "tile_bg": "#F5F7FA",         # tinte sutil navy: filas alternas de tabla, relleno de
                                   # tarjetas KPI y panel del gráfico (antes blanco/gris parejo)
    "kpi_border": "#C9D6E5",      # borde fino de las tarjetas KPI, tinte navy (antes gris
                                   # neutro #E2E5EA)
}

# Fuentes: familia IBM Plex completa, embebida en el PDF (carpeta fonts/, con su LICENSE.txt
# de IBM y la OFL.txt de Google Fonts -- ambas son la misma licencia SIL Open Font License,
# solo se descargaron de fuentes distintas, ver nota abajo). Al embeber el TTF en el PDF, se
# ve igual en cualquier sistema operativo, no depende de qué fuentes tenga instaladas quien
# lo abra (a diferencia de Segoe UI, que solo está en Windows).
# - IBM Plex Sans (Regular/Bold): títulos, encabezados y cuerpo. Primer intento fue bajarla
#   del mirror de Google Fonts en GitHub (google/fonts), pero ahí solo está como variable
#   font (un archivo con eje de peso, sin instances estáticos) -- ReportLab no puede
#   seleccionar "Bold" de una variable font. Se consiguió en su forma estática correcta
#   desde el repo OFICIAL de IBM (github.com/IBM/plex, packages/plex-sans/fonts/complete/ttf).
# - IBM Plex Mono (Regular/Bold): cifras de tarjetas KPI y columnas numéricas de tabla --
#   monoespaciada, alinea decimales de forma natural, look "dashboard". Esta sí estaba
#   disponible como estática en el mirror de Google Fonts, se dejó de ahí.
# Fallback: si por lo que sea faltan los archivos, pdf.py cae a Helvetica/Courier (siempre
# disponibles en ReportLab) en vez de romper.
FONT_REGULAR_TTF = os.path.join(_BASE_DIR, "fonts", "IBMPlexSans-Regular.ttf")
FONT_BOLD_TTF = os.path.join(_BASE_DIR, "fonts", "IBMPlexSans-Bold.ttf")
FONT_MONO_TTF = os.path.join(_BASE_DIR, "fonts", "IBMPlexMono-Regular.ttf")
FONT_MONO_BOLD_TTF = os.path.join(_BASE_DIR, "fonts", "IBMPlexMono-Bold.ttf")

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
