#!/bin/bash

set -euo pipefail

PROJECT_ID="proan-quantrue"
REGION="us-west4"
JOB_NAME="anticipos-diario"
SCHEDULER_JOB_NAME="anticipos-diario-scheduler"
REPOSITORY_IMAGE="gcr.io/${PROJECT_ID}/${JOB_NAME}"

# Lunes a sabado a las 10:00 de Mexico. El espejo de BSIK se recarga cada dos horas,
# asi que a esa hora el dato es del mismo dia.
SCHEDULER_CRON="0 10 * * 1-6"
SCHEDULER_TIMEZONE="America/Mexico_City"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${YELLOW}Desplegando reporte diario de anticipos...${NC}"

if [ -f ".env" ]; then
  set -o allexport
  source .env
  set +o allexport
fi

strip_newlines() {
  printf "%s" "$1" | tr -d '\r\n'
}

require_value() {
  local name="$1"
  local value="$2"
  if [[ -z "$value" ]]; then
    echo "Error: falta $name. Definelo en .env o exportalo antes de ejecutar deploy.sh." >&2
    exit 1
  fi
}

SENDGRID_API_KEY_VALUE="$(strip_newlines "${SENDGRID_API_KEY:-}")"
require_value "SENDGRID_API_KEY" "${SENDGRID_API_KEY_VALUE}"
echo -e "${GREEN}SENDGRID_API_KEY detectada en .env/export, longitud: ${#SENDGRID_API_KEY_VALUE} caracteres.${NC}"

if [ ! -f "anticipos.py" ]; then
  echo "Error: no se encuentra anticipos.py"
  echo "Ejecuta este script desde la carpeta Anticipos"
  exit 1
fi

if [ ! -f "Dockerfile" ]; then
  echo "Error: no se encuentra Dockerfile"
  exit 1
fi

echo -e "${YELLOW}Configurando proyecto...${NC}"
gcloud config set project "${PROJECT_ID}"
PROJECT_NUMBER="$(gcloud projects describe "${PROJECT_ID}" --format='value(projectNumber)')"

echo -e "${YELLOW}Habilitando APIs necesarias...${NC}"
gcloud services enable \
  cloudbuild.googleapis.com \
  run.googleapis.com \
  cloudscheduler.googleapis.com \
  bigquery.googleapis.com \
  firestore.googleapis.com \
  containerregistry.googleapis.com

echo -e "${YELLOW}Construyendo imagen...${NC}"
gcloud builds submit --tag "${REPOSITORY_IMAGE}" .

echo -e "${YELLOW}Desplegando Cloud Run Job...${NC}"
gcloud run jobs deploy "${JOB_NAME}" \
  --image "${REPOSITORY_IMAGE}" \
  --region "${REGION}" \
  --memory 512Mi \
  --cpu 1 \
  --task-timeout 900 \
  --max-retries 1

# Ojo: no metas comentarios entre las lineas de este comando. Cada linea acaba en \
# para continuar, y un # en medio corta el comando ahi y despliega con la mitad de las
# variables sin avisar.
echo -e "${YELLOW}Configurando variables de entorno del Cloud Run Job...${NC}"
gcloud run jobs update "${JOB_NAME}" \
  --region "${REGION}" \
  --project "${PROJECT_ID}" \
  --update-env-vars "^~^ANTICIPOS_EMAIL_DRY_RUN=${ANTICIPOS_EMAIL_DRY_RUN:-false}~ANTICIPOS_ONLY_SOCIEDADES=${ANTICIPOS_ONLY_SOCIEDADES:-}~ANTICIPOS_EMAIL_TO=${ANTICIPOS_EMAIL_TO:-pcoma@quantrue.com}~ANTICIPOS_MAX_ANTIGUEDAD_HORAS=${ANTICIPOS_MAX_ANTIGUEDAD_HORAS:-6}~SENDGRID_FROM_EMAIL=${SENDGRID_FROM_EMAIL:-noreply@proan.com}~SENDGRID_API_KEY=${SENDGRID_API_KEY_VALUE}~FIRESTORE_DATABASE_ID=${FIRESTORE_DATABASE_ID:-proan-lista-mails}~FIRESTORE_LISTS_COLLECTION=${FIRESTORE_LISTS_COLLECTION:-lists}~ANTICIPOS_LIST_ID=${ANTICIPOS_LIST_ID:-anticipos}"

SCHEDULER_SA="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"
JOB_URI="https://${REGION}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${PROJECT_NUMBER}/jobs/${JOB_NAME}:run"

echo -e "${YELLOW}Concediendo permisos al Scheduler para ejecutar el Job...${NC}"
gcloud run jobs add-iam-policy-binding "${JOB_NAME}" \
  --region "${REGION}" \
  --member "serviceAccount:${SCHEDULER_SA}" \
  --role "roles/run.invoker" >/dev/null

echo -e "${YELLOW}Creando o actualizando Cloud Scheduler...${NC}"
if gcloud scheduler jobs describe "${SCHEDULER_JOB_NAME}" --location "${REGION}" >/dev/null 2>&1; then
  gcloud scheduler jobs update http "${SCHEDULER_JOB_NAME}" \
    --location "${REGION}" \
    --schedule "${SCHEDULER_CRON}" \
    --time-zone "${SCHEDULER_TIMEZONE}" \
    --uri "${JOB_URI}" \
    --http-method POST \
    --oauth-service-account-email "${SCHEDULER_SA}" \
    --oauth-token-scope "https://www.googleapis.com/auth/cloud-platform"
else
  gcloud scheduler jobs create http "${SCHEDULER_JOB_NAME}" \
    --location "${REGION}" \
    --schedule "${SCHEDULER_CRON}" \
    --time-zone "${SCHEDULER_TIMEZONE}" \
    --uri "${JOB_URI}" \
    --http-method POST \
    --oauth-service-account-email "${SCHEDULER_SA}" \
    --oauth-token-scope "https://www.googleapis.com/auth/cloud-platform"
fi

echo -e "${GREEN}Deployment completado.${NC}"
echo -e "${YELLOW}Variables configuradas en el Cloud Run Job:${NC}"
gcloud run jobs describe "${JOB_NAME}" \
  --region "${REGION}" \
  --project "${PROJECT_ID}" \
  --format="value(spec.template.spec.template.spec.containers[0].env[].name)" | tr ',' '\n' | grep -E 'ANTICIPOS_|SENDGRID_|FIRESTORE_' || true
echo -e "${GREEN}Cloud Run Job:${NC} ${JOB_NAME}"
echo -e "${GREEN}Cloud Scheduler:${NC} ${SCHEDULER_JOB_NAME}"
echo -e "${GREEN}Horario:${NC} ${SCHEDULER_CRON} (${SCHEDULER_TIMEZONE})"
echo -e "${GREEN}Ejecucion manual:${NC}"
echo "gcloud run jobs execute ${JOB_NAME} --region ${REGION} --wait"
