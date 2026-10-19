# Evidencia diaria de alertas de precio

## Qué hace

Cada día (lunes a sábado, 17:00 de España) envía por correo la **evidencia de las alertas de precio graves cuya
factura ya está disponible**: un único correo con un PDF adjunto por sociedad. Por cada alerta, el PDF tiene dos páginas:

1. **Ficha**: precio facturado frente al oficial, por qué salta la alerta, contexto (lo que suele pagar el cliente y
   el resto de clientes), gráfica de 6 meses (cada punto es una línea de factura) y datos de la venta (cliente,
   factura, oficina, usuario que facturó).
2. **Facturas**: primero la factura de la alerta y, separada por una línea, una factura del mismo producto a su
   precio habitual, reconstruidas desde el
   CFDI con el aspecto de la factura impresa, con el producto y el precio recuadrados en rojo.

Es una **recapitulación**: las alertas cuya factura todavía no ha llegado se quedan pendientes y salen el día en que
llega. Si a los 10 días no ha llegado, la alerta sale igualmente sin factura.

## Cómo funciona por dentro

```
Cloud Scheduler (17:00 España, L-S)
   └─> Cloud Run Job "alertas-precios-evidencia"  (main.py)
         1. generar_evidencia.py
              · datos.py      lee de BigQuery las alertas enviadas los últimos días (price_alerts_AAAAMMDD)
              · alertas.py    las agrupa (sociedad + cliente + material + precio), quita los falsos positivos de CCP,
                              se queda con las 10 de mayor impacto de cada día y quita las ya enviadas
              · datos.py      busca sus facturas CFDI  ->  lista / esperando / caducada (10 días sin factura)
              · datos.py      trae el histórico de precios y facturas candidatas a "precio habitual"
              · pdf.py        portada + ficha (graficos.py) + facturas de cada alerta
              -> salidas/evidencia_alertas_precios_AAAA-MM-DD_<SOCIEDAD>.pdf (uno por sociedad)  y  manifiesto_AAAA-MM-DD.json
         2. enviar_evidencia.py
              · destinatarios de Firestore (lists/alertas-precios-evidencia)
              · un solo correo por SendGrid con resumen en el cuerpo y un PDF adjunto por sociedad
              · si SendGrid confirma, apunta las alertas en D60_REPORTING.evidencia_precios_enviadas
```

| Archivo | Para qué |
|---|---|
| `config.py` | Ajustes: tablas, plazo (10 días), alertas por día (10), tope por correo y sociedad (20), colores, textos |
| `formato.py` | Formato de importes, fechas y nombres |
| `datos.py` | Todas las consultas a BigQuery y la escritura en la tabla de control |
| `alertas.py` | Lógica: agrupar, elegir, estado de cada alerta, qué factura enseñar |
| `graficos.py` | Gráfica del histórico de precio |
| `pdf.py` | Maquetación del PDF |
| `generar_evidencia.py` / `enviar_evidencia.py` / `main.py` | Los dos pasos del job y su encadenado |
| `crear_tablas.sql` | Crea la tabla de control (una sola vez) |

### Reglas importantes

- **Fuente de las alertas**: las tablas diarias `price_alerts_AAAAMMDD` (lo que se envió ese día), no
  `PRECIOS_AMPLIADO`, que se recalcula a diario y cambia las alertas de días pasados.
- **Cruce con la factura**: RFC emisor de la sociedad + folio CFDI = últimos 7 dígitos de la factura SAP + fecha.
- **Factura a precio habitual**: venta del mismo producto y sociedad en los 30 días anteriores, a ±5 % del precio
  esperado, con el producto en su propia línea y nunca a otra empresa del grupo.
- **Facturas globales de mostrador** (Público en general): el CFDI no desglosa productos; se muestra su cabecera con
  las líneas del producto tomadas de SAP.
- **Episodio masivo**: si el mismo material y precio aparece en 5 clientes o más el mismo día, es una sola alerta.

## Configuración (`.env`, ver `.env.example`)

- `SENDGRID_API_KEY`, `SENDGRID_FROM_EMAIL`: igual que el resto de reportes.
- `ALERTAS_EVIDENCIA_EMAIL_DRY_RUN`: `true` = genera el PDF pero no envía ni registra nada. **Dejar en `true` hasta
  validar el primer envío.**
- `ALERTAS_EVIDENCIA_LIST_ID`: documento de Firestore con los destinatarios (por defecto `alertas-precios-evidencia`).
- `FECHA_EJECUCION`: solo pruebas locales, para ejecutar como si fuera otro día.

## Uso local

```bash
python generar_evidencia.py                                   # PDF de hoy en salidas/
FECHA_EJECUCION=2026-09-08 python generar_evidencia.py        # como si fuera el 8 de septiembre
python enviar_evidencia.py --dry-run                          # vista previa del correo, sin enviar
python enviar_evidencia.py --to tu@correo.com                 # envío de prueba a una dirección (no registra)
```

## Puesta en marcha (una sola vez)

1. **Tabla de control**: ejecutar `crear_tablas.sql` en BigQuery.
2. **Destinatarios**: crear en Firestore (base `proan-lista-mails`) el documento `lists/alertas-precios-evidencia`
   con `emails` (array) y `enabled: true`.
3. **Permisos** de la cuenta de servicio de compute: lectura en BigQuery (`bigquery.dataViewer`, `bigquery.jobUser`),
   escritura en `D60_REPORTING` (`bigquery.dataEditor`) y lectura de Firestore (`datastore.viewer`).
4. **Desplegar**: `bash deploy.sh` (con `.env` creado a partir de `.env.example`).
5. **Probar**: `gcloud run jobs execute alertas-precios-evidencia --region us-west4 --wait` con DRY_RUN=true y revisar
   el log; después poner DRY_RUN=false y volver a desplegar.

## Dependencias externas

- **Alertas del día** (`D60_REPORTING.price_alerts_AAAAMMDD`): las crea el DAG `proan_cobranza` de Airflow hacia las
  14:40 UTC del día siguiente. Si el DAG falla o corre antes de que SAP termine de cargar, la tabla del día queda vacía
  o no existe y esas alertas no salen nunca: hay que relanzar `alert_price` para esa fecha.
- **Carga de CFDI** (`D30_INTEGRATION.cfdi_completo`): sin facturas no hay evidencia. Se vacía y se rellena entera cada
  día (~14:35-15:40 UTC) desde `D00_SANDBOX.cfdi_cabecera/conceptos`. El CFDI de una venta llega con horas o 1-2 días
  de retraso; es normal: la alerta espera y sale cuando llega. Del 9 al 14-oct-2026 la carga se quedó parada en el
  8-oct sin dar error: si pasa algo así, las alertas se acumulan como "esperando".
- **Puesta en marcha** (19-oct-2026): se marcaron como enviadas en la tabla de control las alertas de ventas
  anteriores al 15-oct-2026 (sin correo), para que el primer envío no arrastre el atraso.
