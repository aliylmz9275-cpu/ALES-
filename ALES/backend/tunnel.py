"""
Telefon erisimi - ngrok veya Cloudflare Tunnel.
PC acikken her yerden ALES'e baglan.
"""
import subprocess, os, time, json, threading
from pathlib import Path

tunnel_info_file = Path("tunnel_info.json")

def start_ngrok(port: int = 8000) -> str:
    """ngrok tunnel baslat - her yerden erisim"""
    try:
        # ngrok yuklu mu?
        result = subprocess.run(["ngrok", "version"], capture_output=True, text=True)
        if result.returncode != 0:
            return "[BILGI] ngrok yuklu degil. https://ngrok.com/download adresinden indir, PATH'e ekle."

        # Onceki tunnel'i durdur
        subprocess.run(["taskkill", "/f", "/im", "ngrok.exe"], capture_output=True)
        time.sleep(1)

        # Yeni tunnel baslat
        proc = subprocess.Popen(
            ["ngrok", "http", str(port)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        time.sleep(3)

        # URL al
        try:
            import urllib.request
            with urllib.request.urlopen("http://localhost:4040/api/tunnels") as r:
                data = json.loads(r.read())
                url = data["tunnels"][0]["public_url"]
                # HTTPS yap
                if url.startswith("http://"):
                    url = "https://" + url[7:]

                tunnel_info_file.write_text(json.dumps({
                    "url": url, "port": port, "started": time.time()
                }))

                # Frontend URL da ekle
                frontend_url = url.replace(":8000", ":5173") if ":8000" in url else url + ":5173"

                return (
                    f"[TUNNEL AKTIF]\n"
                    f"Backend: {url}\n"
                    f"Telefon: {url.replace('8000','5173')}\n"
                    f"Bu linki telefon tarayicina yaz, ALES acilir."
                )
        except:
            return "[TUNNEL BASLADI] http://localhost:4040 adresinden URL'yi grebilirsin."

    except FileNotFoundError:
        return "[BILGI] ngrok bulunamadi. https://ngrok.com/download adresinden indir."
    except Exception as e:
        return f"[HATA] Tunnel: {e}"

def start_cloudflare_tunnel(port: int = 8000) -> str:
    """Cloudflare Tunnel - ngrok alternatifi, ucretsiz"""
    try:
        result = subprocess.run(["cloudflared", "version"], capture_output=True, text=True)
        if result.returncode != 0:
            return "[BILGI] cloudflared yuklu degil. https://github.com/cloudflare/cloudflared/releases adresinden indir."

        proc = subprocess.Popen(
            ["cloudflared", "tunnel", "--url", f"http://localhost:{port}"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )
        # URL'yi stderr'den oku
        for _ in range(20):
            line = proc.stderr.readline()
            if "trycloudflare.com" in line:
                import re
                urls = re.findall(r'https://[\w-]+\.trycloudflare\.com', line)
                if urls:
                    return f"[CLOUDFLARE TUNNEL]\nURL: {urls[0]}\nTelefondan bu linki ac."
            time.sleep(0.5)

        return "[CLOUDFLARE] Baslatildi ama URL alinamadi. Biraz bekle."
    except FileNotFoundError:
        return "[BILGI] cloudflared yuklu degil."
    except Exception as e:
        return f"[HATA] {e}"

def get_local_ip() -> str:
    """Ayni WiFi'deki IP adresini bul"""
    try:
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return (
            f"[YEREL AG ERISIMI]\n"
            f"PC IP: {ip}\n"
            f"Telefon (ayni WiFi): http://{ip}:5173\n"
            f"Backend: http://{ip}:8000\n"
            f"NOT: PC ve telefon ayni WiFi'ye bagli olmali."
        )
    except Exception as e:
        return f"IP alinamadi: {e}"

def get_tunnel_status() -> str:
    if tunnel_info_file.exists():
        info = json.loads(tunnel_info_file.read_text())
        return f"[AKTIF TUNNEL] {info.get('url', 'bilinmiyor')}"
    return "[TUNNEL YOK] 'Tunnel baslat' de."
