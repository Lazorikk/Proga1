"""КП-Мастер: local single-user HTTP app and SQLite storage."""
from contextlib import contextmanager
from datetime import date
import html
import json
import os
from pathlib import Path
import re
import sqlite3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from calculations import number
from quote_engine import prepare_quote

ROOT = Path(__file__).resolve().parent
DB = ROOT / 'kp.sqlite3'
STATUSES = ('Черновик', 'Сформировано', 'Отправлено', 'Согласовано', 'Отказ', 'Архив')


@contextmanager
def connect():
    db = sqlite3.connect(DB, timeout=15)
    db.row_factory = sqlite3.Row
    try:
        with db:
            yield db
    finally:
        db.close()


def init():
    with connect() as db:
        db.executescript('''
        CREATE TABLE IF NOT EXISTS organizations(id INTEGER PRIMARY KEY, name TEXT NOT NULL,
          details TEXT NOT NULL, vat REAL NOT NULL, deduct INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS quotes(id INTEGER PRIMARY KEY, created TEXT NOT NULL,
          buyer TEXT NOT NULL, payload TEXT NOT NULL, total TEXT NOT NULL);
        ''')
        old_columns = [r['name'] for r in db.execute('PRAGMA table_info(organizations)')]
        backup = DB.with_name(DB.stem + '.before-v3.sqlite3')
        if 'profile' not in old_columns and db.execute('SELECT 1 FROM organizations').fetchone() and not backup.exists():
            target = sqlite3.connect(backup)
            try:
                db.backup(target)
            finally:
                target.close()
        for table, column, definition in [
            ('organizations', 'terms', "TEXT NOT NULL DEFAULT 'Оплата: 100% предоплата.'"),
            ('organizations', 'markup', 'REAL NOT NULL DEFAULT 20'),
            ('organizations', 'profile', "TEXT NOT NULL DEFAULT '{}'"),
            ('quotes', 'status', "TEXT NOT NULL DEFAULT 'Черновик'"),
            ('quotes', 'revision', 'INTEGER NOT NULL DEFAULT 1')]:
            if column not in [r['name'] for r in db.execute(f'PRAGMA table_info({table})')]:
                db.execute(f'ALTER TABLE {table} ADD COLUMN {column} {definition}')
        if not db.execute('SELECT 1 FROM organizations').fetchone():
            db.execute('INSERT INTO organizations(name,details,vat,deduct) VALUES(?,?,?,?)',
                       ('Моя организация', 'Заполните реквизиты в разделе «Фирмы и бланки».', 22, 1))


def organization_dict(row):
    result = dict(row)
    result['profile'] = json.loads(result.get('profile') or '{}')
    return result


def save_organization(db, data):
    name, details = str(data.get('name', '')).strip(), str(data.get('details', '')).strip()
    if not name or len(name) > 200 or len(details) > 3000:
        raise ValueError('Укажите название (до 200 символов) и реквизиты (до 3000 символов)')
    vat = float(number(data.get('vat', 0), 'НДС продажи', maximum=100))
    markup = float(number(data.get('markup', 20), 'Наценка', maximum=10000))
    existing = None
    if data.get('id'):
        existing = db.execute('SELECT * FROM organizations WHERE id=?', (data['id'],)).fetchone()
        if not existing:
            raise ValueError('Организация не найдена')
    profile = json.loads(existing['profile']) if existing else {}
    updates = data.get('profile', {})
    if not isinstance(updates, dict):
        raise ValueError('Некорректные настройки организации')
    from documents import validate_asset
    for key in ('logo', 'letterhead'):
        if key in updates:
            profile[key] = validate_asset(updates[key], pdf=key == 'letterhead')
    for key in ('tax_regime', 'manager', 'lead_time'):
        if key in updates:
            profile[key] = str(updates[key])[:1000]
    for key, default, low, high in [('top_mm', 65, 15, 140), ('bottom_mm',20,15,70),('valid_days',5,1,365)]:
        profile[key] = float(number(updates.get(key, profile.get(key, default)), key, minimum=low, maximum=high))
    color = str(updates.get('color', profile.get('color', '#255b68')))
    if not re.fullmatch(r'#[0-9a-fA-F]{6}', color):
        raise ValueError('Некорректный цвет бланка')
    profile['color'] = color
    if 'tax_confirmed' in updates:
        profile['tax_confirmed'] = bool(updates['tax_confirmed'])
    values = (name, details, vat, bool(data.get('deduct')), str(data.get('terms', ''))[:6000], markup,
              json.dumps(profile, ensure_ascii=False))
    if existing:
        db.execute('UPDATE organizations SET name=?,details=?,vat=?,deduct=?,terms=?,markup=?,profile=? WHERE id=?',
                   values + (data['id'],))
        return dict(id=data['id'])
    cursor = db.execute('INSERT INTO organizations(name,details,vat,deduct,terms,markup,profile) VALUES(?,?,?,?,?,?,?)', values)
    return dict(id=cursor.lastrowid)


def process_post(db, path, data):
    if not isinstance(data, dict):
        raise ValueError('Нужен объект данных')
    if path == '/api/organizations':
        return save_organization(db, data)
    if path == '/api/status':
        if data.get('status') not in STATUSES:
            raise ValueError('Неизвестный статус')
        result = db.execute('UPDATE quotes SET status=? WHERE id=?', (data['status'], data.get('id')))
        if not result.rowcount:
            raise ValueError('КП не найдено')
        return {}
    if path not in ('/api/calculate', '/api/quotes', '/api/scenarios'):
        raise ValueError('Неизвестная операция')
    row = db.execute('SELECT * FROM organizations WHERE id=?', (data.get('organization'),)).fetchone()
    if not row:
        raise ValueError('Выберите организацию')
    organization = organization_dict(row)
    old = None
    if data.get('id'):
        old = db.execute('SELECT * FROM quotes WHERE id=?', (data['id'],)).fetchone()
        if not old:
            raise ValueError('КП не найдено')
        snapshot = json.loads(old['payload'])['organization']
        if snapshot['id'] == organization['id']:
            organization = snapshot
    if path == '/api/scenarios':
        from calculations import calculate
        scenarios = data.get('scenarios', [])
        if not isinstance(scenarios, list) or not 1 <= len(scenarios) <= 20:
            raise ValueError('Добавьте от 1 до 20 сценариев')
        results = []
        for scenario in scenarios:
            org_row = db.execute('SELECT * FROM organizations WHERE id=?', (scenario.get('organization'),)).fetchone()
            if not org_row:
                raise ValueError('Фирма сценария не найдена')
            org = organization_dict(org_row)
            result = calculate(1, data.get('purchase', 0), data.get('target',20),
                scenario.get('purchase_vat',0), org['vat'], org['deduct'],
                delivery=data.get('delivery',0), delivery_vat=data.get('delivery_vat',0),
                purchase_includes_vat=data.get('purchase_includes_vat',True),
                mode=data.get('mode','price'), sale_price=data.get('sale_price',0))
            results.append(dict(organization=org, purchase_vat=scenario.get('purchase_vat',0), result=result))
        return dict(scenarios=results)
    payload = prepare_quote(data, organization)
    if path == '/api/calculate':
        return payload
    if old:
        if data.get('revision') is not None and int(data['revision']) != old['revision']:
            raise ValueError('КП уже изменено в другой вкладке. Откройте его заново или сохраните копию.')
        revision = old['revision'] + 1
        db.execute('UPDATE quotes SET buyer=?,payload=?,total=?,revision=? WHERE id=?',
            (payload['buyer'], json.dumps(payload,ensure_ascii=False),payload['total'],revision,old['id']))
        return dict(id=old['id'], revision=revision)
    cursor = db.execute('INSERT INTO quotes(created,buyer,payload,total) VALUES(?,?,?,?)',
        (date.today().isoformat(),payload['buyer'],json.dumps(payload,ensure_ascii=False),payload['total']))
    return dict(id=cursor.lastrowid, revision=1)


class Handler(BaseHTTPRequestHandler):
    def send(self, body, status=200, mime='application/json; charset=utf-8', filename=None):
        data = body if isinstance(body, bytes) else body.encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        if filename:
            self.send_header('Content-Disposition', f'attachment; filename="{filename}"')
        self.end_headers()
        self.wfile.write(data)

    def json(self, value, status=200):
        return self.send(json.dumps(value, ensure_ascii=False), status)

    def do_GET(self):
        path = urlparse(self.path).path
        static = {'/':('index.html','text/html'),'/app.js':('app.js','application/javascript'),'/style.css':('style.css','text/css')}
        if path in static:
            file, mime = static[path]
            return self.send((ROOT / 'templates' / file).read_text(encoding='utf-8'), mime=mime+'; charset=utf-8')
        try:
            with connect() as db:
                if path == '/api/data':
                    organizations = [organization_dict(r) for r in db.execute('SELECT * FROM organizations')]
                    quotes = []
                    for row in db.execute('SELECT id,created,buyer,total,status,revision,payload FROM quotes ORDER BY id DESC'):
                        quote = dict(row)
                        p = json.loads(quote.pop('payload'))
                        quote['organization_name'] = p['organization']['name']
                        quote['profit'] = p.get('profit')
                        quote['items_count'] = len(p['items'])
                        quotes.append(quote)
                    return self.json(dict(organizations=organizations,quotes=quotes,statuses=STATUSES))
                if path == '/api/backup':
                    import tempfile
                    with tempfile.TemporaryDirectory() as folder:
                        target = Path(folder) / 'backup.sqlite3'
                        dest = sqlite3.connect(target)
                        try:
                            db.backup(dest)
                        finally:
                            dest.close()
                        content = target.read_bytes()
                    return self.send(content,mime='application/octet-stream',filename='kp-backup.sqlite3')
                if any(path.startswith(prefix) for prefix in ('/api/quotes/','/print/','/pdf/')):
                    try:
                        row = db.execute('SELECT * FROM quotes WHERE id=?',(int(path.split('/')[-1]),)).fetchone()
                    except ValueError:
                        row = None
                    if row:
                        if path.startswith('/api/'):
                            return self.json(dict(row))
                        if path.startswith('/pdf/'):
                            from documents import build_pdf
                            return self.send(build_pdf(row),mime='application/pdf',filename=None if 'inline=1' in urlparse(self.path).query else f'KP-{row["id"]:04d}.pdf')
                        return self.send(print_quote(row),mime='text/html; charset=utf-8')
            return self.json({'error':'Не найдено'},404)
        except ImportError:
            return self.json({'error':'Для PDF установите зависимости: python -m pip install -r requirements.txt'},503)
        except (ValueError, ArithmeticError, KeyError) as exc:
            return self.json({'error':str(exc)},400)

    def do_POST(self):
        try:
            # Browser forms and unrelated websites cannot submit local app changes.
            if self.headers.get('Content-Type','').split(';')[0] != 'application/json':
                raise ValueError('Требуется application/json')
            origin = self.headers.get('Origin')
            if origin and urlparse(origin).netloc != self.headers.get('Host'):
                return self.json({'error':'Запрос из другого сайта запрещён'},403)
            length = int(self.headers.get('Content-Length',0))
            if not 0 < length <= 16_000_000:
                raise ValueError('Слишком большой или пустой запрос')
            data = json.loads(self.rfile.read(length))
            with connect() as db:
                result = process_post(db,self.path,data)
            return self.json(result)
        except ImportError:
            return self.json({'error':'Установите зависимости: python -m pip install -r requirements.txt'},503)
        except (ValueError,KeyError,TypeError,ArithmeticError) as exc:
            return self.json({'error':str(exc)},400)
        except sqlite3.Error:
            return self.json({'error':'Не удалось записать базу. Проверьте доступ к папке и свободное место.'},500)


def print_quote(row):
    """Browser preview embeds exactly the PDF which is downloaded, with no internal data."""
    e = html.escape
    # Keep an accessible text summary for browsers without a PDF viewer.
    p = json.loads(row['payload'])
    summary = '<br>'.join(e(str(x['name']))+' · '+e(str(x.get('unit','шт'))) for x in p['items'])
    return f'''<!doctype html><html lang="ru"><meta charset="utf-8"><title>КП-{row['id']:04d}</title>
    <style>body{{font:14px system-ui;background:#eef2f7;margin:0}}header{{padding:16px;background:white;display:flex;gap:20px;align-items:center}}a{{color:#2563eb}}iframe{{width:100%;height:88vh;border:0}}details{{padding:16px}}</style>
    <header><b>КП-{row['id']:04d}</b><a href="/pdf/{row['id']}">Скачать PDF</a><span>{e(p.get('buyer',''))} · {e(p['total'])} ₽</span></header>
    <iframe title="Предпросмотр PDF" src="/pdf/{row['id']}?inline=1"></iframe><details><summary>Состав предложения</summary>{summary}<p>{e(p.get('manager',''))}</p></details></html>'''


if __name__ == '__main__':
    init()
    port = int(os.environ.get('PORT','8000'))
    try:
        server = ThreadingHTTPServer(('127.0.0.1',port),Handler)
    except OSError as exc:
        raise SystemExit(f'Не удалось запустить порт {port}. Возможно, программа уже открыта. {exc}') from None
    print(f'КП-Мастер: http://127.0.0.1:{port}',flush=True)
    import sys
    if '--open' in sys.argv:
        import threading
        import webbrowser
        threading.Timer(.7,lambda:webbrowser.open(f'http://127.0.0.1:{port}')).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
