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

# Create directories
RUN mkdir -p data/canvas

EXPOSE 8000

CMD ["python", "main.py", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--config-dir", "configs", \
     "--refresh", "900", \
     "--history-depth", "10", \
     "--data-dir", "data/canvas"]
