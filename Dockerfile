FROM python:3.9-slim

# Set working directory
WORKDIR /app

# Copy requirements and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create the data file during build
RUN python -c "from mylibrary import *; initialize_data_file('data.hdf5')" || echo "Data file creation failed, will be created at runtime"

# Expose port for web app
EXPOSE 8050

# Default command to run the web app with Gunicorn
CMD ["gunicorn", "--bind", "0.0.0.0:8050", "--workers", "4", "app:server"]