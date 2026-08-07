"""Consulta a BigQuery para "Resultado Financiero Mensual" -- Ingresos/Egresos/Resultado por
sociedad, para los ÚLTIMOS 2 MESES YA CERRADOS (corregido 2026-08-07: el mes en curso NO debe
aparecer -- antes se mostraba "mes en curso + mes anterior", el usuario aclaró que el mes en
curso no cuenta hasta que termine). Con "hoy" en agosto, eso son Junio y Julio -- Agosto queda
totalmente fuera de este reporte hasta que se convierta en "mes anterior" el 1 de septiembre.

Consecuencia importante de este cambio: como los DOS meses mostrados están cerrados, el
chequeo de estabilidad corre sobre AMBOS (antes solo corría sobre el mes anterior; el mes en
curso se marcaba PROVISIONAL a mano porque obviamente no tenía snapshot con qué compararlo).

Lógica SQL (el WITH/SELECT completo) sigue siendo la que dio el usuario originalmente -- NO se
rederivó nada de la clasificación de cuentas (dígito 4/5, plan PROA) ni del criterio de
estabilidad (tolerancia 0.5%, NULL como relleno en vez de 0). Cambios mecánicos aplicados:

1. **Bug de offset corregido**: `SUBSTR(table_name, 17)` -> `SUBSTR(table_name, 16)` (el
   prefijo "sap_faglflext2_" mide 15 caracteres, la fecha empieza en la posición 16). Avisado
   al usuario antes de aplicar, ver briefing 2026-08-07.
2. **Parametrización portada de BigQuery Scripting a Python** -- mismo patrón que el resto del
   proyecto, evita depender de scripts multi-sentencia en el cliente de Python.
3. **2 meses, ambos cerrados** (este cambio) -- ya no hay un "mes en curso" con estatus
   hardcodeado; los dos meses usan el mismo CASE de estabilidad real.
"""

import datetime

from google.cloud import bigquery

from config import SNAPSHOT_DIAS_OBJETIVO, SNAPSHOT_DIAS_LIMITE, UMBRAL_MATERIALIDAD_MXN

_HSL_UNPIVOT = """UNPIVOT(valor FOR periodo IN (
    HSL01_TotalLocalCurrency01 AS '1', HSL02_TotalLocalCurrency02 AS '2',
    HSL03_TotalLocalCurrency03 AS '3', HSL04_TotalLocalCurrency04 AS '4',
    HSL05_TotalLocalCurrency05 AS '5', HSL06_TotalLocalCurrency06 AS '6',
    HSL07_TotalLocalCurrency07 AS '7', HSL08_TotalLocalCurrency08 AS '8',
    HSL09_TotalLocalCurrency09 AS '9', HSL10_TotalLocalCurrency10 AS '10',
    HSL11_TotalLocalCurrency11 AS '11', HSL12_TotalLocalCurrency12 AS '12'
  ))"""


def get_snapshot_table(client: bigquery.Client, hoy: datetime.date):
    """Snapshot D10_POSTPROCESSING.sap_faglflext2_YYYYMMDD más cercano a "hace 14 días",
    buscando hasta 24 días atrás si el exacto no existe. Devuelve None si no hay ninguno en
    la ventana."""
    fecha_objetivo = (hoy - datetime.timedelta(days=SNAPSHOT_DIAS_OBJETIVO)).strftime("%Y%m%d")
    fecha_limite = (hoy - datetime.timedelta(days=SNAPSHOT_DIAS_LIMITE)).strftime("%Y%m%d")
    sql = f"""
SELECT MAX(table_name) AS snap
FROM `proan-quantrue.D10_POSTPROCESSING.INFORMATION_SCHEMA.TABLES`
WHERE table_name LIKE 'sap_faglflext2_%'
  AND SUBSTR(table_name, 16) <= '{fecha_objetivo}'
  AND SUBSTR(table_name, 16) >= '{fecha_limite}'
"""
    df = client.query(sql).to_dataframe()
    snap = df["snap"].iloc[0] if not df.empty else None
    return snap if snap else None


def build_query(anio1, per1, anio2, per2, snapshot_table):
    """anio1/per1 = mes más antiguo de los dos mostrados ("m1"), anio2/per2 = mes más
    reciente ("m2") -- AMBOS deben ser meses ya cerrados (lo decide el caller, ver
    fetch_resultado_mensual). Ambos llevan el mismo chequeo de estabilidad real contra el
    snapshot -- ya no hay un tercer mes "en curso" con estatus hardcodeado."""
    return f"""
WITH unpivot_vivo AS (
  SELECT
    RBUKRS_CompanyCode AS sociedad,
    CAST(RYEAR_FiscalYear AS STRING) AS anio,
    RACCT_AccountNumber AS cuenta,
    periodo,
    valor
  FROM `proan-quantrue.D30_INTEGRATION.sap_faglflext`
  {_HSL_UNPIVOT}
  WHERE REGEXP_CONTAINS(RACCT_AccountNumber, r'^[0-9]{{10}}$')
    AND SUBSTR(RACCT_AccountNumber, 4, 1) IN ('4','5')
),
agg_vivo AS (
  SELECT
    sociedad, anio, periodo,
    ROUND(SUM(IF(SUBSTR(cuenta,4,1)='4', -valor, 0)), 2) AS ingresos,
    ROUND(SUM(IF(SUBSTR(cuenta,4,1)='5',  valor, 0)), 2) AS egresos
  FROM unpivot_vivo
  GROUP BY sociedad, anio, periodo
),

unpivot_snap AS (
  SELECT
    RBUKRS_CompanyCode AS sociedad,
    CAST(RYEAR_FiscalYear AS STRING) AS anio,
    RACCT_AccountNumber AS cuenta,
    periodo,
    valor
  FROM `proan-quantrue.D10_POSTPROCESSING.{snapshot_table}`
  {_HSL_UNPIVOT}
  WHERE REGEXP_CONTAINS(RACCT_AccountNumber, r'^[0-9]{{10}}$')
    AND SUBSTR(RACCT_AccountNumber, 4, 1) IN ('4','5')
),
agg_snap AS (
  SELECT
    sociedad, anio, periodo,
    ROUND(SUM(IF(SUBSTR(cuenta,4,1)='4', -valor, 0)), 2) AS ingresos,
    ROUND(SUM(IF(SUBSTR(cuenta,4,1)='5',  valor, 0)), 2) AS egresos
  FROM unpivot_snap
  GROUP BY sociedad, anio, periodo
),

pivot AS (
  SELECT
    sociedad,
    MAX(IF(anio='{anio1}' AND periodo='{per1}', ingresos, NULL)) AS ing_m1,
    MAX(IF(anio='{anio1}' AND periodo='{per1}', egresos, NULL))  AS egr_m1,
    MAX(IF(anio='{anio2}' AND periodo='{per2}', ingresos, NULL)) AS ing_m2,
    MAX(IF(anio='{anio2}' AND periodo='{per2}', egresos, NULL))  AS egr_m2
  FROM agg_vivo
  GROUP BY sociedad
),
pivot_snap AS (
  SELECT
    sociedad,
    MAX(IF(anio='{anio1}' AND periodo='{per1}', ingresos, NULL)) AS ing_m1_snap,
    MAX(IF(anio='{anio1}' AND periodo='{per1}', egresos, NULL))  AS egr_m1_snap,
    MAX(IF(anio='{anio2}' AND periodo='{per2}', ingresos, NULL)) AS ing_m2_snap,
    MAX(IF(anio='{anio2}' AND periodo='{per2}', egresos, NULL))  AS egr_m2_snap
  FROM agg_snap
  GROUP BY sociedad
)

SELECT
  p.sociedad,
  p.ing_m1, p.egr_m1, ROUND(p.ing_m1 - p.egr_m1, 2) AS resultado_m1,
  CASE
    WHEN s.ing_m1_snap IS NULL THEN 'SIN_REFERENCIA'
    WHEN ABS(p.ing_m1 - s.ing_m1_snap) <= 0.005 * ABS(NULLIF(p.ing_m1,0))
     AND ABS(p.egr_m1 - s.egr_m1_snap) <= 0.005 * ABS(NULLIF(p.egr_m1,0))
    THEN 'ESTABLE' ELSE 'PROVISIONAL'
  END AS estatus_m1,

  p.ing_m2, p.egr_m2, ROUND(p.ing_m2 - p.egr_m2, 2) AS resultado_m2,
  CASE
    WHEN s.ing_m2_snap IS NULL THEN 'SIN_REFERENCIA'
    WHEN ABS(p.ing_m2 - s.ing_m2_snap) <= 0.005 * ABS(NULLIF(p.ing_m2,0))
     AND ABS(p.egr_m2 - s.egr_m2_snap) <= 0.005 * ABS(NULLIF(p.egr_m2,0))
    THEN 'ESTABLE' ELSE 'PROVISIONAL'
  END AS estatus_m2

FROM pivot p
LEFT JOIN pivot_snap s USING (sociedad)
ORDER BY sociedad
"""


def fetch_resultado_mensual(client: bigquery.Client, hoy: datetime.date, sociedades: dict):
    """Devuelve (sql, snapshot_table, df). df trae sociedad, nombre_sociedad, y para m1/m2:
    ing_*, egr_*, resultado_*, estatus_* (m1 = mes más antiguo de los dos, m2 = el más
    reciente -- AMBOS cerrados). mes1/mes2 son los primeros de cada mes calendario.

    "Mes más reciente cerrado" = mes anterior al mes en curso -- si hoy es agosto, eso es
    julio, NO agosto (agosto sigue abierto). Corregido 2026-08-07: antes esta función incluía
    el mes en curso, el usuario aclaró que no debe aparecer hasta que cierre."""
    mes_actual = hoy.replace(day=1)
    mes2 = (mes_actual - datetime.timedelta(days=1)).replace(day=1)  # último mes cerrado
    mes1 = (mes2 - datetime.timedelta(days=1)).replace(day=1)        # el anterior a ese

    snapshot_table = get_snapshot_table(client, hoy)
    if snapshot_table is None:
        raise RuntimeError(
            f"No se encontró ningún snapshot D10_POSTPROCESSING.sap_faglflext2_YYYYMMDD en la "
            f"ventana esperada (entre {SNAPSHOT_DIAS_LIMITE} y {SNAPSHOT_DIAS_OBJETIVO} días "
            f"atrás desde {hoy.isoformat()}). Sin snapshot no se puede calcular el chequeo de "
            f"estabilidad -- revisar si el proceso que genera snapshots diarios sigue corriendo."
        )

    sql = build_query(
        str(mes1.year), str(mes1.month),
        str(mes2.year), str(mes2.month),
        snapshot_table,
    )
    df = client.query(sql).to_dataframe()

    for col in ("ing_m1", "egr_m1", "resultado_m1", "ing_m2", "egr_m2", "resultado_m2"):
        df[col] = df[col].astype(float)

    df["nombre_sociedad"] = df["sociedad"].map(sociedades).fillna(df["sociedad"])
    df["mes1"], df["mes2"] = mes1, mes2

    # % Variación: Resultado m2 (más reciente) vs. Resultado m1 -- misma convención
    # "base ~0 -> +100%/-100%" que _pct_o_100 en "Reportes diarios contables/pdf.py".
    diferencia = df["resultado_m2"] - df["resultado_m1"]
    df["pct_variacion"] = diferencia / df["resultado_m1"].abs()
    base_cero = df["resultado_m1"].abs() < UMBRAL_MATERIALIDAD_MXN
    df.loc[base_cero, "pct_variacion"] = diferencia[base_cero].apply(lambda d: 1.0 if d >= 0 else -1.0)

    return sql, snapshot_table, df
