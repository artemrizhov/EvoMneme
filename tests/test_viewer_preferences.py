"""Viewer preferences survive server restarts without changing graph data."""

from contextlib import closing
import http.client
import json
from pathlib import Path
import sqlite3
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
from evomneme_viewer import Explorer, make_server
from evomneme_viewer_preferences import DEFAULTS, ViewerPreferences


class ViewerPreferencesTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'), 'Frontend preferences regression needs existing Node.js')
    def test_frontend_preferences(self):
        result = subprocess.run([shutil.which('node'), str(ROOT / 'tests/test_viewer_preferences.js')],
                                capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr.decode('utf-8', 'replace'))

    def setUp(self):
        area = ROOT / '.evomneme-tests'
        area.mkdir(exist_ok=True)
        temporary = tempfile.TemporaryDirectory(dir=area)
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.database = self.directory / 'graph.sqlite3'
        with closing(sqlite3.connect(self.database)) as db:
            db.executescript((ROOT / 'schema.sql').read_text(encoding='utf-8'))
        self.preferences = ViewerPreferences(self.database)

    def server(self):
        explorer = Explorer(self.database, history=False)
        self.addCleanup(explorer.close)
        server, token = make_server(explorer)
        self.addCleanup(server.server_close)
        return server, token

    def post(self, server, token, body, **headers):
        connection = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=5)
        worker = threading.Thread(target=server.handle_request)
        worker.start()
        try:
            connection.request('POST', '/api/preferences', json.dumps(body),
                               headers={'X-Viewer-Token': token, **headers})
            response = connection.getresponse()
            return response.status, json.loads(response.read())
        finally:
            connection.close()
            worker.join(timeout=6)

    def test_read_defaults_does_not_create_any_files(self):
        before = set(self.directory.iterdir())
        server, token = self.server()
        self.assertEqual(self.post(server, token, {}), (200, DEFAULTS))
        self.assertEqual(self.post(server, token, {'updates': {}}), (200, DEFAULTS))
        self.assertEqual(set(self.directory.iterdir()), before)

    def test_authenticated_roundtrip_restart_and_explicit_off(self):
        graph_before = self.database.read_bytes()
        original, token = self.server()
        enabled = {'gpu': True, 'worker': True, 'elementScale': 65,
                   'experimentalPromptSeen': True}
        self.assertEqual(self.post(original, token, {'updates': enabled}), (200, enabled))
        restarted, new_token = self.server()
        self.assertNotEqual(original.server_port, restarted.server_port)
        self.assertEqual(self.post(restarted, new_token, {}), (200, enabled))
        disabled = {**enabled, 'gpu': False, 'worker': False, 'elementScale': 125}
        self.assertEqual(self.post(restarted, new_token, {'updates': {
            'gpu': False, 'worker': False, 'elementScale': 125}}), (200, disabled))
        again, again_token = self.server()
        self.assertEqual(self.post(again, again_token, {}), (200, disabled))
        self.assertEqual(self.database.read_bytes(), graph_before)
        self.assertEqual(self.preferences.path, self.database.with_suffix('.viewer-settings.json'))

    def test_database_isolation(self):
        self.preferences.request({'updates': {'gpu': True}})
        other = ViewerPreferences(self.directory / 'another.sqlite3')
        self.assertEqual(other.request({}), DEFAULTS)
        other.request({'updates': {'worker': True}})
        self.assertEqual(self.preferences.read(), {**DEFAULTS, 'gpu': True})

    def test_invalid_updates_are_rejected_without_writing(self):
        self.preferences.request({'updates': {'worker': True}})
        before = self.preferences.path.read_bytes()
        for updates in (None, [], {'unknown': True}, {'gpu': 1}, {'worker': 'false'},
                        {'experimentalPromptSeen': 0}, {'elementScale': True},
                        {'elementScale': 60}, {'elementScale': '100'},
                        {'elementScale': float('nan')}, {'gpu': False, 'worker': None}):
            with self.subTest(updates=updates), self.assertRaises(ValueError):
                self.preferences.request({'updates': updates})
            self.assertEqual(self.preferences.path.read_bytes(), before)

    def test_invalid_saved_files_are_visible_and_never_overwritten(self):
        server, token = self.server()
        for raw in ('{broken', '[]', 'null', '{"gpu": "false"}',
                    '{"elementScale": 61}', '{"unrecognized": true}'):
            self.preferences.path.write_text(raw, encoding='utf-8')
            for body in ({}, {'updates': {'gpu': True}}):
                with self.subTest(raw=raw, body=body):
                    status, result = self.post(server, token, body)
                    self.assertEqual(status, 400)
                    self.assertIn('Invalid viewer settings file', result['error'])
                    self.assertEqual(self.preferences.path.read_text(encoding='utf-8'), raw)
        self.preferences.path.write_bytes(b'\xff')
        self.assertEqual(self.post(server, token, {})[0], 400)
        self.assertEqual(self.preferences.path.read_bytes(), b'\xff')

    def test_authentication_and_origin_guards_precede_file_access(self):
        server, token = self.server()
        for headers, supplied in (({}, 'wrong'), ({'Origin': 'https://foreign.test'}, token),
                                  ({'Host': 'foreign.test'}, token)):
            with self.subTest(headers=headers):
                status, _ = self.post(server, supplied, {'updates': {'gpu': True}}, **headers)
                self.assertEqual(status, 403)
                self.assertFalse(self.preferences.path.exists())

    def test_replace_failure_preserves_file_and_removes_temporary(self):
        self.preferences.request({'updates': {'worker': True}})
        before = self.preferences.path.read_bytes()
        with patch('evomneme_viewer_preferences.os.replace', side_effect=OSError('synthetic failure')):
            with self.assertRaisesRegex(OSError, 'synthetic failure'):
                self.preferences.request({'updates': {'gpu': True}})
        self.assertEqual(self.preferences.path.read_bytes(), before)
        self.assertEqual(list(self.directory.glob('*.tmp')), [])

    def test_concurrent_instances_merge_under_file_lock(self):
        peers = [ViewerPreferences(self.database) for _ in range(3)]
        barrier = threading.Barrier(3)
        failures = []

        def update(peer, values):
            try:
                barrier.wait(timeout=5)
                peer.request({'updates': values})
            except Exception as exc:
                failures.append(exc)

        workers = [threading.Thread(target=update, args=(peer, values))
                   for peer, values in zip(peers, ({'gpu': True}, {'worker': True}, {'elementScale': 250}))]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(timeout=7)
            self.assertFalse(worker.is_alive())
        self.assertEqual(failures, [])
        self.assertEqual(self.preferences.read(), {**DEFAULTS, 'gpu': True, 'worker': True, 'elementScale': 250})


if __name__ == '__main__':
    unittest.main()
