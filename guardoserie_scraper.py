import sys, json, time, re
from scrapling.fetchers import StealthySession
from scrapling.parser import Selector

session = None
browser_cookies_loaded = False
saved_cookies = []
fetch_count = 0
MAX_FETCHES_PER_SESSION = 25

STREMIO_CATALOG_PAGE_SIZE = 20
SITE_CATALOG_PAGE_SIZE = 40

def log(message):
    sys.stderr.write(message + '\n')
    sys.stderr.flush()

def get_session():
    global session, browser_cookies_loaded, fetch_count
    if session is not None and fetch_count >= MAX_FETCHES_PER_SESSION:
        log(f'[Guardoserie] Session reached {fetch_count} fetches. Restarting session to free memory...')
        try:
            session.close()
        except Exception as e:
            log(f'[Guardoserie] Error closing session: {e}')
        session = None
        fetch_count = 0

    if session is None:
        session = StealthySession(headless=True, solve_cloudflare=False)
        session.start()
        browser_cookies_loaded = False
    if not browser_cookies_loaded and saved_cookies:
        try:
            session.context.add_cookies(saved_cookies)
            browser_cookies_loaded = True
            log('[Guardoserie] Loaded cookies into browser context')
        except Exception as e:
            log(f'[Guardoserie] Cookie load failed: {e}')
    return session

def save_browser_cookies():
    global saved_cookies
    if session and session.context:
        saved_cookies = session.context.cookies()

def is_cloudflare_challenge(html):
    return not html or 'Just a moment' in html or 'cf-challenge' in html or 'challenge-platform' in html

def scrapling_fetch_page(url, solve_cloudflare=False):
    global fetch_count
    log(f'[Guardoserie] Fetch {url} solve_cf={solve_cloudflare}')
    s = get_session()
    result = [None]
    def action(page):
        time.sleep(2 if solve_cloudflare else 0.1)
        result[0] = page.content()
    
    fetch_count += 1
    s.fetch(
        url,
        google_search=False,
        page_action=action,
        network_idle=solve_cloudflare,
        load_dom=solve_cloudflare,
        wait=3000 if solve_cloudflare else 100,
        disable_resources=not solve_cloudflare,
        timeout=30000 if solve_cloudflare else 30000,
        solve_cloudflare=solve_cloudflare
    )
    save_browser_cookies()
    return result[0]

def fetch_page(url):
    html = scrapling_fetch_page(url, solve_cloudflare=False)
    log(f'[Guardoserie] fetch_page (cf=False): len={len(html) if html else 0} challenge={is_cloudflare_challenge(html) if html else "N/A"}')
    if html and len(html) > 500 and not is_cloudflare_challenge(html):
        return html
    html2 = scrapling_fetch_page(url, solve_cloudflare=True)
    log(f'[Guardoserie] fetch_page (cf=True): len={len(html2) if html2 else 0} challenge={is_cloudflare_challenge(html2) if html2 else "N/A"}')
    return html2

def parse_catalog(html):
    doc = Selector(html)
    series = []
    for item in doc.css('.ml-item'):
        a = item.css('a')
        img = item.css('img')
        if not a or not img:
            continue
        href = a[0].attrib.get('href', '')
        title = a[0].attrib.get('title', '') or img[0].attrib.get('alt', '')
        poster = img[0].attrib.get('src', '')
        slug = href.rstrip('/').split('/')[-1] if href else ''
        if slug and title:
            series.append({'id': f'gs_{slug}', 'type': 'series', 'name': title.strip(), 'poster': poster, 'slug': slug})
    return series

def cmd_catalog(skip=0):
    skip = int(skip or 0)
    page = max(1, (skip // SITE_CATALOG_PAGE_SIZE) + 1)
    page_offset = skip % SITE_CATALOG_PAGE_SIZE
    url = 'https://guardoserie.run/turche/' if page == 1 else f'https://guardoserie.run/turche/page/{page}/'
    html = fetch_page(url)
    series = parse_catalog(html)
    return {'ok': True, 'series': series[page_offset:page_offset + STREMIO_CATALOG_PAGE_SIZE], 'skip': skip, 'page': page}

def parse_series_meta(html, slug):
    doc = Selector(html)
    og_title = doc.css('meta[property="og:title"]')
    title = og_title[0].attrib.get('content', '') if og_title else slug
    title = title.replace(' | Guarda Serie e Film Streaming Completo', '').strip()
    og_desc = doc.css('meta[property="og:description"]')
    description = og_desc[0].attrib.get('content', '') if og_desc else ''
    poster = ''
    for img in doc.css('img'):
        src = img.attrib.get('src', '')
        if 'tmdb' in src and 'w185' in src:
            poster = src.replace('w185', 'w500')
            break
    og_section = doc.css('meta[property="article:section"]')
    genre = og_section[0].attrib.get('content', '') if og_section else ''
    seasons = []
    for sdiv in doc.css('#seasons .tvseason'):
        title_el = sdiv.css('strong')
        season_title = title_el[0].text.strip() if title_el else 'Stagione'
        season_match = re.search(r'(\d+)', season_title)
        season_num = int(season_match.group(1)) if season_match else 1
        episodes = []
        for ep_link in sdiv.css('a'):
            ep_href = ep_link.attrib.get('href', '')
            ep_text = ep_link.text.strip() if ep_link.text else ''
            ep_match = re.search(r'Episodio\s+(\d+)', ep_text, re.IGNORECASE)
            ep_num = int(ep_match.group(1)) if ep_match else len(episodes) + 1
            episodes.append({'id': ep_num, 'title': ep_text or f'Episodio {ep_num}', 'url': ep_href, 'season': season_num})
        seasons.append({'season': season_num, 'title': season_title, 'episodes': episodes})

    return {'ok': True, 'title': title, 'description': description, 'poster': poster, 'genre': genre, 'year': '', 'seasons': seasons, 'slug': slug}

def cmd_meta(slug):
    html = fetch_page(f'https://guardoserie.run/serie/{slug}/')
    return parse_series_meta(html, slug)

def parse_episode(html):
    doc = Selector(html)
    for iframe in doc.css('iframe'):
        src = iframe.attrib.get('src', '')
        if src and src != 'javascript:false':
            return {'ok': True, 'iframe_url': src}
    return {'ok': False, 'iframe_url': None}

def cmd_episode(url):
    html = fetch_page(url)
    return parse_episode(html)

def cmd_close():
    global session, browser_cookies_loaded
    if session:
        try:
            session.close()
        except Exception:
            pass
    session = None
    browser_cookies_loaded = False
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
