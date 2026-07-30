"""
Proceso diario de tipos de cambio con fuente oficial de Banco de Mexico.

API oficial de Banxico:
- Se usa la API REST del SIE de Banxico, no scraping del HTML publico.
- Documentacion oficial: https://www.banxico.org.mx/SieAPIRest/swagger/index.html
- Series usadas:
  - SF43718: tipo de cambio FIX pesos mexicanos por dolar estadounidense.
  - SF46410: tipo de cambio pesos mexicanos por euro.
- Endpoint usado:
  - /v1/series/{idSeries}/datos/oportuno

Sobre el token:
- Banxico protege la API con un token.
- Ese token es una clave de acceso que se manda en la cabecera HTTP Bmx-Token.
- Abrir la URL en el navegador no basta, porque la API espera esa credencial.
- El token se lee de la variable de entorno BANXICO_API_TOKEN. Se carga desde
  .env durante el deploy, igual que SENDGRID_API_KEY.

Calculos:
- usd_mxn: dato directo Banxico.
- eur_mxn: dato directo Banxico.
- eur_usd = eur_mxn / usd_mxn
- usd_eur = 1 / eur_usd

Persistencia en BigQuery:
- Este script guarda historico.
- Si ya existe una fila para la fecha de ejecucion, la actualiza.
- Si no existe, inserta una fila nueva.
- La tabla objetivo es Cambio_divisa_diario dentro del dataset ZZ_PRUEBAS.
- Se conserva la fecha oficial publicada por Banxico y la fecha diaria de ejecucion.
- Se guarda tambien la fecha y hora local de Mexico a la que se actualiza la tabla.
"""

from __future__ import annotations

import json
import logging
import os
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime
from html import escape
from typing import Any
from zoneinfo import ZoneInfo

import requests
from google.cloud import bigquery
from google.cloud import firestore


BANXICO_API_TOKEN = os.environ.get("BANXICO_API_TOKEN", "REEMPLAZAR_CON_TOKEN_BANXICO").strip()
BANXICO_BASE_URL = "https://www.banxico.org.mx/SieAPIRest/service/v1/series"
USD_SERIES_ID = "SF43718"
EUR_SERIES_ID = "SF46410"
DECIMAL_PLACES = Decimal("0.000000")
DEFAULT_EMAIL_RECIPIENTS = ("pcoma@quantrue.com", "fromeo@quantrue.com")
FIRESTORE_DATABASE_ID = os.environ.get("FIRESTORE_DATABASE_ID", "proan-lista-mails").strip()
FIRESTORE_LISTS_COLLECTION = os.environ.get("FIRESTORE_LISTS_COLLECTION", "lists").strip()
CAMBIO_DIVISA_LIST_ID = os.environ.get("CAMBIO_DIVISA_LIST_ID", "cambio_divisa").strip()


def quantize(value: Decimal) -> Decimal:
    return value.quantize(DECIMAL_PLACES, rounding=ROUND_HALF_UP)


def fetch_latest_series_value(series_id: str) -> tuple[str, Decimal]:
    url = f"{BANXICO_BASE_URL}/{series_id}/datos/oportuno"
    headers = {"Bmx-Token": BANXICO_API_TOKEN}
    response = requests.get(url, headers=headers, timeout=30)
    response.raise_for_status()

    payload = response.json()
    try:
        series = payload["bmx"]["series"][0]
        data = series["datos"][0]
        rate_date = data["fecha"]
        raw_value = data["dato"].replace(",", "")
    except (KeyError, IndexError) as exc:
        raise ValueError(
            f"Respuesta inesperada de Banxico para la serie {series_id}: "
            f"{json.dumps(payload, ensure_ascii=True)}"
        ) from exc

    if raw_value in {"N/E", ""}:
        raise ValueError(f"Banxico devolvio un dato no utilizable para {series_id}: {raw_value}")

    return rate_date, Decimal(raw_value)


def build_rates() -> dict[str, Any]:
    usd_date, usd_mxn = fetch_latest_series_value(USD_SERIES_ID)
    eur_date, eur_mxn = fetch_latest_series_value(EUR_SERIES_ID)
    updated_at_mexico = datetime.now(ZoneInfo("America/Mexico_City"))

    usd_date_iso = datetime.strptime(usd_date, "%d/%m/%Y").date().isoformat()
    eur_date_iso = datetime.strptime(eur_date, "%d/%m/%Y").date().isoformat()

    # Si Banxico devolviera fechas distintas, se toma la mas reciente conocida
    # y se deja trazado en logs para revisarlo.
    if usd_date_iso != eur_date_iso:
        logging.warning(
            "Fechas distintas entre series Banxico: USD=%s EUR=%s", usd_date_iso, eur_date_iso
        )

    eur_usd = quantize(eur_mxn / usd_mxn)
    usd_eur = quantize(Decimal("1") / eur_usd)

    return {
        "process_date": updated_at_mexico.date().isoformat(),
        "rate_date": max(usd_date_iso, eur_date_iso),
        "usd_mxn": quantize(usd_mxn),
        "eur_mxn": quantize(eur_mxn),
        "eur_usd": eur_usd,
        "usd_eur": usd_eur,
        "updated_at_mexico": updated_at_mexico.strftime("%Y-%m-%d %H:%M:%S"),
    }


def ensure_table(client: bigquery.Client, table_id: str) -> None:
    schema = [
        bigquery.SchemaField("process_date", "DATE", mode="NULLABLE"),
        bigquery.SchemaField("rate_date", "DATE", mode="REQUIRED"),
        bigquery.SchemaField("usd_mxn", "NUMERIC", mode="REQUIRED"),
        bigquery.SchemaField("eur_mxn", "NUMERIC", mode="REQUIRED"),
        bigquery.SchemaField("eur_usd", "NUMERIC", mode="REQUIRED"),
        bigquery.SchemaField("usd_eur", "NUMERIC", mode="REQUIRED"),
        bigquery.SchemaField("updated_at_mexico", "DATETIME", mode="REQUIRED"),
    ]
    table = bigquery.Table(table_id, schema=schema)
    client.create_table(table, exists_ok=True)
    client.query(
        f"ALTER TABLE `{table_id}` ADD COLUMN IF NOT EXISTS process_date DATE"
    ).result()


def write_history_row(client: bigquery.Client, table_id: str, rates: dict[str, Any]) -> None:
    merge_sql = f"""
        MERGE `{table_id}` T
        USING (
            SELECT
                @process_date AS process_date,
                @rate_date AS rate_date,
                @usd_mxn AS usd_mxn,
                @eur_mxn AS eur_mxn,
                @eur_usd AS eur_usd,
                @usd_eur AS usd_eur,
                @updated_at_mexico AS updated_at_mexico
        ) S
        ON T.rate_date = S.rate_date
        WHEN MATCHED THEN
          UPDATE SET
            process_date = S.process_date,
            rate_date = S.rate_date,
            usd_mxn = S.usd_mxn,
            eur_mxn = S.eur_mxn,
            eur_usd = S.eur_usd,
            usd_eur = S.usd_eur,
            updated_at_mexico = S.updated_at_mexico
        WHEN NOT MATCHED THEN
          INSERT (process_date, rate_date, usd_mxn, eur_mxn, eur_usd, usd_eur, updated_at_mexico)
          VALUES (S.process_date, S.rate_date, S.usd_mxn, S.eur_mxn, S.eur_usd, S.usd_eur, S.updated_at_mexico)
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("process_date", "DATE", rates["process_date"]),
            bigquery.ScalarQueryParameter("rate_date", "DATE", rates["rate_date"]),
            bigquery.ScalarQueryParameter("usd_mxn", "NUMERIC", str(rates["usd_mxn"])),
            bigquery.ScalarQueryParameter("eur_mxn", "NUMERIC", str(rates["eur_mxn"])),
            bigquery.ScalarQueryParameter("eur_usd", "NUMERIC", str(rates["eur_usd"])),
            bigquery.ScalarQueryParameter("usd_eur", "NUMERIC", str(rates["usd_eur"])),
            bigquery.ScalarQueryParameter(
                "updated_at_mexico", "DATETIME", rates["updated_at_mexico"]
            ),
        ]
    )
    client.query(merge_sql, job_config=job_config).result()


def fetch_previous_rates_for_email(
    client: bigquery.Client, table_id: str, current_process_date: str
) -> dict[str, Any]:
    query = f"""
        SELECT process_date, rate_date, usd_mxn, eur_mxn, eur_usd, usd_eur, updated_at_mexico
        FROM `{table_id}`
        WHERE COALESCE(process_date, rate_date) < @current_process_date
        ORDER BY COALESCE(process_date, rate_date) DESC
        LIMIT 1
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("current_process_date", "DATE", current_process_date),
        ]
    )
    row = next(client.query(query, job_config=job_config).result(), None)
    if row is None:
        raise ValueError(
            "No existe una fila anterior en BigQuery para enviar el correo con un dia de retraso."
        )
    return {
        "process_date": (
            row["process_date"].isoformat() if row["process_date"] is not None else row["rate_date"].isoformat()
        ),
        "rate_date": row["rate_date"].isoformat(),
        "usd_mxn": row["usd_mxn"],
        "eur_mxn": row["eur_mxn"],
        "eur_usd": row["eur_usd"],
        "usd_eur": row["usd_eur"],
        "updated_at_mexico": str(row["updated_at_mexico"]),
    }


def _format_rate(value: Decimal) -> str:
    return f"{value:,.6f}"


def _email_recipients() -> list[str]:
    raw = os.environ.get("CAMBIO_DIVISA_EMAIL_TO", "").strip()
    return [email.strip() for email in raw.split(",") if email.strip()]


def _normalize_recipients(raw_recipients: list[str]) -> list[str]:
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


def _firestore_recipients() -> list[str]:
    client = firestore.Client(project="proan-quantrue", database=FIRESTORE_DATABASE_ID)
    snapshot = (
        client.collection(FIRESTORE_LISTS_COLLECTION).document(CAMBIO_DIVISA_LIST_ID).get()
    )
    if not snapshot.exists:
        logging.warning(
            "No existe documento Firestore %s/%s en base %s",
            FIRESTORE_LISTS_COLLECTION,
            CAMBIO_DIVISA_LIST_ID,
            FIRESTORE_DATABASE_ID,
        )
        return []

    data = snapshot.to_dict() or {}
    if not data.get("enabled", True):
        logging.warning("La lista Firestore %s esta deshabilitada", CAMBIO_DIVISA_LIST_ID)
        return []

    emails = data.get("emails")
    if not isinstance(emails, list):
        logging.warning("El campo emails de la lista Firestore %s no es una lista", CAMBIO_DIVISA_LIST_ID)
        return []

    return _normalize_recipients([str(email) for email in emails])


def resolve_email_recipients() -> tuple[list[str], str]:
    try:
        firestore_recipients = _firestore_recipients()
    except Exception as exc:
        logging.warning("No se pudieron leer destinatarios desde Firestore: %s", exc)
        firestore_recipients = []

    if firestore_recipients:
        return firestore_recipients, "firestore"

    env_recipients = _normalize_recipients(_email_recipients())
    if env_recipients:
        return env_recipients, "env"

    return list(DEFAULT_EMAIL_RECIPIENTS), "default"


def build_email_html(rates: dict[str, Any], table_id: str) -> str:
    rows = [
        ("USD/MXN", "Dolar estadounidense a peso mexicano", rates["usd_mxn"]),
        ("EUR/MXN", "Euro a peso mexicano", rates["eur_mxn"]),
        ("EUR/USD", "Euro a dolar estadounidense", rates["eur_usd"]),
        ("USD/EUR", "Dolar estadounidense a euro", rates["usd_eur"]),
    ]
    table_rows = []
    for pair, description, value in rows:
        table_rows.append(
            """<tr style="border-bottom:1px solid #d9dee5;">
              <td style="padding:12px 14px;font-family:Barlow,'Segoe UI',Arial,sans-serif;font-weight:700;color:#2A2B5F;font-size:13px;">{pair}</td>
              <td style="padding:12px 14px;color:#4b5563;font-size:12px;">{description}</td>
              <td style="padding:12px 14px;text-align:right;font-family:Barlow,'Segoe UI',Arial,sans-serif;font-weight:700;color:#2A2B5F;font-size:14px;">{value}</td>
            </tr>""".format(
                pair=escape(pair),
                description=escape(description),
                value=escape(_format_rate(value)),
            )
        )

    return """<!DOCTYPE html>
<html lang="es"><head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#ffffff;font-family:'Segoe UI',Arial,sans-serif;color:#111827;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#ffffff;padding:32px 16px;">
    <tr><td align="center">
      <table width="680" cellpadding="0" cellspacing="0"
             style="background:#ffffff;border-radius:12px;box-shadow:0 8px 24px rgba(15,23,42,.08);
                    border:1px solid #d9dee5;overflow:hidden;max-width:680px;width:100%;">
        <tr style="background:#ffffff;border-bottom:1px solid #d9dee5;">
          <td style="padding:24px 28px;">
            <table width="100%" cellpadding="0" cellspacing="0">
              <tr>
                <td valign="top">
                  <div style="font-family:Barlow,'Segoe UI',Arial,sans-serif;font-size:28px;font-weight:800;color:#2A2B5F;letter-spacing:-0.8px;">
                    Cambio de divisa
                  </div>
                </td>
              </tr>
            </table>
          </td>
        </tr>
        <tr><td style="padding:24px 28px 8px;">
          <p style="font-family:Barlow,'Segoe UI',Arial,sans-serif;font-size:15px;color:#2A2B5F;font-weight:700;margin:0 0 6px;">
            Tipos de cambio actualizados
          </p>
          <p style="font-size:13px;color:#374151;margin:0;line-height:1.6;">
            Datos de tipo de cambio del Banco de Mexico.
          </p>
        </td></tr>
        <tr><td style="padding:0 28px 22px;">
          <table width="100%" cellpadding="0" cellspacing="0"
                 style="border-collapse:collapse;border:1px solid #d9dee5;border-radius:8px;overflow:hidden;">
            <thead>
              <tr style="background:#2A2B5F;">
                <th style="padding:10px 14px;text-align:left;font-family:Barlow,'Segoe UI',Arial,sans-serif;font-size:10px;font-weight:700;color:#ffffff;text-transform:uppercase;letter-spacing:.5px;">Paridad</th>
                <th style="padding:10px 14px;text-align:left;font-family:Barlow,'Segoe UI',Arial,sans-serif;font-size:10px;font-weight:700;color:#ffffff;text-transform:uppercase;letter-spacing:.5px;">Descripcion</th>
                <th style="padding:10px 14px;text-align:right;font-family:Barlow,'Segoe UI',Arial,sans-serif;font-size:10px;font-weight:700;color:#ffffff;text-transform:uppercase;letter-spacing:.5px;">Valor</th>
              </tr>
            </thead>
            <tbody>{table_rows}</tbody>
          </table>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body></html>""".format(
        table_rows="".join(table_rows),
    )


def send_rates_email(rates: dict[str, Any], table_id: str) -> dict[str, Any]:
    dry_run = os.environ.get("CAMBIO_DIVISA_EMAIL_DRY_RUN", "false").strip().lower() in {
        "1",
        "true",
        "yes",
    }
    recipients, recipients_source = resolve_email_recipients()
    logging.info(
        "Destinatarios resueltos desde %s: %s",
        recipients_source,
        len(recipients),
    )
    subject = os.environ.get(
        "CAMBIO_DIVISA_EMAIL_SUBJECT",
        "Tipo de cambio de divisa actualizado",
    ).strip()
    from_email = os.environ.get("SENDGRID_FROM_EMAIL", "noreply@proan.com").strip()

    if dry_run:
        return {
            "to": from_email,
            "cc": recipients,
            "subject": subject,
            "status": "dry_run",
            "recipients_source": recipients_source,
            "message": "Envio simulado por CAMBIO_DIVISA_EMAIL_DRY_RUN=true.",
        }

    api_key = os.environ.get("SENDGRID_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError(
            "SENDGRID_API_KEY no esta configurada. "
            "Define la variable en .env y vuelve a desplegar el Cloud Run Job."
        )

    import sendgrid
    from sendgrid.helpers.mail import Cc, Mail

    html_content = build_email_html(rates, table_id)
    sg_client = sendgrid.SendGridAPIClient(api_key)

    message = Mail(
        from_email=from_email,
        to_emails=from_email,
        subject=subject,
        html_content=html_content,
    )
    for recipient in recipients:
        message.add_cc(Cc(recipient))
    response = sg_client.send(message)

    return {
        "to": from_email,
        "cc": recipients,
        "subject": subject,
        "status": "sent",
        "recipients_source": recipients_source,
        "status_code": response.status_code,
        "message": "Correo enviado via SendGrid.",
    }


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    project_id = "proan-quantrue"
    dataset_id = "ZZ_PRUEBAS"
    table_name = "Cambio_divisa_diario"

    if BANXICO_API_TOKEN == "REEMPLAZAR_CON_TOKEN_BANXICO":
        raise ValueError("Debes reemplazar BANXICO_API_TOKEN por el token real de Banxico.")

    table_id = f"{project_id}.{dataset_id}.{table_name}"
    client = bigquery.Client(project=project_id)

    logging.info("Consultando Banxico")
    rates = build_rates()
    logging.info("Tipos calculados: %s", rates)

    logging.info("Verificando tabla en BigQuery: %s", table_id)
    ensure_table(client, table_id)

    logging.info("Escribiendo historico en BigQuery")
    write_history_row(client, table_id, rates)

    logging.info("Recuperando fila anterior para el correo")
    email_rates = fetch_previous_rates_for_email(client, table_id, rates["process_date"])

    logging.info("Enviando correo de cambio de divisa")
    email_result = send_rates_email(email_rates, table_id)
    logging.info("Resultado envio correo: %s", email_result)

    logging.info("Proceso completado correctamente")


if __name__ == "__main__":
    main()
