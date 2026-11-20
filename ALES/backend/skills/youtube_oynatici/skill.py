"""
YouTube Oynatici - skill.py
Her skill.py'nin uymasi gereken sozlesme:
  - SKILL_TOOLS: main.py'deki TOOLS ile ayni formatta bir tool-sema listesi
  - run(tool_name, args, progress_cb=None) -> str : cagriyi yurutur, sonucu doner
"""
import re
import webbrowser
import httpx

SKILL_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "play_youtube_video",
            "description": "YouTube'da bir video/sarki arar ve BULDUGU ILK sonucu dogrudan oynatir (tarayicida acar). 'youtube'da X'i ac/izlet/oynat/çal' gibi isteklerde kullan.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Aranacak video, sarki veya sanatci adi"}
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_youtube",
            "description": "YouTube'da arama yapar, ilk birkac sonucun basligini ve linkini dondurur (hicbirini acmadan/oynatmadan).",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Aranacak terim"}
                },
                "required": ["query"],
            },
        },
    },
]

_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}


def _search_raw(query: str) -> str:
    url = f"https://www.youtube.com/results?search_query={_url_encode(query)}"
    with httpx.Client(timeout=10, follow_redirects=True, headers=_HEADERS) as client:
        r = client.get(url)
        r.raise_for_status()
        return r.text


def _url_encode(q: str) -> str:
    from urllib.parse import quote
    return quote(q)


def _extract_first_videos(html: str, limit: int = 5):
    """Sayfa HTML'inden video id + basliklarini regex ile cikartir.
    YouTube sayfa yapisini degistirebilir; bu yuzden birden fazla desen dener
    ve bulamazsa bos liste doner (cagiran taraf arama sayfasini acmaya duser)."""
    results = []
    seen = set()
    # ytInitialData icindeki "videoId":"..." ve yakinindaki basligi yakalamaya calis
    for m in re.finditer(r'"videoId":"([a-zA-Z0-9_-]{11})".*?"text":"([^"]{2,120})"', html):
        vid, title = m.group(1), m.group(2)
        if vid not in seen:
            seen.add(vid)
            results.append((vid, title))
        if len(results) >= limit:
            break
    if not results:
        # Daha basit fallback: sadece videoId'leri sirayla al, baslik bilinmesin
        for m in re.finditer(r'"videoId":"([a-zA-Z0-9_-]{11})"', html):
            vid = m.group(1)
            if vid not in seen:
                seen.add(vid)
                results.append((vid, "(baslik alinamadi)"))
            if len(results) >= limit:
                break
    return results


def _play(query: str, progress_cb=None) -> str:
    if progress_cb:
        progress_cb(f"YouTube'da '{query}' aranıyor...")
    try:
        html = _search_raw(query)
        videos = _extract_first_videos(html, limit=1)
        if videos:
            vid, title = videos[0]
            watch_url = f"https://www.youtube.com/watch?v={vid}"
            if progress_cb:
                progress_cb("Video bulundu, açılıyor...")
            webbrowser.open(watch_url)
            return f"✅ '{title}' oynatılıyor: {watch_url}"
        # Sonuc cikartilamadi - en azindan arama sayfasini ac
        search_url = f"https://www.youtube.com/results?search_query={_url_encode(query)}"
        webbrowser.open(search_url)
        return f"⚠️ İlk sonuç otomatik bulunamadı, arama sayfası açıldı: {search_url}"
    except Exception as e:
        return f"❌ YouTube'a erişilemedi: {e}"


def _search(query: str) -> str:
    try:
        html = _search_raw(query)
        videos = _extract_first_videos(html, limit=5)
        if not videos:
            return f"'{query}' için sonuç bulunamadı."
        lines = [f"[YOUTUBE ARAMA: {query}]"]
        for vid, title in videos:
            lines.append(f"  * {title} — https://www.youtube.com/watch?v={vid}")
        return "\n".join(lines)
    except Exception as e:
        return f"❌ Arama hatası: {e}"


def run(tool_name: str, args: dict, progress_cb=None):
    if tool_name == "play_youtube_video":
        return _play(args["query"], progress_cb)
    if tool_name == "search_youtube":
        return _search(args["query"])
    return f"[HATA] Bilinmeyen youtube skill aracı: {tool_name}"
