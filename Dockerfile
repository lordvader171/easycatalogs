FROM node:22-bookworm-slim

# Install system dependencies for Python, Playwright/Firefox and Xvfb
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    python3 \
    python3-pip \
    xvfb \
    python3-tk \
    python3-dev \
    xauth \
    libnss3 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libasound2 \
    libpango-1.0-0 \
    libcairo2 \
    libgl1 \
    libglib2.0-0 \
    libfontconfig1 \
    libfreetype6 \
    xdotool \
    fluxbox \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements and install Python dependencies
COPY requirements.txt ./
RUN pip3 install --no-cache-dir -r requirements.txt --break-system-packages && \
    python3 -m camoufox fetch

# Copy package files first for better caching
COPY package*.json ./

# Install npm dependencies
RUN npm install --omit=dev

# Copy application source code
COPY . .

# Expose the port the app runs on
EXPOSE 7171

# Start the application
CMD ["npm", "start"]
