"""
Gercek web browsing - Playwright ile.
Sitelere giriyor, butonlara tikliyor, form dolduruyor.

HIZ NOTU: Eskiden HER cagrida (browse_sync/search_sync) sifirdan yeni bir
Chromium prosesi baslatiliyordu (~1-2sn baslangic maliyeti + kapatma).
Art arda birkac web istegi geldiginde (orn. "3 farkli siteye bak") bu
maliyet her seferinde tekrar odeniyordu. Simdi: arka planda kendi event
loop'unu calistiran bir thread'de TEK bir Chromium instance'i acik
tutuluyor (lazy - ilk kullanimda baslar), her istek sadece yeni bir
sekme (page) acip kapatiyor (~50-200ms). Sonuc: ilk cagri ayni hizda,
sonraki cagrilar 5-10x daha hizli.
"""
import asyncio
import re
import threading

_loop = None
_loop_thread = None
_playwright = None
_browser = None
_init_lock = threading.Lock()


def _ensure_loop() -> asyncio.AbstractEventLoop:
    """Arka planda surekli acik kalan bir event loop dondurur (yoksa baslatir)."""
    global _loop, _loop_thread
    with _init_lock:
        if _loop is None:
            _loop = asyncio.new_event_loop()
            _loop_thread = threading.Thread(target=_loop.run_forever, daemon=True, name="ales-playwright-loop")
            _loop_thread.start()
        return _loop


async def _ensure_browser():
    """Paylasilan Chromium instance'ini dondurur, yoksa baslatir (lazy init)."""
    global _playwright, _browser
    if _browser is not None:
        try:
            if _browser.is_connected():
                return _browser
        except Exception:
            pass
    from playwright.async_api import async_playwright
    _playwright = await async_playwright().start()
    _browser = await _playwright.chromium.launch(headless=True)
    return _browser


async def _with_page(coro_fn):
    """Paylasilan browser'dan yeni bir sekme acar, coro_fn(page)'i calistirir,
    islem bitince sekmeyi kapatir (browser'in kendisi ACIK kalir)."""
    browser = await _ensure_browser()
    page = await browser.new_page()
    try:
        return await coro_fn(page)
    finally:
        try:
            await page.close()
        except Exception:
            pass


async def browse(url: str, action: str = "read") -> str:
    """Bir siteye git ve içeriğini oku veya işlem yap"""
    try:
        async def _run(page):
            await page.goto(url, wait_until="domcontentloaded", timeout=15000)
            await page.wait_for_timeout(1500)
            text = await page.inner_text("body")
            text = re.sub(r'\s+', ' ', text).strip()[:3000]
            return f"[{url}]\n{text}"
        return await _with_page(_run)
    except ImportError:
        return "Playwright kurulu degil. 'pip install playwright && playwright install chromium' calistir."
    except Exception as e:
        return f"Browsing hatasi: {e}"


async def click_and_read(url: str, selector: str) -> str:
    """Siteye git, elemente tıkla, sonucu oku"""
    try:
        async def _run(page):
            await page.goto(url, timeout=15000)
            await page.wait_for_timeout(1000)
            await page.click(selector)
            await page.wait_for_timeout(1000)
            text = await page.inner_text("body")
            return re.sub(r'\s+', ' ', text).strip()[:3000]
        return await _with_page(_run)
    except Exception as e:
        return f"Hata: {e}"


async def fill_and_submit(url: str, fields: dict, submit_selector: str = None) -> str:
    """Form doldur ve gonder - GORUNUR sekilde (kullanici onayi/izlemesi
    icin), bu yuzden paylasilan headless instance'i DEGIL, kendi ayri
    (gorunur) tarayicisini kullanir."""
    try:
        from playwright.async_api import async_playwright
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=False)
            page = await browser.new_page()
            await page.goto(url, timeout=15000)
            await page.wait_for_timeout(1200)
            for selector, value in fields.items():
                await page.fill(selector, value)
                await page.wait_for_timeout(200)
            result = f"Form dolduruldu: {list(fields.keys())}"
            if submit_selector:
                await page.click(submit_selector)
                await page.wait_for_timeout(1500)
                result += " - Gonderildi"
            await browser.close()
            return result
    except Exception as e:
        return f"Form hatasi: {e}"


async def search_and_read(query: str) -> str:
    """Google'da ara ve ilk sonuclari oku"""
    try:
        async def _run(page):
            await page.goto(f"https://www.google.com/search?q={query}", timeout=15000)
            await page.wait_for_timeout(1000)
            results = []
            items = await page.query_selector_all("h3")
            for item in items[:5]:
                text = await item.inner_text()
                if text.strip():
                    results.append(text.strip())
            return "Arama sonuclari:\n" + "\n".join([f"* {r}" for r in results])
        return await _with_page(_run)
    except Exception as e:
        return f"Arama hatasi: {e}"


# ─── Sync wrapper'lar - paylasilan arka plan loop'una gonderir ────
def _run_on_shared_loop(coro, timeout: int = 25):
    loop = _ensure_loop()
    fut = asyncio.run_coroutine_threadsafe(coro, loop)
    return fut.result(timeout=timeout)


def browse_sync(url: str) -> str:
    try:
        return _run_on_shared_loop(browse(url))
    except Exception as e:
        return f"Browsing hatasi: {e}"


def search_sync(query: str) -> str:
    try:
        return _run_on_shared_loop(search_and_read(query))
    except Exception as e:
        return f"Arama hatasi: {e}"
