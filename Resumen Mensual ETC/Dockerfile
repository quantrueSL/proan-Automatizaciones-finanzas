FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# A diferencia de los demás reportes de este repo (matplotlib + ReportLab, sin navegador),
# este SÍ necesita un navegador real: render_png.py usa Chromium headless para convertir
# la plantilla HTML a PNG (imagen del correo) y a PDF (impresión con @page a medida) --
# ver la cabecera de ese archivo. fontconfig + fonts-liberation dan una alternativa
# razonable a Georgia/Segoe UI (que no existen en Linux) -- no va a ser un match exacto de
# fuente, pero sí legible y con las proporciones correctas; si el logo/tipografía se ve
# raro en el PDF/PNG generado en Cloud Run, empezar a revisar por aquí.
RUN apt-get update && apt-get install -y --no-install-recommends \
      chromium \
      fontconfig \
      fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Se copian los módulos explícitamente (nunca "COPY . ." para no meter .env, __pycache__ ni
# archivos de scratch al build) -- mismo criterio que los demás Dockerfile de este repo.
COPY config.py datos.py graficos.py render_png.py resumen_mensual_etc.py enviar_reporte.py main.py ./
COPY plantilla_resumen_mensual.html ./

# Cloud Run Jobs corren un solo proceso -- main.py encadena generación + envío. No hay
# servidor HTTP que exponer, por eso no hay EXPOSE/PORT como en un Cloud Run Service.
CMD ["python", "main.py"]
