const { createClient } = require('redis');

const redisUrl = process.env.REDIS_URL || 'redis://localhost:6379';

const client = createClient({
    url: redisUrl
});

client.on('error', (err) => console.error('Redis Client Error', err));
client.on('connect', () => console.log('Redis Client Connected'));

// Connect to Redis on startup
client.connect().catch(console.error);

async function get(key) {
    try {
        const value = await client.get(key);
        if (!value) return null;
        try {
            return JSON.parse(value);
        } catch (e) {
            return value;
        }
    } catch (err) {
        console.error("Cache GET error:", err);
        return null; // Fail gracefully
    }
}

async function set(key, value, ttlSeconds = 86400) { // Default 24h
    try {
        const valueStr = JSON.stringify(value);
        await client.set(key, valueStr, {
            EX: ttlSeconds
        });
    } catch (err) {
        console.error("Cache SET error:", err);
    }
}

module.exports = { get, set };
