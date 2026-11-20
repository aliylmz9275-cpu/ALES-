import httpx
import json
import re
from datetime import datetime
from urllib.parse import quote

def clean_html(html: str) -> str:
    """HTML taglarını temizle"""
    clean = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL)
    clean = re.sub(r'<style[^>]*>.*?</style>', '', clean, flags=re.DOTALL)
    clean = re.sub(r'<[^>]+>', ' ', clean)
    clean = re.sub(r'\s+', ' ', clean).strip()
    return clean[:4000]

def fetch_url(url: str) -> str:
    """Bir URL'yi getir ve temiz metin döndür"""
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        with httpx.Client(timeout=10, follow_redirects=True) as client:
            r = client.get(url, headers=headers)
            r.raise_for_status()
            text = clean_html(r.text)
            return f"✅ {url}\n\n{text}"
    except Exception as e:
        return f"❌ URL getirilemedi: {e}"

def get_news_tr() -> str:
    """Turkiye'den guncel haberler (RSS)"""
    feeds = [
        ("Haberler", "https://www.hurriyet.com.tr/rss/anasayfa"),
        ("Son Dakika", "https://www.ntv.com.tr/son-dakika.rss"),
    ]
    results = []
    headers = {"User-Agent": "Mozilla/5.0"}
    for name, url in feeds:
        try:
            with httpx.Client(timeout=8) as client:
                r = client.get(url, headers=headers)
                titles = re.findall(r'<title><!\[CDATA\[(.*?)\]\]></title>', r.text)
                if not titles:
                    titles = re.findall(r'<title>(.*?)</title>', r.text)
                titles = [t.strip() for t in titles[1:8] if t.strip() and len(t) > 10]
                if titles:
                    results.append(f"[{name}]:\n" + "\n".join([f"  * {t}" for t in titles]))
        except:
            pass
    return "\n\n".join(results) if results else "Haberler alinamadi."

def get_weather(city: str = "Istanbul") -> str:
    """Hava durumu - wttr.in (ücretsiz, API key yok)"""
    try:
        url = f"https://wttr.in/{quote(city)}?format=3&lang=tr"
        with httpx.Client(timeout=8) as client:
            r = client.get(url)
            return f"[HAVA] {r.text.strip()}"
    except Exception as e:
        return f"[HATA] Hava durumu alinamadi: {e}"

def get_earthquakes() -> str:
    """Son 24 saatteki M4.5+ depremler - USGS (ucretsiz, key yok, resmi API)"""
    try:
        url = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/4.5_day.geojson"
        with httpx.Client(timeout=8) as client:
            r = client.get(url)
            data = r.json()
            features = data.get("features", [])
            if not features:
                return "[DEPREM] Son 24 saatte M4.5+ deprem yok."
            # En guclu 5 tanesini goster
            features.sort(key=lambda f: f["properties"].get("mag", 0), reverse=True)
            lines = [f"[DEPREM] Son 24 saat, M4.5+ ({len(features)} olay, en guclu {min(5,len(features))} tanesi):"]
            for f in features[:5]:
                p = f["properties"]
                mag = p.get("mag", "?")
                place = p.get("place", "bilinmiyor")
                lines.append(f"  M{mag} - {place}")
            return "\n".join(lines)
    except Exception as e:
        return f"[HATA] Deprem verisi alinamadi: {e}"

def get_crypto_prices() -> str:
    """Kripto fiyatlari - CoinGecko (ucresiz)"""
    try:
        url = "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin,ethereum,solana&vs_currencies=usd,try"
        with httpx.Client(timeout=8) as client:
            r = client.get(url)
            data = r.json()
            lines = ["[KRIPTO] Fiyatlar:"]
            names = {"bitcoin": "Bitcoin", "ethereum": "Ethereum", "solana": "Solana"}
            for coin, vals in data.items():
                usd = vals.get("usd", "?")
                try_price = vals.get("try", "?")
                lines.append(f"  {names.get(coin, coin)}: ${usd:,} / TL{try_price:,}")
            return "\n".join(lines)
    except Exception as e:
        return f"[HATA] Kripto fiyatlari alinamadi: {e}"

def get_exchange_rates() -> str:
    """Doviz kurlari"""
    try:
        url = "https://api.exchangerate-api.com/v4/latest/USD"
        with httpx.Client(timeout=8) as client:
            r = client.get(url)
            data = r.json()
            rates = data.get("rates", {})
            lines = ["[DOVIZ] Kurlar (USD bazli):"]
            for cur in ["TRY", "EUR", "GBP"]:
                if cur in rates:
                    lines.append(f"  1 USD = {rates[cur]:.2f} {cur}")
            return "\n".join(lines)
    except Exception as e:
        return f"[HATA] Doviz alinamadi: {e}"

def google_search(query: str) -> str:
    """DuckDuckGo ile arama (API key yok)"""
    try:
        url = f"https://api.duckduckgo.com/?q={quote(query)}&format=json&no_html=1&skip_disambig=1"
        with httpx.Client(timeout=8) as client:
            r = client.get(url)
            data = r.json()
            results = []
            if data.get("AbstractText"):
                results.append(f"[SONUC] {data['AbstractText'][:500]}")
            for item in data.get("RelatedTopics", [])[:5]:
                if isinstance(item, dict) and item.get("Text"):
                    results.append(f"  * {item['Text'][:200]}")
            return "\n".join(results) if results else f"'{query}' icin sonuc bulunamadi."
    except Exception as e:
        return f"[HATA] Arama hatasi: {e}"

def get_worldview() -> str:
    """Tam worldview ozeti - HIZ: 5 ayri HTTP kaynagi (hava, deprem, doviz,
    kripto, haber) ESKIDEN sirayla cekiliyordu (toplam sure = hepsinin
    toplami, ~4-8sn). Artik ThreadPoolExecutor ile PARALEL cekiliyor -
    toplam sure = EN YAVAS kaynagin suresi (~1-2sn), 3-4x hizlanma."""
    from concurrent.futures import ThreadPoolExecutor
    tasks = {
        "weather": lambda: get_weather("Istanbul"),
        "earthquakes": lambda: get_earthquakes(),
        "exchange": lambda: get_exchange_rates(),
        "crypto": lambda: get_crypto_prices(),
        "news": lambda: get_news_tr(),
    }
    results = {}
    with ThreadPoolExecutor(max_workers=len(tasks)) as ex:
        futures = {ex.submit(fn): name for name, fn in tasks.items()}
        for fut in futures:
            name = futures[fut]
            try:
                results[name] = fut.result(timeout=12)
            except Exception as e:
                results[name] = f"[HATA] {name} alinamadi: {e}"

    parts = [f"[WORLDVIEW] {datetime.now().strftime('%d.%m.%Y %H:%M')}", "=" * 40]
    for name in ("weather", "earthquakes", "exchange", "crypto", "news"):
        parts.append(results[name])
    return "\n\n".join(parts)
