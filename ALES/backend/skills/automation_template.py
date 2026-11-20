"""
SABLON: Zamanlanmis Otomasyon / Bildirim Botu
Kullanim: Belirli araliklarla bir kontrolu calistirir, kosul tutarsa
bildirim gonderir (dosyaya yazma, e-posta, Telegram - secenekler asagida).

DUZENLENECEK YERLER asagida [DUZENLE] etiketiyle isaretli.

Kurulum (gerekirse): pip install requests
"""
import time
from datetime import datetime

# [DUZENLE] Kontrol araligi (saniye) - ornek: 3600 = her saat
CHECK_INTERVAL_SECONDS = 3600


def check_condition() -> tuple[bool, str]:
    """
    [DUZENLE] Buraya gercek kontrol mantigini yaz.
    Donus: (kosul_tuttu_mu: bool, mesaj: str)

    Ornek senaryolar:
    - Bir URL'deki fiyatin belirli bir degerin altina dusmesi
    - Bir API'den gelen verinin degismesi
    - Bir dosyanin icindeki bir degerin esik asmasi
    """
    # ORNEK: sahte bir kontrol - gercek mantikla degistir
    kosul_tuttu = False
    mesaj = "Kontrol yapildi, kosul henuz tutmadi."
    return kosul_tuttu, mesaj


def send_notification(message: str):
    """
    [DUZENLE] Bildirim yontemini sec ve asagidaki secenekten birini ac.
    Varsayilan: log dosyasina yazma (en basit, key gerektirmez).
    """
    timestamp = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
    log_line = f"[{timestamp}] {message}\n"

    # SECENEK 1 (varsayilan): Dosyaya yaz
    with open("bildirimler.log", "a", encoding="utf-8") as f:
        f.write(log_line)
    print(f"[BILDIRIM] {message}")

    # SECENEK 2: Telegram (asagidaki 2 satiri acip kendi bilgilerini gir)
    # import requests
    # requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
    #               data={"chat_id": CHAT_ID, "text": message})

    # SECENEK 3: E-posta (smtplib ile - musteri SMTP bilgisi verirse eklenir)


def run_once():
    """Tek seferlik kontrol - test icin"""
    tutuldu, mesaj = check_condition()
    print(f"[KONTROL] {mesaj}")
    if tutuldu:
        send_notification(mesaj)
    return tutuldu


def run_loop():
    """Surekli calisan dongu - gercek kullanimda bu calisir"""
    print(f"[BASLADI] Her {CHECK_INTERVAL_SECONDS} saniyede bir kontrol edilecek.")
    while True:
        run_once()
        time.sleep(CHECK_INTERVAL_SECONDS)


if __name__ == "__main__":
    # Test sirasinda run_once() kullan (ALES bunu test eder).
    # Gercek/kalici calisma icin musteriye run_loop() veya Windows
    # Gorev Zamanlayicisi ile run_once() kullanmasini soyle.
    run_once()
