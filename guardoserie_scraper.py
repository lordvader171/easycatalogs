import sys, json, time, re, os
import urllib.request
from bs4 import BeautifulSoup
from curl_cffi import requests

STREMIO_CATALOG_PAGE_SIZE = 20
SITE_CATALOG_PAGE_SIZE = 40

# Global cookie and User-Agent cache in memory
cached_cookies = {}
cached_user_agent = ""

# Resolve persistent cache file path in data volume
if os.path.exists("/app/data"):
    COOKIE_CACHE_FILE = "/app/data/guardoserie_cookies.json"
else:
    COOKIE_CACHE_FILE = os.path.join(os.path.dirname(__file__), "data", "guardoserie_cookies.json")

def log(message):
    sys.stderr.write(message + '\n')
    sys.stderr.flush()

def load_cookie_cache():
    global cached_cookies, cached_user_agent
    try:
        if os.path.exists(COOKIE_CACHE_FILE):
            with open(COOKIE_CACHE_FILE, 'r') as f:
                cache_data = json.load(f)
                cached_cookies = cache_data.get('cookies', {})
                cached_user_agent = cache_data.get('userAgent', '')
                if cached_cookies:
                    log(f'[Guardoserie] Loaded {len(cached_cookies)} cookies from cache file')
    except Exception as e:
        log(f'[Guardoserie] Failed to load cookie cache file: {e}')

def save_cookie_cache():
    try:
        dir_name = os.path.dirname(COOKIE_CACHE_FILE)
        if dir_name and not os.path.exists(dir_name):
            os.makedirs(dir_name, exist_ok=True)
        with open(COOKIE_CACHE_FILE, 'w') as f:
            json.dump({
                'cookies': cached_cookies,
                'userAgent': cached_user_agent
            }, f)
        log('[Guardoserie] Saved cookies to cache file')
    except Exception as e:
        log(f'[Guardoserie] Failed to save cookie cache file: {e}')

def is_cloudflare_challenge(html):
    if not html:
        return True
    html_lower = html.lower()
    return ('<title>just a moment' in html_lower or 
            '<title>ci siamo quasi' in html_lower or
            '<title>attention required!' in html_lower or
            'id="challenge-running"' in html_lower or
            'id="challenge-stage"' in html_lower or
            'id="challenge-form"' in html_lower or
            'cf-browser-verification' in html_lower or
            'verify you are human' in html_lower or
            'in attesa della risposta' in html_lower or
            'enable javascript and cookies to continue' in html_lower)

CF_BYPASS_SCRIPT = os.environ.get(
    'CF_BYPASS_SCRIPT',
    os.path.join(os.path.dirname(__file__), "cf_bypass.py")
)

def fetch_via_cf_bypass(url):
    global cached_cookies, cached_user_agent
    script_path = CF_BYPASS_SCRIPT
    if not os.path.exists(script_path):
        script_path = os.path.join(os.path.dirname(__file__), "cf_bypass.py")
    if not os.path.exists(script_path):
        log(f'[Guardoserie] cf_bypass script not found at {script_path}')
        return ""

    log(f'[Guardoserie] Fetching via cf_bypass (Camoufox): {url}')
    try:
        import subprocess
        python_exe = sys.executable or "python"
        cmd = [python_exe, script_path, url, "--provider", "guardoserie"]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        output = proc.stdout.strip()
        if output:
            # Output can contain log lines before JSON; extract last JSON block
            json_str = output.strip().split('\n')[-1]
            res = json.loads(json_str)
            if res.get('status') == 'ok':
                html = res.get('html', '')
                cookies_list = res.get('cookies', [])
                if cookies_list:
                    cached_cookies = {c['name']: c['value'] for c in cookies_list if c and 'name' in c}
                    cached_user_agent = res.get('userAgent', '')
                    save_cookie_cache()
                if not is_cloudflare_challenge(html):
                    log(f'[Guardoserie] cf_bypass success: len={len(html)}')
                    return html
                else:
                    log('[Guardoserie] cf_bypass returned challenge page')
            else:
                log(f"[Guardoserie] cf_bypass error: {res.get('message')}")
        else:
            log(f"[Guardoserie] cf_bypass no output, stderr: {proc.stderr}")
    except Exception as e:
        log(f"[Guardoserie] cf_bypass failed: {e}")
    return ""

def fetch_page(url):
    for attempt in range(1, 4):
        log(f'[Guardoserie] Fetch attempt {attempt} for: {url}')
        bypass_html = fetch_via_cf_bypass(url)
        if bypass_html and not is_cloudflare_challenge(bypass_html):
            return bypass_html

        if attempt < 3:
            log('[Guardoserie] Waiting 2.5 seconds before retry...')
            time.sleep(2.5)

    return ""

def parse_catalog(html):
    doc = BeautifulSoup(html, 'html.parser')
    series = []
    for item in doc.select('.ml-item'):
        a = item.select('a')
        img = item.select('img')
        if not a or not img:
            continue
        href = a[0].get('href', '')
        title = a[0].get('title', '') or img[0].get('alt', '')
        poster = img[0].get('src', '')
        slug = href.rstrip('/').split('/')[-1] if href else ''
        if slug and title:
            series.append({'id': f'gs_{slug}', 'type': 'series', 'name': title.strip(), 'poster': poster, 'slug': slug})
    return series

def cmd_catalog(skip=0):
    skip = int(skip or 0)
    page = max(1, (skip // SITE_CATALOG_PAGE_SIZE) + 1)
    page_offset = skip % SITE_CATALOG_PAGE_SIZE
    url = 'https://guardoserie.study/turche/' if page == 1 else f'https://guardoserie.study/turche/page/{page}/'
    html = fetch_page(url)
    series = parse_catalog(html)
    return {'ok': True, 'series': series[page_offset:page_offset + STREMIO_CATALOG_PAGE_SIZE], 'skip': skip, 'page': page}

def parse_series_meta(html, slug):
    doc = BeautifulSoup(html, 'html.parser')
    og_title = doc.select('meta[property="og:title"]')
    title = og_title[0].get('content', '') if og_title else slug
    title = title.replace(' | Guarda Serie e Film Streaming Completo', '').strip()
    og_desc = doc.select('meta[property="og:description"]')
    description = og_desc[0].get('content', '') if og_desc else ''
    poster = ''
    for img in doc.select('img'):
        src = img.get('src', '')
        if 'tmdb' in src and 'w185' in src:
            poster = src.replace('w185', 'w500')
            break
    og_section = doc.select('meta[property="article:section"]')
    genre = og_section[0].get('content', '') if og_section else ''
    seasons = []
    for sdiv in doc.select('#seasons .tvseason'):
        title_el = sdiv.select('strong')
        season_title = title_el[0].get_text().strip() if title_el else 'Stagione'
        season_match = re.search(r'(\d+)', season_title)
        season_num = int(season_match.group(1)) if season_match else 1
        episodes = []
        for ep_link in sdiv.select('a'):
            ep_href = ep_link.get('href', '')
            ep_text = ep_link.get_text().strip()
            ep_match = re.search(r'Episodio\s+(\d+)', ep_text, re.IGNORECASE)
            ep_num = int(ep_match.group(1)) if ep_match else len(episodes) + 1
            episodes.append({'id': ep_num, 'title': ep_text or f'Episodio {ep_num}', 'url': ep_href, 'season': season_num})
        seasons.append({'season': season_num, 'title': season_title, 'episodes': episodes})

    return {'ok': True, 'title': title, 'description': description, 'poster': poster, 'genre': genre, 'year': '', 'seasons': seasons, 'slug': slug}

def cmd_meta(slug):
    html = fetch_page(f'https://guardoserie.study/serie/{slug}/')
    return parse_series_meta(html, slug)

def parse_episode(html):
    doc = BeautifulSoup(html, 'html.parser')
    iframes = doc.select('iframe')
    log(f"[Guardoserie] parse_episode found {len(iframes)} iframes")
    for iframe in iframes:
        src = iframe.get('src', '')
        data_src = iframe.get('data-src', '') or iframe.get('data-lazy-src', '')
        if data_src:
            src = data_src
            log(f"[Guardoserie] Found lazy-loaded data-src: '{src}'")
        else:
            log(f"[Guardoserie] Found standard src: '{src}'")

        if not src:
            continue
        src_lower = src.lower().strip()
        if src_lower in ('about:blank', 'javascript:false', 'javascript:;'):
            continue
        if src_lower.startswith('javascript:'):
            continue
        if src.startswith('http://') or src.startswith('https://') or src.startswith('//'):
            return {'ok': True, 'iframe_url': src}
    return {'ok': False, 'iframe_url': None}

def cmd_episode(url):
    html = fetch_page(url)
    return parse_episode(html)

def cmd_close():
    return {'ok': True}

if __name__ == '__main__':
    while True:
        line = sys.stdin.readline()
        if not line:
            break
        try:
            cmd = json.loads(line.strip())
            action = cmd.get('action')
            rid = cmd.get('_requestId')
            if action == 'catalog':
                result = cmd_catalog(cmd.get('skip', 0))
            elif action == 'meta':
                result = cmd_meta(cmd.get('slug', ''))
            elif action == 'episode':
                result = cmd_episode(cmd.get('url', ''))
            elif action == 'close':
                result = cmd_close()
                if rid: result['_requestId'] = rid
                print(json.dumps(result)); sys.stdout.flush(); break
            else:
                result = {'ok': False, 'error': f'Unknown action: {action}'}
            if rid: result['_requestId'] = rid
            print(json.dumps(result)); sys.stdout.flush()
        except Exception as e:
            resp = {'ok': False, 'error': str(e)}
            try: resp['_requestId'] = cmd.get('_requestId')
            except Exception: pass
            print(json.dumps(resp)); sys.stdout.flush()
