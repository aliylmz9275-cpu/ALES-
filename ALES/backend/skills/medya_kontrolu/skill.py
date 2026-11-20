"""
Medya/Spotify Kontrolü - skill.py
pyautogui ile isletim sisteminin medya tuslarini simule eder - hangi
uygulama odaktaysa (Spotify, YouTube, VLC, vb.) onu kontrol eder.
"""

SKILL_TOOLS = [
    {"type": "function", "function": {
        "name": "media_play_pause",
        "description": "Müziği/videoyu oynat veya duraklat (Spotify, YouTube, vb. - hangisi aktifse)",
        "parameters": {"type": "object", "properties": {}, "required": []},
    }},
    {"type": "function", "function": {
        "name": "media_next",
        "description": "Sonraki parçaya/videoya geç",
        "parameters": {"type": "object", "properties": {}, "required": []},
    }},
    {"type": "function", "function": {
        "name": "media_previous",
        "description": "Önceki parçaya/videoya dön",
        "parameters": {"type": "object", "properties": {}, "required": []},
    }},
    {"type": "function", "function": {
        "name": "media_volume_up",
        "description": "Ses seviyesini artır",
        "parameters": {"type": "object", "properties": {}, "required": []},
    }},
    {"type": "function", "function": {
        "name": "media_volume_down",
        "description": "Ses seviyesini kıs",
        "parameters": {"type": "object", "properties": {}, "required": []},
    }},
]

_KEY_MAP = {
    "media_play_pause": ("playpause", "▶️ Oynat/duraklat"),
    "media_next": ("nexttrack", "⏭️ Sonraki parça"),
    "media_previous": ("prevtrack", "⏮️ Önceki parça"),
    "media_volume_up": ("volumeup", "🔊 Ses artırıldı"),
    "media_volume_down": ("volumedown", "🔉 Ses kısıldı"),
}


def run(tool_name: str, args: dict, progress_cb=None):
    mapping = _KEY_MAP.get(tool_name)
    if not mapping:
        return f"[HATA] Bilinmeyen medya skill aracı: {tool_name}"
    key, label = mapping
    try:
        import pyautogui
        pyautogui.press(key)
        return f"✅ {label}"
    except Exception as e:
        return f"❌ Medya tuşu gönderilemedi: {e}"
