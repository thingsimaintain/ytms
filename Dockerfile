# Use Python 3.11 slim image for smaller size
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies for yt-dlp and ffmpeg
RUN apt-get update && apt-get install -y \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Copy the entire project
COPY . .

# Install the ytms package first
RUN pip install --no-cache-dir .

# Install web-app requirements (includes Flask, gunicorn, etc.)
RUN pip install --no-cache-dir -r web-app/requirements.txt

# Create directory for temporary downloads
RUN mkdir -p /app/downloads && chmod 777 /app/downloads

# Set environment variables
ENV FLASK_APP=web-app/main.py
ENV PYTHONUNBUFFERED=1
ENV DOWNLOAD_DIR=/app/downloads

# Set working directory to web-app
WORKDIR /app/web-app

# Expose port 5000
EXPOSE 5000

# Use gunicorn for production
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "2", "--timeout", "300", "--log-level", "info", "main:app"]
