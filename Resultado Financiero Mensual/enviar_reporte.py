"""Envía por correo el "Resultado Financiero Mensual": PDF adjunto (detalle completo) + el
mismo contenido visible directamente en el CUERPO del correo (banner navy + tarjetas KPI +
gráfico embebido + tabla completa con íconos de estatus), agregado 2026-08-07 a pedido
explícito del usuario ("también quiero que salga el html en el correo") -- mismo criterio que
los otros dos reportes.

No duplica cálculos: reutiliza fetch_resultado_mensual (datos.py), build_chart_mensual
(graficos.py) y _money/_pct (pdf.py).

Íconos en el correo: texto plano (▲ ámbar / ● gris), NO imágenes SVG en data: URI -- mismo
criterio que el reporte diario (Outlook rompe casi cualquier SVG en data: URI). Los glifos
▲ (U+25B2) y ● (U+25CF) son parte del bloque "Geometric Shapes", con soporte de fuente mucho
más confiable que dingbats/emoji (⚠/✓) en clientes de correo.

Usa la misma API de SendGrid que los otros reportes, con credenciales propias (.env de esta
misma carpeta -- ya no reutiliza el .env de "Reportes diarios contables").

Destinatarios: se leen de la lista de Firestore lists/reportes-financieros
(base proan-lista-mails) via get_mailing_list() -- fuente unica, sin cascada ni
correos hardcodeados. Cambiar quien recibe el reporte es editar ese documento,
no hace falta redesplegar. El correo se manda To: SENDGRID_FROM_EMAIL, Cc: cada destinatario
resuelto.

Uso:
    python enviar_reporte.py                        # cascada de destinatarios
    python enviar_reporte.py --to correo@destino.com # OVERRIDE explícito, salta la lista
    python enviar_reporte.py --dry-run               # no envía; guarda una vista previa del HTML

En Cloud Run también se puede forzar dry-run con RESULTADO_MENSUAL_EMAIL_DRY_RUN=true (además
del flag --dry-run) -- un Job no recibe argumentos de línea de comandos.
"""

import argparse
import base64
import datetime
import os

from dotenv import load_dotenv
from google.cloud import bigquery

from config import (
    EMAIL_ASUNTO_TEMPLATE, FIRESTORE_DATABASE_ID,
    FIRESTORE_LISTS_COLLECTION, OUTPUT_DIR, PROJECT_ID, RESULTADO_MENSUAL_LIST_ID, SOCIEDADES,
    COLORS, FILTRAR_SOCIEDADES_SIN_ACTIVIDAD_RECIENTE,
)
from datos import fetch_resultado_mensual
from graficos import build_chart_mensual
from pdf import _money, _pct

# Carga el .env de ESTA carpeta -- el usuario debe crearlo (ver .env.example), no se copia la
# API key de otra carpeta automáticamente.
load_dotenv()

SENDGRID_FROM_EMAIL_DEFAULT = "noreply@proan.com"
CHART_CID = "grafico_resultado_mensual"


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


_MESES_ES = ["", "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
             "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]


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
    return get_mailing_list(RESULTADO_MENSUAL_LIST_ID), "firestore"


def _mes_str(fecha):
    return f"{_MESES_ES[fecha.month]} {fecha.year}"


def _signo_color(v):
    if v != v:
        return COLORS["muted"]
    return COLORS["good"] if v >= 0 else COLORS["critical"]


def _color_valor_estatus(valor, estatus):
    if estatus in ("PROVISIONAL", "SIN_REFERENCIA"):
        return COLORS["text_secondary"]
    return _signo_color(valor)


def _icono_estatus(estatus):
    if estatus == "PROVISIONAL":
        return f'<span style="color:{COLORS["provisional_text"]};font-size:10px;">&#9650;</span> '  # ▲
    if estatus == "SIN_REFERENCIA":
        return f'<span style="color:{COLORS["sin_referencia_text"]};font-size:10px;">&#9679;</span> '  # ●
    return ""


def _card_html(label, value, color_hex):
    return f"""
      <td width="25%" style="padding:5px;">
        <table width="100%" cellpadding="0" cellspacing="0" style="background:{COLORS['tile_bg']};border-radius:8px;">
          <tr><td style="padding:12px 12px;">
            <div style="font-family:'Segoe UI',Arial,sans-serif;font-size:9px;font-weight:700;color:{COLORS['muted']};text-transform:uppercase;letter-spacing:.3px;margin:0 0 6px;">{label}</div>
            <div style="font-family:'Segoe UI',Arial,sans-serif;font-size:17px;font-weight:800;color:{color_hex};">{value}</div>
          </td></tr>
        </table>
      </td>"""


def _fila_html(r):
    sig = COLORS["good"] if r["resultado_m2"] >= 0 else COLORS["critical"]
    return f"""
      <tr>
        <td style="padding:6px 8px;border-left:3px solid {sig};font-family:'Segoe UI',Arial,sans-serif;font-size:11px;color:{COLORS['text_primary']};">{r['nombre_sociedad']}</td>
        <td style="padding:6px 8px;font-family:'Courier New',monospace;font-size:10.5px;color:{COLORS['text_secondary']};text-align:right;">{_money(r['ing_m1'])}</td>
        <td style="padding:6px 8px;font-family:'Courier New',monospace;font-size:10.5px;color:{COLORS['text_secondary']};text-align:right;">{_money(r['egr_m1'])}</td>
        <td style="padding:6px 8px;font-family:'Courier New',monospace;font-size:10.5px;color:{_color_valor_estatus(r['resultado_m1'], r['estatus_m1'])};text-align:right;">{_icono_estatus(r['estatus_m1'])}{_money(r['resultado_m1'])}</td>
        <td style="padding:6px 8px;font-family:'Courier New',monospace;font-size:10.5px;color:{COLORS['text_secondary']};text-align:right;">{_money(r['ing_m2'])}</td>
        <td style="padding:6px 8px;font-family:'Courier New',monospace;font-size:10.5px;color:{COLORS['text_secondary']};text-align:right;">{_money(r['egr_m2'])}</td>
        <td style="padding:6px 8px;font-family:'Courier New',monospace;font-size:10.5px;color:{_signo_color(r['resultado_m2'])};text-align:right;">{_money(r['resultado_m2'])}</td>
        <td style="padding:6px 8px 6px 8px;font-family:'Courier New',monospace;font-size:10.5px;font-weight:700;color:{_signo_color(r['pct_variacion'])};text-align:right;">{_pct(r['pct_variacion'])}</td>
      </tr>"""


def _tabla_html(df, mes1_str, mes2_str):
    df_ordenado = df.sort_values("nombre_sociedad")
    filas = "".join(_fila_html(r) for _, r in df_ordenado.iterrows())
    totales = {c: df[c].sum() for c in ("ing_m1", "egr_m1", "resultado_m1", "ing_m2", "egr_m2", "resultado_m2")}
    diferencia_total = totales["resultado_m2"] - totales["resultado_m1"]
    pct_total = diferencia_total / abs(totales["resultado_m1"]) if abs(totales["resultado_m1"]) >= 1000 else (1.0 if diferencia_total >= 0 else -1.0)
    fila_total = f"""
      <tr style="background:{COLORS['tile_bg']};">
        <td style="padding:8px;font-family:'Segoe UI',Arial,sans-serif;font-size:11px;font-weight:800;color:{COLORS['text_primary']};">TOTAL GENERAL</td>
        <td style="padding:8px;font-family:'Courier New',monospace;font-size:10.5px;font-weight:700;text-align:right;">{_money(totales['ing_m1'])}</td>
        <td style="padding:8px;font-family:'Courier New',monospace;font-size:10.5px;font-weight:700;text-align:right;">{_money(totales['egr_m1'])}</td>
        <td style="padding:8px;font-family:'Courier New',monospace;font-size:10.5px;font-weight:700;text-align:right;">{_money(totales['resultado_m1'])}</td>
        <td style="padding:8px;font-family:'Courier New',monospace;font-size:10.5px;font-weight:700;text-align:right;">{_money(totales['ing_m2'])}</td>
        <td style="padding:8px;font-family:'Courier New',monospace;font-size:10.5px;font-weight:700;text-align:right;">{_money(totales['egr_m2'])}</td>
        <td style="padding:8px;font-family:'Courier New',monospace;font-size:10.5px;font-weight:700;text-align:right;">{_money(totales['resultado_m2'])}</td>
        <td style="padding:8px;font-family:'Courier New',monospace;font-size:10.5px;font-weight:800;color:{_signo_color(pct_total)};text-align:right;">{_pct(pct_total)}</td>
      </tr>"""
    header = ["Sociedad", f"Ingresos {mes1_str}", f"Egresos {mes1_str}", f"Resultado {mes1_str}",
              f"Ingresos {mes2_str}", f"Egresos {mes2_str}", f"Resultado {mes2_str}*", "% Variación"]
    ths = "".join(
        f'<td style="padding:8px;font-family:\'Segoe UI\',Arial,sans-serif;font-size:10px;font-weight:700;color:#ffffff;{"text-align:right;" if i else ""}">{h}</td>'
        for i, h in enumerate(header)
    )
    return f"""
      <table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;border:1px solid {COLORS['kpi_border']};">
        <tr style="background:{COLORS['header_bg']};">{ths}</tr>
        {filas}
        {fila_total}
      </table>"""


def build_email_html(df, mes1_str, mes2_str, fecha_str, chart_src):
    total_m1 = df["resultado_m1"].sum()
    total_m2 = df["resultado_m2"].sum()
    pct_total = (total_m2 - total_m1) / abs(total_m1) if abs(total_m1) >= 1000 else (1.0 if total_m2 >= total_m1 else -1.0)
    n_provisional_m2 = int((df["estatus_m2"] == "PROVISIONAL").sum())

    cards = "".join([
        _card_html(f"Resultado {mes1_str}", _money(total_m1), _signo_color(total_m1)),
        _card_html(f"Resultado {mes2_str}", _money(total_m2), _signo_color(total_m2)),
        _card_html("% Variación total", _pct(pct_total), _signo_color(pct_total)),
        _card_html(f"Con {mes2_str} en revisión", str(n_provisional_m2), COLORS["text_primary"]),
    ])

    return f"""<!DOCTYPE html>
<html lang="es"><head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:{COLORS['surface']};font-family:'Segoe UI',Arial,sans-serif;color:{COLORS['text_primary']};">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:{COLORS['surface']};padding:24px 12px;">
    <tr><td align="center">
      <table width="900" cellpadding="0" cellspacing="0"
             style="background:#ffffff;border-radius:12px;overflow:hidden;border:1px solid {COLORS['grid']};max-width:900px;width:100%;">
        <tr><td style="background:{COLORS['header_bg']};padding:22px 28px;border-top:4px solid {COLORS['header_accent']};">
          <div style="font-family:'Segoe UI',Arial,sans-serif;font-size:19px;font-weight:800;color:#ffffff;">
            Resultado Financiero Mensual PROAN
          </div>
          <div style="font-family:'Segoe UI',Arial,sans-serif;font-size:12px;color:#c9d6e5;margin-top:4px;">
            Ingresos, Egresos y Resultado por sociedad -- {mes1_str} / {mes2_str} (ambos cerrados) | Generado {fecha_str}
          </div>
        </td></tr>
        <tr><td style="padding:18px 24px 4px;">
          <table width="100%" cellpadding="0" cellspacing="0"><tr>{cards}</tr></table>
        </td></tr>
        <tr><td style="padding:14px 24px 4px;">
          <img src="{chart_src}" width="850"
               style="width:100%;max-width:850px;display:block;border-radius:6px;border:1px solid {COLORS['grid']};"
               alt="Resultado por sociedad -- últimos 2 meses">
        </td></tr>
        <tr><td style="padding:16px 24px 4px;">
          {_tabla_html(df, mes1_str, mes2_str)}
        </td></tr>
        <tr><td style="padding:14px 24px 4px;">
          <p style="font-family:'Segoe UI',Arial,sans-serif;font-size:10.5px;font-weight:700;color:{COLORS['text_secondary']};margin:0 0 6px;line-height:1.5;">
            * Cifras de {mes2_str} preliminares -- el mes cerró recientemente y SAP puede seguir recibiendo ajustes en las próximas semanas.
          </p>
          <p style="font-family:'Segoe UI',Arial,sans-serif;font-size:10.5px;color:{COLORS['muted']};margin:0 0 4px;line-height:1.5;">
            <span style="color:{COLORS['provisional_text']};">&#9650;</span> (en la columna Resultado {mes1_str}) PROVISIONAL: el mes cerró recientemente y SAP puede seguir recibiendo ajustes -- esta cifra no es definitiva.
          </p>
          <p style="font-family:'Segoe UI',Arial,sans-serif;font-size:10.5px;color:{COLORS['muted']};margin:0;line-height:1.5;">
            <span style="color:{COLORS['sin_referencia_text']};">&#9679;</span> (en la columna Resultado {mes1_str}) SIN_REFERENCIA: no había snapshot disponible para esa sociedad/mes -- no se pudo verificar si es estable.
          </p>
        </td></tr>
        <tr><td style="padding:16px 24px 24px;border-top:1px solid {COLORS['grid']};">
          <p style="font-family:'Segoe UI',Arial,sans-serif;font-size:11px;color:{COLORS['muted']};margin:0;line-height:1.5;">
            Vista previa manual -- no conectado a Cloud Run/Scheduler todavía. El PDF adjunto trae el mismo detalle.
          </p>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body></html>"""


def enviar(pdf_path, destinatario_override=None, dry_run_override=False):
    if not os.path.exists(pdf_path):
        raise FileNotFoundError(f"No se encontró el PDF: {pdf_path}")

    hoy = datetime.date.today()
    fecha_str = hoy.strftime("%d/%m/%Y")
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
              f"Firestore lists/{RESULTADO_MENSUAL_LIST_ID} (campos enabled / emails).")
        return

    dry_run_env = os.environ.get("RESULTADO_MENSUAL_EMAIL_DRY_RUN", "false").strip().lower() in {
        "1", "true", "yes",
    }
    dry_run = dry_run_override or dry_run_env

    client = bigquery.Client(project=PROJECT_ID)
    _, snapshot_table, df = fetch_resultado_mensual(client, hoy, SOCIEDADES)
    if FILTRAR_SOCIEDADES_SIN_ACTIVIDAD_RECIENTE:
        sin_actividad = df[df[["ing_m1", "egr_m1", "ing_m2", "egr_m2"]].isna().all(axis=1)]
        df = df.drop(sin_actividad.index).reset_index(drop=True)

    mes1_str = _mes_str(df["mes1"].iloc[0])
    mes2_str = _mes_str(df["mes2"].iloc[0])
    asunto = EMAIL_ASUNTO_TEMPLATE.format(mes1_str=mes1_str, mes2_str=mes2_str)
    cuerpo_texto_plano = (
        f"Hola Luis Enrique,\n\n"
        f"Adjunto el Resultado Financiero Mensual PROAN de {mes1_str} y {mes2_str} (ambos "
        f"meses ya cerrados): Ingresos, Egresos y Resultado por sociedad. El mismo detalle "
        f"está también en el cuerpo de este correo.\n\n"
        f"Los 2 meses llevan chequeo de estabilidad contra un snapshot de ~14 días atrás -- "
        f"la marca ▲ junto al Resultado significa PROVISIONAL (el mes puede seguir moviéndose),"
        f" ● significa SIN_REFERENCIA (no había snapshot con qué comparar).\n\n"
        f"Nota: vista previa manual, no conectado a Cloud Run ni a un horario automático "
        f"todavía.\n\nSaludos."
    )

    chart_path = os.path.join(OUTPUT_DIR, "_chart_resultado_mensual.png")
    build_chart_mensual(df, mes1_str, mes2_str, chart_path)

    if dry_run:
        chart_src = "file:///" + os.path.abspath(chart_path).replace("\\", "/")
        html_preview = build_email_html(df, mes1_str, mes2_str, fecha_str, chart_src)
        preview_path = os.path.join(OUTPUT_DIR, "_preview_email_resultado_mensual.html")
        with open(preview_path, "w", encoding="utf-8") as f:
            f.write(html_preview)
        print(f"[DRY RUN] De: {from_email}  Para (To): {from_email}  Cc: {recipients}")
        print(f"[DRY RUN] Asunto: {asunto}")
        print(f"[DRY RUN] Adjunto PDF: {pdf_path}")
        print(f"[DRY RUN] Vista previa del HTML guardada en: {preview_path}")
        print("[DRY RUN] No se envió ningún correo real.")
        return

    html_body = build_email_html(df, mes1_str, mes2_str, fecha_str, f"cid:{CHART_CID}")

    import sendgrid
    from sendgrid.helpers.mail import (
        Attachment, Cc, ContentId, Disposition, FileContent, FileName, FileType, Mail,
    )

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

    with open(chart_path, "rb") as f:
        chart_bytes = f.read()
    message.add_attachment(Attachment(
        FileContent(base64.b64encode(chart_bytes).decode()),
        FileName(os.path.basename(chart_path)),
        FileType("image/png"),
        Disposition("inline"),
        ContentId(CHART_CID),
    ))

    api_key = os.environ["SENDGRID_API_KEY"]
    sg_client = sendgrid.SendGridAPIClient(api_key)
    response = sg_client.send(message)
    print(f"SendGrid respondió con status {response.status_code}")
    return response


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--to", default=None,
                         help="Override de destinatario para pruebas locales -- salta la "
                              "lista de Firestore")
    parser.add_argument("--pdf", default=None, help="Ruta al PDF a enviar")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    hoy = datetime.date.today()
    pdf_path = args.pdf or os.path.join(
        OUTPUT_DIR, f"resultado_financiero_mensual_{hoy.isoformat()}.pdf"
    )
    if not os.path.exists(pdf_path):
        raise FileNotFoundError(
            f"No se encontró {pdf_path}. Corre primero: python generar_reporte.py"
        )

    enviar(pdf_path, destinatario_override=args.to, dry_run_override=args.dry_run)
    if not args.dry_run:
        print(f"Reporte enviado: {pdf_path}")


if __name__ == "__main__":
    main()
