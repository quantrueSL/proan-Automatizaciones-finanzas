"""Genera el PDF de evidencia del día y un manifiesto (JSON) con las alertas que incluye.

Pasos:
  1. Lee las alertas graves enviadas en los últimos días (tablas price_alerts_AAAAMMDD).
  2. Las agrupa en alertas y se queda con las 10 de mayor impacto de cada día.
  3. Quita las que ya se enviaron con su evidencia (tabla de control).
  4. Busca su factura CFDI: si está, la alerta está lista; si pasaron PLAZO_DIAS sin factura, sale sin ella.
  5. Para las que salen hoy, trae el histórico de precios y una factura de referencia a precio normal.
  6. Genera el PDF y el manifiesto que usará enviar_evidencia.py.

Uso local:  python generar_evidencia.py
            FECHA_EJECUCION=2026-09-08 python generar_evidencia.py   (como si fuera ese día)
"""
import json
import os
import time
from types import SimpleNamespace

import pandas as pd

import alertas as al
import config
import datos
import pdf


def ruta_manifiesto():
    return os.path.join(config.OUTPUT_DIR, f"manifiesto_{config.HOY.isoformat()}.json")


def main():
    t0 = time.time()
    os.makedirs(config.OUTPUT_DIR, exist_ok=True)
    print(f"[generar] Fecha de ejecución: {config.HOY}"
          + (f" (prueba; facturas cargadas hasta {config.CORTE_CFDI:%Y-%m-%d %H:%M} México)" if config.CORTE_CFDI else ""))

    # 1-2. Alertas de los últimos días, agrupadas
    fechas = [datos.hace(k) for k in range(1, config.PLAZO_DIAS + 4)]
    lineas = datos.alertas_de_los_dias(fechas)
    manifiesto = {"fecha": config.HOY.isoformat(), "pdf": None, "alertas": [], "esperando": 0}
    if lineas.empty:
        print("[generar] No hay tablas de alertas en el periodo.")
        return _guardar(manifiesto)
    lineas = al.preparar_lineas(lineas)
    grupos = al.agrupar(lineas)
    print(f"[generar] {len(lineas)} líneas graves -> {len(grupos)} alertas reales "
          f"({fechas[-1]} a {fechas[0]})")

    # 3-4. Pendientes y su estado según la factura
    enviadas = datos.alertas_ya_enviadas(fechas[-1])
    top = grupos[(grupos.puesto_dia <= config.TOP_POR_DIA) & ~grupos.alerta_id.isin(enviadas)]
    facturas = {(r.sociedad, f, r.fecha.date()) for r in top.itertuples() for f in r.facturas}
    cfdi = datos.cfdi_de_facturas(facturas, fechas[-1])
    pend = al.clasificar(grupos, lineas, cfdi, enviadas)
    seleccion = al.seleccionar(pend)
    n_esperando = int((pend.estado == "esperando").sum()) if len(pend) else 0
    manifiesto["esperando"] = n_esperando
    print(f"[generar] Ya enviadas: {len(enviadas)} · pendientes: {len(pend)} · salen hoy: {len(seleccion)} · "
          f"esperando factura: {n_esperando}")
    if seleccion.empty:
        return _guardar(manifiesto)

    # 5. Histórico, referencias y resto de líneas de cada factura
    claves = sorted({f"{r.sociedad}|{r.material_number}|{r.unidad}" for r in seleccion.itertuples()})
    kilos = lineas[["material_number", "sales_unit", "kilo_unitario"]].drop_duplicates(["material_number", "sales_unit"])
    hist = datos.historico(claves, (seleccion.fecha.min() - pd.DateOffset(months=config.MESES_HISTORICO)).date(),
                           seleccion.fecha.max().date(), kilos)
    candidatas = {r.alerta_id: al.candidatas_referencia(r, hist) for r in seleccion.itertuples()}
    refs = {(r.sociedad, c.billing_document, c.billing_date.date())
            for r in seleccion.itertuples() for c in candidatas[r.alerta_id].itertuples()}
    cfdi_ref = datos.cfdi_de_facturas(refs, (seleccion.fecha.min() - pd.Timedelta(days=config.DIAS_REFERENCIA + 2)).date())
    principales = {r.alerta_id: al.factura_principal(r, lineas, cfdi) for r in seleccion.itertuples()}
    lineas_fact = datos.lineas_de_facturas({f for _, f in principales.values()})
    ctx = SimpleNamespace(lineas=lineas, hist=hist, cfdi=cfdi, cfdi_ref=cfdi_ref, candidatas=candidatas,
                          lineas_fact=lineas_fact)

    # 6. PDF y manifiesto
    ruta = os.path.join(config.OUTPUT_DIR, f"evidencia_alertas_precios_{config.HOY.isoformat()}.pdf")
    pdf.construir(seleccion, ctx, ruta, n_esperando)
    manifiesto["pdf"] = ruta
    for r in seleccion.itertuples():
        cf_al, fact = principales[r.alerta_id]
        cf_ref, r_ref = al.elegir_referencia(r, candidatas[r.alerta_id], cfdi_ref)
        manifiesto["alertas"].append({
            "alerta_id": r.alerta_id, "fecha_alerta": r.fecha.date().isoformat(), "sociedad": r.sociedad,
            "material": r.material, "nombre_material": r.nombre_material, "cliente": r.cliente,
            "facturas": list(r.facturas), "factura_mostrada": fact,
            "uuid": cf_al.UUID.iloc[0] if cf_al is not None else None,
            "factura_referencia": r_ref.billing_document if r_ref is not None else None,
            "con_factura": bool(r.con_factura), "precio": float(r.precio), "esperado": float(r.esperado),
            "impacto_mxn": float(r.dif)})
    print(f"[generar] PDF: {ruta} ({len(seleccion)} alertas) en {time.time() - t0:.0f} s")
    return _guardar(manifiesto)


def _guardar(manifiesto):
    with open(ruta_manifiesto(), "w", encoding="utf-8") as f:
        json.dump(manifiesto, f, ensure_ascii=False, indent=2)
    print(f"[generar] Manifiesto: {ruta_manifiesto()}")
    return manifiesto


if __name__ == "__main__":
    main()
