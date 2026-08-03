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

from config import COLORS, FONT_REGULAR_TTF, FONT_BOLD_TTF

C = {k: rl_colors.HexColor(v) for k, v in COLORS.items()}

FONT_REGULAR, FONT_BOLD = "Helvetica", "Helvetica-Bold"
if os.path.exists(FONT_REGULAR_TTF) and os.path.exists(FONT_BOLD_TTF):
    pdfmetrics.registerFont(TTFont("Segoe UI", FONT_REGULAR_TTF))
    pdfmetrics.registerFont(TTFont("Segoe UI Bold", FONT_BOLD_TTF))
    FONT_REGULAR, FONT_BOLD = "Segoe UI", "Segoe UI Bold"

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


class StatTile(Flowable):
    """Tarjeta KPI con esquinas redondeadas y barra de acento superior."""

    def __init__(self, width, height, label, value, value_color, accent_color=None):
        super().__init__()
        self.width = width
        self.height = height
        self.label = label
        self.value = value
        self.value_color = value_color
        self.accent_color = accent_color or value_color

    def wrap(self, availWidth, availHeight):
        return self.width, self.height

    def draw(self):
        c = self.canv
        c.saveState()
        c.setFillColor(C["tile_bg"])
        c.roundRect(0, 0, self.width, self.height, 7, fill=1, stroke=0)
        c.setFillColor(self.accent_color)
        c.roundRect(0, self.height - 3.5, self.width, 3.5, 1.5, fill=1, stroke=0)
        c.setFont(FONT_REGULAR, 7.3)
        c.setFillColor(C["muted"])
        c.drawString(13, self.height - 24, self.label.upper())
        c.setFont(FONT_BOLD, 16)
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
        c.setFont(FONT_REGULAR, 9)
        c.setFillColor(rl_colors.HexColor("#c9d6e5"))
        c.drawString(16, self.height - 48, self.subtitulo)
        c.restoreState()


def _header(cuenta_nombre, raccts, fecha_str):
    subtitulo = f"CUENTA(S) DE MAYOR: {', '.join(raccts)}  |  AL DÍA DE HOY ({fecha_str}), MXN"
    return [RoundedHeader(180 * mm, 26 * mm, cuenta_nombre, subtitulo)]


def _stat_tiles(total_actual, total_anterior, current_year, prior_year):
    diferencia = total_actual - total_anterior
    pct = (diferencia / abs(total_anterior)) if total_anterior else float("nan")

    tile_w, tile_h, gap = 43 * mm, 22 * mm, 2 * mm
    tiles_data = [
        (f"Total {current_year} (hoy)", _money(total_actual), C["text_primary"], C["header_bg"]),
        (f"Total {prior_year}", _money(total_anterior), C["text_primary"], C["header_bg"]),
        ("Diferencia total", _money(diferencia), _signo_color(diferencia), _signo_color(diferencia)),
        ("% Variación global", _pct(pct), _signo_color(pct), _signo_color(pct)),
    ]
    tiles = [StatTile(tile_w, tile_h, label, value, color, accent)
             for label, value, color, accent in tiles_data]
    tbl = Table([tiles], colWidths=[tile_w] * 4, rowHeights=[tile_h])
    tbl.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), gap),
        ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    return tbl


def _tabla_sociedades(df, current_year, prior_year):
    header = ["Sociedad", f"{prior_year}", f"{current_year} (HOY)", "Diferencia", "% Variac."]
    rows = [header]
    df_ordenado = df.sort_values("actual", ascending=False, key=abs)
    for _, r in df_ordenado.iterrows():
        rows.append([r["nombre_sociedad"], _money(r["anterior"]), _money(r["actual"]),
                     _money(r["diferencia"]), _pct(r["pct_variacion"])])

    total_actual = df["actual"].sum()
    total_anterior = df["anterior"].sum()
    total_dif = total_actual - total_anterior
    total_pct = (total_dif / abs(total_anterior)) if total_anterior else float("nan")
    rows.append(["TOTAL GENERAL", _money(total_anterior), _money(total_actual),
                 _money(total_dif), _pct(total_pct)])

    n_rows = len(rows)
    tbl = Table(rows, colWidths=[55 * mm, 32 * mm, 32 * mm, 32 * mm, 24 * mm], repeatRows=1)
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), C["header_bg"]),
        ("TEXTCOLOR", (0, 0), (-1, 0), rl_colors.white),
        ("FONTNAME", (0, 0), (-1, 0), FONT_BOLD),
        ("FONTNAME", (0, 1), (-1, -1), FONT_REGULAR),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("ALIGN", (0, 0), (0, -1), "LEFT"),
        ("LINEBELOW", (0, 0), (-1, 0), 0, rl_colors.white),
        ("LINEBELOW", (0, 1), (-1, -2), 0.4, C["grid"]),
        ("LINEABOVE", (0, -1), (-1, -1), 0.8, C["text_primary"]),
        ("BACKGROUND", (0, -1), (-1, -1), C["tile_bg"]),
        ("FONTNAME", (0, -1), (-1, -1), FONT_BOLD),
        ("TOPPADDING", (0, 0), (-1, -1), 3.2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3.2),
        ("TOPPADDING", (0, 0), (-1, 0), 6),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 6),
        ("TOPPADDING", (0, -1), (-1, -1), 5),
        ("BOTTOMPADDING", (0, -1), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]
    # Franjas alternadas (excepto encabezado y fila de total) para lectura más fácil.
    for i in range(1, n_rows - 1):
        if i % 2 == 0:
            style.append(("BACKGROUND", (0, i), (-1, i), C["tile_bg"]))
    for i, r in df_ordenado.reset_index().iterrows():
        color = _signo_color(r["pct_variacion"])
        style.append(("TEXTCOLOR", (3, i + 1), (4, i + 1), color))
    tbl.setStyle(TableStyle(style))
    return tbl


def build_section(cuenta_nombre, raccts, df, chart_path, fecha_str, current_year, prior_year):
    flow = []
    flow.extend(_header(cuenta_nombre, raccts, fecha_str))
    flow.append(Spacer(1, 7))
    flow.append(_stat_tiles(df["actual"].sum(), df["anterior"].sum(), current_year, prior_year))
    flow.append(Spacer(1, 8))
    flow.append(Image(chart_path, width=180 * mm, height=68 * mm))
    flow.append(Spacer(1, 8))
    flow.append(_tabla_sociedades(df, current_year, prior_year))
    return flow


def _header_descuentos(fecha_str):
    subtitulo = f"CUENTAS DE VENTAS (RACCT 000401%)  |  AL DÍA DE HOY ({fecha_str}), MXN"
    return [RoundedHeader(180 * mm, 26 * mm, "Descuentos y Bonificaciones", subtitulo)]


def _stat_tiles_descuentos(ingresos_total, descuentos_total, current_year):
    pct = (descuentos_total / ingresos_total) if ingresos_total else float("nan")

    tile_w, tile_h, gap = 58 * mm, 22 * mm, 2 * mm
    tiles_data = [
        (f"Ingresos totales {current_year} (hoy)", _money(ingresos_total), C["text_primary"], C["header_bg"]),
        (f"Descuentos totales {current_year} (hoy)", _money(descuentos_total), C["text_primary"], C["header_bg"]),
        ("% Global (Descuentos/Ingresos)", _pct(pct), C["text_primary"], C["header_bg"]),
    ]
    tiles = [StatTile(tile_w, tile_h, label, value, color, accent)
             for label, value, color, accent in tiles_data]
    tbl = Table([tiles], colWidths=[tile_w] * 3, rowHeights=[tile_h])
    tbl.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), gap),
        ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    return tbl


def _p(text, style):
    return Paragraph(str(text), style)


def _tabla_descuentos(df, current_year, prior_year):
    header = ["Sociedad", f"Ingresos {prior_year}", f"Ingresos {current_year} (HOY)",
              f"Descuentos {prior_year}", f"Descuentos {current_year} (HOY)",
              f"% {prior_year}", f"% {current_year} (HOY)"]
    rows = [[_p(header[0], _STYLE_TH_LEFT)] + [_p(h, _STYLE_TH) for h in header[1:]]]

    df_ordenado = df.sort_values("ingresos_actual", ascending=False, key=abs)
    for _, r in df_ordenado.iterrows():
        rows.append([
            _p(r["nombre_sociedad"], _STYLE_TD_LEFT),
            _p(_money(r["ingresos_anterior"]), _STYLE_TD),
            _p(_money(r["ingresos_actual"]), _STYLE_TD),
            _p(_money(r["descuentos_anterior"]), _STYLE_TD),
            _p(_money(r["descuentos_actual"]), _STYLE_TD),
            _p(_pct(r["pct_anterior"]), _STYLE_TD),
            _p(_pct(r["pct_actual"]), _STYLE_TD),
        ])

    total_ingresos_actual = df["ingresos_actual"].sum()
    total_ingresos_anterior = df["ingresos_anterior"].sum()
    total_descuentos_actual = df["descuentos_actual"].sum()
    total_descuentos_anterior = df["descuentos_anterior"].sum()
    total_pct_actual = (total_descuentos_actual / total_ingresos_actual) if total_ingresos_actual else float("nan")
    total_pct_anterior = (total_descuentos_anterior / total_ingresos_anterior) if total_ingresos_anterior else float("nan")
    rows.append([
        _p("TOTAL GENERAL", _STYLE_TD_BOLD_LEFT),
        _p(_money(total_ingresos_anterior), _STYLE_TD_BOLD),
        _p(_money(total_ingresos_actual), _STYLE_TD_BOLD),
        _p(_money(total_descuentos_anterior), _STYLE_TD_BOLD),
        _p(_money(total_descuentos_actual), _STYLE_TD_BOLD),
        _p(_pct(total_pct_anterior), _STYLE_TD_BOLD),
        _p(_pct(total_pct_actual), _STYLE_TD_BOLD),
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


def build_section_descuentos(df, chart_path, fecha_str, current_year, prior_year):
    flow = []
    flow.extend(_header_descuentos(fecha_str))
    flow.append(Spacer(1, 7))
    flow.append(_stat_tiles_descuentos(df["ingresos_actual"].sum(), df["descuentos_actual"].sum(), current_year))
    flow.append(Spacer(1, 8))
    flow.append(Image(chart_path, width=180 * mm, height=68 * mm))
    flow.append(Spacer(1, 8))
    flow.append(_tabla_descuentos(df, current_year, prior_year))
    return flow


def _stat_tiles_precios(total_actual, total_anterior, current_year, prior_year):
    """3 cards (no 4): esta cuenta no usa % de variación en su reporte de referencia
    (ver _tabla_precios). Dif. = anterior - actual, convención propia de este reporte."""
    diferencia = total_anterior - total_actual

    tile_w, tile_h, gap = 58 * mm, 22 * mm, 2 * mm
    tiles_data = [
        (f"Total {prior_year}", _money(total_anterior), C["text_primary"], C["header_bg"]),
        (f"Total {current_year} (hoy)", _money(total_actual), C["text_primary"], C["header_bg"]),
        ("Diferencia global", _money(diferencia), _signo_color(diferencia), _signo_color(diferencia)),
    ]
    tiles = [StatTile(tile_w, tile_h, label, value, color, accent)
             for label, value, color, accent in tiles_data]
    tbl = Table([tiles], colWidths=[tile_w] * 3, rowHeights=[tile_h])
    tbl.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), gap),
        ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    return tbl


def _tabla_precios(df, current_year, prior_year):
    """Reproduce el formato del reporte de finanzas "Variación de precios": Empresa /
    Año anterior / Año actual / Dif., SIN columna de % (a diferencia de _tabla_sociedades).
    Dif. = Año anterior - Año actual: convención propia de este reporte, invertida respecto
    al resto (donde diferencia = actual - anterior). Empresa usa Paragraph porque el
    catálogo SOCIEDADES trae nombres completos más largos que los truncados de dm_company."""
    header = ["Empresa", f"{prior_year}", f"{current_year} (HOY)", "Dif."]
    rows = [[_p(header[0], _STYLE_TH_LEFT), header[1], header[2], header[3]]]

    df = df.copy()
    df["dif_mostrada"] = df["anterior"] - df["actual"]
    df_ordenado = df.sort_values("actual", ascending=False, key=abs)
    for _, r in df_ordenado.iterrows():
        rows.append([_p(r["nombre_sociedad"], _STYLE_TD_LEFT), _money(r["anterior"]),
                     _money(r["actual"]), _money(r["dif_mostrada"])])

    total_actual = df["actual"].sum()
    total_anterior = df["anterior"].sum()
    total_dif = total_anterior - total_actual
    rows.append([_p("TOTAL GENERAL", _STYLE_TD_BOLD_LEFT), _money(total_anterior),
                 _money(total_actual), _money(total_dif)])

    n_rows = len(rows)
    tbl = Table(rows, colWidths=[62 * mm, 39 * mm, 39 * mm, 40 * mm], repeatRows=1)
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), C["header_bg"]),
        ("TEXTCOLOR", (1, 0), (-1, 0), rl_colors.white),
        ("FONTNAME", (1, 0), (-1, 0), FONT_BOLD),
        ("FONTNAME", (1, 1), (-1, -2), FONT_REGULAR),
        ("FONTNAME", (1, -1), (-1, -1), FONT_BOLD),
        ("FONTSIZE", (1, 0), (-1, -1), 8),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
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
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]
    # Franjas alternadas (excepto encabezado y fila de total) para lectura más fácil.
    for i in range(1, n_rows - 1):
        if i % 2 == 0:
            style.append(("BACKGROUND", (0, i), (-1, i), C["tile_bg"]))
    # Semáforo rojo/verde en Dif., por fila y en el total.
    for i, r in df_ordenado.reset_index().iterrows():
        style.append(("TEXTCOLOR", (3, i + 1), (3, i + 1), _signo_color(r["dif_mostrada"])))
    style.append(("TEXTCOLOR", (3, n_rows - 1), (3, n_rows - 1), _signo_color(total_dif)))
    tbl.setStyle(TableStyle(style))
    return tbl


def build_section_precios(cuenta_nombre, raccts, df, chart_path, fecha_str, current_year, prior_year):
    flow = []
    flow.extend(_header(cuenta_nombre, raccts, fecha_str))
    flow.append(Spacer(1, 7))
    flow.append(_stat_tiles_precios(df["actual"].sum(), df["anterior"].sum(), current_year, prior_year))
    flow.append(Spacer(1, 8))
    flow.append(Image(chart_path, width=180 * mm, height=68 * mm))
    flow.append(Spacer(1, 8))
    flow.append(_tabla_precios(df, current_year, prior_year))
    return flow


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
