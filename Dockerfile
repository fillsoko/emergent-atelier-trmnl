FROM python:3.11-slim

WORKDIR /app

# Install system dependencies for Pillow/scipy
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpng-dev \
    libjpeg-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

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
