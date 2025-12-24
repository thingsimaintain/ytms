# Use Python 3.11 slim image for smaller size
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies for yt-dlp and ffmpeg
RUN apt-get update && apt-get install -y \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better layer caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the ytms package from parent directory
COPY ../ytms /app/ytms

# Copy web-app files
COPY . .

# Create directory for temporary downloads
RUN mkdir -p /app/downloads && chmod 777 /app/downloads

# Set environment variables
ENV FLASK_APP=main.py
ENV PYTHONUNBUFFERED=1
ENV DOWNLOAD_DIR=/app/downloads

# Expose port 5000
EXPOSE 5000

# Use gunicorn for production (or waitress on Windows)
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "2", "--timeout", "300", "--log-level", "info", "main:app"]
