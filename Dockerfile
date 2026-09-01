FROM python:3.12-slim

# The server never performs interactive browser login. Authentication is
# injected as a secret; only certificates and report fonts are needed here.
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    fonts-liberation \
    fonts-noto \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy project files (Dockerfile-side excludes are handled by .dockerignore)
COPY . /app

# Install Python dependencies
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -e ".[notebooklm-server,web]"

# Render.com and other cloud hosts supply PORT; fall back to 8765
ENV PILOT_PORT=8765
ENV PILOT_HOST=0.0.0.0
ENV PILOT_IDLE_TIMEOUT_SECONDS=0

# Render sets PORT at runtime – the app reads it in main()
EXPOSE 8765

CMD ["python", "-m", "pilot.web"]
