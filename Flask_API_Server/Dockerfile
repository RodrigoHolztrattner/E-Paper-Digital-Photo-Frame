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
    IMMICH_URL=http://localhost \
    IMMICH_API_KEY="" \
    IMAGE_PATH=/app/images

# Create simple start script
RUN echo '#!/bin/bash\n\
exec python -u flask_server.py' > /app/start.sh && \
    chmod +x /app/start.sh

# Run the application
CMD ["./start.sh"]