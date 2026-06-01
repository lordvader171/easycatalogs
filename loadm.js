const CryptoJS = require('crypto-js');
const https = require('https');
const http = require('http');

const USER_AGENT = "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36";

function httpGet(url, headers) {
    return new Promise((resolve, reject) => {
        const mod = url.startsWith('https') ? https : http;
        mod.get(url, { headers }, res => {
            const chunks = [];
            res.on('data', chunk => chunks.push(chunk));
            res.on('end', () => resolve({ status: res.statusCode, body: Buffer.concat(chunks).toString(), headers: res.headers }));
        }).on('error', reject);
    });
}

async function extractLoadm(playerUrl, referer = 'guardoserie.run') {
    try {
        if (!playerUrl || !playerUrl.includes('#')) return [];

        const [baseUrl, id] = playerUrl.split('#');
        const apiUrl = `${baseUrl}api/v1/video`;
        const query = `id=${encodeURIComponent(id)}&w=2560&h=1440&r=${encodeURIComponent(referer)}`;

        const response = await httpGet(`${apiUrl}?${query}`, {
            'User-Agent': USER_AGENT,
            'Referer': baseUrl,
            'X-Requested-With': 'XMLHttpRequest'
        });

        if (response.status !== 200) return [];

        const key = CryptoJS.enc.Utf8.parse('kiemtienmua911ca');
        const iv = CryptoJS.enc.Utf8.parse('1234567890oiuytr');
        const ciphertext = CryptoJS.enc.Hex.parse(response.body.trim());
        const decrypted = CryptoJS.AES.decrypt({ ciphertext }, key, {
            iv,
            mode: CryptoJS.mode.CBC,
            padding: CryptoJS.pad.Pkcs7
        });

        const decryptedStr = decrypted.toString(CryptoJS.enc.Utf8).trim();
        if (!decryptedStr) return [];

        const lastBraceIndex = decryptedStr.lastIndexOf('}');
        const cleanJson = lastBraceIndex !== -1 ? decryptedStr.substring(0, lastBraceIndex + 1) : decryptedStr;
        const data = JSON.parse(cleanJson);
        if (!data.source) return [];

        const playbackHeaders = {
            'Referer': baseUrl,
            'Origin': baseUrl.replace(/\/$/, ''),
            'User-Agent': USER_AGENT,
            'Accept': '*/*',
            'Accept-Language': 'it-IT,it;q=0.9,en-US;q=0.8,en;q=0.7',
            'Connection': 'keep-alive',
            'Sec-Fetch-Dest': 'empty',
            'Sec-Fetch-Mode': 'cors',
            'Sec-Fetch-Site': 'cross-site'
        };

        return [{
            name: 'Guardoserie Loadm',
            url: data.source,
            title: data.title || 'M3U8',
            headers: playbackHeaders,
            behaviorHints: {
                notWebReady: true,
                proxyHeaders: {
                    request: playbackHeaders
                }
            }
        }];
    } catch (e) {
        console.error('[Loadm] Extraction error:', e.message);
        return [];
    }
}

module.exports = { extractLoadm };
