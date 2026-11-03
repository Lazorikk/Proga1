import json
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.request import Request, urlopen
from http.server import ThreadingHTTPServer
import app


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.database = Path(self.folder.name) / 'test.sqlite3'
        self.binding = patch.object(app, 'DB', self.database)
        self.binding.start()
        # Create the exact old schema: migration must preserve existing records.
        with sqlite3.connect(self.database) as db:
            db.executescript('''CREATE TABLE organizations(id INTEGER PRIMARY KEY,
                name TEXT NOT NULL, details TEXT NOT NULL, vat REAL NOT NULL, deduct INTEGER NOT NULL);
                CREATE TABLE quotes(id INTEGER PRIMARY KEY, created TEXT NOT NULL,
                buyer TEXT NOT NULL, payload TEXT NOT NULL, total TEXT NOT NULL);
                INSERT INTO organizations VALUES(1, 'Старая организация', 'ИНН 123', 22, 1);''')
        app.init()
        app.init()
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), app.Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = 'http://127.0.0.1:' + str(self.server.server_port)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.binding.stop()
        self.folder.cleanup()

    def request(self, path, data=None):
        req = Request(self.base + path, data=json.dumps(data).encode() if data else None,
                      headers={'Content-Type': 'application/json'})
        with urlopen(req) as response:
            return json.load(response)

    def quote(self):
        return dict(organization=1, buyer='<Клиент>', manager='Анна, 123', terms='5 дней',
                    items=[dict(name='Цемент', quantity=2, purchase=122, markup=20,
                                purchase_vat=22, unit='меш', delivery=10)])

    def test_edit_copy_status_and_snapshot(self):
        data = self.quote()
        qid = self.request('/api/quotes', data)['id']
        self.request('/api/organizations', dict(id=1, name='Новые реквизиты', details='Новый адрес',
                                              vat=5, deduct=False, markup=30))
        data['id'] = qid
        data['buyer'] = 'Обновлённый клиент'
        self.assertEqual(self.request('/api/quotes', data)['id'], qid)
        stored = self.request('/api/quotes/' + str(qid))
        payload = json.loads(stored['payload'])
        self.assertEqual(payload['organization']['vat'], 22)
        self.assertEqual(payload['organization']['name'], 'Старая организация')
        self.assertEqual(stored['buyer'], data['buyer'])
        data.pop('id')
        copy = self.request('/api/quotes', data)['id']
        self.assertNotEqual(copy, qid)
        self.request('/api/status', dict(id=qid, status='Согласовано'))
        self.assertEqual(self.request('/api/quotes/' + str(qid))['status'], 'Согласовано')

    def test_print_privacy_and_backup(self):
        qid = self.request('/api/quotes', self.quote())['id']
        with urlopen(self.base + '/print/' + str(qid)) as response:
            page = response.read().decode('utf-8')
        self.assertIn('&lt;Клиент&gt;', page)
        self.assertIn('Анна', page)
        self.assertIn('меш', page)
        self.assertNotIn('purchase', page)
        self.assertNotIn('profit', page)
        with urlopen(self.base + '/api/backup') as response:
            backup = response.read()
        target = Path(self.folder.name) / 'restored.sqlite3'
        target.write_bytes(backup)
        with sqlite3.connect(target) as db:
            self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
            self.assertEqual(db.execute('SELECT count(*) FROM quotes').fetchone()[0], 1)

    def test_migration_preserves_organization(self):
        data = self.request('/api/data')
        self.assertEqual(data['organizations'][0]['name'], 'Старая организация')
        self.assertEqual(data['organizations'][0]['markup'], 20)
