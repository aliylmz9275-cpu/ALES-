"""
Fiverr ve Bionluk otomasyonu.
Brave tarayici destegi dahil. Cookie kaydeder - bir kez login yeter.

ONEMLI TASARIM KARARI: Bu modul artik tarayici penceresini ACIK BIRAKIYOR
ve ONE GETIRIYOR. Eskiden islem bitince driver.quit() cagriliyordu, yani
Ali sonucu gordugunde pencere zaten kapanmis oluyordu - sanki hicbir sey
olmamis gibi görünüyordu. Artik:
  1) Pencere gercekten one geliyor ve buyuk aciliyor (Ali gorsun diye)
  2) Her adim progress_callback ile bildiriliyor (main.py bunu
     websocket'e tool_use mesaji olarak yolluyor, Ali "ALES Fiverr'i
     aciyor... sayfaya bakiyor... mesajlari okuyor..." gibi gercek
     zamanli ilerleme görür)
  3) Pencere islem bitince OTOMATIK KAPANMIYOR - Ali kendi gozuyle
     son durumu görebilsin diye acik kaliyor.
"""
import time, json, os
from pathlib import Path

BRAVE_PATHS = [
    r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
    r"C:\Program Files (x86)\BraveSoftware\Brave-Browser\Application\brave.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\BraveSoftware\Brave-Browser\Application\brave.exe"),
]
CHROME_PATHS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
]

COOKIES_FILE = Path("fiverr_cookies.json")


def _noop_callback(msg: str):
    pass


def get_driver(headless=False, bring_to_front=True):
    """
    Chrome veya Brave driver olustur. (driver, hata_mesaji) doner.
    bring_to_front=True ise pencere buyuk acilir ve one getirilir -
    Ali'nin ALES'in ne yaptigini GORMESI icin.
    """
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.service import Service
        from selenium.webdriver.chrome.options import Options
        from webdriver_manager.chrome import ChromeDriverManager

        opts = Options()
        if headless:
            opts.add_argument("--headless=new")
        else:
            # Pencereyi buyuk ve gorunur ac - "arka planda sessizce
            # calisma", Ali'nin istedigi gibi GORUNUR calisma
            opts.add_argument("--start-maximized")
            opts.add_argument("--window-position=0,0")
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")
        opts.add_argument("--disable-blink-features=AutomationControlled")
        opts.add_experimental_option("excludeSwitches", ["enable-automation"])
        opts.add_experimental_option("useAutomationExtension", False)

        brave_path = next((p for p in BRAVE_PATHS if os.path.exists(p)), None)
        if brave_path:
            opts.binary_location = brave_path
        else:
            chrome_path = next((p for p in CHROME_PATHS if os.path.exists(p)), None)
            if chrome_path:
                opts.binary_location = chrome_path

        driver = webdriver.Chrome(
            service=Service(ChromeDriverManager().install()),
            options=opts
        )
        driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

        if bring_to_front and not headless:
            try:
                # Windows'ta pencereyi gercekten one getir (sadece acmak
                # yetmeyebilir, baska bir pencerenin arkasinda kalabilir)
                driver.maximize_window()
                driver.switch_to.window(driver.current_window_handle)
            except Exception:
                pass

        return driver, None
    except Exception as e:
        return None, str(e)


def save_cookies(driver, site: str):
    try:
        cookies = driver.get_cookies()
        data = {}
        if COOKIES_FILE.exists():
            data = json.loads(COOKIES_FILE.read_text())
        data[site] = cookies
        COOKIES_FILE.write_text(json.dumps(data))
    except: pass


def load_cookies(driver, site: str):
    try:
        if not COOKIES_FILE.exists(): return False
        data = json.loads(COOKIES_FILE.read_text())
        if site not in data: return False
        for cookie in data[site]:
            try: driver.add_cookie(cookie)
            except: pass
        return True
    except: return False


def _looks_logged_out_fiverr(driver) -> bool:
    """URL tek basina yetersiz - Fiverr giris formunu modal olarak da
    acabilir, URL hic degismez. Sayfa icerigine de bakiyoruz."""
    url = driver.current_url.lower()
    if "login" in url or "/start" in url or "signin" in url:
        return True
    try:
        page_text = driver.page_source.lower()
        logged_out_signals = ["sign in", "giriş yap", "log in", "join fiverr", "kaydol"]
        logged_in_signals = ["inbox", "/users/", "logout", "çıkış"]
        has_logged_out = any(s in page_text for s in logged_out_signals)
        has_logged_in = any(s in page_text for s in logged_in_signals)
        return has_logged_out and not has_logged_in
    except Exception:
        return False


def get_fiverr_messages_manual(progress_callback=None, visible=False) -> str:
    """
    Fiverr inbox'unu kontrol eder. VARSAYILAN: arka planda (headless) -
    Ali'nin ekranina cikmaz, isini bolmez. visible=True verilirse (Ali
    'goster'/'ana ekranda yap' derse) pencere gorunur acilir.
    progress_callback verilirse her adimda cagrilir.
    """
    cb = progress_callback or _noop_callback

    cb("Tarayici aciliyor (arka planda)..." if not visible else "Tarayici aciliyor (gorebilmen icin pencere one gelecek)...")
    driver, err = get_driver(headless=not visible, bring_to_front=visible)
    if not driver:
        return f"[HATA] Tarayici baslatilamadi: {err or 'bilinmeyen hata'}. Selenium/ChromeDriver kurulu mu kontrol et."

    try:
        cb("Fiverr.com'a gidiliyor...")
        driver.get("https://www.fiverr.com")
        time.sleep(2)

        loaded = load_cookies(driver, "fiverr")
        if loaded:
            cb("Kayitli oturum bulundu, inbox'a gidiliyor...")
            driver.get("https://www.fiverr.com/inbox")
            time.sleep(3)
        else:
            cb("Kayitli oturum yok, mevcut sayfa kontrol ediliyor...")

        if _looks_logged_out_fiverr(driver):
            if not visible:
                # Arka planda giris ekranini gormesi/tiklamasi mumkun degil -
                # pencereyi sessizce acik birakmak yerine kapatip acikca
                # soyluyoruz, boylece gorunmez bir pencere ortada kalmiyor.
                driver.quit()
                return (
                    "[BILGI] Fiverr'a giris yapilmamis gibi görünüyor. Arka planda "
                    "oturum acamiyorum - 'fiverr'a giris yap, göster' de, tarayiciyi "
                    "gorunur sekilde acayim ve sen giris yapabilesin."
                )
            cb("Giris yapilmamis gibi görünüyor, pencere acik birakiliyor.")
            # Pencereyi KAPATMIYORUZ - Ali kendi gozuyle giris ekranini
            # gorsun ve isterse oradan direkt giris yapsin.
            return (
                "[BILGI] Fiverr'a giris yapilmamis gibi görünüyor. Tarayici "
                "penceresini acik biraktim, ekranina bak - giris ekranindaysa "
                "oradan giris yapabilirsin, sonra 'fiverr mesajlarima tekrar "
                "bak' de."
            )

        save_cookies(driver, "fiverr")
        cb("Sayfadaki mesajlar okunuyor...")
        messages = []
        from selenium.webdriver.common.by import By
        items = driver.find_elements(By.CSS_SELECTOR, "[class*='inbox'], [class*='conversation'], [class*='message-item']")
        for item in items[:6]:
            try:
                t = item.text.strip()
                if t and len(t) > 5:
                    messages.append(t[:200])
            except: pass

        if visible:
            # Gorunur modda Ali sonucu kendi ekraninda da gorebilsin diye
            # pencereyi acik birakiyoruz.
            if messages:
                return "[FIVERR INBOX - tarayici penceresi acik, kendi gozunle de bakabilirsin]\n" + "\n---\n".join(messages)
            return (
                "[FIVERR] Giris yapilmis görünüyor, tarayici penceresi acik "
                "biraktim - ekrana bak, sayfada mesaj var mi kendi gozunle "
                "kontrol edebilirsin. Otomatik okuma secicileri bu sayfa "
                "yapisinda bir sey bulamadi, Fiverr arayuzu degismis olabilir."
            )
        # Arka plan modda is bitince pencereyi kapatiyoruz - Ali'nin
        # ekraninda gorunmeyen bir Chrome sureci asilida kalmasin.
        driver.quit()
        if messages:
            return "[FIVERR INBOX - arka planda kontrol edildi]\n" + "\n---\n".join(messages)
        return (
            "[FIVERR] Giris yapilmis görünüyor ama sayfada mesaj bulunamadi "
            "(seciciler bu sayfa yapisinda bir sey yakalayamadi, Fiverr "
            "arayuzu degismis olabilir). 'fiverr'a bak, göster' dersen "
            "gorunur modda tekrar deneyip kendi gozunle kontrol edebilirsin."
        )
    except Exception as e:
        if not visible:
            try: driver.quit()
            except: pass
            return f"[HATA] Fiverr (arka plan): {e}"
        return f"[HATA] Fiverr: {e}. Tarayici penceresi acik kaldi, durumu kontrol edebilirsin."


def open_fiverr_for_login(progress_callback=None) -> str:
    cb = progress_callback or _noop_callback
    cb("Tarayici aciliyor...")
    driver, err = get_driver(headless=False, bring_to_front=True)
    if not driver:
        return f"[HATA] Tarayici baslatilamadi: {err or 'bilinmeyen hata'}"
    cb("Fiverr giris sayfasina gidiliyor, lutfen ekrandan giris yap...")
    driver.get("https://www.fiverr.com/login")
    # Pencere acik kalir, Ali manuel giris yapar. Burada bekleme YOK -
    # Ali'yi bekletmek yerine, giris yaptiktan sonra "fiverr mesajlarima
    # bak" demesini istiyoruz, o zaman cookie otomatik kaydedilir.
    return (
        "[TAMAM] Fiverr giris sayfasi acildi, tarayici penceresi onunde. "
        "Giris yaptiktan sonra bana 'fiverr mesajlarima bak' de, oturumunu "
        "hatirlayip devam edecegim."
    )


def get_bionluk_messages_manual(progress_callback=None, visible=False) -> str:
    cb = progress_callback or _noop_callback
    cb("Tarayici aciliyor (arka planda)..." if not visible else "Tarayici aciliyor...")
    driver, err = get_driver(headless=not visible, bring_to_front=visible)
    if not driver:
        return f"[HATA] Tarayici baslatilamadi: {err or 'bilinmeyen hata'}"

    try:
        cb("Bionluk.com'a gidiliyor...")
        driver.get("https://bionluk.com")
        time.sleep(2)
        loaded = load_cookies(driver, "bionluk")
        if loaded:
            cb("Kayitli oturum bulundu, mesajlara gidiliyor...")
            driver.get("https://bionluk.com/mesajlar")
            time.sleep(3)

        url = driver.current_url.lower()
        page_logged_out = False
        try:
            page_text = driver.page_source.lower()
            page_logged_out = any(s in page_text for s in ["giriş yap", "üye ol", "kaydol"]) and "çıkış" not in page_text
        except Exception:
            pass

        if "giris" in url or "login" in url or page_logged_out:
            if not visible:
                driver.quit()
                return (
                    "[BILGI] Bionluk'a giris yapilmamis gibi görünüyor. Arka planda "
                    "oturum acamiyorum - 'bionluk'a giris yap, göster' de, tarayiciyi "
                    "gorunur sekilde acayim."
                )
            return (
                "[BILGI] Bionluk'a giris yapilmamis gibi görünüyor. Tarayici "
                "penceresi acik, ekrandan giris yapip 'bionluk mesajlarima "
                "tekrar bak' diyebilirsin."
            )

        save_cookies(driver, "bionluk")
        cb("Mesajlar okunuyor...")
        messages = []
        from selenium.webdriver.common.by import By
        items = driver.find_elements(By.CSS_SELECTOR, ".conversation-item, .message-row, [class*='mesaj']")
        for item in items[:6]:
            try:
                t = item.text.strip()
                if t: messages.append(t[:200])
            except: pass

        if messages:
            if visible:
                return "[BIONLUK - tarayici penceresi acik]\n" + "\n---\n".join(messages)
            driver.quit()
            return "[BIONLUK - arka planda kontrol edildi]\n" + "\n---\n".join(messages)
        if not visible:
            driver.quit()
            return "[BIONLUK] Giris yapilmis görünüyor ama mesaj bulunamadi (arka plan). 'göster' dersen gorunur modda kontrol edebilirsin."
        return "[BIONLUK] Giris yapilmis görünüyor, pencere acik - sayfa yapisinin degismis olma ihtimaline karsi kendi gozunle de bakabilirsin."
    except Exception as e:
        if not visible:
            try: driver.quit()
            except: pass
            return f"[HATA] Bionluk (arka plan): {e}"
        return f"[HATA] Bionluk: {e}. Tarayici penceresi acik kaldi."
