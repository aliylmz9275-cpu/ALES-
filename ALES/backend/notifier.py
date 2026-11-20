import asyncio
import json
import subprocess
from datetime import datetime
from pathlib import Path

try:
    from config_manager import NOTIF_FILE as notify_file
except Exception:
    notify_file = Path("notifications.json")

def load_notifications() -> list:
    if notify_file.exists():
        return json.loads(notify_file.read_text(encoding="utf-8"))
    return []

def save_notifications(n: list):
    notify_file.write_text(json.dumps(n, ensure_ascii=False, indent=2), encoding="utf-8")

def windows_notify(title: str, message: str):
    """Windows 11 bildirim gönder"""
    try:
        script = f"""
Add-Type -AssemblyName System.Windows.Forms
$notify = New-Object System.Windows.Forms.NotifyIcon
$notify.Icon = [System.Drawing.SystemIcons]::Information
$notify.Visible = $true
$notify.ShowBalloonTip(5000, '{title}', '{message}', [System.Windows.Forms.ToolTipIcon]::None)
Start-Sleep -Seconds 6
$notify.Dispose()
"""
        subprocess.Popen(
            ["powershell", "-WindowStyle", "Hidden", "-Command", script],
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0
        )
        return True
    except Exception as e:
        print(f"[NOTIFIER] Bildirim hatasi: {e}")
        return False

def add_notification_rule(trigger: str, message: str, check_interval: int = 3600) -> str:
    """
    Proaktif bildirim kuralı ekle.
    trigger formatlari:
      'time:09:00'          - her gun bu saatte
      'crypto_drop:BTC:5'   - BTC bir onceki kontrole gore %5+ degisirse
      'fiverr_message'      - yeni Fiverr mesaji algilanirsa
      'news_keyword:bitcoin'- haberlerde bu kelime gecerse
    """
    rules = load_notifications()
    rule_id = int(datetime.now().timestamp())
    rules.append({
        "id": rule_id,
        "trigger": trigger,
        "message": message,
        "check_interval": check_interval,
        "active": True,
        "last_checked": None,
        "created": datetime.now().isoformat()
    })
    save_notifications(rules)
    return f"✅ Bildirim kuralı eklendi: [{trigger}] → {message}"

def list_notification_rules() -> str:
    rules = load_notifications()
    if not rules:
        return "🔔 Aktif bildirim kuralı yok."
    lines = ["🔔 Bildirim Kuralları:"]
    for r in rules:
        status = "✅" if r["active"] else "⏸️"
        lines.append(f"  {status} [{r['id']}] {r['trigger']} → {r['message']}")
    return "\n".join(lines)

def remove_notification_rule(rule_id: int) -> str:
    rules = load_notifications()
    rules = [r for r in rules if r["id"] != rule_id]
    save_notifications(rules)
    return f"✅ Kural kaldırıldı: {rule_id}"

def send_notification(title: str, message: str) -> str:
    """Anında bildirim gönder"""
    success = windows_notify(title, message)
    return f"✅ Bildirim gönderildi: {title}" if success else f"⚠️ Bildirim gönderilemedi (ama kaydedildi)"

async def run_notifier(browser_module, check_callback, fiverr_module=None):
    """Arka planda bildirim kurallarini kontrol et.
    ARTIK 'fiverr_message' ve 'crypto_drop' tetikleyicileri de GERCEKTEN
    calisiyor (eskiden sadece dokumanda vaad edilmisti, kod placeholder
    ya da tamamen eksikti)."""
    print("[NOTIFIER] Motoru basladi...")
    # crypto_drop icin: bir onceki kontrolde gorulen fiyati sakla (id -> fiyat)
    _last_crypto_snapshot: dict = {}
    while True:
        try:
            rules = load_notifications()
            now = datetime.now()

            for rule in rules:
                if not rule.get("active"):
                    continue

                trigger = rule["trigger"]
                last = rule.get("last_checked")
                interval = rule.get("check_interval", 3600)

                if last:
                    elapsed = (now - datetime.fromisoformat(last)).total_seconds()
                    if elapsed < interval:
                        continue

                triggered = False
                notify_msg = rule["message"]

                # Zaman tetikleyici
                if trigger.startswith("time:"):
                    target_time = trigger.split(":")[1] + ":" + trigger.split(":")[2]
                    if now.strftime("%H:%M") == target_time:
                        triggered = True

                # Kripto dusus/yukselis tetikleyici - trigger: "crypto_drop:BTC:5"
                # (BTC %5'ten fazla degisirse haber ver - onceki kontrole gore)
                elif trigger.startswith("crypto_drop:"):
                    try:
                        parts = trigger.split(":")
                        coin = parts[1].upper()
                        threshold_pct = float(parts[2]) if len(parts) > 2 else 5.0
                        prices_text = browser_module.get_crypto_prices()
                        # get_crypto_prices metin donduruyor - coin adinin
                        # gectigi satirdan basit bir fiyat cikarimi yap
                        current_price = None
                        for line in prices_text.splitlines():
                            if coin in line.upper():
                                import re as _re
                                m = _re.search(r'[\d]+[\.,]?[\d]*', line.replace(coin, ""))
                                if m:
                                    current_price = float(m.group(0).replace(",", "."))
                                    break
                        if current_price is not None:
                            prev = _last_crypto_snapshot.get(coin)
                            _last_crypto_snapshot[coin] = current_price
                            if prev:
                                change_pct = ((current_price - prev) / prev) * 100
                                if abs(change_pct) >= threshold_pct:
                                    triggered = True
                                    direction = "yükseldi 📈" if change_pct > 0 else "düştü 📉"
                                    notify_msg = f"💰 {coin} %{abs(change_pct):.1f} {direction}! {rule['message']}"
                    except Exception as e:
                        print(f"[NOTIFIER] crypto_drop kontrolu hatasi: {e}")

                # Fiverr yeni mesaj tetikleyici - trigger: "fiverr_message"
                elif trigger == "fiverr_message" and fiverr_module is not None:
                    try:
                        result = fiverr_module.get_fiverr_messages_manual(visible=False)
                        # "yeni mesaj yok" / "0 mesaj" gibi olumsuz sonuclari filtrele
                        neg_markers = ("yeni mesaj yok", "mesaj yok", "0 yeni", "bulunamadı", "hata")
                        if result and not any(m in result.lower() for m in neg_markers):
                            triggered = True
                            notify_msg = f"📩 Fiverr'da yeni mesaj olabilir! {rule['message']}\n{result[:200]}"
                    except Exception as e:
                        print(f"[NOTIFIER] fiverr_message kontrolu hatasi: {e}")

                # Haber kelimesi tetikleyici
                elif trigger.startswith("news_keyword:"):
                    keyword = trigger.split(":")[1]
                    news = browser_module.get_news_tr()
                    if keyword.lower() in news.lower():
                        triggered = True
                        notify_msg = f"📰 '{keyword}' haberlerde! {rule['message']}"

                if triggered:
                    windows_notify("ALES", notify_msg)
                    await check_callback(notify_msg)

                rule["last_checked"] = now.isoformat()

            save_notifications(rules)

        except Exception as e:
            print(f"[NOTIFIER] Motor hatasi: {e}")

        await asyncio.sleep(60)
