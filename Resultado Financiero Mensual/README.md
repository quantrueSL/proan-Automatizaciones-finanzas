# Resultado Financiero Mensual PROAN

## Alcance

Genera el día 1 de cada mes, a partir de `D30_INTEGRATION.sap_faglflext`, Ingresos/Egresos/
Resultado por sociedad para los **últimos 2 meses ya cerrados** (el mes en curso no aparece).
Ambos meses llevan un chequeo de estabilidad contra un snapshot de ~14 días atrás (los
cierres de SAP siguen recibiendo ajustes 2-4 semanas) -- el mes marcado `PROVISIONAL` puede
seguir moviéndose, `SIN_REFERENCIA` significa que no había snapshot con qué comparar.

**Hueco de cobertura conocido:** la query no captura Ingresos/Egresos de SCO1 (plan de
cuentas PCSD, posición de dígito distinta a la del resto) -- ver memoria del proyecto
(`resultado-financiero-mensual-proyecto`) para el detalle, pendiente de decisión.

## Envío automático a destinatarios

El mismo Cloud Run Job envía el correo automáticamente al terminar de generar el PDF.
El destinatario principal es el remitente genérico configurado en `SENDGRID_FROM_EMAIL`; los
destinatarios reales van en copia (`Cc`).

Origen de destinatarios (cascada, ver `enviar_reporte.py`):

1. Firestore, base `proan-lista-mails`, colección `lists`, documento `resultado_financiero_mensual`.
2. Si Firestore no existe, está deshabilitado o no tiene emails válidos: `RESULTADO_MENSUAL_EMAIL_TO`.
3. Si tampoco hay valor en entorno: destinatario por defecto hardcodeado en `config.py`.

## Configuración (`.env`, ver `.env.example`)

- `SENDGRID_API_KEY` / `SENDGRID_FROM_EMAIL`: credenciales de SendGrid (independientes de las
  de "Reportes diarios contables").
- `RESULTADO_MENSUAL_EMAIL_TO`: fallback de destinatarios (nivel 2 de la cascada).
- `RESULTADO_MENSUAL_EMAIL_DRY_RUN`: si vale `true`, el Job no envía correo real.
- `FIRESTORE_DATABASE_ID` / `FIRESTORE_LISTS_COLLECTION` / `RESULTADO_MENSUAL_LIST_ID`:
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

Job separado: `resultado-financiero-mensual`. Scheduler: `0 8 1 * *` (día 1 de cada mes, 08:00
America/Mexico_City).
