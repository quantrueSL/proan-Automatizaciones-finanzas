-- Tabla de control de la evidencia de alertas de precio. Se ejecuta UNA sola vez (consola de BigQuery o bq query).
-- Cada fila es una alerta que ya se envió con su evidencia; así no se repite y las pendientes se reconocen solas.

CREATE TABLE IF NOT EXISTS `proan-quantrue.D60_REPORTING.evidencia_precios_enviadas` (
  alerta_id          STRING  NOT NULL OPTIONS(description = "Identificador de la alerta agrupada (fecha, sociedad, cliente, material, unidad y precio)"),
  fecha_alerta       DATE             OPTIONS(description = "Día de la venta que generó la alerta"),
  sociedad           STRING,
  material           STRING,
  cliente            STRING,
  facturas           ARRAY<STRING>    OPTIONS(description = "Facturas SAP que forman la alerta"),
  factura_mostrada   STRING           OPTIONS(description = "Factura SAP cuya factura se incluyó en el PDF"),
  uuid               STRING           OPTIONS(description = "Folio fiscal del CFDI mostrado (vacío si no llegó)"),
  factura_referencia STRING           OPTIONS(description = "Factura SAP usada como precio normal"),
  con_factura        BOOL             OPTIONS(description = "FALSE si se envió sin factura por superar el plazo"),
  impacto_mxn        FLOAT64,
  fecha_envio        TIMESTAMP        OPTIONS(description = "Momento del envío del correo")
)
PARTITION BY DATE(fecha_envio)
OPTIONS(description = "Alertas de precio enviadas con evidencia (job alertas-precios-evidencia)");
