FROM node:22-bookworm-slim

WORKDIR /app

# Install system dependencies: Python3 + Xvfb + Fluxbox + browser deps
RUN apt-get update && apt-get install -y \
    python3 python3-pip python3-venv python3-tk python3-dev \
    xvfb xauth xdotool fluxbox \
    libnss3 libnspr4 libatk-bridge2.0-0 libdrm2 libxkbcommon0 libxcomposite1 \
    libxdamage1 libxrandr2 libgbm1 libpango-1.0-0 libcairo2 libasound2 \
    libatspi2.0-0 libwayland-client0 libxfixes3 libgl1 libglib2.0-0 \
    libfontconfig1 libfreetype6 \
    && rm -rf /var/lib/apt/lists/*

# Install Python packages and pre-fetch Camoufox
RUN pip3 install --no-cache-dir "playwright==1.59.0" "scrapling[fetchers]" "curl_cffi" "camoufox[geoip]" pyautogui pygetwindow pyvirtualdisplay Pillow --break-system-packages && \
    python3 -m camoufox fetch


# Copy package files first for better caching
COPY package*.json ./

# Install npm dependencies
RUN npm install

# Copy application source code
COPY . .

# Expose the port the app runs on
EXPOSE 7171

# Start the application
CMD ["npm", "start"]
