"""
Browser UI for the Fire Risk AI Agent.

Run:
    python web_app.py

Then open:
    http://127.0.0.1:8000
"""

from __future__ import annotations

import json
import mimetypes
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import Fire_Risk_Agent as fire


ROOT = Path(__file__).resolve().parent
WEB_ROOT = ROOT / "web"
HOST = os.environ.get("FIRE_RISK_WEB_HOST", "127.0.0.1")
PORT = int(os.environ.get("FIRE_RISK_WEB_PORT", "8000"))

_agent_lock = threading.Lock()
_agent: fire.FireRiskAgent | fire.ChatGPTFireRiskAgent | None = None


def _json_default(value: Any) -> str:
    return str(value)


def _get_agent() -> fire.FireRiskAgent | fire.ChatGPTFireRiskAgent:
    global _agent
    with _agent_lock:
        if _agent is None:
            provider = os.environ.get("FIRE_RISK_AGENT_PROVIDER", "anthropic").lower()
            if provider in {"openai", "chatgpt"}:
                _agent = fire.ChatGPTFireRiskAgent()
            else:
                _agent = fire.FireRiskAgent()
        return _agent


def _dashboard_payload() -> dict:
    return {
        "zones": fire.tool_get_all_zones_risk(),
        "alerts": fire.tool_get_active_alerts(),
        "forecast": fire.tool_get_weather_forecast(3),
        "recent_fires": fire.tool_get_recent_fires(days=1, limit=12),
        "zone_locations": fire.ZONES,
        "model": {
            "anthropic": fire.ANTHROPIC_MODEL,
            "openai": fire.OPENAI_MODEL,
            "provider": os.environ.get("FIRE_RISK_AGENT_PROVIDER", "anthropic"),
        },
    }


class FireRiskRequestHandler(BaseHTTPRequestHandler):
    server_version = "FireRiskWeb/1.0"

    def log_message(self, format: str, *args: Any) -> None:
        print(f"{self.address_string()} - {format % args}")

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/dashboard":
            self._send_json(_dashboard_payload())
            return
        if parsed.path == "/api/zone":
            query = parse_qs(parsed.query)
            zone_name = query.get("name", [""])[0]
            self._send_json(fire.tool_get_zone_risk(zone_name))
            return
        if parsed.path == "/api/clear":
            agent = _get_agent()
            with _agent_lock:
                agent.conversation_history.clear()
            self._send_json({"ok": True})
            return

        path = parsed.path
        if path == "/":
            path = "/index.html"
        self._send_static(path)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path != "/api/query":
            self._send_json({"error": "Not found"}, status=404)
            return

        try:
            payload = self._read_json()
            question = str(payload.get("question", "")).strip()
            if not question:
                self._send_json({"error": "Question is required"}, status=400)
                return

            agent = _get_agent()
            with _agent_lock:
                answer = agent.query(question)
            self._send_json({"answer": answer})
        except Exception as exc:
            self._send_json(
                {"error": f"{type(exc).__name__}: {exc}"},
                status=500,
            )

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            return {}
        body = self.rfile.read(length).decode("utf-8")
        return json.loads(body)

    def _send_json(self, payload: Any, status: int = 200) -> None:
        data = json.dumps(payload, default=_json_default).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _send_static(self, request_path: str) -> None:
        relative = request_path.lstrip("/")
        file_path = (WEB_ROOT / relative).resolve()
        if WEB_ROOT not in file_path.parents and file_path != WEB_ROOT:
            self._send_json({"error": "Forbidden"}, status=403)
            return
        if not file_path.exists() or not file_path.is_file():
            self._send_json({"error": "Not found"}, status=404)
            return

        content = file_path.read_bytes()
        content_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
        if file_path.suffix == ".js":
            content_type = "application/javascript"
        self.send_response(200)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)


def main() -> None:
    WEB_ROOT.mkdir(exist_ok=True)
    server = ThreadingHTTPServer((HOST, PORT), FireRiskRequestHandler)
    print(f"Fire Risk web UI running at http://{HOST}:{PORT}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping Fire Risk web UI.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
