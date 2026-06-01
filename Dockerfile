FROM node:20-bookworm-slim

WORKDIR /app

# Install system dependencies: Python3 + Playwright browser deps
RUN apt-get update && apt-get install -y \
    python3 python3-pip \
    libnss3 libnspr4 libatk-bridge2.0-0 libdrm2 libxkbcommon0 libxcomposite1 \
    libxdamage1 libxrandr2 libgbm1 libpango-1.0-0 libcairo2 libasound2 \
    libatspi2.0-0 libwayland-client0 \
    && rm -rf /var/lib/apt/lists/*

# Install Scrapling + curl_cffi (TLS fingerprinting) + patchright (Playwright fork) + Chromium
RUN pip3 install scrapling curl_cffi playwright patchright --break-system-packages && \
    python3 -m playwright install chromium && \
    python3 -m playwright install-deps chromium

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
