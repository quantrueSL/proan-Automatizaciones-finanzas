"""Gráfico: Resultado (Ingresos - Egresos) de los 2 meses mostrados, barras agrupadas por
sociedad. Reducido de 3 a 2 barras por sociedad (2026-08-07, mismo cambio que el resto del
reporte). Mismo estilo visual que "Reportes diarios contables/graficos.py" (IBM Plex, fondo
tile_bg, grid horizontal muy tenue, spines mínimos)."""

import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.font_manager as fm
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np

from config import COLORS, FONT_REGULAR_TTF, FONT_BOLD_TTF

if os.path.exists(FONT_REGULAR_TTF) and os.path.exists(FONT_BOLD_TTF):
    fm.fontManager.addfont(FONT_REGULAR_TTF)
    fm.fontManager.addfont(FONT_BOLD_TTF)
    plt.rcParams["font.family"] = fm.FontProperties(fname=FONT_REGULAR_TTF).get_name()


def _elegir_unidad(max_valor):
    max_abs = abs(max_valor) or 1
    if max_abs >= 1_000_000:
        return 1_000_000, "Millones $"
    if max_abs >= 1_000:
        return 1_000, "Miles $"
    return 1, "$"


def _filtrar_sin_actividad(df):
    """Saca del GRÁFICO (no de la tabla, ver pdf.py) cualquier sociedad con Ingresos=0 Y
    Egresos=0 en AMBOS meses mostrados -- pedido explícito del usuario (2026-08-07), caso
    genérico (no hardcodeado a PIN, aunque ese fue el caso que lo motivó: sus 4 valores dan
    exactamente $0, una barra en cero no aporta nada y solo ocupa espacio en el eje X)."""
    sin_actividad = (
        (df["ing_m1"].fillna(0).abs() < 0.005) & (df["egr_m1"].fillna(0).abs() < 0.005) &
        (df["ing_m2"].fillna(0).abs() < 0.005) & (df["egr_m2"].fillna(0).abs() < 0.005)
    )
    return df[~sin_actividad].copy()


def build_chart_mensual(df, nombre_m1, nombre_m2, out_path, figsize=(10, 5.2)):
    """df: columnas sociedad/nombre_sociedad, ing_m1/egr_m1, ing_m2/egr_m2, resultado_m1/m2.
    Barras agrupadas de 2 por sociedad, ordenadas por |resultado_m2| (mes actual) descendente."""
    df = _filtrar_sin_actividad(df)
    df = df.copy()
    df["orden"] = df["resultado_m2"].abs()
    df = df.sort_values("orden", ascending=False)

    divisor, unidad = _elegir_unidad(df[["resultado_m1", "resultado_m2"]].abs().to_numpy().max())

    fig, ax = plt.subplots(figsize=figsize, dpi=150)
    fig.patch.set_facecolor(COLORS["tile_bg"])
    ax.set_facecolor(COLORS["tile_bg"])

    x = np.arange(len(df))
    width = 0.36
    ax.bar(x - width / 2, df["resultado_m1"] / divisor, width, color=COLORS["anterior"], label=nombre_m1, zorder=2)
    ax.bar(x + width / 2, df["resultado_m2"] / divisor, width, color=COLORS["actual"], label=nombre_m2, zorder=2)

    ax.axhline(0, color=COLORS["muted"], linewidth=0.6, zorder=1)
    ax.set_ylabel(unidad, fontsize=9, color=COLORS["text_secondary"])
    ax.set_xticks(x)
    ax.set_xticklabels(df["nombre_sociedad"] if len(df) <= 8 else df["sociedad"],
                        rotation=40 if len(df) <= 8 else 0, ha="right" if len(df) <= 8 else "center",
                        fontsize=8, color=COLORS["text_secondary"])
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{v:,.0f}"))
    ax.tick_params(axis="y", length=0, colors=COLORS["muted"], labelsize=8)
    ax.tick_params(axis="x", length=0)
    ax.grid(axis="y", color=COLORS["grid"], linewidth=0.5, zorder=0)
    ax.set_axisbelow(True)
    for spine in ("top", "left", "right"):
        ax.spines[spine].set_visible(False)
    ax.spines["bottom"].set_color(COLORS["muted"])

    ax.set_title("Resultado por sociedad -- últimos 2 meses", fontsize=13,
                 color=COLORS["text_primary"], fontweight="bold", loc="left", pad=14)
    ax.legend(frameon=False, fontsize=7.5, loc="upper right", labelcolor=COLORS["text_secondary"])

    fig.tight_layout()
    fig.savefig(out_path, facecolor=fig.get_facecolor())
    plt.close(fig)
