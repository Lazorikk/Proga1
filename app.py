"""Local single-user prototype. Run: python app.py."""
import html
import json
import os
import sqlite3
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from calculations import calculate

ROOT = Path(__file__).resolve().parent
DB = ROOT / 'kp.sqlite3'


def connect():
    db = sqlite3.connect(DB)
    db.row_factory = sqlite3.Row
    return db


def init():
    with connect() as db:
        db.executescript('''
        CREATE TABLE IF NOT EXISTS organizations(id INTEGER PRIMARY KEY, name TEXT NOT NULL,
          details TEXT NOT NULL, vat REAL NOT NULL, deduct INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS quotes(id INTEGER PRIMARY KEY, created TEXT NOT NULL,
          buyer TEXT NOT NULL, payload TEXT NOT NULL, total TEXT NOT NULL);
        ''')
        if not db.execute('SELECT 1 FROM organizations').fetchone():
            db.execute('INSERT INTO organizations(name,details,vat,deduct) VALUES(?,?,?,?)',
                       ('Демо · Стройкомплект', 'Демонстрационная организация. Замените реквизиты перед отправкой КП.', 22, 1))


class Handler(BaseHTTPRequestHandler):
    def send(self, body, status=200, mime='application/json; charset=utf-8'):
        data = body.encode()
        self.send_response(status)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = urlparse(self.path).path
        with connect() as db:
            if path == '/':
                return self.send((ROOT / 'templates/index.html').read_text(), mime='text/html; charset=utf-8')
            if path == '/api/data':
                return self.send(json.dumps(dict(
                    organizations=[dict(r) for r in db.execute('SELECT * FROM organizations')],
                    quotes=[dict(r) for r in db.execute('SELECT id,created,buyer,total FROM quotes ORDER BY id DESC')]), ensure_ascii=False))
            if path.startswith('/print/'):
                try:
                    row = db.execute('SELECT * FROM quotes WHERE id=?', (int(path.split('/')[-1]),)).fetchone()
                except ValueError:
                    row = None
                if row:
                    return self.send(print_quote(row), mime='text/html; charset=utf-8')
        self.send('Не найдено', 404, 'text/plain; charset=utf-8')

    def do_POST(self):
        try:
            length = int(self.headers.get('Content-Length', 0))
            if length > 1_000_000:
                raise ValueError('Слишком большой запрос')
            data = json.loads(self.rfile.read(length))
            with connect() as db:
                if self.path == '/api/organizations':
                    name = str(data['name']).strip()
                    vat = float(data['vat'])
                    if not name or not 0 <= vat <= 100:
                        raise ValueError('Укажите название и НДС от 0 до 100')
                    db.execute('INSERT INTO organizations(name,details,vat,deduct) VALUES(?,?,?,?)',
                               (name, str(data.get('details', '')), vat, bool(data.get('deduct'))))
                    return self.send('{}')
                if self.path not in ('/api/calculate', '/api/quotes'):
                    return self.send('{}', 404)
                org = db.execute('SELECT * FROM organizations WHERE id=?', (data['organization'],)).fetchone()
                if org is None:
                    raise ValueError('Выберите организацию')
                items = data['items']
                if not items or len(items) > 100:
                    raise ValueError('Добавьте от 1 до 100 товаров')
                from decimal import Decimal
                total = Decimal(0)
                for item in items:
                    if not str(item['name']).strip():
                        raise ValueError('Укажите наименование товара')
                    item['result'] = calculate(item['quantity'], item['purchase'], item['markup'],
                                               item['purchase_vat'], org['vat'], org['deduct'])
                    total += Decimal(item['result']['total'])
                payload = dict(organization=dict(org), items=items, buyer=str(data.get('buyer', '')),
                               terms=str(data.get('terms', '')), total=str(total))
                if self.path == '/api/calculate':
                    return self.send(json.dumps(payload, ensure_ascii=False))
                cursor = db.execute('INSERT INTO quotes(created,buyer,payload,total) VALUES(?,?,?,?)',
                                    (date.today().isoformat(), payload['buyer'], json.dumps(payload, ensure_ascii=False), str(total)))
                self.send(json.dumps(dict(id=cursor.lastrowid)))
        except (ValueError, KeyError, TypeError, ArithmeticError) as exc:
            self.send(json.dumps({'error': str(exc)}, ensure_ascii=False), 400)


def print_quote(row):
    p = json.loads(row['payload'])
    e = lambda value: html.escape(str(value))
    rows = ''.join(f'<tr><td>{i+1}</td><td>{e(x["name"])}</td><td>{e(x.get("unit", "шт"))}</td><td>{e(x["quantity"])}</td><td>{e(x["result"]["price"])}</td><td>{e(x["result"]["total"])}</td></tr>' for i, x in enumerate(p['items']))
    vat = 'Без НДС' if not p['organization']['vat'] else f'В том числе НДС {e(p["organization"]["vat"])}%'
    return f'''<!doctype html><html lang="ru"><meta charset="utf-8"><title>КП-{row['id']:04d}</title>
    <style>body{{font:16px Arial;max-width:900px;margin:45px auto;color:#182b40}}header{{border-bottom:4px solid #236653;padding-bottom:20px}}table{{width:100%;border-collapse:collapse;margin:35px 0}}td,th{{padding:12px;border-bottom:1px solid #ddd;text-align:left}}pre{{white-space:pre-wrap;font:inherit}}@media print{{button{{display:none}}body{{margin:0}}}}@page{{size:A4;margin:18mm}}</style>
    <button onclick="window.print()">Печать / сохранить PDF</button><header><h1>{e(p['organization']['name'])}</h1><pre>{e(p['organization']['details'])}</pre></header>
    <h2>Коммерческое предложение № {row['id']:04d}</h2><p>от {e(row['created'])}</p><p>{e(p['buyer'])}</p>
    <table><thead><tr><th>№</th><th>Товар</th><th>Ед.</th><th>Кол-во</th><th>Цена, ₽</th><th>Сумма, ₽</th></tr></thead><tbody>{rows}</tbody></table>
    <h2>Итого: {e(p['total'])} ₽</h2><p>{vat}</p><pre>{e(p['terms'])}</pre></html>'''


if __name__ == '__main__':
    init()
    port = int(os.environ.get('PORT', '8000'))
    print(f'КП-Мастер: http://127.0.0.1:{port}', flush=True)
    ThreadingHTTPServer(('127.0.0.1', port), Handler).serve_forever()
