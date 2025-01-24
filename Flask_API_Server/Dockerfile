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

# Create non-root user
RUN useradd -m -r appuser && \
    mkdir -p /app/config /app/images && \
    chown -R appuser:appuser /app

# Copy requirements first to leverage Docker cache
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY . .

# Set proper permissions
RUN chown -R appuser:appuser /app

# Switch to non-root user
USER appuser

# Create volumes for persistent data
VOLUME [ "/app/config", "/app/images" ]

# Expose ports
EXPOSE 9999
EXPOSE 9998

# Set environment variables
ENV FLASK_APP=flask_server.py \
    FLASK_ENV=production \
    PYTHONUNBUFFERED=1 \
    GUNICORN_WORKERS=4 \
    GUNICORN_THREADS=2 \
    IMMICH_URL=http://localhost \
    IMMICH_API_KEY="" \
    IMAGE_PATH=/app/images

# Add healthcheck
HEALTHCHECK --interval=30s --timeout=30s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:9999/ || exit 1

# Create start script
COPY <<EOF /app/start.sh
#!/bin/bash
exec gunicorn \
    --bind 0.0.0.0:9999 \
    --workers \$GUNICORN_WORKERS \
    --threads \$GUNICORN_THREADS \
    --worker-class eventlet \
    --timeout 120 \
    --keep-alive 5 \
    --log-level info \
    --access-logfile - \
    --error-logfile - \
    'flask_server:app'
EOF

RUN chmod +x /app/start.sh

# Run the application
CMD ["./start.sh"]