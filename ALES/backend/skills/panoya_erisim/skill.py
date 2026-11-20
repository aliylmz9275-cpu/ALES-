"""
Panoya Erişim - skill.py
Once pyperclip dener, o yoksa/basarisiz olursa tkinter uzerinden
(Python'un standart kutuphanesiyle gelir, ekstra kurulum gerekmez)
yedek bir yol dener.
"""

SKILL_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "read_clipboard",
            "description": "Panodaki (clipboard) güncel metni oku. 'az önce kopyaladığım şey' gibi isteklerde kullan.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_clipboard",
            "description": "Panoya (clipboard) yeni bir metin yaz/kopyala.",
            "parameters": {
                "type": "object",
                "properties": {"text": {"type": "string", "description": "Panoya yazılacak metin"}},
                "required": ["text"],
            },
        },
    },
]


def _read() -> str:
    try:
        import pyperclip
        text = pyperclip.paste()
        if not text:
            return "📋 Pano boş."
        preview = text if len(text) <= 1500 else text[:1500] + "...[kesildi]"
        return f"📋 Panodaki metin:\n{preview}"
    except Exception:
        pass
    try:
        import tkinter as tk
        root = tk.Tk()
        root.withdraw()
        text = root.clipboard_get()
        root.destroy()
        if not text:
            return "📋 Pano boş."
        preview = text if len(text) <= 1500 else text[:1500] + "...[kesildi]"
        return f"📋 Panodaki metin:\n{preview}"
    except Exception as e:
        return f"❌ Panoya erişilemedi: {e}"


def _write(text: str) -> str:
    try:
        import pyperclip
        pyperclip.copy(text)
        return f"✅ Panoya kopyalandı ({len(text)} karakter)"
    except Exception:
        pass
    try:
        import tkinter as tk
        root = tk.Tk()
        root.withdraw()
        root.clipboard_clear()
        root.clipboard_append(text)
        root.update()
        root.destroy()
        return f"✅ Panoya kopyalandı ({len(text)} karakter)"
    except Exception as e:
        return f"❌ Panoya yazılamadı: {e}"


def run(tool_name: str, args: dict, progress_cb=None):
    if tool_name == "read_clipboard":
        return _read()
    if tool_name == "write_clipboard":
        return _write(args["text"])
    return f"[HATA] Bilinmeyen pano skill aracı: {tool_name}"
