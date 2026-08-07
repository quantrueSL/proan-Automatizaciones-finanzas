"""Genera el PDF "Resultado Financiero Mensual" (Ingresos/Egresos/Resultado, últimos 2 meses
YA CERRADOS -- el mes en curso no aparece) a partir de sap_faglflext. Reporte SEPARADO del
diario y de las 4 cuentas contables.

Uso:
    python generar_reporte.py

Estado: SOLO genera el PDF localmente para revisión.
"""

import os
import datetime

from google.cloud import bigquery

from config import PROJECT_ID, OUTPUT_DIR, SOCIEDADES, FILTRAR_SOCIEDADES_SIN_ACTIVIDAD_RECIENTE
from datos import fetch_resultado_mensual
from graficos import build_chart_mensual
from pdf import build_pdf

_MESES_ES = [
    "", "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
    "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre",
]


def _mes_str(fecha):
    return f"{_MESES_ES[fecha.month]} {fecha.year}"


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    hoy = datetime.date.today()
    fecha_str = hoy.strftime("%d/%m/%Y")

    client = bigquery.Client(project=PROJECT_ID)
    sql, snapshot_table, df = fetch_resultado_mensual(client, hoy, SOCIEDADES)

    mes1_str = _mes_str(df["mes1"].iloc[0])
    mes2_str = _mes_str(df["mes2"].iloc[0])

    print(f"--- Resultado Financiero Mensual ({fecha_str}) ---")
    print(f"Snapshot de referencia usado para el chequeo de estabilidad: {snapshot_table}")
    print(f"Meses mostrados (ambos cerrados): {mes1_str} (m1) / {mes2_str} (m2)")
    print(sql)

    n_total = len(df)
    if FILTRAR_SOCIEDADES_SIN_ACTIVIDAD_RECIENTE:
        sin_actividad = df[
            df[["ing_m1", "egr_m1", "ing_m2", "egr_m2"]].isna().all(axis=1)
        ]
        if len(sin_actividad):
            print(f"\nSociedades excluidas del reporte por no tener NINGÚN dato en los 2 meses "
                  f"mostrados (actividad histórica, no de {mes1_str}-{mes2_str}):")
            print(sin_actividad[["sociedad", "nombre_sociedad"]].to_string(index=False))
        df = df.drop(sin_actividad.index).reset_index(drop=True)
    print(f"\nSociedades en el reporte: {len(df)} de {n_total} códigos devueltos por la query.")

    print(df[["sociedad", "nombre_sociedad", "resultado_m1", "estatus_m1",
              "resultado_m2", "estatus_m2", "pct_variacion"]].to_string(index=False))

    for mes_str, col in ((mes1_str, "estatus_m1"), (mes2_str, "estatus_m2")):
        provisional = df[df[col] == "PROVISIONAL"]
        sin_ref = df[df[col] == "SIN_REFERENCIA"]
        print(f"\n{mes_str}: {len(provisional)} sociedad(es) PROVISIONAL, {len(sin_ref)} SIN_REFERENCIA.")
        if len(provisional):
            print("  PROVISIONAL:", ", ".join(provisional["nombre_sociedad"]))
        if len(sin_ref):
            print("  SIN_REFERENCIA:", ", ".join(sin_ref["nombre_sociedad"]))

    chart_path = os.path.join(OUTPUT_DIR, "_chart_resultado_mensual.png")
    build_chart_mensual(df, mes1_str, mes2_str, chart_path)

    output_path = os.path.join(OUTPUT_DIR, f"resultado_financiero_mensual_{hoy.isoformat()}.pdf")
    build_pdf(df, mes1_str, mes2_str, fecha_str, chart_path, output_path)
    print(f"\nPDF generado: {output_path}")


if __name__ == "__main__":
    main()
