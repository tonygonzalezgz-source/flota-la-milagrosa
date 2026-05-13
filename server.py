"""Servidor estático con live-reload para desarrollo."""
from http.server import HTTPServer, SimpleHTTPRequestHandler
import os, time, threading, glob

_watched_mtimes = {}
_reload_event   = threading.Event()

LIVERELOAD_SCRIPT = (
    b'<script>'
    b'(function(){'
    b'var es=new EventSource("/__livereload");'
    b'es.onmessage=function(){location.reload();};'
    b'es.onerror=function(){setTimeout(function(){location.reload();},1500);};'
    b'})();'
    b'</script>'
)

def _watch_loop():
    base = os.path.dirname(os.path.abspath(__file__))
    while True:
        changed = False
        for pat in ('*.html', '*.css', '*.js', 'api/*.py'):
            for f in glob.glob(os.path.join(base, pat)):
                try:
                    mt = os.stat(f).st_mtime
                except OSError:
                    continue
                if _watched_mtimes.get(f) != mt:
                    if f in _watched_mtimes:
                        changed = True
                        print(f'[RELOAD] {os.path.basename(f)}')
                    _watched_mtimes[f] = mt
        if changed:
            _reload_event.set()
        time.sleep(0.5)


class DevHandler(SimpleHTTPRequestHandler):

    def end_headers(self):
        self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
        self.send_header('Pragma',  'no-cache')
        self.send_header('Expires', '0')
        super().end_headers()

    def do_GET(self):
        if self.path.split('?')[0] == '/__livereload':
            self._sse_handler()
            return

        # Inject livereload script into HTML responses
        path = self.translate_path(self.path)
        if os.path.isfile(path) and path.endswith('.html'):
            self._serve_html(path)
            return

        super().do_GET()

    def _sse_handler(self):
        self.send_response(200)
        self.send_header('Content-Type',  'text/event-stream')
        self.send_header('Cache-Control', 'no-cache')
        self.send_header('Connection',    'keep-alive')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        try:
            while True:
                fired = _reload_event.wait(timeout=25)
                if fired:
                    self.wfile.write(b'data: reload\n\n')
                    self.wfile.flush()
                    _reload_event.clear()
                else:
                    self.wfile.write(b': ping\n\n')
                    self.wfile.flush()
        except Exception:
            pass

    def _serve_html(self, path):
        try:
            with open(path, 'rb') as f:
                content = f.read()
        except OSError:
            super().do_GET()
            return

        content = content.replace(b'</body>', LIVERELOAD_SCRIPT + b'</body>')

        self.send_response(200)
        self.send_header('Content-Type',   'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def log_message(self, format, *args):
        pass


if __name__ == '__main__':
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    t = threading.Thread(target=_watch_loop, daemon=True)
    t.start()
    server = HTTPServer(('', 3030), DevHandler)
    print('[WEB] http://localhost:3030  (live-reload activo ⚡)')
    server.serve_forever()
