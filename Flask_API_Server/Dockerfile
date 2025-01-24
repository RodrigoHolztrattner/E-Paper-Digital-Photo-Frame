FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    gcc \
    python3-dev \
    libffi-dev \
    netcat-traditional && \
    rm -rf /var/lib/apt/lists/*

# Create required directories
RUN mkdir -p /app/config /app/images

# Copy requirements first to leverage Docker cache
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY . .

# Create volumes for persistent data
VOLUME [ "/app/config", "/app/images" ]

# Expose ports - explicitly specify protocols
EXPOSE 9999/tcp
EXPOSE 9998/udp

# Set environment variables
ENV FLASK_APP=flask_server.py \
    FLASK_ENV=production \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    BROADCAST_INTERVAL=2.0 \
    PYTHONIOENCODING=utf-8 \
    HOST_IP="" \
    IMMICH_URL=http://localhost \
    IMMICH_API_KEY="" \
    IMAGE_PATH=/app/images

# Create simple start script - no need for -u flag since PYTHONUNBUFFERED is set
RUN echo '#!/bin/bash\n\
exec python flask_server.py' > /app/start.sh && \
    chmod +x /app/start.sh

# Add labels for required capabilities
LABEL capabilities="NET_ADMIN NET_BROADCAST" \
      description="E-Paper Digital Photo Frame Server - Requires NET_ADMIN and NET_BROADCAST capabilities"

# Note: Run with --cap-add NET_ADMIN --cap-add NET_BROADCAST
# Run the application
CMD ["./start.sh"]