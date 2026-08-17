"""Consulta a BigQuery — misma fórmula validada por el usuario para Gastos no Deducibles,
generalizada a cualquier cuenta contable (una o varias RACCT) y rango de años."""

from google.cloud import bigquery
import pandas as pd

from config import (
    TABLE_FQN, LEDGER, RECORD_TYPE, VERSION, UMBRAL_MATERIALIDAD_MXN, RACCT_PREFIX_DESCUENTOS,
    RACCT_PREFIX_COSTOS,
)

_HSL_COLS = ["HSLVT_BalanceCarriedForwardLocalCurrency"] + [
    f"HSL{str(i).zfill(2)}_TotalLocalCurrency{str(i).zfill(2)}" for i in range(1, 17)
]
_HSL_SUM_EXPR = " + ".join(_HSL_COLS)


def build_query(raccts, years, solo_debe=False):
    """Misma estructura que el query de referencia del usuario (SUM CASE WHEN por año),
    generalizada a N cuentas y N años.

    solo_debe: si True, agrega `AND DRCRK_DebitCreditIndicator = 'S'` -- filtra solo los
    movimientos de Debe (Soll), excluyendo Haber (H). Es una excepción puntual a la fórmula
    neta de siempre: se descubrió con datos reales de Mermas (0005010628) que esa cuenta
    recibe reclasificaciones/correcciones en Haber que casi cancelan el Debe original (ej.
    Proteína Animal 2025: Debe $274,816,762 vs. Haber -$274,759,261 -> neto solo $57,501;
    en DBC/HEGP/PAL/SAP el Debe y el Haber son EXACTAMENTE iguales -> neto $0, aunque hubo
    varios millones de mermas reales). El proceso manual de referencia (FS10N, "sumo las
    columnas del Debe") nunca resta el Haber -- por eso el reporte automático neto y el
    manual daban números completamente distintos, no por redondeo. No se aplica a las demás
    cuentas (Gastos no Deducibles, Variación de Precios): esas sí se validaron con la
    fórmula neta contra Excel/árbol de SAP, cambiarles esto rompería esa validación."""
    year_cases = ",\n".join(
        f"  SUM(CASE WHEN RYEAR_FiscalYear = {y} THEN {_HSL_SUM_EXPR} ELSE 0 END) AS total_{y}"
        for y in years
    )
    raccts_list = ", ".join(f"'{r}'" for r in raccts)
    years_list = ", ".join(str(y) for y in years)
    filtro_debe = "\n  AND DRCRK_DebitCreditIndicator = 'S'" if solo_debe else ""
    return f"""
SELECT
  RBUKRS_CompanyCode AS sociedad,
{year_cases}
FROM {TABLE_FQN}
WHERE RACCT_AccountNumber IN ({raccts_list})
  AND RYEAR_FiscalYear IN ({years_list})
  AND RLDNR_LedgerInGLAccounting = '{LEDGER}'
  AND RRCTY_RecordType = '{RECORD_TYPE}'
  AND RVERS_Version = '{VERSION}'{filtro_debe}
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


def fetch_cuenta(client: bigquery.Client, raccts, years, current_year, prior_year, sociedades,
                  solo_debe=False):
    """Ejecuta la consulta y devuelve un DataFrame con: sociedad, nombre_sociedad,
    total_<year> por cada año pedido, diferencia y % variación (actual vs anterior).

    solo_debe: ver build_query -- excepción puntual para Mermas."""
    sql = build_query(raccts, years, solo_debe=solo_debe)
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


def build_query_descuentos(years):
    """A diferencia de build_query, no pivotea por año en SQL: se necesita el neto por
    (sociedad, cuenta, año) para poder clasificar cada CUENTA como Ingreso o Descuento
    según el signo de su propio saldo neto (ver fetch_descuentos)."""
    years_list = ", ".join(str(y) for y in years)
    return f"""
SELECT
  RBUKRS_CompanyCode AS sociedad,
  RACCT_AccountNumber AS cuenta,
  RYEAR_FiscalYear AS anio,
  SUM({_HSL_SUM_EXPR}) AS neto
FROM {TABLE_FQN}
WHERE RACCT_AccountNumber LIKE '{RACCT_PREFIX_DESCUENTOS}%'
  AND RYEAR_FiscalYear IN ({years_list})
  AND RLDNR_LedgerInGLAccounting = '{LEDGER}'
  AND RRCTY_RecordType = '{RECORD_TYPE}'
  AND RVERS_Version = '{VERSION}'
GROUP BY sociedad, cuenta, anio
ORDER BY sociedad, cuenta, anio
"""


def fetch_descuentos(client: bigquery.Client, current_year, prior_year, sociedades):
    """Ejecuta la consulta a nivel (sociedad, cuenta, año), clasifica cada cuenta como
    Ingreso o Descuento según el signo de su neto agregado, y devuelve un DataFrame con
    ingresos/descuentos/% por sociedad para el año actual y el anterior.

    Clasificación: neto < 0 -> Ingreso (se reporta en positivo, ×-1); neto > 0 -> Descuento
    (se reporta tal cual). Se evalúa sobre el neto YA agregado por cuenta, no fila por fila,
    porque una misma cuenta puede tener movimientos de ambos signos y lo que importa es su neto.
    """
    years = [prior_year, current_year]
    sql = build_query_descuentos(years)
    df_cuentas = client.query(sql).to_dataframe()
    df_cuentas["neto"] = df_cuentas["neto"].astype(float)

    df_cuentas["ingreso"] = df_cuentas["neto"].clip(upper=0) * -1
    df_cuentas["descuento"] = df_cuentas["neto"].clip(lower=0)

    agg = df_cuentas.groupby(["sociedad", "anio"], as_index=False)[["ingreso", "descuento"]].sum()
    wide = agg.pivot(index="sociedad", columns="anio", values=["ingreso", "descuento"])
    wide.columns = [f"{metric}_{int(anio)}" for metric, anio in wide.columns]
    wide = wide.reset_index().fillna(0.0)

    for col in (f"ingreso_{current_year}", f"ingreso_{prior_year}",
                f"descuento_{current_year}", f"descuento_{prior_year}"):
        if col not in wide.columns:
            wide[col] = 0.0

    wide["nombre_sociedad"] = wide["sociedad"].map(sociedades).fillna(wide["sociedad"])
    wide["ingresos_actual"] = wide[f"ingreso_{current_year}"]
    wide["ingresos_anterior"] = wide[f"ingreso_{prior_year}"]
    wide["descuentos_actual"] = wide[f"descuento_{current_year}"]
    wide["descuentos_anterior"] = wide[f"descuento_{prior_year}"]

    # Mismo criterio de materialidad que fetch_cuenta: fuera si ningún monto (ingreso o
    # descuento, en ninguno de los dos años) supera el umbral.
    wide = wide[
        (wide["ingresos_actual"].abs() >= UMBRAL_MATERIALIDAD_MXN)
        | (wide["descuentos_actual"].abs() >= UMBRAL_MATERIALIDAD_MXN)
        | (wide["ingresos_anterior"].abs() >= UMBRAL_MATERIALIDAD_MXN)
        | (wide["descuentos_anterior"].abs() >= UMBRAL_MATERIALIDAD_MXN)
    ].reset_index(drop=True)

    wide["pct_actual"] = wide.apply(
        lambda r: (r["descuentos_actual"] / r["ingresos_actual"])
        if abs(r["ingresos_actual"]) >= UMBRAL_MATERIALIDAD_MXN else float("nan"),
        axis=1,
    )
    wide["pct_anterior"] = wide.apply(
        lambda r: (r["descuentos_anterior"] / r["ingresos_anterior"])
        if abs(r["ingresos_anterior"]) >= UMBRAL_MATERIALIDAD_MXN else float("nan"),
        axis=1,
    )
    return sql, wide


def a_plantilla_importe(df, col):
    """Convierte un DataFrame de razón (el de fetch_descuentos o fetch_mermas_ratio) al
    formato de Plantilla A -- actual/anterior/diferencia/pct_variacion -- para poder emitir
    la MISMA cuenta también como importe suelto, sin volver a consultar BigQuery.

    col: prefijo de las columnas a promover a actual/anterior ("descuentos", "mermas").

    El filtro de materialidad se re-aplica sobre la columna promovida, no sobre la que traía
    el df original: en la variante de razón basta con que la base sea material para que la
    sociedad aparezca (una sociedad con ingresos grandes y cero descuentos es informativa
    ahí, porque su % es 0.00%), pero en la variante de importe esa misma fila sería una fila
    de puros ceros. Mismo criterio que fetch_cuenta."""
    out = df[["sociedad", "nombre_sociedad"]].copy()
    out["actual"] = df[f"{col}_actual"]
    out["anterior"] = df[f"{col}_anterior"]
    out = out[(out["actual"].abs() >= UMBRAL_MATERIALIDAD_MXN) |
              (out["anterior"].abs() >= UMBRAL_MATERIALIDAD_MXN)].reset_index(drop=True)
    out["diferencia"] = out["actual"] - out["anterior"]
    out["pct_variacion"] = out.apply(
        lambda r: (r["diferencia"] / abs(r["anterior"]))
        if abs(r["anterior"]) >= UMBRAL_MATERIALIDAD_MXN else float("nan"),
        axis=1,
    )
    return out


def build_query_mermas_ratio(raccts_mermas, years):
    """Mermas y su base (Costo Total) en una sola pasada por sap_faglflext -- misma tabla y
    mismos filtros de ledger que el resto del reporte, sin tocar ninguna otra fuente.

    Dos sumas con criterios distintos a propósito, cada una como su proceso manual:
    - mermas: solo Debe (DRCRK='S'), igual que build_query(solo_debe=True) -- ver la nota
      larga ahí sobre por qué el neto no sirve para esta cuenta.
    - costo: neto, sobre las cuentas del grupo CTOS (prefijo RACCT_PREFIX_COSTOS). El nodo
      "Costos" del árbol de ZF01 es un saldo neto, no una suma de Debe.
    """
    raccts_list = ", ".join(f"'{r}'" for r in raccts_mermas)
    years_list = ", ".join(str(y) for y in years)
    n = len(RACCT_PREFIX_COSTOS)
    es_costo = f"SUBSTR(RACCT_AccountNumber, 1, {n}) = '{RACCT_PREFIX_COSTOS}'"
    return f"""
SELECT
  RBUKRS_CompanyCode AS sociedad,
  RYEAR_FiscalYear AS anio,
  ROUND(SUM(CASE WHEN RACCT_AccountNumber IN ({raccts_list})
                  AND DRCRK_DebitCreditIndicator = 'S'
                 THEN {_HSL_SUM_EXPR} ELSE 0 END), 2) AS mermas,
  ROUND(SUM(CASE WHEN {es_costo} THEN {_HSL_SUM_EXPR} ELSE 0 END), 2) AS costo
FROM {TABLE_FQN}
WHERE (RACCT_AccountNumber IN ({raccts_list}) OR {es_costo})
  AND RYEAR_FiscalYear IN ({years_list})
  AND RLDNR_LedgerInGLAccounting = '{LEDGER}'
  AND RRCTY_RecordType = '{RECORD_TYPE}'
  AND RVERS_Version = '{VERSION}'
GROUP BY sociedad, anio
ORDER BY sociedad, anio
"""


def fetch_mermas_ratio(client: bigquery.Client, raccts_mermas, current_year, prior_year,
                       sociedades):
    """Mermas contra Costo Total por sociedad, para el año actual y el anterior. Devuelve el
    mismo juego de columnas que fetch_descuentos pero con el par costo/mermas en vez de
    ingresos/descuentos, para que pdf.build_section_ratio y graficos.build_chart_ratio sirvan
    igual para las dos (ver TITULOS_SECCION en config.py)."""
    years = [prior_year, current_year]
    sql = build_query_mermas_ratio(raccts_mermas, years)
    df = client.query(sql).to_dataframe()
    df["mermas"] = df["mermas"].astype(float)
    df["costo"] = df["costo"].astype(float)

    wide = df.pivot(index="sociedad", columns="anio", values=["costo", "mermas"])
    wide.columns = [f"{metric}_{int(anio)}" for metric, anio in wide.columns]
    wide = wide.reset_index().fillna(0.0)

    for col in (f"costo_{current_year}", f"costo_{prior_year}",
                f"mermas_{current_year}", f"mermas_{prior_year}"):
        if col not in wide.columns:
            wide[col] = 0.0

    wide["nombre_sociedad"] = wide["sociedad"].map(sociedades).fillna(wide["sociedad"])
    wide["costo_actual"] = wide[f"costo_{current_year}"]
    wide["costo_anterior"] = wide[f"costo_{prior_year}"]
    wide["mermas_actual"] = wide[f"mermas_{current_year}"]
    wide["mermas_anterior"] = wide[f"mermas_{prior_year}"]

    wide = wide[
        (wide["costo_actual"].abs() >= UMBRAL_MATERIALIDAD_MXN)
        | (wide["mermas_actual"].abs() >= UMBRAL_MATERIALIDAD_MXN)
        | (wide["costo_anterior"].abs() >= UMBRAL_MATERIALIDAD_MXN)
        | (wide["mermas_anterior"].abs() >= UMBRAL_MATERIALIDAD_MXN)
    ].reset_index(drop=True)

    wide["pct_actual"] = wide.apply(
        lambda r: (r["mermas_actual"] / r["costo_actual"])
        if abs(r["costo_actual"]) >= UMBRAL_MATERIALIDAD_MXN else float("nan"),
        axis=1,
    )
    wide["pct_anterior"] = wide.apply(
        lambda r: (r["mermas_anterior"] / r["costo_anterior"])
        if abs(r["costo_anterior"]) >= UMBRAL_MATERIALIDAD_MXN else float("nan"),
        axis=1,
    )
    return sql, wide
