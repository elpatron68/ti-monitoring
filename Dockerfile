FROM python:3.9-slim

# Build-time version injection
ARG TI_VERSION="unbekannt"
ARG TI_COMMIT="unbekannt"
ENV TI_VERSION=${TI_VERSION}
ENV TI_COMMIT=${TI_COMMIT}
ENV HTTP_PROXY=${HTTP_PROXY}
ENV HTTPS_PROXY=${HTTPS_PROXY}

# Set working directory
WORKDIR /app

# Copy requirements and install dependencies
COPY requirements.txt .
RUN apt-get update \
 && apt-get install -y --no-install-recommends fonts-dejavu-core \
 && rm -rf /var/lib/apt/lists/* \
 && pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .



# Expose port for web app
EXPOSE 8050

# Use fewer workers to reduce resource contention
CMD ["gunicorn", "--bind", "0.0.0.0:8050", "--workers", "2", "app:server"]
