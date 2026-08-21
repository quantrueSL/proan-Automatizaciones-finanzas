"""Genera el PDF "Resultado Financiero diario" (cuadre por sociedad) a partir de
sap_faglflext_rt. Reporte SEPARADO del de "Reportes diarios contables" -- no lo toca, no
comparte PDF ni envío de correo (ver briefing 2026-08-07).

Uso:
    python generar_reporte.py

Requiere Application Default Credentials para BigQuery (gcloud auth application-default
login, o el puente ADC de CLOUDSDK_AUTH_ACCESS_TOKEN si el login interactivo no está
disponible -- ver memoria bq-auth-adc-bridge).

Estado: SOLO genera el PDF localmente para revisión. No envía correo (enviar_reporte.py no
existe todavía para esta carpeta) ni se despliega a Cloud Run -- pendiente de que el usuario
confirme destinatario y diseño del Job (ver config.py).
"""

import os
import datetime

from google.cloud import bigquery

from config import PROJECT_ID, OUTPUT_DIR, TOLERANCIA_DIF_MXN, SOCIEDADES
from datos import fetch_resultado_financiero
from graficos import build_chart_top5
from pdf import build_pdf


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    hoy = datetime.date.today()
    anio = str(hoy.year)
    fecha_str = hoy.strftime("%d/%m/%Y")
    hora_str = datetime.datetime.now().strftime("%H:%M")

    client = bigquery.Client(project=PROJECT_ID)
    sql, df = fetch_resultado_financiero(client, anio, SOCIEDADES)

    print(f"--- Resultado Financiero Diario ({fecha_str}, año fiscal {anio}) ---")
    print(sql)
    print()
    print("Con el signo de la query del usuario (columnas balance/estado_resultados/dif):")
    print(df[["sociedad", "nombre_sociedad", "balance", "estado_resultados", "dif"]].to_string(index=False))
    print()
    print("Mismos datos SIN negar (balance_raw/estado_resultados_raw), para el análisis de signo:")
    print(df[["sociedad", "balance_raw", "estado_resultados_raw"]].to_string(index=False))

    n_dif = int((df["dif"].abs() > TOLERANCIA_DIF_MXN).sum())
    print(f"\nSociedades con |Dif.| > {TOLERANCIA_DIF_MXN}: {n_dif}")
    if n_dif:
        print(df.loc[df["dif"].abs() > TOLERANCIA_DIF_MXN, ["sociedad", "dif"]].to_string(index=False))

    chart_path = os.path.join(OUTPUT_DIR, "_chart_resultado_financiero_top5.png")
    chart_ok = build_chart_top5(df, chart_path)
    print(f"\nGráfico top 5 por Resultado Financiero: {'generado' if chart_ok else 'omitido (sin datos que graficar)'}")

    output_path = os.path.join(OUTPUT_DIR, f"resultado_financiero_diario_{hoy.isoformat()}.pdf")
    build_pdf(df, fecha_str, hora_str, chart_path, chart_ok, output_path)
    print(f"\nPDF generado: {output_path}")


if __name__ == "__main__":
    main()
