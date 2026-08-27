# Reporte diario de cuentas contables PROAN

## Alcance

Genera diariamente, a partir de `D30_INTEGRATION.sap_faglflext_rt` (única fuente de importes;
antes `sap_faglflext`, cambiado el 2026-08-21 -- mismo esquema y saldos, se actualiza con mayor
frecuencia),
un PDF de 7 secciones -- una por página -- y lo envía por correo con un resumen visual
(tarjetas + gráfico) en el cuerpo del mensaje.

Cubre 5 cuentas, pero Mermas y Descuentos salen cada una en **dos formas** porque no está
decidido cuál es el criterio correcto y finanzas tiene que elegir viéndolas lado a lado:

| # | Sección | Forma |
|---|---|---|
| 1 | Gastos no Deducibles | Importe |
| 2 | Pasivo Temporal | Importe |
| 3 | Mermas — Importe | Importe |
| 4 | Mermas — % sobre Costo Total | Razón |
| 5 | Descuentos y Bonificaciones — Importe | Importe |
| 6 | Descuentos y Bonificaciones — % sobre Ingresos | Razón |
| 7 | Variación de Precios | Importe |

Pasivo Temporal (`RACCT 0002090000`) se agregó el 2026-08-27 a pedido del usuario -- misma
Plantilla A que Gastos no Deducibles (neto Debe-Haber, sin ratio propia), ver la nota en
`config.py` junto a `CUENTAS["Pasivo Temporal"]`.

- **Importe** (Plantilla A): solo la cantidad económica de la cuenta en cada sociedad, año
  actual vs. anterior, diferencia y % de variación entre periodos.
- **Razón** (Plantilla B): la cuenta contra su base en los dos periodos --- Mermas sobre el
  Costo Total (grupo de cuentas CTOS, `RACCT 000504%`), Descuentos sobre los Ingresos.

Las cinco cuentas usan las mismas columnas de periodo (año en curso vs. año anterior), por
decisión explícita del usuario. En **Variación de Precios** eso tiene una salvedad importante,
avisada y aceptada: el cierre anual reclasifica esa cuenta y borra del ejercicio cerrado
movimientos que sí existían cuando el año estaba abierto, así que la mayoría de sociedades tiene
saldo cero en el año previo y su % sale como ±100.0%. La sección lleva `NOTA_PRECIOS` al pie del
PDF explicándolo; la evidencia (comparación contra el árbol de ZF01 de diciembre de 2024) está
junto a esa constante en `config.py`. La columna fiable de esa cuenta es la del año en curso.

Las dos formas de una cuenta salen de la **misma** consulta: no se pregunta a BigQuery dos
veces por cuenta. Cuando finanzas decida, se quita la sección que sobre de
`generar_reporte.py` y `enviar_reporte.py` (y su entrada en `TITULOS_SECCION`); nada más.

El denominador del Costo Total quedó confirmado el 2026-08-17 contra el Excel de finanzas
(cuadra al peso en 9 de 12 sociedades comparables) --- ver la nota larga junto a
`RACCT_PREFIX_COSTOS` en `config.py`, que además documenta que las columnas históricas de ese
Excel están corridas un año.

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

- `SENDGRID_API_KEY`: API key de SendGrid.
- `SENDGRID_FROM_EMAIL`: remitente verificado. Por defecto `noreply@proan.com`.
- `REPORTE_CUENTAS_EMAIL_TO`: **ya no se usa** (se retiró el 2026-08-20 al pasar la lista a
  Firestore). El `deploy.sh` todavía la inyecta; es inofensiva, pero puede
  borrarse en el próximo cambio del script.
- `REPORTE_CUENTAS_EMAIL_DRY_RUN`: si vale `true`, el Job no envía correo real (para probar
  en producción sin gastar un envío -- el flag `--dry-run` no se puede pasar a un Cloud Run Job).
- `FIRESTORE_DATABASE_ID` / `FIRESTORE_LISTS_COLLECTION` / `REPORTE_CUENTAS_LIST_ID`: normalmente
  no hace falta tocarlos, los defaults ya son correctos.
- `OUTPUT_DIR`: solo para Cloud Run (`/tmp/salidas`, la inyecta `deploy.sh`).

## Uso local

```bash
python generar_reporte.py                 # genera el PDF de hoy
python enviar_reporte.py --dry-run         # lee la lista de Firestore, no envía nada real
python enviar_reporte.py --to a@b.com      # override explícito, salta la lista de Firestore
```

## Despliegue

```bash
bash deploy.sh
```

Job: `reporte-cuentas-diario`. Scheduler: `0 17 * * 1-6` (lunes a sábado, 17:00
America/Mexico_City) -- a la misma hora que `resultado-financiero-diario`, para que los dos
reportes lleguen juntos (cambiado el 2026-08-27, a petición del usuario; antes 14:00 desde el
2026-08-20, y 07:15 antes de eso). Muy separado de Anticipos (10:00), Partidas (10:10) y
Clientes bloqueados (10:20).

El `.env` queda excluido del build mediante `.gcloudignore`. Si cambias `.env`, vuelve a
ejecutar `bash deploy.sh` -- ejecutar el Job a mano solo usa la configuración ya desplegada.
