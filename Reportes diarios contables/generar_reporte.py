"""Genera el PDF diario de cuentas contables PROAN a partir de sap_faglflext.

Uso:
    python generar_reporte.py

Requiere credenciales de Application Default Credentials para BigQuery:
    gcloud auth application-default login
"""

import os
import datetime

from google.cloud import bigquery

from config import (
    PROJECT_ID, CUENTAS, CUENTAS_ACTIVAS, CUENTAS_SOLO_DEBE, OUTPUT_DIR, SOCIEDADES,
    TITULOS_SECCION, NOTA_PRECIOS,
)
from datos import (
    fetch_cuenta, fetch_sociedades, fetch_descuentos, fetch_mermas_ratio, a_plantilla_importe,
)
from graficos import build_chart, build_chart_descuentos, build_chart_ratio
from pdf import (
    build_section, build_pdf, build_section_descuentos, build_section_mermas_ratio,
)


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
        solo_debe = nombre_cuenta in CUENTAS_SOLO_DEBE
        titulo = TITULOS_SECCION.get(nombre_cuenta, nombre_cuenta)
        print(f"--- {titulo} ({', '.join(raccts)}){' [solo Debe]' if solo_debe else ''} ---")
        sql, df = fetch_cuenta(client, raccts, hist_years, current_year, prior_year, sociedades,
                                solo_debe=solo_debe)
        print(sql)
        print(df[["sociedad", "nombre_sociedad", "anterior", "actual", "diferencia", "pct_variacion"]]
              .to_string(index=False))

        chart_path = os.path.join(OUTPUT_DIR, f"_chart_{nombre_cuenta.replace(' ', '_')}.png")
        build_chart(df, titulo, current_year, prior_year, chart_path)

        sections.append(
            build_section(titulo, raccts, df, chart_path, fecha_str, current_year, prior_year)
        )

    # Mermas, segunda forma: % sobre Costo Total (grupo CTOS). Va inmediatamente después de
    # Mermas — Importe para que las dos formas se puedan comparar de un vistazo y finanzas
    # decida cuál es la correcta (ver TITULOS_SECCION en config.py).
    raccts_mermas = CUENTAS["Mermas"]
    titulo_mermas_ratio = TITULOS_SECCION["Mermas ratio"]
    print(f"--- {titulo_mermas_ratio} ---")
    sql_mermas_ratio, df_mermas_ratio = fetch_mermas_ratio(
        client, raccts_mermas, current_year, prior_year, sociedades
    )
    print(sql_mermas_ratio)
    print(df_mermas_ratio[["sociedad", "nombre_sociedad", "costo_anterior", "costo_actual",
                            "mermas_anterior", "mermas_actual", "pct_anterior", "pct_actual"]]
          .to_string(index=False))

    chart_path_mermas_ratio = os.path.join(OUTPUT_DIR, "_chart_Mermas_ratio.png")
    build_chart_ratio(df_mermas_ratio, titulo_mermas_ratio, current_year, prior_year,
                      chart_path_mermas_ratio, col_cuenta="mermas")
    sections.append(
        build_section_mermas_ratio(df_mermas_ratio, chart_path_mermas_ratio, fecha_str,
                                    current_year, prior_year, raccts_mermas,
                                    titulo=titulo_mermas_ratio)
    )

    print("--- Descuentos y Bonificaciones (RACCT 000401%) ---")
    sql_desc, df_desc = fetch_descuentos(client, current_year, prior_year, SOCIEDADES)
    print(sql_desc)
    print(df_desc[["sociedad", "nombre_sociedad", "ingresos_anterior", "ingresos_actual",
                    "descuentos_anterior", "descuentos_actual", "pct_anterior", "pct_actual"]]
          .to_string(index=False))

    # Descuentos, primera forma: solo el importe de la cuenta (Plantilla A), reusando la misma
    # query -- misma pareja de variantes que Mermas, en el mismo orden (importe y luego razón).
    titulo_desc_importe = TITULOS_SECCION["Descuentos importe"]
    df_desc_importe = a_plantilla_importe(df_desc, "descuentos")
    print(f"--- {titulo_desc_importe} ---")
    print(df_desc_importe[["sociedad", "nombre_sociedad", "anterior", "actual", "diferencia",
                            "pct_variacion"]].to_string(index=False))

    chart_path_desc_importe = os.path.join(OUTPUT_DIR, "_chart_Descuentos_importe.png")
    build_chart(df_desc_importe, titulo_desc_importe, current_year, prior_year,
                chart_path_desc_importe)
    sections.append(
        build_section(titulo_desc_importe, ["000401% (clasificadas como descuento)"],
                      df_desc_importe, chart_path_desc_importe, fecha_str, current_year, prior_year)
    )

    chart_path_desc = os.path.join(OUTPUT_DIR, "_chart_Descuentos_y_Bonificaciones.png")
    titulo_desc_ratio = TITULOS_SECCION["Descuentos ratio"]
    build_chart_descuentos(df_desc, current_year, prior_year, chart_path_desc,
                           titulo=titulo_desc_ratio)
    sections.append(
        build_section_descuentos(df_desc, chart_path_desc, fecha_str, current_year, prior_year,
                                  titulo=titulo_desc_ratio)
    )

    # Variación de Precios: MISMO formato que el resto de cuentas (Plantilla A, año en curso vs.
    # año anterior), por decisión explícita del usuario (2026-08-17) de mantener las cuatro
    # cuentas con las mismas columnas. Se probó antes un desglose mensual porque el cierre anual
    # reclasifica esta cuenta y el año previo no es comparable; la evidencia sigue documentada en
    # config.py y por eso la sección lleva NOTA_PRECIOS al pie -- el formato es idéntico al de
    # las demás, pero quien lea el PDF necesita saber por qué salen tantos ±100%.
    # Usa el catálogo SOCIEDADES (no dm_company) y va al final del PDF.
    raccts_precios = CUENTAS["Variación de Precios"]
    print(f"--- Variación de Precios ({', '.join(raccts_precios)}) ---")
    sql_precios, df_precios = fetch_cuenta(
        client, raccts_precios, hist_years, current_year, prior_year, SOCIEDADES
    )
    print(sql_precios)
    print(df_precios[["sociedad", "nombre_sociedad", "anterior", "actual", "diferencia",
                      "pct_variacion"]].to_string(index=False))

    chart_path_precios = os.path.join(OUTPUT_DIR, "_chart_Variacion_de_Precios.png")
    build_chart(df_precios, "Variación de Precios", current_year, prior_year, chart_path_precios)
    sections.append(
        build_section("Variación de Precios", raccts_precios, df_precios,
                      chart_path_precios, fecha_str, current_year, prior_year,
                      nota=NOTA_PRECIOS.format(prior_year=prior_year))
    )

    output_path = os.path.join(OUTPUT_DIR, f"reporte_cuentas_proan_{hoy.isoformat()}.pdf")
    build_pdf(sections, output_path)
    print(f"\nPDF generado: {output_path}")


if __name__ == "__main__":
    main()
