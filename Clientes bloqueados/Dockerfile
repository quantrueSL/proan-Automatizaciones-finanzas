FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# WeasyPrint necesita Pango para maquetar el texto del PDF, y una tipografia de verdad:
# la imagen slim no trae ninguna, y sin fuentes el PDF sale con cuadraditos. Liberation
# Sans es compatible en metricas con Arial, que es el ultimo recurso de la pila de
# fuentes del correo, asi que el PDF conserva las proporciones del HTML.
RUN apt-get update && apt-get install -y --no-install-recommends \
      libpango-1.0-0 \
      libpangoft2-1.0-0 \
      fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY clientes_bloqueados.py .

CMD ["python", "clientes_bloqueados.py"]
