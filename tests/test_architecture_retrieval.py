"""Architecture orientation contracts and source-grounded synthetic scenarios."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import types
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from evomneme import Executor

spec = importlib.util.spec_from_file_location('orientation_fixture', ROOT / 'tests/fixtures/orientation/build_fixture.py')
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)
probe_spec = importlib.util.spec_from_file_location('orientation_probe', ROOT / 'tests/fixtures/orientation/readonly_query.py')
probe = importlib.util.module_from_spec(probe_spec)
probe_spec.loader.exec_module(probe)


def rows(result):
    table = result['results'][0]
    return [dict(zip(table['columns'], row)) for row in table['rows']]


class ArchitectureRetrievalTests(unittest.TestCase):
    def setUp(self):
        area = ROOT / '.evomneme-tests'
        area.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=area)
        self.addCleanup(self.temp.cleanup)
        self.receipt = fixture.build(Path(self.temp.name))
        self.executor = Executor(Path(self.receipt['database']), history=False)
        self.addCleanup(self.executor.close)
        self.measured_results = []

    def query(self, name, budget=8192, **params):
        if name != 'scopes':
            params.setdefault('scope', self.receipt['scope'])
        result = self.executor.execute_sql(sql=(ROOT / 'queries' / (name + '.sql')).read_text(encoding='utf-8'),
            params=params, max_rows=params.get('limit', 8), max_output_bytes=budget)
        self.assertTrue(result['ok'], result)
        self.measured_results.append(result)
        return result

    def catalog(self, **params):
        defaults = dict(kind='architecture', after_id=None, limit=3, preview_chars=120)
        defaults.update(params)
        return self.query('architecture', **defaults)

    def incident(self, root, **params):
        defaults = dict(root=root, edge_kind=None, after_id=None, limit=8)
        defaults.update(params)
        return self.query('incident', **defaults)

    def test_catalog_pages_pathless_knowledge_and_measurable_budget(self):
        first = self.catalog()
        second = self.catalog(after_id=rows(first)[-1]['id'])
        self.assertTrue(first['results'][0]['has_more'])
        self.assertFalse(second['results'][0]['has_more'])
        cards = rows(first) + rows(second)
        self.assertEqual(len(cards), 6)
        self.assertTrue(all(card['kind'] == 'architecture' and card['layer'] == 'knowledge' for card in cards))
        self.assertTrue(all(len(card['summary_preview']) <= 120 for card in cards))
        self.assertTrue(any(card['summary_truncated'] for card in cards))
        self.assertEqual(cards[-1]['confidence'], 'uncertain')
        self.assertEqual(len(self.measured_results), 2)
        for result in self.measured_results:
            self.assertLessEqual(len(json.dumps(result, ensure_ascii=False, separators=(',', ':')).encode('utf-8')), 8192)

    def test_preview_bounds_and_explicit_kind(self):
        self.assertTrue(all(card['summary_preview'] == '' and card['summary_truncated'] for card in rows(self.catalog(preview_chars=0))))
        for invalid in (-1, 241, '120', 1.5):
            self.assertEqual(rows(self.catalog(preview_chars=invalid)), [])
        for invalid in (0, 33):
            self.assertEqual(rows(self.catalog(limit=invalid)), [])
        self.assertEqual(len(rows(self.catalog(kind='decision'))), 2)
        self.assertEqual(rows(self.catalog(kind='nonexistent')), [])

    def test_full_detail_reaches_implementation_and_constraint_across_modules(self):
        detail = rows(self.query('node', id='a-admission'))[0]
        self.assertIsNone(detail['source_path'])
        self.assertIn('pending request', detail['summary'])
        admission = rows(self.incident('a-admission'))
        self.assertEqual({r['neighbor_id'] for r in admission}, {'confirm', 'c-local', 'd-wire', 'e-delivery'})
        raw = rows(self.incident('b-draft'))
        self.assertEqual({r['neighbor_id'] for r in raw}, {'edit_reference', 'decision-raw'})
        replay = rows(self.incident('e-delivery'))
        self.assertIn('decision-replay', {r['neighbor_id'] for r in replay})
        code = rows(self.incident('confirm', edge_kind='calls'))
        self.assertEqual({r['neighbor_id'] for r in code}, {'prepare', 'commit', 'pending', 'acknowledge'})
        self.assertEqual({r['neighbor_source_path'] for r in code}, {'protocol.py', 'ledger.py'})
        for row in code:
            path = Path(self.receipt['source_root']) / row['neighbor_source_path']
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), row['neighbor_source_hash'])
            self.assertIn('def ', path.read_text(encoding='utf-8').splitlines()[row['neighbor_line_start'] - 1])

    def test_scopes_no_auto_latest_and_physical_file_declarations(self):
        first = self.query('scopes', after_id=None, limit=1)
        self.assertTrue(first['results'][0]['has_more'])
        second = self.query('scopes', after_id=rows(first)[-1]['id'], limit=1)
        self.assertEqual({rows(first)[0]['id'], rows(second)[0]['id']}, {'synthetic-current', 'synthetic-other'})
        self.assertEqual(rows(self.catalog(scope='synthetic-other'))[0]['title'], 'Old local strategy')
        entry = self.query('anchors', query='ledger.py', mode='exact', path_prefix=None, after_id=None, limit=8)
        self.assertEqual([r['id'] for r in rows(entry)], ['ledger.py'])
        declarations = self.query('declarations', source_path='ledger.py', kind='method', after_id=None, limit=8)
        self.assertEqual({r['id'] for r in rows(declarations)}, {'pending', 'commit', 'acknowledge'})

    def test_no_architecture_and_missing_edge_are_real_gaps(self):
        db = self.executor.connection
        db.execute("DELETE FROM evidence WHERE edge_id='03'")
        db.execute("DELETE FROM edges WHERE id='03'")
        self.assertNotIn('commit', {r['neighbor_id'] for r in rows(self.incident('c-local'))})
        db.execute("UPDATE nodes SET validity='stale' WHERE kind='architecture' AND scope_id='synthetic-current'")
        self.assertEqual(rows(self.catalog()), [])
        self.assertEqual(rows(self.query('node', id='c-local')), [])
        # Actual source still exists: an empty catalog is not absence of implementation.
        self.assertTrue((Path(self.receipt['source_root']) / 'ledger.py').is_file())

    def test_receipt_has_tasks_but_no_oracle_identifiers(self):
        self.assertEqual(len(self.receipt['tasks']), 2)
        text = json.dumps(self.receipt)
        for identifier in ('a-admission', 'b-draft', 'c-local', 'decision-replay'):
            self.assertNotIn(identifier, text)
        with self.assertRaises(FileExistsError):
            fixture.build(Path(self.temp.name))

    def test_probe_audits_reads_and_failed_writes_without_changing_database(self):
        root = Path(self.temp.name)
        audit = root / 'probe.jsonl'
        result = probe.run(Path(self.receipt['database']), ROOT / 'queries/architecture.sql',
                           dict(scope=self.receipt['scope'], kind='architecture', after_id=None,
                                limit=12, preview_chars=120), 12, 8192, audit)
        self.assertEqual(len(rows(result)), 6)
        attempted_write = root / 'write.sql'
        attempted_write.write_text("UPDATE nodes SET summary='Unwanted mutation'", encoding='utf-8')
        failed = probe.run(Path(self.receipt['database']), attempted_write, {}, 12, 8192, audit)
        self.assertFalse(failed['ok'])
        records = [json.loads(line) for line in audit.read_text(encoding='utf-8').splitlines()]
        self.assertEqual(len(records), 2)
        self.assertTrue(all(record['database_unchanged'] for record in records))
        self.assertEqual(records[0]['result_bytes'], len(json.dumps(result, ensure_ascii=False, separators=(',', ':')).encode('utf-8')))
        self.assertEqual(records[1]['request']['sql'], attempted_write.read_text(encoding='utf-8'))
        self.assertFalse(records[1]['result']['ok'])

    def test_probe_creates_audit_parent_before_query(self):
        audit = Path(self.temp.name) / 'new' / 'nested' / 'audit.jsonl'
        result = probe.run(Path(self.receipt['database']), ROOT / 'queries/node.sql',
                           dict(scope=self.receipt['scope'], id='a-admission'), 12, 8192, audit)
        self.assertEqual(rows(result)[0]['id'], 'a-admission')
        record = json.loads(audit.read_text(encoding='utf-8'))
        self.assertTrue(record['database_unchanged'])
        self.assertEqual(record['result'], result)

    def test_probe_audit_open_failure_and_database_destination_precede_execution(self):
        audit_directory = Path(self.temp.name) / 'not-a-file'
        audit_directory.mkdir()
        database = Path(self.receipt['database'])
        before = database.read_bytes()
        params = dict(scope=self.receipt['scope'], id='a-admission')
        with mock.patch.object(probe, 'Executor') as executor:
            with self.assertRaises(OSError):
                probe.run(database, ROOT / 'queries/node.sql', params, 12, 8192, audit_directory)
            executor.assert_not_called()
            with self.assertRaises(ValueError):
                probe.run(database, ROOT / 'queries/node.sql', params, 12, 8192, database)
            executor.assert_not_called()
        self.assertEqual(database.read_bytes(), before)

    def test_sources_preserve_raw_draft_atomicity_and_exact_retry_bytes(self):
        previous = {name: sys.modules.get(name) for name in ('protocol', 'drafts', 'ledger', 'commands')}
        loaded = {}
        try:
            for name in previous:
                module = types.ModuleType(name)
                sys.modules[name] = module
                path = Path(self.receipt['source_root']) / (name + '.py')
                exec(compile(path.read_text(encoding='utf-8'), str(path), 'exec'), module.__dict__)
                loaded[name] = module
            draft = loaded['drafts'].Draft()
            draft.edit_reference(' ab 123 ')
            connection = sqlite3.connect(':memory:')
            self.addCleanup(connection.close)
            ledger = loaded['ledger'].Ledger(connection)
            sent = []

            def timeout(request_id, payload):
                sent.append((request_id, payload))
                raise TimeoutError('Synthetic timeout')

            with self.assertRaises(TimeoutError):
                loaded['commands'].confirm(draft, 'request-1', ledger, timeout)
            self.assertEqual(draft.reference, ' ab 123 ')
            self.assertEqual(connection.execute('SELECT reference FROM saved').fetchone()[0], 'AB123')
            draft.edit_reference('different text')
            loaded['commands'].confirm(draft, 'request-1', ledger, lambda id_, payload: sent.append((id_, payload)))
            self.assertEqual(sent[0], sent[1])
            self.assertIsNone(ledger.pending('request-1'))
            connection.execute("INSERT INTO outbox VALUES('collision',X'00')")
            connection.commit()
            with self.assertRaises(sqlite3.IntegrityError):
                ledger.commit('collision', 'OTHER', b'different')
            self.assertIsNone(connection.execute("SELECT reference FROM saved WHERE request_id='collision'").fetchone())
        finally:
            for name, module in previous.items():
                if module is None:
                    sys.modules.pop(name, None)
                else:
                    sys.modules[name] = module


if __name__ == '__main__':
    unittest.main()
