FROM node:22-bookworm-slim

WORKDIR /app

# Install system dependencies: Python3 + pip
RUN apt-get update && apt-get install -y \
    python3 python3-pip \
    && rm -rf /var/lib/apt/lists/*

# Install BeautifulSoup4
RUN pip3 install beautifulsoup4 --break-system-packages

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
