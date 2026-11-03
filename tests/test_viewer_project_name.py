"""Project names come from the bound root and arrive in the initial HTML."""

import contextlib
from html import escape
import http.client
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import patch

from test_viewer import ROOT, fixture
from evomneme_viewer import Explorer, make_server, project_name


class ProjectNameTests(unittest.TestCase):
    def setUp(self):
        area = ROOT / '.evomneme-tests'
        area.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=area)
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name).resolve()
        self.path = self.project / '.evomneme/knowledge.sqlite3'
        self.path.parent.mkdir()
        fixture(self.path)
        self.explorer = Explorer(self.path, history=False)
        self.addCleanup(self.explorer.close)
        self.receipt = self.path.parent / 'connection.json'
        self.binding = {'version': 1, 'database': str(self.path),
                        'project_root': str(self.project), 'scope': 'branch', 'root_id': '1'}
        self.write_receipt()

    def write_receipt(self):
        self.receipt.write_text(json.dumps(self.binding), encoding='utf-8')

    def test_selected_scope_and_root_without_database_writes(self):
        with contextlib.closing(sqlite3.connect(self.path)) as db:
            before = list(db.iterdump())
        self.assertEqual(project_name(self.explorer), 'branch node 1')
        with contextlib.closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(before, list(db.iterdump()))

    def test_invalid_or_missing_receipt_falls_back(self):
        for raw in ('{', '[]', 'null', '{"version": true}', '{"scope": 1}', '{}'):
            with self.subTest(raw=raw):
                self.receipt.write_text(raw, encoding='utf-8')
                self.assertEqual(project_name(self.explorer), self.project.name)
        self.receipt.unlink()
        self.assertEqual(project_name(self.explorer), self.project.name)

    def test_foreign_binding_is_not_used(self):
        for key, value in (('database', str(self.project / 'other.sqlite3')),
                           ('database', 'knowledge.sqlite3'),
                           ('project_root', str(self.project.parent)),
                           ('project_identity', 'different-project')):
            with self.subTest(key=key, value=value):
                original = self.binding.copy()
                self.binding[key] = value
                self.write_receipt()
                self.assertEqual(project_name(self.explorer), self.project.name)
                self.binding = original

    def test_missing_stale_and_empty_root_fall_back(self):
        for scope, root in (('missing', '1'), ('branch', 'missing'), ('branch', '2'), ('branch', '3')):
            self.binding.update(scope=scope, root_id=root)
            self.write_receipt()
            self.assertEqual(project_name(self.explorer), self.project.name)
        self.binding.update(scope='branch', root_id='1')
        self.write_receipt()
        with contextlib.closing(sqlite3.connect(self.path)) as db:
            db.execute("UPDATE nodes SET title='  ' WHERE scope_id='branch' AND id='1'")
            db.commit()
        self.assertEqual(project_name(self.explorer), self.project.name)

    def test_custom_mapping_uses_filename_fallback(self):
        self.explorer.mapping = {'nodes': 'SELECT 1', 'edges': 'SELECT 1'}
        with patch.object(self.explorer, 'connect', side_effect=AssertionError('Unexpected lookup')):
            self.assertEqual(project_name(self.explorer), self.project.name)

    def test_bound_standalone_database_and_matching_identity(self):
        path = self.project / 'standalone.sqlite3'
        fixture(path)
        self.binding.update(database=str(path), project_identity='synthetic-project')
        self.write_receipt()
        with contextlib.closing(sqlite3.connect(path)) as db:
            db.execute("INSERT INTO metadata VALUES ('project_identity', 'synthetic-project')")
            db.commit()
        explorer = Explorer(path, history=False)
        self.addCleanup(explorer.close)
        self.assertEqual(project_name(explorer), 'branch node 1')
        self.receipt.unlink()
        self.assertEqual(project_name(explorer), 'standalone')

    def test_initial_html_escapes_title_and_never_requeries(self):
        title = 'Проект "А" & <Demo>'
        with contextlib.closing(sqlite3.connect(self.path)) as db:
            db.execute("UPDATE nodes SET title=? WHERE scope_id='branch' AND id='1'", (title,))
            db.commit()
        server, _ = make_server(self.explorer)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        conn = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=5)
        self.addCleanup(conn.close)
        # Neither a later rename nor a failed database read affects page loading.
        with contextlib.closing(sqlite3.connect(self.path)) as db:
            db.execute("UPDATE nodes SET title='Renamed' WHERE scope_id='branch' AND id='1'")
            db.commit()
        with patch.object(self.explorer, 'connect', side_effect=AssertionError('Unexpected lookup')):
            for _ in range(2):
                conn.request('GET', '/')
                response = conn.getresponse()
                self.assertEqual(response.status, 200)
                page = response.read().decode('utf-8')
                self.assertIn('<title>' + escape(title) + ' · Memory Explorer · EvoMneme</title>', page)
                self.assertIn('title="' + escape(title) + '">' + escape(title) + '</h1>', page)


if __name__ == '__main__':
    unittest.main()
