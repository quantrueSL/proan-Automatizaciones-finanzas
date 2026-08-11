#!/bin/bash

set -euo pipefail

PROJECT_ID="proan-quantrue"
REGION="us-west4"
JOB_NAME="resultado-financiero-diario"
SCHEDULER_JOB_NAME="resultado-financiero-diario-scheduler"
REPOSITORY_IMAGE="gcr.io/${PROJECT_ID}/${JOB_NAME}"

# Confirmado con el usuario (2026-08-07): Job SEPARADO del Job "reporte-cuentas-diario" (las
# 4 cuentas contables) -- no comparten Dockerfile, imagen, ni horario. 07:45 L-S: 30 minutos
# después de ese Job (07:15) para no competir por recursos y salir poco después.
SCHEDULER_CRON="45 7 * * 1-6"
SCHEDULER_TIMEZONE="America/Mexico_City"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${YELLOW}Desplegando Resultado Financiero Diario PROAN...${NC}"

# Carpeta autónoma (2026-08-07): ya NO cae al .env de "Reportes diarios contables" -- cada
# automatización tiene su propio .env, ver .env.example. Crea uno aquí antes de desplegar.
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
echo -e "${GREEN}SENDGRID_API_KEY detectada, longitud: ${#SENDGRID_API_KEY_VALUE} caracteres.${NC}"

# Variable propia de este reporte (2026-08-07, ya no comparte REPORTE_EMAIL_TO con los otros
# dos) -- nivel 2 de la cascada Firestore -> env -> default, ver enviar_reporte.py.
RESULTADO_DIARIO_EMAIL_TO_VALUE="$(strip_newlines "${RESULTADO_DIARIO_EMAIL_TO:-}")"
require_value "RESULTADO_DIARIO_EMAIL_TO" "${RESULTADO_DIARIO_EMAIL_TO_VALUE}"
echo -e "${GREEN}RESULTADO_DIARIO_EMAIL_TO detectada: ${RESULTADO_DIARIO_EMAIL_TO_VALUE}${NC}"

if [ ! -f "main.py" ]; then
  echo "Error: no se encuentra main.py"
  echo "Ejecuta este script desde la carpeta 'Resultado Financiero Diario'"
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
  --memory 1Gi \
  --cpu 1 \
  --task-timeout 900 \
  --max-retries 1

# Archivo YAML temporal en vez de "--update-env-vars" inline: en Git Bash (Windows) cualquier
# argumento que parezca ruta POSIX se "traduce" a ruta de Windows antes de llegar a gcloud
# (mismo problema ya documentado en "Reportes diarios contables/deploy.sh").
ENV_VARS_FILE="$(mktemp)"
trap 'rm -f "${ENV_VARS_FILE}"' EXIT
cat > "${ENV_VARS_FILE}" <<EOF
RESULTADO_DIARIO_EMAIL_TO: ${RESULTADO_DIARIO_EMAIL_TO_VALUE}
RESULTADO_DIARIO_EMAIL_DRY_RUN: "${RESULTADO_DIARIO_EMAIL_DRY_RUN:-false}"
RESULTADO_DIARIO_LIST_ID: ${RESULTADO_DIARIO_LIST_ID:-resultado_financiero_diario}
FIRESTORE_DATABASE_ID: ${FIRESTORE_DATABASE_ID:-proan-lista-mails}
FIRESTORE_LISTS_COLLECTION: ${FIRESTORE_LISTS_COLLECTION:-lists}
SENDGRID_FROM_EMAIL: ${SENDGRID_FROM_EMAIL:-noreply@proan.com}
SENDGRID_API_KEY: ${SENDGRID_API_KEY_VALUE}
OUTPUT_DIR: /tmp/salidas
EOF

echo -e "${YELLOW}Configurando variables de entorno del Cloud Run Job...${NC}"
gcloud run jobs update "${JOB_NAME}" \
  --region "${REGION}" \
  --project "${PROJECT_ID}" \
  --env-vars-file "${ENV_VARS_FILE}"

SCHEDULER_SA="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"
JOB_URI="https://${REGION}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${PROJECT_NUMBER}/jobs/${JOB_NAME}:run"

echo -e "${YELLOW}Concediendo permisos al Scheduler para ejecutar el Job...${NC}"
# No fatal: la cuenta con la que se despliega (quantrue4@proan.com, rol Editor) no tiene
# permiso run.jobs.setIamPolicy -- ese permiso está deliberadamente excluido del rol Editor
# (solo Owner/roles admin de IAM lo tienen). Sin este binding, el Scheduler se crea igual pero
# el Job le devolverá 403 al intentar invocarlo -- hace falta que alguien con más permisos
# corra el mismo comando una vez (se imprime abajo si falla).
if ! gcloud run jobs add-iam-policy-binding "${JOB_NAME}" \
  --region "${REGION}" \
  --member "serviceAccount:${SCHEDULER_SA}" \
  --role "roles/run.invoker" >/dev/null 2>&1; then
  echo -e "${YELLOW}AVISO: no se pudo asignar el permiso run.invoker (falta run.jobs.setIamPolicy en la cuenta actual).${NC}"
  echo -e "${YELLOW}El Scheduler se va a crear igual, pero NO podrá invocar el Job hasta que alguien con más permisos corra:${NC}"
  echo "  gcloud run jobs add-iam-policy-binding ${JOB_NAME} --region ${REGION} --member serviceAccount:${SCHEDULER_SA} --role roles/run.invoker --project ${PROJECT_ID}"
fi

# El Job en sí corre bajo esta misma cuenta -- necesita permiso de lectura en BigQuery sobre
# proan-quantrue (D30_INTEGRATION, D20_DIMENSION). Si el proyecto no le dio ya ese rol a nivel
# de proyecto (ej. porque ya se hizo para "reporte-cuentas-diario"), descomenta y ajusta:
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
  --format="value(spec.template.spec.template.spec.containers[0].env[].name)" | tr ',' '\n' | grep -E 'RESULTADO_DIARIO_|SENDGRID_|OUTPUT_DIR|FIRESTORE_' || true
echo -e "${GREEN}Cloud Run Job:${NC} ${JOB_NAME}"
echo -e "${GREEN}Cloud Scheduler:${NC} ${SCHEDULER_JOB_NAME}"
echo -e "${GREEN}Horario:${NC} ${SCHEDULER_CRON} (${SCHEDULER_TIMEZONE})"
echo -e "${GREEN}Ejecucion manual:${NC}"
echo "gcloud run jobs execute ${JOB_NAME} --region ${REGION} --wait"
