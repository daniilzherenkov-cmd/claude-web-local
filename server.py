#!/usr/bin/env python3
"""
Local Claude web proxy — bridges browser to LiteLLM with auth.
Stdlib only, no pip install needed. Works on Python 3.9+.
"""
from __future__ import annotations
import http.server
import http.client
import json
import os
import socketserver
import sys
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path

PORT = int(os.environ.get("CLAUDE_WEB_PORT", "8765"))
HERE = Path(__file__).resolve().parent
CONFIG_FILE = Path.home() / ".claude-web" / "config.json"


def load_config() -> dict:
    cfg: dict = {}
    if CONFIG_FILE.exists():
        try:
            cfg = json.loads(CONFIG_FILE.read_text())
        except json.JSONDecodeError:
            cfg = {}
    if not cfg.get("baseUrl") and os.environ.get("ANTHROPIC_BASE_URL"):
        cfg["baseUrl"] = os.environ["ANTHROPIC_BASE_URL"]
    if not cfg.get("token") and os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        cfg["token"] = os.environ["ANTHROPIC_AUTH_TOKEN"]
    return cfg


def save_config(cfg: dict) -> None:
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2))
    try:
        os.chmod(CONFIG_FILE, 0o600)
    except OSError:
        pass


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(HERE), **kwargs)

    def log_message(self, fmt, *args):
        sys.stderr.write(f"[{self.log_date_time_string()}] {fmt % args}\n")

    def do_GET(self):
        if self.path == "/api/config":
            return self._get_config()
        if self.path == "/api/models":
            return self._proxy_models()
        if self.path == "/" or self.path == "":
            self.path = "/index.html"
        return super().do_GET()

    def do_POST(self):
        if self.path == "/api/config":
            return self._post_config()
        if self.path == "/api/messages":
            return self._proxy_messages()
        return self.send_error(404)

    def _send_json(self, status: int, obj):
        data = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _read_body(self) -> bytes:
        length = int(self.headers.get("Content-Length", "0") or 0)
        return self.rfile.read(length) if length else b""

    def _get_config(self):
        cfg = load_config()
        self._send_json(200, {
            "baseUrl": cfg.get("baseUrl", ""),
            "model": cfg.get("model", "claude-sonnet-4-6"),
            "hasToken": bool(cfg.get("token")),
        })

    def _post_config(self):
        try:
            body = json.loads(self._read_body() or b"{}")
        except json.JSONDecodeError:
            return self._send_json(400, {"error": "invalid JSON"})
        cfg = load_config()
        for k in ("baseUrl", "token", "model"):
            v = body.get(k)
            if isinstance(v, str) and v.strip():
                cfg[k] = v.strip()
        save_config(cfg)
        self._send_json(200, {"ok": True})

    def _upstream(self, method: str, path: str, body: bytes | None = None,
                  extra_headers: dict | None = None):
        cfg = load_config()
        base = cfg.get("baseUrl") or ""
        token = cfg.get("token") or ""
        if not base or not token:
            return None, None, "Not configured. Open Settings and paste your LiteLLM URL + token."
        url = f"{base.rstrip('/')}{path}"
        headers = {
            "Authorization": f"Bearer {token}",
            "anthropic-version": "2023-06-01",
        }
        if extra_headers:
            headers.update(extra_headers)
        req = urllib.request.Request(url, data=body, method=method, headers=headers)
        try:
            resp = urllib.request.urlopen(req, timeout=600)
            return resp, None, None
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", "ignore")
            return None, e.code, err_body
        except Exception as e:
            return None, 502, str(e)

    def _proxy_models(self):
        resp, code, err = self._upstream("GET", "/v1/models")
        if resp is None:
            return self._send_json(code or 400, {"error": err})
        try:
            data = resp.read()
        finally:
            resp.close()
        try:
            parsed = json.loads(data)
        except json.JSONDecodeError:
            parsed = {"data": []}
        models = []
        for m in parsed.get("data", []):
            mid = m.get("id", "")
            if mid.startswith("claude"):
                models.append(mid)
        models.sort(key=_model_sort_key, reverse=True)
        self._send_json(200, {"models": models})

    def _proxy_messages(self):
        body = self._read_body()
        resp, code, err = self._upstream(
            "POST", "/v1/messages", body=body,
            extra_headers={"Content-Type": "application/json"},
        )
        if resp is None:
            return self._send_json(code or 502, {"error": err})

        try:
            self.send_response(resp.status)
            ct = resp.headers.get("Content-Type") or "text/event-stream"
            self.send_header("Content-Type", ct)
            self.send_header("Cache-Control", "no-cache")
            self.send_header("X-Accel-Buffering", "no")
            self.send_header("Connection", "close")
            self.end_headers()
            while True:
                chunk = resp.read(1024)
                if not chunk:
                    break
                try:
                    self.wfile.write(chunk)
                    self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError):
                    break
        finally:
            try:
                resp.close()
            except Exception:
                pass


def _model_sort_key(model_id: str) -> tuple:
    """Sort newer Claude models above older ones, family-grouped."""
    family_order = {"opus": 3, "sonnet": 2, "haiku": 1}
    family = 0
    for k, v in family_order.items():
        if k in model_id:
            family = v
            break
    parts = model_id.split("-")
    nums = []
    for p in parts:
        try:
            nums.append(int(p))
        except ValueError:
            pass
    return (family, tuple(nums))


class ThreadingServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def main():
    url = f"http://localhost:{PORT}/"
    cfg = load_config()
    print(f"\n  Claude web running at {url}")
    if cfg.get("token") and cfg.get("baseUrl"):
        print(f"  Auth ready (baseUrl={cfg['baseUrl']})")
    else:
        print("  Token not configured yet — paste it in the Settings modal that appears.")
    print("  Press Ctrl+C to stop.\n")
    if "--no-open" not in sys.argv:
        try:
            webbrowser.open(url)
        except Exception:
            pass
    try:
        ThreadingServer(("127.0.0.1", PORT), Handler).serve_forever()
    except KeyboardInterrupt:
        print("\n  Bye.")


if __name__ == "__main__":
    main()
