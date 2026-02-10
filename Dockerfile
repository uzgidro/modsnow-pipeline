FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY data/ /app/data/
COPY download_modis.py process_modis.py run.py api_client.py ./

COPY config/ /app/config/

RUN mkdir -p /app/modis_data

EXPOSE 8000

HEALTHCHECK --interval=60s --timeout=10s --start-period=30s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"

CMD ["python", "run.py"]
