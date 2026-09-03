import json
import os
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from services import SanctionsChatOrchestrator, build_sanction_result_from_local_payload, lookup_local_query


HOST = os.environ.get("HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", "8765"))
STATIC_DIR = Path(__file__).parent / "static"
CHAT_ORCHESTRATOR = SanctionsChatOrchestrator()


class SanctionsRequestHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC_DIR), **kwargs)

    def do_GET(self) -> None:
        parsed_url = urlparse(self.path)
        if parsed_url.path == "/api/local-lookup":
            self.handle_local_lookup(parsed_url.query)
            return

        if parsed_url.path == "/":
            self.path = "/index.html"

        super().do_GET()

    def do_POST(self) -> None:
        parsed_url = urlparse(self.path)
        if parsed_url.path == "/api/chat":
            self.handle_chat()
            return

        self.send_json({"error": "Not found."}, status=404)

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_cors_headers()
        self.end_headers()

    def handle_local_lookup(self, query_string: str) -> None:
        params = parse_qs(query_string)
        query = (params.get("q") or [""])[0].strip()
        include_neighbors = (params.get("neighbors") or ["false"])[0].lower() == "true"

        if not query:
            self.send_json({"error": "Query is required."}, status=400)
            return

        try:
            payload = lookup_local_query(query, include_neighbors=include_neighbors)
            result = build_sanction_result_from_local_payload(payload)
            self.send_json(
                {
                    "result": result.model_dump(),
                    "raw": payload,
                }
            )
        except Exception as exc:
            self.send_json({"error": str(exc)}, status=500)

    def handle_chat(self) -> None:
        try:
            body_length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(body_length).decode("utf-8")
            payload = json.loads(body) if body else {}
            message = str(payload.get("message") or "")
            session_id = payload.get("session_id")
            response = CHAT_ORCHESTRATOR.handle_message(message, session_id=session_id)
            self.send_json(response)
        except Exception as exc:
            self.send_json({"error": str(exc)}, status=500)

    def send_json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_cors_headers()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_cors_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")


def main() -> None:
    server = ThreadingHTTPServer((HOST, PORT), SanctionsRequestHandler)
    print(f"Sanctions test UI running at http://{HOST}:{PORT}")
    server.serve_forever()


if __name__ == "__main__":
    main()
