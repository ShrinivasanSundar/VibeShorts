# Production Dockerfile for VibeShorts Backend
FROM python:3.11-slim

# Install system dependencies: FFmpeg (with libass), fonts, and audio libraries
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libass9 \
    fonts-montserrat \
    fontconfig \
    libsm6 \
    libxext6 \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Update font cache
RUN fc-cache -fv

WORKDIR /app

# Copy requirements and install Python packages
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY . .

# Expose HTTP port
EXPOSE 8000

# Run FastAPI server with Uvicorn
CMD ["uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
