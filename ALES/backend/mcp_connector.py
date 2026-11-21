"""
mcp_connector.py — Model Context Protocol (MCP) İstemcisi & Yerleşik Sunucusu.

NE YAPAR:
  Anthropic Model Context Protocol (MCP) JSON-RPC 2.0 standardını destekler.
  1) Harici stdio tabanlı MCP sunucularına (ör. @modelcontextprotocol/server-filesystem)
     bağlanır ve araçları dinamik olarak keşfeder/çağırır.
  2) Sistemde harici MCP sunucusu (node/npx) yoksa, tam MCP JSON-RPC protokolünü
     yerel olarak işleten YERLEŞİK (EMBEDDED) bir MCP Filesystem sunucusu sunar.
     Böylece dosya listeleme, okuma, yazma işlemleri standart MCP protokolüyle çalışır.
"""

import asyncio
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

# İstatistikler
_stats = {
    "initialized": False,
    "active_server": "embedded",
    "calls_total": 0,
    "calls_success": 0,
    "last_error": None,
}

_lock = threading.Lock()


class EmbeddedMCPServer:
    """
    Standart JSON-RPC 2.0 protokolüne tam uyumlu yerleşik MCP Filesystem sunucusu.
    Harici Node.js veya npx bağımlılığı olmadan ALES içerisinde MCP yetenekleri sunar.
    """

    TOOLS = [
        {
            "name": "list_directory",
            "description": "Belirtilen dizindeki dosya ve klasörleri listeler.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Listelenecek dizin yolu"}
                },
                "required": ["path"]
            }
        },
        {
            "name": "read_file",
            "description": "Belirtilen dosyanın metin içeriğini okur.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Okunacak dosya yolu"}
                },
                "required": ["path"]
            }
        },
        {
            "name": "write_file",
            "description": "Belirtilen dosyaya içerik yazar.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Yazılacak dosya yolu"},
                    "content": {"type": "string", "description": "Yazılacak metin"}
                },
                "required": ["path", "content"]
            }
        },
        {
            "name": "get_file_info",
            "description": "Dosya veya dizin hakkında boyut ve zaman damgası bilgisi döner.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Hedef dosya veya dizin yolu"}
                },
                "required": ["path"]
            }
        }
    ]

    def handle_request(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """JSON-RPC 2.0 isteğini ayrıştırır ve standart yanıt üretir."""
        req_id = request.get("id")
        method = request.get("method")
        params = request.get("params", {})

        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "serverInfo": {
                        "name": "ales-embedded-mcp-filesystem",
                        "version": "1.0.0"
                    },
                    "capabilities": {
                        "tools": {"listChanged": False},
                        "resources": {"subscribe": False}
                    }
                }
            }

        elif method == "tools/list":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "tools": self.TOOLS
                }
            }

        elif method == "tools/call":
            tool_name = params.get("name")
            args = params.get("arguments", {})
            try:
                res_content = self._execute_tool(tool_name, args)
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [
                            {"type": "text", "text": res_content}
                        ],
                        "isError": False
                    }
                }
            except Exception as e:
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [
                            {"type": "text", "text": f"Hata: {str(e)}"}
                        ],
                        "isError": True
                    }
                }

        elif method == "ping":
            return {"jsonrpc": "2.0", "id": req_id, "result": {}}

        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": -32601, "message": f"Method not found: {method}"}
        }

    def _execute_tool(self, name: str, args: Dict[str, Any]) -> str:
        if name == "list_directory":
            p = Path(args.get("path", ".")).resolve()
            if not p.exists():
                return f"Hata: Dizin bulunamadı: {p}"
            if not p.is_dir():
                return f"Hata: Belirtilen yol bir dizin değil: {p}"
            items = []
            for item in sorted(p.iterdir()):
                kind = "📁 [DIR] " if item.is_dir() else "📄 [FILE]"
                size_str = f" ({item.stat().st_size} bytes)" if item.is_file() else ""
                items.append(f"{kind} {item.name}{size_str}")
            return f"Dizin: {p}\n" + ("\n".join(items) if items else "(boş dizin)")

        elif name == "read_file":
            p = Path(args.get("path", "")).resolve()
            if not p.exists():
                return f"Hata: Dosya bulunamadı: {p}"
            if not p.is_file():
                return f"Hata: Belirtilen yol bir dosya değil: {p}"
            try:
                return p.read_text(encoding="utf-8", errors="replace")
            except Exception as e:
                return f"Hata: Dosya okunamadı: {e}"

        elif name == "write_file":
            p = Path(args.get("path", "")).resolve()
            content = args.get("content", "")
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
            return f"✅ Dosya başarıyla kaydedildi: {p} ({len(content)} karakter)"

        elif name == "get_file_info":
            p = Path(args.get("path", "")).resolve()
            if not p.exists():
                return f"Hata: Yol bulunamadı: {p}"
            stat = p.stat()
            info = {
                "path": str(p),
                "is_dir": p.is_dir(),
                "is_file": p.is_file(),
                "size_bytes": stat.st_size,
                "modified": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(stat.st_mtime))
            }
            return json.dumps(info, ensure_ascii=False, indent=2)

        raise ValueError(f"Bilinmeyen araç: {name}")


class StdioMCPClient:
    """
    Harici bir MCP sunucusuyla standart I/O (stdio) üzerinden konuşan istemci.
    JSON-RPC 2.0 newline-delimited JSON mesajlarını aktarır.
    """

    def __init__(self, command: List[str]):
        self.command = command
        self.process: Optional[subprocess.Popen] = None
        self._msg_id = 0
        self._pending_lock = threading.Lock()
        self._is_alive = False

    def start(self) -> bool:
        try:
            self.process = subprocess.Popen(
                self.command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                encoding="utf-8"
            )
            self._is_alive = True
            # initialize handshake
            res = self.send_request("initialize", {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "ALES", "version": "2.0"}
            }, timeout=5.0)
            return res is not None
        except Exception as e:
            print(f"[MCP] Harici sunucu başlatılamadı ({self.command}): {e}")
            self._is_alive = False
            return False

    def send_request(self, method: str, params: Dict[str, Any], timeout: float = 8.0) -> Optional[Dict[str, Any]]:
        if not self._is_alive or not self.process:
            return None
        with self._pending_lock:
            self._msg_id += 1
            current_id = self._msg_id

        payload = {
            "jsonrpc": "2.0",
            "id": current_id,
            "method": method,
            "params": params
        }

        try:
            line = json.dumps(payload) + "\n"
            self.process.stdin.write(line)
            self.process.stdin.flush()

            # Cevap bekle
            start = time.time()
            while time.time() - start < timeout:
                if self.process.stdout.readable():
                    resp_line = self.process.stdout.readline()
                    if resp_line:
                        try:
                            data = json.loads(resp_line.strip())
                            if data.get("id") == current_id:
                                return data
                        except json.JSONDecodeError:
                            continue
                time.sleep(0.05)
            return None
        except Exception as e:
            print(f"[MCP] İstek iletim hatası: {e}")
            self._is_alive = False
            return None

    def close(self):
        self._is_alive = False
        if self.process:
            try:
                self.process.terminate()
            except Exception:
                pass


# Modül Tekili (Singleton)
_embedded_server = EmbeddedMCPServer()
_external_client: Optional[StdioMCPClient] = None


def get_mcp_client() -> Optional[StdioMCPClient]:
    """Varsa aktif harici MCP istemcisini, yoksa None döner."""
    global _external_client
    return _external_client


def list_mcp_tools() -> List[Dict[str, Any]]:
    """Kullanılabilir tüm MCP araçlarını döndürür."""
    global _stats
    _stats["calls_total"] += 1
    client = get_mcp_client()
    if client and client._is_alive:
        resp = client.send_request("tools/list", {})
        if resp and "result" in resp:
            _stats["calls_success"] += 1
            return resp["result"].get("tools", [])

    # Yerleşik sunucu fallback
    resp = _embedded_server.handle_request({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/list",
        "params": {}
    })
    _stats["calls_success"] += 1
    return resp["result"].get("tools", [])


def call_mcp_tool(tool_name: str, arguments: Dict[str, Any]) -> str:
    """
    Belirtilen aracı MCP protokolü üzerinden çalıştırır.
    Öncelikle harici sunucuyu dener, erişilemezse yerleşik sunucuyu kullanır.
    """
    global _stats
    _stats["calls_total"] += 1
    client = get_mcp_client()
    if client and client._is_alive:
        resp = client.send_request("tools/call", {
            "name": tool_name,
            "arguments": arguments
        })
        if resp and "result" in resp:
            content = resp["result"].get("content", [])
            _stats["calls_success"] += 1
            return "".join(c.get("text", "") for c in content)

    # Yerleşik sunucu fallback
    req = {
        "jsonrpc": "2.0",
        "id": int(time.time() * 1000) % 100000,
        "method": "tools/call",
        "params": {
            "name": tool_name,
            "arguments": arguments
        }
    }
    resp = _embedded_server.handle_request(req)
    if "result" in resp:
        content = resp["result"].get("content", [])
        _stats["calls_success"] += 1
        return "".join(c.get("text", "") for c in content)
    elif "error" in resp:
        err = resp["error"].get("message", "Bilinmeyen hata")
        _stats["last_error"] = err
        return f"❌ MCP Hatası: {err}"
    return "❌ MCP: Yanıt alınamadı."


def mcp_read_file(path: str) -> str:
    """Standart MCP araç çağrısı ile dosya okur."""
    return call_mcp_tool("read_file", {"path": path})


def mcp_list_directory(path: str = ".") -> str:
    """Standart MCP araç çağrısı ile dizin listeler."""
    return call_mcp_tool("list_directory", {"path": path})


def mcp_write_file(path: str, content: str) -> str:
    """Standart MCP araç çağrısı ile dosya yazar."""
    return call_mcp_tool("write_file", {"path": path, "content": content})


def get_mcp_status() -> Dict[str, Any]:
    """MCP modülü sağlık ve çalışma durumu."""
    return {
        "ok": True,
        "active_mode": "external" if (_external_client and _external_client._is_alive) else "embedded",
        "protocol": "JSON-RPC 2.0 (MCP 2024-11-05)",
        "available_tools": [t["name"] for t in _embedded_server.TOOLS],
        "stats": _stats
    }
