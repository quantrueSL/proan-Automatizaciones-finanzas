"""KPIs e insights automáticos del cuadre -- calculados UNA vez aquí y reutilizados por
pdf.py y enviar_reporte.py (mismo criterio del resto del proyecto: no duplicar cálculos
entre el PDF y el correo). Todo lo que hay aquí sale de columnas que la query YA trae
(balance, estado_resultados, dif) -- no se inventa ningún dato nuevo.

Rediseño premium pedido por el usuario (2026-08-07): tarjetas KPI + insights de texto en
vez de una sola nota plana ("Ninguna sociedad muestra Dif. != 0 hoy")."""


def build_kpis(df, tolerancia):
    """Devuelve un dict con los 5 KPI del header: conciliadas, con_diferencias,
    diferencia_total (suma de |Dif.| -- magnitud total del descuadre), mayor_diferencia
    (la |Dif.| más grande, 0 si todas concilian) y su sociedad, y estado_general."""
    dif_abs = df["dif"].abs()
    con_diferencias = df[dif_abs > tolerancia]
    n_conciliadas = int((dif_abs <= tolerancia).sum())
    n_con_diferencias = len(con_diferencias)

    if n_con_diferencias:
        idx_mayor = con_diferencias["dif"].abs().idxmax()
        mayor_diferencia = float(abs(df.loc[idx_mayor, "dif"]))
        sociedad_mayor_diferencia = df.loc[idx_mayor, "nombre_sociedad"]
    else:
        mayor_diferencia = 0.0
        sociedad_mayor_diferencia = None

    return {
        "n_conciliadas": n_conciliadas,
        "n_con_diferencias": n_con_diferencias,
        "diferencia_total": float(dif_abs.sum()),
        "mayor_diferencia": mayor_diferencia,
        "sociedad_mayor_diferencia": sociedad_mayor_diferencia,
        "conciliado": n_con_diferencias == 0,
    }


def build_insights(df, kpis):
    """Bullets de texto, generados a partir de los mismos datos (nunca hardcodeados a un
    ejemplo) -- máximo 4, en orden de relevancia."""
    insights = []

    if kpis["conciliado"]:
        insights.append("No existen diferencias contables pendientes -- todas las sociedades concilian hoy.")
    else:
        insights.append(
            f"La mayor diferencia corresponde a {kpis['sociedad_mayor_diferencia']} "
            f"(${kpis['mayor_diferencia']:,.0f})."
        )

    # % que representan las 5 sociedades de mayor magnitud (|Estado de Resultados|) sobre el
    # total -- mismo criterio de "tamaño" que usa el gráfico cuando no hay diferencias que
    # graficar (ver graficos.py). Se calcula sobre valor absoluto porque el signo alterna
    # según utilidad/pérdida del periodo (ver memoria del proyecto), sumar con signo daría
    # una cifra sin sentido.
    magnitudes = df["estado_resultados"].abs().sort_values(ascending=False)
    total_magnitud = magnitudes.sum()
    if total_magnitud > 0:
        pct_top5 = magnitudes.head(5).sum() / total_magnitud * 100
        insights.append(
            f"Las cinco sociedades de mayor magnitud representan el {pct_top5:.0f}% del "
            f"total (en valor absoluto de Estado de Resultados)."
        )

    # Sociedades sin actividad contable (Balance y Resultados en $0) -- no es un error, pero
    # es información real y auto-detectable (ver nota de GSI en la memoria del proyecto).
    sin_actividad = df[(df["balance"].abs() < 0.005) & (df["estado_resultados"].abs() < 0.005)]
    if len(sin_actividad):
        nombres = ", ".join(sin_actividad["nombre_sociedad"].tolist())
        insights.append(f"{len(sin_actividad)} sociedad(es) sin actividad contable este año: {nombres}.")

    insights.append(
        "Resultado Fiscal: pendiente de identificar su fuente -- no se incluye en este reporte."
    )

    return insights[:4]
