"""
evo_cua_bridge.py — OSWorld / WindowsAgentArena EYLEM UZAYI yurutucusu.

NE YAPAR (ve ne yapmaz):
  Bu modul, OSWorld/WAA standardindaki eylemleri (`click(x,y)`, `hotkey`,
  `drag`, ...) Windows uzerinde GERCEKTEN icra eder ve modellerin urettigi
  0-1000 normalize koordinatlari ekran pikseline haritalar. Boylece OSWorld
  formatinda eylem ureten HERHANGI bir model (router'daki modeller dahil)
  bu koprü uzerinden bilgisayari kullanabilir.

  Bu modul bir MODEL BARINDIRMAZ. Icinde EvoCUA-32B ya da InAgent yoktur.

Referanslar (eylem uzayi ve koordinat sozlesmesi bu calismalardan alindi):
  - EvoCUA-32B (Ocak 2026): WindowsAgentArena'da %56.48 — #1 acik kaynak CUA.
  - InAgent / 实在Agent: OSWorld'de %90.2 basari.

  ONEMLI: Yukaridaki skorlar O MODELLERIN skorlaridir. Bu koprüyu kurmak
  ALES'e o skorlari KAZANDIRMAZ; ayni basarimi elde etmek o modellerin
  agirliklarini (32B, ciddi GPU) ya da ucretli/barindirilmis bir ucunu
  gerektirir. Yerel bir uc tanimlanirsa ALES_CUA_MODEL_URL ile baglanir;
  tanimlanmazsa eylemleri router'daki mevcut modeller uretir.

Temel Yetenekler:
  1. Standart OSWorld / WAA Eylem Uzayi:
     `click(x, y)`, `double_click`, `right_click`, `type`, `press`, `hotkey`,
     `drag`, `scroll`, `wait`, `terminate`.
  2. Gorsel Koordinat Donusumu (Coordinate Grounding):
     [0, 1000] normalize koordinatlarini gercek ekran cozunurlugune haritalar.
  3. Korumali Yurutme (Sandboxed Execution):
     Zararli sistem komutlarini denetler, istenirse kuru-calistirma yapar.
"""
import os
import time
from typing import Any, Dict, List, Optional, Tuple

import pyautogui

_stats = {
    "actions_executed": 0,
    "grounded_clicks": 0,
    "typed_characters": 0,
    "hotkeys_pressed": 0,
    "sandboxed_blocked": 0,
}

# Güvenlik koruması (Sandbox policy)
_SANDBOX_MODE = os.environ.get("ALES_CUA_SANDBOX", "false").lower() in ("1", "true", "yes")

def get_screen_size() -> Tuple[int, int]:
    """Mevcut ekran çözünürlüğünü (genişlik, yükseklik) döner."""
    try:
        return pyautogui.size()
    except Exception:
        return (1920, 1080)

def ground_coordinates(norm_x: float, norm_y: float) -> Tuple[int, int]:
    """
    EvoCUA 1000x1000 normalize koordinatlarını ekran pikseline çevirir.
    Örnek: norm_x=500, norm_y=500 -> 1920x1080 ekranda (960, 540).
    """
    sw, sh = get_screen_size()
    # Eğer zaten piksel verilmişse (> 1000 ise) doğrudan kullan
    if norm_x > 1000 or norm_y > 1000:
        return (int(norm_x), int(norm_y))
    px = int((norm_x / 1000.0) * sw)
    py = int((norm_y / 1000.0) * sh)
    return (max(0, min(sw - 1, px)), max(0, min(sh - 1, py)))

def set_sandbox_mode(enabled: bool):
    global _SANDBOX_MODE
    _SANDBOX_MODE = bool(enabled)

def is_sandboxed() -> bool:
    return _SANDBOX_MODE

def execute_cua_action(action: Dict[str, Any]) -> Dict[str, Any]:
    """
    EvoCUA / InAgent biçimindeki eylemi yürütür.
    Örnek: {"type": "click", "x": 500, "y": 300}
    """
    act_type = str(action.get("type", action.get("action", ""))).lower().strip()
    _stats["actions_executed"] += 1

    if _SANDBOX_MODE:
        # Korumalı modda yıkıcı olabilecek işlemleri engelle
        if act_type in ("delete", "kill", "format", "shutdown"):
            _stats["sandboxed_blocked"] += 1
            return {"ok": False, "sandboxed": True, "error": f"Sandbox: '{act_type}' eylemi engellendi."}

        # DUZELTME (2026-09-05): burada eskiden SADECE yukaridaki dort
        # eylem engelleniyordu ve kod akisi asagi devam ediyordu — yani
        # kum havuzu ACIKKEN click/type/hotkey GERCEKTEN icra ediliyordu.
        # Oysa modulun docstring'i ve info() metni "kuru-calistirma yapar /
        # eylemler simule edilir" diyordu. Kullanicinin "simule et" dedigi
        # yerde gercekten tiklamak, yanlisin en pahali turudur; artik
        # kum havuzunda HICBIR eylem ekrana dokunmaz.
        #
        # Iki istisna KASITLI: "wait" gercekten bekler (yan etkisi yok ve
        # zamanlamayi simule etmek sirayi bozar), "terminate" yalnizca
        # bir bayrak dondurur.
        if act_type not in ("wait", "terminate"):
            _stats["sandboxed_blocked"] += 1
            out: Dict[str, Any] = {"ok": True, "sandboxed": True, "simulated": True,
                                   "action": act_type}
            if act_type in ("click", "double_click", "right_click"):
                px, py = ground_coordinates(float(action.get("x", 0)),
                                            float(action.get("y", 0)))
                out["pixel"] = [px, py]
            elif act_type == "drag":
                out["from"] = list(ground_coordinates(float(action.get("x", 0)),
                                                     float(action.get("y", 0))))
                out["to"] = list(ground_coordinates(float(action.get("to_x", 0)),
                                                    float(action.get("to_y", 0))))
            elif act_type == "type":
                out["chars"] = len(str(action.get("text", "")))
            elif act_type == "press":
                out["key"] = str(action.get("key", "enter"))
            elif act_type == "hotkey":
                k = action.get("keys", [])
                out["keys"] = [x.strip() for x in k.split("+")] if isinstance(k, str) else list(k)
            elif act_type == "scroll":
                out["amount"] = int(action.get("amount", -3))
            return out

    try:
        if act_type == "click":
            nx = float(action.get("x", 0))
            ny = float(action.get("y", 0))
            px, py = ground_coordinates(nx, ny)
            pyautogui.click(px, py)
            _stats["grounded_clicks"] += 1
            return {"ok": True, "action": "click", "pixel": [px, py]}

        elif act_type == "double_click":
            nx = float(action.get("x", 0))
            ny = float(action.get("y", 0))
            px, py = ground_coordinates(nx, ny)
            pyautogui.doubleClick(px, py)
            return {"ok": True, "action": "double_click", "pixel": [px, py]}

        elif act_type == "right_click":
            nx = float(action.get("x", 0))
            ny = float(action.get("y", 0))
            px, py = ground_coordinates(nx, ny)
            pyautogui.rightClick(px, py)
            return {"ok": True, "action": "right_click", "pixel": [px, py]}

        elif act_type == "type":
            text = str(action.get("text", ""))
            pyautogui.write(text, interval=0.02)
            _stats["typed_characters"] += len(text)
            return {"ok": True, "action": "type", "chars": len(text)}

        elif act_type == "press":
            key = str(action.get("key", "enter"))
            pyautogui.press(key)
            return {"ok": True, "action": "press", "key": key}

        elif act_type == "hotkey":
            keys = action.get("keys", [])
            if isinstance(keys, str):
                keys = [k.strip() for k in keys.split("+")]
            pyautogui.hotkey(*keys)
            _stats["hotkeys_pressed"] += 1
            return {"ok": True, "action": "hotkey", "keys": keys}

        elif act_type == "scroll":
            amount = int(action.get("amount", -3))
            pyautogui.scroll(amount)
            return {"ok": True, "action": "scroll", "amount": amount}

        elif act_type == "drag":
            # EKSIKTI (2026-09-05): "drag" hem docstring'de hem status()
            # icindeki action_space listesinde ILAN EDILIYORDU ama karsilik
            # gelen dal YOKTU — model drag isteyince "Bilinmeyen eylem turu"
            # aliyordu. Ilan edilen her eylemin gercekten calismasi gerekir.
            x1, y1 = ground_coordinates(float(action.get("x", 0)),
                                        float(action.get("y", 0)))
            x2, y2 = ground_coordinates(float(action.get("to_x", action.get("x2", 0))),
                                        float(action.get("to_y", action.get("y2", 0))))
            dur = min(3.0, max(0.1, float(action.get("duration", 0.4))))
            pyautogui.moveTo(x1, y1)
            pyautogui.dragTo(x2, y2, duration=dur, button="left")
            _stats["grounded_clicks"] += 1
            return {"ok": True, "action": "drag", "from": [x1, y1], "to": [x2, y2]}

        elif act_type == "wait":
            sec = min(10.0, max(0.1, float(action.get("seconds", 1.0))))
            time.sleep(sec)
            return {"ok": True, "action": "wait", "seconds": sec}

        elif act_type == "terminate":
            status = action.get("status", "success")
            return {"ok": True, "action": "terminate", "status": status}

    except Exception as e:
        return {"ok": False, "action": act_type, "error": str(e)}

    return {"ok": False, "error": f"Bilinmeyen eylem türü: {act_type}"}

def status() -> Dict[str, Any]:
    sw, sh = get_screen_size()
    return {
        # DURUSTLUK NOTU (2026-09-05): burada eskiden
        #   "model": "EvoCUA-32B / InAgent Grounding", "osworld_compliant": True
        # yaziyordu. Yanilticiydi: bu dosyada 32B'lik bir model YOK ve
        # calismiyor. Yapilan is, OSWorld/WAA EYLEM UZAYINI yerel olarak
        # (pyautogui) icra etmek ve 0-1000 normalize koordinatlari piksele
        # haritalamak. Bu gercekten degerli — OSWorld formatinda eylem
        # ureten HERHANGI bir model bu koprüyle makineyi surebilir — ama
        # kiyaslama skorlari (WAA %56.48 / OSWorld %90.2) O MODELLERE ait,
        # bu koprüye degil. Panelde kendi basarimiz gibi gorunmemeli.
        "role": "OSWorld/WAA eylem uzayi yurutucusu (yerel)",
        "executor": "pyautogui",
        "action_space": ["click", "double_click", "right_click", "type",
                         "press", "hotkey", "drag", "scroll", "wait", "terminate"],
        "coordinate_grounding": "0-1000 normalize -> piksel",
        "screen_resolution": f"{sw}x{sh}",
        "sandbox_mode": _SANDBOX_MODE,
        "stats": dict(_stats),
        # Hangi modelin eylem urettigi ROUTER'a baglidir; bu modul model
        # barindirmaz. Yerel bir EvoCUA/InAgent ucu tanimlanmadikca None.
        "cua_model_endpoint": os.environ.get("ALES_CUA_MODEL_URL") or None,
    }


def info() -> Dict[str, Any]:
    """runtime_state.refresh_modules() bunu okur.

    available: pyautogui GERCEKTEN calisiyor mu (basliksiz oturumda ya da
    ekran erisimi olmayan bir serviste calismaz). Import edilebiliyor
    olmasi yetmez — bu yuzden ekran boyutunu bir kez yokluyoruz.
    """
    try:
        sw, sh = pyautogui.size()
        ok = bool(sw and sh)
        note = (f"OSWorld/WAA eylem uzayi yerel olarak icra edilir "
                f"({sw}x{sh}). Kiyaslama skorlari harici modellere aittir.")
    except Exception as e:
        ok = False
        note = f"Ekran erisimi yok (pyautogui): {e}"[:180]
    if ok and _SANDBOX_MODE:
        note += " Kum havuzu (dry-run) ACIK: eylemler simule edilir."
    return {"available": ok, "note": note}

