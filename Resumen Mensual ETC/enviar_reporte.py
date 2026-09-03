"""Envía por correo el Resumen Ejecutivo Mensual de ETC.

El diseño (mockup_resumen_mensual.html) usa flexbox, variables CSS y conic-gradient para el
donut -- nada de eso es email-safe (Outlook lo ignora por completo). En vez de mandar el
HTML crudo, se renderiza a UNA imagen PNG (ver render_png.py, Chrome headless) incrustada en
el cuerpo vía cid (Content-ID, adjunto MIME "inline") + un PDF de una sola página adjunto
con el mismo contenido (texto vectorial, ver generar_reporte_completo).

**2026-09-03: se probó cambiar la imagen a data: URI** (base64 directo en el HTML, sin
adjunto aparte) para que se viera "nada más abrir el correo" sin depender de que el cliente
cargue un adjunto -- NO funcionó, y casi seguro por la misma razón ya documentada en
"Reportes diarios contables/enviar_reporte.py": Gmail recorta el cuerpo del correo si el
HTML supera ~102 KB. Con data: URI los ~650 KB de la imagen en base64 pasan a ser parte del
HTML mismo, muy por encima del límite -- Gmail probablemente recortaba el mensaje. Con cid:
la imagen es un adjunto aparte (no cuenta para ese límite de 102 KB del HTML) y sí funcionó.
NO volver a usar data: URI para imágenes de este tamaño sin resolver antes el límite de
Gmail.

**Mismo día, segundo hallazgo:** con cid SÍ llega, pero Gmail lo muestra colapsado detrás
de un "Mostrar contenido reducido" -- confirmado por búsqueda web (no solo el límite de
102 KB del *cuerpo* HTML: Gmail también colapsa mensajes con imágenes/adjuntos pesados en
general, aunque el HTML del cuerpo sea chico). Se redujo el peso de la imagen incrustada
cuantizándola a 256 colores en render_png.py (489 KB -> 193 KB, idéntica a simple vista --
el diseño es color plano + texto, no foto) para bajar el peso total del correo.

Misma infraestructura de envío que los demás reportes financieros de este repo (SendGrid,
.env propio de esta carpeta, Firestore como única fuente de destinatarios) -- ver
"Resultado Financiero Mensual/enviar_reporte.py", de donde se copió el patrón a pedido
explícito del usuario (2026-09-03). get_mailing_list() está duplicada aquí a propósito
(cada carpeta es autónoma para su propio build de Docker, ver README del repo).

Uso:
    python enviar_reporte.py                        # mes cerrado más reciente, lista de Firestore
    python enviar_reporte.py --mes 2026-08           # fuerza un mes (pruebas)
    python enviar_reporte.py --to correo@destino.com # override de destinatario, salta Firestore
    python enviar_reporte.py --dry-run               # no envía; guarda una vista previa

En Cloud Run también se puede forzar dry-run con RESUMEN_MENSUAL_ETC_EMAIL_DRY_RUN=true
(además del flag --dry-run) -- un Job no recibe argumentos de línea de comandos.
"""

import argparse
import base64
import datetime
import os

from dotenv import load_dotenv

from config import (
    COLORS, EMAIL_ASUNTO_TEMPLATE, EMPRESA_NOMBRE, FIRESTORE_DATABASE_ID,
    FIRESTORE_LISTS_COLLECTION, PROJECT_ID, RESUMEN_MENSUAL_ETC_LIST_ID,
)
from resumen_mensual_etc import generar_reporte_completo

load_dotenv()

SENDGRID_FROM_EMAIL_DEFAULT = "noreply@proan.com"
IMAGEN_CID = "resumen_mensual_etc"


# --- Destinatarios: lista administrada en Firestore -------------------------------------

def _normalize_recipients(raw_recipients):
    recipients, seen = [], set()
    for raw in raw_recipients:
        email = str(raw or "").strip()
        key = email.lower()
        if email and key not in seen:
            seen.add(key)
            recipients.append(email)
    return recipients


def get_mailing_list(list_id):
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

    recipients = _normalize_recipients([str(e) for e in emails])
    if not recipients:
        print(f"[recipients] ADVERTENCIA: la lista {list_id} no tiene ningún correo válido")
    return recipients


def resolve_email_recipients():
    return get_mailing_list(RESUMEN_MENSUAL_ETC_LIST_ID), "firestore"


# --- Cuerpo del correo: wrapper simple (a prueba de Outlook) + la imagen del reporte ------

def build_email_html(img_src, mes_nombre, anio):
    return f"""<!DOCTYPE html>
<html lang="es"><head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:{COLORS['paper']};font-family:'Segoe UI',Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:{COLORS['paper']};padding:24px 12px;">
    <tr><td align="center">
      <table width="1040" cellpadding="0" cellspacing="0" style="max-width:1040px;width:100%;">
        <tr><td style="padding:0 0 14px;">
          <p style="font-family:'Segoe UI',Arial,sans-serif;font-size:12px;color:{COLORS['muted']};margin:0;">
            Resumen Ejecutivo Mensual — {EMPRESA_NOMBRE} — {mes_nombre} {anio}
          </p>
        </td></tr>
        <tr><td>
          <img src="{img_src}" width="1040"
               style="width:100%;max-width:1040px;display:block;border-radius:6px;border:1px solid {COLORS['line']};"
               alt="Resumen Ejecutivo Mensual {EMPRESA_NOMBRE} — {mes_nombre} {anio}">
        </td></tr>
      </table>
    </td></tr>
  </table>
</body></html>"""


def _plain_text(contexto):
    k = {kpi["label"]: kpi for kpi in contexto["kpis"]}
    return (
        f"Resumen Ejecutivo Mensual {EMPRESA_NOMBRE} — {contexto['mes_nombre']} {contexto['anio']}\n\n"
        f"Ingresos Totales: {k['Ingresos Totales']['valor']}\n"
        f"Gastos Totales: {k['Gastos Totales']['valor']}\n"
        f"Utilidad Neta: {k['Utilidad Neta']['valor']} ({k['Utilidad Neta']['valor2']})\n\n"
        "El reporte completo (gráficos, rentabilidad por segmento, composición de ingresos, "
        "origen y aplicación de recursos) está incrustado en este correo -- si tu cliente de "
        "correo no muestra HTML (ej. Outlook clásico), el mismo contenido está en el PDF "
        "adjunto."
    )


def enviar(mes_forzado=None, destinatario_override=None, dry_run_override=False):
    from_email = os.environ.get("SENDGRID_FROM_EMAIL", SENDGRID_FROM_EMAIL_DEFAULT)

    if destinatario_override:
        recipients = _normalize_recipients([destinatario_override])
        recipients_source = "override (--to, cascada omitida)"
    else:
        recipients, recipients_source = resolve_email_recipients()
    print(f"Destinatarios resueltos desde {recipients_source}: {recipients}")

    if not recipients:
        print("[recipients] Sin destinatarios: no se envía el correo. Revisa el documento "
              f"Firestore lists/{RESUMEN_MENSUAL_ETC_LIST_ID} (campos enabled / emails).")
        return

    dry_run_env = os.environ.get("RESUMEN_MENSUAL_ETC_EMAIL_DRY_RUN", "false").strip().lower() in {
        "1", "true", "yes",
    }
    dry_run = dry_run_override or dry_run_env

    html_path, png_path, pdf_path, contexto, mes_cerrado = generar_reporte_completo(mes_forzado)
    asunto = EMAIL_ASUNTO_TEMPLATE.format(mes_nombre=contexto["mes_nombre"], anio=contexto["anio"])
    cuerpo_texto_plano = _plain_text(contexto)

    if dry_run:
        img_src = "file:///" + os.path.abspath(png_path).replace("\\", "/")
        html_preview = build_email_html(img_src, contexto["mes_nombre"], contexto["anio"])
        preview_path = os.path.join(os.path.dirname(png_path), "_preview_email_resumen_mensual_etc.html")
        with open(preview_path, "w", encoding="utf-8") as f:
            f.write(html_preview)
        print(f"[DRY RUN] De: {from_email}  Para (To): {from_email}  Cc: {recipients}")
        print(f"[DRY RUN] Asunto: {asunto}")
        print(f"[DRY RUN] Imagen incrustada (cid en el envío real): {png_path}")
        print(f"[DRY RUN] PDF adjunto: {pdf_path}")
        print(f"[DRY RUN] Vista previa del HTML guardada en: {preview_path}")
        print("[DRY RUN] No se envió ningún correo real.")
        return

    html_body = build_email_html(f"cid:{IMAGEN_CID}", contexto["mes_nombre"], contexto["anio"])

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

    with open(png_path, "rb") as f:
        png_bytes = f.read()
    message.add_attachment(Attachment(
        FileContent(base64.b64encode(png_bytes).decode()),
        FileName(os.path.basename(png_path)),
        FileType("image/png"),
        Disposition("inline"),
        ContentId(IMAGEN_CID),
    ))

    with open(pdf_path, "rb") as f:
        pdf_bytes = f.read()
    message.add_attachment(Attachment(
        FileContent(base64.b64encode(pdf_bytes).decode()),
        FileName(os.path.basename(pdf_path)),
        FileType("application/pdf"),
        Disposition("attachment"),
    ))

    api_key = os.environ["SENDGRID_API_KEY"]
    sg_client = sendgrid.SendGridAPIClient(api_key)
    response = sg_client.send(message)
    print(f"SendGrid respondió con status {response.status_code}")
    return response


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mes", default=None, help="Forzar el mes a reportar, formato YYYY-MM")
    parser.add_argument("--to", default=None,
                         help="Override de destinatario para pruebas locales -- salta Firestore")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    mes_forzado = None
    if args.mes:
        anio, mes = args.mes.split("-")
        mes_forzado = datetime.date(int(anio), int(mes), 1)

    enviar(mes_forzado, destinatario_override=args.to, dry_run_override=args.dry_run)
    if not args.dry_run:
        print("Reporte enviado.")


if __name__ == "__main__":
    main()
