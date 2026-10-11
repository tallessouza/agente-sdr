FROM python:3.13-slim
RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-por \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py handover.py sdr.py prospeccao.py leads.py importar_leads.py cloud.py template_health.py templates_db.py monitor.py fila.py retomada.py alertas.py ligacoes.py vigia.py .
COPY validate_fixtures.py simulate_fixtures.py ./
COPY fixtures ./fixtures
EXPOSE 8080
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080"]
