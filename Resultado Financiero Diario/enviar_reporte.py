"""Envía por correo el "Resultado Financiero diario" premium (rediseño 2026-08-07): PDF
adjunto (detalle completo, igual al que genera generar_reporte.py) + el mismo contenido
visible directamente en el CUERPO del correo -- header con logo, tarjetas KPI, gráfico (si
hay diferencias), tarjeta de estado, tabla con iconos y color por signo, insights, footer.

Límites reales de un correo HTML (avisado al usuario en el chat, no se finge lo contrario):
- Hover en filas de tabla: funciona en Gmail web/app y Apple Mail: Outlook de escritorio
  (motor Word) lo ignora sin romper nada -- degrada a "sin hover", no a un error visual.
- Sombras/blur tipo glassmorphism: box-shadow se ve en la mayoría de clientes modernos;
  backdrop-filter (blur real) NO tiene soporte fiable en email y no se usó.
- No hay botón "Actualizar" funcional: un correo no tiene backend detrás que lo ejecute.

No duplica cálculos: reutiliza fetch_resultado_financiero (datos.py), build_chart_top5
(graficos.py), build_kpis/build_insights (insights.py) y _money/_money_sin_decimales (pdf.py)
-- las mismas funciones que arman el PDF.

Uso:
    python enviar_reporte.py --to correo@destino.com
    python enviar_reporte.py --to correo@destino.com --dry-run   # no envía; guarda
                                                                  # una vista previa del HTML
"""

import argparse
import base64
import datetime
import os

from dotenv import load_dotenv
from google.cloud import bigquery

from config import (
    EMAIL_ASUNTO_TEMPLATE, EMAIL_DESTINATARIO_DEFAULT, OUTPUT_DIR, PROJECT_ID, SOCIEDADES,
    COLORS, TOLERANCIA_DIF_MXN, LOGO_PNG,
)
from datos import fetch_resultado_financiero
from graficos import build_chart_top5
from insights import build_kpis, build_insights
from pdf import _money, _money_sin_decimales

_SIBLING_ENV = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "Reportes diarios contables", ".env"
)
load_dotenv(_SIBLING_ENV)

SENDGRID_FROM_EMAIL_DEFAULT = "noreply@proan.com"
CHART_CID = "grafico_top5_resultado_financiero"
LOGO_CID = "logo_proan"

CUERPO_TEXTO_PLANO = (
    "Hola Luis Enrique,\n\n"
    "Adjunto el Resultado Financiero Diario PROAN correspondiente al {fecha}: cuadre por "
    "sociedad (Balance vs. Estado de Resultados). El mismo detalle está también en el cuerpo "
    "de este correo, no hace falta abrir el adjunto para verlo.\n\n"
    "Nota: este envío es una vista previa manual para revisar formato -- el cálculo todavía "
    "NO está validado contra SAP ZF01 en vivo (pendiente).\n\n"
    "Saludos."
)

def _badge_html(ok, size=16):
    """Círculo de color + carácter de texto (✓ / !) -- NO usa imágenes SVG en data: URI.
    El soporte de SVG y de data: URIs en clientes de correo es muy inconsistente (Outlook de
    escritorio en particular no renderiza casi ninguno de los dos, y se vería como un ícono
    roto); un carácter Unicode es solo texto, lo renderiza el tipo de letra del sistema del
    lector, funciona en cualquier cliente. border-radius:50% no lo respeta Outlook clásico
    (se ve como un cuadrado de color en vez de círculo) pero el color y el símbolo sí llegan
    -- degradación aceptable, nunca un ícono ausente."""
    color = COLORS["good"] if ok else COLORS["critical"]
    caracter = "&#10003;" if ok else "!"
    return (
        f'<span style="display:inline-block;width:{size}px;height:{size}px;line-height:{size}px;'
        f'border-radius:50%;background:{color};color:#ffffff;font-family:Arial,sans-serif;'
        f'font-weight:800;font-size:{int(size * 0.62)}px;text-align:center;">{caracter}</span>'
    )


def _kpi_card_html(label, value, value_color, icon_ok=None):
    icon_html = f'<span style="margin-left:6px;">{_badge_html(icon_ok, 15)}</span>' if icon_ok is not None else ""
    return f"""
      <td width="20%" style="padding:4px;">
        <table width="100%" cellpadding="0" cellspacing="0"
               style="background:{COLORS['surface']};border:1px solid {COLORS['border']};border-radius:10px;
                      box-shadow:0 1px 3px rgba(18,53,91,0.08);">
          <tr><td style="padding:12px 12px;">
            <div style="font-family:'Segoe UI',Arial,sans-serif;font-size:9px;font-weight:700;color:{COLORS['muted']};text-transform:uppercase;letter-spacing:.3px;margin:0 0 6px;">{label}</div>
            <div style="font-family:'Segoe UI',Arial,sans-serif;font-size:19px;font-weight:800;color:{value_color};">{value}{icon_html}</div>
          </td></tr>
        </table>
      </td>"""


def _kpi_row_html(kpis):
    estado_txt = "Conciliado" if kpis["conciliado"] else "Revisar"
    estado_color = COLORS["good"] if kpis["conciliado"] else COLORS["critical"]
    cards = [
        _kpi_card_html("Sociedades conciliadas", str(kpis["n_conciliadas"]), COLORS["good"], True),
        _kpi_card_html("Con diferencias", str(kpis["n_con_diferencias"]),
                       COLORS["critical"] if kpis["n_con_diferencias"] else COLORS["muted"],
                       False if kpis["n_con_diferencias"] else None),
        _kpi_card_html("Diferencia total", _money_sin_decimales(kpis["diferencia_total"]), COLORS["primary"]),
        _kpi_card_html("Mayor diferencia", _money_sin_decimales(kpis["mayor_diferencia"]), COLORS["primary"]),
        _kpi_card_html("Estado general", estado_txt, estado_color),
    ]
    return f'<table width="100%" cellpadding="0" cellspacing="0"><tr>{"".join(cards)}</tr></table>'


def _status_card_html(kpis, tolerancia):
    ok = kpis["conciliado"]
    bg = COLORS["good_bg"] if ok else COLORS["critical_bg"]
    accent = COLORS["good"] if ok else COLORS["critical"]
    icon = _badge_html(ok, 26)
    if ok:
        headline = "Todas las sociedades conciliaron correctamente."
        subtext = "No existen diferencias entre Balance y Estado de Resultados para la fecha seleccionada."
    else:
        headline = f"Se detectaron diferencias en {kpis['n_con_diferencias']} sociedad(es)."
        subtext = f"Fuera de tolerancia (+/- ${tolerancia:.2f}) -- requieren revisión, ver filas marcadas abajo."
    return f"""
      <table width="100%" cellpadding="0" cellspacing="0"
             style="background:{bg};border-left:4px solid {accent};border-radius:10px;">
        <tr>
          <td width="44" style="padding:14px 0 14px 14px;">{icon}</td>
          <td style="padding:14px 14px 14px 10px;">
            <div style="font-family:'Segoe UI',Arial,sans-serif;font-size:13.5px;font-weight:800;color:{COLORS['primary']};margin:0 0 3px;">{headline}</div>
            <div style="font-family:'Segoe UI',Arial,sans-serif;font-size:11.5px;color:{COLORS['text_secondary']};">{subtext}</div>
          </td>
        </tr>
      </table>"""


def _color_monto(v):
    return COLORS["critical"] if v < 0 else COLORS["text_secondary"]


def _fila_html(r, conciliada):
    dif_color = COLORS["good"] if conciliada else COLORS["critical"]
    # clase "fila-hover" -- ver <style> en build_email_html (Gmail web/Apple Mail sí aplican
    # :hover; Outlook de escritorio simplemente lo ignora, no rompe el layout).
    return f"""
      <tr class="fila-hover">
        <td style="padding:9px 8px 9px 12px;width:22px;">{_badge_html(conciliada, 13)}</td>
        <td style="padding:9px 10px;font-family:'Segoe UI',Arial,sans-serif;font-size:12px;color:{COLORS['text_secondary']};">{r['nombre_sociedad']}</td>
        <td style="padding:9px 10px;font-family:'Courier New',monospace;font-size:11.5px;color:{_color_monto(r['balance'])};text-align:right;">{_money_sin_decimales(r['balance'])}</td>
        <td style="padding:9px 10px;font-family:'Courier New',monospace;font-size:11.5px;color:{_color_monto(r['estado_resultados'])};text-align:right;">{_money_sin_decimales(r['estado_resultados'])}</td>
        <td style="padding:9px 12px 9px 10px;font-family:'Courier New',monospace;font-size:11.5px;color:{dif_color};font-weight:700;text-align:right;">{_money(r['dif'])}</td>
      </tr>"""


def _tabla_html(df, tolerancia):
    df_ordenado = df.sort_values("nombre_sociedad")
    filas = "".join(
        _fila_html(r, abs(r["dif"]) <= tolerancia) for _, r in df_ordenado.iterrows()
    )
    total_balance = df["balance"].sum()
    total_estado = df["estado_resultados"].sum()
    total_dif = df["dif"].sum()
    fila_total = f"""
      <tr>
        <td style="padding:10px 8px 10px 12px;background:{COLORS['support']};"></td>
        <td style="padding:10px;background:{COLORS['support']};font-family:'Segoe UI',Arial,sans-serif;font-size:12px;font-weight:800;color:{COLORS['primary']};">TOTAL GENERAL</td>
        <td style="padding:10px;background:{COLORS['support']};font-family:'Courier New',monospace;font-size:11.5px;font-weight:800;color:{COLORS['primary']};text-align:right;">{_money_sin_decimales(total_balance)}</td>
        <td style="padding:10px;background:{COLORS['support']};font-family:'Courier New',monospace;font-size:11.5px;font-weight:800;color:{COLORS['primary']};text-align:right;">{_money_sin_decimales(total_estado)}</td>
        <td style="padding:10px 12px 10px 10px;background:{COLORS['support']};font-family:'Courier New',monospace;font-size:11.5px;font-weight:800;color:{COLORS['primary']};text-align:right;">{_money(total_dif)}</td>
      </tr>"""
    return f"""
      <table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;border:1px solid {COLORS['border']};border-radius:10px;overflow:hidden;">
        <tr style="background:{COLORS['primary']};">
          <td style="padding:10px 8px 10px 12px;"></td>
          <td style="padding:10px;font-family:'Segoe UI',Arial,sans-serif;font-size:11px;font-weight:700;color:#ffffff;">SOCIEDAD</td>
          <td style="padding:10px;font-family:'Segoe UI',Arial,sans-serif;font-size:11px;font-weight:700;color:#ffffff;text-align:right;">BALANCE</td>
          <td style="padding:10px;font-family:'Segoe UI',Arial,sans-serif;font-size:11px;font-weight:700;color:#ffffff;text-align:right;">ESTADO DE RESULTADOS</td>
          <td style="padding:10px 12px 10px 10px;font-family:'Segoe UI',Arial,sans-serif;font-size:11px;font-weight:700;color:#ffffff;text-align:right;">DIF.</td>
        </tr>
        {filas}
        {fila_total}
      </table>"""


def _insights_html(insights):
    items = "".join(
        f'<li style="font-family:\'Segoe UI\',Arial,sans-serif;font-size:12px;color:{COLORS["text_secondary"]};'
        f'line-height:1.6;margin-bottom:4px;">{texto}</li>'
        for texto in insights
    )
    return f"""
      <div style="font-family:'Segoe UI',Arial,sans-serif;font-size:14px;font-weight:800;color:{COLORS['primary']};margin:0 0 8px;">Insights del día</div>
      <ul style="margin:0;padding-left:18px;">{items}</ul>"""


def build_email_html(fecha_str, hora_str, df, chart_src, chart_ok, logo_src):
    kpis = build_kpis(df, TOLERANCIA_DIF_MXN)
    insights = build_insights(df, kpis)

    chart_block = ""
    if chart_ok:
        chart_block = f"""
        <tr><td style="padding:0 28px 18px;">
          <img src="{chart_src}" width="620"
               style="width:100%;max-width:620px;display:block;border-radius:10px;border:1px solid {COLORS['border']};"
               alt="Top 5 sociedades por Resultado Financiero">
        </td></tr>"""

    logo_html = f'<img src="{logo_src}" width="34" style="display:block;margin-bottom:6px;">' if logo_src else ""

    return f"""<!DOCTYPE html>
<html lang="es"><head><meta charset="UTF-8">
<style>
  /* Hover de filas: Gmail web y Apple Mail lo aplican; Outlook de escritorio lo ignora sin
     romper el layout (degrada a "sin hover", nunca a un error visual). */
  .fila-hover:hover td {{ background:{COLORS['support']} !important; }}
</style>
</head>
<body style="margin:0;padding:0;background:{COLORS['bg']};font-family:'Segoe UI',Arial,sans-serif;color:{COLORS['text_primary']};">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:{COLORS['bg']};padding:28px 12px;">
    <tr><td align="center">
      <table width="700" cellpadding="0" cellspacing="0"
             style="background:{COLORS['surface']};border-radius:14px;overflow:hidden;border:1px solid {COLORS['border']};
                    box-shadow:0 4px 18px rgba(18,53,91,0.09);max-width:700px;width:100%;">
        <tr><td style="padding:24px 28px 18px;border-bottom:2px solid {COLORS['secondary']};">
          <table width="100%" cellpadding="0" cellspacing="0"><tr>
            <td>
              {logo_html}
              <div style="font-family:'Segoe UI',Arial,sans-serif;font-size:24px;font-weight:800;color:{COLORS['primary']};">
                Resultado Financiero Diario
              </div>
              <div style="font-family:'Segoe UI',Arial,sans-serif;font-size:13px;color:{COLORS['muted']};margin-top:3px;">
                Conciliación Balance vs. Estado de Resultados
              </div>
            </td>
            <td align="right" style="vertical-align:top;">
              <div style="font-family:'Segoe UI',Arial,sans-serif;font-size:11px;font-weight:700;color:{COLORS['muted']};">{fecha_str}</div>
              <div style="font-family:'Segoe UI',Arial,sans-serif;font-size:10.5px;color:{COLORS['muted']};margin-top:2px;">Generado a las {hora_str}</div>
            </td>
          </tr></table>
        </td></tr>
        <tr><td style="padding:18px 28px 0;">{_kpi_row_html(kpis)}</td></tr>
        <tr><td style="padding:14px 28px 0;">{_status_card_html(kpis, TOLERANCIA_DIF_MXN)}</td></tr>
        {chart_block}
        <tr><td style="padding:18px 28px 0;">{_tabla_html(df, TOLERANCIA_DIF_MXN)}</td></tr>
        <tr><td style="padding:20px 28px 0;">{_insights_html(insights)}</td></tr>
        <tr><td style="padding:16px 28px 24px;border-top:1px solid {COLORS['border']};margin-top:16px;">
          <p style="font-family:'Segoe UI',Arial,sans-serif;font-size:10.5px;color:{COLORS['muted']};margin:14px 0 0;line-height:1.6;">
            Última actualización: {fecha_str} {hora_str}  |  Fuente: BigQuery -- sap_faglflext  |  Versión: v2<br>
            Vista previa manual -- cálculo pendiente de validar contra SAP ZF01 en vivo. El PDF adjunto trae el mismo detalle.
          </p>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body></html>"""


def enviar(pdf_path, destinatario, dry_run=False):
    if not os.path.exists(pdf_path):
        raise FileNotFoundError(f"No se encontró el PDF: {pdf_path}")

    hoy = datetime.date.today()
    anio = str(hoy.year)
    fecha_str = hoy.strftime("%d/%m/%Y")
    hora_str = datetime.datetime.now().strftime("%H:%M")
    asunto = EMAIL_ASUNTO_TEMPLATE.format(fecha=fecha_str)
    cuerpo_texto_plano = CUERPO_TEXTO_PLANO.format(fecha=fecha_str)
    from_email = os.environ.get("SENDGRID_FROM_EMAIL", SENDGRID_FROM_EMAIL_DEFAULT)

    client = bigquery.Client(project=PROJECT_ID)
    _, df = fetch_resultado_financiero(client, anio, SOCIEDADES)

    chart_path = os.path.join(OUTPUT_DIR, "_chart_resultado_financiero_top5.png")
    chart_ok = build_chart_top5(df, chart_path)
    logo_ok = os.path.exists(LOGO_PNG)

    if dry_run:
        chart_src = "file:///" + os.path.abspath(chart_path).replace("\\", "/") if chart_ok else ""
        logo_src = "file:///" + os.path.abspath(LOGO_PNG).replace("\\", "/") if logo_ok else ""
        html_preview = build_email_html(fecha_str, hora_str, df, chart_src, chart_ok, logo_src)
        preview_path = os.path.join(OUTPUT_DIR, "_preview_email_resultado_financiero.html")
        with open(preview_path, "w", encoding="utf-8") as f:
            f.write(html_preview)
        print(f"[DRY RUN] De: {from_email}  Para: {destinatario}")
        print(f"[DRY RUN] Asunto: {asunto}")
        print(f"[DRY RUN] Adjunto PDF: {pdf_path}")
        print(f"[DRY RUN] Gráfico: {'incluido' if chart_ok else 'omitido (sin diferencias que graficar)'}")
        print(f"[DRY RUN] Vista previa del HTML guardada en: {preview_path} (ábrela en el navegador)")
        print("[DRY RUN] No se envió ningún correo real (SendGrid no fue invocado).")
        return

    html_body = build_email_html(
        fecha_str, hora_str, df, f"cid:{CHART_CID}", chart_ok, f"cid:{LOGO_CID}" if logo_ok else "",
    )

    import sendgrid
    from sendgrid.helpers.mail import (
        Attachment, ContentId, Disposition, FileContent, FileName, FileType, Mail,
    )

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

    if chart_ok:
        with open(chart_path, "rb") as f:
            chart_bytes = f.read()
        message.add_attachment(Attachment(
            FileContent(base64.b64encode(chart_bytes).decode()),
            FileName(os.path.basename(chart_path)),
            FileType("image/png"),
            Disposition("inline"),
            ContentId(CHART_CID),
        ))

    if logo_ok:
        with open(LOGO_PNG, "rb") as f:
            logo_bytes = f.read()
        message.add_attachment(Attachment(
            FileContent(base64.b64encode(logo_bytes).decode()),
            FileName(os.path.basename(LOGO_PNG)),
            FileType("image/png"),
            Disposition("inline"),
            ContentId(LOGO_CID),
        ))

    api_key = os.environ["SENDGRID_API_KEY"]
    sg_client = sendgrid.SendGridAPIClient(api_key)
    response = sg_client.send(message)
    print(f"SendGrid respondió con status {response.status_code}")
    return response


def main():
    # REPORTE_EMAIL_TO (Cloud Run, ver deploy.sh) tiene prioridad sobre EMAIL_DESTINATARIO_DEFAULT
    # (config.py, usado en ejecución local) -- mismo patrón que "Reportes diarios contables".
    destinatario_default = os.environ.get("REPORTE_EMAIL_TO", EMAIL_DESTINATARIO_DEFAULT)
    parser = argparse.ArgumentParser()
    parser.add_argument("--to", default=destinatario_default, help="Correo destinatario")
    parser.add_argument("--pdf", default=None, help="Ruta al PDF a enviar")
    parser.add_argument("--dry-run", action="store_true",
                         help="No envía el correo; guarda una vista previa del HTML")
    args = parser.parse_args()

    pdf_path = args.pdf or os.path.join(
        OUTPUT_DIR, f"resultado_financiero_diario_{datetime.date.today().isoformat()}.pdf"
    )
    enviar(pdf_path, args.to, dry_run=args.dry_run)
    if not args.dry_run:
        print(f"Reporte enviado a {args.to}: {pdf_path}")


if __name__ == "__main__":
    main()
