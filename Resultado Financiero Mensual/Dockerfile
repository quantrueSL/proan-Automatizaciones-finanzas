FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Se copian los módulos explícitamente (nunca "COPY . ." para no meter .env, __pycache__ ni
# archivos de scratch al build) -- mismo criterio que "Reportes diarios contables/Dockerfile".
# fonts/ trae IBM Plex Sans/Mono embebidas, viaja con el código porque pdf.py/graficos.py las
# registran por ruta relativa (config.py, _BASE_DIR).
COPY config.py datos.py graficos.py pdf.py generar_reporte.py enviar_reporte.py main.py ./
COPY fonts/ fonts/

# Cloud Run Jobs corren un solo proceso -- main.py encadena generar_reporte + enviar_reporte.
# No hay servidor HTTP que exponer, por eso no hay EXPOSE/PORT como en un Cloud Run Service.
CMD ["python", "main.py"]
