# Automatizaciones Proan

Procesos automáticos de apoyo a reporting y operación de Proan, cada uno en su
propia carpeta con su propio despliegue.

## Automatizaciones

| Carpeta | Estado | Descripción |
|---|---|---|
| [`Cambio divisa`](Cambio%20divisa/README.md) | En producción | Obtiene diariamente el tipo de cambio oficial de Banco de México, lo guarda en BigQuery y envía un correo con los valores. |
| [`Anticipos`](Anticipos/README.md) | En pruebas | Calcula a diario los anticipos a proveedores por sociedad, guarda una foto en BigQuery y envía un correo por sociedad. |
| [`Partidas abiertas por compensar`](Partidas%20abiertas%20por%20compensar/README.md) | En pruebas | Lista a diario las partidas de cuentas de mayor sin compensar por sociedad, guarda una foto en BigQuery y envía un correo por sociedad. |
| [`Clientes bloqueados`](Clientes%20bloqueados/README.md) | En pruebas | Lee a diario los clientes bloqueados o en riesgo de bloqueo por sociedad (sin escribir en BigQuery) y envía un correo por sociedad. Desplegado; destinatarios aun de prueba. |
| [`Reportes diarios contables`](Reportes%20diarios%20contables/README.md) | En pruebas | Reporte diario en PDF de 4 cuentas contables (Gastos no Deducibles, Mermas, Descuentos y Bonificaciones, Variación de Precios), con resumen visual en el cuerpo del correo. Mermas y Descuentos van en dos formas (importe y % sobre su base) a la espera de que finanzas decida cuál es la correcta. |
| [`Resultado Financiero Diario`](Resultado%20Financiero%20Diario/README.md) | En pruebas | Cuadre contable diario por sociedad (Balance vs. Estado de Resultados) -- aún sin validar contra SAP ZF01 en vivo. |
| [`Resultado Financiero Mensual`](Resultado%20Financiero%20Mensual/README.md) | En pruebas | Ingresos/Egresos/Resultado por sociedad de los últimos 2 meses cerrados, con chequeo de estabilidad contra un snapshot de ~14 días atrás. |

Cada carpeta con una automatización desarrollada incluye su propio `README.md`
con el detalle técnico, variables de entorno y pasos de deploy.

## Convenciones

- Cada automatización es independiente: su propio `Dockerfile`, `deploy.sh`,
  `requirements.txt` y `.env` (nunca versionado).
- Los secretos viven en `.env` local durante el desarrollo y se inyectan al
  desplegar (Cloud Run / Cloud Run Jobs); nunca se hardcodean en el código.
- El `.gitignore` en la raíz del repo excluye `.env`, credenciales y archivos
  de datos (`.csv`, `.xlsx`, etc.) para todas las automatizaciones.
