FROM python:3.11-slim@sha256:9358444059ed78e2975ada2c189f1c1a3144a5dab6f35bff8c981afb38946634

WORKDIR /app

# Install system dependencies for Pillow/scipy
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpng-dev \
    libjpeg-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt requirements-lock.txt ./
# Upgrade pip/setuptools/wheel first to fix CVEs (CVE-2025-8869, CVE-2026-1703, PYSEC-2025-49, CVE-2024-6345, CVE-2026-24049)
RUN pip install --no-cache-dir --upgrade pip==26.0 setuptools==78.1.1 wheel==0.46.2
RUN pip install --no-cache-dir -r requirements-lock.txt

COPY . .

# Create directories and non-root user
RUN mkdir -p data/canvas && \
    useradd -m -u 1001 appuser && \
    chown -R appuser:appuser /app

USER appuser

EXPOSE 8000

CMD ["python", "main.py", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--config-dir", "configs", \
     "--refresh", "900", \
     "--history-depth", "10", \
     "--data-dir", "data/canvas"]
