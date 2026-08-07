"""Gráfico de barras horizontales: top 5 sociedades por |Estado de Resultados| -- vuelto a
cambiar el 2026-08-07 (mismo día del rediseño premium) a pedido explícito del usuario:
"quiero que el gráfico muestre el resultado financiero de las 5 mejores sociedades".

Historial de esta métrica, para no volver a dar vueltas en círculo:
1. Versión original: top 5 por |Estado de Resultados| (proxy de "tamaño", porque este
   reporte no calcula ingresos reales).
2. Rediseño premium (mismo día): se cambió a top 5 por |Dif.| ("mayor diferencia", pedido
   explícito de ese brief) -- pero como este reporte casi siempre da Dif.=0.00 en las 19
   sociedades (es un cuadre, se espera que concilie), el gráfico se omitía casi todos los
   días por falta de datos que rankear.
3. Esta versión (revertida): de vuelta a |Estado de Resultados| -- el usuario prefiere ver
   siempre el tamaño de las sociedades más grandes, no depende de que exista una diferencia
   ese día. build_chart_top5() ya no recibe `tolerancia` (no la necesita)."""

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


def build_chart_top5(df, out_path):
    """df: columnas sociedad, nombre_sociedad, estado_resultados. Devuelve True si generó la
    imagen, False solo en el caso extremo de que TODAS las sociedades den $0 (nada que
    rankear -- no se ha visto en datos reales, pero se maneja igual que antes por seguridad)."""
    con_datos = df[df["estado_resultados"].abs() > 0.005]
    if con_datos.empty:
        return False

    top = con_datos.reindex(
        con_datos["estado_resultados"].abs().sort_values(ascending=False).index
    ).head(TOP_N)
    top = top.iloc[::-1]  # invertido: barh dibuja de abajo hacia arriba, la #1 queda arriba

    fig, ax = plt.subplots(figsize=(9.6, 2.6), dpi=150)
    fig.patch.set_facecolor(COLORS["surface"])
    ax.set_facecolor(COLORS["surface"])

    y = range(len(top))
    valores = top["estado_resultados"].to_numpy()
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

    # Título arriba de TODO (fig.suptitle, no ax.set_title): un ax.text() en coordenadas de
    # ejes por encima de y=1 (como se probó primero) se solapaba con el título de la propia
    # Axes porque tight_layout() no reserva espacio para texto fuera de sus límites -- se
    # veía como dos líneas de texto pisándose. suptitle + ax.set_title (subtítulo, pegado al
    # eje) son ambos mecanismos que matplotlib sí contempla al calcular el layout.
    fig.suptitle("Top 5 sociedades por Resultado Financiero", x=0.01, ha="left",
                 fontsize=12.5, fontweight="bold", color=COLORS["primary"])
    ax.set_title("Magnitud absoluta del Estado de Resultados", fontsize=8.5,
                 color=COLORS["muted"], loc="left", pad=8)

    fig.tight_layout(rect=(0, 0, 1, 0.88))
    fig.savefig(out_path, facecolor=fig.get_facecolor())
    plt.close(fig)
    return True
