FROM condaforge/miniforge3:latest AS deps

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Зависимости (редко меняются — кэшируется)
RUN conda install -y -c conda-forge \
    "python>=3.12,<3.13" \
    "netcdf4>=1.7,<1.7.4" \
    numpy geopandas pyproj shapely \
    && conda clean -afy \
    && pip install --no-cache-dir \
    "earthaccess>=0.12" \
    "APScheduler>=3.10,<4.0" \
    "fastapi>=0.115" \
    "uvicorn>=0.30" \
    "requests>=2.31" \
    "PyYAML>=6.0" \
    && python -c "import netCDF4; print('netCDF4', netCDF4.__version__, '- HDF4 OK')"

# --- Runtime stage ---
FROM deps AS runtime

WORKDIR /app

RUN useradd -r -m -s /usr/sbin/nologin appuser \
    && mkdir -p /app/modis_data \
    && chown -R appuser:appuser /app

# Данные (меняются редко)
COPY --chown=appuser:appuser data/ /app/data/
COPY --chown=appuser:appuser config/ /app/config/

# Код (меняется часто — последний слой)
COPY --chown=appuser:appuser download_modis.py process_modis.py run.py api_client.py ./

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=60s --timeout=10s --start-period=30s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"

CMD ["python", "run.py"]
