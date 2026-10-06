FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Se copian los módulos uno a uno (nunca "COPY . .") para no meter en la imagen el .env, las salidas ni pruebas.
COPY config.py formato.py datos.py alertas.py graficos.py pdf.py generar_evidencia.py enviar_evidencia.py main.py ./

# Cloud Run Job: un solo proceso que genera el PDF y lo envía (ver main.py). No expone ningún puerto.
CMD ["python", "main.py"]
