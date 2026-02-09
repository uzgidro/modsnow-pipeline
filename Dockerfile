FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY data/ /app/data/
COPY download_modis.py process_modis.py run.py api_client.py ./

RUN mkdir -p /app/modis_data

HEALTHCHECK --interval=60s --timeout=10s --start-period=30s \
    CMD python -c "import os; assert os.path.exists('/app/data/ca_catchments.shp')"

CMD ["python", "run.py"]
