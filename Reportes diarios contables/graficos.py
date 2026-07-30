"""Gráfico igual al formato de referencia (reporte-cuentas-actual.png): barras
verticales agrupadas (anterior/actual) en el eje izquierdo + línea de % de
variación en un eje secundario derecho. El % se limita a +/-PCT_CAP (como la
referencia, que lo topa en 500%) para que un caso extremo (base casi cero) no
rompa la escala; los casos sin base material se muestran como hueco en la línea."""

import math

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np

from config import COLORS, MAX_SOCIEDADES_EN_GRAFICO

PCT_CAP = 5.0  # +/-500%, igual que la referencia


def _elegir_unidad(max_valor):
    max_abs = abs(max_valor) or 1
    if max_abs >= 1_000_000:
        return 1_000_000, "Millones $"
    if max_abs >= 1_000:
        return 1_000, "Miles $"
    return 1, "$"


def build_chart(df, cuenta_nombre, current_year, prior_year, out_path):
    df = df.copy()
    df["orden"] = df["actual"].abs()
    df = df.sort_values("orden", ascending=False)

    truncado = len(df) > MAX_SOCIEDADES_EN_GRAFICO
    df = df.head(MAX_SOCIEDADES_EN_GRAFICO)

    divisor, unidad = _elegir_unidad(df[["actual", "anterior"]].abs().to_numpy().max())

    fig, ax1 = plt.subplots(figsize=(10, 5), dpi=150)
    fig.patch.set_facecolor(COLORS["surface"])
    ax1.set_facecolor(COLORS["surface"])

    x = np.arange(len(df))
    width = 0.36
    ax1.bar(x - width / 2, df["anterior"] / divisor, width,
            color=COLORS["anterior"], label=f"{prior_year} (Millones $)", zorder=2)
    ax1.bar(x + width / 2, df["actual"] / divisor, width,
            color=COLORS["actual"], label=f"{current_year} - Hoy (Millones $)", zorder=2)

    ax1.set_ylabel(unidad, fontsize=9, color=COLORS["text_secondary"])
    ax1.set_xticks(x)
    ax1.set_xticklabels(df["nombre_sociedad"], rotation=40, ha="right", fontsize=8,
                         color=COLORS["text_secondary"])
    ax1.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{v:,.0f}"))
    ax1.tick_params(axis="y", length=0, colors=COLORS["muted"], labelsize=8)
    ax1.tick_params(axis="x", length=0)
    ax1.grid(axis="y", color=COLORS["grid"], linewidth=0.8, zorder=0)
    ax1.set_axisbelow(True)
    for spine in ("top", "left", "right"):
        ax1.spines[spine].set_visible(False)
    ax1.spines["bottom"].set_color(COLORS["muted"])

    # % variación, topado a +/-PCT_CAP (igual que la referencia limita a 500%).
    # Huecos (NaN) donde la base no es material -> la línea se corta ahí, no inventa un valor.
    pct_capped = df["pct_variacion"].clip(-PCT_CAP, PCT_CAP)
    ax2 = ax1.twinx()
    ax2.plot(x, pct_capped * 100, color=COLORS["critical"], marker="o", markersize=4.5,
              linewidth=1.6, label=f"% Variación (máx ±{PCT_CAP:.0%})", zorder=3)
    ax2.set_ylabel("% Variación", fontsize=9, color=COLORS["critical"])
    ax2.tick_params(axis="y", colors=COLORS["critical"], labelsize=8, length=0)
    ax2.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{v:.0f}%"))
    ax2.set_ylim(-PCT_CAP * 100 - 20, PCT_CAP * 100 + 20)
    for spine in ("top", "left"):
        ax2.spines[spine].set_visible(False)
    ax2.spines["right"].set_color(COLORS["critical"])

    # Marca los puntos que sí se recortaron (excedían el tope) para no ocultar que hay más.
    for i, pct in enumerate(df["pct_variacion"]):
        if pct == pct and abs(pct) > PCT_CAP:
            y_marca = (PCT_CAP if pct > 0 else -PCT_CAP) * 100
            ax2.annotate(f"{pct:+.0%}", (x[i], y_marca), textcoords="offset points",
                         xytext=(0, 8 if pct > 0 else -12), ha="center", fontsize=6.5,
                         color=COLORS["critical"], fontweight="bold")

    ax1.set_title(cuenta_nombre, fontsize=13, color=COLORS["text_primary"], fontweight="bold", loc="left")

    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, frameon=False, fontsize=7.5,
               loc="upper right", labelcolor=COLORS["text_secondary"])

    if truncado:
        fig.text(0.5, 0.01, f"Mostrando las {MAX_SOCIEDADES_EN_GRAFICO} sociedades con mayor monto — "
                             f"el resto está en la tabla adjunta.",
                  ha="center", fontsize=7, color=COLORS["muted"])

    fig.tight_layout()
    fig.savefig(out_path, facecolor=fig.get_facecolor())
    plt.close(fig)
    return truncado
