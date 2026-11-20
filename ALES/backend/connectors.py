"""
ALES Connectors
================
Claude.ai'daki "connectors/MCP" mantiginin ALES'e tasinmis, basitlestirilmis
hali: her connector, disaridaki bir servise (Notion, Slack, Spotify, Google
Calendar, kendi API'niz vb.) API-key/token ile baglanan, acip kapatilabilen
bir tanimdir.

Depolama: APPDATA/connectors.json  →  [{id, name, description, base_url,
auth_header, icon, enabled, api_key, custom} ...]

Var olan bir connector'i kullanmak icin: connectors panelinden (veya
POST /connectors/{id}/configure ile) API key gir, ac (enabled=true).
ALES ajanina tek bir genel arac tanitilir: call_connector(connector_id,
path, method, body) - bu, connector'in base_url'ine, kayitli
auth header'i ile bir HTTP istegi yapar. Boylece her yeni connector icin
main.py'de yeni bir fonksiyon yazmaya gerek kalmaz.

Kendi connector'unuzu eklemek icin: connectors paneli > "Yeni Connector"
ile id/isim/base_url/auth bilgisi girip kaydedin - aninda kullanilabilir olur.
"""
import json
import httpx
from pathlib import Path

from config_manager import APPDATA

CONNECTORS_FILE = APPDATA / "connectors.json"

# Ilk kurulumda gelen ornek connector sablonlari (hepsi varsayilan pasif -
# kullanici kendi API key'ini girip acana kadar hicbir disaridaki servise
# istek atilmaz).
DEFAULT_CONNECTORS = [
    {
        "id": "notion",
        "name": "Notion",
        "description": "Notion sayfalarini oku/yaz (Notion API token gerekir)",
        "icon": "📝",
        "base_url": "https://api.notion.com/v1",
        "auth_style": "bearer",
        "extra_headers": {"Notion-Version": "2022-06-28"},
        "enabled": False,
        "api_key": "",
        "custom": False,
        "docs_url": "https://developers.notion.com/docs/create-a-notion-integration",
    },
    {
        "id": "slack",
        "name": "Slack",
        "description": "Slack kanallarina mesaj gonder / oku (Bot token gerekir)",
        "icon": "💬",
        "base_url": "https://slack.com/api",
        "auth_style": "bearer",
        "extra_headers": {},
        "enabled": False,
        "api_key": "",
        "custom": False,
        "docs_url": "https://api.slack.com/apps",
    },
    {
        "id": "spotify",
        "name": "Spotify",
        "description": "Spotify'da parca ara / calma listesine ekle (OAuth erisim token'i gerekir)",
        "icon": "🎵",
        "base_url": "https://api.spotify.com/v1",
        "auth_style": "bearer",
        "extra_headers": {},
        "enabled": False,
        "api_key": "",
        "custom": False,
        "docs_url": "https://developer.spotify.com/documentation/web-api",
    },
    {
        "id": "google_calendar",
        "name": "Google Calendar",
        "description": "Takvim etkinliklerini oku/ekle (Google erisim token'i gerekir)",
        "icon": "📅",
        "base_url": "https://www.googleapis.com/calendar/v3",
        "auth_style": "bearer",
        "extra_headers": {},
        "enabled": False,
        "api_key": "",
        "custom": False,
        "docs_url": "https://developers.google.com/calendar/api",
    },
]


def _load() -> list:
    if CONNECTORS_FILE.exists():
        try:
            data = json.loads(CONNECTORS_FILE.read_text(encoding="utf-8"))
            if isinstance(data, list) and data:
                return data
        except Exception:
            pass
    _save(DEFAULT_CONNECTORS)
    return json.loads(json.dumps(DEFAULT_CONNECTORS))


def _save(connectors: list):
    CONNECTORS_FILE.write_text(json.dumps(connectors, ensure_ascii=False, indent=2), encoding="utf-8")


def list_connectors() -> list:
    """API/UI icin - api_key maskelenir (var/yok bilgisi disinda disari sizmaz)."""
    out = []
    for c in _load():
        cc = dict(c)
        cc["has_key"] = bool(cc.get("api_key"))
        cc.pop("api_key", None)
        out.append(cc)
    return out


def get_connector(connector_id: str) -> dict:
    for c in _load():
        if c["id"] == connector_id:
            return c
    return None


def configure_connector(connector_id: str, api_key: str = None, enabled: bool = None) -> str:
    connectors = _load()
    for c in connectors:
        if c["id"] == connector_id:
            if api_key is not None:
                c["api_key"] = api_key
            if enabled is not None:
                c["enabled"] = bool(enabled)
            _save(connectors)
            return f"[OK] '{connector_id}' connector'i guncellendi."
    return f"[HATA] Connector bulunamadi: {connector_id}"


def add_custom_connector(connector_id: str, name: str, base_url: str, description: str = "",
                          auth_style: str = "bearer", icon: str = "🔌") -> str:
    import re
    safe_id = re.sub(r'[^a-zA-Z0-9_\-]', '_', (connector_id or "").strip())
    if not safe_id or not base_url:
        return "[HATA] id ve base_url zorunlu."
    connectors = _load()
    if any(c["id"] == safe_id for c in connectors):
        return f"[HATA] Bu id zaten kullaniliyor: {safe_id}"
    connectors.append({
        "id": safe_id, "name": name or safe_id, "description": description,
        "icon": icon, "base_url": base_url.rstrip("/"), "auth_style": auth_style,
        "extra_headers": {}, "enabled": False, "api_key": "", "custom": True, "docs_url": "",
    })
    _save(connectors)
    return f"[OK] Connector eklendi: {safe_id}"


def delete_connector(connector_id: str) -> str:
    connectors = _load()
    filtered = [c for c in connectors if c["id"] != connector_id]
    if len(filtered) == len(connectors):
        return f"[HATA] Connector bulunamadi: {connector_id}"
    _save(filtered)
    return f"[OK] Connector silindi: {connector_id}"


def get_enabled_connectors() -> list:
    return [c for c in _load() if c.get("enabled") and c.get("api_key")]


def get_tool_categories() -> dict:
    """tool_router.py icin - her aktif connector kendi kategorisi olur,
    kullanicinin mesaji connector adini gecerse call_connector arac listesine girer."""
    cats = {}
    for c in get_enabled_connectors():
        cats[f"connector:{c['id']}"] = {
            "keywords": [c["id"], c["name"].lower()],
            "tools": ["call_connector"],
        }
    return cats


def call_connector(connector_id: str, path: str, method: str = "GET", body: dict = None, params: dict = None) -> str:
    """Aktif bir connector uzerinden HTTP istegi yapar. Bu, main.py'nin
    execute_tool'unda 'call_connector' tool-cagrisi geldiginde calisir."""
    c = get_connector(connector_id)
    if not c:
        return f"[HATA] Connector bulunamadi: {connector_id}"
    if not c.get("enabled"):
        return f"[HATA] '{connector_id}' connector'i pasif. Once Connectors panelinden ac ve API key gir."
    if not c.get("api_key"):
        return f"[HATA] '{connector_id}' icin API key girilmemis. Connectors panelinden ekle."

    url = c["base_url"].rstrip("/") + "/" + path.lstrip("/")
    headers = {"Content-Type": "application/json"}
    headers.update(c.get("extra_headers") or {})
    if c.get("auth_style") == "bearer":
        headers["Authorization"] = f"Bearer {c['api_key']}"
    elif c.get("auth_style") == "header_key":
        headers[c.get("auth_header_name", "X-API-Key")] = c["api_key"]

    try:
        with httpx.Client(timeout=15) as client:
            r = client.request(method.upper(), url, headers=headers, params=params or {}, json=body if body else None)
            text = r.text
            if len(text) > 3000:
                text = text[:3000] + "...[kesildi]"
            return f"[{connector_id.upper()} {r.status_code}] {text}"
    except Exception as e:
        return f"[HATA] Connector istegi basarisiz: {e}"
