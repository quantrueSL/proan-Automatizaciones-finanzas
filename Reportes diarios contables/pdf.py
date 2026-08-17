"""Ensamblado del PDF final: banda de encabezado, tarjetas KPI redondeadas, gráfico
y tabla, una sección por cuenta contable. Color por signo: positivo = verde, negativo = rojo."""

import os

from reportlab.lib.pagesizes import letter
from reportlab.lib.units import mm
from reportlab.lib import colors as rl_colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image, PageBreak, Flowable,
)
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT

from config import (
    COLORS, FONT_REGULAR_TTF, FONT_BOLD_TTF, FONT_MONO_TTF, FONT_MONO_BOLD_TTF,
    UMBRAL_MATERIALIDAD_MXN,
)

C = {k: rl_colors.HexColor(v) for k, v in COLORS.items()}

FONT_REGULAR, FONT_BOLD = "Helvetica", "Helvetica-Bold"
if os.path.exists(FONT_REGULAR_TTF) and os.path.exists(FONT_BOLD_TTF):
    pdfmetrics.registerFont(TTFont("IBM Plex Sans", FONT_REGULAR_TTF))
    pdfmetrics.registerFont(TTFont("IBM Plex Sans Bold", FONT_BOLD_TTF))
    FONT_REGULAR, FONT_BOLD = "IBM Plex Sans", "IBM Plex Sans Bold"

# Monoespaciada para cifras (tarjetas KPI + columnas numéricas de tabla): alinea decimales
# de forma natural, look "dashboard". IBM Plex Mono se embebe desde Reportes diarios
# contables/fonts/ (ver nota en config.py sobre por qué no se pudo embeber Inter/Plex Sans
# para los títulos). Si el archivo no está, cae a Courier (monoespaciada, siempre disponible
# en ReportLab) en vez de romper.
FONT_MONO, FONT_MONO_BOLD = "Courier", "Courier-Bold"
if os.path.exists(FONT_MONO_TTF) and os.path.exists(FONT_MONO_BOLD_TTF):
    pdfmetrics.registerFont(TTFont("IBM Plex Mono", FONT_MONO_TTF))
    pdfmetrics.registerFont(TTFont("IBM Plex Mono Bold", FONT_MONO_BOLD_TTF))
    FONT_MONO, FONT_MONO_BOLD = "IBM Plex Mono", "IBM Plex Mono Bold"

_STYLE_TITLE = ParagraphStyle("titulo", fontName=FONT_BOLD, fontSize=17,
                               textColor=rl_colors.white, leading=20)
_STYLE_SUBTITLE = ParagraphStyle("subtitulo", fontName=FONT_REGULAR, fontSize=9,
                                  textColor=rl_colors.HexColor("#c9d6e5"), leading=12)

# Estilos de celda para tablas con encabezados/nombres largos (Descuentos y Bonificaciones):
# usar Paragraph en vez de strings planos evita que el texto se desborde sobre la columna
# vecina cuando no cabe (los strings planos en Table no hacen wrap).
_STYLE_TH = ParagraphStyle("th", fontName=FONT_BOLD, fontSize=7,
                            textColor=rl_colors.white, leading=8.5, alignment=TA_CENTER)
_STYLE_TH_LEFT = ParagraphStyle("th_left", parent=_STYLE_TH, alignment=TA_LEFT)
_STYLE_TD = ParagraphStyle("td", fontName=FONT_REGULAR, fontSize=7.5,
                            textColor=C["text_primary"], leading=9, alignment=TA_RIGHT)
_STYLE_TD_LEFT = ParagraphStyle("td_left", parent=_STYLE_TD, alignment=TA_LEFT)
_STYLE_TD_BOLD = ParagraphStyle("td_bold", parent=_STYLE_TD, fontName=FONT_BOLD)
_STYLE_TD_BOLD_LEFT = ParagraphStyle("td_bold_left", parent=_STYLE_TD_BOLD, alignment=TA_LEFT)
# Variantes monoespaciadas, solo para cifras (nunca para texto corrido/nombres). Tamaño más
# chico que _STYLE_TD (6.5 vs 7.5): IBM Plex Mono es más ancha por carácter que la Sans, y
# en _tabla_descuentos (7 columnas, cifras hasta miles de millones) el tamaño de _STYLE_TD
# hacía que los valores más largos ("$35,254,498,702") envolvieran a dos líneas y la tabla
# se corriera a una página extra (visto con datos reales).
_STYLE_TD_MONO = ParagraphStyle("td_mono", parent=_STYLE_TD, fontName=FONT_MONO, fontSize=6.5, leading=7.8)
# El bold es un poco más ancho por carácter que el regular al mismo tamaño -- en la fila
# TOTAL GENERAL (donde vive el valor más grande de cada columna) eso alcanzaba a envolver
# a dos líneas; un punto menos de tamaño lo evita sin verse desigual junto al resto.
_STYLE_TD_MONO_BOLD = ParagraphStyle("td_mono_bold", parent=_STYLE_TD_MONO, fontName=FONT_MONO_BOLD, fontSize=6.2)
# Nota al pie de sección (build_section acepta `nota`). Hoy solo la usa Variación de Precios,
# para explicar por qué esa cuenta muestra tantos ±100% sin cambiarle el formato.
_STYLE_NOTA = ParagraphStyle("nota", fontName=FONT_REGULAR, fontSize=7,
                              textColor=C["muted"], leading=9.5, alignment=TA_LEFT)


def _signo_color(v):
    if v != v:  # NaN
        return C["muted"]
    return C["good"] if v >= 0 else C["critical"]


def _money(v):
    signo = "-" if v < 0 else ""
    return f"{signo}${abs(v):,.0f}"


def _pct(v):
    if v != v:
        return "N/A"
    return f"{v:+.1%}"


def _pct_o_100(diferencia, base):
    """Diferencia/abs(base), pero sin división por ~cero: si el periodo base (normalmente
    el anterior) está por debajo del umbral de materialidad, se considera "creció/cayó desde
    cero" y se muestra +100.00%/-100.00% en vez de N/A. Convención del formato único de
    reporte (dashboard tipo Pasivo Temporal), pedida explícitamente por el usuario para no
    calcular una división por cero."""
    if abs(base) < UMBRAL_MATERIALIDAD_MXN:
        return 1.0 if diferencia >= 0 else -1.0
    return diferencia / abs(base)


class StatTile(Flowable):
    """Tarjeta KPI: relleno navy muy tenue (no blanco puro, no gris parejo), borde fino
    navy y línea de acento navy arriba -- el acento es SIEMPRE ese mismo navy medio (igual
    en las 4 tarjetas de los 4 reportes, tema monocromático); solo la cifra cambia de color
    según su signo. Cifra en monoespaciada."""

    def __init__(self, width, height, label, value, value_color):
        super().__init__()
        self.width = width
        self.height = height
        self.label = label
        self.value = value
        self.value_color = value_color

    def wrap(self, availWidth, availHeight):
        return self.width, self.height

    def draw(self):
        c = self.canv
        c.saveState()
        c.setFillColor(C["tile_bg"])
        c.setStrokeColor(C["kpi_border"])
        c.setLineWidth(0.75)
        c.roundRect(0, 0, self.width, self.height, 7, fill=1, stroke=1)
        c.setFillColor(C["header_accent"])
        c.roundRect(0, self.height - 3, self.width, 3, 1.5, fill=1, stroke=0)
        c.setFont(FONT_REGULAR, 7.3)
        c.setFillColor(C["muted"])
        c.drawString(13, self.height - 24, self.label.upper())

        # IBM Plex Mono es más ancha por carácter que la Segoe UI Bold que reemplaza -- un
        # valor largo (ej. "-$16,033,068") se salía de la tarjeta a tamaño fijo. Se encoge
        # hasta que quepa en vez de recortarse.
        max_value_width = self.width - 21
        font_size = 15.5
        while font_size > 9 and pdfmetrics.stringWidth(self.value, FONT_MONO_BOLD, font_size) > max_value_width:
            font_size -= 0.5
        c.setFont(FONT_MONO_BOLD, font_size)
        c.setFillColor(self.value_color)
        c.drawString(13, 15, self.value)
        c.restoreState()


class RoundedHeader(Flowable):
    """Banda de encabezado con esquinas superiores redondeadas."""

    def __init__(self, width, height, titulo, subtitulo):
        super().__init__()
        self.width = width
        self.height = height
        self.titulo = titulo
        self.subtitulo = subtitulo

    def wrap(self, availWidth, availHeight):
        return self.width, self.height

    def draw(self):
        c = self.canv
        c.saveState()
        c.setFillColor(C["header_bg"])
        c.roundRect(0, 0, self.width, self.height, 8, fill=1, stroke=0)
        c.rect(0, 0, self.width, self.height * 0.45, fill=1, stroke=0)  # cuadra las esquinas inferiores
        c.setFillColor(C["header_accent"])
        c.rect(0, 0, self.width, 3, fill=1, stroke=0)
        c.setFont(FONT_BOLD, 17)
        c.setFillColor(rl_colors.white)
        c.drawString(16, self.height - 30, self.titulo.upper())

        # El subtítulo se encoge hasta caber dentro de la banda en vez de derramarse fuera
        # (visto con Mermas — % sobre Costo Total, cuyo subtítulo nombra dos juegos de cuentas
        # y salía cortado a la mitad de "MXN"). Mismo criterio que StatTile con las cifras
        # largas: reducir tamaño antes que recortar el texto.
        max_sub_width = self.width - 32
        sub_size = 9
        while sub_size > 6 and pdfmetrics.stringWidth(self.subtitulo, FONT_REGULAR, sub_size) > max_sub_width:
            sub_size -= 0.25
        c.setFont(FONT_REGULAR, sub_size)
        c.setFillColor(rl_colors.HexColor("#c9d6e5"))
        c.drawString(16, self.height - 48, self.subtitulo)
        c.restoreState()


def _chart_panel(chart_path):
    """Envuelve el gráfico en un panel con borde navy fino -- el fondo del panel es el mismo
    tinte navy tenue que ya trae el propio PNG (fig.patch en graficos.py), así que el único
    elemento visible añadido aquí es el borde; queda "el gráfico dentro de un panel navy"
    sin costura entre el borde de la imagen y el panel."""
    img = Image(chart_path, width=176 * mm, height=66 * mm)
    tbl = Table([[img]], colWidths=[180 * mm])
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), C["tile_bg"]),
        ("BOX", (0, 0), (-1, -1), 0.75, C["kpi_border"]),
        ("LEFTPADDING", (0, 0), (-1, -1), 2 * mm),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2 * mm),
        ("TOPPADDING", (0, 0), (-1, -1), 1 * mm),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1 * mm),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
    ]))
    return tbl


def _header(cuenta_nombre, raccts, fecha_str):
    """Formato único de banner (referencia: reporte-cuentas-actual.png / "Pasivo Temporal"):
    título "REPORTE [CUENTA]" + subtítulo "CUENTA DE MAYOR: ... | SALDOS AL DÍA DE HOY...".
    RoundedHeader.draw() ya hace .upper() sobre el título, no hace falta aquí."""
    subtitulo = f"CUENTA DE MAYOR: {', '.join(raccts)}  |  SALDOS AL DÍA DE HOY ({fecha_str}), MXN"
    return [RoundedHeader(180 * mm, 26 * mm, f"Reporte {cuenta_nombre}", subtitulo)]


def _stat_tiles(total_actual, total_anterior, current_year, prior_year):
    diferencia = total_actual - total_anterior
    pct = _pct_o_100(diferencia, total_anterior)

    tile_w, tile_h, gap = 43 * mm, 22 * mm, 2 * mm
    tiles_data = [
        (f"Total {current_year} (hoy)", _money(total_actual), C["text_primary"]),
        (f"Total {prior_year}", _money(total_anterior), C["text_primary"]),
        ("Diferencia total", _money(diferencia), _signo_color(diferencia)),
        ("% Variación global", _pct(pct), _signo_color(pct)),
    ]
    tiles = [StatTile(tile_w, tile_h, label, value, color) for label, value, color in tiles_data]
    tbl = Table([tiles], colWidths=[tile_w] * 4, rowHeights=[tile_h])
    tbl.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), gap),
        ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    return tbl


def _tabla_sociedades(df, current_year, prior_year):
    """Orden de columnas (actual antes que anterior) igual al formato de referencia
    "Pasivo Temporal": Sociedad | [actual] | [anterior] | Diferencias | % Variac.

    Columna 0 (sin encabezado, muy angosta): barra de color sólida por fila -- verde/rojo
    según el signo de la diferencia (elemento firma, ver COLORS). Refuerza el semáforo
    además del texto coloreado en Diferencias/%Variac -- no lo reemplaza, porque el par
    verde/rojo no alcanza el piso de separación para daltonismo por sí solo (ver nota de
    validación en config.py junto a COLORS)."""
    header = ["", "Sociedad", f"{current_year} (HOY)", f"{prior_year}", "Diferencias", "% Variac."]
    rows = [header]
    df_ordenado = df.sort_values("actual", ascending=False, key=abs)
    for _, r in df_ordenado.iterrows():
        pct = _pct_o_100(r["diferencia"], r["anterior"])
        rows.append(["", r["nombre_sociedad"], _money(r["actual"]), _money(r["anterior"]),
                     _money(r["diferencia"]), _pct(pct)])

    total_actual = df["actual"].sum()
    total_anterior = df["anterior"].sum()
    total_dif = total_actual - total_anterior
    total_pct = _pct_o_100(total_dif, total_anterior)
    rows.append(["", "TOTAL GENERAL", _money(total_actual), _money(total_anterior),
                 _money(total_dif), _pct(total_pct)])

    n_rows = len(rows)
    tbl = Table(rows, colWidths=[2.2 * mm, 52.8 * mm, 32 * mm, 32 * mm, 32 * mm, 24 * mm], repeatRows=1)
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), C["header_bg"]),
        ("TEXTCOLOR", (0, 0), (-1, 0), rl_colors.white),
        ("FONTNAME", (1, 0), (-1, 0), FONT_BOLD),
        ("FONTNAME", (1, 1), (1, -1), FONT_REGULAR),       # Sociedad: sans-serif, cuerpo
        ("FONTNAME", (2, 1), (-1, -2), FONT_MONO),         # cifras: monoespaciada
        ("FONTNAME", (2, -1), (-1, -1), FONT_MONO_BOLD),   # cifras del TOTAL: mono bold
        ("FONTNAME", (1, -1), (1, -1), FONT_BOLD),         # "TOTAL GENERAL"
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("ALIGN", (2, 0), (-1, -1), "RIGHT"),
        ("ALIGN", (1, 0), (1, -1), "LEFT"),
        ("LINEBELOW", (0, 0), (-1, 0), 0, rl_colors.white),
        ("LINEBELOW", (0, 1), (-1, -2), 0.4, C["grid"]),
        ("LINEABOVE", (0, -1), (-1, -1), 0.8, C["text_primary"]),
        ("BACKGROUND", (1, -1), (-1, -1), C["tile_bg"]),
        ("TOPPADDING", (0, 0), (-1, -1), 3.2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3.2),
        ("TOPPADDING", (0, 0), (-1, 0), 6),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 6),
        ("TOPPADDING", (0, -1), (-1, -1), 5),
        ("BOTTOMPADDING", (0, -1), (-1, -1), 5),
        ("LEFTPADDING", (1, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("LEFTPADDING", (0, 0), (0, -1), 0),
        ("RIGHTPADDING", (0, 0), (0, -1), 0),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]
    # Franjas alternadas (excepto encabezado y fila de total) para lectura más fácil.
    for i in range(1, n_rows - 1):
        if i % 2 == 0:
            style.append(("BACKGROUND", (1, i), (-1, i), C["tile_bg"]))
    for i, r in df_ordenado.reset_index().iterrows():
        color = _signo_color(_pct_o_100(r["diferencia"], r["anterior"]))
        style.append(("TEXTCOLOR", (4, i + 1), (5, i + 1), color))
        style.append(("BACKGROUND", (0, i + 1), (0, i + 1), color))
    style.append(("BACKGROUND", (0, n_rows - 1), (0, n_rows - 1), _signo_color(total_pct)))
    tbl.setStyle(TableStyle(style))
    return tbl


def build_section(cuenta_nombre, raccts, df, chart_path, fecha_str, current_year, prior_year,
                  nota=None):
    """nota: texto opcional al pie de la sección. Se usa en Variación de Precios para advertir
    de por qué esa cuenta muestra tantos ±100% (el cierre anual barra el año previo, ver
    config.py) sin cambiarle el formato, que es igual al del resto de cuentas."""
    flow = []
    flow.extend(_header(cuenta_nombre, raccts, fecha_str))
    flow.append(Spacer(1, 7))
    flow.append(_stat_tiles(df["actual"].sum(), df["anterior"].sum(), current_year, prior_year))
    flow.append(Spacer(1, 8))
    flow.append(_chart_panel(chart_path))
    flow.append(Spacer(1, 8))
    flow.append(_tabla_sociedades(df, current_year, prior_year))
    if nota:
        flow.append(Spacer(1, 5))
        flow.append(Paragraph(nota, _STYLE_NOTA))
    return flow


def _header_ratio(titulo, subtitulo_fuente, fecha_str):
    subtitulo = f"{subtitulo_fuente}  |  AL DÍA DE HOY ({fecha_str}), MXN"
    return [RoundedHeader(180 * mm, 26 * mm, titulo, subtitulo)]


def _stat_tiles_ratio(base_total, cuenta_total, current_year, label_base, label_cuenta,
                      label_base_total, label_cuenta_total):
    """label_*_total: cómo se nombra el total en la tarjeta. Va aparte de label_* (que rotula
    las columnas de la tabla) porque no siempre es "<label> totales": "Costo Total totales"
    se leería mal, ahí el rótulo correcto es simplemente "Costo Total"."""
    pct = (cuenta_total / base_total) if base_total else float("nan")

    tile_w, tile_h, gap = 58 * mm, 22 * mm, 2 * mm
    tiles_data = [
        (f"{label_base_total} {current_year} (hoy)", _money(base_total), C["text_primary"]),
        (f"{label_cuenta_total} {current_year} (hoy)", _money(cuenta_total), C["text_primary"]),
        (f"% Global ({label_cuenta}/{label_base})", _pct(pct), C["text_primary"]),
    ]
    tiles = [StatTile(tile_w, tile_h, label, value, color) for label, value, color in tiles_data]
    tbl = Table([tiles], colWidths=[tile_w] * 3, rowHeights=[tile_h])
    tbl.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), gap),
        ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    return tbl


def _p(text, style):
    return Paragraph(str(text), style)


def _tabla_ratio(df, current_year, prior_year, label_base, label_cuenta, col_base, col_cuenta):
    header = ["Sociedad", f"{label_base} {prior_year}", f"{label_base} {current_year} (HOY)",
              f"{label_cuenta} {prior_year}", f"{label_cuenta} {current_year} (HOY)",
              f"% {prior_year}", f"% {current_year} (HOY)"]
    rows = [[_p(header[0], _STYLE_TH_LEFT)] + [_p(h, _STYLE_TH) for h in header[1:]]]

    df_ordenado = df.sort_values(f"{col_base}_actual", ascending=False, key=abs)
    for _, r in df_ordenado.iterrows():
        rows.append([
            _p(r["nombre_sociedad"], _STYLE_TD_LEFT),
            _p(_money(r[f"{col_base}_anterior"]), _STYLE_TD_MONO),
            _p(_money(r[f"{col_base}_actual"]), _STYLE_TD_MONO),
            _p(_money(r[f"{col_cuenta}_anterior"]), _STYLE_TD_MONO),
            _p(_money(r[f"{col_cuenta}_actual"]), _STYLE_TD_MONO),
            _p(_pct(r["pct_anterior"]), _STYLE_TD_MONO),
            _p(_pct(r["pct_actual"]), _STYLE_TD_MONO),
        ])

    total_base_actual = df[f"{col_base}_actual"].sum()
    total_base_anterior = df[f"{col_base}_anterior"].sum()
    total_cuenta_actual = df[f"{col_cuenta}_actual"].sum()
    total_cuenta_anterior = df[f"{col_cuenta}_anterior"].sum()
    total_pct_actual = (total_cuenta_actual / total_base_actual) if total_base_actual else float("nan")
    total_pct_anterior = (total_cuenta_anterior / total_base_anterior) if total_base_anterior else float("nan")
    rows.append([
        _p("TOTAL GENERAL", _STYLE_TD_BOLD_LEFT),
        _p(_money(total_base_anterior), _STYLE_TD_MONO_BOLD),
        _p(_money(total_base_actual), _STYLE_TD_MONO_BOLD),
        _p(_money(total_cuenta_anterior), _STYLE_TD_MONO_BOLD),
        _p(_money(total_cuenta_actual), _STYLE_TD_MONO_BOLD),
        _p(_pct(total_pct_anterior), _STYLE_TD_MONO_BOLD),
        _p(_pct(total_pct_actual), _STYLE_TD_MONO_BOLD),
    ])

    n_rows = len(rows)
    tbl = Table(rows, colWidths=[44 * mm, 25 * mm, 27 * mm, 22 * mm, 24 * mm, 17 * mm, 19 * mm], repeatRows=1)
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), C["header_bg"]),
        ("LINEBELOW", (0, 0), (-1, 0), 0, rl_colors.white),
        ("LINEBELOW", (0, 1), (-1, -2), 0.4, C["grid"]),
        ("LINEABOVE", (0, -1), (-1, -1), 0.8, C["text_primary"]),
        ("BACKGROUND", (0, -1), (-1, -1), C["tile_bg"]),
        ("TOPPADDING", (0, 0), (-1, -1), 3.2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3.2),
        ("TOPPADDING", (0, 0), (-1, 0), 6),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 6),
        ("TOPPADDING", (0, -1), (-1, -1), 5),
        ("BOTTOMPADDING", (0, -1), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]
    # Franjas alternadas (excepto encabezado y fila de total) para lectura más fácil.
    for i in range(1, n_rows - 1):
        if i % 2 == 0:
            style.append(("BACKGROUND", (0, i), (-1, i), C["tile_bg"]))
    tbl.setStyle(TableStyle(style))
    return tbl


def build_section_ratio(titulo, subtitulo_fuente, label_base, label_cuenta, df, chart_path,
                        fecha_str, current_year, prior_year, col_base, col_cuenta,
                        label_base_total=None, label_cuenta_total=None):
    """Plantilla B: una cuenta comparada contra su base, en los dos periodos. Era el formato
    exclusivo de Descuentos y Bonificaciones (descuentos/ingresos); se generalizó para que
    Mermas pueda emitirse igual contra el Costo Total (ver TITULOS_SECCION en config.py).
    df debe traer {col_base}_actual/_anterior, {col_cuenta}_actual/_anterior, pct_actual,
    pct_anterior y nombre_sociedad."""
    flow = []
    flow.extend(_header_ratio(titulo, subtitulo_fuente, fecha_str))
    flow.append(Spacer(1, 7))
    flow.append(_stat_tiles_ratio(df[f"{col_base}_actual"].sum(), df[f"{col_cuenta}_actual"].sum(),
                                  current_year, label_base, label_cuenta,
                                  label_base_total or f"{label_base} totales",
                                  label_cuenta_total or f"{label_cuenta} totales"))
    flow.append(Spacer(1, 8))
    flow.append(_chart_panel(chart_path))
    flow.append(Spacer(1, 8))
    flow.append(_tabla_ratio(df, current_year, prior_year, label_base, label_cuenta,
                             col_base, col_cuenta))
    return flow


def build_section_descuentos(df, chart_path, fecha_str, current_year, prior_year,
                             titulo="Descuentos y Bonificaciones"):
    return build_section_ratio(
        titulo, "CUENTAS DE VENTAS (RACCT 000401%)", "Ingresos", "Descuentos",
        df, chart_path, fecha_str, current_year, prior_year,
        col_base="ingresos", col_cuenta="descuentos",
    )


def build_section_mermas_ratio(df, chart_path, fecha_str, current_year, prior_year, raccts,
                               titulo="Mermas — % sobre Costo Total"):
    subtitulo = (f"MERMAS {', '.join(raccts)} (SOLO DEBE)  /  COSTO TOTAL: "
                 f"GRUPO CTOS (RACCT 000504%)")
    return build_section_ratio(
        titulo, subtitulo, "Costo Total", "Mermas",
        df, chart_path, fecha_str, current_year, prior_year,
        col_base="costo", col_cuenta="mermas",
        label_base_total="Costo Total", label_cuenta_total="Mermas totales",
    )


def build_pdf(sections, output_path):
    """sections: lista de listas de flowables ya construidas por build_section."""
    doc = SimpleDocTemplate(
        output_path, pagesize=letter,
        leftMargin=15 * mm, rightMargin=15 * mm, topMargin=12 * mm, bottomMargin=12 * mm,
    )
    story = []
    for i, section in enumerate(sections):
        if i > 0:
            story.append(PageBreak())
        story.extend(section)
    doc.build(story)
