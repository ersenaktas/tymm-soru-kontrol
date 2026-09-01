FROM python:3.12-slim

# Install system utilities, Xvfb for virtual display, and font packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    xvfb \
    xauth \
    ca-certificates \
    curl \
    fonts-liberation \
    fonts-noto \
    fonts-freefont-ttf \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy application files
COPY . /app

# Install Python dependencies
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -e ".[notebooklm,web]"

# Install Playwright Chromium and automatically install all required Linux system dependencies
RUN python -m playwright install --with-deps chromium

# Ensure entrypoint is executable
RUN chmod +x /app/entrypoint.sh

# Environment variables
ENV DISPLAY=:99
ENV PILOT_PORT=8765
ENV PILOT_HOST=0.0.0.0
ENV PILOT_IDLE_TIMEOUT_SECONDS=0

EXPOSE 8765

CMD ["/app/entrypoint.sh"]
