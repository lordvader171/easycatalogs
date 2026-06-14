const { createClient } = require("redis");
const fs = require("fs");
const path = require("path");

const redisUrl = typeof process.env.REDIS_URL === "string"
    ? process.env.REDIS_URL.trim()
    : "";

const cacheType = (process.env.CACHE_TYPE || "hybrid").toLowerCase().trim();

let client = null;
let cacheEnabled = false;
let cacheDisabled = false;
let failureLogged = false;
const defaultSqlitePath = fs.existsSync("/app/data")
    ? "/app/data/db.sqlite"
    : path.join(__dirname, "data", "db.sqlite");
const sqliteCachePath = process.env.SQLITE_CACHE_PATH || defaultSqlitePath;
let sqliteDb = null;

function initializeSqlite() {
    if (sqliteDb) return sqliteDb;
    try {
        const { DatabaseSync } = require("node:sqlite");
        const dir = path.dirname(sqliteCachePath);
        if (!fs.existsSync(dir)) {
            fs.mkdirSync(dir, { recursive: true });
        }
        
        sqliteDb = new DatabaseSync(sqliteCachePath);
        
        // Crea la tabella di cache se non esiste
        sqliteDb.exec(`
            CREATE TABLE IF NOT EXISTS cache (
                key TEXT PRIMARY KEY,
                value TEXT,
                expires_at INTEGER
            )
        `);
        
        // Crea un indice per ottimizzare la pulizia delle chiavi scadute
        sqliteDb.exec(`
            CREATE INDEX IF NOT EXISTS idx_cache_expires_at ON cache (expires_at)
        `);
        
        // Avvia pulizia iniziale e pianifica pulizia periodica ogni ora
        cleanupExpiredKeys();
        setInterval(cleanupExpiredKeys, 60 * 60 * 1000).unref();
        
        return sqliteDb;
    } catch (err) {
        console.error("[Cache] Failed to initialize SQLite cache:", err);
        return null;
    }
}

function cleanupExpiredKeys() {
    if (!sqliteDb) return;
    try {
        const stmt = sqliteDb.prepare("DELETE FROM cache WHERE expires_at IS NOT NULL AND expires_at <= ?");
        stmt.run(Date.now());
    } catch (err) {
        // Keep cleanup best-effort
    }
}

function logCacheDisabled(err) {
    if (failureLogged) return;
    failureLogged = true;

    const reason = err && (err.code || err.message)
        ? `${err.code || err.message}`
        : "unknown error";

    console.warn(`[Cache] Redis unavailable. Continuing without cache (${reason}).`);
}

function closeClient() {
    if (!client) return;

    try {
        client.removeAllListeners();
    } catch (err) {
        // Ignore cleanup errors.
    }

    try {
        if (typeof client.destroy === "function") {
            client.destroy();
        } else if (typeof client.disconnect === "function") {
            client.disconnect();
        }
    } catch (err) {
        // Ignore cleanup errors.
    }

    client = null;
}

async function migrateKeysFromRedisToSqlite(redisClient, sqliteDbInstance) {
    const patterns = ["guardoserie:slug:*", "animemapping:*"];
    const stmt = sqliteDbInstance.prepare("INSERT OR REPLACE INTO cache (key, value, expires_at) VALUES (?, ?, ?)");
    let migratedCount = 0;

    for (const pattern of patterns) {
        let cursor = "0";
        do {
            try {
                const reply = await redisClient.scan(cursor, {
                    MATCH: pattern,
                    COUNT: 100
                });
                cursor = String(reply.cursor);
                const keys = reply.keys;
                
                if (keys && keys.length > 0) {
                    for (const key of keys) {
                        const value = await redisClient.get(key);
                        const ttl = await redisClient.ttl(key);
                        
                        let expiresAt = null;
                        if (ttl > 0) {
                            expiresAt = Date.now() + (ttl * 1000);
                        } else if (ttl === -2) {
                            continue;
                        }
                        
                        stmt.run(key, value, expiresAt);
                        await redisClient.del(key);
                        migratedCount++;
                    }
                }
            } catch (err) {
                console.error("[Cache Migration] Error migrating keys:", err);
                break;
            }
        } while (cursor !== "0");
    }
    
    if (migratedCount > 0) {
        console.log(`[Cache Migration] Successfully migrated ${migratedCount} keys from Redis to SQLite.`);
    }
}

async function initializeCache() {
    if (cacheType === "sqlite") {
        cacheEnabled = false;
        cacheDisabled = true;
        console.log("[Cache] SQLite forced via CACHE_TYPE");
        return;
    }
    if (!redisUrl || cacheDisabled || client) return;

    client = createClient({
        url: redisUrl,
        socket: {
            reconnectStrategy: false,
            connectTimeout: 1500
        }
    });

    client.on("error", (err) => {
        if (!cacheEnabled) return;

        cacheEnabled = false;
        cacheDisabled = true;
        logCacheDisabled(err);
        closeClient();
    });

    try {
        await client.connect();
        cacheEnabled = client.isReady;

        if (cacheEnabled) {
            console.log(`[Cache] Redis enabled (${redisUrl})`);
            const db = initializeSqlite();
            if (db) {
                migrateKeysFromRedisToSqlite(client, db).catch(() => {});
            }
        }
    } catch (err) {
        cacheEnabled = false;
        cacheDisabled = true;
        logCacheDisabled(err);
        closeClient();
    }
}

void initializeCache();

function isSqliteForcedKey(key) {
    return typeof key === "string" && (
        key.startsWith("guardoserie:slug:") ||
        key.startsWith("animemapping:")
    );
}

async function get(key) {
    const useSqlite = isSqliteForcedKey(key) || !cacheEnabled || !client || !client.isReady;
    
    if (useSqlite) {
        const db = initializeSqlite();
        if (!db) return null;
        try {
            const stmt = db.prepare("SELECT value, expires_at FROM cache WHERE key = ?");
            const row = stmt.get(key);
            if (!row) return null;
            if (row.expires_at && row.expires_at <= Date.now()) {
                const delStmt = db.prepare("DELETE FROM cache WHERE key = ?");
                delStmt.run(key);
                return null;
            }
            try {
                return JSON.parse(row.value);
            } catch (err) {
                return row.value;
            }
        } catch (err) {
            return null;
        }
    }

    try {
        const value = await client.get(key);
        if (!value) return null;

        try {
            return JSON.parse(value);
        } catch (err) {
            return value;
        }
    } catch (err) {
        cacheEnabled = false;
        cacheDisabled = true;
        logCacheDisabled(err);
        closeClient();
        
        // Se Redis fallisce, proviamo a cercare in SQLite come fallback
        const db = initializeSqlite();
        if (!db) return null;
        try {
            const stmt = db.prepare("SELECT value, expires_at FROM cache WHERE key = ?");
            const row = stmt.get(key);
            if (!row) return null;
            if (row.expires_at && row.expires_at <= Date.now()) {
                return null;
            }
            try {
                return JSON.parse(row.value);
            } catch (e) {
                return row.value;
            }
        } catch (e) {
            return null;
        }
    }
}

async function set(key, value, ttlSeconds = 86400) {
    const useSqlite = isSqliteForcedKey(key) || !cacheEnabled || !client || !client.isReady;

    if (useSqlite) {
        const db = initializeSqlite();
        if (!db) return;
        try {
            const expiresAt = ttlSeconds ? Date.now() + (ttlSeconds * 1000) : null;
            const valStr = JSON.stringify(value);
            const stmt = db.prepare("INSERT OR REPLACE INTO cache (key, value, expires_at) VALUES (?, ?, ?)");
            stmt.run(key, valStr, expiresAt);
        } catch (err) {
            // Keep cache best-effort
        }
        return;
    }

    try {
        await client.set(key, JSON.stringify(value), {
            EX: ttlSeconds
        });
    } catch (err) {
        cacheEnabled = false;
        cacheDisabled = true;
        logCacheDisabled(err);
        closeClient();
        
        // Se la scrittura su Redis fallisce, salviamo su SQLite come fallback
        const db = initializeSqlite();
        if (!db) return;
        try {
            const expiresAt = ttlSeconds ? Date.now() + (ttlSeconds * 1000) : null;
            const valStr = JSON.stringify(value);
            const stmt = db.prepare("INSERT OR REPLACE INTO cache (key, value, expires_at) VALUES (?, ?, ?)");
            stmt.run(key, valStr, expiresAt);
        } catch (e) {}
    }
}

module.exports = { get, set };
