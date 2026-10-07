import json
import os
import re
import secrets
from functools import partial
from http.cookies import SimpleCookie, CookieError
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlsplit, parse_qs, unquote

from kullanici_kayitlari import UserRecords, RecordError, symbol
from push_bildirim_motoru import public_config, subscription_save, subscription_disable
from veri_yollari import paths, PRIVATE_NAMES, RUNTIME_LEGACY

ROOT = Path(__file__).resolve().parent
PORT = int(os.environ.get('PORT', '8000'))
WEB_DIR = ROOT / 'webapp'
# Private files are outside the static document root. Use a retained writable volume
# through BIST_USER_DATA_DIR when deploying to an ephemeral hosting service.
USER_DATA_DIR = paths().users


class BistHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, records=None, data_paths=None, **kwargs):
        self.data_paths = data_paths or paths()
        self.records = records or UserRecords(self.data_paths.users, WEB_DIR, public_dir=self.data_paths.public)
        self.new_cookie = None
        super().__init__(*args, **kwargs)

    def translate_path(self, path):
        route = unquote(urlsplit(path).path)
        missing = str(self.data_paths.web / '.not-served')
        if any(p in ('.','..') for p in route.split('/')):
            return missing
        if route == '/data' or route.startswith('/data/'):
            parts = route.removeprefix('/data/').split('/')
            if any(p in ('', '.', '..') or p.startswith('.') for p in parts):
                return missing
            if len(parts) == 2 and parts[0] == 'yarin_top10_arsiv' and re.fullmatch(r'\d{4}-\d{2}-\d{2}\.json',parts[1]):
                root = self.data_paths.archives
                target = root / parts[1]
            elif len(parts) == 1 and parts[0].endswith('.json') and parts[0] not in PRIVATE_NAMES | set(RUNTIME_LEGACY):
                root = self.data_paths.public
                target = root / parts[0]
            else:
                return missing
            resolved = target.resolve()
            return str(resolved) if resolved.is_relative_to(root.resolve()) and resolved.is_file() else missing
        target = Path(super().translate_path(path)).resolve()
        # Never serve private volume contents through traversal or static symlinks.
        return str(target) if target.is_relative_to(self.data_paths.web.resolve()) and not target.is_relative_to(self.data_paths.web/'data') else missing

    def end_headers(self):
        route = urlsplit(self.path).path
        if route.startswith('/data/') or route in ('/', '/index.html', '/service-worker.js', '/manifest.webmanifest'):
            self.send_header('Cache-Control', 'no-store')
        if route == '/service-worker.js':
            self.send_header('Service-Worker-Allowed', '/')
        super().end_headers()

    def list_directory(self, path):
        self.send_error(404, 'Directory listing disabled')
        return None

    def session(self):
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get('Cookie', ''))
        except CookieError:
            pass
        token = cookie.get('bist_user')
        value = token.value if token else ''
        if not re.fullmatch(r'[a-f0-9]{64}', value):
            value = secrets.token_hex(32)
            self.new_cookie = value
        return value

    def respond(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False, allow_nan=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        if self.new_cookie:
            secure = '; Secure' if self.headers.get('X-Forwarded-Proto') == 'https' else ''
            self.send_header('Set-Cookie', f'bist_user={self.new_cookie}; HttpOnly; SameSite=Strict; Path=/; Max-Age=31536000{secure}')
        self.end_headers()
        self.wfile.write(body)
        self.new_cookie = None

    def body(self):
        if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
            raise RecordError('JSON isteği gerekiyor.', 415)
        try:
            size = int(self.headers.get('Content-Length', '0'))
        except ValueError:
            raise RecordError('Geçersiz istek uzunluğu.') from None
        if not 0 < size <= 16384:
            raise RecordError('İstek boyutu geçersiz.', 413)
        try:
            value = json.loads(self.rfile.read(size))
        except (ValueError, UnicodeError):
            raise RecordError('Geçersiz JSON.') from None
        if not isinstance(value, dict):
            raise RecordError('JSON nesnesi gerekiyor.')
        return value

    def api(self):
        try:
            # Same-origin JSON requests only; no CORS or cross-site form writes.
            if self.command != 'GET':
                origin = self.headers.get('Origin')
                if (self.headers.get('X-Bist-Request') != '1'
                        or (origin and urlsplit(origin).netloc != self.headers.get('Host'))):
                    raise RecordError('Aynı uygulamadan yapılan istek gerekiyor.', 403)
            url = urlsplit(self.path)
            if url.path == '/api/intraday-signals' and self.command == 'GET':
                from gunluk_al_sat import api_report
                self.respond(api_report(parse_qs(url.query,keep_blank_values=True),self.data_paths))
                return
            if url.path == '/api/top10-learning-performance' and self.command == 'GET':
                from top10_ogrenme_performansi import api_report
                self.respond(api_report(parse_qs(url.query,keep_blank_values=True),self.data_paths))
                return
            if url.path == '/api/indicator-performance' and self.command == 'GET':
                from sinyal_performansi import indicator_report
                self.respond(indicator_report(parse_qs(url.query,keep_blank_values=True),self.data_paths))
                return
            if url.path == '/api/signal-performance' and self.command == 'GET':
                from sinyal_performansi import read_report
                self.respond(read_report(self.data_paths))
                return
            if url.path == '/api/market-context' and self.command == 'GET':
                from piyasa_baglami import PiyasaBaglami
                self.respond(PiyasaBaglami(self.data_paths).context() or {
                    'piyasa_rejimi':'BELIRSIZ','rejim_confidence':0,'stale':True,'updated_at':None})
                return
            user = self.session()
            if url.path == '/api/push/config' and self.command == 'GET':
                self.respond(public_config())
                return
            if url.path == '/api/push/subscriptions' and self.command == 'POST':
                self.respond(subscription_save(self.records, user, self.body()), 201)
                return
            push_match = re.fullmatch(r'/api/push/subscriptions/([a-f0-9]{64})', url.path)
            if push_match and self.command == 'DELETE':
                self.respond(subscription_disable(self.records, user, push_match[1]))
                return
            stock_match = re.fullmatch(r'/api/stocks/([A-Za-z0-9]+)(?:/(levels|alarms))?', url.path)
            if stock_match:
                stock, action = symbol(stock_match[1]), stock_match[2]
                if self.command == 'GET' and action is None:
                    model = parse_qs(url.query).get('model', ['GUNLUK'])[0]
                    from ai_karar_motoru import ai_ozet_oku
                    automatic=self.records.automatic(stock,model)
                    summary=ai_ozet_oku(stock,self.data_paths)
                    from ai_karar_motoru import decision_view,ISTANBUL,stamp
                    from datetime import datetime
                    final=automatic.get('nihai_karar') or {}
                    shared=(summary or {}).get('nihai_karar') or {}
                    target='INTRADAY' if model=='GUN_ICI' else 'DAILY'
                    current=datetime.now(ISTANBUL)
                    newer=stamp(shared.get('updated_at'));previous=stamp(final.get('updated_at'))
                    if previous and previous>current:previous=None
                    if shared.get('zaman_dilimi')==target and newer and newer<=current and (not previous or newer>=previous):
                        final=decision_view(shared,current)
                    from gunluk_al_sat import stock_signal,enabled as intraday_engine_enabled
                    intraday_extra={'intraday_signal':stock_signal(stock,self.data_paths)} if intraday_engine_enabled() else {}
                    self.respond({'manuel': self.records.levels(user, stock),**intraday_extra,
                                  'otomatik': automatic,
                                  'ai_ozet': summary,'nihai_karar':final,
                                  'alarmlar': self.records.alarms(user, stock)})
                    return
                if self.command == 'PUT' and action == 'levels':
                    self.respond(self.records.save_levels(user, stock, self.body()))
                    return
                if self.command == 'POST' and action == 'alarms':
                    record, created = self.records.create_alarm(user, stock, self.body())
                    self.respond({'alarm': record, 'created': created}, 201 if created else 200)
                    return
            alarm_match = re.fullmatch(r'/api/alarms/([a-f0-9]{32})', url.path)
            if alarm_match and self.command in ('DELETE', 'PATCH'):
                if self.command == 'PATCH' and self.body() != {'aktif': False}:
                    raise RecordError('Yalnızca pasifleştirme destekleniyor.')
                self.respond(self.records.change_alarm(user, alarm_match[1], delete=self.command == 'DELETE'))
                return
            raise RecordError('İşlem bulunamadı.', 404)
        except RecordError as error:
            self.respond({'error': str(error)}, error.status)
        except OSError:
            self.respond({'error': 'Kayıt işlemi tamamlanamadı; tekrar deneyin.'}, 503)

    def do_GET(self):
        if urlsplit(self.path).path == '/health':
            from ana_motor import health_snapshot
            self.respond({'web': 'OK', 'ana_motor': health_snapshot(self.data_paths.runtime)})
        elif urlsplit(self.path).path.startswith('/api/'):
            self.api()
        else:
            super().do_GET()

    def do_PUT(self):
        self.api()

    def do_POST(self):
        self.api()

    def do_PATCH(self):
        self.api()

    def do_DELETE(self):
        self.api()


def create_server(host='0.0.0.0', port=PORT, records=None, data_paths=None):
    location = data_paths or paths()
    if records is None:
        location.ensure()
    return ThreadingHTTPServer((host, port), partial(BistHandler, directory=str(location.web), records=records, data_paths=location))


if __name__ == '__main__':
    print(f'BIST Asistani Web Server baslatiliyor - Port: {PORT}', flush=True)
    import signal
    import threading
    server = create_server()
    def stop_server(*_):
        threading.Thread(target=server.shutdown, daemon=True).start()
    signal.signal(signal.SIGTERM, stop_server)
    signal.signal(signal.SIGINT, stop_server)
    try:
        server.serve_forever()
    finally:
        server.server_close()
