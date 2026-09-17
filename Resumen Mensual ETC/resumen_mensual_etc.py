"""Genera el Resumen Ejecutivo Mensual de ETC (Enlaces Terrestres Comerciales).

Uso:
    python resumen_mensual_etc.py                # genera el HTML del mes cerrado más
                                                   # reciente en OUTPUT_DIR
    python resumen_mensual_etc.py --mes 2026-08   # fuerza un mes específico (para
                                                   # comparar contra el mockup / pruebas)

v1 (2026-09-03): solo genera el HTML -- el envío por correo (Gmail SMTP + conversión a
imagen) se agrega en un paso posterior, replicando resumen_diario_etc.py una vez que esté
disponible. Todas las cifras y agrupaciones de este script se validaron contra el mockup
real con datos de agosto 2026 antes de escribirlo (ver notas "Verificado:" en datos.py).
"""

import argparse
import calendar
import datetime
import os

from jinja2 import Environment, FileSystemLoader

from config import (
    COLORS, EMPRESA_NOMBRE, EMPRESA_SIGLAS, OUTPUT_DIR, TEMPLATE_PATH, TOP_N_GASTOS,
)
import datos
import graficos

MESES_ABREV_ES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]


def _dinero_corto(v):
    """$143.2M / $0.9M para valores grandes (>= 500K), $266K para valores chicos, $850
    para valores menores a mil. Verificado contra el mockup: Flotilla ($1.4M/$0.9M) y
    Ruta ($266K/$385K) usan exactamente este corte en 500,000."""
    signo = "-" if v < 0 else ""
    v = abs(v)
    if v >= 500_000:
        return f"{signo}${v/1_000_000:,.1f}M"
    if v >= 1_000:
        return f"{signo}${v/1_000:.0f}K"
    return f"{signo}${v:.0f}"


def _pct1(v):
    if v != v:  # NaN
        return "N/D"
    return f"{v:.1%}"


def _signed_pct(v):
    if v != v:
        return "N/D"
    return f"{v:+.1%}"


def _delta_kpi(valor, bueno_si_sube, ctx, es_pp=False):
    """Pieza {glyph, clase, texto, ctx} para una tarjeta KPI. El glyph (▲/▼) refleja el
    signo real del valor; la clase de color (up=verde/down=rojo) refleja si ESE signo es
    buena o mala noticia para el negocio -- decouplados a propósito, ver nota en la
    plantilla sobre "Gastos Totales" (sube = ▲ pero en rojo)."""
    if valor != valor:  # NaN
        return None
    sube = valor >= 0
    glyph = "▲" if sube else "▼"
    clase = "up" if (sube == bueno_si_sube) else "down"
    # es_pp=True: valor ya viene en puntos porcentuales (ej. -2.9). es_pp=False: valor es
    # una fracción (0.07 = 7.0%) y hay que multiplicar por 100 antes de mostrarlo.
    texto = f"{abs(valor):.1f} pp" if es_pp else f"{abs(valor) * 100:.1f}%"
    return {"glyph": glyph, "clase": clase, "texto": texto, "ctx": ctx}


def _clase_margen(valor, es_mejor):
    if valor < 0:
        return "bad"
    return "good" if es_mejor else "warn"


def _construir_segmento(titulo, desc, resultado, unidad_sub):
    """unidad_sub: función(fila) -> texto de la sub-etiqueta (ingreso formateado, o RFAREA)."""
    if resultado is None:
        return {"titulo": titulo, "desc": desc, "mejor": None, "peor": None}
    mejor, peor = resultado["mejor"], resultado["peor"]
    return {
        "titulo": titulo, "desc": desc,
        "mejor": {
            "nombre": mejor["nombre"], "sub": unidad_sub(mejor),
            "pct_txt": _pct1(mejor["margen"]), "clase": _clase_margen(mejor["margen"], True),
        },
        "peor": {
            "nombre": peor["nombre"], "sub": unidad_sub(peor),
            "pct_txt": _pct1(peor["margen"]), "clase": _clase_margen(peor["margen"], False),
        },
    }


def construir_contexto(client, mes_cerrado):
    mes_nombre = datos.nombre_mes(mes_cerrado)
    anio = mes_cerrado.year
    ultimo_dia = calendar.monthrange(anio, mes_cerrado.month)[1]

    serie = datos.fetch_serie_desempeno(client, mes_cerrado)
    kpis_raw = datos.fetch_kpis(client, mes_cerrado, serie)
    composicion, total_ingreso_donut = datos.fetch_composicion_ingresos(client, mes_cerrado)
    top_gastos_raw, pct_acumulado_gastos = datos.fetch_top_gastos(client, mes_cerrado, TOP_N_GASTOS)
    oya_raw = datos.fetch_origen_aplicacion(client, mes_cerrado)
    seg_flotilla = datos.fetch_segmento_flotilla(client, mes_cerrado)
    seg_unidad = datos.fetch_segmento_unidad(client, mes_cerrado)

    mes_rutas_str, poper_rutas, poper_nombre_rutas = datos.detectar_ultimo_mes_rutas(client)
    mes_rutas_date = datetime.date(int(mes_rutas_str[:4]), int(mes_rutas_str[4:6]), 1)
    seg_ruta = datos.fetch_segmento_ruta(client, mes_rutas_str)
    pct_ruta_asignada = datos.fetch_pct_ingreso_con_ruta(client, mes_rutas_str, mes_rutas_date)

    advertencia_deprec = datos.fetch_advertencia_depreciacion(client, mes_cerrado)

    grafico = graficos.calcular_grafico_desempeno(serie)
    donut = graficos.calcular_donut(composicion)

    top_gastos = graficos.calcular_barras_gasto([
        {"descripcion": f["descripcion"], "monto": f["monto"], "pct": f["pct"],
         "monto_txt": _dinero_corto(f["monto"]), "pct_txt": _pct1(f["pct"])}
        for f in top_gastos_raw
    ])

    oya = {
        "origen": [{"nombre": f["nombre"], "monto_txt": _dinero_corto(f["monto"])} for f in oya_raw["origen"]],
        "aplicacion": [{"nombre": f["nombre"], "monto_txt": _dinero_corto(f["monto"])} for f in oya_raw["aplicacion"]],
        "total_origen_txt": _dinero_corto(oya_raw["total_origen"]),
        "total_aplicacion_txt": _dinero_corto(oya_raw["total_aplicacion"]),
        "balance_txt": (
            f"Origen y aplicación cuadran en {_dinero_corto(oya_raw['total_origen'])}"
            if abs(oya_raw["total_origen"] - oya_raw["total_aplicacion"]) < 1
            else f"⚠ Origen ({_dinero_corto(oya_raw['total_origen'])}) y aplicación "
                 f"({_dinero_corto(oya_raw['total_aplicacion'])}) NO cuadran este mes"
        ),
    }

    kpis = [
        {"label": "Ingresos Totales", "valor": _dinero_corto(kpis_raw["ingreso_total"]),
         "delta": _delta_kpi(kpis_raw["crecim_ingresos"], True, f"vs. {MESES_ABREV_ES[mes_cerrado.month - 2]}")},
        {"label": "Gastos Totales", "valor": _dinero_corto(kpis_raw["gasto_total"]),
         "delta": _delta_kpi(kpis_raw["crecim_gastos"], False, f"vs. {MESES_ABREV_ES[mes_cerrado.month - 2]}")},
        {"label": "Utilidad Neta", "valor": _dinero_corto(kpis_raw["utilidad"]),
         "valor2": f"{_pct1(kpis_raw['margen'])} margen",
         "delta": _delta_kpi(kpis_raw["delta_margen_pp"], True, f"vs {MESES_ABREV_ES[mes_cerrado.month - 2]}", es_pp=True)},
        {"label": f"Utilidad Acum. Ene–{mes_nombre[:3]}", "valor": _dinero_corto(kpis_raw["utilidad_ytd"]),
         "valor2": f"{_pct1(kpis_raw['margen_ytd'])} margen YTD", "delta": None},
        {"label": "Crecim. de Ingresos", "valor": _signed_pct(kpis_raw["crecim_ingresos"]),
         "valor2": "vs. mes anterior", "delta": None},
    ]

    intro_html = (
        f"{mes_nombre} cerró con <b>{_dinero_corto(kpis_raw['ingreso_total'])}</b> de ingresos y "
        f"<b>{_dinero_corto(kpis_raw['gasto_total'])}</b> de gasto, dejando un margen de "
        f"<b>{_pct1(kpis_raw['margen'])}</b>. En lo acumulado del año, {EMPRESA_SIGLAS} lleva "
        f"<b>{_dinero_corto(kpis_raw['utilidad_ytd'])}</b> de utilidad sobre "
        f"{_dinero_corto(kpis_raw['ingreso_ytd'])} de ingreso ({_pct1(kpis_raw['margen_ytd'])} de margen)."
    )

    mensaje_clave = (
        f"{mes_nombre} acumula <b>{_dinero_corto(kpis_raw['ingreso_total'])}</b> de ingreso y "
        f"<b>{_dinero_corto(kpis_raw['gasto_total'])}</b> de gasto, con un margen de "
        f"<b>{_pct1(kpis_raw['margen'])}</b>"
    )
    if kpis_raw["delta_margen_pp"] == kpis_raw["delta_margen_pp"]:  # no NaN
        direccion = "por debajo" if kpis_raw["delta_margen_pp"] < 0 else "por encima"
        mensaje_clave += f" — {abs(kpis_raw['delta_margen_pp']):.1f} puntos {direccion} del mes anterior"
    mensaje_clave += ". "
    if kpis_raw["crecim_gastos"] == kpis_raw["crecim_gastos"] and kpis_raw["crecim_ingresos"] == kpis_raw["crecim_ingresos"]:
        cual_crecio_mas = "gasto" if kpis_raw["crecim_gastos"] > kpis_raw["crecim_ingresos"] else "ingreso"
        mensaje_clave += (
            f"El {'gasto' if cual_crecio_mas == 'gasto' else 'ingreso'} creció más rápido "
            f"({_signed_pct(kpis_raw['crecim_gastos'] if cual_crecio_mas == 'gasto' else kpis_raw['crecim_ingresos'])}) "
            f"que el {'ingreso' if cual_crecio_mas == 'gasto' else 'gasto'} "
            f"({_signed_pct(kpis_raw['crecim_ingresos'] if cual_crecio_mas == 'gasto' else kpis_raw['crecim_gastos'])}) "
            "frente al mes anterior, "
        )
    if top_gastos_raw:
        mensaje_clave += (
            f"con <b>{top_gastos_raw[0]['descripcion']}</b> como el concepto dominante "
            f"({_pct1(top_gastos_raw[0]['pct'])} del gasto total). "
        )
    mensaje_clave += (
        f"En lo acumulado del año, la utilidad llega a <b>{_dinero_corto(kpis_raw['utilidad_ytd'])}</b> "
        f"sobre {_dinero_corto(kpis_raw['ingreso_ytd'])} de ingreso ({_pct1(kpis_raw['margen_ytd'])} de margen)."
    )
    if advertencia_deprec:
        mensaje_clave += f'<span class="aviso">⚠ {advertencia_deprec}</span>'

    nota_segmentos = (
        f"* Rutas: la fuente de viajes (TORITE/TORROT) no se ha actualizado desde el "
        f"último día con datos ({poper_nombre_rutas}), por lo que se muestra el último mes "
        f"disponible; solo ~{pct_ruta_asignada:.0%} del ingreso total tiene ruta asignada. "
        "Flotilla y unidad excluyen registros por debajo de un ingreso mínimo para evitar "
        "distorsión por bajo volumen."
    )

    return {
        "empresa_nombre": EMPRESA_NOMBRE, "empresa_siglas": EMPRESA_SIGLAS,
        "periodo_badge": f"{mes_nombre.upper()} {anio}",
        "subtitulo": f"Cierre al {ultimo_dia} de {mes_nombre.lower()} de {anio}",
        "intro_html": intro_html,
        "mes_nombre": mes_nombre, "mes_nombre_lower": mes_nombre.lower(), "anio": anio,
        "mes_anterior_abrev": MESES_ABREV_ES[mes_cerrado.month - 2],
        "desde_hasta": f"{datos.nombre_mes(serie.iloc[0]['MES_CONTABLE'].date(), False)} a {mes_nombre.lower()} {anio}",
        "kpis": kpis,
        "kpis_extra": {
            "margen": kpis_raw["margen"], "margen_txt": _pct1(kpis_raw["margen"]),
            "crecim_ingresos_txt": _signed_pct(kpis_raw["crecim_ingresos"]),
            "crecim_ingresos_clase": "good" if kpis_raw["crecim_ingresos"] >= 0 else "bad",
            "crecim_gastos_txt": _signed_pct(kpis_raw["crecim_gastos"]),
            "crecim_gastos_clase": "bad" if kpis_raw["crecim_gastos"] >= 0 else "good",
        },
        "grafico": grafico, "colors": COLORS,
        "segmentos": [
            _construir_segmento("Por Flotilla", f"{mes_nombre} {anio}", seg_flotilla,
                                lambda f: f"{_dinero_corto(f['ingreso'])} ingreso"),
            _construir_segmento(
                "Por Unidad (motriz)",
                f"{mes_nombre} {anio} · {seg_unidad['n_unidades'] if seg_unidad else 0} unidades",
                seg_unidad, lambda f: f"RFAREA {f['rfarea']}"),
            _construir_segmento(f"Por Ruta", f"{poper_nombre_rutas}*", seg_ruta,
                                lambda f: f"{_dinero_corto(f['ingreso'])} ingreso"),
        ],
        "nota_segmentos": nota_segmentos,
        "donut_gradient_css": donut["gradient_css"], "donut_legend": [
            {**item, "pct_txt": _pct1(item["pct"])} for item in donut["legend"]
        ],
        "donut_total_txt": _dinero_corto(total_ingreso_donut),
        "top_gastos": top_gastos, "pct_acumulado_gastos_txt": _pct1(pct_acumulado_gastos),
        "oya": oya,
        "mensaje_clave_html": mensaje_clave,
    }


def generar_html(mes_forzado=None, client=None):
    """Devuelve (out_path, contexto, mes_cerrado) -- enviar_reporte.py reutiliza `contexto`
    (KPIs ya formateados) para el texto plano del correo, sin volver a consultar BigQuery."""
    client = client or datos.get_client()
    mes_cerrado = mes_forzado or datos.detectar_mes_cerrado(client)
    print(f"Generando Resumen Mensual ETC para: {datos.nombre_mes(mes_cerrado)} {mes_cerrado.year}")

    contexto = construir_contexto(client, mes_cerrado)

    env = Environment(loader=FileSystemLoader(os.path.dirname(TEMPLATE_PATH)))
    template = env.get_template(os.path.basename(TEMPLATE_PATH))
    html = template.render(**contexto)

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    out_path = os.path.join(OUTPUT_DIR, f"resumen_mensual_etc_{mes_cerrado.isoformat()}.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"HTML generado: {out_path}")
    return out_path, contexto, mes_cerrado


def generar_html_y_png(mes_forzado=None, client=None):
    """Igual que generar_reporte_completo, pero sin el PDF -- se mantiene para quien solo
    necesite la vista previa rápida (ver --dry-run)."""
    out_path, png_path, _pdf_path, contexto, mes_cerrado = generar_reporte_completo(mes_forzado, client)
    return out_path, png_path, contexto, mes_cerrado


def generar_reporte_completo(mes_forzado=None, client=None):
    """Genera HTML + PNG (para incrustar en el correo, ver render_png.py) + PDF (mismo
    contenido, adjunto -- pedido explícito del usuario 2026-09-03: "quiero que se incluya
    un PDF"). El PDF se imprime del MISMO HTML con un @page ajustado al tamaño real del
    contenido medido por renderizar_html_a_png -- no es una captura del PNG, así que el
    texto queda nítido a cualquier zoom (la otra queja del mismo pedido)."""
    import render_png

    out_path, contexto, mes_cerrado = generar_html(mes_forzado, client)
    color_fondo = COLORS["paper"].lstrip("#")

    png_path = out_path.replace(".html", ".png")
    ancho_css, alto_css = render_png.renderizar_html_a_png(out_path, png_path, color_fondo=color_fondo)
    print(f"PNG generado: {png_path}")

    pdf_path = out_path.replace(".html", ".pdf")
    render_png.renderizar_html_a_pdf(out_path, pdf_path, ancho_css, alto_css, color_fondo=color_fondo)
    print(f"PDF generado: {pdf_path}")

    return out_path, png_path, pdf_path, contexto, mes_cerrado


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mes", default=None, help="Forzar el mes a reportar, formato YYYY-MM "
                                                       "(para pruebas -- por defecto detecta el "
                                                       "último mes cerrado automáticamente)")
    args = parser.parse_args()
    mes_forzado = None
    if args.mes:
        anio, mes = args.mes.split("-")
        mes_forzado = datetime.date(int(anio), int(mes), 1)
    generar_html(mes_forzado)[0]


if __name__ == "__main__":
    main()
