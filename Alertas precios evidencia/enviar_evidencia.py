"""Envía por correo el PDF de evidencia del día y registra las alertas enviadas.

Lee el manifiesto que deja generar_evidencia.py. Si el envío sale bien (SendGrid responde 2xx), apunta cada alerta en
la tabla de control para no volver a enviarla. Si falla, no apunta nada: las alertas se reintentan al día siguiente.

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
def cuerpo_html(m):
    filas = "".join(
        f"""<tr><td>{fecha_corta(a['fecha_alerta'])[:5]}</td><td>{a['sociedad']}</td><td>{a['cliente']}</td>
        <td>{a['nombre_material']}</td><td class="n">{a['precio']:,.2f}</td><td class="n">{a['esperado']:,.2f}</td>
        <td class="n {'neg' if a['impacto_mxn'] < 0 else 'pos'}">{mxn(a['impacto_mxn'], signo=True)}</td>
        <td>{'Sí' if a['con_factura'] else 'No llegó'}</td></tr>"""
        for a in m["alertas"])
    n = len(m["alertas"])
    esperando = (f"<p>{m['esperando']} alerta{'s' if m['esperando'] != 1 else ''} más "
                 f"esper{'an' if m['esperando'] != 1 else 'a'} su factura y saldrá{'n' if m['esperando'] != 1 else ''} "
                 "en próximos envíos.</p>") if m["esperando"] else ""
    return f"""<html><head><style>
  body {{ font-family:'Segoe UI',Arial,sans-serif; font-size:13px; color:{config.INK}; }}
  table {{ border-collapse:collapse; width:100%; margin-top:10px; }}
  th {{ background:{config.BARRA_FACTURA}; color:#fff; font-size:11px; padding:6px; text-align:left; }}
  td {{ border-bottom:1px solid {config.LINE}; padding:6px; font-size:12px; }}
  .n {{ text-align:right; font-family:Consolas,monospace; }} .neg {{ color:{config.CRIT}; font-weight:700; }}
  .pos {{ color:{config.WARN}; font-weight:700; }} .nota {{ color:{config.MUTED}; font-size:11px; }}
</style></head><body>
<p>Hola,</p>
<p>Adjuntamos la evidencia de {n} alerta{'s' if n != 1 else ''} de precio grave{'s' if n != 1 else ''} cuya factura ya
está disponible. Para cada alerta, el PDF incluye el histórico de precios, la factura de la venta y una factura del mismo
producto a precio normal.</p>
<table><tr><th>Venta</th><th>Sociedad</th><th>Cliente</th><th>Producto</th><th>Precio $/kg</th><th>Esperado $/kg</th>
<th>Impacto</th><th>Factura</th></tr>{filas}</table>
{esperando}
<p class="nota">Impacto = (precio - esperado) x kilos. Correo generado automáticamente.</p>
</body></html>"""


# --- Envío ------------------------------------------------------------------------------------------------------
def enviar(m, para_override=None, dry_run=False, registrar=True):
    n = len(m["alertas"])
    if n == 0 and not config.ENVIAR_SI_VACIO:
        print("[correo] No hay evidencias nuevas hoy: no se envía correo.")
        return
    asunto = config.ASUNTO.format(fecha=fecha_corta(m["fecha"]).replace("-", "/"), n=n, s="s" if n != 1 else "")
    html = cuerpo_html(m)
    remitente = os.environ.get("SENDGRID_FROM_EMAIL", config.SENDGRID_FROM_EMAIL_DEFAULT)
    para = [para_override] if para_override else destinatarios()

    if dry_run:
        vista = os.path.join(config.OUTPUT_DIR, f"vista_previa_correo_{m['fecha']}.html")
        with open(vista, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"[DRY RUN] Asunto: {asunto}")
        print(f"[DRY RUN] De: {remitente} · Cc: {para or '(lista vacía o no accesible)'}")
        print(f"[DRY RUN] Adjunto: {m['pdf']}")
        print(f"[DRY RUN] Vista previa del correo: {vista}")
        print("[DRY RUN] No se ha enviado nada ni se ha registrado ninguna alerta como enviada.")
        return
    if not para:
        print("[correo] Sin destinatarios: no se envía. Revisa la lista de Firestore (campos enabled / emails).")
        return

    import sendgrid
    from sendgrid.helpers.mail import Attachment, Cc, Disposition, FileContent, FileName, FileType, Mail
    msg = Mail(from_email=remitente, to_emails=remitente, subject=asunto, html_content=html,
               plain_text_content=f"Evidencia de {n} alertas de precio del {fecha_larga(m['fecha'])}. Ver PDF adjunto.")
    for e in para:
        msg.add_cc(Cc(e))
    if m["pdf"]:
        with open(m["pdf"], "rb") as f:
            msg.add_attachment(Attachment(FileContent(base64.b64encode(f.read()).decode()),
                                          FileName(os.path.basename(m["pdf"])), FileType("application/pdf"),
                                          Disposition("attachment")))
    resp = sendgrid.SendGridAPIClient(os.environ["SENDGRID_API_KEY"]).send(msg)
    print(f"[correo] SendGrid respondió {resp.status_code} · destinatarios: {len(para)}")
    if not 200 <= resp.status_code < 300:
        raise RuntimeError("El correo no se envió; las alertas quedan pendientes para el próximo día.")

    # Solo si el correo salió bien se apuntan como enviadas (si es un envío de prueba a una dirección, no se apunta)
    if para_override or not registrar:
        print("[correo] Envío de prueba: no se registran las alertas como enviadas.")
        return
    ahora = datetime.datetime.now(datetime.timezone.utc).isoformat()
    campos = ["alerta_id", "fecha_alerta", "sociedad", "material", "cliente", "facturas", "factura_mostrada", "uuid",
              "factura_referencia", "con_factura", "impacto_mxn"]
    datos.registrar_enviadas([{**{k: a[k] for k in campos}, "fecha_envio": ahora} for a in m["alertas"]])
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
