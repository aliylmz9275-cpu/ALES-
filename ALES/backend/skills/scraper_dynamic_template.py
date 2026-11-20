"""
SABLON: Dinamik (JS ile yuklenen) Site Scraping
Kullanim: Playwright ile gercek tarayici acar, JS calismasini bekler,
sonra veriyi okur. Statik HTML siteler icin scraper_static_template.py
daha hizli ve hafiftir - once onu dene.

DUZENLENECEK YERLER asagida [DUZENLE] etiketiyle isaretli.

Kurulum (bir kere): pip install playwright && playwright install chromium
"""
from playwright.sync_api import sync_playwright
import csv
import time

# [DUZENLE] Hedef URL
URL = "https://ornek-site.com/urunler"

# [DUZENLE] Sayfanin tam yuklendigini anlamak icin beklenecek eleman
WAIT_SELECTOR = ".urun-karti"


def scrape():
    results = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(URL, wait_until="domcontentloaded", timeout=20000)

        # [DUZENLE] JS icerigin yuklenmesini bekle (gerekirse selector'u degistir)
        try:
            page.wait_for_selector(WAIT_SELECTOR, timeout=10000)
        except Exception:
            print("[UYARI] Beklenen eleman bulunamadi, devam ediliyor (sayfa farkli yapida olabilir).")

        time.sleep(1)  # ekstra JS render suresi icin kucuk bir tampon

        # [DUZENLE] Her ogeyi sec ve veriyi cek
        items = page.query_selector_all(WAIT_SELECTOR)
        for item in items:
            title_el = item.query_selector(".urun-baslik")
            price_el = item.query_selector(".urun-fiyat")
            link_el = item.query_selector("a")

            results.append({
                "baslik": title_el.inner_text().strip() if title_el else "",
                "fiyat": price_el.inner_text().strip() if price_el else "",
                "link": link_el.get_attribute("href") if link_el else "",
            })

        browser.close()
    return results


def save_csv(data, filename="sonuc.csv"):
    if not data:
        print("[UYARI] Hic veri bulunamadi. WAIT_SELECTOR veya veri secicileri yanlis olabilir.")
        return
    with open(filename, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=data[0].keys())
        writer.writeheader()
        writer.writerows(data)
    print(f"[OK] {len(data)} kayit '{filename}' dosyasina yazildi.")


if __name__ == "__main__":
    data = scrape()
    save_csv(data)
