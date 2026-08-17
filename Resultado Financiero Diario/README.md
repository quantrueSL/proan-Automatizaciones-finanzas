# Resultado Financiero Diario PROAN

## Alcance

Genera diariamente, a partir de `D30_INTEGRATION.sap_faglflext`, un cuadre contable por
sociedad: Balance vs. Estado de Resultados. PDF con header, tarjetas KPI, gráfico top 5, tabla
con estatus por sociedad e insights automáticos. Envía el PDF por correo con el mismo contenido
visible en el cuerpo del mensaje.

### Limitación importante de la columna `Dif.` (comprobado 2026-08-17)

**`Dif.` es 0.00 por construcción y no puede detectar un descuadre.** Es la suma de todos los
saldos de la sociedad, y la balanza de comprobación suma cero por partida doble, así que la
utilidad que sale del balance y la que sale del estado de resultados son forzosamente iguales.
Medido: máx `|Dif.|` = 0.0000 en las 20 sociedades de 2024 y las 19 de 2026, sin excepción.

Los descuadres que sí muestra ZF01 (en la tabla de referencia del PDF de finanzas: Proteína
Animal +$425,040 y Proan Alimentos −$529,200 al 13/12/2024) vienen de cuentas **no asignadas a
la estructura de balance/PyG PROA**, que el árbol de SAP deja fuera. Replicarlo exige las tablas
`T011` / `FAGL_011`, que **no están en BigQuery** (solo hay `SKA1`, `SKAT`, `SKB1`). Con los
datos de hoy ese descuadre no se puede calcular: no es un bug de la query. El PDF lleva una nota
de alcance al pie para que nadie lea el 0.00 como "todo conciliado" — ver
`pdf._nota_alcance` y el docstring de `datos.py`.

Corolario: **`Dif. == 0` no valida la clasificación BAL/RES** (cualquier partición en dos grupos
da cero). Para validarla hay que comparar contra el árbol de ZF01 sociedad por sociedad.

**Sin validar contra SAP ZF01 en vivo todavía** -- ver memoria del proyecto
(`resultado-financiero-diario-proyecto`). La comparación contra la tabla del PDF de finanzas
(13/12/2024) resultó inconcluyente: las diferencias van de −21% a −408% y cuatro sociedades
salen con signo opuesto, pero el PDF es una foto de año parcial y FY2024 se reclasificó después,
así que no se puede separar "clasificación incorrecta" de "los datos se movieron".

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
