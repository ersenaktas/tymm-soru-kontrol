FROM python:3.12-slim

# Install system dependencies, Xvfb for virtual display, fonts, and Playwright prerequisites
RUN apt-get update && apt-get install -y --no-install-recommends \
    xvfb \
    xauth \
    ca-certificates \
    curl \
    fonts-liberation \
    fonts-noto \
    fonts-freefont-ttf \
    libatk-bridge2.0-0 \
    libatk1.0-0 \
    libcups2 \
    libdrm2 \
    libgbm1 \
    libgtk-3-0 \
    libnss3 \
    libx11-xcb1 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxkbcommon0 \
    libxrandr2 \
    libxss1 \
    libxtst6 \
    xdg-utils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy project files
COPY . /app

# Install Python dependencies
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -e ".[notebooklm,web]"

# Install Playwright browser
RUN python -m playwright install chromium || true

# Ensure entrypoint is executable
RUN chmod +x /app/entrypoint.sh

# Environment variables
ENV DISPLAY=:99
ENV PILOT_PORT=8765
ENV PILOT_HOST=0.0.0.0
ENV PILOT_IDLE_TIMEOUT_SECONDS=0

EXPOSE 8765

CMD ["/app/entrypoint.sh"]
