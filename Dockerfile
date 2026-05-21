# krai-insights app image — Python 3.12 + Microsoft ODBC 18 (for FleetMgmt MSSQL)
FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app \
    PIP_NO_CACHE_DIR=1

# --- System deps: MSSQL ODBC driver (pyodbc) + build essentials -------------
# Microsoft's prod.list references signed-by=/usr/share/keyrings/microsoft-prod.gpg,
# so the key must be dearmored to exactly that path (an armored .asc in
# trusted.gpg.d is NOT honored -> apt NO_PUBKEY error).
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl gnupg ca-certificates unixodbc-dev \
    && curl -fsSL https://packages.microsoft.com/keys/microsoft.asc \
        | gpg --dearmor -o /usr/share/keyrings/microsoft-prod.gpg \
    && curl -fsSL https://packages.microsoft.com/config/debian/12/prod.list \
        -o /etc/apt/sources.list.d/mssql-release.list \
    && apt-get update \
    && ACCEPT_EULA=Y apt-get install -y --no-install-recommends msodbcsql18 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# --- Python deps (cached layer) ---------------------------------------------
COPY requirements.txt ./
RUN pip install -r requirements.txt

# --- App code ----------------------------------------------------------------
COPY . .

EXPOSE 8501

# Default: run the Streamlit dashboard. ETL / migrations run via
#   docker compose run --rm app python scripts/migrate.py
CMD ["streamlit", "run", "insights/ui/app.py", \
     "--server.address=0.0.0.0", "--server.port=8501", \
     "--server.headless=true"]
