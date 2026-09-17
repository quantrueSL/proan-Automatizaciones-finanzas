"""Consultas a BigQuery y cálculos del Resumen Ejecutivo Mensual de ETC.

Cada función de este archivo se validó por separado contra el mockup real (agosto 2026,
ver mockup_resumen_mensual.html) antes de darse por buena -- las notas "Verificado:" en
cada docstring dicen contra qué cifra exacta del mockup se comparó. Esa verificación se
hizo con datos reales de BigQuery, no con datos inventados.
"""

import datetime

from google.cloud import bigquery
import pandas as pd

from config import (
    PROJECT_ID, TABLA_INGRESOS, TABLA_GASTOS, TABLA_ORIGEN_APLICACION, TABLA_DASHBOARD,
    TABLA_DASHBOARD2, UMBRAL_INGRESO_FLOTILLA, UMBRAL_INGRESO_UNIDAD, UMBRAL_INGRESO_RUTA,
    categoria_ingreso, CATEGORIA_INGRESO_ORDEN, TOP_N_GASTOS, MESES_PROMEDIO_DEPRECIACION,
    UMBRAL_DEPRECIACION_CERO, ORIGEN_LINEAS_DESTACADAS, APLICACION_LINEAS_DESTACADAS,
    MESES_SERIE_DESEMPENO, FIRESTORE_DATABASE_ID, FIRESTORE_LISTS_COLLECTION,
    RESUMEN_MENSUAL_ETC_LIST_ID,
)

MESES_ES = [
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
]


def nombre_mes(fecha, mayuscula_inicial=True):
    nombre = MESES_ES[fecha.month - 1]
    return nombre.capitalize() if mayuscula_inicial else nombre


def poper_de_fecha(fecha):
    """RYEAR/POPER de ETC es el número de mes con cero a la izquierda a 3 dígitos
    ('001'..'012'), igual que el resto de reportes SAP de este repo."""
    return f"{fecha.month:03d}"


def get_client():
    return bigquery.Client(project=PROJECT_ID)


def detectar_mes_cerrado(client):
    """El mes a reportar: el MES_CONTABLE máximo que sea estrictamente anterior al mes
    calendario en curso (nunca el mes actual, que siempre está a medio acumular -- se ve
    clarísimo en los datos reales: septiembre 2026 lleva $4.6M de ingreso al día 3, vs.
    ~$130-150M de un mes cerrado cualquiera). No se asume "mes anterior al actual" a
    ciegas -- se pregunta por el MES_CONTABLE real más reciente que cumpla la condición,
    así que si algún mes faltara del todo, esto retrocede automáticamente uno más.

    Verificado: para "hoy" 2026-09-03 devuelve 2026-08-01, el mismo mes que usa el mockup.
    """
    sql = f"""
    SELECT MAX(MES_CONTABLE) AS mes_cerrado
    FROM `{PROJECT_ID}.{TABLA_INGRESOS}`
    WHERE MES_CONTABLE < DATE_TRUNC(CURRENT_DATE(), MONTH)
    """
    df = client.query(sql).to_dataframe()
    mes = df.iloc[0]["mes_cerrado"]
    if pd.isna(mes):
        raise RuntimeError("No hay ningún mes cerrado con datos en rentabilidad_ETC_ingresos.")
    return mes if isinstance(mes, datetime.date) else mes.date()


def fetch_serie_desempeno(client, mes_cerrado, n_meses=MESES_SERIE_DESEMPENO):
    """Ingresos vs. gastos por mes, los últimos `n_meses` hasta mes_cerrado inclusive.
    Verificado: los 8 puntos de agosto 2026 hacia atrás (ene-ago) coinciden en forma con
    la polyline del mockup (pico de ingresos en junio, gastos bajando desde marzo)."""
    sql_ing = f"""
    SELECT MES_CONTABLE, SUM(ingreso_mes) AS ingreso
    FROM `{PROJECT_ID}.{TABLA_INGRESOS}`
    WHERE MES_CONTABLE <= @mes_cerrado
    GROUP BY MES_CONTABLE ORDER BY MES_CONTABLE DESC LIMIT @n
    """
    sql_gas = f"""
    SELECT MES_CONTABLE, SUM(gasto_mes) AS gasto
    FROM `{PROJECT_ID}.{TABLA_GASTOS}`
    WHERE MES_CONTABLE <= @mes_cerrado
    GROUP BY MES_CONTABLE ORDER BY MES_CONTABLE DESC LIMIT @n
    """
    job_config = bigquery.QueryJobConfig(query_parameters=[
        bigquery.ScalarQueryParameter("mes_cerrado", "DATE", mes_cerrado),
        bigquery.ScalarQueryParameter("n", "INT64", n_meses),
    ])
    df_ing = client.query(sql_ing, job_config=job_config).to_dataframe()
    df_gas = client.query(sql_gas, job_config=job_config).to_dataframe()
    df = pd.merge(df_ing, df_gas, on="MES_CONTABLE", how="outer").fillna(0.0)
    # BigQuery NUMERIC vuelve como Decimal en el DataFrame -- a float explícito, si no
    # las operaciones aritméticas de más abajo (graficos.py) truenan mezclando tipos.
    df["ingreso"] = df["ingreso"].astype(float)
    df["gasto"] = df["gasto"].astype(float)
    df["MES_CONTABLE"] = pd.to_datetime(df["MES_CONTABLE"])
    return df.sort_values("MES_CONTABLE").reset_index(drop=True)


def fetch_kpis(client, mes_cerrado, serie):
    """KPIs del header + fila de tarjetas. `serie` es la salida de fetch_serie_desempeno
    (se reutiliza para no volver a consultar el mes actual/anterior).

    Verificado contra agosto 2026: ingreso_total $143.2M, gasto_total $93.3M, utilidad
    $49.9M (34.9% margen), crecim. ingresos +7.0% vs jul, crecim. gastos +11.9% vs jul,
    margen jul 37.7% (calculado, no está impreso en el mockup pero 34.9-37.7=-2.8pp ~
    los "▼ 2.9 pp" del mockup, la diferencia de una centésima es solo redondeo)."""
    fila_actual = serie.iloc[-1]
    fila_anterior = serie.iloc[-2] if len(serie) >= 2 else None

    ingreso_total = float(fila_actual["ingreso"])
    gasto_total = float(fila_actual["gasto"])
    utilidad = ingreso_total - gasto_total
    margen = (utilidad / ingreso_total) if ingreso_total else float("nan")

    if fila_anterior is not None and fila_anterior["ingreso"]:
        ingreso_ant = float(fila_anterior["ingreso"])
        gasto_ant = float(fila_anterior["gasto"])
        utilidad_ant = ingreso_ant - gasto_ant
        margen_ant = (utilidad_ant / ingreso_ant) if ingreso_ant else float("nan")
        crecim_ingresos = (ingreso_total - ingreso_ant) / ingreso_ant
        crecim_gastos = (gasto_total - gasto_ant) / gasto_ant if gasto_ant else float("nan")
        delta_margen_pp = (margen - margen_ant) * 100
    else:
        crecim_ingresos = crecim_gastos = delta_margen_pp = float("nan")

    sql_ytd = f"""
    SELECT
      (SELECT SUM(ingreso_ytd) FROM `{PROJECT_ID}.{TABLA_INGRESOS}` WHERE MES_CONTABLE = @mes) AS ingreso_ytd,
      (SELECT SUM(gasto_ytd) FROM `{PROJECT_ID}.{TABLA_GASTOS}` WHERE MES_CONTABLE = @mes) AS gasto_ytd
    """
    job_config = bigquery.QueryJobConfig(query_parameters=[
        bigquery.ScalarQueryParameter("mes", "DATE", mes_cerrado),
    ])
    ytd = client.query(sql_ytd, job_config=job_config).to_dataframe().iloc[0]
    ingreso_ytd = float(ytd["ingreso_ytd"])
    gasto_ytd = float(ytd["gasto_ytd"])
    utilidad_ytd = ingreso_ytd - gasto_ytd
    margen_ytd = (utilidad_ytd / ingreso_ytd) if ingreso_ytd else float("nan")

    return {
        "ingreso_total": ingreso_total, "gasto_total": gasto_total,
        "utilidad": utilidad, "margen": margen,
        "ingreso_ytd": ingreso_ytd, "gasto_ytd": gasto_ytd,
        "utilidad_ytd": utilidad_ytd, "margen_ytd": margen_ytd,
        "crecim_ingresos": crecim_ingresos, "crecim_gastos": crecim_gastos,
        "delta_margen_pp": delta_margen_pp,
    }


def fetch_composicion_ingresos(client, mes_cerrado):
    """Ingreso del mes por categoría (donut), agrupado con config.categoria_ingreso().
    Verificado: agosto 2026 da 75.3/19.4/3.1/1.8/0.4% -- coincide al décimo con el mockup
    en las 5 categorías."""
    sql = f"""
    SELECT descripcion, es_venta_de_activos, SUM(ingreso_mes) AS total
    FROM `{PROJECT_ID}.{TABLA_INGRESOS}`
    WHERE MES_CONTABLE = @mes
    GROUP BY descripcion, es_venta_de_activos
    """
    job_config = bigquery.QueryJobConfig(query_parameters=[
        bigquery.ScalarQueryParameter("mes", "DATE", mes_cerrado),
    ])
    df = client.query(sql, job_config=job_config).to_dataframe()
    df["total"] = df["total"].astype(float)
    df["categoria"] = df.apply(
        lambda r: categoria_ingreso(r["descripcion"], r["es_venta_de_activos"]), axis=1
    )
    agrupado = df.groupby("categoria")["total"].sum()
    total_general = agrupado.sum()
    filas = []
    for categoria in CATEGORIA_INGRESO_ORDEN:
        monto = float(agrupado.get(categoria, 0.0))
        pct = (monto / total_general) if total_general else 0.0
        filas.append({"categoria": categoria, "monto": monto, "pct": pct})
    return filas, float(total_general)


def fetch_top_gastos(client, mes_cerrado, top_n=TOP_N_GASTOS):
    """Top N conceptos de gasto del mes + qué % del gasto total representan entre todos.
    Verificado: agosto 2026 da Diesel/Casetas/Sueldos y Salarios/Refacciones/Gastos No
    Deducibles en ese orden, con los mismos montos y % del mockup (38.6/16.7/11.9/10.3/6.1%,
    83.5% acumulado)."""
    sql = f"""
    SELECT descripcion, SUM(gasto_mes) AS total
    FROM `{PROJECT_ID}.{TABLA_GASTOS}`
    WHERE MES_CONTABLE = @mes
    GROUP BY descripcion
    ORDER BY total DESC
    """
    job_config = bigquery.QueryJobConfig(query_parameters=[
        bigquery.ScalarQueryParameter("mes", "DATE", mes_cerrado),
    ])
    df = client.query(sql, job_config=job_config).to_dataframe()
    df["total"] = df["total"].astype(float)
    total_general = df["total"].sum()
    top = df.head(top_n).copy()
    top["pct"] = top["total"] / total_general if total_general else 0.0
    pct_acumulado = top["total"].sum() / total_general if total_general else 0.0
    filas = [
        {"descripcion": r["descripcion"].title(), "monto": r["total"], "pct": r["pct"]}
        for _, r in top.iterrows()
    ]
    return filas, pct_acumulado


def fetch_origen_aplicacion(client, mes_cerrado):
    """Origen y Aplicación de Recursos del mes, con las líneas destacadas de config.py
    mostradas por nombre propio y el resto sumado en "Otros orígenes"/"Otros aplicación".
    Verificado: agosto 2026 da $102.2M en ambos lados (cuadran), con los mismos 4 renglones
    de origen ($49.9M/$25.0M/$22.7M/$4.6M) y 5 de aplicación ($13.9M/$24.8M/$21.9M/$21.5M/
    $20.1M) del mockup."""
    sql = f"""
    SELECT linea, linea_orden, origen_mes, aplicacion_mes
    FROM `{PROJECT_ID}.{TABLA_ORIGEN_APLICACION}`
    WHERE MES_CONTABLE = @mes
    ORDER BY linea_orden
    """
    job_config = bigquery.QueryJobConfig(query_parameters=[
        bigquery.ScalarQueryParameter("mes", "DATE", mes_cerrado),
    ])
    df = client.query(sql, job_config=job_config).to_dataframe()
    df["origen_mes"] = df["origen_mes"].astype(float)
    df["aplicacion_mes"] = df["aplicacion_mes"].astype(float)

    def _armar_columna(col, destacadas):
        con_movimiento = df[df[col] > 0]
        destacadas_df = con_movimiento[con_movimiento["linea"].isin(destacadas)]
        resto = con_movimiento[~con_movimiento["linea"].isin(destacadas)]
        filas = [
            {"nombre": r["linea"], "monto": r[col]}
            for _, r in destacadas_df.sort_values(col, ascending=False).iterrows()
        ]
        otros = float(resto[col].sum())
        if otros > 0:
            etiqueta = "Otros orígenes" if col == "origen_mes" else "Otros aplicación"
            filas.append({"nombre": etiqueta, "monto": otros})
        total = float(con_movimiento[col].sum())
        return filas, total

    origen, total_origen = _armar_columna("origen_mes", ORIGEN_LINEAS_DESTACADAS)
    aplicacion, total_aplicacion = _armar_columna("aplicacion_mes", APLICACION_LINEAS_DESTACADAS)
    return {
        "origen": origen, "total_origen": total_origen,
        "aplicacion": aplicacion, "total_aplicacion": total_aplicacion,
    }


def _mejor_peor_margen(df, col_ingreso, col_gasto, umbral_ingreso):
    """Filtra por umbral de materialidad, calcula margen, y devuelve (mejor, peor) como
    dicts {ingreso, gasto, margen} sobre las filas restantes de df (cada caller define sus
    propias columnas de nombre)."""
    df = df[df[col_ingreso] > umbral_ingreso].copy()
    if df.empty:
        return None, None
    df["margen"] = (df[col_ingreso] - df[col_gasto]) / df[col_ingreso]
    mejor = df.loc[df["margen"].idxmax()]
    peor = df.loc[df["margen"].idxmin()]
    return mejor, peor


def fetch_segmento_flotilla(client, mes_cerrado):
    """Mejor/peor margen del mes por FLOTILLA (excluye FLOTILLA nula), con el umbral de
    materialidad de config.UMBRAL_INGRESO_FLOTILLA.
    Verificado: agosto 2026 -> mejor "Aves + Tello SLP" 78.1% ($1.4M ingreso), peor
    "Construcción" 9.8% ($0.9M ingreso) -- coincide exacto con el mockup."""
    poper = poper_de_fecha(mes_cerrado)
    sql = f"""
    SELECT FLOTILLA, SUM(ingresos) AS ingreso, SUM(gastos) AS gasto
    FROM `{PROJECT_ID}.{TABLA_DASHBOARD}`
    WHERE POPER = @poper AND FLOTILLA IS NOT NULL
    GROUP BY FLOTILLA
    """
    job_config = bigquery.QueryJobConfig(query_parameters=[
        bigquery.ScalarQueryParameter("poper", "STRING", poper),
    ])
    df = client.query(sql, job_config=job_config).to_dataframe()
    df["ingreso"] = df["ingreso"].astype(float)
    df["gasto"] = df["gasto"].astype(float)
    mejor, peor = _mejor_peor_margen(df, "ingreso", "gasto", UMBRAL_INGRESO_FLOTILLA)
    if mejor is None:
        return None
    return {
        "mejor": {"nombre": mejor["FLOTILLA"], "ingreso": mejor["ingreso"], "margen": mejor["margen"]},
        "peor": {"nombre": peor["FLOTILLA"], "ingreso": peor["ingreso"], "margen": peor["margen"]},
    }


def fetch_segmento_unidad(client, mes_cerrado):
    """Mejor/peor margen del mes por unidad motriz individual (TIPO_ACTIVO='UNIDAD
    MOTRIZ'), agrupado por RFAREA (cada unidad física). El nombre mostrado combina
    Categoria_Principal (tipo de unidad, normalizado -- ej. "TRACTO" y "TRACTOR" caen
    ambos en "TRACTOR") con la FLOTILLA a la que está asignada ese mes.
    Verificado: agosto 2026 -> mejor RFAREA 1001200200 "Tractor · Acarreo Cerdos" 84.9%,
    peor RFAREA 1001200136 "Tractor · Foraneo Huevo" -82.9% -- coincide exacto (incluido
    el RFAREA) con el mockup."""
    poper = poper_de_fecha(mes_cerrado)
    sql = f"""
    SELECT RFAREA, Categoria_Principal, FLOTILLA, SUM(ingresos) AS ingreso, SUM(gastos) AS gasto
    FROM `{PROJECT_ID}.{TABLA_DASHBOARD}`
    WHERE POPER = @poper AND TIPO_ACTIVO = 'UNIDAD MOTRIZ' AND FLOTILLA IS NOT NULL
    GROUP BY RFAREA, Categoria_Principal, FLOTILLA
    """
    job_config = bigquery.QueryJobConfig(query_parameters=[
        bigquery.ScalarQueryParameter("poper", "STRING", poper),
    ])
    df = client.query(sql, job_config=job_config).to_dataframe()
    df["ingreso"] = df["ingreso"].astype(float)
    df["gasto"] = df["gasto"].astype(float)
    n_unidades = df["RFAREA"].nunique()  # antes del filtro de materialidad, ver docstring
    mejor, peor = _mejor_peor_margen(df, "ingreso", "gasto", UMBRAL_INGRESO_UNIDAD)
    if mejor is None:
        return None

    def _nombre(r):
        return f"{r['Categoria_Principal'].title()} · {r['FLOTILLA']}"

    return {
        "n_unidades": int(n_unidades),
        "mejor": {"nombre": _nombre(mejor), "rfarea": mejor["RFAREA"],
                  "ingreso": mejor["ingreso"], "margen": mejor["margen"]},
        "peor": {"nombre": _nombre(peor), "rfarea": peor["RFAREA"],
                 "ingreso": peor["ingreso"], "margen": peor["margen"]},
    }


def detectar_ultimo_mes_rutas(client):
    """rentabilidad_ETC_dashboard2 (fuente TORITE/TORROT) puede ir rezagada respecto al
    resto del reporte -- se detecta su propio último mes con datos en vez de asumir que
    coincide con mes_cerrado. Devuelve (mes_contable_str 'YYYYMM', poper, poper_nombre).
    Verificado: hoy (2026-09) devuelve '202607' / Julio 2026, igual que la nota del
    mockup ("* ... no se ha actualizado desde el 6 de julio de 2026")."""
    sql = f"""
    SELECT MES_CONTABLE, POPER, POPER_NOMBRE
    FROM `{PROJECT_ID}.{TABLA_DASHBOARD2}`
    WHERE MES_CONTABLE = (SELECT MAX(MES_CONTABLE) FROM `{PROJECT_ID}.{TABLA_DASHBOARD2}`)
    LIMIT 1
    """
    df = client.query(sql).to_dataframe()
    if df.empty:
        raise RuntimeError("rentabilidad_ETC_dashboard2 no tiene ningún mes con datos.")
    r = df.iloc[0]
    return r["MES_CONTABLE"], r["POPER"], r["POPER_NOMBRE"]


def fetch_segmento_ruta(client, mes_contable_rutas):
    """Mejor/peor margen del mes (de rutas, no necesariamente el mismo mes_cerrado del
    resto del reporte -- ver detectar_ultimo_mes_rutas) por ID_RUTA.
    Verificado: julio 2026 -> mejor Ruta 103 59.1% ($266K ingreso), peor Ruta 1863 -32.3%
    ($385K ingreso) -- coincide exacto con el mockup."""
    sql = f"""
    SELECT ID_RUTA, SUM(ingreso_ruta) AS ingreso, SUM(gasto_ruta) AS gasto
    FROM `{PROJECT_ID}.{TABLA_DASHBOARD2}`
    WHERE MES_CONTABLE = @mes
    GROUP BY ID_RUTA
    """
    job_config = bigquery.QueryJobConfig(query_parameters=[
        bigquery.ScalarQueryParameter("mes", "STRING", mes_contable_rutas),
    ])
    df = client.query(sql, job_config=job_config).to_dataframe()
    df["ingreso"] = df["ingreso"].astype(float)
    df["gasto"] = df["gasto"].astype(float)
    mejor, peor = _mejor_peor_margen(df, "ingreso", "gasto", UMBRAL_INGRESO_RUTA)
    if mejor is None:
        return None
    return {
        "mejor": {"nombre": f"Ruta {mejor['ID_RUTA']}", "ingreso": mejor["ingreso"], "margen": mejor["margen"]},
        "peor": {"nombre": f"Ruta {peor['ID_RUTA']}", "ingreso": peor["ingreso"], "margen": peor["margen"]},
    }


def fetch_pct_ingreso_con_ruta(client, mes_contable_rutas, mes_cerrado_del_mismo_calendario):
    """Qué % del ingreso total de la empresa (tabla rentabilidad_ETC_ingresos, mismo mes
    calendario que mes_contable_rutas) tiene ruta asignada en dashboard2. Sirve para la
    nota "solo ~28% del ingreso total tiene ruta asignada" -- el resto de las rutas de
    ETC simplemente no captura ID_RUTA para todos los viajes.
    Verificado: julio 2026 -> 28.3%, coincide con el "~28%" del mockup."""
    sql_ruta = f"""
    SELECT SUM(ingreso_ruta) AS total FROM `{PROJECT_ID}.{TABLA_DASHBOARD2}`
    WHERE MES_CONTABLE = @mes
    """
    sql_total = f"""
    SELECT SUM(ingreso_mes) AS total FROM `{PROJECT_ID}.{TABLA_INGRESOS}`
    WHERE MES_CONTABLE = @mes_cal
    """
    jc_ruta = bigquery.QueryJobConfig(query_parameters=[
        bigquery.ScalarQueryParameter("mes", "STRING", mes_contable_rutas),
    ])
    jc_total = bigquery.QueryJobConfig(query_parameters=[
        bigquery.ScalarQueryParameter("mes_cal", "DATE", mes_cerrado_del_mismo_calendario),
    ])
    con_ruta = float(client.query(sql_ruta, job_config=jc_ruta).to_dataframe().iloc[0]["total"])
    total = float(client.query(sql_total, job_config=jc_total).to_dataframe().iloc[0]["total"])
    return (con_ruta / total) if total else float("nan")


def fetch_advertencia_depreciacion(client, mes_cerrado):
    """Caveat de datos: desde mayo 2026 las cuentas de depreciación caen a $0 exacto
    (problema de origen en SAP). Compara el gasto de depreciación del mes cerrado contra
    el promedio de los MESES_PROMEDIO_DEPRECIACION meses anteriores; si el mes actual
    está en (casi) cero y el promedio anterior no lo estaba, devuelve un texto de
    advertencia para el Mensaje Clave. Si no aplica, devuelve None.

    Verificado: para agosto 2026 (mes actual $0, promedio abr-jul con datos reales de
    varios millones) SÍ dispara la advertencia -- consistente con el caveat documentado
    por el usuario."""
    sql = f"""
    SELECT MES_CONTABLE, SUM(gasto_mes) AS total
    FROM `{PROJECT_ID}.{TABLA_GASTOS}`
    WHERE descripcion LIKE 'DEPRECIACION%' AND MES_CONTABLE <= @mes
    GROUP BY MES_CONTABLE ORDER BY MES_CONTABLE DESC
    LIMIT @n
    """
    job_config = bigquery.QueryJobConfig(query_parameters=[
        bigquery.ScalarQueryParameter("mes", "DATE", mes_cerrado),
        bigquery.ScalarQueryParameter("n", "INT64", MESES_PROMEDIO_DEPRECIACION + 1),
    ])
    df = client.query(sql, job_config=job_config).to_dataframe()
    if df.empty:
        return None
    df["total"] = df["total"].astype(float)
    mes_actual = float(df.iloc[0]["total"])
    anteriores = df.iloc[1:]["total"]
    if anteriores.empty:
        return None
    promedio_anterior = float(anteriores.mean())
    if mes_actual < UMBRAL_DEPRECIACION_CERO and promedio_anterior >= UMBRAL_DEPRECIACION_CERO:
        return (
            f"Aviso de datos: el gasto por depreciación de {nombre_mes(mes_cerrado, False)} "
            f"aparece en $0 (promedio de los {MESES_PROMEDIO_DEPRECIACION} meses previos: "
            f"${promedio_anterior:,.0f}) — es un problema de origen en SAP, no de este "
            "reporte, y sigue inflando la utilidad calculada mientras no se corrija."
        )
    return None


# --- Destinatarios: lista administrada en Firestore -------------------------------------
# Mismo patrón que enviar_reporte.py de "Reportes diarios contables" / "Resultado
# Financiero Diario" / "Resultado Financiero Mensual" -- duplicado a propósito (cada
# carpeta es autónoma para su propio build de Docker, ver README del repo).

def get_mailing_list(list_id=RESUMEN_MENSUAL_ETC_LIST_ID):
    try:
        from google.cloud import firestore

        client = firestore.Client(project=PROJECT_ID, database=FIRESTORE_DATABASE_ID)
        snapshot = client.collection(FIRESTORE_LISTS_COLLECTION).document(list_id).get()
    except Exception as exc:
        print(f"[recipients] ADVERTENCIA: no se pudo leer Firestore "
              f"({FIRESTORE_DATABASE_ID}/{FIRESTORE_LISTS_COLLECTION}/{list_id}): {exc}")
        return []

    if not snapshot.exists:
        print(f"[recipients] ADVERTENCIA: no existe el documento "
              f"{FIRESTORE_LISTS_COLLECTION}/{list_id} en la base {FIRESTORE_DATABASE_ID}")
        return []

    data = snapshot.to_dict() or {}
    if not data.get("enabled", True):
        print(f"[recipients] ADVERTENCIA: la lista {list_id} está deshabilitada (enabled=false)")
        return []

    emails = data.get("emails")
    if not isinstance(emails, list):
        print(f"[recipients] ADVERTENCIA: el campo emails de {list_id} no es un array")
        return []

    recipients, seen = [], set()
    for raw in emails:
        email = str(raw or "").strip()
        key = email.lower()
        if email and key not in seen:
            seen.add(key)
            recipients.append(email)
    if not recipients:
        print(f"[recipients] ADVERTENCIA: la lista {list_id} no tiene ningún correo válido")
    return recipients
