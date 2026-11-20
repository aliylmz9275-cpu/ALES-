"""
smoke_test.py — ALES Backend Automated Smoke Testing Script

Tests:
1. Backend availability / Server auto-start
2. GET /status (200 OK, status: online)
3. POST /desktop/test (200 OK, ok: True, base64 screenshot, detailed error logging)
4. POST /speak (200 OK, ok: True, audio bytes / valid audio payload)
5. POST /config save & verify persistence (preserve original config)
"""
import sys
import os
import time
import json
import base64
import subprocess
import urllib.request
import urllib.error

BASE_URL = "http://127.0.0.1:8000"
BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))


def _http_get(path: str, timeout: float = 10.0):
    url = f"{BASE_URL}{path}"
    req = urllib.request.Request(url, headers={"User-Agent": "ALES-SmokeTest"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.getcode(), json.loads(resp.read().decode("utf-8"))


def _http_post(path: str, data: dict = None, timeout: float = 30.0):
    url = f"{BASE_URL}{path}"
    payload = json.dumps(data or {}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json", "User-Agent": "ALES-SmokeTest"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        ct = resp.headers.get("Content-Type", "")
        body = resp.read()
        if "application/json" in ct:
            return resp.getcode(), json.loads(body.decode("utf-8"))
        return resp.getcode(), body


def ensure_server_running():
    """FastAPI sunucusunun çalıştığından emin ol, çalışmıyorsa başlat."""
    try:
        code, data = _http_get("/status", timeout=2.0)
        if code == 200:
            print("[SMOKE TEST] Sunucu halihazırda çalışıyor (127.0.0.1:8000).")
            return None
    except Exception:
        pass

    print("[SMOKE TEST] Sunucu çalışmıyor, uvicorn başlatılıyor...")
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", "8000"],
        cwd=BACKEND_DIR,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    # 15 saniye boyunca sunucunun hazır olmasını bekle
    start_time = time.time()
    while time.time() - start_time < 15.0:
        try:
            code, data = _http_get("/status", timeout=1.0)
            if code == 200:
                print("[SMOKE TEST] Sunucu başarıyla başlatıldı ve hazır!")
                return proc
        except Exception:
            time.sleep(0.5)

    # Zaman aşımı
    proc.terminate()
    raise RuntimeError("Sunucu 15 saniye içinde başlatılamadı!")


def test_status():
    print("\n--- TEST 1: GET /status ---")
    code, data = _http_get("/status")
    print(f"Status Code: {code}")
    print(f"Response: {data}")
    assert code == 200, f"Beklenen 200, gelen {code}"
    assert data.get("status") == "online", f"Beklenen status online, gelen: {data.get('status')}"
    print(">>> TEST 1 GEÇTİ [OK]")


def test_desktop():
    print("\n--- TEST 2: POST /desktop/test ---")
    try:
        code, data = _http_post("/desktop/test", timeout=30.0)
    except urllib.error.HTTPError as e:
        print(f"HTTP Error: {e.code} - {e.read().decode('utf-8')}")
        raise
    except Exception as e:
        print(f"Masaüstü testi isteği başarısız: {e}")
        raise

    print(f"Status Code: {code}")
    print(f"OK: {data.get('ok')}")
    print(f"Message: {data.get('message')}")
    if not data.get("ok"):
        print(f"HATA DETAYI: {data.get('error')}")
        raise RuntimeError(f"Desktop test failed: {data.get('error')}")

    shot = data.get("screenshot")
    assert shot and len(shot) > 100, "Ekran görüntüsü verisi boş veya çok kısa!"
    img_bytes = base64.b64decode(shot)
    print(f"Ekran görüntüsü boyutu: {len(img_bytes)} bayt (PNG Header: {img_bytes[:8].hex()})")
    assert img_bytes.startswith(b"\x89PNG\r\n\x1a\n"), "Geçersiz PNG başlığı!"
    print(">>> TEST 2 GEÇTİ [OK]")


def test_speak():
    print("\n--- TEST 3: POST /speak ---")
    code, data = _http_post("/speak", {"text": "Test"}, timeout=20.0)
    print(f"Status Code: {code}")
    assert code == 200, f"Beklenen 200, gelen {code}"

    if isinstance(data, dict):
        assert data.get("ok") is True, f"Ses sentezi başarısız: {data.get('error')}"
        audio_b64 = data.get("audio")
        assert audio_b64, "Ses verisi boş!"
        audio_bytes = base64.b64decode(audio_b64)
    else:
        audio_bytes = data

    print(f"Ses verisi boyutu: {len(audio_bytes)} bayt")
    assert len(audio_bytes) > 200, "Ses verisi çok kısa (< 200 bayt)!"
    print(">>> TEST 3 GEÇTİ [OK]")


def test_config():
    print("\n--- TEST 4: POST /config save & verify ---")
    import config_manager
    original_cfg = config_manager.load_config()
    original_groq = original_cfg.get("groq_key", "")

    test_dummy = "smoke_dummy_key_999"
    try:
        code, res = _http_post("/config", {"groq_key": test_dummy})
        assert code == 200, f"Config kaydı başarısız: {code}"

        saved_cfg = config_manager.load_config()
        assert saved_cfg.get("groq_key") == test_dummy, f"Anahtar kaydedilemedi! Beklenen: {test_dummy}, Mevcut: {saved_cfg.get('groq_key')}"

        code, cfg_api = _http_get("/config")
        assert cfg_api.get("has_groq") is True, "API has_groq False döndürdü!"
        print("Ayar kaydı ve kalıcılık doğrulandı.")
    finally:
        # Eski ayarı geri yükle
        if original_groq:
            _http_post("/config", {"groq_key": original_groq})
        else:
            _http_post("/config", {"groq_key": "", "clear_groq_key": True})
        restored = config_manager.load_config().get("groq_key", "")
        assert restored == original_groq, "Orijinal ayar geri yüklenemedi!"
        print("Orijinal ayarlar başarıyla geri yüklendi.")

    print(">>> TEST 4 GEÇTİ [OK]")


def test_test_key():
    print("\n--- TEST 5: POST /test-key validation ---")
    code, res = _http_post("/test-key", {"provider": "groq", "key": "invalid_smoke_test_key"})
    print(f"Status Code: {code}, Response: {res}")
    assert code == 200, f"Beklenen 200, gelen {code}"
    assert res.get("ok") is False, "Geçersiz anahtar onaylandı, False dönmeliydi!"
    assert ("Invalid API Key" in res.get("error", "") or "Groq Hatası" in res.get("error", "")), f"Beklenen hata mesajı eksik: {res.get('error')}"
    print(">>> TEST 5 GEÇTİ [OK]")


def run_all_tests():
    server_proc = None
    results = {}
    try:
        server_proc = ensure_server_running()

        tests = [
            ("test_status", test_status),
            ("test_desktop", test_desktop),
            ("test_speak", test_speak),
            ("test_config", test_config),
            ("test_test_key", test_test_key),
        ]

        for name, fn in tests:
            try:
                fn()
                results[name] = "PASSED"
            except Exception as e:
                results[name] = f"FAILED: {e}"
                print(f"!!! {name} BAŞARISIZ: {e}")

        print("\n" + "=" * 50)
        print("SMOKE TEST SONUÇLARI:")
        all_passed = True
        for name, res in results.items():
            print(f"  {name}: {res}")
            if res != "PASSED":
                all_passed = False
        print("=" * 50)

        if not all_passed:
            sys.exit(1)
        print("\nTÜM SMOKE TESTLER BAŞARIYLA TAMAMLANDI!")

    finally:
        if server_proc:
            print("[SMOKE TEST] Test için başlatılan sunucu kapatılıyor...")
            server_proc.terminate()
            try:
                server_proc.wait(timeout=5)
            except Exception:
                server_proc.kill()


if __name__ == "__main__":
    run_all_tests()
