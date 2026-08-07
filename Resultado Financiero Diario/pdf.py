"""PDF premium del "Resultado Financiero diario" -- rediseño 2026-08-07 a pedido explícito
del usuario ("actúa como Senior UI/UX Designer... dashboard financiero para CFOs"). Sigue
siendo un PDF ESTÁTICO: lo que el brief pedía que solo tiene sentido en una app web (botón
"Actualizar" funcional, hover, animaciones, blur real de glassmorphism) no se simula aquí --
se avisó explícitamente al usuario en el chat, no se finge que un PDF puede hacer eso.

Estructura: header blanco con logo + tarjetas KPI + gráfico (si hay diferencias que graficar)
+ tarjeta de estado (verde/roja) + tabla con iconos por fila + insights automáticos + footer.
"""

import datetime
import getpass
import os

from reportlab.lib.pagesizes import letter
from reportlab.lib.units import mm
from reportlab.lib import colors as rl_colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image, Flowable, KeepTogether,
)
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_RIGHT

from config import (
    COLORS, FONT_REGULAR_TTF, FONT_BOLD_TTF, FONT_MONO_TTF, FONT_MONO_BOLD_TTF,
    TOLERANCIA_DIF_MXN, LOGO_PNG,
)
from insights import build_kpis, build_insights

C = {k: rl_colors.HexColor(v) for k, v in COLORS.items()}
PAGE_W = 180 * mm

FONT_REGULAR, FONT_BOLD = "Helvetica", "Helvetica-Bold"
if os.path.exists(FONT_REGULAR_TTF) and os.path.exists(FONT_BOLD_TTF):
    pdfmetrics.registerFont(TTFont("IBM Plex Sans", FONT_REGULAR_TTF))
    pdfmetrics.registerFont(TTFont("IBM Plex Sans Bold", FONT_BOLD_TTF))
    FONT_REGULAR, FONT_BOLD = "IBM Plex Sans", "IBM Plex Sans Bold"

FONT_MONO, FONT_MONO_BOLD = "Courier", "Courier-Bold"
if os.path.exists(FONT_MONO_TTF) and os.path.exists(FONT_MONO_BOLD_TTF):
    pdfmetrics.registerFont(TTFont("IBM Plex Mono", FONT_MONO_TTF))
    pdfmetrics.registerFont(TTFont("IBM Plex Mono Bold", FONT_MONO_BOLD_TTF))
    FONT_MONO, FONT_MONO_BOLD = "IBM Plex Mono", "IBM Plex Mono Bold"


def _money(v):
    signo = "-" if v < 0 else ""
    return f"{signo}${abs(v):,.2f}"


def _money_sin_decimales(v):
    signo = "-" if v < 0 else ""
    return f"{signo}${abs(v):,.0f}"


# --- Iconos vectoriales (check / warning) -------------------------------------------------
# Dibujados a mano con primitivas del canvas (círculo + trazos), no con glifos de fuente: un
# check mark (U+2713) o un emoji no está garantizado en todas las fuentes/encodings, un
# vector sí se ve igual siempre. Se reutilizan en las tarjetas KPI, la tarjeta de estado y la
# columna de icono de la tabla.

def _draw_check(canv, cx, cy, r, bg_color):
    canv.saveState()
    canv.setFillColor(bg_color)
    canv.circle(cx, cy, r, fill=1, stroke=0)
    canv.setStrokeColor(rl_colors.white)
    canv.setLineWidth(max(1.1, r * 0.26))
    canv.setLineCap(1)
    canv.setLineJoin(1)
    p = canv.beginPath()
    p.moveTo(cx - r * 0.48, cy - r * 0.02)
    p.lineTo(cx - r * 0.08, cy - r * 0.42)
    p.lineTo(cx + r * 0.52, cy + r * 0.38)
    canv.drawPath(p, stroke=1, fill=0)
    canv.restoreState()


def _draw_warning(canv, cx, cy, r, bg_color):
    canv.saveState()
    canv.setFillColor(bg_color)
    canv.circle(cx, cy, r, fill=1, stroke=0)
    canv.setFillColor(rl_colors.white)
    canv.roundRect(cx - r * 0.09, cy - r * 0.05, r * 0.18, r * 0.62, r * 0.09, fill=1, stroke=0)
    canv.circle(cx, cy - r * 0.42, r * 0.11, fill=1, stroke=0)
    canv.restoreState()


class _RowIcon(Flowable):
    """Icono chico (check/warning) para la columna de icono de cada fila de la tabla."""

    def __init__(self, ok, size=8.5):
        super().__init__()
        self.ok = ok
        self.width = self.height = size

    def wrap(self, availWidth, availHeight):
        return self.width, self.height

    def draw(self):
        r = self.width / 2
        if self.ok:
            _draw_check(self.canv, r, r, r, C["good"])
        else:
            _draw_warning(self.canv, r, r, r, C["critical"])


# --- Header premium -------------------------------------------------------------------------

class HeaderPremium(Flowable):
    """Banda blanca con sombra suave, logo, título/subtítulo a la izquierda y timestamp de
    generación a la derecha -- reemplaza la banda navy sólida de la versión anterior. La
    "sombra" se simula con un rectángulo gris muy claro desplazado detrás (ReportLab no tiene
    drop-shadow nativo); el "botón actualizar/exportar" del brief NO se dibuja como botón --
    no hay backend detrás que lo haga funcionar en un PDF, sería un elemento decorativo que
    miente sobre ser interactivo. En su lugar se muestra el timestamp real de generación."""

    def __init__(self, width, height, titulo, subtitulo, fecha_str, hora_str, logo_path):
        super().__init__()
        self.width, self.height = width, height
        self.titulo, self.subtitulo = titulo, subtitulo
        self.fecha_str, self.hora_str = fecha_str, hora_str
        self.logo_path = logo_path

    def wrap(self, availWidth, availHeight):
        return self.width, self.height + 3

    def draw(self):
        c = self.canv
        c.saveState()
        # Sombra: rectángulo gris muy tenue, ligeramente más abajo y con alpha bajo.
        c.setFillColor(C["border"])
        c.setFillAlpha(0.55)
        c.roundRect(0, -3, self.width, self.height, 10, fill=1, stroke=0)
        c.setFillAlpha(1)
        # Banda blanca principal + línea de acento inferior en azul medio.
        c.setFillColor(C["surface"])
        c.roundRect(0, 0, self.width, self.height, 10, fill=1, stroke=0)
        c.setFillColor(C["secondary"])
        c.rect(0, 0, self.width, 2.4, fill=1, stroke=0)

        logo_w = 0
        if self.logo_path and os.path.exists(self.logo_path):
            logo_h = self.height * 0.52
            logo_w = logo_h * (447 / 385)
            c.drawImage(self.logo_path, 16, self.height - logo_h - 14, width=logo_w, height=logo_h,
                        preserveAspectRatio=True, mask="auto")

        text_x = 16 + logo_w + (10 if logo_w else 0)
        c.setFont(FONT_BOLD, 19)
        c.setFillColor(C["primary"])
        c.drawString(text_x, self.height - 27, self.titulo)
        c.setFont(FONT_REGULAR, 10)
        c.setFillColor(C["muted"])
        c.drawString(text_x, self.height - 43, self.subtitulo)

        c.setFont(FONT_BOLD, 8.5)
        c.setFillColor(C["muted"])
        c.drawRightString(self.width - 16, self.height - 22, self.fecha_str.upper())
        c.setFont(FONT_REGULAR, 8)
        c.setFillColor(C["muted"])
        c.drawRightString(self.width - 16, self.height - 34, f"Generado a las {self.hora_str}")
        c.restoreState()


def _header(fecha_str, hora_str):
    logo = LOGO_PNG if os.path.exists(LOGO_PNG) else None
    return HeaderPremium(
        PAGE_W, 27 * mm,
        "Resultado Financiero Diario", "Conciliación Balance vs. Estado de Resultados",
        fecha_str, hora_str, logo,
    )


# --- Tarjetas KPI -----------------------------------------------------------------------

class KPICard(Flowable):
    """Icono + valor grande + etiqueta pequeña, sombra suave simulada, esquinas redondeadas
    (radio 5pt ~ equivalente premium a los 12-16px web del brief, escalado a tamaño de PDF)."""

    def __init__(self, width, height, label, value, value_color, icon=None):
        super().__init__()
        self.width, self.height = width, height
        self.label, self.value, self.value_color, self.icon = label, value, value_color, icon

    def wrap(self, availWidth, availHeight):
        return self.width, self.height + 3

    def draw(self):
        c = self.canv
        c.saveState()
        c.setFillColor(C["border"])
        c.setFillAlpha(0.5)
        c.roundRect(0, -2, self.width, self.height, 8, fill=1, stroke=0)
        c.setFillAlpha(1)
        c.setFillColor(C["surface"])
        c.setStrokeColor(C["border"])
        c.setLineWidth(0.6)
        c.roundRect(0, 0, self.width, self.height, 8, fill=1, stroke=1)

        # Etiqueta arriba, a todo el ancho de la tarjeta (con auto-encogido, igual que el
        # valor) -- el ícono se dibuja ABAJO junto al valor, no arriba, para que nunca se
        # solape con el texto de la etiqueta (bug visto en la primera versión: "SOCIEDADES
        # CON[icono]ADO" con el ícono tapando la etiqueta larga).
        max_label_width = self.width - 20
        label_size = 7.3
        label_text = self.label.upper()
        while label_size > 5.6 and pdfmetrics.stringWidth(label_text, FONT_REGULAR, label_size) > max_label_width:
            label_size -= 0.3
        c.setFont(FONT_REGULAR, label_size)
        c.setFillColor(C["muted"])
        c.drawString(12, self.height - 16, label_text)

        icon_w = 17 if self.icon else 0
        max_value_width = self.width - 16 - icon_w
        font_size = 16.5
        while font_size > 9 and pdfmetrics.stringWidth(self.value, FONT_BOLD, font_size) > max_value_width:
            font_size -= 0.5
        c.setFont(FONT_BOLD, font_size)
        c.setFillColor(self.value_color)
        c.drawString(12, 12, self.value)

        if self.icon == "check":
            _draw_check(c, self.width - 14, 16, 7, C["good"])
        elif self.icon == "warning":
            _draw_warning(c, self.width - 14, 16, 7, C["critical"])
        c.restoreState()


def _kpi_row(kpis):
    n = 5
    gap = 2.5 * mm
    card_w = (PAGE_W - gap * (n - 1)) / n
    card_h = 21 * mm

    estado_txt = "Conciliado" if kpis["conciliado"] else "Revisar"
    estado_color = C["good"] if kpis["conciliado"] else C["critical"]

    cards_data = [
        ("Sociedades conciliadas", str(kpis["n_conciliadas"]), C["good"], "check"),
        ("Sociedades con diferencias", str(kpis["n_con_diferencias"]), C["critical"] if kpis["n_con_diferencias"] else C["muted"],
         "warning" if kpis["n_con_diferencias"] else None),
        ("Diferencia total", _money_sin_decimales(kpis["diferencia_total"]), C["primary"], None),
        ("Mayor diferencia", _money_sin_decimales(kpis["mayor_diferencia"]), C["primary"], None),
        ("Estado general", estado_txt, estado_color, None),
    ]
    cards = [KPICard(card_w, card_h, label, value, color, icon) for label, value, color, icon in cards_data]
    tbl = Table([cards], colWidths=[card_w] * n, rowHeights=[card_h + 3])
    tbl.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), gap),
        ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    return tbl


# --- Tarjeta de estado -------------------------------------------------------------------

class StatusCard(Flowable):
    """Reemplaza la nota de texto plano ("Ninguna sociedad muestra Dif. != 0 hoy") por una
    tarjeta de estado a todo el ancho, verde si concilia todo o roja si hay diferencias."""

    def __init__(self, width, height, ok, headline, subtext):
        super().__init__()
        self.width, self.height = width, height
        self.ok, self.headline, self.subtext = ok, headline, subtext

    def wrap(self, availWidth, availHeight):
        return self.width, self.height + 3

    def draw(self):
        c = self.canv
        bg = C["good_bg"] if self.ok else C["critical_bg"]
        accent = C["good"] if self.ok else C["critical"]
        c.saveState()
        c.setFillColor(C["border"])
        c.setFillAlpha(0.4)
        c.roundRect(0, -2, self.width, self.height, 9, fill=1, stroke=0)
        c.setFillAlpha(1)
        c.setFillColor(bg)
        c.roundRect(0, 0, self.width, self.height, 9, fill=1, stroke=0)
        c.setFillColor(accent)
        c.roundRect(0, 0, 4, self.height, 2, fill=1, stroke=0)

        icon_cx = 26
        if self.ok:
            _draw_check(c, icon_cx, self.height / 2, 10, accent)
        else:
            _draw_warning(c, icon_cx, self.height / 2, 10, accent)

        c.setFont(FONT_BOLD, 11)
        c.setFillColor(C["primary"])
        c.drawString(46, self.height / 2 + 5, self.headline)
        c.setFont(FONT_REGULAR, 8.5)
        c.setFillColor(C["text_secondary"])
        c.drawString(46, self.height / 2 - 8, self.subtext)
        c.restoreState()


def _status_card(kpis, tolerancia):
    if kpis["conciliado"]:
        return StatusCard(
            PAGE_W, 15 * mm, True,
            "Todas las sociedades conciliaron correctamente.",
            "No existen diferencias entre Balance y Estado de Resultados para la fecha seleccionada.",
        )
    return StatusCard(
        PAGE_W, 15 * mm, False,
        f"Se detectaron diferencias en {kpis['n_con_diferencias']} sociedad(es).",
        f"Fuera de tolerancia (+/- ${tolerancia:.2f}) -- requieren revisión, ver filas marcadas en la tabla.",
    )


# --- Gráfico ------------------------------------------------------------------------------

def _chart_panel(chart_path):
    img = Image(chart_path, width=176 * mm, height=48 * mm)
    tbl = Table([[img]], colWidths=[PAGE_W])
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), C["surface"]),
        ("BOX", (0, 0), (-1, -1), 0.6, C["border"]),
        ("LEFTPADDING", (0, 0), (-1, -1), 2 * mm),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2 * mm),
        ("TOPPADDING", (0, 0), (-1, -1), 1.5 * mm),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1 * mm),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
    ]))
    return tbl


# --- Tabla premium ----------------------------------------------------------------------

_STYLE_TD_SOCIEDAD = ParagraphStyle("td_sociedad", fontName=FONT_REGULAR, fontSize=8.5,
                                     textColor=C["text_secondary"], leading=10.5, alignment=TA_LEFT)
_STYLE_TH_SOCIEDAD = ParagraphStyle("th_sociedad", fontName=FONT_BOLD, fontSize=8.5,
                                     textColor=rl_colors.white, leading=11, alignment=TA_LEFT)


def _color_monto(v):
    """Pedido explícito del usuario: negativos en rojo suave, positivos en gris oscuro
    (nunca negro puro)."""
    return C["critical"] if v < 0 else C["text_secondary"]


def _tabla(df, tolerancia):
    header = ["", Paragraph("Sociedad", _STYLE_TH_SOCIEDAD), "Balance", "Estado de Resultados", "Dif."]
    rows = [header]
    df_ordenado = df.sort_values("nombre_sociedad")
    for _, r in df_ordenado.iterrows():
        conciliada = abs(r["dif"]) <= tolerancia
        rows.append([
            _RowIcon(conciliada),
            Paragraph(r["nombre_sociedad"], _STYLE_TD_SOCIEDAD),
            _money_sin_decimales(r["balance"]),
            _money_sin_decimales(r["estado_resultados"]),
            _money(r["dif"]),
        ])

    total_balance = df["balance"].sum()
    total_estado = df["estado_resultados"].sum()
    total_dif = df["dif"].sum()
    rows.append([
        "", Paragraph("TOTAL GENERAL", ParagraphStyle("th_total", parent=_STYLE_TD_SOCIEDAD,
                                                        fontName=FONT_BOLD, textColor=C["primary"])),
        _money_sin_decimales(total_balance), _money_sin_decimales(total_estado), _money(total_dif),
    ])

    n_rows = len(rows)
    tbl = Table(rows, colWidths=[7 * mm, 55 * mm, 40 * mm, 46 * mm, 32 * mm], repeatRows=1)
    style = [
        ("BOX", (0, 0), (-1, -1), 0.6, C["border"]),
        ("BACKGROUND", (0, 0), (-1, 0), C["primary"]),
        ("TEXTCOLOR", (0, 0), (-1, 0), rl_colors.white),
        ("FONTNAME", (0, 0), (-1, 0), FONT_BOLD),
        ("FONTNAME", (2, 1), (-1, -1), FONT_MONO),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("ALIGN", (2, 0), (-1, -1), "RIGHT"),
        ("ALIGN", (0, 0), (0, -1), "CENTER"),
        ("LINEBELOW", (0, 0), (-1, 0), 0, rl_colors.white),
        ("LINEBELOW", (0, 1), (-1, -2), 0.4, C["border"]),
        ("LINEABOVE", (0, -1), (-1, -1), 0.8, C["primary"]),
        ("BACKGROUND", (0, -1), (-1, -1), C["support"]),
        ("TOPPADDING", (0, 0), (-1, -1), 4),   # generoso pero ajustado para caber en una página
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, 0), 6.5),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 6.5),
        ("LEFTPADDING", (1, 0), (-1, -1), 9),
        ("RIGHTPADDING", (0, 0), (-1, -1), 9),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]
    # Zebra: franjas en el azul de apoyo muy claro (support), no gris -- pedido de paleta.
    for i in range(1, n_rows - 1):
        if i % 2 == 0:
            style.append(("BACKGROUND", (0, i), (-1, i), C["support"]))

    # Color por signo en Balance/Estado de Resultados (negativo=rojo suave, positivo=gris
    # oscuro) + columna Dif. verde/roja según el spec del usuario (ya no ámbar).
    for i, r in enumerate(df_ordenado.itertuples(), start=1):
        style.append(("TEXTCOLOR", (2, i), (2, i), _color_monto(r.balance)))
        style.append(("TEXTCOLOR", (3, i), (3, i), _color_monto(r.estado_resultados)))
        dif_color = C["good"] if abs(r.dif) <= tolerancia else C["critical"]
        style.append(("TEXTCOLOR", (4, i), (4, i), dif_color))
        style.append(("FONTNAME", (4, i), (4, i), FONT_MONO_BOLD))

    # Fila de totales: cifras en bold, color primary.
    style.append(("FONTNAME", (2, -1), (-1, -1), FONT_MONO_BOLD))
    style.append(("TEXTCOLOR", (2, -1), (-1, -1), C["primary"]))

    tbl.setStyle(TableStyle(style))
    return tbl


# --- Insights -----------------------------------------------------------------------------

_STYLE_INSIGHT_TITLE = ParagraphStyle("insight_title", fontName=FONT_BOLD, fontSize=12.5,
                                       textColor=C["primary"], leading=15)
_STYLE_INSIGHT = ParagraphStyle("insight", fontName=FONT_REGULAR, fontSize=9,
                                 textColor=C["text_secondary"], leading=13, leftIndent=10)


def _insights_section(insights):
    flow = [Paragraph("Insights del día", _STYLE_INSIGHT_TITLE), Spacer(1, 5)]
    for texto in insights:
        flow.append(Paragraph(f"•  {texto}", _STYLE_INSIGHT))
        flow.append(Spacer(1, 3))
    return flow


# --- Footer -------------------------------------------------------------------------------

_STYLE_FOOTER = ParagraphStyle("footer", fontName=FONT_REGULAR, fontSize=7.3,
                                textColor=C["muted"], leading=10)


def _footer(fecha_str, hora_str):
    usuario = getpass.getuser()
    texto = (
        f"Última actualización: {fecha_str} {hora_str}  |  "
        f"Fuente de datos: BigQuery -- proan-quantrue.D30_INTEGRATION.sap_faglflext  |  "
        f"Versión del reporte: v2  |  Generado por: {usuario}"
    )
    return Paragraph(texto, _STYLE_FOOTER)


# --- Ensamblado -----------------------------------------------------------------------------

def build_pdf(df, fecha_str, hora_str, chart_path, chart_ok, output_path):
    doc = SimpleDocTemplate(
        output_path, pagesize=letter,
        leftMargin=15 * mm, rightMargin=15 * mm, topMargin=12 * mm, bottomMargin=12 * mm,
    )
    kpis = build_kpis(df, TOLERANCIA_DIF_MXN)
    insights = build_insights(df, kpis)

    story = [
        _header(fecha_str, hora_str),
        Spacer(1, 6),
        _kpi_row(kpis),
        Spacer(1, 6),
    ]
    if chart_ok:
        story.append(_chart_panel(chart_path))
        story.append(Spacer(1, 6))
    story.append(_status_card(kpis, TOLERANCIA_DIF_MXN))
    story.append(Spacer(1, 6))
    story.append(_tabla(df, TOLERANCIA_DIF_MXN))
    story.append(Spacer(1, 8))
    # Insights + footer como un solo bloque: si no caben en lo que queda de la página, se
    # empujan juntos a la siguiente en vez de partir el título de sus bullets (visto en la
    # primera versión: "Insights del día" quedaba solo al fondo de la página 1).
    cierre = _insights_section(insights) + [Spacer(1, 6), _footer(fecha_str, hora_str)]
    story.append(KeepTogether(cierre))

    doc.build(story)
