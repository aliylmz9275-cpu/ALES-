"""PDF Generation Test — Escape character fix verification."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from document_generator import generate_pdf

# Simüle: LLM tool_call argümanlarında gelen literal \n (iki karakter: backslash + n)
raw_content = (
    "Bu bir test raporu.\\n\\n"
    "## Türkçe Karakter Testi\\n\\n"
    "Çığırtkan öğretmen şüpheli ışıkta güzel bir söz söyledi.\\n\\n"
    "### Madde Listesi\\n\\n"
    "- Birinci madde\\n"
    "- İkinci madde (**kalın**)\\n"
    "- Üçüncü madde\\n\\n"
    "---\\n\\n"
    "Sonuç: Türkçe karakterler doğru çalışıyor."
)

result = generate_pdf("Türkçe Test Raporu", raw_content)
ok = result.get("ok")
fn = result.get("filename", "")
size = result.get("size_bytes", 0)
print(f"PDF Result: ok={ok}, filename={fn}, size={size} bytes")

if ok:
    path = result.get("path")
    with open(path, "rb") as f:
        pdf_bytes = f.read()
    # PDF içinde literal \n (iki karakter) olmamalı
    has_literal = b"\\n" in pdf_bytes
    if has_literal:
        print("WARNING: Literal backslash-n found in PDF!")
    else:
        print("[PASS] No literal backslash-n in PDF.")
    print(f"[PASS] PDF generated at: {path}")
else:
    print(f"FAIL: {result.get('error')}")
