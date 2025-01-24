FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Copy application files
COPY . .

# Create required directories
RUN mkdir -p /app/config /app/images

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Create volumes for persistent data
VOLUME [ "/app/config", "/app/images" ]

# Expose ports
EXPOSE 9999/tcp  # Flask server port
EXPOSE 9998/udp  # Broadcast port

# Set environment variables
ENV FLASK_APP=flask_server.py \
    FLASK_ENV=production \
    FLASK_RUN_HOST=0.0.0.0 \
    FLASK_RUN_PORT=9999 \
    IMMICH_URL=http://localhost \
    IMMICH_API_KEY="" \
    IMAGE_PATH=/app/images

# Run the application
CMD ["python", "-u", "flask_server.py"]