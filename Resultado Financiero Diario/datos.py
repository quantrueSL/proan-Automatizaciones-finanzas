"""Consulta a BigQuery para el cuadre "Resultado Financiero diario" por sociedad.

Query tal cual la validó el usuario (ver briefing 2026-08-07) -- NO se rederiva la lógica
de clasificación BAL/RES aquí, solo se parametriza el año fiscal dinámicamente (año de hoy,
en vez de hardcodear '2026') y se envuelve en una función para poder reutilizarla desde
generar_reporte.py.

Nota de signo (IMPORTANTE, sin resolver del todo -- ver briefing 2026-08-07 y mensaje de
generar_reporte.py): el "-" delante de cada ROUND(...) es el que trae la query del usuario
tal cual se recibió. build_query() lo respeta sin tocarlo. fetch_resultado_financiero()
además devuelve las columnas *_raw (sin negar) para que generar_reporte.py pueda mostrar
ambas versiones y el usuario decida con el análisis de signo incluido en este mismo cambio.
"""

from google.cloud import bigquery


def build_query(anio: str) -> str:
    """anio: año fiscal como string (ej. "2026"). Debe ser el año en curso -- lo calcula
    el caller (ver generar_reporte.py), esta función no asume ningún año por defecto."""
    return f"""
DECLARE v_anio STRING DEFAULT '{anio}';

WITH base AS (
  SELECT
    RBUKRS_CompanyCode AS sociedad,
    CASE
      WHEN RBUKRS_CompanyCode = 'SCO1'
           AND SUBSTR(RACCT_AccountNumber, 5, 1) IN ('4','5','6','7','8') THEN 'RES'
      WHEN RBUKRS_CompanyCode = 'SCO1' THEN 'BAL'
      WHEN REGEXP_CONTAINS(RACCT_AccountNumber, r'^[0-9]{{10}}$')
           AND SUBSTR(RACCT_AccountNumber, 4, 1) IN ('4','5') THEN 'RES'
      ELSE 'BAL'
    END AS grupo,
    HSLVT_BalanceCarriedForwardLocalCurrency
      + HSL01_TotalLocalCurrency01 + HSL02_TotalLocalCurrency02
      + HSL03_TotalLocalCurrency03 + HSL04_TotalLocalCurrency04
      + HSL05_TotalLocalCurrency05 + HSL06_TotalLocalCurrency06
      + HSL07_TotalLocalCurrency07 + HSL08_TotalLocalCurrency08
      + HSL09_TotalLocalCurrency09 + HSL10_TotalLocalCurrency10
      + HSL11_TotalLocalCurrency11 + HSL12_TotalLocalCurrency12
      + HSL13_TotalLocalCurrency13 + HSL14_TotalLocalCurrency14
      + HSL15_TotalLocalCurrency15 + HSL16_TotalLocalCurrency16 AS saldo
  FROM `proan-quantrue.D30_INTEGRATION.sap_faglflext`
  WHERE CAST(RYEAR_FiscalYear AS STRING) = v_anio
)
SELECT
  sociedad,
  -ROUND(SUM(IF(grupo = 'BAL', saldo, 0)), 2) AS balance,
  -ROUND(SUM(IF(grupo = 'RES', saldo, 0)), 2) AS estado_resultados,
  -ROUND(SUM(saldo), 2)                        AS dif,
  ROUND(SUM(IF(grupo = 'BAL', saldo, 0)), 2)   AS balance_raw,
  ROUND(SUM(IF(grupo = 'RES', saldo, 0)), 2)   AS estado_resultados_raw
FROM base
GROUP BY sociedad
ORDER BY sociedad
"""


def fetch_resultado_financiero(client: bigquery.Client, anio: str, sociedades: dict):
    """Devuelve (sql, df). df trae: sociedad, nombre_sociedad, balance, estado_resultados,
    dif (con el signo de la query del usuario) + balance_raw/estado_resultados_raw (sin
    negar, para el análisis de signo -- ver nota arriba).

    sociedades: catálogo RBUKRS -> nombre comercial (config.SOCIEDADES). Un código sin
    entrada en el catálogo se muestra tal cual (fallback), no se descarta ni se rompe."""
    sql = build_query(anio)
    df = client.query(sql).to_dataframe()
    for col in ("balance", "estado_resultados", "dif", "balance_raw", "estado_resultados_raw"):
        df[col] = df[col].astype(float)
    df["nombre_sociedad"] = df["sociedad"].map(sociedades).fillna(df["sociedad"])
    return sql, df
