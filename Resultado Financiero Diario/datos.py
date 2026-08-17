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

LIMITACIÓN DE FONDO DE LA COLUMNA `dif` (comprobado 2026-08-17, leer antes de "arreglar"
cualquier cosa aquí):

`dif` = -SUM(saldo) sobre TODAS las cuentas de la sociedad, y `balance + estado_resultados` es
esa misma suma, porque el CASE reparte cada cuenta en BAL o RES sin dejar ninguna fuera (el
`ELSE 'BAL'` absorbe todo lo demás). Como la balanza de comprobación de una sociedad suma cero
por partida doble, `dif` es 0.00 POR CONSTRUCCIÓN. Medido: máx |dif| = 0.0000 en las 20
sociedades de 2024 y las 19 de 2026, sin una sola excepción.

Conceptualmente la fórmula es la correcta (utilidad vía cuentas de resultados menos utilidad
vía cuentas de balance), pero con la balanza completa esas dos cifras son forzosamente iguales,
así que la columna no puede señalar un descuadre. Los descuadres que sí muestra ZF01 -- en la
tabla de referencia del PDF, Proteína Animal +425,040.00 y Proan Alimentos -529,200.00 al
13/12/2024 -- salen de cuentas NO asignadas a la estructura de balance/PyG PROA, que el árbol
deja fuera y aquí no tienen equivalente.

Para reproducirlos hace falta la asignación cuenta -> nodo de la estructura (tablas T011 /
FAGL_011 de SAP), y NO está replicada en BigQuery (comprobado: en el proyecto solo hay SKA1,
SKAT, SKB1 del catálogo de cuentas). O sea: con los datos disponibles hoy este descuadre no se
puede calcular; no es cuestión de corregir la query. Mientras tanto el PDF lleva una nota de
alcance (pdf._nota_alcance) para que finanzas no lea un 0.00 como "todo conciliado".

Corolario importante: `dif == 0` NO valida la clasificación BAL/RES. Cualquier partición de las
cuentas en dos grupos da cero. Si hay que validar la clasificación, hay que hacerlo contra el
árbol de ZF01 sociedad por sociedad, no con esta columna.
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
    -- Añadidos 2026-08-17: la query original solo filtraba el año. Hoy son redundantes (toda la
    -- tabla es 0L / 0 / 001, verificado), pero sin ellos cualquier ledger paralelo, registro de
    -- plan (RRCTY != '0') o versión distinta que llegue a replicarse se sumaría en silencio y
    -- duplicaría los importes sin que nada fallara. Mismos filtros que ya usa la query de
    -- "Reportes diarios contables".
    AND RLDNR_LedgerInGLAccounting = '0L'
    AND RRCTY_RecordType = '0'
    AND RVERS_Version = '001'
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
