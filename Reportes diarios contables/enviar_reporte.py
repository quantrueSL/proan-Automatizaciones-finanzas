"""Envía por correo el reporte diario: PDF adjunto (detalle completo) + un resumen
visual en el propio cuerpo del correo (cards de totales + gráfico embebido por sección),
para que se pueda ver de un vistazo en Gmail sin abrir el adjunto.

Usa la API de SendGrid, igual que la automatización de Cambio de Divisa
(ver "Cambio divisa/divisa.py"), en vez de SMTP con contraseña de aplicación de
Office 365 (bloqueada mientras no se configure una app password ahí).

No duplica cálculos: reutiliza fetch_cuenta/fetch_descuentos (datos.py),
build_chart/build_chart_descuentos (graficos.py) y _money/_pct (pdf.py) — las mismas
funciones que ya arman las cards y los gráficos del PDF. El PDF en sí no se toca aquí,
solo se adjunta.

Uso:
    python enviar_reporte.py                          # envía el reporte de hoy
    python enviar_reporte.py --pdf ruta\al\reporte.pdf # envía un PDF específico
    python enviar_reporte.py --to otro@correo.com      # cambia el destinatario
    python enviar_reporte.py --dry-run                 # no envía nada; guarda una
                                                        # vista previa del HTML en OUTPUT_DIR

Requiere credenciales de SendGrid en variables de entorno (ver .env.example):
    SENDGRID_API_KEY, SENDGRID_FROM_EMAIL (opcional)
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
    COLORS, CUENTAS, CUENTAS_ACTIVAS, CUENTAS_SOLO_DEBE, EMAIL_ASUNTO_TEMPLATE,
    EMAIL_CUERPO_TEMPLATE, EMAIL_DESTINATARIO_DEFAULT, OUTPUT_DIR, PROJECT_ID, SOCIEDADES,
)
from datos import fetch_cuenta, fetch_descuentos, fetch_sociedades
from graficos import build_chart, build_chart_descuentos
from pdf import _money, _pct

load_dotenv()

SENDGRID_FROM_EMAIL_DEFAULT = "noreply@proan.com"


def _slug(nombre):
    sin_acentos = "".join(
        c for c in unicodedata.normalize("NFKD", nombre) if not unicodedata.combining(c)
    )
    return re.sub(r"[^a-z0-9]+", "_", sin_acentos.lower()).strip("_")


def _color_por_signo(v):
    if v != v:  # NaN
        return COLORS["muted"]
    return COLORS["good"] if v >= 0 else COLORS["critical"]


def _preparar_resumenes(client, hoy):
    """Reconstruye, con las mismas funciones que usa generar_reporte.py, el resumen
    (cards + gráfico) de cada sección del PDF. Devuelve una lista de dicts:
    {titulo, cards: [(label, value, color_hex)], chart_path, cid}."""
    current_year = hoy.year
    prior_year = current_year - 1
    hist_years = list(range(current_year - 4, current_year + 1))
    sociedades = fetch_sociedades(client)

    secciones = []
    for nombre_cuenta in CUENTAS_ACTIVAS:
        raccts = CUENTAS[nombre_cuenta]
        _, df = fetch_cuenta(client, raccts, hist_years, current_year, prior_year, sociedades,
                              solo_debe=nombre_cuenta in CUENTAS_SOLO_DEBE)

        chart_path = os.path.join(OUTPUT_DIR, f"_chart_{nombre_cuenta.replace(' ', '_')}.png")
        build_chart(df, nombre_cuenta, current_year, prior_year, chart_path)

        total_actual = df["actual"].sum()
        total_anterior = df["anterior"].sum()
        diferencia = total_actual - total_anterior
        cards = [
            (f"Total {current_year} (hoy)", _money(total_actual), COLORS["header_bg"]),
            (f"Total {prior_year}", _money(total_anterior), COLORS["header_bg"]),
            ("Diferencia total", _money(diferencia), _color_por_signo(diferencia)),
        ]
        secciones.append({
            "titulo": nombre_cuenta,
            "cards": cards,
            "chart_path": chart_path,
            "cid": f"grafico_{_slug(nombre_cuenta)}",
        })

    df_desc = fetch_descuentos(client, current_year, prior_year, SOCIEDADES)[1]
    chart_path_desc = os.path.join(OUTPUT_DIR, "_chart_Descuentos_y_Bonificaciones.png")
    build_chart_descuentos(df_desc, current_year, prior_year, chart_path_desc)

    ingresos_total = df_desc["ingresos_actual"].sum()
    descuentos_total = df_desc["descuentos_actual"].sum()
    pct_global = (descuentos_total / ingresos_total) if ingresos_total else float("nan")
    secciones.append({
        "titulo": "Descuentos y Bonificaciones",
        "cards": [
            (f"Ingresos totales {current_year} (hoy)", _money(ingresos_total), COLORS["header_bg"]),
            (f"Descuentos totales {current_year} (hoy)", _money(descuentos_total), COLORS["header_bg"]),
            ("% Global (Descuentos/Ingresos)", _pct(pct_global), COLORS["header_bg"]),
        ],
        "chart_path": chart_path_desc,
        "cid": "grafico_descuentos_y_bonificaciones",
    })

    # Variación de Precios: mismo mecanismo que CUENTAS_ACTIVAS (fetch_cuenta + build_chart),
    # pero usa SOCIEDADES (no dm_company) y se agrega al final, después de Descuentos, para
    # que el orden coincida con el del PDF (ver nota de validación en config.py).
    raccts_precios = CUENTAS["Variación de Precios"]
    _, df_precios = fetch_cuenta(client, raccts_precios, hist_years, current_year, prior_year, SOCIEDADES)
    chart_path_precios = os.path.join(OUTPUT_DIR, "_chart_Variacion_de_Precios.png")
    build_chart(df_precios, "Variación de Precios", current_year, prior_year, chart_path_precios)

    total_actual_precios = df_precios["actual"].sum()
    total_anterior_precios = df_precios["anterior"].sum()
    # Mismo patrón de cards que Gastos no Deducibles (formato único): diferencia = actual - anterior.
    diferencia_precios = total_actual_precios - total_anterior_precios
    secciones.append({
        "titulo": "Variación de Precios",
        "cards": [
            (f"Total {current_year} (hoy)", _money(total_actual_precios), COLORS["header_bg"]),
            (f"Total {prior_year}", _money(total_anterior_precios), COLORS["header_bg"]),
            ("Diferencia total", _money(diferencia_precios), _color_por_signo(diferencia_precios)),
        ],
        "chart_path": chart_path_precios,
        "cid": "grafico_variacion_de_precios",
    })
    return secciones


def _card_html(label, value, color_hex):
    return f"""
      <td width="33%" style="padding:5px;">
        <table width="100%" cellpadding="0" cellspacing="0" style="background:{COLORS['tile_bg']};border-radius:8px;">
          <tr><td style="padding:14px 14px;">
            <div style="font-family:'Segoe UI',Arial,sans-serif;font-size:9.5px;font-weight:700;color:{COLORS['muted']};text-transform:uppercase;letter-spacing:.4px;margin:0 0 6px;">{label}</div>
            <div style="font-family:'Segoe UI',Arial,sans-serif;font-size:18px;font-weight:800;color:{color_hex};">{value}</div>
          </td></tr>
        </table>
      </td>"""


def _seccion_html(seccion, src_img):
    cards_html = "".join(_card_html(label, value, color) for label, value, color in seccion["cards"])
    return f"""
        <tr><td style="padding:22px 28px 4px;">
          <div style="font-family:'Segoe UI',Arial,sans-serif;font-size:15px;font-weight:800;
                      color:{COLORS['header_bg']};border-left:4px solid {COLORS['header_accent']};
                      padding-left:10px;margin:0 0 12px;">{seccion['titulo'].upper()}</div>
          <table width="100%" cellpadding="0" cellspacing="0"><tr>{cards_html}</tr></table>
          <div style="margin-top:12px;">
            <img src="{src_img}" width="620"
                 style="width:100%;max-width:620px;display:block;border-radius:6px;border:1px solid {COLORS['grid']};"
                 alt="{seccion['titulo']}">
          </div>
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
<html lang="es"><head><meta charset="UTF-8"></head>
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
            El detalle completo por sociedad está en el PDF adjunto.
          </p>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body></html>"""


def enviar_reporte(pdf_path, destinatario, dry_run=False):
    if not os.path.exists(pdf_path):
        raise FileNotFoundError(f"No se encontró el PDF: {pdf_path}")

    hoy = datetime.date.today()
    fecha_str = hoy.strftime("%d/%m/%Y")
    asunto = EMAIL_ASUNTO_TEMPLATE.format(fecha=fecha_str)
    cuerpo_texto_plano = EMAIL_CUERPO_TEMPLATE.format(fecha=fecha_str)
    from_email = os.environ.get("SENDGRID_FROM_EMAIL", SENDGRID_FROM_EMAIL_DEFAULT)

    client = bigquery.Client(project=PROJECT_ID)
    secciones = _preparar_resumenes(client, hoy)

    if dry_run:
        html_preview = build_email_html(fecha_str, secciones, use_cid=False)
        preview_path = os.path.join(OUTPUT_DIR, "_preview_email.html")
        with open(preview_path, "w", encoding="utf-8") as f:
            f.write(html_preview)
        print(f"[DRY RUN] De: {from_email}  Para: {destinatario}")
        print(f"[DRY RUN] Asunto: {asunto}")
        print(f"[DRY RUN] Adjunto PDF: {pdf_path}")
        print(f"[DRY RUN] Secciones en el cuerpo: {', '.join(s['titulo'] for s in secciones)}")
        print(f"[DRY RUN] Vista previa del HTML guardada en: {preview_path} (ábrela en el navegador)")
        print("[DRY RUN] No se envió ningún correo real (SendGrid no fue invocado).")
        return

    html_body = build_email_html(fecha_str, secciones, use_cid=True)

    api_key = os.environ["SENDGRID_API_KEY"]

    import sendgrid
    from sendgrid.helpers.mail import Attachment, ContentId, Disposition, FileContent, FileName, FileType, Mail

    message = Mail(
        from_email=from_email,
        to_emails=destinatario,
        subject=asunto,
        plain_text_content=cuerpo_texto_plano,
        html_content=html_body,
    )

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
    parser.add_argument("--to", default=EMAIL_DESTINATARIO_DEFAULT, help="Correo destinatario")
    parser.add_argument("--dry-run", action="store_true",
                         help="No envía el correo; guarda una vista previa del HTML")
    args = parser.parse_args()

    pdf_path = args.pdf or os.path.join(
        OUTPUT_DIR, f"reporte_cuentas_proan_{datetime.date.today().isoformat()}.pdf"
    )

    enviar_reporte(pdf_path, args.to, dry_run=args.dry_run)
    if not args.dry_run:
        print(f"Reporte enviado a {args.to}: {pdf_path}")


if __name__ == "__main__":
    main()
