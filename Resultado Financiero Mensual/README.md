# Resultado Financiero Mensual PROAN

## Alcance

Genera el día 1 de cada mes, a partir de `D30_INTEGRATION.sap_faglflext_rt`, Ingresos/Egresos/
Resultado por sociedad para los **últimos 2 meses ya cerrados** (el mes en curso no aparece).
Ambos meses llevan un chequeo de estabilidad contra un snapshot de ~14 días atrás (los
cierres de SAP siguen recibiendo ajustes 2-4 semanas) -- el mes marcado `PROVISIONAL` puede
seguir moviéndose, `SIN_REFERENCIA` significa que no había snapshot con qué comparar.

**Fuente de datos (aclaración, 2026-08-17; tabla actualizada 2026-08-21):** todos los importes
que se reportan salen exclusivamente de `proan-quantrue.D30_INTEGRATION.sap_faglflext_rt`
(antes `sap_faglflext` -- mismo esquema y saldos, se actualiza con mayor frecuencia). Los
snapshots `D10_POSTPROCESSING.sap_faglflext2_YYYYMMDD` **no aportan ninguna cifra al
reporte**: se leen solo como referencia histórica para el chequeo de estabilidad, porque
`sap_faglflext_rt` es una tabla viva sin histórico y sin una foto anterior no hay forma de
saber si un mes cerrado sigue moviéndose. Decisión del usuario (2026-08-17): mantener el
snapshot con ese único uso en lugar de perder el chequeo. Si algún día se quita, el reporte lee
solo `sap_faglflext_rt` pero desaparece la columna de estatus.

**Superdoña Comercial (SCO1): resuelto el 2026-08-17.** Esa sociedad usa el plan de cuentas
`PCSD` (cuentas de 6 dígitos rellenadas a 10, dígito significativo en la posición 5, no en la 4),
así que la clasificación original no veía ninguna de sus cuentas de resultados: salía todo en cero
y el filtro de "sin actividad reciente" la quitaba del reporte **sin ningún aviso**, pese a tener
del orden de $234M de ingresos. Ya se incluye — el reporte pasó de 17 a 18 sociedades.

Validado contra el Excel de finanzas de 2024 (corte de junio): Ingresos a **0.0009%** del valor
publicado, Egresos a **+0.59%** — misma banda y mismo signo que el resto de sociedades, o sea
desviación por apuntes posteriores a la foto, no por clasificación errónea. Comprobado además que
las otras 17 sociedades conservan **exactamente** los mismos importes. Detalle de la
correspondencia dígito → Ingresos/Egresos en la nota junto a `_FILTRO_CUENTAS_RES` en `datos.py`.

## Envío automático a destinatarios

El mismo Cloud Run Job envía el correo automáticamente al terminar de generar el PDF.
El destinatario principal es el remitente genérico configurado en `SENDGRID_FROM_EMAIL`; los
destinatarios reales van en copia (`Cc`).

Origen de destinatarios (`get_mailing_list()` en `enviar_reporte.py`):

La lista vive **solo** en Firestore: base `proan-lista-mails`, colección `lists`, documento
`reportes-financieros` (campos `emails` como array de strings y `enabled` como booleano). Es el
mismo documento para los tres reportes financieros, así que un cambio ahí los afecta a los tres.

Para cambiar quién recibe el reporte se edita ese documento y **no hace falta redesplegar**.

Si el documento no existe, tiene `enabled: false`, trae `emails` mal formado o Firestore no
responde, `get_mailing_list()` devuelve una lista vacía, deja una advertencia en el log y el Job
termina sin enviar y **sin fallar**. Ya no hay fallback a variable de entorno ni a correos
hardcodeados: si la lista se apaga, no sale correo — que es justo lo que se busca al apagarla,
pero conviene saberlo.

## Configuración (`.env`, ver `.env.example`)

- `SENDGRID_API_KEY` / `SENDGRID_FROM_EMAIL`: credenciales de SendGrid (independientes de las
  de "Reportes diarios contables").
- `RESULTADO_MENSUAL_EMAIL_TO`: **ya no se usa** (se retiró el 2026-08-20 al pasar la lista a
  Firestore). El `deploy.sh` todavía la inyecta; es inofensiva, pero puede
  borrarse en el próximo cambio del script.
- `RESULTADO_MENSUAL_EMAIL_DRY_RUN`: si vale `true`, el Job no envía correo real.
- `FIRESTORE_DATABASE_ID` / `FIRESTORE_LISTS_COLLECTION` / `RESULTADO_MENSUAL_LIST_ID`:
  normalmente no hace falta tocarlos.
- `OUTPUT_DIR`: solo para Cloud Run (`/tmp/salidas`, la inyecta `deploy.sh`).

## Uso local

```bash
python generar_reporte.py
python enviar_reporte.py --dry-run
python enviar_reporte.py --to a@b.com   # override, salta la lista de Firestore
```

## Despliegue

```bash
bash deploy.sh
```

Job separado: `resultado-financiero-mensual`. Scheduler: `0 8 1 * *` (día 1 de cada mes, 08:00
America/Mexico_City).
