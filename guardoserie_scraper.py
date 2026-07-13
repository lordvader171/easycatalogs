import sys, json, time, re, os
import requests
from scrapling.parser import Selector

STREMIO_CATALOG_PAGE_SIZE = 20
SITE_CATALOG_PAGE_SIZE = 40

SCRAPER_DIR = os.path.dirname(os.path.abspath(__file__))
SESSION_FILE = os.path.join(SCRAPER_DIR, 'cf-session-guardoserie.json')

def log(message):
    sys.stderr.write(message + '\n')
    sys.stderr.flush()

def load_session():
    if os.path.exists(SESSION_FILE):
        try:
            with open(SESSION_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            log(f'[Guardoserie] Error loading session: {e}')
    return None

def save_session(data):
    try:
        with open(SESSION_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        log(f'[Guardoserie] Error saving session: {e}')

def is_cloudflare_challenge(html):
    if not html:
        return True
    challenge_titles = [
        "just a moment", "ci siamo quasi", "attention required",
        "un instant", "un moment", "einen moment", "un momento",
        "só um momento", "um momento", "cf-challenge", "challenge-platform"
    ]
    html_lower = html.lower()
    return any(m in html_lower for m in challenge_titles)

def tab_space_os(page):
    try:
        if os.name == "nt":
            import pyautogui, pygetwindow as gw
            w = None
            for ww in gw.getAllWindows():
                try:
                    if "camoufox" in (ww.title or "").lower() and ww.visible:
                        w = ww; break
                except: pass
            if not w:
                for ww in gw.getWindowsWithTitle("Camoufox"):
                    if ww.visible: w = ww; break
            if not w: return False
            w.activate()
            time.sleep(0.3)
            pyautogui.press("tab"); time.sleep(0.3)
            pyautogui.press("space")
        else:
            import subprocess
            wid = None
            r = subprocess.run(["xdotool","search","--name","Camoufox"],
                               capture_output=True,text=True,timeout=10)
            if r.stdout.strip():
                wid = r.stdout.strip().split("\n")[0]
            else:
                r2 = subprocess.run(["xdotool","search","--class","Firefox"],
                                    capture_output=True,text=True,timeout=10)
                if r2.stdout.strip():
                    wid = r2.stdout.strip().split("\n")[0]
            if not wid:
                sys.stderr.write(f"tab_space: finestra non trovata\n")
                return False
            sys.stderr.write(f"tab_space: finestra {wid}, focus + 3xTab+Space via pyautogui...\n")
            subprocess.run(["xdotool","windowfocus","--sync",wid], timeout=10)
            time.sleep(0.3)
            subprocess.run(["xauth","add",os.environ.get("DISPLAY",":99"),
                           ".","ffffffffffffffffffffffffffffffff"],
                           capture_output=True, timeout=5)
            import pyautogui
            pyautogui.press("tab"); time.sleep(0.3)
            pyautogui.press("space")
        return True
    except Exception as ex:
        sys.stderr.write(f"tab_space errore: {ex}\n")
        return False

def solve_cloudflare_bypass(url):
    log(f'[Guardoserie] Running Camoufox bypass for: {url}')
    from playwright.sync_api import sync_playwright
    from camoufox.utils import launch_options as _cf_lo
    import tempfile
    
    display = None
    if os.name != "nt":
        try:
            from pyvirtualdisplay import Display
            display = Display(visible=0, size=(1920, 1080))
            display.start()
            import subprocess
            subprocess.Popen(["fluxbox"], env={**os.environ}, stderr=subprocess.DEVNULL)
            time.sleep(1)
        except Exception as e:
            sys.stderr.write(f"Failed to start pyvirtualdisplay/fluxbox: {e}\n")

    try:
        kw = {"headless": False, "humanize": True, "locale": "it-IT", "geoip": True}
        _lo = _cf_lo(**kw)
        _td = os.path.join(tempfile.gettempdir(), "camoufox_ctx_guardoserie")
        os.makedirs(_td, exist_ok=True)
        
        with sync_playwright() as pw:
            ctx = pw.firefox.launch_persistent_context(_td, no_viewport=True, **_lo)
            try:
                page = ctx.new_page()
                page.evaluate("window.moveTo(0,0); window.resizeTo(1280, 720)")
                page.set_default_timeout(60000)
                
                sess = load_session()
                if sess and sess.get('cookies'):
                    cookie_str = sess.get('cookies')
                    playwright_cookies = []
                    for item in cookie_str.split(';'):
                        if '=' in item:
                            k, v = item.strip().split('=', 1)
                            from urllib.parse import urlparse
                            domain = urlparse(url).hostname
                            playwright_cookies.append({
                                'name': k,
                                'value': v,
                                'domain': domain,
                                'path': '/'
                            })
                    try:
                        ctx.add_cookies(playwright_cookies)
                    except Exception as ce:
                        log(f'[Guardoserie] Error adding existing cookies to bypass ctx: {ce}')

                page.goto(url, wait_until="domcontentloaded")
                
                challenge_titles = ["just a moment", "ci siamo quasi", "attention required",
                    "un instant", "un moment", "einen moment", "un momento",
                    "só um momento", "um momento"]

                def is_ch(t):
                    return t and any(m in t.lower() for m in challenge_titles)

                def safe_title(p):
                    try: return p.title()
                    except: return ""

                bypass_start = time.time()
                max_wait = 90
                bypassed = False
                
                time.sleep(12)
                
                while time.time() - bypass_start < max_wait:
                    try:
                        page.wait_for_load_state("domcontentloaded", timeout=8000)
                    except: pass
                    t = safe_title(page)
                    log(f'[Guardoserie] bypass loop: title={t!r} bypassed={bypassed}')
                    if not is_ch(t):
                        if bypassed:
                            time.sleep(2)
                            t2 = safe_title(page)
                            if not is_ch(t2):
                                log('[Guardoserie] bypass stable')
                                break
                        else:
                            bypassed = True
                            continue
                    
                    if not tab_space_os(page):
                        time.sleep(3)
                        continue
                    time.sleep(3)
                
                html = page.content()
                current_url = page.url
                
                cookies_list = []
                try:
                    for c in ctx.cookies():
                        cookies_list.append({k: c.get(k) for k in ("name","value","domain","path","httpOnly","secure")})
                        if "expires" in c: cookies_list[-1]["expiry"] = c["expires"]
                except Exception as ce:
                    log(f'[Guardoserie] Error getting cookies: {ce}')
                
                ua = page.evaluate("navigator.userAgent")
                
                cookies_str = "; ".join([f"{c['name']}={c['value']}" for c in cookies_list if c.get('name') and c.get('value')])
                cookie_domains = list(set([c.get('domain') for c in cookies_list if c.get('domain')]))
                
                session_data = {
                    "userAgent": ua,
                    "cookies": cookies_str,
                    "url": current_url,
                    "cookieDomains": cookie_domains,
                    "timestamp": int(time.time() * 1000)
                }
                save_session(session_data)
                log('[Guardoserie] Cloudflare bypass successfully completed and session saved.')
                return html
            finally:
                try: ctx.close()
                except: pass
    finally:
        if display:
            try: display.stop()
            except: pass
    return None

def http_fetch(url):
    sess = load_session()
    cookies = {}
    ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    
    if sess:
        ua = sess.get('userAgent', ua)
        cookie_str = sess.get('cookies', '')
        if cookie_str:
            for item in cookie_str.split(';'):
                if '=' in item:
                    k, v = item.strip().split('=', 1)
                    cookies[k] = v

    headers = {
        'User-Agent': ua,
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
        'Accept-Language': 'it-IT,it;q=0.9,en-US;q=0.8,en;q=0.7',
    }
    
    try:
        r = requests.get(url, headers=headers, cookies=cookies, timeout=15)
        if r.status_code in (403, 503) or is_cloudflare_challenge(r.text):
            log(f'[Guardoserie] Cloudflare challenge detected (Status {r.status_code})')
            return None
        return r.text
    except Exception as e:
        log(f'[Guardoserie] HTTP fetch error: {e}')
        return None

def fetch_page(url):
    html = http_fetch(url)
    if html:
        return html
    
    html2 = solve_cloudflare_bypass(url)
    if html2 and not is_cloudflare_challenge(html2):
        return html2
        
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
    url = 'https://guardoserie.study/turche/' if page == 1 else f'https://guardoserie.study/turche/page/{page}/'
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
    html = fetch_page(f'https://guardoserie.study/serie/{slug}/')
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
