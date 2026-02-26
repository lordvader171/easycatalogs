FROM node:20-alpine

WORKDIR /app

# Install system dependencies (needed for sqlite3 build)
RUN apk add --no-cache python3 make g++

# Copy package files first for better caching
COPY package*.json ./

# Install dependencies
RUN npm install

# Copy application source code
COPY . .

# Expose the port the app runs on
EXPOSE 7171

# Start the application
CMD ["npm", "start"]
