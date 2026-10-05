import os
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler

PORT = int(os.environ.get("PORT", "8000"))
WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "webapp")
os.chdir(WEB_DIR)

print(f"BIST Asistani Web Server baslatiliyor - Port: {PORT}")
ThreadingHTTPServer(("0.0.0.0", PORT), SimpleHTTPRequestHandler).serve_forever()
