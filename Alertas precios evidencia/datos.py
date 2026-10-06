"""Lecturas y escrituras en BigQuery.

Cada función hace una sola consulta y devuelve un DataFrame. No hay lógica de negocio aquí: solo traer datos.
"""
import datetime

import pandas as pd
from google.cloud import bigquery
from google.api_core.exceptions import NotFound

import config

_client = None


def cliente():
    global _client
    if _client is None:
        _client = bigquery.Client(project=config.PROJECT_ID)
    return _client


def _q(sql, params=()):
    df = cliente().query(sql, job_config=bigquery.QueryJobConfig(query_parameters=list(params))).to_dataframe()
    for col in df.columns:  # BigQuery devuelve NUMERIC como Decimal; se pasa a float para poder calcular
        if df[col].dtype == object and df[col].notna().any() and type(df[col].dropna().iloc[0]).__name__ == "Decimal":
            df[col] = df[col].astype(float)
    return df


def _filtro_carga(alias="c"):
    """En pruebas con FECHA_EJECUCION solo cuentan las facturas que ya habían llegado a esa hora."""
    if config.CORTE_CFDI is None:
        return "", []
    return (f" AND {alias}.UploadedAt <= @corte",
            [bigquery.ScalarQueryParameter("corte", "TIMESTAMP", config.CORTE_CFDI)])


# --- 1. Alertas -------------------------------------------------------------------------------------------------
def alertas_de_los_dias(fechas):
    """Alertas graves tal como se enviaron cada uno de esos días (tablas price_alerts_AAAAMMDD).

    Quita las líneas repetidas por el JOIN con bkpf (misma factura y posición).
    """
    partes = []
    for f in fechas:
        tabla = config.TABLA_ALERTAS_DIA.format(fecha=f.strftime("%Y%m%d"))
        try:
            cliente().get_table(tabla)
        except NotFound:  # ese día no se generó tabla (p. ej. domingo sin ejecución del DAG)
            continue
        partes.append(f"SELECT * EXCEPT(user_department, user_function) FROM `{tabla}`")
    if not partes:
        return pd.DataFrame()
    return _q(f"SELECT * FROM ({' UNION ALL '.join(partes)}) "
              "QUALIFY ROW_NUMBER() OVER (PARTITION BY billing_document, item_number ORDER BY user_name) = 1")


# --- 2. Control de envíos ---------------------------------------------------------------------------------------
def alertas_ya_enviadas(desde):
    sql = f"SELECT DISTINCT alerta_id FROM `{config.TABLA_ENVIADAS}` WHERE fecha_alerta >= @desde"
    try:
        return set(_q(sql, [bigquery.ScalarQueryParameter("desde", "DATE", desde)]).alerta_id)
    except NotFound:
        if config.DRY_RUN:  # en pruebas se puede trabajar sin la tabla: se considera que no se ha enviado nada
            print(f"[datos] AVISO: no existe {config.TABLA_ENVIADAS}; en modo prueba se asume que no hay envíos previos")
            return set()
        raise RuntimeError(f"No existe la tabla de control {config.TABLA_ENVIADAS}. Ejecuta crear_tablas.sql.")


def registrar_enviadas(filas):
    """Añade las alertas enviadas a la tabla de control (carga por lotes, no streaming)."""
    if not filas:
        return
    job = cliente().load_table_from_json(
        filas, config.TABLA_ENVIADAS,
        job_config=bigquery.LoadJobConfig(write_disposition="WRITE_APPEND"))
    job.result()


# --- 3. Facturas CFDI -------------------------------------------------------------------------------------------
_CAMPOS_CFDI = """UUID, UploadedAt, concepto_idx, ClaveProdServ, NoIdentificacion, Descripcion, Cantidad, ClaveUnidad,
    Unidad, ValorUnitario, Importe, Descuento_Concepto, IVA_Traslado_Tasa, Estatus, Serie, Folio, Fecha, FormaPago,
    MetodoPago, SubTotal, Total, Moneda, Exportacion, LugarExpedicion, NoCertificado, EmisorRfc, EmisorNombre,
    EmisorRegimen, ReceptorRfc, ReceptorNombre, ReceptorRegimen, ReceptorUsoCFDI, ReceptorDomicilioFiscal,
    FechaTimbrado, NoCertificadoSAT, InfoGlobal_Periodicidad"""


def cfdi_de_facturas(facturas, desde):
    """CFDI (todas sus líneas, última carga) de una lista de (sociedad, factura SAP, fecha).

    Cruce: RFC emisor de la sociedad + folio = últimos 7 dígitos de la factura SAP + fecha de emisión.
    """
    claves = [f"{config.RFC_SOCIEDAD[s]}|{int(f[-7:])}|{d}" for s, f, d in facturas if s in config.RFC_SOCIEDAD]
    if not claves:
        return pd.DataFrame()
    filtro, extra = _filtro_carga()
    return _q(f"""
        SELECT {_CAMPOS_CFDI} FROM `{config.TABLA_CFDI}` c
        WHERE c.UploadedAt >= TIMESTAMP(@desde) AND c.TipoDeComprobante = 'I'
          AND CONCAT(c.EmisorRfc, '|', CAST(SAFE_CAST(c.Folio AS INT64) AS STRING), '|', SUBSTR(c.Fecha, 1, 10))
              IN UNNEST(@claves){filtro}
        QUALIFY ROW_NUMBER() OVER (PARTITION BY UUID, concepto_idx ORDER BY UploadedAt DESC) = 1""",
              [bigquery.ArrayQueryParameter("claves", "STRING", claves),
               bigquery.ScalarQueryParameter("desde", "DATE", desde)] + extra)


# --- 4. Histórico de precios ------------------------------------------------------------------------------------
def historico(claves, desde, hasta, kilos_por_unidad):
    """Una fila por línea de factura SAP (no por factura: una factura puede mezclar precios).

    claves: lista de 'sociedad|material|unidad'. kilos_por_unidad: DataFrame material/sales_unit/kilo_unitario para
    pasar a kilos las líneas sin peso real.
    """
    h = _q(f"""
        SELECT company_code, material_number, sales_unit, billing_date, billing_document, item_number, customer_code,
               SUM(amount_mxn) AS importe, SUM(invoiced_quantity) AS cantidad,
               SUM(IF(catch_weight_meins = 'KG', catch_weight_menge, 0)) AS kg_cw
        FROM `{config.TABLA_FACTURAS_SAP}`
        WHERE billing_date BETWEEN @desde AND @hasta
          AND CONCAT(company_code, '|', material_number, '|', sales_unit) IN UNNEST(@claves)
          AND amount_mxn > 0 AND document_category = 'M'
          AND billing_document NOT LIKE '0070%' AND billing_document NOT LIKE '0071%'
        GROUP BY 1, 2, 3, 4, 5, 6, 7""",
           [bigquery.ScalarQueryParameter("desde", "DATE", desde),
            bigquery.ScalarQueryParameter("hasta", "DATE", hasta),
            bigquery.ArrayQueryParameter("claves", "STRING", claves)])
    if h.empty:
        return h
    h = h.merge(kilos_por_unidad, on=["material_number", "sales_unit"], how="left")
    h["kg"] = h.kg_cw.where(h.kg_cw > 0, h.cantidad.where(h.sales_unit == "KG", h.cantidad * h.kilo_unitario))
    h = h[h.kg > 0].copy()
    h["precio_kg"] = h.importe / h.kg
    h["billing_date"] = pd.to_datetime(h.billing_date)
    return h


# --- 5. Resto de líneas de las facturas con alerta (para la nota) -----------------------------------------------
def lineas_de_facturas(facturas):
    if not facturas:
        return pd.DataFrame(columns=["billing_document", "price_per_unit_mxn", "median_30d"])
    return _q(f"""
        SELECT billing_document, item_number, material_number, price_per_unit_mxn, median_30d
        FROM `{config.TABLA_PRECIOS}` WHERE billing_document IN UNNEST(@f)
        QUALIFY ROW_NUMBER() OVER (PARTITION BY billing_document, item_number ORDER BY usuario) = 1""",
              [bigquery.ArrayQueryParameter("f", "STRING", sorted(facturas))])


def hace(dias, desde=None):
    return (desde or config.HOY) - datetime.timedelta(days=dias)
