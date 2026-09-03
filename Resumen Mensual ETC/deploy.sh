#!/bin/bash

set -euo pipefail

PROJECT_ID="proan-quantrue"
REGION="us-west4"
JOB_NAME="resumen-mensual-etc"
SCHEDULER_JOB_NAME="resumen-mensual-etc-scheduler"
REPOSITORY_IMAGE="gcr.io/${PROJECT_ID}/${JOB_NAME}"

# Día 1 de cada mes, 08:00 America/Mexico_City -- mismo horario que "Resultado Financiero
# Mensual" (el otro reporte mensual de este repo), por consistencia. Ajustable: si el
# cierre de datos de ETC (D60_REPORTING) tarda más en estar listo, correr unos días
# después (ej. "0 8 3 * *" para el día 3) -- detectar_mes_cerrado() en datos.py ya busca
# dinámicamente el último mes con MES_CONTABLE < mes en curso, así que no hay que tocar
# código para eso, solo esta fecha si se corre antes de que los datos estén listos.
SCHEDULER_CRON="0 8 1 * *"
SCHEDULER_TIMEZONE="America/Mexico_City"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${YELLOW}Desplegando Resumen Ejecutivo Mensual ETC...${NC}"

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

# A diferencia de los otros reportes, este NUNCA tuvo una cascada a variable de entorno
# para destinatarios -- Firestore (lists/reporte_mensual_etc) es la única fuente desde el
# día uno, así que no hay un *_EMAIL_TO que exigir aquí.

if [ ! -f "main.py" ]; then
  echo "Error: no se encuentra main.py"
  echo "Ejecuta este script desde la carpeta 'Resumen Mensual ETC'"
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

echo -e "${YELLOW}Construyendo imagen (incluye Chromium -- tarda más que los otros reportes)...${NC}"
gcloud builds submit --tag "${REPOSITORY_IMAGE}" .

echo -e "${YELLOW}Desplegando Cloud Run Job...${NC}"
# Memoria/timeout más altos que los demás reportes de este repo: Chromium headless (PNG +
# PDF) consume bastante más RAM que matplotlib/ReportLab, y renderizar dos veces (PNG y
# PDF) más las queries de BigQuery puede tardar más que los 900s de margen de los otros.
gcloud run jobs deploy "${JOB_NAME}" \
  --image "${REPOSITORY_IMAGE}" \
  --region "${REGION}" \
  --memory 2Gi \
  --cpu 2 \
  --task-timeout 1200 \
  --max-retries 1

# Archivo YAML temporal en vez de "--update-env-vars" inline: en Git Bash (Windows) cualquier
# argumento que parezca ruta POSIX se "traduce" a ruta de Windows antes de llegar a gcloud
# (mismo problema ya documentado en los demás deploy.sh de este repo).
ENV_VARS_FILE="$(mktemp)"
trap 'rm -f "${ENV_VARS_FILE}"' EXIT
cat > "${ENV_VARS_FILE}" <<EOF
RESUMEN_MENSUAL_ETC_EMAIL_DRY_RUN: "${RESUMEN_MENSUAL_ETC_EMAIL_DRY_RUN:-false}"
RESUMEN_MENSUAL_ETC_LIST_ID: ${RESUMEN_MENSUAL_ETC_LIST_ID:-reporte_mensual_etc}
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
# permiso run.jobs.setIamPolicy (excluido deliberadamente del rol Editor). Sin este
# binding, el Scheduler se crea igual y SÍ puede invocar el Job de todos modos -- el rol
# Editor a nivel de proyecto ya incluye run.jobs.run (confirmado con los otros 3 reportes
# de este repo, ver memoria del proyecto). Este binding es solo un endurecimiento opcional
# de mínimo privilegio, no bloqueante.
if ! gcloud run jobs add-iam-policy-binding "${JOB_NAME}" \
  --region "${REGION}" \
  --member "serviceAccount:${SCHEDULER_SA}" \
  --role "roles/run.invoker" >/dev/null 2>&1; then
  echo -e "${YELLOW}AVISO: no se pudo asignar el permiso run.invoker (falta run.jobs.setIamPolicy en la cuenta actual). No es bloqueante.${NC}"
  echo "  gcloud run jobs add-iam-policy-binding ${JOB_NAME} --region ${REGION} --member serviceAccount:${SCHEDULER_SA} --role roles/run.invoker --project ${PROJECT_ID}"
fi

# El Job en sí corre bajo esta misma cuenta -- necesita permiso de lectura en BigQuery sobre
# proan-quantrue (D60_REPORTING). Si el proyecto no le dio ya ese rol a nivel de proyecto,
# descomenta y ajusta:
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
  --format="value(spec.template.spec.template.spec.containers[0].env[].name)" | tr ',' '\n' | grep -E 'RESUMEN_MENSUAL_ETC_|SENDGRID_|OUTPUT_DIR|FIRESTORE_' || true
echo -e "${GREEN}Cloud Run Job:${NC} ${JOB_NAME}"
echo -e "${GREEN}Cloud Scheduler:${NC} ${SCHEDULER_JOB_NAME}"
echo -e "${GREEN}Horario:${NC} ${SCHEDULER_CRON} (${SCHEDULER_TIMEZONE})"
echo -e "${GREEN}Ejecucion manual:${NC}"
echo "gcloud run jobs execute ${JOB_NAME} --region ${REGION} --wait"
