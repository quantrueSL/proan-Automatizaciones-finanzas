#!/bin/bash

set -euo pipefail

PROJECT_ID="proan-quantrue"
REGION="us-west4"
JOB_NAME="reporte-cuentas-diario"
SCHEDULER_JOB_NAME="reporte-cuentas-diario-scheduler"
REPOSITORY_IMAGE="gcr.io/${PROJECT_ID}/${JOB_NAME}"

# PENDIENTE DE CONFIRMAR: horario provisional, lunes a sabado a las 07:15 de Mexico (antes
# de que el equipo entre), para no chocar con Anticipos (10:00) ni Partidas (10:10). Ajustar
# si se pide otra hora.
SCHEDULER_CRON="15 7 * * 1-6"
SCHEDULER_TIMEZONE="America/Mexico_City"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${YELLOW}Desplegando reporte diario de cuentas contables PROAN...${NC}"

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

# PENDIENTE DE CONFIRMAR: destinatario real de produccion. Mientras no se confirme el correo
# de Luis Enrique, el deploy exige pasarlo explicito (REPORTE_EMAIL_TO en .env o exportado)
# en vez de caer solo en el EMAIL_DESTINATARIO_DEFAULT de config.py (una cuenta de prueba).
REPORTE_EMAIL_TO_VALUE="$(strip_newlines "${REPORTE_EMAIL_TO:-}")"
require_value "REPORTE_EMAIL_TO" "${REPORTE_EMAIL_TO_VALUE}"
echo -e "${GREEN}REPORTE_EMAIL_TO detectada en .env/export: ${REPORTE_EMAIL_TO_VALUE}${NC}"

if [ ! -f "main.py" ]; then
  echo "Error: no se encuentra main.py"
  echo "Ejecuta este script desde la carpeta 'Reportes diarios contables'"
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
  containerregistry.googleapis.com

echo -e "${YELLOW}Construyendo imagen...${NC}"
gcloud builds submit --tag "${REPOSITORY_IMAGE}" .

echo -e "${YELLOW}Desplegando Cloud Run Job...${NC}"
gcloud run jobs deploy "${JOB_NAME}" \
  --image "${REPOSITORY_IMAGE}" \
  --region "${REGION}" \
  --memory 1Gi \
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
  --update-env-vars "^~^REPORTE_EMAIL_TO=${REPORTE_EMAIL_TO_VALUE}~SENDGRID_FROM_EMAIL=${SENDGRID_FROM_EMAIL:-noreply@proan.com}~SENDGRID_API_KEY=${SENDGRID_API_KEY_VALUE}~OUTPUT_DIR=/tmp/salidas"

SCHEDULER_SA="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"
JOB_URI="https://${REGION}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${PROJECT_NUMBER}/jobs/${JOB_NAME}:run"

echo -e "${YELLOW}Concediendo permisos al Scheduler para ejecutar el Job...${NC}"
gcloud run jobs add-iam-policy-binding "${JOB_NAME}" \
  --region "${REGION}" \
  --member "serviceAccount:${SCHEDULER_SA}" \
  --role "roles/run.invoker" >/dev/null

# El Job en sí corre bajo esta misma cuenta (${SCHEDULER_SA}, la de compute por defecto) --
# necesita permiso de lectura en BigQuery sobre proan-quantrue (D30_INTEGRATION,
# D20_DIMENSION) o el primer "gcloud run jobs execute" fallará con un 403 de BigQuery.
# Si el proyecto no le dio ya ese rol a nivel de proyecto, descomenta y ajusta:
# gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
#   --member "serviceAccount:${SCHEDULER_SA}" \
#   --role "roles/bigquery.dataViewer"
# gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
#   --member "serviceAccount:${SCHEDULER_SA}" \
#   --role "roles/bigquery.jobUser"

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
  --format="value(spec.template.spec.template.spec.containers[0].env[].name)" | tr ',' '\n' | grep -E 'REPORTE_|SENDGRID_|OUTPUT_DIR' || true
echo -e "${GREEN}Cloud Run Job:${NC} ${JOB_NAME}"
echo -e "${GREEN}Cloud Scheduler:${NC} ${SCHEDULER_JOB_NAME}"
echo -e "${GREEN}Horario:${NC} ${SCHEDULER_CRON} (${SCHEDULER_TIMEZONE})"
echo -e "${GREEN}Ejecucion manual:${NC}"
echo "gcloud run jobs execute ${JOB_NAME} --region ${REGION} --wait"
