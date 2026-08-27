"""Configuración del reporte diario de cuentas contables PROAN."""

import os

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))

PROJECT_ID = "proan-quantrue"
# Cambiado 2026-08-21: antes `sap_faglflext`. `sap_faglflext_rt` es la misma tabla (esquema
# idéntico verificado en BigQuery, mismo filtro 0L/0/001, mismos saldos por sociedad) pero se
# actualiza con mayor frecuencia -- confirmado con una comparación de saldos y conteo de filas
# por sociedad contra `sap_faglflext` antes de cambiarla (diff = 0 en todas, _rt con algunas
# filas más recientes).
TABLE_FQN = "`proan-quantrue.D30_INTEGRATION.sap_faglflext_rt`"

# Filtros fijos usados en la consulta validada por el usuario para Gastos no Deducibles.
# Verificado en BigQuery (2026-08): las 417,443 filas de sap_faglflext (ahora sap_faglflext_rt)
# tienen exactamente esta combinación (0L / 0 / 001) -- la tabla no trae otra, así que estos
# filtros son redundantes hoy. Se dejan de todos modos por seguridad ante un cambio futuro de
# datos.
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
# sap_faglflext_rt (mismo mecanismo de siempre, fetch_cuenta), con el riesgo ya documentado de
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
    # Agregada 2026-08-27 a pedido del usuario ("cuenta de pasivo temporal... creo que el
    # número es 209000"). Confirmada en el catálogo D00_SANDBOX.proan_SKAT_20260804: plan
    # PROA, SAKNR 0002090000, TXT50 "Pasivo Temporal" -- coincide exacto con lo pedido (no
    # confundir con 0002090001 "IEPS No Desglosado", vecina en el mismo prefijo). Es
    # justamente la cuenta del prototipo "Reporte Pasivo Temporal" que ya se menciona como
    # referencia del formato único más arriba -- por eso "de la misma forma" es Plantilla A
    # (banner + KPIs + gráfico + tabla), igual que Gastos no Deducibles, sin ABS() ni
    # CUENTAS_SOLO_DEBE (neto Debe-Haber directo, dígito 2 = Pasivo, se valida igual que las
    # demás de este tipo). Datos reales en sap_faglflext_rt confirmados antes de activarla
    # (17 sociedades con saldo material en 2026, todas en negativo -- convención SAP estándar
    # para Pasivo).
    "Pasivo Temporal": ["0002090000"],
}

# Solo se generan las cuentas listadas aquí; las demás se activan a medida que se validen
# sus queries. Mermas (0005010628) se activó como "Plantilla A" (cuenta única, igual
# formato que Gastos no Deducibles). Igual que Gastos no Deducibles: dígito 5 (egresos),
# sin ABS(), tabla viva (mismo criterio que el resto -- ver nota de snapshot pendiente
# más abajo). Pasivo Temporal se insertó ANTES de "Mermas" (no al final de la lista):
# generar_reporte.py/enviar_reporte.py agregan la sección "Mermas ratio" inmediatamente
# después de terminar este bucle, así que Mermas tiene que seguir siendo la ÚLTIMA entrada
# aquí para que sus dos formas (importe/razón) queden en páginas contiguas -- si se agrega
# otra cuenta a este bucle en el futuro, ponerla antes de "Mermas", nunca después.
CUENTAS_ACTIVAS = ["Gastos no Deducibles", "Pasivo Temporal", "Mermas"]

# --- Dos formas de reportar la misma cuenta: importe vs. razón ----------------------
# Mermas y Descuentos/Bonificaciones se emiten AMBAS en las dos formas, en secciones
# contiguas del mismo PDF, porque no está decidido cuál es la correcta y finanzas tiene que
# elegir viéndolas lado a lado (instrucción explícita del usuario, 2026-08-17):
#
#   Importe -- solo la cantidad económica de la cuenta en cada sociedad (Plantilla A:
#     actual vs. anterior, diferencia, % variación entre periodos). Es lo que ya hacía
#     Mermas.
#   Razón   -- la cuenta comparada contra su base (Plantilla B: base, cuenta, % sobre la
#     base, en los dos periodos). Es lo que ya hacía Descuentos (descuentos/ingresos).
#     Para Mermas la base es el Costo Total (ver RACCT_PREFIX_COSTOS).
#
# Las dos variantes de una cuenta salen de la MISMA query -- no se consulta BigQuery dos
# veces por cuenta.
TITULOS_SECCION = {
    "Mermas": "Mermas — Importe",
    "Mermas ratio": "Mermas — % sobre Costo Total",
    "Descuentos importe": "Descuentos y Bonificaciones — Importe",
    "Descuentos ratio": "Descuentos y Bonificaciones — % sobre Ingresos",
}

# Denominador de la razón de Mermas ("Costo Total" en el Excel de finanzas y nodo "Costos"
# del árbol de ZF01). CONFIRMADO 2026-08-17, después de haber quedado sin resolver antes:
#
# 1. El grupo de cuentas de SAP (KTOKS en el catálogo SKA1, plan PROA) parte los egresos en
#    exactamente dos: CTOS = "Costos", cuentas 0005040100-0005041999 (77 cuentas, todas con
#    prefijo 000504), y GAGE = "Gastos generales", que es todo el resto (000501/000502/
#    000503). Eso corresponde 1:1 con los dos únicos hijos de EGRESOS en el árbol de ZF01
#    ("Costos" y "Gastos generales"). El catálogo se usó SOLO para obtener la lista de
#    cuentas; todos los importes de este reporte salen de sap_faglflext_rt y nada más.
# 2. Validado contra el Excel de finanzas "Mermas" (FY2024, con corte en el periodo 7):
#    la suma de 000504% cuadra AL PESO en 9 sociedades -- CCP 657,173,985 · GSI
#    6,252,798,495 · AME 610,530,076 · PAL 585,236,860 · MPE 284,112,661 · HEGP 232,217,290
#    · PAT 196,556,110 · PFO 99,475,133 · ABP 53,486,260. Solo PAN, PRA y ROMM difieren
#    (0.7%-13%), consistente con reclasificación posterior a la fecha del Excel (la propia
#    cuenta de Mermas de PAN también se movió: la captura de FS10N del PDF dice
#    $290,209,977 de Debe en 2024 y hoy la tabla viva dice $307,008,768).
#
# Ojo al usar ese Excel como referencia otra vez: sus columnas históricas están CORRIDAS UN
# AÑO (la rotulada "2023" contiene FY2022, "2022" contiene FY2021, "2021" contiene FY2020),
# mientras la rotulada "2024" sí es FY2024 pero parcial -- Mermas cortada en el periodo 6 y
# Costo Total en el 7, porque salen de dos transacciones distintas (FS10N y ZF01) capturadas
# en fechas distintas. Se comprobó al céntimo: Mermas de PAN en el Excel es 214,333,515.82
# (FY2020), 259,314,242.10 (FY2021), 447,023,995.65 (FY2022) y 157,427,250.71 (FY2024 p1-6).
# Comparar contra la columna que le toca por AÑO FISCAL, no por su rótulo.
RACCT_PREFIX_COSTOS = "000504"

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
# CONFIRMADO 2026-08-17 (antes estaba anotado aquí como sospecha "sin confirmar del todo"):
# el cierre anual SÍ reclasifica esta cuenta. Se avisó al usuario y su decisión (2026-08-17,
# reafirmada) es mantener de todos modos el MISMO formato que el resto de cuentas: año en curso
# vs. año anterior (Plantilla A), para que las cuatro cuentas tengan las mismas columnas. La
# sección lleva NOTA_PRECIOS al pie para que quien lea el PDF sepa interpretar los ±100%.
# La evidencia es el árbol de ZF01 del PDF "Variación de precios.pdf" (carpeta Reportes
# documentos), corrido el 13/12/2024 sobre el ejercicio 2024:
#
#   sociedad        árbol ZF01 al 13/12/2024      faglflext hoy (mismo FY2024)
#   GSI                     2,726,129.94                          0.00
#   PAL                    12,289,508.60                          0.00
#   PRA                    13,341,938.14                          0.00
#   AME                      -235,827.68                          0.00
#   PAN                   322,035,076.78                243,288,299.77
#
# O sea: el dato de un ejercicio ya cerrado cambia después de cerrado, y en la mayoría de
# sociedades se barre a 0.00 exacto. Comparar el año en curso contra ese residuo medía el
# cierre, no la variación de precios: producía ±100% en 9 de 12 filas y cosas como -236%.
#
# Lo que sí quedó validado de esta cuenta (no tocar sin repetir la comprobación): el neto de
# HSL01..16 reproduce el árbol de ZF01 AL CENTAVO en las 16 sociedades del ejercicio 2023
# (AME 253,501,755.08 · PAN 413,316,906.54 · PAL -1,616,613.12 · PAT 54,937.56 · CCP 1,403.32
# · ISE -53.73 · MPE -401.01 · ROMM -23,159.65 · SAP 2,813.78 · BAG 0.01, y las seis que el
# árbol pone en 0.00 salen 0.00). Además HSLVT (arrastre) es 0 en todas las filas de esta
# cuenta, y el criterio correcto es el NETO, no "solo Debe" como en Mermas: el Debe de esta
# cuenta es absurdo (PFO en 2023: $190,420,303,924 de Debe con neto 0).
#
# Nota al pie de la sección (pdf.build_section acepta `nota`). Explica los ±100% sin cambiar el
# formato: con datos de 2026, solo 3 de las 12 sociedades con movimiento tienen base material en
# 2025 (PAN $190.6M, ROMM -$3.0M, MPE $54.7k en Ene-Ago; el resto exactamente 0.00), así que la
# mayoría de filas cae en la convención +100%/-100% de _pct_o_100. No es un error de cálculo.
NOTA_PRECIOS = (
    "Muchas sociedades muestran ±100.0% porque su saldo de {prior_year} es cero: el cierre "
    "anual reclasifica esta cuenta y borra del ejercicio ya cerrado movimientos que sí existían "
    "cuando el año estaba abierto (comprobado contra el árbol de SAP: sociedades con saldo a "
    "diciembre aparecen hoy en 0.00 para ese mismo ejercicio). En esas filas el % indica "
    "\"no había base el año anterior\", no una variación real de precios; la cifra fiable es la "
    "columna del año en curso."
)

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
    "PIN": "Perfil Integral",  # identificada 2026-08-17 vía dm_company ("PERFIL INTEGRAL SA DE CV")
    "SCO1": "Superdoña Comercial",  # confirmado vía dm_company (plan de cuentas PCSD)
}

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

# --- Destinatarios: lista administrada en Firestore ---------------------------------------
# Fuente unica: el documento lists/reportes-financieros de la base proan-lista-mails
# (compartido por los tres reportes financieros). Se lee con get_mailing_list() en
# enviar_reporte.py. Ya no hay cascada a variable de entorno ni tupla hardcodeada.
FIRESTORE_DATABASE_ID = os.environ.get("FIRESTORE_DATABASE_ID", "proan-lista-mails").strip()
FIRESTORE_LISTS_COLLECTION = os.environ.get("FIRESTORE_LISTS_COLLECTION", "lists").strip()
REPORTE_CUENTAS_LIST_ID = os.environ.get("REPORTE_CUENTAS_LIST_ID", "reportes-financieros").strip()
# Los destinatarios ya NO viven en el codigo: se administran en el documento de
# Firestore lists/reportes-financieros (base proan-lista-mails). Ver get_mailing_list()
# en enviar_reporte.py. Se retiraron EMAIL_DESTINATARIO_DEFAULT y
# DEFAULT_EMAIL_RECIPIENTS el 2026-08-20 para que no quede una copia de los correos
# aqui que pueda desincronizarse de la lista real.
EMAIL_ASUNTO_TEMPLATE = "Reporte diario cuentas contables PROAN - {fecha}"
EMAIL_CUERPO_TEMPLATE = (
    "Hola Luis Enrique,\n\n"
    "Adjunto el reporte diario de cuentas contables PROAN correspondiente al {fecha}, "
    "con las secciones de Gastos no Deducibles, Pasivo Temporal, Mermas, Descuentos y "
    "Bonificaciones y Variación de Precios.\n\n"
    "Mermas y Descuentos van cada una en DOS formas, en secciones seguidas: el importe de "
    "la cuenta por sociedad, y la misma cuenta como porcentaje sobre su base (Mermas sobre "
    "el Costo Total, Descuentos sobre los Ingresos). Están las dos porque no está definido "
    "cuál de los dos criterios es el correcto — agradecemos que nos indiquen cuál usar para "
    "dejar solo ese.\n\n"
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

# Local (Windows, ejecución manual): carpeta fija de Lucia. Cloud Run (Linux, filesystem de
# solo lectura salvo /tmp): se sobreescribe con la variable de entorno OUTPUT_DIR=/tmp/salidas
# (ver deploy.sh) -- el contenedor no tiene "C:\Users\Lucia\..." y tampoco hace falta
# persistir el PDF entre ejecuciones, /tmp alcanza para generarlo y adjuntarlo al correo.
OUTPUT_DIR = os.environ.get("OUTPUT_DIR", r"C:\Users\Lucia\proan_reporte_diario\salidas")
