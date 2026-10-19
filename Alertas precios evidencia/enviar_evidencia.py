"""Envía por correo la evidencia del día (un PDF adjunto por sociedad) y registra las alertas enviadas.

Lee el manifiesto que deja generar_evidencia.py. Es un único correo con un PDF por sociedad. Si el envío sale bien
(SendGrid responde 2xx), apunta cada alerta en la tabla de control para no volver a enviarla. Si falla, no apunta nada:
las alertas se reintentan al día siguiente.

Destinatarios: lista de Firestore (base proan-lista-mails, colección lists, documento alertas-precios-evidencia, campos
`emails` y `enabled`), igual que los reportes financieros. Cambiar quién lo recibe no requiere redesplegar.

Uso local:
    python enviar_evidencia.py --dry-run          # no envía ni registra; guarda la vista previa del correo
    python enviar_evidencia.py --to a@b.com       # envía solo a esa dirección (pruebas)
    python enviar_evidencia.py --sin-registrar    # envía a la lista de Firestore sin apuntar las alertas (pruebas)
"""
import argparse
import base64
import datetime
import json
import os

import config
import datos
from formato import fecha_corta, fecha_larga, mxn



# --- Destinatarios ----------------------------------------------------------------------------------------------
def destinatarios():
    """Lista de Firestore. Si no existe, está deshabilitada o falla, devuelve [] y deja aviso (sin romper el job)."""
    try:
        from google.cloud import firestore
        doc = (firestore.Client(project=config.PROJECT_ID, database=config.FIRESTORE_DATABASE_ID)
               .collection(config.FIRESTORE_LISTS_COLLECTION).document(config.LISTA_CORREO).get())
    except Exception as exc:
        print(f"[correo] AVISO: no se pudo leer Firestore ({config.LISTA_CORREO}): {exc}")
        return []
    if not doc.exists:
        print(f"[correo] AVISO: no existe la lista {config.FIRESTORE_LISTS_COLLECTION}/{config.LISTA_CORREO}")
        return []
    data = doc.to_dict() or {}
    if not data.get("enabled", True):
        print(f"[correo] AVISO: la lista {config.LISTA_CORREO} está deshabilitada")
        return []
    vistos, out = set(), []
    for e in data.get("emails") or []:
        e = str(e or "").strip()
        if e and e.lower() not in vistos:
            vistos.add(e.lower())
            out.append(e)
    return out


# --- Cuerpo del correo ------------------------------------------------------------------------------------------
def cuerpo_html(m, envios):
    """Correo en una tarjeta de 680 px: cabecera, cifras resumen, tabla de alertas agrupada por sociedad y pie.

    La numeración de cada sociedad coincide con la de su PDF. Maquetado con tablas y estilos en línea (lo único que
    respetan a la vez Gmail y Outlook).
    """
    alertas = [a for e in envios for a in e["alertas"]]
    n = len(alertas)
    perdida = sum(a["impacto_mxn"] for a in alertas if a["impacto_mxn"] < 0)
    sobre = sum(a["impacto_mxn"] for a in alertas if a["impacto_mxn"] > 0)
    sin_factura = sum(1 for a in alertas if not a["con_factura"])
    n_esperando = m.get("esperando", 0)
    fuente = "font-family:'Segoe UI',Helvetica,Arial,sans-serif;"
    azul = config.BARRA_FACTURA

    def tarjeta(etiqueta, valor, color):
        return (f'<td width="25%" style="padding:0 4px;"><table width="100%" cellpadding="0" cellspacing="0" '
                f'style="background:#f4f6f8;border-radius:6px;"><tr><td style="padding:12px 14px;{fuente}">'
                f'<div style="font-size:10px;letter-spacing:.6px;text-transform:uppercase;color:{config.MUTED};">'
                f'{etiqueta}</div><div style="font-size:20px;font-weight:700;color:{color};margin-top:4px;">{valor}'
                f'</div></td></tr></table></td>')

    filas = []
    for e in envios:
        color_soc = config.COLOR_SOCIEDAD.get(e["sociedad"], azul)
        k = len(e["alertas"])
        filas.append(f"""
        <tr><td colspan="6" style="padding:14px 8px 8px;{fuente}border-bottom:2px solid {color_soc};">
          <span style="display:inline-block;width:10px;height:10px;border-radius:5px;background:{color_soc};margin-right:8px;"></span>
          <span style="font-size:13px;font-weight:700;color:{config.INK};">{e['sociedad']}</span>
          <span style="font-size:12px;color:{config.MUTED};"> · {e['nombre_sociedad']} · {k} alerta{"s" if k != 1 else ""}
            · {os.path.basename(e['pdf'])}</span></td></tr>""")
        for i, a in enumerate(e["alertas"], start=1):
            color_imp = config.CRIT if a["impacto_mxn"] < 0 else config.WARN
            aviso = ("<br><span style='font-size:10px;color:#9a6400;'>Factura no disponible</span>"
                     if not a["con_factura"] else "")
            fondo = "#ffffff" if i % 2 else "#fafbfc"
            filas.append(f"""
        <tr style="background:{fondo};">
          <td style="padding:10px 8px;{fuente}font-size:11px;color:{config.MUTED};border-bottom:1px solid #e8ebee;">{i}</td>
          <td style="padding:10px 8px;{fuente}font-size:12px;color:{config.INK};border-bottom:1px solid #e8ebee;white-space:nowrap;">{fecha_corta(a['fecha_alerta'])[:5]}</td>
          <td style="padding:10px 8px;{fuente}border-bottom:1px solid #e8ebee;">
            <div style="font-size:12px;font-weight:600;color:{config.INK};">{a['nombre_material']}</div>
            <div style="font-size:11px;color:{config.MUTED};margin-top:2px;">{a['cliente']}</div></td>
          <td align="right" style="padding:10px 8px;{fuente}font-size:12px;color:{config.INK};border-bottom:1px solid #e8ebee;white-space:nowrap;">
            ${a['precio']:,.2f}</td>
          <td align="right" style="padding:10px 8px;{fuente}font-size:12px;color:{config.MUTED};border-bottom:1px solid #e8ebee;white-space:nowrap;">
            ${a['esperado']:,.2f}</td>
          <td align="right" style="padding:10px 8px;{fuente}font-size:13px;font-weight:700;color:{color_imp};border-bottom:1px solid #e8ebee;white-space:nowrap;">
            {mxn(a['impacto_mxn'], signo=True)}{aviso}</td>
        </tr>""")

    th = (f"padding:9px 8px;{fuente}font-size:10px;font-weight:600;letter-spacing:.5px;text-transform:uppercase;"
          f"color:#ffffff;background:{azul};")
    esperando = ""
    if n_esperando:
        x = n_esperando
        esperando = (f'<p style="{fuente}font-size:12px;color:{config.MUTED};margin:14px 0 0;">'
                     f'{x} alerta{"s" if x != 1 else ""} más esper{"an" if x != 1 else "a"} su factura y '
                     f'saldrá{"n" if x != 1 else ""} en los próximos envíos.</p>')
    plural = "s" if n != 1 else ""
    n_soc = len(envios)
    adjuntos = "un PDF" if n_soc == 1 else f"un PDF por sociedad ({n_soc})"
    return f"""<!DOCTYPE html>
<html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#eef1f4;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#eef1f4;"><tr><td align="center" style="padding:24px 12px;">
  <table width="680" cellpadding="0" cellspacing="0" style="max-width:680px;width:100%;background:#ffffff;border-radius:8px;overflow:hidden;">
    <tr><td style="background:{azul};padding:22px 28px;{fuente}">
      <div style="font-size:11px;letter-spacing:1px;text-transform:uppercase;color:#c9d3e6;">Alertas de precio</div>
      <div style="font-size:22px;font-weight:700;color:#ffffff;margin-top:4px;">Evidencia de alertas graves</div>
      <div style="font-size:13px;color:#c9d3e6;margin-top:4px;">{fecha_larga(m['fecha'])}</div>
    </td></tr>
    <tr><td style="padding:22px 28px 6px;{fuente}font-size:14px;line-height:21px;color:{config.INK};">
      Buenas tardes:<br><br>
      Adjuntamos la evidencia de <b>{n} alerta{plural} de precio grave{plural}</b> cuya factura ya está disponible,
      en {adjuntos}. Para cada alerta, el PDF incluye el histórico de precios del producto, la factura de la venta y
      una factura del mismo producto a su precio habitual.
    </td></tr>
    <tr><td style="padding:14px 24px 4px;"><table width="100%" cellpadding="0" cellspacing="0"><tr>
      {tarjeta("Alertas", n, config.INK)}
      {tarjeta("Pérdida estimada", mxn(perdida), config.CRIT)}
      {tarjeta("Ganancia estimada", mxn(sobre, signo=True) if sobre else "$0", config.WARN)}
      {tarjeta("Sin factura", sin_factura, config.INK)}
    </tr></table></td></tr>
    <tr><td style="padding:18px 28px 4px;">
      <table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;">
        <tr><th align="left" style="{th}">#</th><th align="left" style="{th}">Venta</th>
            <th align="left" style="{th}">Producto y cliente</th><th align="right" style="{th}">Precio facturado</th>
            <th align="right" style="{th}">Precio oficial</th><th align="right" style="{th}">Pérdida o ganancia</th></tr>
        {''.join(filas)}
      </table>
      {esperando}
    </td></tr>
    <tr><td style="padding:22px 28px 26px;{fuente}font-size:11px;line-height:17px;color:{config.MUTED};">
      El número de cada alerta coincide con el del PDF de su sociedad. Precios en $/kg. Pérdida o ganancia = (precio
      facturado − precio oficial) × kilos; en rojo, ventas por debajo del precio oficial y en ámbar, por encima.<br>
      Este correo se genera automáticamente cada día con las alertas cuya factura se ha recibido.
    </td></tr>
  </table>
</td></tr></table>
</body></html>"""


# --- Envío ------------------------------------------------------------------------------------------------------
def enviar(m, para_override=None, dry_run=False, registrar=True):
    envios = [e for e in m.get("envios", []) if e["alertas"]]
    alertas = [a for e in envios for a in e["alertas"]]
    n = len(alertas)
    if n == 0 and not config.ENVIAR_SI_VACIO:
        print("[correo] No hay evidencias nuevas hoy: no se envía correo.")
        return
    asunto = config.ASUNTO.format(fecha=fecha_corta(m["fecha"]).replace("-", "/"), n=n, s="s" if n != 1 else "")
    html = cuerpo_html(m, envios)
    remitente = os.environ.get("SENDGRID_FROM_EMAIL", config.SENDGRID_FROM_EMAIL_DEFAULT)
    para = [para_override] if para_override else destinatarios()

    if dry_run:
        vista = os.path.join(config.OUTPUT_DIR, f"vista_previa_correo_{m['fecha']}.html")
        with open(vista, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"[DRY RUN] Asunto: {asunto}")
        print(f"[DRY RUN] De: {remitente} · Cc: {para or '(lista vacía o no accesible)'}")
        for e in envios:
            print(f"[DRY RUN] Adjunto: {os.path.basename(e['pdf'])} ({len(e['alertas'])} alertas)")
        print(f"[DRY RUN] Vista previa del correo: {vista}")
        print("[DRY RUN] No se ha enviado nada ni se ha registrado ninguna alerta como enviada.")
        return
    if not para:
        print("[correo] Sin destinatarios: no se envía. Revisa la lista de Firestore (campos enabled / emails).")
        return

    import sendgrid
    from sendgrid.helpers.mail import Attachment, Cc, Disposition, FileContent, FileName, FileType, Mail
    msg = Mail(from_email=remitente, to_emails=remitente, subject=asunto, html_content=html,
               plain_text_content=f"Evidencia de {n} alertas de precio del {fecha_larga(m['fecha'])}. "
                                  f"Ver un PDF adjunto por sociedad.")
    for e in para:
        msg.add_cc(Cc(e))
    for e in envios:
        with open(e["pdf"], "rb") as f:
            msg.add_attachment(Attachment(FileContent(base64.b64encode(f.read()).decode()),
                                          FileName(os.path.basename(e["pdf"])), FileType("application/pdf"),
                                          Disposition("attachment")))
    resp = sendgrid.SendGridAPIClient(os.environ["SENDGRID_API_KEY"]).send(msg)
    print(f"[correo] SendGrid respondió {resp.status_code} · destinatarios: {len(para)} · adjuntos: {len(envios)}")
    if not 200 <= resp.status_code < 300:
        raise RuntimeError("El correo no se envió; las alertas quedan pendientes para el próximo día.")

    # Solo si el correo salió bien se apuntan como enviadas (si es un envío de prueba a una dirección, no se apunta)
    if para_override or not registrar:
        print("[correo] Envío de prueba: no se registran las alertas como enviadas.")
        return
    ahora = datetime.datetime.now(datetime.timezone.utc).isoformat()
    campos = ["alerta_id", "fecha_alerta", "sociedad", "material", "cliente", "facturas", "factura_mostrada", "uuid",
              "factura_referencia", "con_factura", "impacto_mxn"]
    datos.registrar_enviadas([{**{k: a[k] for k in campos}, "fecha_envio": ahora} for a in alertas])
    print(f"[correo] {n} alertas registradas en {config.TABLA_ENVIADAS}")


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true", help="No envía ni registra; guarda la vista previa")
    p.add_argument("--to", default=None, help="Envía solo a esta dirección (pruebas; no registra)")
    p.add_argument("--sin-registrar", action="store_true",
                   help="Envía a la lista de Firestore pero no apunta las alertas como enviadas (pruebas)")
    args = p.parse_args(argv)
    import generar_evidencia
    with open(generar_evidencia.ruta_manifiesto(), encoding="utf-8") as f:
        m = json.load(f)
    enviar(m, para_override=args.to, dry_run=args.dry_run or config.DRY_RUN, registrar=not args.sin_registrar)


if __name__ == "__main__":
    main()
