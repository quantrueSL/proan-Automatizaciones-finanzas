"""PDF "Resultado Financiero Mensual" -- mismo sistema visual que "Reportes diarios
contables" (navy vigente, confirmado con el usuario 2026-08-07, no el dorado retirado).

Cambios 2026-08-07 (pedido explícito del usuario, ver briefing "CAMBIOS AL REPORTE MENSUAL"):
1. 2 meses en vez de 3 (se quitó el mes antepasado).
2. El resaltado ámbar de FONDO en la celda de Resultado se reemplazó por un ÍCONO pequeño
   junto al valor -- PROVISIONAL (triángulo ámbar) / SIN_REFERENCIA (círculo gris), dibujados
   a mano en el canvas (mismo criterio que los íconos ✓/⚠ del rediseño premium del reporte
   diario: un glifo Unicode como ⚠ no está garantizado en toda fuente/encoding, un vector sí
   se ve igual siempre). Con leyenda al pie explicando cada ícono.
3. Columna "% Variación" al final de la tabla (Resultado mes actual vs. Resultado mes
   anterior).

Landscape (no portrait): con 2 meses x 3 métricas + % Variación siguen siendo demasiadas
columnas para una página vertical sin abreviar montos."""

import os

from reportlab.lib.pagesizes import letter, landscape
from reportlab.lib.units import mm
from reportlab.lib import colors as rl_colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image, Flowable
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT

from config import COLORS, FONT_REGULAR_TTF, FONT_BOLD_TTF, FONT_MONO_TTF, FONT_MONO_BOLD_TTF

C = {k: rl_colors.HexColor(v) for k, v in COLORS.items()}
PAGE_W = 249 * mm  # ancho útil en landscape Letter (279.4mm - 15mm*2 de márgenes)

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
    if v != v:  # NaN
        return "—"
    signo = "-" if v < 0 else ""
    return f"{signo}${abs(v):,.0f}"


def _pct(v):
    if v != v:
        return "N/A"
    return f"{v:+.1%}"


def _signo_color(v):
    if v != v:
        return C["muted"]
    return C["good"] if v >= 0 else C["critical"]


class RoundedHeader(Flowable):
    def __init__(self, width, height, titulo, subtitulo):
        super().__init__()
        self.width, self.height = width, height
        self.titulo, self.subtitulo = titulo, subtitulo

    def wrap(self, availWidth, availHeight):
        return self.width, self.height

    def draw(self):
        c = self.canv
        c.saveState()
        c.setFillColor(C["header_bg"])
        c.roundRect(0, 0, self.width, self.height, 8, fill=1, stroke=0)
        c.rect(0, 0, self.width, self.height * 0.45, fill=1, stroke=0)
        c.setFillColor(C["header_accent"])
        c.rect(0, 0, self.width, 3, fill=1, stroke=0)
        c.setFont(FONT_BOLD, 17)
        c.setFillColor(rl_colors.white)
        c.drawString(16, self.height - 30, self.titulo.upper())
        c.setFont(FONT_REGULAR, 9)
        c.setFillColor(rl_colors.HexColor("#c9d6e5"))
        c.drawString(16, self.height - 48, self.subtitulo)
        c.restoreState()


class StatTile(Flowable):
    def __init__(self, width, height, label, value, value_color):
        super().__init__()
        self.width, self.height = width, height
        self.label, self.value, self.value_color = label, value, value_color

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
        max_value_width = self.width - 21
        font_size = 15.5
        while font_size > 9 and pdfmetrics.stringWidth(self.value, FONT_MONO_BOLD, font_size) > max_value_width:
            font_size -= 0.5
        c.setFont(FONT_MONO_BOLD, font_size)
        c.setFillColor(self.value_color)
        c.drawString(13, 15, self.value)
        c.restoreState()


def _header(mes1_str, mes2_str, fecha_str):
    subtitulo = f"INGRESOS, EGRESOS Y RESULTADO POR SOCIEDAD -- {mes1_str} / {mes2_str}, MXN | GENERADO {fecha_str}"
    return RoundedHeader(PAGE_W, 24 * mm, "Resultado Financiero Mensual", subtitulo)


def _stat_tiles(df, mes1_str, mes2_str):
    total_m1 = df["resultado_m1"].sum()
    total_m2 = df["resultado_m2"].sum()
    pct_total = (total_m2 - total_m1) / abs(total_m1) if abs(total_m1) >= 1000 else (1.0 if total_m2 >= total_m1 else -1.0)
    # m2 (el más reciente de los dos) es el más relevante para "¿todavía se está moviendo?"
    # -- ambos meses ya están cerrados, pero m2 acaba de cerrar hace más o menos una semana.
    n_provisional_m2 = int((df["estatus_m2"] == "PROVISIONAL").sum())

    tile_w, tile_h, gap = (PAGE_W - 3 * 2 * mm) / 4, 20 * mm, 2 * mm
    tiles_data = [
        (f"Resultado {mes1_str}", _money(total_m1), _signo_color(total_m1)),
        (f"Resultado {mes2_str}", _money(total_m2), _signo_color(total_m2)),
        ("% Variación total", _pct(pct_total), _signo_color(pct_total)),
        (f"Sociedades con {mes2_str} aún en revisión", str(n_provisional_m2), C["text_primary"]),
    ]
    tiles = [StatTile(tile_w, tile_h, label, value, color) for label, value, color in tiles_data]
    tbl = Table([tiles], colWidths=[tile_w] * 4, rowHeights=[tile_h])
    tbl.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), gap),
        ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    return tbl


def _chart_panel(chart_path):
    img = Image(chart_path, width=(PAGE_W - 4 * mm), height=68 * mm)
    tbl = Table([[img]], colWidths=[PAGE_W])
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), C["tile_bg"]),
        ("BOX", (0, 0), (-1, -1), 0.75, C["kpi_border"]),
        ("LEFTPADDING", (0, 0), (-1, -1), 2 * mm), ("RIGHTPADDING", (0, 0), (-1, -1), 2 * mm),
        ("TOPPADDING", (0, 0), (-1, -1), 1 * mm), ("BOTTOMPADDING", (0, 0), (-1, -1), 1 * mm),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("ALIGN", (0, 0), (-1, -1), "CENTER"),
    ]))
    return tbl


_STYLE_TH = ParagraphStyle("th", fontName=FONT_BOLD, fontSize=6.8, textColor=rl_colors.white,
                            leading=8, alignment=TA_CENTER)
_STYLE_TH_LEFT = ParagraphStyle("th_left", parent=_STYLE_TH, alignment=TA_LEFT)


# --- Íconos vectoriales de estatus (dibujados a mano, no glifos de fuente) -----------------
# Mismo criterio que el rediseño premium del reporte diario: un ⚠ Unicode no está garantizado
# en toda fuente/encoding, un vector construido con primitivas del canvas sí se ve igual
# siempre. Triángulo ámbar con "!" para PROVISIONAL, círculo gris con "-" para SIN_REFERENCIA
# -- formas DISTINTAS (no solo color distinto), para que la diferencia se note incluso en
# blanco y negro o para daltonismo.

def _draw_provisional_icon(canv, cx, cy, r, color):
    canv.saveState()
    canv.setFillColor(color)
    p = canv.beginPath()
    p.moveTo(cx, cy + r)
    p.lineTo(cx - r * 0.95, cy - r * 0.75)
    p.lineTo(cx + r * 0.95, cy - r * 0.75)
    p.close()
    canv.drawPath(p, fill=1, stroke=0)
    canv.setFillColor(rl_colors.white)
    canv.roundRect(cx - r * 0.09, cy - r * 0.15, r * 0.18, r * 0.55, r * 0.09, fill=1, stroke=0)
    canv.circle(cx, cy - r * 0.48, r * 0.1, fill=1, stroke=0)
    canv.restoreState()


def _draw_sin_referencia_icon(canv, cx, cy, r, color):
    canv.saveState()
    canv.setFillColor(color)
    canv.circle(cx, cy, r, fill=1, stroke=0)
    canv.setFillColor(rl_colors.white)
    canv.roundRect(cx - r * 0.5, cy - r * 0.09, r, r * 0.18, r * 0.06, fill=1, stroke=0)
    canv.restoreState()


class _ValorConEstatus(Flowable):
    """Celda de la tabla para Resultado m1/m2: monto (mono, alineado a la derecha) + ícono de
    estatus a la izquierda del monto cuando aplica (PROVISIONAL/SIN_REFERENCIA). ESTABLE (o
    sin estatus, ej. columna % Variación) no lleva ícono -- se pasa estatus=None."""

    def __init__(self, texto, estatus, color_texto, font=FONT_MONO, font_size=7, height=9.5):
        super().__init__()
        self.texto, self.estatus, self.color_texto = texto, estatus, color_texto
        self.font, self.font_size, self.height = font, font_size, height
        self.width = 0

    def wrap(self, availWidth, availHeight):
        self.width = availWidth
        return availWidth, self.height

    def draw(self):
        c = self.canv
        c.saveState()
        c.setFont(self.font, self.font_size)
        text_w = pdfmetrics.stringWidth(self.texto, self.font, self.font_size)
        c.setFillColor(self.color_texto)
        c.drawRightString(self.width, self.height * 0.32, self.texto)

        if self.estatus in ("PROVISIONAL", "SIN_REFERENCIA"):
            r = 3.1
            gap = 3
            cx = self.width - text_w - gap - r
            cy = self.height / 2
            if self.estatus == "PROVISIONAL":
                _draw_provisional_icon(c, cx, cy, r, C["provisional_text"])
            else:
                _draw_sin_referencia_icon(c, cx, cy, r, C["sin_referencia_text"])
        c.restoreState()


def _color_valor_estatus(valor, estatus):
    """Color por signo SOLO cuando el mes ya está confirmado ESTABLE -- si está PROVISIONAL o
    SIN_REFERENCIA se usa un color neutro (el ícono ya avisa que hay que revisarlo, doblar
    con rojo/verde sería ruido). Usado SOLO para la columna Resultado m1 -- m2 ya no lleva
    ícono por fila (ver nota en _tabla, cambio 2026-08-07)."""
    if estatus in ("PROVISIONAL", "SIN_REFERENCIA"):
        return C["text_primary"]
    return _signo_color(valor)


def _tabla(df, mes1_str, mes2_str):
    # Columna Resultado m2 (el mes más reciente, ej. "Resultado Julio 2026"): pedido explícito
    # del usuario (2026-08-07) -- YA NO lleva ícono de estatus por fila. Motivo: con el mes
    # recién cerrado, es NORMAL que las 17 sociedades salgan PROVISIONAL a la vez (apenas pasó
    # una semana desde el cierre) -- repetir el mismo ícono en cada fila no aporta nada, solo
    # ensucia. En su lugar: color por signo (igual que m1) + una sola nota a nivel de columna
    # ("*" en el encabezado + texto explicativo al pie, ver _leyenda_estatus).
    #
    # m1 SÍ conserva el ícono por fila -- ahí es donde una excepción puntual (ej. PIN, que
    # queda PROVISIONAL por su división entre cero pese a que el resto del mes ya está
    # ESTABLE) sí vale la pena señalar fila por fila. A propósito NO se generalizó esto en una
    # regla automática ("si todas son PROVISIONAL, usar columna; si no, usar íconos") -- el
    # usuario pidió explícitamente no sobre-codificarlo; si algún mes futuro m2 sale mixto
    # (algunas ESTABLE, algunas PROVISIONAL), se revisa el criterio entonces, a mano.
    header = [
        "", "Sociedad",
        f"Ingresos {mes1_str}", f"Egresos {mes1_str}", f"Resultado {mes1_str}",
        f"Ingresos {mes2_str}", f"Egresos {mes2_str}", f"Resultado {mes2_str}*",
        "% Variación",
    ]
    rows = [[Paragraph(header[0], _STYLE_TH)] + [Paragraph(h, _STYLE_TH_LEFT if i == 1 else _STYLE_TH)
                                                  for i, h in enumerate(header[1:], start=1)]]
    df_ordenado = df.sort_values("nombre_sociedad")
    for _, r in df_ordenado.iterrows():
        rows.append([
            "", r["nombre_sociedad"],
            _money(r["ing_m1"]), _money(r["egr_m1"]),
            _ValorConEstatus(_money(r["resultado_m1"]), r["estatus_m1"],
                             _color_valor_estatus(r["resultado_m1"], r["estatus_m1"])),
            _money(r["ing_m2"]), _money(r["egr_m2"]),
            _money(r["resultado_m2"]),
            _pct(r["pct_variacion"]),
        ])

    total_row_idx = len(rows)
    totales = {c: df[c].sum() for c in ("ing_m1", "egr_m1", "resultado_m1", "ing_m2", "egr_m2", "resultado_m2")}
    diferencia_total = totales["resultado_m2"] - totales["resultado_m1"]
    pct_total = diferencia_total / abs(totales["resultado_m1"]) if abs(totales["resultado_m1"]) >= 1000 else (1.0 if diferencia_total >= 0 else -1.0)
    rows.append([
        "", "TOTAL GENERAL",
        _money(totales["ing_m1"]), _money(totales["egr_m1"]), _money(totales["resultado_m1"]),
        _money(totales["ing_m2"]), _money(totales["egr_m2"]), _money(totales["resultado_m2"]),
        _pct(pct_total),
    ])

    n_rows = len(rows)
    col_w = [2.2 * mm, 40 * mm, 26 * mm, 26 * mm, 27 * mm, 26 * mm, 26 * mm, 27 * mm, 21.8 * mm]
    tbl = Table(rows, colWidths=col_w, repeatRows=1)
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), C["header_bg"]),
        ("FONTNAME", (1, 1), (1, -1), FONT_REGULAR),
        ("FONTNAME", (2, 1), (3, -2), FONT_MONO), ("FONTNAME", (5, 1), (7, -2), FONT_MONO),
        ("FONTNAME", (8, 1), (8, -2), FONT_MONO),
        ("FONTNAME", (2, -1), (-1, -1), FONT_MONO_BOLD),
        ("FONTNAME", (1, -1), (1, -1), FONT_BOLD),
        ("FONTSIZE", (0, 0), (-1, -1), 7),
        ("ALIGN", (2, 0), (-1, -1), "RIGHT"),
        ("ALIGN", (1, 0), (1, -1), "LEFT"),
        ("LINEBELOW", (0, 0), (-1, 0), 0, rl_colors.white),
        ("LINEBELOW", (0, 1), (-1, -2), 0.4, C["grid"]),
        ("LINEABOVE", (0, -1), (-1, -1), 0.8, C["text_primary"]),
        ("BACKGROUND", (1, -1), (-1, -1), C["tile_bg"]),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, 0), 6), ("BOTTOMPADDING", (0, 0), (-1, 0), 6),
        ("TOPPADDING", (0, -1), (-1, -1), 4.5), ("BOTTOMPADDING", (0, -1), (-1, -1), 4.5),
        ("LEFTPADDING", (1, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (0, -1), 0), ("RIGHTPADDING", (0, 0), (0, -1), 0),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]
    for i in range(1, n_rows - 1):
        if i % 2 == 0:
            style.append(("BACKGROUND", (1, i), (-1, i), C["tile_bg"]))
        r = df_ordenado.iloc[i - 1]
        style.append(("TEXTCOLOR", (0, i), (0, i), _signo_color(r["resultado_m2"])))
        style.append(("BACKGROUND", (0, i), (0, i), _signo_color(r["resultado_m2"])))
        # Resultado m2: color por signo, igual criterio que m1 -- ya no depende del estatus
        # (ver nota arriba, cambio 2026-08-07: sin ícono por fila en esta columna).
        style.append(("TEXTCOLOR", (7, i), (7, i), _signo_color(r["resultado_m2"])))
        style.append(("TEXTCOLOR", (8, i), (8, i), _signo_color(r["pct_variacion"])))

    style.append(("TEXTCOLOR", (0, total_row_idx), (0, total_row_idx), _signo_color(totales["resultado_m2"])))
    style.append(("BACKGROUND", (0, total_row_idx), (0, total_row_idx), _signo_color(totales["resultado_m2"])))
    style.append(("TEXTCOLOR", (8, total_row_idx), (8, total_row_idx), _signo_color(pct_total)))
    tbl.setStyle(TableStyle(style))
    return tbl


_STYLE_NOTE = ParagraphStyle("nota", fontName=FONT_REGULAR, fontSize=7.3,
                              textColor=C["muted"], leading=10)


class _LeyendaIcono(Flowable):
    """Fila de leyenda: ícono + texto explicativo, para el pie del reporte. Mismo dibujo a
    mano que en la tabla (ver _draw_provisional_icon/_draw_sin_referencia_icon)."""

    def __init__(self, tipo, texto, width=520, height=11):
        super().__init__()
        self.tipo, self.texto, self.width, self.height = tipo, texto, width, height

    def wrap(self, availWidth, availHeight):
        return self.width, self.height

    def draw(self):
        c = self.canv
        r = 3.6
        if self.tipo == "provisional":
            _draw_provisional_icon(c, r + 1, self.height / 2, r, C["provisional_text"])
        else:
            _draw_sin_referencia_icon(c, r + 1, self.height / 2, r, C["sin_referencia_text"])
        c.setFont(FONT_REGULAR, 7.3)
        c.setFillColor(C["muted"])
        c.drawString(r * 2 + 8, self.height * 0.3, self.texto)


_STYLE_NOTE_ASTERISCO = ParagraphStyle("nota_asterisco", parent=_STYLE_NOTE, fontName=FONT_BOLD,
                                        textColor=C["text_secondary"])


def _leyenda_estatus(mes1_str, mes2_str):
    """Nota de columna (la "*" del encabezado "Resultado {mes2}*") + leyenda de los íconos
    por fila, que ahora solo aparecen en la columna Resultado {mes1} -- ver nota en _tabla
    sobre por qué {mes2} ya no lleva ícono por fila, solo color y esta nota (2026-08-07)."""
    return [
        Paragraph(
            f"* Cifras de {mes2_str} preliminares -- el mes cerró recientemente y SAP puede "
            f"seguir recibiendo ajustes en las próximas semanas.",
            _STYLE_NOTE_ASTERISCO,
        ),
        Spacer(1, 4),
        _LeyendaIcono(
            "provisional",
            f"(en la columna Resultado {mes1_str}) PROVISIONAL: el mes cerró recientemente y "
            f"SAP puede seguir recibiendo ajustes -- esta cifra no es definitiva.",
            width=PAGE_W,
        ),
        Spacer(1, 2),
        _LeyendaIcono(
            "sin_referencia",
            f"(en la columna Resultado {mes1_str}) SIN_REFERENCIA: no había snapshot disponible "
            f"para esa sociedad/mes -- no se pudo verificar si es estable (distinto de "
            f"PROVISIONAL: aquí simplemente no se sabe).",
            width=PAGE_W,
        ),
    ]


def build_pdf(df, mes1_str, mes2_str, fecha_str, chart_path, output_path):
    doc = SimpleDocTemplate(
        output_path, pagesize=landscape(letter),
        leftMargin=15 * mm, rightMargin=15 * mm, topMargin=12 * mm, bottomMargin=12 * mm,
    )
    story = [
        _header(mes1_str, mes2_str, fecha_str),
        Spacer(1, 7),
        _stat_tiles(df, mes1_str, mes2_str),
        Spacer(1, 8),
        _chart_panel(chart_path),
        Spacer(1, 8),
        _tabla(df, mes1_str, mes2_str),
        Spacer(1, 6),
    ]
    story.extend(_leyenda_estatus(mes1_str, mes2_str))
    doc.build(story)
