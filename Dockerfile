FROM python:3.9-slim

# Set working directory
WORKDIR /app

# Copy requirements and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create a non-root user
RUN useradd --create-home --shell /bin/bash appuser
USER appuser

# Expose port for web app
EXPOSE 8050

# Default command to run the web app with Gunicorn
CMD ["gunicorn", "--bind", "0.0.0.0:8050", "--workers", "4", "app:server"]