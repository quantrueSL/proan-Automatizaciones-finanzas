"""Genera el PDF diario de cuentas contables PROAN a partir de sap_faglflext.

Uso:
    python generar_reporte.py

Requiere credenciales de Application Default Credentials para BigQuery:
    gcloud auth application-default login
"""

import os
import datetime

from google.cloud import bigquery

from config import PROJECT_ID, CUENTAS, CUENTAS_ACTIVAS, OUTPUT_DIR, SOCIEDADES
from datos import fetch_cuenta, fetch_sociedades, fetch_descuentos
from graficos import build_chart, build_chart_descuentos
from pdf import build_section, build_pdf, build_section_descuentos


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

    print("--- Descuentos y Bonificaciones (RACCT 000401%) ---")
    sql_desc, df_desc = fetch_descuentos(client, current_year, prior_year, SOCIEDADES)
    print(sql_desc)
    print(df_desc[["sociedad", "nombre_sociedad", "ingresos_anterior", "ingresos_actual",
                    "descuentos_anterior", "descuentos_actual", "pct_anterior", "pct_actual"]]
          .to_string(index=False))

    chart_path_desc = os.path.join(OUTPUT_DIR, "_chart_Descuentos_y_Bonificaciones.png")
    build_chart_descuentos(df_desc, current_year, prior_year, chart_path_desc)
    sections.append(
        build_section_descuentos(df_desc, chart_path_desc, fecha_str, current_year, prior_year)
    )

    # Variación de Precios: mismo mecanismo genérico que Gastos no Deducibles (fetch_cuenta +
    # build_chart + build_section, formato único), pero usa el catálogo SOCIEDADES (no
    # dm_company) y va al final del PDF (ver nota de validación en config.py: la fuente de
    # verdad de esta cuenta es el árbol de SAP, no el Excel de finanzas).
    raccts_precios = CUENTAS["Variación de Precios"]
    print(f"--- Variación de Precios ({', '.join(raccts_precios)}) ---")
    sql_precios, df_precios = fetch_cuenta(
        client, raccts_precios, hist_years, current_year, prior_year, SOCIEDADES
    )
    print(sql_precios)
    print(df_precios[["sociedad", "nombre_sociedad", "anterior", "actual", "diferencia", "pct_variacion"]]
          .to_string(index=False))

    chart_path_precios = os.path.join(OUTPUT_DIR, "_chart_Variacion_de_Precios.png")
    build_chart(df_precios, "Variación de Precios", current_year, prior_year, chart_path_precios)
    sections.append(
        build_section("Variación de Precios", raccts_precios, df_precios,
                       chart_path_precios, fecha_str, current_year, prior_year)
    )

    output_path = os.path.join(OUTPUT_DIR, f"reporte_cuentas_proan_{hoy.isoformat()}.pdf")
    build_pdf(sections, output_path)
    print(f"\nPDF generado: {output_path}")


if __name__ == "__main__":
    main()
