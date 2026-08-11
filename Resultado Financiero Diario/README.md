# Resultado Financiero Diario PROAN

## Alcance

Genera diariamente, a partir de `D30_INTEGRATION.sap_faglflext`, un cuadre contable por
sociedad: Balance vs. Estado de Resultados (deben coincidir en teoría; `Dif. != 0` señala
sociedades con algo mal clasificado o pendiente de revisar). PDF con header, tarjetas KPI,
gráfico top 5, tabla con estatus por sociedad e insights automáticos. Envía el PDF por correo
con el mismo contenido visible en el cuerpo del mensaje.

**Sin validar contra SAP ZF01 en vivo todavía** -- ver memoria del proyecto
(`resultado-financiero-diario-proyecto`) para el detalle de qué falta confirmar antes de
tratar las cifras como definitivas.

## Envío automático a destinatarios

El mismo Cloud Run Job envía el correo automáticamente al terminar de generar el PDF.
El destinatario principal es el remitente genérico configurado en `SENDGRID_FROM_EMAIL`; los
destinatarios reales van en copia (`Cc`).

Origen de destinatarios (cascada, ver `enviar_reporte.py`):

1. Firestore, base `proan-lista-mails`, colección `lists`, documento `resultado_financiero_diario`.
2. Si Firestore no existe, está deshabilitado o no tiene emails válidos: `RESULTADO_DIARIO_EMAIL_TO`.
3. Si tampoco hay valor en entorno: destinatario por defecto hardcodeado en `config.py`.

## Configuración (`.env`, ver `.env.example`)

- `SENDGRID_API_KEY` / `SENDGRID_FROM_EMAIL`: credenciales de SendGrid (independientes de las
  de "Reportes diarios contables" -- esta carpeta ya no depende de ese `.env`).
- `RESULTADO_DIARIO_EMAIL_TO`: fallback de destinatarios (nivel 2 de la cascada).
- `RESULTADO_DIARIO_EMAIL_DRY_RUN`: si vale `true`, el Job no envía correo real.
- `FIRESTORE_DATABASE_ID` / `FIRESTORE_LISTS_COLLECTION` / `RESULTADO_DIARIO_LIST_ID`:
  normalmente no hace falta tocarlos.
- `OUTPUT_DIR`: solo para Cloud Run (`/tmp/salidas`, la inyecta `deploy.sh`).

## Uso local

```bash
python generar_reporte.py
python enviar_reporte.py --dry-run
python enviar_reporte.py --to a@b.com   # override, salta la cascada
```

## Despliegue

```bash
bash deploy.sh
```

Job separado del de las 4 cuentas contables: `resultado-financiero-diario`. Scheduler:
`45 7 * * 1-6` (lunes a sábado, 07:45 America/Mexico_City -- 30 min después del Job de las 4
cuentas).
