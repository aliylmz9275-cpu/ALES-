"""
Tool Router - ALES'i zekilestiren en kritik parca.

35+ arac var. Hepsini her seferinde modele gondermek:
- Token harcar (limit daha hizli dolar)
- Kucuk modelleri (Llama/Cerebras) kafasini karistirir
- Yanlis arac secimini artirir

Bunun yerine: kullanicinin mesajina bakip SADECE ilgili
araclari + her zaman gerekli "cekirdek" araclari gonderiyoruz.

Bu, isair/jarvis ve benzeri projelerin kullandigi "tool routing"
teknigi - kucuk/ucretsiz modellerle buyuk fark yaratir.
"""

# Her zaman gonderilen cekirdek araclar (en sik kullanilanlar)
CORE_TOOLS = {
    "remember_fact", "search_memory", "get_user_profile",
    "add_pending_approval", "get_system_info", "generate_pdf",
    "read_file", "write_file", "run_terminal_command",
}

# Bu kategoriler HER ZAMAN aktif - ALES'in "Claude gibi" temel
# yetenekleri. Kisitlanirsa model elinde arac olmadigi icin
# "yapamiyorum" der.
ALWAYS_INCLUDE_CATEGORIES = ["pc_control", "filesystem", "document", "web", "code", "terminal", "worldview", "memory"]

# Kategori -> anahtar kelimeler -> arac isimleri
TOOL_CATEGORIES = {
    "document": {
        "keywords": ["pdf", "rapor", "belge", "dokuman", "doküman", "yazdır", "yazdir",
                      "kitapçık", "kitapcik", "çıktı", "cikti", "generate_pdf"],
        "tools": ["generate_pdf"]
    },
    "pc_control": {
        "keywords": ["ekran", "tikla", "yaz", "tus", "ac aç", "uygulama", "screenshot",
                      "goruntu", "kapat", "minimize", "pencere", "fare", "klavye"],
        "tools": ["take_screenshot", "open_app", "type_text", "press_key", "click_at",
                  "analyze_screen", "find_on_screen",
                  "cua_action"]
    },
    "filesystem": {
        "keywords": ["dosya", "klasor", "klasör", "oku", "yaz", "duzenle", "düzenle",
                      "sil", "olustur", "oluştur", "kaydet", "ara", "bul", "liste",
                      "klasoru", "icerik", "içerik", "rapor", "belge", "txt", "csv", "json",
                      "pdf", "dokuman", "doküman"],
        "tools": ["read_file", "write_file", "edit_file", "list_directory",
                  "create_directory", "delete_path", "search_files", "get_file_info",
                  "list_skills", "read_skill", "generate_pdf"]
    },
    "web": {
        "keywords": ["ara", "arastir", "araştır", "internet", "site", "web", "google",
                      "sayfa", "link", "url", "haber"],
        "tools": ["fetch_url", "google_search", "browse_web", "web_search_deep",
                  "get_news_tr"]
    },
    "worldview": {
        "keywords": ["gundem", "gündem", "dunya", "dünya", "hava", "doviz", "döviz",
                      "kripto", "bitcoin", "ethereum", "kur", "bugün", "bugun", "ne var",
                      "ne oldu", "haberler"],
        "tools": ["get_worldview", "get_weather", "get_crypto_prices",
                  "get_exchange_rates", "get_news_tr"]
    },
    "fiverr": {
        "keywords": ["fiverr", "bionluk", "musteri", "müşteri", "is", "iş", "gorev",
                      "görev", "siparis", "sipariş", "mesaj", "is yeri"],
        "tools": ["check_fiverr_messages", "check_bionluk_messages", "open_fiverr_login",
                  "add_fiverr_task", "get_fiverr_tasks"]
    },
    "schedule": {
        "keywords": ["zamanla", "her gun", "her gün", "hatirlat", "hatırlat", "saat",
                      "sabah", "aksam", "akşam", "tekrar", "bildirim", "uyar"],
        "tools": ["add_schedule", "list_schedules", "remove_schedule",
                  "send_notification", "add_notification_rule", "list_notification_rules"]
    },
    "code": {
        "keywords": ["kod", "python", "hesapla", "calistir", "çalıştır", "script",
                      "fonksiyon", "program", "yazılım", "yazilim", "debug", "test",
                      "hata", "duzelt", "düzelt", "refactor"],
        "tools": ["run_python_code", "run_terminal_command", "read_file", "write_file", "edit_file"]
    },
    # ── Kabuk komutu (Terminal / Shell) ──────────────────────────────
    "terminal": {
        "keywords": ["terminal", "komut satiri", "komut satırı", "cmd", "powershell",
                      "kabuk", "shell", "bash", "git ", "npm", "pip install",
                      "derle", "build", "komutu calistir", "komutu çalıştır", "run"],
        "tools": ["run_terminal_command", "openclaw_terminal"]
    },
    # ── OpenClaw koprusu (OPT-IN) ────────────────────────────────────
    # Bu araclarin yaptigi isi ALES yerel olarak DA yapiyor (list_windows /
    # click_control / browse_web). Harici daemon kurulu degilse bunlar zaten
    # o yerel yedeklere duser — yani her mesajda gondermenin bir kazanci yok.
    # Sadece kullanici acikca OpenClaw'dan soz ederse devreye girer.
    "openclaw": {
        "keywords": ["openclaw", "daemon", "harici ajan", "kopru", "koprü",
                      "bilgisayar kullanimi", "bilgisayar kullanımı"],
        "tools": ["openclaw_desktop", "openclaw_browser", "openclaw_terminal",
                  "cua_action"]
    },
    "multi_agent": {
        "keywords": ["derin analiz", "4 ai", "4 yapay", "5 ai", "5 yapay", "tartis", "tartış",
                      "farkli perspektif", "farklı perspektif", "ortak fikir",
                      "ne dusunur", "ne düşünür", "multi agent", "kapsamli analiz",
                      "kapsamlı analiz", "derinlemesine", "tüm ai", "tum ai"],
        "tools": ["multi_agent_discuss"]
    },
    "memory": {
        "keywords": ["hatirla", "hatırla", "unutma", "ogren", "öğren", "profil",
                      "kim oldugumu", "beni", "ogrendiklerini", "öğrendiklerini", "notlar"],
        "tools": ["update_user_profile", "get_all_facts"]
    },
    "phone": {
        "keywords": ["telefon", "tunnel", "link ver", "uzaktan", "disardan", "dışarıdan",
                      "her yerden", "mobil", "android"],
        "tools": ["start_tunnel", "get_phone_access"]
    },
    "persona": {
        "keywords": ["mod degistir", "mod değiştir", "is modu", "iş modu", "ogretmen",
                      "öğretmen", "dinlenme", "gece modu", "persona", "siparis modu",
                      "sipariş modu", "siparis geldi", "sipariş geldi", "musteri siparisi",
                      "müşteri siparişi", "brief"],
        "tools": ["set_persona", "list_personas"]
    },
}

def _all_categories() -> dict:
    """TOOL_CATEGORIES + skills/ ve connectors/ tarafindan eklenen dinamik
    kategoriler. Boylece yeni bir skill veya connector eklendiginde
    tool_router.py'ye dokunmadan otomatik olarak dogru anahtar kelimelerle
    devreye girer. Skills/connectors calisma zamaninda acilip
    kapatilabildigi icin bunlar sabit degil, her cagrida taze okunur."""
    cats = dict(TOOL_CATEGORIES)
    try:
        import skills_engine
        cats.update(skills_engine.get_tool_categories())
    except Exception:
        pass
    try:
        import connectors
        cats.update(connectors.get_tool_categories())
    except Exception:
        pass
    return cats


def select_relevant_tools(user_message: str, all_tools: list) -> list:
    """
    Kullanici mesajina gore ilgili araclari sec.

    ALWAYS_INCLUDE: PC kontrolu, dosya sistemi, web, kod, worldview, hafiza.
    Bunlar ALES'in "Claude gibi" temel yetenekleri - kisitlanirsa model
    elinde arac olmadigi icin "yapamiyorum" der. Bu yuzden hep aciktirlar.

    OPT-IN (sadece anahtar kelime eslesirse): fiverr, zamanlama, telefon,
    persona - daha niş, her mesajda gerekmeyen araclar.
    """
    msg = user_message.lower()
    selected_names = set(CORE_TOOLS)
    matched_categories = []
    all_categories = _all_categories()

    for cat_name in ALWAYS_INCLUDE_CATEGORIES:
        selected_names.update(all_categories[cat_name]["tools"])

    for cat_name, cat in all_categories.items():
        if cat_name in ALWAYS_INCLUDE_CATEGORIES:
            continue
        if any(kw in msg for kw in cat["keywords"]):
            selected_names.update(cat["tools"])
            matched_categories.append(cat_name)

    # Filtrele
    filtered = [t for t in all_tools if t["function"]["name"] in selected_names]

    # Guvenlik: hicbir sey secilmediyse hepsini don (asla bos kalma)
    if not filtered:
        return all_tools

    return filtered

def get_routing_info(user_message: str) -> str:
    """Debug/log icin - hangi opsiyonel kategoriler tetiklendi"""
    msg = user_message.lower()
    matched = [name for name, cat in _all_categories().items()
               if name not in ALWAYS_INCLUDE_CATEGORIES and any(kw in msg for kw in cat["keywords"])]
    return f"Daima acik: {ALWAYS_INCLUDE_CATEGORIES} | Ek: {matched or ['yok']}"

def expand_after_tool_call(current_tools: list, used_tool_names: list, all_tools: list) -> list:
    """
    Ilk tool-call turundan sonra arac listesini genisletir - AMA tum 49
    araca degil. Eskiden burada dogrudan TOOLS (hepsi) kullaniliyordu;
    bu her ek turda ~930 token fazladan gonderiyordu (49 aracin JSON
    semasi), cok adimli isteklerde gozle gorulur yavasliga sebep oluyordu.

    Bunun yerine: modelin AZ ONCE kullandigi araclarin ait oldugu
    kategori(ler)i bulup, sadece o kategorileri de mevcut listeye ekler.
    Yani "scope" buyur ama 49'a degil, ilgili komsulara genisler.
    """
    selected_names = {t["function"]["name"] for t in current_tools}

    # Kullanilan her aracin hangi kategori(ler)den geldigini bul, o
    # kategorinin TUMUNU ekle (model bir sonraki adimda ayni alandan
    # baska bir arac isteyebilir, orn: read_file sonrasi edit_file)
    for cat in _all_categories().values():
        if any(name in cat["tools"] for name in used_tool_names):
            selected_names.update(cat["tools"])

    filtered = [t for t in all_tools if t["function"]["name"] in selected_names]
    return filtered if filtered else current_tools
