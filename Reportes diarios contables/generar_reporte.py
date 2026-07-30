"""Genera el PDF diario de cuentas contables PROAN a partir de sap_faglflext.

Uso:
    python generar_reporte.py

Requiere credenciales de Application Default Credentials para BigQuery:
    gcloud auth application-default login
"""

import os
import datetime

from google.cloud import bigquery

from config import PROJECT_ID, CUENTAS, CUENTAS_ACTIVAS, OUTPUT_DIR
from datos import fetch_cuenta, fetch_sociedades
from graficos import build_chart
from pdf import build_section, build_pdf


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    hoy = datetime.date.today()
    current_year = hoy.year
    prior_year = current_year - 1
    hist_years = list(range(current_year - 4, current_year + 1))
    fecha_str = hoy.strftime("%d/%m/%Y")

    client = bigquery.Client(project=PROJECT_ID)
    sociedades = fetch_sociedades(client)
    print(f"Sociedades cargadas desde D20_DIMENSION.dm_company: {len(sociedades)}")

    sections = []
    for nombre_cuenta in CUENTAS_ACTIVAS:
        raccts = CUENTAS[nombre_cuenta]
        print(f"--- {nombre_cuenta} ({', '.join(raccts)}) ---")
        sql, df = fetch_cuenta(client, raccts, hist_years, current_year, prior_year, sociedades)
        print(sql)
        print(df[["sociedad", "nombre_sociedad", "anterior", "actual", "diferencia", "pct_variacion"]]
              .to_string(index=False))

        chart_path = os.path.join(OUTPUT_DIR, f"_chart_{nombre_cuenta.replace(' ', '_')}.png")
        build_chart(df, nombre_cuenta, current_year, prior_year, chart_path)

        sections.append(
            build_section(nombre_cuenta, raccts, df, chart_path, fecha_str, current_year, prior_year)
        )

    output_path = os.path.join(OUTPUT_DIR, f"reporte_cuentas_proan_{hoy.isoformat()}.pdf")
    build_pdf(sections, output_path)
    print(f"\nPDF generado: {output_path}")


if __name__ == "__main__":
    main()
