FROM condaforge/miniforge3:latest

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# netCDF4 через conda-forge (гарантированно с HDF4)
RUN conda install -y -c conda-forge \
    "python>=3.12,<3.13" \
    "netcdf4>=1.7,<1.7.4" \
    numpy geopandas pyproj shapely \
    && conda clean -afy

# Остальное через pip
RUN pip install --no-cache-dir \
    "earthaccess>=0.12" \
    "APScheduler>=3.10,<4.0" \
    "fastapi>=0.115" \
    "uvicorn>=0.30" \
    "requests>=2.31" \
    "PyYAML>=6.0" \
    "cdsapi>=0.7"

COPY data/ /app/data/
COPY download_modis.py process_modis.py download_era5.py process_era5.py run.py api_client.py ./
COPY config/ /app/config/

RUN mkdir -p /app/modis_data /app/era5_data

# Проверка HDF4 при сборке
RUN python -c "import netCDF4; print('netCDF4', netCDF4.__version__, '- HDF4 OK')"

EXPOSE 8000

HEALTHCHECK --interval=60s --timeout=10s --start-period=30s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"

CMD ["python", "run.py"]
