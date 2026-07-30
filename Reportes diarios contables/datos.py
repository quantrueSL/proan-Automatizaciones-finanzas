"""Consulta a BigQuery — misma fórmula validada por el usuario para Gastos no Deducibles,
generalizada a cualquier cuenta contable (una o varias RACCT) y rango de años."""

from google.cloud import bigquery
import pandas as pd

from config import TABLE_FQN, LEDGER, RECORD_TYPE, VERSION, UMBRAL_MATERIALIDAD_MXN

_HSL_COLS = ["HSLVT_BalanceCarriedForwardLocalCurrency"] + [
    f"HSL{str(i).zfill(2)}_TotalLocalCurrency{str(i).zfill(2)}" for i in range(1, 17)
]
_HSL_SUM_EXPR = " + ".join(_HSL_COLS)


def build_query(raccts, years):
    """Misma estructura que el query de referencia del usuario (SUM CASE WHEN por año),
    generalizada a N cuentas y N años."""
    year_cases = ",\n".join(
        f"  SUM(CASE WHEN RYEAR_FiscalYear = {y} THEN {_HSL_SUM_EXPR} ELSE 0 END) AS total_{y}"
        for y in years
    )
    raccts_list = ", ".join(f"'{r}'" for r in raccts)
    years_list = ", ".join(str(y) for y in years)
    return f"""
SELECT
  RBUKRS_CompanyCode AS sociedad,
{year_cases}
FROM {TABLE_FQN}
WHERE RACCT_AccountNumber IN ({raccts_list})
  AND RYEAR_FiscalYear IN ({years_list})
  AND RLDNR_LedgerInGLAccounting = '{LEDGER}'
  AND RRCTY_RecordType = '{RECORD_TYPE}'
  AND RVERS_Version = '{VERSION}'
GROUP BY sociedad
ORDER BY sociedad
"""


def fetch_sociedades(client: bigquery.Client):
    """Mapeo RBUKRS -> nombre de sociedad desde el catálogo de sociedades SAP (T001).
    SKAT es el catálogo de cuentas contables, no de sociedades, así que no sirve para esto."""
    sql = "SELECT company_code, company_name FROM `proan-quantrue.D20_DIMENSION.dm_company`"
    df = client.query(sql).to_dataframe()
    # company_name viene en mayúsculas (y a veces truncado a 25 caracteres, campo BUTXT de SAP).
    return dict(zip(df["company_code"], df["company_name"].str.title()))


def fetch_cuenta(client: bigquery.Client, raccts, years, current_year, prior_year, sociedades):
    """Ejecuta la consulta y devuelve un DataFrame con: sociedad, nombre_sociedad,
    total_<year> por cada año pedido, diferencia y % variación (actual vs anterior)."""
    sql = build_query(raccts, years)
    df = client.query(sql).to_dataframe()

    for y in years:
        col = f"total_{y}"
        if col not in df.columns:
            df[col] = 0.0
        df[col] = df[col].astype(float)

    df["nombre_sociedad"] = df["sociedad"].map(sociedades).fillna(df["sociedad"])
    df["actual"] = df[f"total_{current_year}"]
    df["anterior"] = df[f"total_{prior_year}"]

    # Sin actividad material ni en el periodo actual ni en el anterior (por debajo del umbral
    # de materialidad, ej. residuos de redondeo de unos centavos): fuera del reporte de "hoy",
    # sin importar si tuvo movimiento en años más viejos.
    df = df[(df["actual"].abs() >= UMBRAL_MATERIALIDAD_MXN) |
            (df["anterior"].abs() >= UMBRAL_MATERIALIDAD_MXN)].reset_index(drop=True)
    df["diferencia"] = df["actual"] - df["anterior"]
    df["pct_variacion"] = df.apply(
        lambda r: (r["diferencia"] / abs(r["anterior"]))
        if abs(r["anterior"]) >= UMBRAL_MATERIALIDAD_MXN else float("nan"),
        axis=1,
    )
    return sql, df
