"""Servidor estático con cabeceras no-cache para desarrollo."""
from http.server import HTTPServer, SimpleHTTPRequestHandler
import os

class NoCacheHandler(SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        super().end_headers()

    def log_message(self, format, *args):
        pass  # silenciar logs repetitivos

if __name__ == "__main__":
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    server = HTTPServer(("", 3030), NoCacheHandler)
    print("[WEB] Corriendo en http://localhost:3030 (sin caché)")
    server.serve_forever()
