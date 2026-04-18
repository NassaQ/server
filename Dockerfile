# STAGE 1: Builder (Best Practice: Multi-Stage)
# ============================================
FROM python:3.11.14-slim AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    unixodbc-dev \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.4.0 /uv /uvx /bin/

WORKDIR /build

COPY pyproject.toml ./
# If we optimized the uv.lock, then uncomment the next line to ensure strict versioning
# COPY uv.lock ./

RUN uv venv /opt/venv && \
    uv pip install --python /opt/venv -r pyproject.toml

# STAGE 2: Runtime Environment
# ============================
FROM python:3.11.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    ACCEPT_EULA=Y \
    PATH="/opt/venv/bin:$PATH"

# Microsoft ODBC Driver 18
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    gnupg \
    apt-transport-https \
    unixodbc \
    && curl -fsSL https://packages.microsoft.com/keys/microsoft.asc | gpg --dearmor -o /usr/share/keyrings/microsoft-prod.gpg \
    && curl -fsSL https://packages.microsoft.com/config/debian/12/prod.list | tee /etc/apt/sources.list.d/mssql-release.list \
    && apt-get update \
    && ACCEPT_EULA=Y apt-get install -y --no-install-recommends msodbcsql18 \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --shell /bin/bash user14

WORKDIR /server

COPY --from=builder /opt/venv /opt/venv

COPY ./app ./app

RUN chown -R user14:user14 /server

USER user14

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/ || exit 1

CMD ["gunicorn", "app.main:app", "-w", "9", "-k", "uvicorn.workers.UvicornWorker", "--bind", "0.0.0.0:8000", "--timeout", "120", "--graceful-timeout", "30"]