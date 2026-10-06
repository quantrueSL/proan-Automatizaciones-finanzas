"""Gráfica del histórico de precio de una alerta: cada punto es una línea de factura."""
import io

import matplotlib
matplotlib.use("Agg")  # sin pantalla (Cloud Run)
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd
from reportlab.lib.units import mm
from reportlab.platypus import Image

import config


def historico_de(alerta, hist):
    """Ventas del mismo material y sociedad, marcando cuáles son del cliente y cuáles de la propia alerta."""
    h = hist[(hist.company_code == alerta.sociedad) & (hist.material_number.str.lstrip("0") == alerta.material)
             & (hist.sales_unit == alerta.unidad) & (hist.billing_date <= alerta.fecha)].copy()
    h["es_cliente"] = h.customer_code.isin(alerta.clientes)
    h["es_alerta"] = (h.billing_document + "|" + h.item_number).isin(alerta.lineas)
    return h


def grafica(g, h, ancho_mm=180, alto_mm=57):
    plt.rcParams["font.family"] = "DejaVu Sans"
    fig, ax = plt.subplots(figsize=(ancho_mm / 25.4, alto_mm / 25.4), dpi=200)
    otros = h[~h.es_cliente]
    cli = h[h.es_cliente & ~h.es_alerta]
    alerta = h[h.es_alerta]
    x0 = g.fecha - pd.DateOffset(months=config.MESES_HISTORICO)
    x1 = g.fecha + pd.Timedelta(days=24)
    umbral = g.esperado / 2 if g.dif < 0 else g.esperado * 2

    # Escala: que entren el esperado, el umbral, la venta y el grueso del histórico
    precios = h.precio_kg if len(h) else pd.Series([g.precio])
    base = pd.concat([precios.clip(precios.quantile(.02), precios.quantile(.98)),
                      pd.Series([g.esperado, umbral, g.precio])])
    lo, hi = base.min(), base.max()
    pad = (hi - lo) * .14 or 1
    y0, y1 = max(0, lo - pad), hi + pad
    rango = y1 - y0

    # Zona que el modelo considera grave
    if g.dif < 0:
        ax.axhspan(y0, umbral, color=config.C_ZONA, lw=0, zorder=0)
    else:
        ax.axhspan(umbral, y1, color=config.C_ZONA, lw=0, zorder=0)

    if len(otros) > 2500:
        otros = otros.sample(2500, random_state=1)
    if len(cli) > 2500:
        cli = cli.sample(2500, random_state=1)
    pocos = len(otros) + len(cli) < 60  # con pocas ventas, puntos más grandes y opacos para que se vean
    ax.scatter(otros.billing_date, otros.precio_kg, s=34 if pocos else 11,
               color="#7d8783" if pocos else config.C_OTROS, alpha=.9 if pocos else (.5 if len(otros) < 800 else .3),
               lw=0, zorder=2)
    ax.scatter(cli.billing_date, cli.precio_kg, s=34 if pocos else 16, color=config.C_CLIENTE, alpha=.9, zorder=3,
               edgecolor="white", linewidth=.5)
    ax.axhline(g.esperado, color=config.INK, lw=1.1, ls=(0, (4, 3)), zorder=4)
    if len(alerta):
        ax.scatter(alerta.billing_date, alerta.precio_kg, s=75, color=config.C_ALERTA, zorder=7,
                   edgecolor="white", linewidth=1.2)
    else:  # la línea de la alerta aún no está en el histórico SAP: se marca con el precio de la alerta
        ax.scatter([g.fecha], [g.precio], s=75, color=config.C_ALERTA, zorder=7, edgecolor="white", linewidth=1.2)

    fs = 7.4
    ax.text(1.01, (g.esperado - y0) / rango, f"Esperado\n${g.esperado:,.2f}", transform=ax.transAxes,
            va="center", ha="left", fontsize=fs, color=config.INK, fontweight="bold", clip_on=False)
    quien = "Este cliente" if g.n_clientes == 1 else ("Estas tiendas" if g.publico else "Estos clientes")
    ley = [plt.Line2D([], [], ls="", marker="o", ms=5, mfc=config.C_CLIENTE, mec="white", label=quien),
           plt.Line2D([], [], ls="", marker="o", ms=4.5, mfc=config.C_OTROS, mec="none", label="Otros clientes"),
           plt.Line2D([], [], ls="", marker="o", ms=7, mfc=config.C_ALERTA, mec="white", label="Venta de la alerta")]
    ax.legend(handles=ley, loc="lower left", bbox_to_anchor=(0, 1.0), ncol=3, frameon=False, fontsize=fs,
              handletextpad=.3, columnspacing=1.4, borderaxespad=.2)
    if g.dif < 0:
        ax.text(x0 + pd.Timedelta(days=3), umbral - rango * .03,
                f"Zona grave: menos de la mitad del esperado (< ${umbral:,.2f})",
                va="top", ha="left", fontsize=6.6, color=config.CRIT)
    else:
        ax.text(x0 + pd.Timedelta(days=3), umbral + rango * .03,
                f"Zona grave: más del doble del esperado (> ${umbral:,.2f})",
                va="bottom", ha="left", fontsize=6.6, color=config.CRIT)
    ax.annotate(f"Esta venta ${g.precio:,.2f}", (g.fecha, g.precio), xytext=(-9, 0), textcoords="offset points",
                ha="right", va="center", fontsize=fs, color=config.C_ALERTA, fontweight="bold", zorder=8,
                bbox=dict(boxstyle="round,pad=0.25", fc="white", ec="none", alpha=.9))

    ax.set_ylim(y0, y1)
    ax.set_xlim(x0, x1)
    for s in ["top", "right", "left"]:
        ax.spines[s].set_visible(False)
    ax.spines["bottom"].set_color(config.LINE)
    ax.tick_params(axis="both", colors=config.MUTED, labelsize=7.2, length=0, pad=3)
    ax.grid(axis="y", color="#e9ecea", lw=.6)
    ax.set_axisbelow(True)
    ax.xaxis.set_major_locator(mdates.MonthLocator(bymonthday=15))
    ax.xaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: config.MES_CORTO[mdates.num2date(x).month - 1]))
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"${v:,.0f}"))
    ax.yaxis.set_major_locator(plt.MaxNLocator(5))
    fig.tight_layout(pad=.25)
    fig.subplots_adjust(right=.83)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=200)
    plt.close(fig)
    buf.seek(0)
    return Image(buf, width=ancho_mm * mm, height=alto_mm * mm)
