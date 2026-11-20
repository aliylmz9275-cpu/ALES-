"""
_ornek_eklenti.py — ALES eklenti SABLONU.

Bu dosya BILEREK "_" ile baslar: plugin_loader "_" ile baslayan dosyalari
taramaz, yani bu sablon yuklenmez ve arac listesine girmez. Kendi eklentini
yazmak icin bu dosyayi "_" olmadan yeni bir isimle kopyala:

    copy _ornek_eklenti.py  hesap.py

sonra UI'da Ayarlar -> EKLENTILER -> Yenile (veya POST /plugins/reload).

Ornek iki arac tanimliyor: biri ilerleme bildirimi kullaniyor, biri
kullanmiyor — ikisi de gecerli imza.
"""
PLUGIN_API = 1


def _topla(args, progress_cb=None):
    """Handler imzasi 1: (args, progress_cb). Uzun surecek isler icin
    progress_cb("...") cagirirsan kullanici arayuzde ilerlemeyi gorur."""
    try:
        a = float(args.get("a", 0))
        b = float(args.get("b", 0))
    except (TypeError, ValueError):
        return "[HATA] a ve b sayi olmali."
    if progress_cb:
        try:
            progress_cb("toplama yapiliyor...")
        except Exception:
            pass          # ilerleme bildirimi bir eklentiyi ASLA dusurmemeli
    return f"{a} + {b} = {a + b}"


def _tersine_cevir(args):
    """Handler imzasi 2: sadece (args). plugin_loader imzayi okur ve
    progress_cb'yi bu fonksiyona GECIRMEZ."""
    metin = str(args.get("metin", ""))
    if not metin:
        return "[HATA] 'metin' bos."
    return metin[::-1]


def on_load():
    print("[PLUGIN] ornek eklenti yuklendi")


def on_unload():
    print("[PLUGIN] ornek eklenti bosaltildi")


def register():
    return {
        "id": "ornek",
        "name": "Ornek Eklenti",
        "description": "Eklenti sablonu: toplama + metni tersine cevirme.",
        "version": "1.0.0",
        "api": PLUGIN_API,
        # keywords: tool_router bu kelimeleri gorurse eklentinin araclarini
        # modele sunar (49 cekirdek arac arasinda bogulmasin diye).
        "keywords": ["ornek", "topla", "tersine", "sablon"],
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": "plugin_ornek_topla",
                    "description": "Iki sayiyi toplar ve sonucu dondurur.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "a": {"type": "number", "description": "birinci sayi"},
                            "b": {"type": "number", "description": "ikinci sayi"},
                        },
                        "required": ["a", "b"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "plugin_ornek_tersine",
                    "description": "Verilen metni tersine cevirir.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "metin": {"type": "string", "description": "cevrilecek metin"},
                        },
                        "required": ["metin"],
                    },
                },
            },
        ],
        "handlers": {
            "plugin_ornek_topla": _topla,
            "plugin_ornek_tersine": _tersine_cevir,
        },
        "on_load": on_load,
        "on_unload": on_unload,
    }
