import sys, json, time, re, os
import urllib.request
from bs4 import BeautifulSoup
from curl_cffi import requests

TRAWL_URL = os.environ.get('TRAWL_URL', 'http://localhost:8191')

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
    return ('just a moment' in html_lower or 
            'cf-challenge' in html_lower or 
            'challenge-platform' in html_lower or
            '<title>loading' in html_lower or
            '__cf_chl_tk' in html)

def fetch_page(url):
    global cached_cookies, cached_user_agent

    # Load cache lazily from disk if empty
    if not cached_cookies:
        load_cookie_cache()

    for attempt in range(1, 4):
        log(f'[Guardoserie] Fetch attempt {attempt} for: {url}')
        
        # 1. Try direct fetch via curl_cffi with cached cookies
        if cached_cookies and cached_user_agent:
            try:
                log(f'[Guardoserie] Fetching directly via curl_cffi: {url}')
                headers = {"User-Agent": cached_user_agent}
                response = requests.get(
                    url,
                    headers=headers,
                    cookies=cached_cookies,
                    impersonate="firefox",
                    timeout=15
                )
                html = response.text
                status = response.status_code
                if (200 <= status < 400) and not is_cloudflare_challenge(html):
                    log(f'[Guardoserie] Direct fetch success on attempt {attempt}: status={status} len={len(html)}')
                    return html
                else:
                    log(f'[Guardoserie] Direct fetch on attempt {attempt} failed or got challenge: status={status} len={len(html) if html else 0}')
            except Exception as e:
                if "timed out" in str(e).lower() or "timeout" in str(e).lower():
                    log(f'[Guardoserie] Direct fetch attempt {attempt} timed out (expected Cloudflare block)')
                else:
                    log(f'[Guardoserie] Direct fetch attempt {attempt} failed: {e}')

        # 2. Fallback: Fetch via Trawl to solve challenge and get new cookies
        log(f'[Guardoserie] Fetch via Trawl: {url}')
        try:
            req_url = f"{TRAWL_URL.rstrip('/')}/scrape"
            data = {
                "url": url,
                "maxTimeout": 80000
            }
            req = urllib.request.Request(
                req_url,
                data=json.dumps(data).encode('utf-8'),
                headers={'Content-Type': 'application/json'},
                method='POST'
            )
            with urllib.request.urlopen(req, timeout=85) as response:
                resp_data = json.loads(response.read().decode('utf-8'))
                status_code = resp_data.get('statusCode')
                html = resp_data.get('html', '')
                
                try:
                    status_int = int(status_code)
                except (TypeError, ValueError):
                    status_int = status_code

                is_success = False
                if isinstance(status_int, int):
                    is_success = 200 <= status_int < 400
                else:
                    is_success = resp_data.get('status') == 'ok'

                if is_success:
                    if not html and 'solution' in resp_data:
                        html = resp_data.get('solution', {}).get('response', '')
                    
                    # Cache the updated cookies and User-Agent
                    cookies_list = resp_data.get('cookies', [])
                    if cookies_list:
                        cached_cookies = {c['name']: c['value'] for c in cookies_list}
                        cached_user_agent = resp_data.get('userAgent', '')
                        log(f'[Guardoserie] Cookie cache updated with {len(cached_cookies)} cookies')
                        save_cookie_cache()
                    
                    if not is_cloudflare_challenge(html):
                        log(f'[Guardoserie] Trawl success on attempt {attempt}: len={len(html)}')
                        return html
                    else:
                        log(f'[Guardoserie] Trawl on attempt {attempt} returned challenge page: len={len(html)}')
                else:
                    log(f"[Guardoserie] Trawl error response: status={status_code} data={resp_data}")
        except Exception as e:
            log(f"[Guardoserie] Trawl request failed on attempt {attempt}: {e}")
        
        # If we got a challenge or failed, wait 2.5 seconds before retrying
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
    for iframe in doc.select('iframe'):
        src = iframe.get('src', '')
        if src and src != 'javascript:false':
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
