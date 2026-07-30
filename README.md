# Automatizaciones Proan

Procesos automáticos de apoyo a reporting y operación de Proan, cada uno en su
propia carpeta con su propio despliegue.

## Automatizaciones

| Carpeta | Estado | Descripción |
|---|---|---|
| [`Cambio divisa`](Cambio%20divisa/README.md) | En producción | Obtiene diariamente el tipo de cambio oficial de Banco de México, lo guarda en BigQuery y envía un correo con los valores. |
| [`Anticipos`](Anticipos/README.md) | En pruebas | Calcula a diario los anticipos a proveedores por sociedad, guarda una foto en BigQuery y envía un correo por sociedad. |
| [`Partidas abiertas por compensar`](Partidas%20abiertas%20por%20compensar/README.md) | En pruebas | Lista a diario las partidas de cuentas de mayor sin compensar por sociedad, guarda una foto en BigQuery y envía un correo por sociedad. |
| `Reportes diarios contables` | Pendiente de desarrollo | — |

Cada carpeta con una automatización desarrollada incluye su propio `README.md`
con el detalle técnico, variables de entorno y pasos de deploy.

## Convenciones

- Cada automatización es independiente: su propio `Dockerfile`, `deploy.sh`,
  `requirements.txt` y `.env` (nunca versionado).
- Los secretos viven en `.env` local durante el desarrollo y se inyectan al
  desplegar (Cloud Run / Cloud Run Jobs); nunca se hardcodean en el código.
- El `.gitignore` en la raíz del repo excluye `.env`, credenciales y archivos
  de datos (`.csv`, `.xlsx`, etc.) para todas las automatizaciones.
