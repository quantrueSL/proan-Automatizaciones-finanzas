#!/bin/bash
# Despliega la evidencia diaria de alertas de precio como Cloud Run Job + Cloud Scheduler.
# Mismo esquema que "Reportes diarios contables". Ejecutar desde esta carpeta:  bash deploy.sh

set -euo pipefail

PROJECT_ID="proan-quantrue"
REGION="us-west4"
JOB_NAME="alertas-precios-evidencia"
SCHEDULER_JOB_NAME="alertas-precios-evidencia-scheduler"
REPOSITORY_IMAGE="gcr.io/${PROJECT_ID}/${JOB_NAME}"

# Lunes a sábado a las 15:30 de México. Las facturas de un día llegan sobre todo entre las 7:00 y las 14:00 del día
# siguiente, así que a esta hora ya está la mayoría (si la carga de CFDI a BigQuery se hace antes; ver README).
# Las ventas del sábado salen el lunes: el envío recoge siempre todo lo pendiente.
SCHEDULER_CRON="30 15 * * 1-6"
SCHEDULER_TIMEZONE="America/Mexico_City"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${YELLOW}Desplegando evidencia de alertas de precio...${NC}"

if [ -f ".env" ]; then
  set -o allexport
  source .env
  set +o allexport
fi

strip_newlines() { printf "%s" "$1" | tr -d '\r\n'; }

SENDGRID_API_KEY_VALUE="$(strip_newlines "${SENDGRID_API_KEY:-}")"
if [[ -z "${SENDGRID_API_KEY_VALUE}" ]]; then
  echo "Error: falta SENDGRID_API_KEY. Defínela en .env (ver .env.example)." >&2
  exit 1
fi

for f in main.py Dockerfile requirements.txt; do
  [ -f "$f" ] || { echo "Error: no se encuentra $f. Ejecuta este script desde la carpeta 'Alertas precios evidencia'."; exit 1; }
done

echo -e "${YELLOW}Configurando proyecto...${NC}"
gcloud config set project "${PROJECT_ID}"
PROJECT_NUMBER="$(gcloud projects describe "${PROJECT_ID}" --format='value(projectNumber)')"

echo -e "${YELLOW}Habilitando APIs necesarias...${NC}"
gcloud services enable cloudbuild.googleapis.com run.googleapis.com cloudscheduler.googleapis.com \
  bigquery.googleapis.com firestore.googleapis.com containerregistry.googleapis.com

# 1. Construir el contenedor en Cloud Build (no hace falta Docker en local)
echo -e "${YELLOW}Construyendo imagen...${NC}"
gcloud builds submit --tag "${REPOSITORY_IMAGE}" .

# 2. Crear o actualizar el Cloud Run Job
echo -e "${YELLOW}Desplegando Cloud Run Job...${NC}"
gcloud run jobs deploy "${JOB_NAME}" \
  --image "${REPOSITORY_IMAGE}" \
  --region "${REGION}" \
  --memory 2Gi \
  --cpu 1 \
  --task-timeout 900 \
  --max-retries 1

# Variables de entorno en un archivo (en Git Bash las rutas tipo /tmp se convierten a rutas de Windows si van inline)
ENV_VARS_FILE="$(mktemp)"
trap 'rm -f "${ENV_VARS_FILE}"' EXIT
cat > "${ENV_VARS_FILE}" <<EOF
SENDGRID_API_KEY: ${SENDGRID_API_KEY_VALUE}
SENDGRID_FROM_EMAIL: ${SENDGRID_FROM_EMAIL:-noreply@proan.com}
ALERTAS_EVIDENCIA_EMAIL_DRY_RUN: "${ALERTAS_EVIDENCIA_EMAIL_DRY_RUN:-true}"
ALERTAS_EVIDENCIA_LIST_ID: ${ALERTAS_EVIDENCIA_LIST_ID:-alertas-precios-evidencia}
FIRESTORE_DATABASE_ID: ${FIRESTORE_DATABASE_ID:-proan-lista-mails}
FIRESTORE_LISTS_COLLECTION: ${FIRESTORE_LISTS_COLLECTION:-lists}
OUTPUT_DIR: /tmp/salidas
EOF
gcloud run jobs update "${JOB_NAME}" --region "${REGION}" --project "${PROJECT_ID}" --env-vars-file "${ENV_VARS_FILE}"

# 3. Permisos. El job corre con la cuenta de servicio por defecto de compute. Necesita:
#    - leer BigQuery (D30_INTEGRATION, D60_REPORTING): roles/bigquery.dataViewer y roles/bigquery.jobUser
#    - escribir en la tabla de control D60_REPORTING.evidencia_precios_enviadas: roles/bigquery.dataEditor (dataset)
#    - leer Firestore (lista de correo): roles/datastore.viewer
#    Si el proyecto no se los da ya, alguien con permisos debe asignarlos (ver README).
SCHEDULER_SA="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"
JOB_URI="https://${REGION}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${PROJECT_NUMBER}/jobs/${JOB_NAME}:run"

echo -e "${YELLOW}Concediendo permiso al Scheduler para ejecutar el Job...${NC}"
if ! gcloud run jobs add-iam-policy-binding "${JOB_NAME}" --region "${REGION}" \
  --member "serviceAccount:${SCHEDULER_SA}" --role "roles/run.invoker" >/dev/null 2>&1; then
  echo -e "${YELLOW}AVISO: no se pudo asignar run.invoker. Que alguien con permisos ejecute:${NC}"
  echo "  gcloud run jobs add-iam-policy-binding ${JOB_NAME} --region ${REGION} --member serviceAccount:${SCHEDULER_SA} --role roles/run.invoker --project ${PROJECT_ID}"
fi

# 4. Programar la ejecución diaria
echo -e "${YELLOW}Creando o actualizando Cloud Scheduler...${NC}"
ACCION="create"
gcloud scheduler jobs describe "${SCHEDULER_JOB_NAME}" --location "${REGION}" >/dev/null 2>&1 && ACCION="update"
gcloud scheduler jobs "${ACCION}" http "${SCHEDULER_JOB_NAME}" \
  --location "${REGION}" \
  --schedule "${SCHEDULER_CRON}" \
  --time-zone "${SCHEDULER_TIMEZONE}" \
  --uri "${JOB_URI}" \
  --http-method POST \
  --oauth-service-account-email "${SCHEDULER_SA}" \
  --oauth-token-scope "https://www.googleapis.com/auth/cloud-platform"

echo -e "${GREEN}Despliegue completado.${NC}"
echo -e "${GREEN}Job:${NC} ${JOB_NAME} · ${GREEN}Horario:${NC} ${SCHEDULER_CRON} (${SCHEDULER_TIMEZONE})"
echo -e "${GREEN}Modo prueba (DRY_RUN):${NC} ${ALERTAS_EVIDENCIA_EMAIL_DRY_RUN:-true}"
echo "Ejecución manual: gcloud run jobs execute ${JOB_NAME} --region ${REGION} --wait"
