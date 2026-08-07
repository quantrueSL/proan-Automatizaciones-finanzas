"""Gráfico de barras horizontales: top 5 sociedades por |Dif.| -- rediseño 2026-08-07 a
pedido explícito del usuario ("Top 5 sociedades con mayor diferencia" / "Magnitud absoluta
de la diferencia diaria"). Reemplaza la versión anterior (top 5 por |Estado de Resultados|,
usada como proxy porque este reporte no calcula ingresos) -- ahora que el propósito del
gráfico es explícitamente mostrar diferencias, |Dif.| es la métrica correcta y ya no hace
falta ningún proxy.

Caso especial: si NINGUNA sociedad tiene |Dif.| > tolerancia (como el 2026-08-07: las 19
dan Dif.=0.00), no hay nada que rankear -- un gráfico de 5 barras en $0 no comunica nada y
se ve roto. build_chart_top5() devuelve False en ese caso y NO genera imagen; pdf.py /
enviar_reporte.py omiten el panel del gráfico ese día (la tarjeta de estado ya cubre ese
mensaje: "todas las sociedades conciliaron")."""

import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.font_manager as fm
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker

from config import COLORS, FONT_REGULAR_TTF, FONT_BOLD_TTF

if os.path.exists(FONT_REGULAR_TTF) and os.path.exists(FONT_BOLD_TTF):
    fm.fontManager.addfont(FONT_REGULAR_TTF)
    fm.fontManager.addfont(FONT_BOLD_TTF)
    plt.rcParams["font.family"] = fm.FontProperties(fname=FONT_REGULAR_TTF).get_name()

TOP_N = 5


def _money_corta(v):
    signo = "-" if v < 0 else ""
    a = abs(v)
    if a >= 1_000_000_000:
        return f"{signo}${a / 1_000_000_000:,.2f}B"
    if a >= 1_000_000:
        return f"{signo}${a / 1_000_000:,.1f}M"
    if a >= 1_000:
        return f"{signo}${a / 1_000:,.1f}K"
    return f"{signo}${a:,.0f}"


def build_chart_top5(df, tolerancia, out_path):
    """df: columnas sociedad, nombre_sociedad, dif. Devuelve True si generó la imagen
    (había al menos 1 sociedad con |Dif.| > tolerancia), False si no había nada que graficar."""
    con_diferencia = df[df["dif"].abs() > tolerancia]
    if con_diferencia.empty:
        return False

    top = con_diferencia.reindex(
        con_diferencia["dif"].abs().sort_values(ascending=False).index
    ).head(TOP_N)
    top = top.iloc[::-1]  # invertido: barh dibuja de abajo hacia arriba, la #1 queda arriba

    fig, ax = plt.subplots(figsize=(9.6, 2.6), dpi=150)
    fig.patch.set_facecolor(COLORS["surface"])
    ax.set_facecolor(COLORS["surface"])

    y = range(len(top))
    valores = top["dif"].to_numpy()
    # Barras más gruesas que la versión anterior (0.62 vs 0.58) y color secundario de marca
    # para todas -- serie única, el eje ya identifica cada sociedad (ver dataviz: el color no
    # debe cargar identidad cuando la posición ya lo hace).
    ax.barh(y, valores, height=0.62, color=COLORS["secondary"], zorder=2)

    ax.set_yticks(list(y))
    ax.set_yticklabels(top["nombre_sociedad"], fontsize=9.5, color=COLORS["primary"], fontweight="bold")
    ax.tick_params(axis="y", length=0)
    ax.tick_params(axis="x", length=0, labelsize=7.5, colors=COLORS["muted"])
    ax.xaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: _money_corta(v)))
    # Grid MUY tenue, sin bordes (spines) -- pedido explícito del usuario.
    ax.grid(axis="x", color=COLORS["border"], linewidth=0.5, zorder=0)
    ax.set_axisbelow(True)
    for spine in ax.spines.values():
        spine.set_visible(False)

    max_abs = max(abs(v) for v in valores) if len(valores) else 1
    ax.set_xlim(min(0, valores.min()) - max_abs * 0.05, max_abs * 1.22)

    for i, v in enumerate(valores):
        texto = _money_corta(v)
        dentro = abs(v) > max_abs * 0.32
        if dentro:
            ax.annotate(texto, (v, i), textcoords="offset points", xytext=(-8, 0),
                        ha="right", va="center", fontsize=8.5, color="white", fontweight="bold")
        else:
            ax.annotate(texto, (v, i), textcoords="offset points", xytext=(8, 0),
                        ha="left", va="center", fontsize=8.5, color=COLORS["primary"],
                        fontweight="bold")

    ax.set_title("Top 5 sociedades con mayor diferencia", fontsize=12.5, color=COLORS["primary"],
                 fontweight="bold", loc="left", pad=16)
    ax.text(0, 1.155, "Magnitud absoluta de la diferencia diaria", transform=ax.transAxes,
            fontsize=8.5, color=COLORS["muted"])

    fig.tight_layout()
    fig.savefig(out_path, facecolor=fig.get_facecolor())
    plt.close(fig)
    return True
