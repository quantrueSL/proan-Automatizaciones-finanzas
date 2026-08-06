FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# A diferencia de partidas.py (un solo archivo), este reporte está repartido en varios
# módulos -- se copian todos explícitamente (nunca "COPY . ." para no meter .env, __pycache__
# ni los scripts _tmp_*/_preview_* de scratch al build). fonts/ trae IBM Plex Sans/Mono
# embebidas: pdf.py y graficos.py las registran por ruta relativa a este archivo (ver
# config.py, _BASE_DIR), así que tienen que viajar junto con el código.
COPY config.py datos.py graficos.py pdf.py generar_reporte.py enviar_reporte.py main.py ./
COPY fonts/ fonts/

# Cloud Run Jobs corren un solo proceso -- main.py encadena generar_reporte + enviar_reporte
# (ver main.py). No hay servidor HTTP que exponer, por eso no hay EXPOSE/PORT como en un
# Cloud Run Service.
CMD ["python", "main.py"]
