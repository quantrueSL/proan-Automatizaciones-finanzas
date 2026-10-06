"""Lógica de negocio: de líneas de factura con alerta a alertas agrupadas, y cuáles se envían hoy.

No consulta BigQuery ni dibuja nada: recibe DataFrames y devuelve DataFrames.
"""
import datetime
import hashlib

import numpy as np
import pandas as pd

import config
from formato import limpia, nz, titulo


def preparar_lineas(a):
    """Añade a cada línea las columnas que se usan para agrupar."""
    a = a.copy()
    for col in ["customer_name", "product_description", "company_name"]:
        a[col] = a[col].map(limpia)
    a["fecha"] = pd.to_datetime(a.creation_dt)
    ratio = a.price_per_unit_mxn / a.median_30d
    # Falsos positivos: ventas de CCP comparadas con el precio interno al que Panovo le vende (mediana con IQR 0)
    a["falsa"] = (a.company_code == "CCP") & (a.IQR == 0) & ((ratio < .5) | (ratio > 2))
    a["publico"] = a.customer_name.str.upper().str.startswith("PUBLICO EN GENERAL")
    a["cliente_clave"] = np.where(a.publico, "PUBLICO", a.customer_code)
    a["banda"] = a.price_per_unit_mxn.round(1)
    a["material"] = a.material_number.str.lstrip("0")
    a["nombre_material"] = a.product_description.str.split(" - ", n=1).str[-1]
    # Episodio masivo: el mismo día, mismo material y precio en muchos clientes -> una sola alerta
    episodio = ["fecha", "company_code", "material_number", "sales_unit", "banda"]
    n_cli = a[~a.falsa].groupby(episodio).customer_code.transform("nunique")
    a["masivo"] = False
    a.loc[n_cli.index, "masivo"] = n_cli >= config.CLIENTES_EPISODIO
    a.loc[a.masivo, "cliente_clave"] = "VARIOS"
    clave = ["fecha", "company_code", "material_number", "sales_unit", "cliente_clave", "banda"]
    a["alerta_id"] = a[clave].astype(str).agg("|".join, axis=1).map(
        lambda s: hashlib.md5(s.encode()).hexdigest()[:16])
    return a


def _resumen(g):
    kg = g.real_weight.sum()
    return pd.Series({
        "fecha": g.fecha.iloc[0], "sociedad": g.company_code.iloc[0],
        "nombre_sociedad": titulo(g.company_name.iloc[0]),
        "cliente": (f"{g.customer_code.nunique()} clientes" if g.masivo.iloc[0] else
                    "Público en general" if g.publico.iloc[0] else titulo(g.customer_name.iloc[0])),
        "publico": bool(g.publico.iloc[0]), "masivo": bool(g.masivo.iloc[0]),
        "clientes": sorted(g.customer_code.unique()), "n_clientes": g.customer_code.nunique(),
        "material": g.material.iloc[0], "material_number": g.material_number.iloc[0], "nombre_material": titulo(g.nombre_material.iloc[0], frase=True),
        "unidad": g.sales_unit.iloc[0], "ops": len(g), "facturas": sorted(g.billing_document.unique()),
        "lineas": set(g.billing_document + "|" + g.item_number),
        "kg": kg, "importe": g.amount_mxn.sum(),
        "precio": g.amount_mxn.sum() / kg if kg > 0 else g.price_per_unit_mxn.mean(),
        "esperado": g.median_30d.iloc[0], "dif": g.amount_difference_mxn.sum(),
        "oficina": g.sales_office.iloc[0], "falsa": bool(g.falsa.iloc[0]),
    })


def agrupar(lineas):
    """Una fila por alerta. Devuelve solo las reales (sin falsos positivos), con su posición por impacto en el día."""
    if lineas.empty:
        return pd.DataFrame()
    g = lineas.groupby("alerta_id").apply(_resumen, include_groups=False).reset_index()
    g = g[~g.falsa].copy()
    g["impacto"] = g.dif.abs()
    g["puesto_dia"] = g.groupby("fecha").impacto.rank(ascending=False, method="first").astype(int)
    return g


def facturas_de(alerta, lineas):
    """Facturas SAP de una alerta, de mayor a menor impacto, con lo que aporta cada una."""
    l = lineas[lineas.alerta_id == alerta.alerta_id]
    f = (l.groupby("billing_document")
         .agg(posiciones=("item_number", "count"), kg=("real_weight", "sum"), dif=("amount_difference_mxn", "sum"),
              cliente=("customer_code", "first"), usuario=("usuario", "first"), nombre_usuario=("user_name", "first"))
         .reset_index())
    return f.reindex(f.dif.abs().sort_values(ascending=False).index).reset_index(drop=True)


def cfdi_de_factura(cfdi, sociedad, factura):
    """Líneas del CFDI de una factura SAP (o None si aún no se ha cargado)."""
    if cfdi is None or cfdi.empty:
        return None
    rfc = config.RFC_SOCIEDAD.get(sociedad)
    cf = cfdi[(cfdi.EmisorRfc == rfc) & (cfdi.Folio.astype(str).str.lstrip("0") == str(int(factura[-7:])))]
    return cf.sort_values("concepto_idx") if len(cf) else None


def clasificar(alertas, lineas, cfdi, enviadas):
    """Estado de cada alerta pendiente: 'lista', 'caducada' o 'esperando'. Quita las ya enviadas."""
    pend = alertas[(alertas.puesto_dia <= config.TOP_POR_DIA) & ~alertas.alerta_id.isin(enviadas)].copy()
    if pend.empty:
        pend["estado"] = []
        return pend
    pend["con_factura"] = [any(cfdi_de_factura(cfdi, r.sociedad, f) is not None for f in r.facturas)
                           for r in pend.itertuples()]
    limite = pd.Timestamp(config.HOY - datetime.timedelta(days=config.PLAZO_DIAS))
    pend["estado"] = np.where(pend.con_factura, "lista", np.where(pend.fecha <= limite, "caducada", "esperando"))
    return pend


def seleccionar(pend):
    """Las que salen hoy: primero las más antiguas (para que ninguna se quede atrás), y dentro de cada día por impacto.

    Si superan el tope por correo, las que no entran se quedan pendientes para mañana.
    """
    sale = pend[pend.estado.isin(["lista", "caducada"])].sort_values(["fecha", "impacto"], ascending=[True, False])
    return sale.head(config.MAX_ALERTAS_CORREO).reset_index(drop=True)


# --- Qué factura se enseña ---------------------------------------------------------------------------------------
def factura_principal(alerta, lineas, cfdi):
    """(CFDI, factura SAP) de la factura de mayor impacto que ya esté cargada; si ninguna lo está, (None, la mayor)."""
    facturas = facturas_de(alerta, lineas).billing_document
    for f in facturas:
        cf = cfdi_de_factura(cfdi, alerta.sociedad, f)
        if cf is not None:
            return cf, f
    return None, facturas.iloc[0]


def es_global(cf):
    """Factura global de mostrador: a Público en general y agrupando tickets (el producto no viene desglosado)."""
    return cf.ReceptorRfc.iloc[0] == config.RFC_PUBLICO and nz(cf.InfoGlobal_Periodicidad.iloc[0], None) is not None


def candidatas_referencia(alerta, hist):
    """Ventas recientes del mismo producto cerca del precio esperado, primero de otros clientes y las más nuevas."""
    desde = alerta.fecha - pd.Timedelta(days=config.DIAS_REFERENCIA)
    h = hist[(hist.company_code == alerta.sociedad) & (hist.material_number.str.lstrip("0") == alerta.material)
             & (hist.sales_unit == alerta.unidad) & (hist.billing_date < alerta.fecha)
             & (hist.billing_date >= desde)
             & ((hist.precio_kg / alerta.esperado - 1).abs() <= config.TOLERANCIA_REFERENCIA)].copy()
    h["otro_cliente"] = ~h.customer_code.isin(alerta.clientes)
    h = h.sort_values(["otro_cliente", "billing_date"], ascending=[False, False])
    return h.drop_duplicates("billing_document").head(30)


def elegir_referencia(alerta, candidatas, cfdi_ref):
    """(CFDI, fila del histórico) de la primera candidata válida como "factura a precio normal".

    Válida = su CFDI está cargado, el producto aparece en su propia línea y no es una venta a otra empresa del grupo.
    """
    for r in candidatas.itertuples():
        cf = cfdi_de_factura(cfdi_ref, alerta.sociedad, r.billing_document)
        if (cf is not None and (cf.NoIdentificacion.astype(str).str.lstrip("0") == alerta.material).any()
                and cf.ReceptorRfc.iloc[0] not in config.RFC_GRUPO):
            return cf, r
    return None, None


def lineas_sap(alerta, lineas, factura, cf_ref):
    """Líneas del producto en la factura SAP con las columnas de un concepto de CFDI (para facturas globales)."""
    l = lineas[(lineas.billing_document == factura) & (lineas.alerta_id == alerta.alerta_id)].sort_values("item_number")
    clave = "-"
    if cf_ref is not None:
        m = cf_ref[cf_ref.NoIdentificacion.astype(str).str.lstrip("0") == alerta.material]
        clave = m.ClaveProdServ.iloc[0] if len(m) else "-"
    return pd.DataFrame({
        "concepto_idx": range(len(l)), "ClaveProdServ": clave, "NoIdentificacion": alerta.material,
        "Descripcion": [f"{alerta.nombre_material.upper()} (pos. {int(x)})" for x in l.item_number],
        "Cantidad": l.real_weight.values, "ClaveUnidad": "KGM", "ValorUnitario": l.price_per_unit_mxn.values,
        "Importe": l.amount_mxn.values, "IVA_Traslado_Tasa": float("nan"), "Descuento_Concepto": 0.0})


def nota_factura(alerta, factura, lineas_fact):
    """Cuántos productos de la factura están por debajo del precio normal (más de un 5 % bajo su mediana)."""
    lin = lineas_fact[lineas_fact.billing_document == factura]
    if lin.empty or alerta.dif >= 0:
        return ""
    debajo = int((lin.price_per_unit_mxn < lin.median_30d * .95).sum())
    if debajo == len(lin):
        return "Todos los productos de esta factura están por debajo del precio normal."
    if debajo > 1:
        return f"{debajo} de los {len(lin)} productos de esta factura están por debajo del precio normal."
    return ""
