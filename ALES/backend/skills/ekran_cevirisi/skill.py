"""
Ekran Çevirisi - skill.py
Aktif pencereyi yakalar, once yerel OCR ile metni cikartip Groq ile
hizlica cevirir; OCR yoksa/basarisizsa vision zincirine (Groq/Gemini/
Ollama/OpenRouter - vision.py) tek adimda "oku ve cevir" diye sorar.
"""

SKILL_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "translate_screen",
            "description": "Ekrandaki (aktif pencere) yazıyı hedef dile çevirir.",
            "parameters": {
                "type": "object",
                "properties": {
                    "target_language": {"type": "string", "description": "Hedef dil, örn: Türkçe, İngilizce (varsayılan Türkçe)"},
                    "region": {"type": "string", "enum": ["auto", "active_window", "full_screen"]},
                },
                "required": [],
            },
        },
    },
]


def _translate_text_with_groq(text: str, target_language: str, groq_key: str) -> str:
    from groq import Groq
    client = Groq(api_key=groq_key)
    resp = client.chat.completions.create(
        model="openai/gpt-oss-120b",
        messages=[{
            "role": "user",
            "content": f"Aşağıdaki metni {target_language} diline çevir. SADECE çeviriyi yaz, başka açıklama ekleme:\n\n{text}"
        }],
        max_tokens=800,
    )
    return resp.choices[0].message.content.strip()


def _translate(target_language: str = "Türkçe", region: str = "auto", progress_cb=None) -> str:
    try:
        from config_manager import load_config
        import vision

        if progress_cb:
            progress_cb("Ekran görüntüsü alınıyor...")
        img = vision._grab_screen(region)
        if img.width > vision.MAX_PREVIEW_WIDTH:
            ratio = vision.MAX_PREVIEW_WIDTH / float(img.width)
            img = img.resize((vision.MAX_PREVIEW_WIDTH, max(1, int(img.height * ratio))))

        cfg = load_config()

        # 1) Once yerel OCR ile metni cikartmayi dene (hizli, ag yok)
        ocr_text = None
        try:
            import pytesseract
            raw = pytesseract.image_to_string(img).strip()
            if len(raw) >= 5:
                ocr_text = raw
        except Exception:
            pass

        if ocr_text:
            if progress_cb:
                progress_cb("Metin bulundu, çevriliyor...")
            groq_key = cfg.get("groq_key", "")
            if groq_key:
                try:
                    translated = _translate_text_with_groq(ocr_text, target_language, groq_key)
                    return f"🌐 Çeviri ({target_language}):\n{translated}\n\n[Orijinal metin (OCR)]:\n{ocr_text[:500]}"
                except Exception as e:
                    print(f"[EKRAN_CEVIRISI] Groq çeviri hatası, vision'a düşülüyor: {e}")
            # groq yoksa/basarisizsa asagidaki vision fallback'e dus

        # 2) OCR yoksa/basarisizsa: tek adimda vision modeline "oku ve cevir" sor
        if progress_cb:
            progress_cb("Vision ile okunuyor ve çevriliyor...")
        import tempfile, os
        path = os.path.join(tempfile.gettempdir(), "ales_translate.jpg")
        img.convert("RGB").save(path, "JPEG", quality=vision.JPEG_QUALITY, optimize=True)
        question = f"Ekrandaki yazıyı oku ve {target_language} diline çevir. Sadece çeviriyi ver, kısa tut."
        result = vision.analyze_screenshot(path, question)
        return f"🌐 {result}"
    except Exception as e:
        return f"❌ Ekran çevirisi hatası: {e}"


def run(tool_name: str, args: dict, progress_cb=None):
    if tool_name == "translate_screen":
        return _translate(
            args.get("target_language", "Türkçe"),
            args.get("region", "auto"),
            progress_cb,
        )
    return f"[HATA] Bilinmeyen ekran çevirisi aracı: {tool_name}"
