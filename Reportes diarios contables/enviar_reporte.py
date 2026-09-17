"""Envía por correo el reporte diario: PDF adjunto (detalle completo) + el MISMO detalle
completo en el propio cuerpo del correo (cards de totales + gráfico + tabla por sociedad,
por cada sección), para que se pueda ver todo de un vistazo en el correo sin necesidad de
abrir el adjunto.

Usa la API de SendGrid, igual que la automatización de Cambio de Divisa
(ver "Cambio divisa/divisa.py"), en vez de SMTP con contraseña de aplicación de
Office 365 (bloqueada mientras no se configure una app password ahí).

No duplica cálculos: reutiliza fetch_cuenta/fetch_descuentos/fetch_mermas_ratio/
a_plantilla_importe (datos.py), build_chart/build_chart_ratio (graficos.py) y
_money/_pct/_pct_o_100 (pdf.py) — las mismas funciones que ya arman las cards, los gráficos
y la lógica de signo del PDF. El PDF en sí no se toca aquí, solo se adjunta.

Las secciones del cuerpo van en el MISMO orden que las páginas del PDF, incluidas las dos
formas (importe y razón) de Mermas y de Descuentos — si se agrega o quita una sección en
generar_reporte.py hay que reflejarlo en _preparar_resumenes() o el correo queda desalineado
con su adjunto.

**Tablas completas en el cuerpo (2026-09-03, a pedido explícito del usuario/finanzas):** antes
el cuerpo solo traía cards + gráfico, y había que abrir el PDF para ver el detalle por
sociedad. Se probaron dos layouts (tabla debajo del gráfico a ancho completo vs. tabla al
lado del gráfico) con datos reales -- la opción "al lado" se descartó porque el gráfico de
este reporte es horizontal ancho, con etiquetas de sociedad rotadas 40° pensadas para hasta
20 barras, y se vuelve ilegible si se achica a la mitad del ancho para dejarle espacio a la
tabla. Se implementó "tabla completa debajo del gráfico", igual estilo que la tabla del PDF.

Encontrado al probar con las 7 secciones reales: el HTML resultante pesaba 126 KB con estilos
inline repetidos en cada celda -- por encima del umbral de recorte de Gmail (~102 KB), que
muestra "[Mensaje recortado] Ver mensaje completo" en vez del cuerpo completo. Confirmado
además que la mayoría de la lista de destinatarios reales usa Gmail/Google Workspace (MX de
proan.com y ucm.es apuntan a Google; solo quantrue.com es Microsoft 365) -- no era un riesgo
remoto. Se resolvió moviendo los estilos repetidos de cada celda a clases CSS en un único
bloque <style> en el <head> (ver STYLE_BLOCK) en vez de repetir el `style="..."` inline en
cada `<td>` -- mismo diseño visual exacto, HTML de 48 KB (verificado con un envío de prueba
real a dos destinatarios, uno en Gmail y otro en Outlook, antes de aplicarlo a toda la lista).

Destinatarios: se leen de la lista de Firestore lists/reportes-financieros
(base proan-lista-mails) via get_mailing_list() -- fuente unica, sin cascada ni
correos hardcodeados. Cambiar quien recibe el reporte es editar ese documento,
no hace falta redesplegar. El correo se manda To: SENDGRID_FROM_EMAIL, Cc: cada destinatario
resuelto (igual que divisa.py), no To: destinatario como antes.

Uso:
    python enviar_reporte.py                          # envía el reporte de hoy (lista de Firestore)
    python enviar_reporte.py --pdf ruta\al\reporte.pdf # envía un PDF específico
    python enviar_reporte.py --to otro@correo.com      # OVERRIDE explícito para pruebas
                                                        # locales -- salta la lista de Firestore
    python enviar_reporte.py --dry-run                 # no envía nada; guarda una
                                                        # vista previa del HTML en OUTPUT_DIR

Requiere credenciales de SendGrid en variables de entorno (ver .env.example):
    SENDGRID_API_KEY, SENDGRID_FROM_EMAIL (opcional)

En Cloud Run (ver deploy.sh) también se puede forzar dry-run con la variable de entorno
REPORTE_CUENTAS_EMAIL_DRY_RUN=true (además del flag --dry-run) -- un Job no recibe argumentos
de línea de comandos, así que es la única forma de probar en producción sin enviar de verdad.
"""

import argparse
import base64
import datetime
import os
import re
import unicodedata

from dotenv import load_dotenv
from google.cloud import bigquery

from config import (
    COLORS, CUENTAS, CUENTAS_ACTIVAS, CUENTAS_SOLO_DEBE,
    EMAIL_ASUNTO_TEMPLATE, EMAIL_CUERPO_TEMPLATE, FIRESTORE_DATABASE_ID,
    FIRESTORE_LISTS_COLLECTION, OUTPUT_DIR, PROJECT_ID, REPORTE_CUENTAS_LIST_ID, SOCIEDADES,
    TITULOS_SECCION,
)
from datos import (
    fetch_cuenta, fetch_descuentos, fetch_sociedades, fetch_mermas_ratio, a_plantilla_importe,
)
from graficos import build_chart, build_chart_descuentos, build_chart_ratio
from pdf import _money, _pct, _pct_o_100

load_dotenv()

SENDGRID_FROM_EMAIL_DEFAULT = "noreply@proan.com"

# Estilos de las tablas y tarjetas del cuerpo del correo, como clases CSS en un único bloque
# <style> (en vez de repetir `style="..."` inline en cada <td>/<div>) -- ver la nota de
# "Tablas completas en el cuerpo" en el docstring del módulo: con las 7 secciones reales,
# estilo inline por celda pesaba 126 KB (por encima del umbral de recorte de Gmail, ~102 KB);
# con clases baja a 48 KB, mismo diseño visual exacto. Colores tomados de COLORS (config.py)
# para no duplicar la paleta.
STYLE_BLOCK = f"""
<style>
  .tbl {{ width:100%; border-collapse:collapse; margin-top:12px; }}
  .tbl th {{ padding:8px; font-family:'Segoe UI',Arial,sans-serif; font-size:10.5px; font-weight:700; color:#fff; }}
  .tbl thead tr {{ background:{COLORS['header_bg']}; }}
  .thl {{ text-align:left; }}
  .thr {{ text-align:right; }}
  .bar {{ width:4px; padding:0; }}
  .nm {{ padding:6px 8px; font-size:11.5px; color:{COLORS['text_primary']}; font-family:'Segoe UI',Arial,sans-serif; }}
  .num {{ padding:6px 8px; font-size:11px; text-align:right; font-family:Consolas,'Courier New',monospace; color:{COLORS['text_primary']}; }}
  .tot td {{ background:{COLORS['tile_bg']}; border-top:1.5px solid {COLORS['text_primary']}; }}
  .tot .nm {{ font-size:11.5px; font-weight:800; }}
  .tot .num {{ font-weight:700; }}
  .pos {{ color:{COLORS['good']}; }}
  .neg {{ color:{COLORS['critical']}; }}
  .mut {{ color:{COLORS['muted']}; }}
  .rtbl th {{ padding:6px; font-size:9px; }}
  .rtbl .nm {{ padding:5px 6px; font-size:10px; border-bottom:1px solid {COLORS['grid']}; }}
  .rtbl .num {{ padding:5px 6px; font-size:9px; border-bottom:1px solid {COLORS['grid']}; }}
  .rtbl .tot .nm {{ font-size:10px; }}
  .rtbl .tot .num {{ font-size:9px; }}
  .card {{ background:{COLORS['tile_bg']}; border-radius:8px; }}
  .card-l {{ font-family:'Segoe UI',Arial,sans-serif; font-size:9.5px; font-weight:700; color:{COLORS['muted']}; text-transform:uppercase; letter-spacing:.4px; margin:0 0 6px; }}
  .card-v {{ font-family:'Segoe UI',Arial,sans-serif; font-size:18px; font-weight:800; color:{COLORS['text_primary']}; }}
  .sect-h {{ font-family:'Segoe UI',Arial,sans-serif; font-size:15px; font-weight:800; color:{COLORS['header_bg']}; border-left:4px solid {COLORS['header_accent']}; padding-left:10px; margin:0 0 12px; }}
</style>"""


def _slug(nombre):
    sin_acentos = "".join(
        c for c in unicodedata.normalize("NFKD", nombre) if not unicodedata.combining(c)
    )
    return re.sub(r"[^a-z0-9]+", "_", sin_acentos.lower()).strip("_")


def _clase_signo(v):
    """Clase CSS ('pos'/'neg'/'mut') según el signo de v, para tarjetas y celdas de tabla
    coloreadas por signo (ver STYLE_BLOCK). Reemplaza a la vieja _color_por_signo (que
    devolvía un hex): con clases en vez de estilo inline, colorear por signo es aplicar la
    clase, no interpolar un color distinto en cada celda."""
    if v != v:  # NaN
        return "mut"
    return "pos" if v >= 0 else "neg"


# --- Destinatarios: lista administrada en Firestore ---------------------------------------
# La lista vive en lists/reportes-financieros (base proan-lista-mails) y la comparten los
# tres reportes financieros. get_mailing_list() esta duplicada en cada carpeta a proposito:
# cada automatizacion es autonoma para su propio build de Docker (ver README del repo), el
# contexto de 'gcloud builds submit .' es solo esta carpeta y un modulo compartido fuera de
# ella no viajaria en la imagen.

def _normalize_recipients(raw_recipients):
    recipients = []
    seen = set()
    for raw in raw_recipients:
        email = str(raw or "").strip()
        if not email:
            continue
        key = email.lower()
        if key in seen:
            continue
        seen.add(key)
        recipients.append(email)
    return recipients


def get_mailing_list(list_id):
    """Destinatarios de una lista de correo administrada en Firestore.

    Lee el documento `lists/{list_id}` de la base FIRESTORE_DATABASE_ID
    ("proan-lista-mails"), que NO es la base default del proyecto: hay que pasar
    `database=` explicitamente o el cliente apuntaria a "(default)" y no encontraria nada.

    Devuelve el array `emails` si el documento existe y tiene `enabled` en true. En
    cualquier otro caso -- documento inexistente, lista deshabilitada, `emails` mal formado
    o Firestore inaccesible -- devuelve [] y deja una advertencia clara en el log, SIN
    lanzar excepcion: quedarse sin destinatarios no debe tumbar el Job.

    Usa print() y no logging por la convencion de este archivo (ver cabecera); en Cloud Run
    stdout va igualmente a Cloud Logging, asi que la advertencia queda registrada.
    """
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
        print(f"[recipients] ADVERTENCIA: la lista {list_id} esta deshabilitada "
              f"(enabled=false); no se enviara el reporte a nadie")
        return []

    emails = data.get("emails")
    if not isinstance(emails, list):
        print(f"[recipients] ADVERTENCIA: el campo emails de {list_id} no es un array")
        return []

    recipients = _normalize_recipients([str(email) for email in emails])
    if not recipients:
        print(f"[recipients] ADVERTENCIA: la lista {list_id} no tiene ningun correo valido")
    return recipients


def resolve_email_recipients():
    """Destinatarios del reporte. La lista de Firestore es la UNICA fuente.

    Hasta el 2026-08-20 habia una cascada Firestore -> variable de entorno -> tupla
    hardcodeada en config.py. Se retiro a peticion del usuario para que la lista se
    administre en un solo sitio: cambiar quien recibe el reporte es editar el documento de
    Firestore, sin redesplegar nada.

    Contrapartida a tener presente: si la lista se deshabilita o Firestore no responde, no
    sale correo. get_mailing_list() lo avisa en el log y enviar_reporte() corta ahi mismo,
    en vez de fallar con una excepcion.
    """
    return get_mailing_list(REPORTE_CUENTAS_LIST_ID), "firestore"


def _tabla_importe_html(df, current_year, prior_year):
    """Tabla Sociedad | actual | anterior | Diferencias | %Variac., mismo contenido y mismo
    orden (por |actual| descendente) que pdf._tabla_sociedades, pero como HTML de correo con
    clases de STYLE_BLOCK en vez de estilo inline por celda."""
    df = df.sort_values("actual", key=lambda s: s.abs(), ascending=False)
    filas = []
    for _, r in df.iterrows():
        pct = _pct_o_100(r["diferencia"], r["anterior"])
        clase = _clase_signo(pct)
        filas.append(f"""
        <tr>
          <td class="bar {clase}"></td>
          <td class="nm">{r['nombre_sociedad']}</td>
          <td class="num">{_money(r['actual'])}</td>
          <td class="num">{_money(r['anterior'])}</td>
          <td class="num {clase}">{_money(r['diferencia'])}</td>
          <td class="num {clase}">{_pct(pct)}</td>
        </tr>""")
    total_actual = df["actual"].sum()
    total_anterior = df["anterior"].sum()
    diferencia_total = total_actual - total_anterior
    pct_total = _pct_o_100(diferencia_total, total_anterior)
    clase_total = _clase_signo(pct_total)
    return f"""
  <table class="tbl">
    <thead><tr>
      <td class="bar"></td>
      <th class="thl">SOCIEDAD</th>
      <th class="thr">{current_year} (HOY)</th>
      <th class="thr">{prior_year}</th>
      <th class="thr">DIFERENCIAS</th>
      <th class="thr">% VARIAC.</th>
    </tr></thead>
    <tbody>
    {"".join(filas)}
    <tr class="tot">
      <td class="bar {clase_total}"></td>
      <td class="nm">TOTAL GENERAL</td>
      <td class="num">{_money(total_actual)}</td>
      <td class="num">{_money(total_anterior)}</td>
      <td class="num {clase_total}">{_money(diferencia_total)}</td>
      <td class="num {clase_total}">{_pct(pct_total)}</td>
    </tr>
    </tbody>
  </table>"""


def _tabla_ratio_html(df, current_year, prior_year, label_base, label_cuenta, col_base, col_cuenta):
    """Tabla de 7 columnas (base/cuenta en los dos periodos + %), mismo contenido y mismo
    orden (por |{col_base}_actual| descendente) que pdf._tabla_ratio, como HTML de correo."""
    df = df.sort_values(f"{col_base}_actual", key=lambda s: s.abs(), ascending=False)
    filas = []
    for _, r in df.iterrows():
        clase_act = _clase_signo(r["pct_actual"])
        clase_ant = _clase_signo(r["pct_anterior"])
        filas.append(f"""
        <tr>
          <td class="nm">{r['nombre_sociedad']}</td>
          <td class="num">{_money(r[f'{col_base}_anterior'])}</td>
          <td class="num">{_money(r[f'{col_base}_actual'])}</td>
          <td class="num">{_money(r[f'{col_cuenta}_anterior'])}</td>
          <td class="num">{_money(r[f'{col_cuenta}_actual'])}</td>
          <td class="num {clase_ant}">{_pct(r['pct_anterior'])}</td>
          <td class="num {clase_act}">{_pct(r['pct_actual'])}</td>
        </tr>""")
    tb_act = df[f"{col_base}_actual"].sum(); tb_ant = df[f"{col_base}_anterior"].sum()
    tc_act = df[f"{col_cuenta}_actual"].sum(); tc_ant = df[f"{col_cuenta}_anterior"].sum()
    tp_act = (tc_act / tb_act) if tb_act else float("nan")
    tp_ant = (tc_ant / tb_ant) if tb_ant else float("nan")
    return f"""
  <table class="tbl rtbl">
    <thead><tr>
      <th class="thl">SOCIEDAD</th>
      <th class="thr">{label_base} {prior_year}</th>
      <th class="thr">{label_base} {current_year}</th>
      <th class="thr">{label_cuenta} {prior_year}</th>
      <th class="thr">{label_cuenta} {current_year}</th>
      <th class="thr">% {prior_year}</th>
      <th class="thr">% {current_year}</th>
    </tr></thead>
    <tbody>
    {"".join(filas)}
    <tr class="tot">
      <td class="nm">TOTAL GENERAL</td>
      <td class="num">{_money(tb_ant)}</td>
      <td class="num">{_money(tb_act)}</td>
      <td class="num">{_money(tc_ant)}</td>
      <td class="num">{_money(tc_act)}</td>
      <td class="num {_clase_signo(tp_ant)}">{_pct(tp_ant)}</td>
      <td class="num {_clase_signo(tp_act)}">{_pct(tp_act)}</td>
    </tr>
    </tbody>
  </table>"""


def _preparar_resumenes(client, hoy):
    """Reconstruye, con las mismas funciones que usa generar_reporte.py, el resumen
    (cards + gráfico + tabla completa por sociedad) de cada sección del PDF. Devuelve una
    lista de dicts: {titulo, cards: [(label, value, clase_css)], chart_path, cid, tabla_html}."""
    current_year = hoy.year
    prior_year = current_year - 1
    hist_years = list(range(current_year - 4, current_year + 1))
    sociedades = fetch_sociedades(client)

    def _cards_importe(df):
        total_actual = df["actual"].sum()
        total_anterior = df["anterior"].sum()
        diferencia = total_actual - total_anterior
        return [
            (f"Total {current_year} (hoy)", _money(total_actual), ""),
            (f"Total {prior_year}", _money(total_anterior), ""),
            ("Diferencia total", _money(diferencia), _clase_signo(diferencia)),
        ]

    def _cards_ratio(df, col_base, col_cuenta, label_base, label_cuenta):
        base_total = df[f"{col_base}_actual"].sum()
        cuenta_total = df[f"{col_cuenta}_actual"].sum()
        pct_global = (cuenta_total / base_total) if base_total else float("nan")
        return [
            (f"{label_base} total {current_year} (hoy)", _money(base_total), ""),
            (f"{label_cuenta} total {current_year} (hoy)", _money(cuenta_total), ""),
            (f"% Global ({label_cuenta}/{label_base})", _pct(pct_global), ""),
        ]

    secciones = []
    for nombre_cuenta in CUENTAS_ACTIVAS:
        raccts = CUENTAS[nombre_cuenta]
        titulo = TITULOS_SECCION.get(nombre_cuenta, nombre_cuenta)
        _, df = fetch_cuenta(client, raccts, hist_years, current_year, prior_year, sociedades,
                              solo_debe=nombre_cuenta in CUENTAS_SOLO_DEBE)

        chart_path = os.path.join(OUTPUT_DIR, f"_chart_{nombre_cuenta.replace(' ', '_')}.png")
        build_chart(df, titulo, current_year, prior_year, chart_path)

        secciones.append({
            "titulo": titulo,
            "cards": _cards_importe(df),
            "chart_path": chart_path,
            "cid": f"grafico_{_slug(nombre_cuenta)}",
            "tabla_html": _tabla_importe_html(df, current_year, prior_year),
        })

    # Mermas — % sobre Costo Total: la segunda de las dos formas de la misma cuenta, en el
    # mismo orden que el PDF (importe primero, razón después). Ver TITULOS_SECCION en config.py.
    titulo_mermas_ratio = TITULOS_SECCION["Mermas ratio"]
    df_mermas_ratio = fetch_mermas_ratio(
        client, CUENTAS["Mermas"], current_year, prior_year, sociedades
    )[1]
    chart_path_mermas_ratio = os.path.join(OUTPUT_DIR, "_chart_Mermas_ratio.png")
    build_chart_ratio(df_mermas_ratio, titulo_mermas_ratio, current_year, prior_year,
                      chart_path_mermas_ratio, col_cuenta="mermas")
    secciones.append({
        "titulo": titulo_mermas_ratio,
        "cards": _cards_ratio(df_mermas_ratio, "costo", "mermas", "Costo Total", "Mermas"),
        "chart_path": chart_path_mermas_ratio,
        "cid": "grafico_mermas_ratio",
        "tabla_html": _tabla_ratio_html(df_mermas_ratio, current_year, prior_year,
                                        "Costo Total", "Mermas", "costo", "mermas"),
    })

    df_desc = fetch_descuentos(client, current_year, prior_year, SOCIEDADES)[1]

    titulo_desc_importe = TITULOS_SECCION["Descuentos importe"]
    df_desc_importe = a_plantilla_importe(df_desc, "descuentos")
    chart_path_desc_importe = os.path.join(OUTPUT_DIR, "_chart_Descuentos_importe.png")
    build_chart(df_desc_importe, titulo_desc_importe, current_year, prior_year,
                chart_path_desc_importe)
    secciones.append({
        "titulo": titulo_desc_importe,
        "cards": _cards_importe(df_desc_importe),
        "chart_path": chart_path_desc_importe,
        "cid": "grafico_descuentos_importe",
        "tabla_html": _tabla_importe_html(df_desc_importe, current_year, prior_year),
    })

    titulo_desc_ratio = TITULOS_SECCION["Descuentos ratio"]
    chart_path_desc = os.path.join(OUTPUT_DIR, "_chart_Descuentos_y_Bonificaciones.png")
    build_chart_descuentos(df_desc, current_year, prior_year, chart_path_desc,
                           titulo=titulo_desc_ratio)
    secciones.append({
        "titulo": titulo_desc_ratio,
        "cards": _cards_ratio(df_desc, "ingresos", "descuentos", "Ingresos", "Descuentos"),
        "chart_path": chart_path_desc,
        "cid": "grafico_descuentos_y_bonificaciones",
        "tabla_html": _tabla_ratio_html(df_desc, current_year, prior_year,
                                        "Ingresos", "Descuentos", "ingresos", "descuentos"),
    })

    # Variación de Precios: mismo formato que el resto de cuentas (año en curso vs. año
    # anterior), por decisión del usuario -- ver la nota de esta cuenta en config.py. Usa
    # SOCIEDADES (no dm_company) y va al final, igual que en el PDF.
    raccts_precios = CUENTAS["Variación de Precios"]
    _, df_precios = fetch_cuenta(client, raccts_precios, hist_years, current_year, prior_year,
                                 SOCIEDADES)
    chart_path_precios = os.path.join(OUTPUT_DIR, "_chart_Variacion_de_Precios.png")
    build_chart(df_precios, "Variación de Precios", current_year, prior_year, chart_path_precios)
    secciones.append({
        "titulo": "Variación de Precios",
        "cards": _cards_importe(df_precios),
        "chart_path": chart_path_precios,
        "cid": "grafico_variacion_de_precios",
        "tabla_html": _tabla_importe_html(df_precios, current_year, prior_year),
    })
    return secciones


def _card_html(label, value, clase_color):
    return f"""
      <td width="33%" style="padding:5px;">
        <table width="100%" cellpadding="0" cellspacing="0" class="card">
          <tr><td style="padding:14px 14px;">
            <div class="card-l">{label}</div>
            <div class="card-v {clase_color}">{value}</div>
          </td></tr>
        </table>
      </td>"""


def _seccion_html(seccion, src_img):
    cards_html = "".join(_card_html(label, value, clase) for label, value, clase in seccion["cards"])
    return f"""
        <tr><td style="padding:22px 28px 4px;">
          <div class="sect-h">{seccion['titulo'].upper()}</div>
          <table width="100%" cellpadding="0" cellspacing="0"><tr>{cards_html}</tr></table>
          <div style="margin-top:12px;">
            <img src="{src_img}" width="620"
                 style="width:100%;max-width:620px;display:block;border-radius:6px;border:1px solid {COLORS['grid']};"
                 alt="{seccion['titulo']}">
          </div>
          {seccion['tabla_html']}
        </td></tr>"""


def build_email_html(fecha_str, secciones, use_cid=True):
    """use_cid=True referencia las imágenes como cid:... (correo real). use_cid=False
    referencia el archivo local en disco (solo para la vista previa de --dry-run,
    ya que cid: no se puede abrir directamente en un navegador)."""
    def src_de(seccion):
        if use_cid:
            return f"cid:{seccion['cid']}"
        return "file:///" + os.path.abspath(seccion["chart_path"]).replace("\\", "/")

    secciones_html = "".join(_seccion_html(s, src_de(s)) for s in secciones)
    return f"""<!DOCTYPE html>
<html lang="es"><head><meta charset="UTF-8">{STYLE_BLOCK}</head>
<body style="margin:0;padding:0;background:{COLORS['surface']};font-family:'Segoe UI',Arial,sans-serif;color:{COLORS['text_primary']};">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:{COLORS['surface']};padding:24px 12px;">
    <tr><td align="center">
      <table width="680" cellpadding="0" cellspacing="0"
             style="background:#ffffff;border-radius:12px;overflow:hidden;border:1px solid {COLORS['grid']};max-width:680px;width:100%;">
        <tr><td style="background:{COLORS['header_bg']};padding:22px 28px;border-top:4px solid {COLORS['header_accent']};">
          <div style="font-family:'Segoe UI',Arial,sans-serif;font-size:19px;font-weight:800;color:#ffffff;">
            Reporte diario cuentas contables PROAN
          </div>
          <div style="font-family:'Segoe UI',Arial,sans-serif;font-size:12px;color:#c9d6e5;margin-top:4px;">
            {fecha_str}
          </div>
        </td></tr>
        {secciones_html}
        <tr><td style="padding:16px 28px 26px;border-top:1px solid {COLORS['grid']};">
          <p style="font-family:'Segoe UI',Arial,sans-serif;font-size:11.5px;color:{COLORS['muted']};margin:0;line-height:1.5;">
            Arriba tienes el detalle completo por sociedad de cada sección; el PDF adjunto
            trae el mismo detalle en un solo documento.
          </p>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body></html>"""


def enviar_reporte(pdf_path, destinatario_override=None, dry_run_override=False):
    if not os.path.exists(pdf_path):
        raise FileNotFoundError(f"No se encontró el PDF: {pdf_path}")

    hoy = datetime.date.today()
    fecha_str = hoy.strftime("%d/%m/%Y")
    asunto = EMAIL_ASUNTO_TEMPLATE.format(fecha=fecha_str)
    cuerpo_texto_plano = EMAIL_CUERPO_TEMPLATE.format(fecha=fecha_str)
    from_email = os.environ.get("SENDGRID_FROM_EMAIL", SENDGRID_FROM_EMAIL_DEFAULT)

    if destinatario_override:
        recipients = _normalize_recipients([destinatario_override])
        recipients_source = "override (--to, cascada omitida)"
    else:
        recipients, recipients_source = resolve_email_recipients()
    print(f"Destinatarios resueltos desde {recipients_source}: {recipients}")

    # Sin destinatarios no se envia nada, pero tampoco se falla: la lista de Firestore es la
    # unica fuente, y si esta deshabilitada o vacia lo correcto es terminar limpio dejando el
    # motivo en el log (get_mailing_list ya imprimio la advertencia concreta).
    if not recipients:
        print("[recipients] Sin destinatarios: no se envia el correo. Revisa el documento "
              f"Firestore lists/{REPORTE_CUENTAS_LIST_ID} (campos enabled / emails).")
        return

    dry_run_env = os.environ.get("REPORTE_CUENTAS_EMAIL_DRY_RUN", "false").strip().lower() in {
        "1", "true", "yes",
    }
    dry_run = dry_run_override or dry_run_env

    client = bigquery.Client(project=PROJECT_ID)
    secciones = _preparar_resumenes(client, hoy)

    if dry_run:
        html_preview = build_email_html(fecha_str, secciones, use_cid=False)
        preview_path = os.path.join(OUTPUT_DIR, "_preview_email.html")
        with open(preview_path, "w", encoding="utf-8") as f:
            f.write(html_preview)
        print(f"[DRY RUN] De: {from_email}  Para (To): {from_email}  Cc: {recipients}")
        print(f"[DRY RUN] Asunto: {asunto}")
        print(f"[DRY RUN] Adjunto PDF: {pdf_path}")
        print(f"[DRY RUN] Secciones en el cuerpo: {', '.join(s['titulo'] for s in secciones)}")
        print(f"[DRY RUN] Vista previa del HTML guardada en: {preview_path} (ábrela en el navegador)")
        print("[DRY RUN] No se envió ningún correo real (SendGrid no fue invocado).")
        return

    html_body = build_email_html(fecha_str, secciones, use_cid=True)

    api_key = os.environ["SENDGRID_API_KEY"]

    import sendgrid
    from sendgrid.helpers.mail import Attachment, Cc, ContentId, Disposition, FileContent, FileName, FileType, Mail

    message = Mail(
        from_email=from_email,
        to_emails=from_email,
        subject=asunto,
        plain_text_content=cuerpo_texto_plano,
        html_content=html_body,
    )
    for recipient in recipients:
        message.add_cc(Cc(recipient))

    with open(pdf_path, "rb") as f:
        pdf_bytes = f.read()
    message.add_attachment(Attachment(
        FileContent(base64.b64encode(pdf_bytes).decode()),
        FileName(os.path.basename(pdf_path)),
        FileType("application/pdf"),
        Disposition("attachment"),
    ))

    for seccion in secciones:
        with open(seccion["chart_path"], "rb") as f:
            chart_bytes = f.read()
        message.add_attachment(Attachment(
            FileContent(base64.b64encode(chart_bytes).decode()),
            FileName(os.path.basename(seccion["chart_path"])),
            FileType("image/png"),
            Disposition("inline"),
            ContentId(seccion["cid"]),
        ))

    sg_client = sendgrid.SendGridAPIClient(api_key)
    response = sg_client.send(message)
    print(f"SendGrid respondió con status {response.status_code}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pdf", default=None, help="Ruta al PDF a enviar")
    parser.add_argument("--to", default=None,
                         help="Override de destinatario para pruebas locales -- salta la "
                              "lista de Firestore")
    parser.add_argument("--dry-run", action="store_true",
                         help="No envía el correo; guarda una vista previa del HTML")
    args = parser.parse_args()

    pdf_path = args.pdf or os.path.join(
        OUTPUT_DIR, f"reporte_cuentas_proan_{datetime.date.today().isoformat()}.pdf"
    )

    enviar_reporte(pdf_path, destinatario_override=args.to, dry_run_override=args.dry_run)
    if not args.dry_run:
        print(f"Reporte enviado: {pdf_path}")


if __name__ == "__main__":
    main()
