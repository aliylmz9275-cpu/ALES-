"""
SABLON: Statik Site Scraping
Kullanim: requests + BeautifulSoup ile, JS calistirmadan HTML'i okur.
JS ile yuklenen icerik icin scraper_dynamic_template.py kullan.

DUZENLENECEK YERLER asagida [DUZENLE] etiketiyle isaretli.
"""
import requests
from bs4 import BeautifulSoup
import csv

# [DUZENLE] Hedef URL
URL = "https://ornek-site.com/urunler"

# [DUZENLE] Tarayici gibi gorunmek icin (cogu site bunu ister)
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
}

def scrape():
    resp = requests.get(URL, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    results = []
    # [DUZENLE] CSS secicisini hedef sitenin HTML yapisina gore degistir.
    # Tarayicida F12 -> Elementi sec -> "Copy selector" ile bulabilirsin.
    items = soup.select(".urun-karti")  # ORNEK secici

    for item in items:
        # [DUZENLE] Her veri alani icin dogru seciciyi kullan
        title_el = item.select_one(".urun-baslik")
        price_el = item.select_one(".urun-fiyat")
        link_el = item.select_one("a")

        results.append({
            "baslik": title_el.get_text(strip=True) if title_el else "",
            "fiyat": price_el.get_text(strip=True) if price_el else "",
            "link": link_el["href"] if link_el and link_el.has_attr("href") else "",
        })

    return results

def save_csv(data, filename="sonuc.csv"):
    if not data:
        print("[UYARI] Hic veri bulunamadi. Seciciler yanlis olabilir - hedef sitenin HTML yapisini kontrol et.")
        return
    with open(filename, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=data[0].keys())
        writer.writeheader()
        writer.writerows(data)
    print(f"[OK] {len(data)} kayit '{filename}' dosyasina yazildi.")

if __name__ == "__main__":
    data = scrape()
    save_csv(data)
