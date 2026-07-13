import sys, json, time, re, os
import requests
from scrapling.parser import Selector

STREMIO_CATALOG_PAGE_SIZE = 20
SITE_CATALOG_PAGE_SIZE = 40

playwright_instance = None
browser_context = None
browser_page = None
virtual_display = None

def log(message):
    sys.stderr.write(message + '\n')
    sys.stderr.flush()

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

def get_browser_page():
    global playwright_instance, browser_context, browser_page, virtual_display
    if browser_page is None:
        log('[Guardoserie] Initializing persistent Camoufox browser context...')
        from playwright.sync_api import sync_playwright
        from camoufox.utils import launch_options as _cf_lo
        import tempfile
        
        if os.name != "nt" and virtual_display is None:
            try:
                from pyvirtualdisplay import Display
                virtual_display = Display(visible=0, size=(1920, 1080))
                virtual_display.start()
                import subprocess
                subprocess.Popen(["fluxbox"], env={**os.environ}, stderr=subprocess.DEVNULL)
                time.sleep(1)
            except Exception as e:
                sys.stderr.write(f"Failed to start pyvirtualdisplay/fluxbox: {e}\n")

        kw = {"headless": False, "humanize": True, "locale": "it-IT", "geoip": True}
        _lo = _cf_lo(**kw)
        _td = os.path.join(tempfile.gettempdir(), "camoufox_ctx_guardoserie")
        os.makedirs(_td, exist_ok=True)
        
        playwright_instance = sync_playwright().start()
        browser_context = playwright_instance.firefox.launch_persistent_context(_td, no_viewport=True, **_lo)
        browser_page = browser_context.new_page()
        browser_page.evaluate("window.moveTo(0,0); window.resizeTo(1280, 720)")
        browser_page.set_default_timeout(60000)
        
        # Block ads and heavy resources to prevent Playwright crashes
        browser_page.route('**/*', lambda route: 
            route.abort() if route.request.resource_type in ['image', 'media', 'font'] or 
            any(x in route.request.url for x in ['adsco.re', 'popads', 'shinystat', 'exoclick', 'google-analytics', 'doubleclick', 'addthis'])
            else route.continue_()
        )
        
    return browser_page

def close_browser():
    global playwright_instance, browser_context, browser_page, virtual_display
    log('[Guardoserie] Closing persistent browser context...')
    if browser_context:
        try: browser_context.close()
        except: pass
    if playwright_instance:
        try: playwright_instance.stop()
        except: pass
    if virtual_display:
        try: virtual_display.stop()
        except: pass
    browser_page = None
    browser_context = None
    playwright_instance = None
    virtual_display = None

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

def fetch_page(url):
    log(f'[Guardoserie] Fetching page: {url}')
    page = get_browser_page()
    
    try:
        page.goto(url, wait_until="commit")
        
        challenge_titles = ["just a moment", "ci siamo quasi", "attention required",
            "un instant", "un moment", "einen moment", "un momento",
            "só um momento", "um momento"]

        def is_ch(t):
            return t and any(m in t.lower() for m in challenge_titles)

        def safe_title(p):
            try: return p.title()
            except: return ""

        t = safe_title(page)
        if is_ch(t):
            log('[Guardoserie] Cloudflare challenge detected. Solving Turnstile...')
            time.sleep(12) # Wait for auto-solve
            
            bypass_start = time.time()
            max_wait = 90
            bypassed = False
            
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
        else:
            log('[Guardoserie] Page loaded instantly using cached browser session.')

        try: page.wait_for_load_state("domcontentloaded", timeout=5000)
        except: pass
        return page.content()
    except Exception as e:
        log(f'[Guardoserie] Fetch error: {e}')
        return ""



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
    close_browser()
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
