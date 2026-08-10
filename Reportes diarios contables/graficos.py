"""Gráfico igual al formato de referencia (reporte-cuentas-actual.png): barras
verticales agrupadas (anterior/actual) en el eje izquierdo + línea de % de
variación en un eje secundario derecho. El % se limita a +/-PCT_CAP (como la
referencia, que lo topa en 500%) para que un caso extremo (base casi cero) no
rompa la escala; los casos sin base material se muestran como hueco en la línea."""

import math
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.font_manager as fm
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np

from config import (
    COLORS, MAX_SOCIEDADES_EN_GRAFICO, UMBRAL_MATERIALIDAD_MXN, FONT_REGULAR_TTF, FONT_BOLD_TTF,
)

# Misma sans-serif que los títulos del PDF (pdf.py): IBM Plex Sans, registrada desde los TTF
# embebidos en fonts/ en vez de depender de que esté instalada en el sistema (así el gráfico
# se ve igual sin importar el SO donde se genere). Se registran Regular Y Bold -- solo el
# Regular hacía que matplotlib no encontrara el peso bold del título y lo simulara mal
# (warning "Failed to find font weight bold"). Si los archivos no están, cae al sans-serif
# por defecto de matplotlib en vez de romper.
if os.path.exists(FONT_REGULAR_TTF) and os.path.exists(FONT_BOLD_TTF):
    fm.fontManager.addfont(FONT_REGULAR_TTF)
    fm.fontManager.addfont(FONT_BOLD_TTF)
    plt.rcParams["font.family"] = fm.FontProperties(fname=FONT_REGULAR_TTF).get_name()

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

    fig, ax1 = plt.subplots(figsize=(10, 3.8), dpi=150)
    fig.patch.set_facecolor(COLORS["tile_bg"])
    ax1.set_facecolor(COLORS["tile_bg"])

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
    ax1.grid(axis="y", color=COLORS["grid"], linewidth=0.5, zorder=0)
    ax1.set_axisbelow(True)
    for spine in ("top", "left", "right"):
        ax1.spines[spine].set_visible(False)
    ax1.spines["bottom"].set_color(COLORS["muted"])

    # % variación, topado a +/-PCT_CAP (igual que la referencia limita a 500%).
    # Donde la base no es material (NaN) se traza como 0 para que la línea quede unida sin
    # cortes; ese punto se marca aparte (hueco + "N/A") para no confundirlo con un 0% real.
    # Color: pct_line (navy medio), no "critical" -- la línea es una serie de datos, no un
    # indicador de signo/estado (esos siguen siendo good/critical, reservados para eso).
    pct_original = df["pct_variacion"]
    pct_capped = pct_original.fillna(0.0).clip(-PCT_CAP, PCT_CAP)
    ax2 = ax1.twinx()
    ax2.plot(x, pct_capped * 100, color=COLORS["pct_line"], marker="o", markersize=4.5,
              linewidth=1.6, label=f"% Variación (máx ±{PCT_CAP:.0%})", zorder=3)

    for i, pct in enumerate(pct_original):
        if pct != pct:  # NaN: base no material, marcado como hueco sobre la línea unida
            ax2.plot(x[i], pct_capped.iloc[i] * 100, marker="o", markersize=5.5,
                      markerfacecolor=COLORS["tile_bg"], markeredgecolor=COLORS["pct_line"],
                      markeredgewidth=1.4, zorder=4)
            ax2.annotate("N/A", (x[i], pct_capped.iloc[i] * 100), textcoords="offset points",
                         xytext=(0, 8), ha="center", fontsize=6.5, color=COLORS["muted"],
                         fontweight="bold")
    ax2.set_ylabel("% Variación", fontsize=9, color=COLORS["pct_line"])
    ax2.tick_params(axis="y", colors=COLORS["pct_line"], labelsize=8, length=0)
    ax2.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{v:.0f}%"))
    # Margen superior más grande que el inferior: cuando hay varios puntos recortados
    # (ej. Mermas, con variaciones de decenas de miles de %), sus etiquetas "+NNNNN%" need
    # sitio para no chocar con el título del gráfico (visto con datos reales de Mermas).
    ax2.set_ylim(-PCT_CAP * 100 - 20, PCT_CAP * 100 + 55)
    for spine in ("top", "left"):
        ax2.spines[spine].set_visible(False)
    ax2.spines["right"].set_color(COLORS["pct_line"])

    # Marca los puntos que sí se recortaron (excedían el tope) para no ocultar que hay más.
    for i, pct in enumerate(df["pct_variacion"]):
        if pct == pct and abs(pct) > PCT_CAP:
            y_marca = (PCT_CAP if pct > 0 else -PCT_CAP) * 100
            ax2.annotate(f"{pct:+.0%}", (x[i], y_marca), textcoords="offset points",
                         xytext=(0, 8 if pct > 0 else -12), ha="center", fontsize=6.5,
                         color=COLORS["pct_line"], fontweight="bold")

    ax1.set_title(cuenta_nombre, fontsize=13, color=COLORS["text_primary"], fontweight="bold",
                  loc="left", pad=14)

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


def build_chart_descuentos(df, current_year, prior_year, out_path):
    """Descuentos 2025 vs 2026 (NO Ingresos): Ingresos vive en una escala miles de veces
    mayor que Descuentos (miles de millones vs. cientos de millones), así que graficarlos
    juntos aplastaba las barras de Descuentos y la línea de % quedaba pegada a cero e
    ilegible. Las cards y la tabla siguen mostrando Ingresos/Descuentos/% -- esto es
    solo el gráfico.

    Se arma un DataFrame "traducido" a la forma genérica de build_chart
    (actual/anterior/pct_variacion) y se delega ahí -- misma función, mismo estilo, que
    Gastos no Deducibles y Variación de Precios (familia visual única)."""
    shim = df[["nombre_sociedad"]].copy()
    shim["actual"] = df["descuentos_actual"]
    shim["anterior"] = df["descuentos_anterior"]
    diferencia = shim["actual"] - shim["anterior"]
    # % Variación de Descuentos entre periodos (no Descuentos/Ingresos). Mismo criterio de
    # materialidad que el resto del reporte: base ~0 -> NaN -> build_chart la dibuja como
    # hueco + "N/A" en vez de una división por cero.
    shim["pct_variacion"] = np.where(
        shim["anterior"].abs() < UMBRAL_MATERIALIDAD_MXN, np.nan, diferencia / shim["anterior"].abs()
    )
    return build_chart(shim, "Descuentos y Bonificaciones", current_year, prior_year, out_path)
