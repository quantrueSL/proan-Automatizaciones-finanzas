"""Envía por correo el PDF del reporte diario generado por generar_reporte.py.

Uso:
    python enviar_reporte.py                          # envía el reporte de hoy
    python enviar_reporte.py --pdf ruta\al\reporte.pdf # envía un PDF específico
    python enviar_reporte.py --to otro@correo.com      # cambia el destinatario

Requiere credenciales SMTP en variables de entorno (ver .env.example):
    SMTP_USER, SMTP_PASSWORD, SMTP_HOST (opcional), SMTP_PORT (opcional)
"""

import argparse
import datetime
import os
import smtplib
from email.message import EmailMessage

from dotenv import load_dotenv

from config import OUTPUT_DIR, EMAIL_DESTINATARIO_DEFAULT, EMAIL_ASUNTO_TEMPLATE, EMAIL_CUERPO_TEMPLATE

load_dotenv()

SMTP_HOST_DEFAULT = "smtp.office365.com"
SMTP_PORT_DEFAULT = 587


def enviar_reporte(pdf_path, destinatario):
    if not os.path.exists(pdf_path):
        raise FileNotFoundError(f"No se encontró el PDF: {pdf_path}")

    usuario = os.environ["SMTP_USER"]
    password = os.environ["SMTP_PASSWORD"]
    host = os.environ.get("SMTP_HOST", SMTP_HOST_DEFAULT)
    port = int(os.environ.get("SMTP_PORT", SMTP_PORT_DEFAULT))

    fecha_str = datetime.date.today().strftime("%d/%m/%Y")

    msg = EmailMessage()
    msg["Subject"] = EMAIL_ASUNTO_TEMPLATE.format(fecha=fecha_str)
    msg["From"] = usuario
    msg["To"] = destinatario
    msg.set_content(EMAIL_CUERPO_TEMPLATE.format(fecha=fecha_str))

    with open(pdf_path, "rb") as f:
        msg.add_attachment(
            f.read(), maintype="application", subtype="pdf",
            filename=os.path.basename(pdf_path),
        )

    with smtplib.SMTP(host, port) as server:
        server.starttls()
        server.login(usuario, password)
        server.send_message(msg)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pdf", default=None, help="Ruta al PDF a enviar")
    parser.add_argument("--to", default=EMAIL_DESTINATARIO_DEFAULT, help="Correo destinatario")
    args = parser.parse_args()

    pdf_path = args.pdf or os.path.join(
        OUTPUT_DIR, f"reporte_cuentas_proan_{datetime.date.today().isoformat()}.pdf"
    )

    enviar_reporte(pdf_path, args.to)
    print(f"Reporte enviado a {args.to}: {pdf_path}")


if __name__ == "__main__":
    main()
