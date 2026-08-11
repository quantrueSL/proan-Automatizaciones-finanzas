# Reporte diario de cuentas contables PROAN

## Alcance

Genera diariamente, a partir de `D30_INTEGRATION.sap_faglflext`, un PDF con 4 secciones:
Gastos no Deducibles, Mermas, Descuentos y Bonificaciones, Variación de Precios. Envía el PDF
por correo con un resumen visual (tarjetas + gráfico) directamente en el cuerpo del mensaje.

## Envío automático a destinatarios

El mismo Cloud Run Job envía el correo automáticamente al terminar de generar el PDF.
El destinatario principal es el remitente genérico configurado en `SENDGRID_FROM_EMAIL`; los
destinatarios reales van en copia (`Cc`).

Origen de destinatarios (cascada, ver `enviar_reporte.py`):

1. Firestore, base `proan-lista-mails`, colección `lists`, documento `reporte_cuentas_diario`.
2. Si Firestore no existe, está deshabilitado o no tiene emails válidos: `REPORTE_CUENTAS_EMAIL_TO`.
3. Si tampoco hay valor en entorno: destinatario por defecto hardcodeado en `config.py`
   (`EMAIL_DESTINATARIO_DEFAULT`).

## Configuración (`.env`, ver `.env.example`)

- `SENDGRID_API_KEY`: API key de SendGrid.
- `SENDGRID_FROM_EMAIL`: remitente verificado. Por defecto `noreply@proan.com`.
- `REPORTE_CUENTAS_EMAIL_TO`: fallback de destinatarios separados por coma (nivel 2 de la
  cascada).
- `REPORTE_CUENTAS_EMAIL_DRY_RUN`: si vale `true`, el Job no envía correo real (para probar
  en producción sin gastar un envío -- el flag `--dry-run` no se puede pasar a un Cloud Run Job).
- `FIRESTORE_DATABASE_ID` / `FIRESTORE_LISTS_COLLECTION` / `REPORTE_CUENTAS_LIST_ID`: normalmente
  no hace falta tocarlos, los defaults ya son correctos.
- `OUTPUT_DIR`: solo para Cloud Run (`/tmp/salidas`, la inyecta `deploy.sh`).

## Uso local

```bash
python generar_reporte.py                 # genera el PDF de hoy
python enviar_reporte.py --dry-run         # cascada de destinatarios, no envía nada real
python enviar_reporte.py --to a@b.com      # override explícito, salta la cascada
```

## Despliegue

```bash
bash deploy.sh
```

Job: `reporte-cuentas-diario`. Scheduler: `15 7 * * 1-6` (lunes a sábado, 07:15
America/Mexico_City) -- antes de que el equipo entre, sin chocar con Anticipos (10:00) ni
Partidas (10:10).

El `.env` queda excluido del build mediante `.gcloudignore`. Si cambias `.env`, vuelve a
ejecutar `bash deploy.sh` -- ejecutar el Job a mano solo usa la configuración ya desplegada.
