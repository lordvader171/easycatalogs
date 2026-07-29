FROM node:22-bookworm-slim

# Install system dependencies for Python, Playwright/Firefox, Xvfb and Cloudflare Warp dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    git \
    iproute2 \
    iptables \
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
    gnupg2 \
    lsb-release \
    libgl1 \
    libglib2.0-0 \
    libfontconfig1 \
    libfreetype6 \
    libgtk-3-0 \
    libdbus-glib-1-2 \
    libxt6 \
    xdotool \
    fluxbox \
    && rm -rf /var/lib/apt/lists/*

# Prefer IPv4 when both A and AAAA records are available.
RUN printf 'precedence ::ffff:0:0/96  100\n' >> /etc/gai.conf

# Install Cloudflare Warp
RUN curl -fsSL https://pkg.cloudflareclient.com/pubkey.gpg | gpg --yes --dearmor --output /usr/share/keyrings/cloudflare-warp-archive-keyring.gpg && \
    echo "deb [signed-by=/usr/share/keyrings/cloudflare-warp-archive-keyring.gpg] https://pkg.cloudflareclient.com/ $(lsb_release -cs) main" | tee /etc/apt/sources.list.d/cloudflare-client.list && \
    apt-get update && apt-get install -y cloudflare-warp && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Environment Settings
ENV NODE_ENV=production
ENV IN_DOCKER=true
ENV NODE_OPTIONS=--dns-result-order=ipv4first

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

# Ensure entrypoint is executable
RUN chmod +x entrypoint.sh

# Expose the port the app runs on
EXPOSE 7171

# Start the application using entrypoint.sh (starts warp-svc and connects before node app)
CMD ["./entrypoint.sh"]
