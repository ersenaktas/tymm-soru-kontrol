FROM python:3.12-slim

# Install system dependencies, Xvfb for virtual display, fonts, gnupg, curl, and Chrome
RUN apt-get update && apt-get install -y --no-install-recommends \
    xvfb \
    xauth \
    ca-certificates \
    curl \
    gnupg \
    wget \
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

# Install Google Chrome stable (provides /opt/google/chrome/chrome for Playwright channel 'chrome')
RUN wget -q -O - https://dl-ssl.google.com/linux/linux_signing_key.pub | gpg --dearmor -o /usr/share/keyrings/google-chrome.gpg \
    && echo "deb [arch=amd64 signed-by=/usr/share/keyrings/google-chrome.gpg] http://dl.google.com/linux/chrome/deb/ stable main" > /etc/apt/sources.list.d/google-chrome.list \
    && apt-get update && apt-get install -y --no-install-recommends google-chrome-stable \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy project files
COPY . /app

# Install Python dependencies
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -e ".[notebooklm,web]"

# Install Playwright browser dependencies and chromium
RUN python -m playwright install --with-deps chromium || true

# Ensure entrypoint is executable
RUN chmod +x /app/entrypoint.sh

# Environment variables
ENV DISPLAY=:99
ENV PILOT_PORT=8765
ENV PILOT_HOST=0.0.0.0
ENV PILOT_IDLE_TIMEOUT_SECONDS=0

EXPOSE 8765

CMD ["/app/entrypoint.sh"]
