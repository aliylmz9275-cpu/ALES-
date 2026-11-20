"""
SABLON: AI Chatbot / Asistan
Kullanim: Groq API ile (ucretsiz, hizli) musteriye ozel chatbot.
Musteri kendi API key'ini kullanmak isterse GROQ_API_KEY degerini degistir.

DUZENLENECEK YERLER asagida [DUZENLE] etiketiyle isaretli.

Kurulum (bir kere): pip install groq
API Key: https://console.groq.com (ucretsiz)
"""
from groq import Groq

# [DUZENLE] Musterinin kendi API key'i (teslimde .env dosyasina tasinmali,
# kod icine GOMULMEMELI - bu sadece test/sablon amaclidir)
GROQ_API_KEY = "musterinin_kendi_key_i_buraya"

# [DUZENLE] Chatbot'un kisiligi ve uzmanlik alani - musteri briefine gore yaz
SYSTEM_PROMPT = """Sen [DUZENLE: chatbot adi], [DUZENLE: hangi isletme/konu]
icin calisan bir asistansin.

GOREVIN:
- [DUZENLE: ne yapacagini yaz, orn: musteri sorularini yanitla, urun onerisi yap]

KURALLAR:
- [DUZENLE: yasakli konular, ton (resmi/samimi), dil]
- Bilmedigin bir soru gelirse, tahmin etme; "Bu konuda kesin bilgim yok,
  [DUZENLE: yetkili kisi/destek hatti] ile iletisime gecebilirsiniz" de.
"""

client = Groq(api_key=GROQ_API_KEY)

# Basit hafiza - bir oturum boyunca konusma gecmisini tutar
conversation_history = []


def chat(user_message: str) -> str:
    conversation_history.append({"role": "user", "content": user_message})

    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + conversation_history[-20:]

    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",  # [DUZENLE] gerekirse model degistir
        messages=messages,
        max_tokens=1024,
        temperature=0.7,
    )

    reply = response.choices[0].message.content
    conversation_history.append({"role": "assistant", "content": reply})
    return reply


def run_cli():
    """Komut satirinda test/demo icin basit dongu"""
    print("Chatbot hazir. Cikmak icin 'exit' yaz.\n")
    while True:
        user_input = input("Sen: ")
        if user_input.strip().lower() in ("exit", "quit", "cikis"):
            break
        reply = chat(user_input)
        print(f"Bot: {reply}\n")


if __name__ == "__main__":
    run_cli()

# NOT (Fiverr/Bionluk teslimi icin):
# - Musteri web sitesine entegrasyon istiyorsa, chat() fonksiyonu bir
#   Flask/FastAPI endpoint'ine baglanir (ALES bunu brief'e gore ekler).
# - Telegram/WhatsApp istegi gelirse, ilgili kutuphane (python-telegram-bot
#   vb.) ile chat() fonksiyonu cagrilir - bu sablonun disinda, ekstra is.
