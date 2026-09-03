"""Cálculo de las piezas gráficas del Resumen Mensual ETC -- todo se dibuja en HTML/CSS/SVG
puro (igual que el mockup: polyline a mano, conic-gradient para el donut, barras con
`width` en %), no hay imágenes PNG de por medio como en los otros reportes de este repo.
Este módulo solo calcula los números/puntos que la plantilla Jinja2 necesita interpolar.
"""

from config import COLORS

# --- Desempeño Financiero (SVG de líneas) -----------------------------------------------
# Mismo viewBox y rango de ejes que el mockup (0 0 590 180, x de 30 a 590, gridlines en
# 0/50M/100M/150M -> y 170/120/70/20). Se generaliza el techo del eje ("150M" en el
# mockup) a un "número redondo" por encima del máximo real de la serie, en vez de dejarlo
# fijo en 150M para siempre -- si el negocio crece más allá de eso, el eje se ajusta solo.
_SVG_X0, _SVG_X1 = 30, 590
_SVG_Y0, _SVG_Y_TOP = 170, 20  # y0 = eje en 0; y_top = borde superior del área de dibujo


_PASOS_CANDIDATOS = [5, 10, 25, 50, 100, 150, 200, 250, 500, 1000, 2500, 5000]


def _paso_redondo(max_valor_millones):
    """El incremento "bonito" entre gridlines (ej. 50 -> 0/50/100/150) tal que 3 pasos
    (4 gridlines incluido el 0) alcancen a cubrir el máximo real de la serie. Igual
    criterio que el mockup (150M de techo, pasos de 50M) pero calculado, no fijo.

    Margen del 2%: si el máximo real se pasa del techo candidato por una fracción chica
    (ej. 150.6M contra un techo de 150M), se prefiere igual el paso más fino -- el punto
    sobresale unos pocos px del gridline superior en vez de saltar a un paso mucho más
    grueso (100M) por una diferencia que ni se nota."""
    for paso in _PASOS_CANDIDATOS:
        if paso * 3 >= max_valor_millones * 0.98:
            return paso
    return _PASOS_CANDIDATOS[-1]


def calcular_grafico_desempeno(serie_df):
    """serie_df: DataFrame con columnas MES_CONTABLE (datetime), ingreso, gasto, ordenado
    ascendente (salida de datos.fetch_serie_desempeno). Devuelve dict listo para la
    plantilla: polylines, círculos, gridlines y etiquetas de mes."""
    n = len(serie_df)
    max_millones = max(serie_df["ingreso"].max(), serie_df["gasto"].max()) / 1_000_000
    paso = _paso_redondo(max_millones)
    techo_millones = paso * 3
    escala = (_SVG_Y0 - _SVG_Y_TOP) / techo_millones  # px por millón

    def _y(valor):
        return _SVG_Y0 - (valor / 1_000_000) * escala

    def _x(i):
        return _SVG_X0 if n <= 1 else _SVG_X0 + i * (_SVG_X1 - _SVG_X0) / (n - 1)

    puntos_ingreso = [(_x(i), _y(v)) for i, v in enumerate(serie_df["ingreso"])]
    puntos_gasto = [(_x(i), _y(v)) for i, v in enumerate(serie_df["gasto"])]

    gridlines = []
    for i in range(4):
        valor_m = paso * i
        etiqueta = "0" if i == 0 else f"{valor_m:.0f}M"
        gridlines.append({"y": round(_y(valor_m * 1_000_000), 1), "label": etiqueta})

    meses_abrev = ["ENE", "FEB", "MAR", "ABR", "MAY", "JUN", "JUL", "AGO", "SEP", "OCT", "NOV", "DIC"]
    return {
        "polyline_ingresos": " ".join(f"{x:.1f},{y:.1f}" for x, y in puntos_ingreso),
        "polyline_gastos": " ".join(f"{x:.1f},{y:.1f}" for x, y in puntos_gasto),
        "circulos_ingresos": [{"cx": round(x, 1), "cy": round(y, 1)} for x, y in puntos_ingreso],
        "circulos_gastos": [{"cx": round(x, 1), "cy": round(y, 1)} for x, y in puntos_gasto],
        "gridlines": gridlines,
        "meses": [meses_abrev[m.month - 1] for m in serie_df["MES_CONTABLE"]],
        "x0": _SVG_X0, "x1": _SVG_X1,
    }


# --- Composición de Ingresos (donut) -----------------------------------------------------

def calcular_donut(filas_composicion):
    """filas_composicion: salida de datos.fetch_composicion_ingresos (lista ordenada de
    {categoria, monto, pct}). Devuelve el string CSS de conic-gradient + la leyenda con
    su color ya asignado (mismo orden -> mismo color que config.COLORS['donut'])."""
    stops = []
    acumulado_pct = 0.0
    legend = []
    for i, fila in enumerate(filas_composicion):
        color = COLORS["donut"][i % len(COLORS["donut"])]
        inicio = acumulado_pct * 360
        acumulado_pct += fila["pct"]
        fin = acumulado_pct * 360
        stops.append(f"{color} {inicio:.1f}deg {fin:.1f}deg")
        legend.append({"categoria": fila["categoria"], "pct": fila["pct"], "color": color})
    return {"gradient_css": "conic-gradient(" + ", ".join(stops) + ")", "legend": legend}


# --- Principales Gastos (barras) ---------------------------------------------------------

def calcular_barras_gasto(filas_top_gastos):
    """Ancho de barra relativo al concepto más grande (el top 1 = 100%), igual que el
    mockup (Diesel 100%, Casetas 43%, ...)."""
    if not filas_top_gastos:
        return []
    maximo = filas_top_gastos[0]["monto"]
    return [
        {**fila, "ancho_pct": round((fila["monto"] / maximo) * 100) if maximo else 0}
        for fila in filas_top_gastos
    ]
