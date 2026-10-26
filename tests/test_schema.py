"""Controlled schema, published migration and cross-type graph contract."""

import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
from evomneme import Executor
from evomneme_trace import configure_trace
from evomneme_viewer import Explorer


def controlled_fixture(path):
    db = sqlite3.connect(path)
    db.executescript((ROOT / 'schema.sql').read_text(encoding='utf-8'))
    for scope in ('main', 'branch'):
        db.execute('INSERT INTO scopes VALUES(?,?,?,?,?,?)', (scope, scope, 'synthetic', 'rev', 'snapshot', 'now'))
        for id_, kind, layer in [('file', 'file', 'code'), ('fn', 'function', 'code'),
                                 ('component', 'component', 'knowledge'), ('decision', 'decision', 'knowledge'),
                                 ('unknown', 'unresolved_reference', 'unresolved')]:
            db.execute('''INSERT INTO nodes(scope_id,id,kind,title,summary,confidence,validity,source_path,updated_at,layer)
                VALUES(?,?,?,?,?,'confirmed','current','src/demo.py','now',?)''', (scope, id_, kind, id_, 'Synthetic', layer))
        for id_, src, dst, kind, layer, resolution in [
                ('member', 'fn', 'file', 'declared_in', 'code', 'resolved'),
                ('dependency', 'fn', 'component', 'depends_on', 'cross', 'resolved'),
                ('reason', 'component', 'decision', 'explained_by', 'knowledge', 'resolved'),
                ('cycle', 'decision', 'fn', 'affects', 'cross', 'resolved'),
                ('missing', 'fn', 'unknown', 'calls', 'code', 'unresolved')]:
            db.execute('''INSERT INTO edges(scope_id,id,source_id,target_id,kind,summary,confidence,validity,updated_at,layer,resolution)
                VALUES(?,?,?,?,?,'Synthetic','confirmed','current','now',?,?)''', (scope, id_, src, dst, kind, layer, resolution))
        db.execute("INSERT INTO symbol_details VALUES(?, 'fn', 'Demo.run', 'def run(value):', 'python')", (scope,))
        db.execute("INSERT INTO file_details VALUES(?,'file','verified','partial','hash',NULL,'Review dynamic call')", (scope,))
        db.execute("INSERT INTO evidence(scope_id,id,node_id,description,validity,updated_at) VALUES(?,'proof','fn','Source inspected','current','now')", (scope,))
        db.execute("INSERT INTO evidence(scope_id,id,edge_id,description,validity,updated_at) VALUES(?,'edge-proof','reason','Decision explanation','current','now')", (scope,))
    db.commit()
    db.close()


class SchemaTests(unittest.TestCase):
    def setUp(self):
        area = ROOT / '.evomneme-tests'
        area.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=area)
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'synthetic.sqlite3'
        controlled_fixture(self.path)
        self.db = sqlite3.connect(self.path)
        self.db.execute('PRAGMA foreign_keys=ON')
        self.addCleanup(self.db.close)
        self.explorer = Explorer(self.path)
        self.addCleanup(self.explorer.close)

    def nearby(self, **changes):
        params = dict(scope='main', root='fn', max_depth=2, direction='outgoing',
                      edge_kind=None, traverse_kind=None, result_kind=None, limit=100)
        params.update(changes)
        rows = self.db.execute((ROOT / 'queries/neighborhood.sql').read_text(), params).fetchall()
        return {r[0]: r[-1] for r in rows}

    def test_shared_identity_foreign_keys_and_evidence_targets(self):
        self.assertEqual(self.db.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
        self.assertEqual(self.db.execute('PRAGMA foreign_key_check').fetchall(), [])
        self.assertEqual(self.db.execute('PRAGMA user_version').fetchone()[0], 3)
        for sql in [
                "INSERT INTO symbol_details VALUES('main','absent','missing',NULL,NULL)",
                "UPDATE edges SET target_id='absent' WHERE scope_id='main' AND id='dependency'",
                "UPDATE evidence SET edge_id='reason' WHERE scope_id='main' AND id='proof'",
                "UPDATE edges SET resolution='invented' WHERE scope_id='main' AND id='missing'",
                "UPDATE nodes SET id='file' WHERE scope_id='main' AND id='fn'"]:
            with self.assertRaises(sqlite3.IntegrityError):
                self.db.execute(sql)
            self.db.rollback()

    def test_depth_direction_cycles_scope_and_separate_result_filter(self):
        self.assertEqual(self.nearby(max_depth=0), {'fn': 0})
        self.assertEqual(self.nearby(result_kind='decision'), {'decision': 2})
        self.assertEqual(self.nearby(result_kind='decision', traverse_kind='decision'), {})
        self.assertEqual(self.nearby(direction='incoming', max_depth=1), {'fn': 0, 'decision': 1})
        self.assertEqual(self.nearby(edge_kind='depends_on'), {'fn': 0, 'component': 1})
        self.assertEqual(self.nearby(max_depth=32)['fn'], 0)
        self.assertEqual(self.nearby(scope='missing'), {})
        self.assertEqual(self.nearby(max_depth=-1), {})
        self.assertEqual(self.nearby(limit=-1), {})
        self.db.execute("UPDATE nodes SET validity='stale' WHERE scope_id='main' AND id='component'")
        self.assertEqual(self.nearby(result_kind='decision'), {})
        self.assertEqual(self.nearby(scope='branch', result_kind='decision'), {'decision': 2})

    def test_v3_viewer_all_layers_details_provenance_and_read_only(self):
        before = self.path.read_bytes()
        graph = self.explorer.snapshot({'whole_graph': True})
        self.assertEqual(graph['totals'], {'nodes': 10, 'edges': 10})
        self.assertEqual(graph['dangling_total'], 0)
        self.assertEqual({n['source_table'] for n in graph['nodes']}, {'nodes'})
        self.assertEqual({e['source_table'] for e in graph['edges']}, {'edges'})
        self.assertEqual(len({n['graph_id'] for n in graph['nodes']}), 10)
        detail = self.explorer.detail({'type': 'nodes', 'id': '["main","fn"]'})
        self.assertEqual(detail['rows'][0]['signature'], 'def run(value):')
        self.assertEqual(detail['coverage'][0]['relationship_status'], 'partial')
        self.assertEqual(detail['evidence'][0]['id'], 'proof')
        edge = self.explorer.detail({'type': 'edges', 'id': '["main","reason"]'})
        self.assertEqual(edge['evidence'][0]['id'], 'edge-proof')
        focused = self.explorer.snapshot({'root': '["main","fn"]', 'depth': 2, 'kind': 'decision'})
        self.assertEqual([n['id'] for n in focused['nodes']], ['decision'])
        layers = self.explorer.snapshot({'excluded_layers': ['code']})
        self.assertTrue(all(n['layer'] != 'code' for n in layers['nodes']))
        self.assertEqual(before, self.path.read_bytes())

    def test_symbol_inspection_without_file_edges_and_scope_isolation(self):
        self.db.execute("DELETE FROM edges WHERE kind='declared_in'")
        self.db.execute("""INSERT INTO nodes(scope_id,id,kind,title,summary,confidence,validity,source_path,updated_at,layer)
            VALUES('main','owner','class','Demo','Owns run','confirmed','current','src/demo.py','now','code')""")
        self.db.execute("UPDATE nodes SET kind='method' WHERE scope_id='main' AND id='fn'")
        for id_, source, target in [('file-owner', 'file', 'owner'), ('owner-member', 'owner', 'fn')]:
            self.db.execute("""INSERT INTO edges(scope_id,id,source_id,target_id,kind,summary,confidence,validity,updated_at)
                VALUES('main',?,?,?,'contains','Immediate owner','confirmed','current','now')""", (id_, source, target))
        self.db.execute("UPDATE file_details SET relationship_status='verified' WHERE scope_id='branch'")
        self.db.commit()
        before = self.path.read_bytes()
        self.assertEqual(self.nearby(root='file', direction='outgoing', edge_kind='contains'),
                         {'file': 0, 'owner': 1, 'fn': 2})
        self.assertEqual(self.db.execute("SELECT count(*) FROM edges WHERE kind='declared_in'").fetchone()[0], 0)
        for scope, status in [('main', 'partial'), ('branch', 'verified')]:
            with self.subTest(scope=scope):
                detail = self.explorer.detail({'type': 'nodes', 'id': json.dumps([scope, 'fn'], separators=(',', ':'))})
                self.assertEqual([(r['scope_id'], r['node_id'], r['relationship_status']) for r in detail['coverage']],
                                 [(scope, 'file', status)])
                self.assertEqual(detail['coverage'][0]['remaining_work'], 'Review dynamic call')
                self.assertFalse(detail['rows'][0]['coverage_has_more'])
        self.assertEqual(before, self.path.read_bytes())

    def test_symbol_inspection_requires_nonempty_matching_source_path(self):
        self.db.execute("DELETE FROM edges WHERE kind='declared_in'")
        for path in (None, '', 'src/other.py'):
            with self.subTest(path=path):
                self.db.execute("UPDATE nodes SET source_path=? WHERE scope_id='main' AND id='fn'", (path,))
                # Empty file locators must not match each other accidentally.
                self.db.execute("UPDATE nodes SET source_path=? WHERE scope_id='main' AND id='file'",
                                ('src/demo.py' if path == 'src/other.py' else path,))
                self.db.commit()
                detail = self.explorer.detail({'type': 'nodes', 'id': '["main","fn"]'})
                self.assertEqual(detail['coverage'], [])
                own = self.explorer.detail({'type': 'nodes', 'id': '["main","file"]'})
                self.assertEqual([r['node_id'] for r in own['coverage']], ['file'])

    def test_locator_lookup_excludes_stale_and_nonfile_nodes_but_keeps_own_detail(self):
        for kind, validity in [('file', 'stale'), ('file', 'superseded'), ('module', 'current')]:
            with self.subTest(kind=kind, validity=validity):
                self.db.execute("UPDATE nodes SET kind=?,validity=? WHERE scope_id='main' AND id='file'", (kind, validity))
                self.db.commit()
                detail = self.explorer.detail({'type': 'nodes', 'id': '["main","fn"]'})
                self.assertEqual(detail['coverage'], [])
                own = self.explorer.detail({'type': 'nodes', 'id': '["main","file"]'})
                self.assertEqual([r['node_id'] for r in own['coverage']], ['file'])

    def test_detail_changes_refresh_fingerprints_and_new_types_need_no_schema(self):
        before = self.explorer.snapshot({'whole_graph': True})
        previous = {n['graph_id']: n['fingerprint'] for n in before['nodes']}
        self.db.execute("UPDATE symbol_details SET signature='def run(new):' WHERE scope_id='main' AND node_id='fn'")
        self.db.execute("UPDATE file_details SET relationship_status='verified' WHERE scope_id='main' AND node_id='file'")
        self.db.execute("UPDATE nodes SET kind='new_language_construct',layer='new_layer' WHERE scope_id='main' AND id='component'")
        self.db.commit()
        after = self.explorer.snapshot({'whole_graph': True})
        current = {n['graph_id']: n for n in after['nodes']}
        for id_ in ('fn', 'file', 'component'):
            key = json.dumps(['main', id_], separators=(',', ':'))
            self.assertNotEqual(previous[key], current[key]['fingerprint'])
        self.assertEqual(current['["main","component"]']['kind'], 'new_language_construct')

    def test_unknown_version_or_broken_contract_is_explicit(self):
        self.db.execute("UPDATE metadata SET value='999' WHERE key='schema_version'")
        self.db.commit()
        with self.assertRaisesRegex(ValueError, 'Unsupported EvoMneme schema'):
            self.explorer.snapshot({})
        self.db.execute("UPDATE metadata SET value='3' WHERE key='schema_version'")
        self.db.execute('PRAGMA user_version=999')
        self.db.commit()
        with self.assertRaisesRegex(ValueError, 'user_version=999'):
            self.explorer.snapshot({})
        self.db.execute('PRAGMA user_version=3')
        self.db.execute('ALTER TABLE symbol_details RENAME COLUMN signature TO unsupported_signature')
        self.db.commit()
        with self.assertRaisesRegex(ValueError, 'Incompatible EvoMneme v3 table symbol_details'):
            self.explorer.snapshot({})

    def test_sql_transport_and_trace_use_shared_node_and_edge_ids(self):
        executor = Executor(self.path)
        self.addCleanup(executor.close)
        log = Path(self.temp.name) / 'activity'
        configure_trace(executor, log, 'synthetic-session')
        for table in ('nodes', 'edges'):
            result = executor.execute_sql(sql='SELECT scope_id,id FROM ' + table + " WHERE scope_id='main' LIMIT 1")
            self.assertTrue(result['ok'])
        events = [json.loads(line) for file in log.glob('*.jsonl') for line in file.read_text().splitlines()]
        self.assertEqual([e['references'][0]['table'] for e in events], ['nodes', 'edges'])
        params = dict(scope='main', root='fn', max_depth=2, direction='outgoing', edge_kind=None,
                      traverse_kind=None, result_kind='decision', limit=10)
        result = executor.execute_sql(sql=(ROOT / 'queries/neighborhood.sql').read_text(), params=params)
        self.assertTrue(result['ok'], result)
        self.assertEqual(result['results'][0]['rows'][0][0], 'decision')


class MigrationTests(unittest.TestCase):
    def legacy(self):
        db = sqlite3.connect(':memory:')
        self.addCleanup(db.close)
        db.executescript((ROOT / 'tests/fixtures/schema-v2.sql').read_text())
        db.execute("INSERT INTO scopes VALUES('main','main','host','rev','snapshot','now')")
        for id_ in ('a', 'b'):
            db.execute("INSERT INTO records VALUES('main',?,'finding',?,'summary','confirmed','current','file','hash',1,2,'now')", (id_, id_))
        db.execute("INSERT INTO relations VALUES('main','e','a','b','supports','reason','confirmed','current','file','hash','now')")
        db.execute("INSERT INTO evidence VALUES('main','p','a',NULL,'proof','file','hash','current','now')")
        db.execute("INSERT INTO evidence VALUES('main','ep',NULL,'e','edge proof','file','hash','stale','now')")
        db.execute("INSERT INTO metadata VALUES('project_identity','synthetic')")
        db.execute("INSERT INTO history VALUES(1,'now','initial','retained')")
        db.commit()
        return db

    def test_migration_preserves_all_data_constraints_and_matches_new_structure(self):
        db = self.legacy()
        original = {table: db.execute('SELECT * FROM ' + table).fetchall() for table in ('records', 'relations', 'evidence', 'scopes')}
        db.executescript((ROOT / 'migrations/002_to_003.sql').read_text())
        self.assertEqual([row[:-1] for row in db.execute('SELECT * FROM nodes')], original['records'])
        self.assertEqual([row[:-4] for row in db.execute('SELECT * FROM edges')], original['relations'])
        self.assertEqual(db.execute('SELECT * FROM evidence').fetchall(), original['evidence'])
        self.assertEqual(db.execute('SELECT * FROM scopes').fetchall(), original['scopes'])
        self.assertEqual(db.execute("SELECT value FROM metadata WHERE key='project_identity'").fetchone()[0], 'synthetic')
        self.assertEqual(db.execute('SELECT detail FROM history WHERE id=1').fetchone()[0], 'retained')
        self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(), [])
        self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 3)
        fresh = sqlite3.connect(':memory:')
        self.addCleanup(fresh.close)
        fresh.executescript((ROOT / 'schema.sql').read_text())
        tables = [r[0] for r in fresh.execute("SELECT name FROM sqlite_schema WHERE type='table'")]
        for table in tables:
            self.assertEqual(db.execute('PRAGMA table_info(' + table + ')').fetchall(), fresh.execute('PRAGMA table_info(' + table + ')').fetchall(), table)
            self.assertEqual(db.execute('PRAGMA foreign_key_list(' + table + ')').fetchall(), fresh.execute('PRAGMA foreign_key_list(' + table + ')').fetchall(), table)

    def test_wrong_versions_extensions_and_failed_migration_leave_legacy_intact(self):
        for change in ('PRAGMA user_version=999', 'CREATE TABLE code_symbols(id TEXT)',
                       'ALTER TABLE records ADD COLUMN private_extension TEXT', 'DROP INDEX records_kind'):
            with self.subTest(change=change):
                db = self.legacy()
                db.execute(change)
                db.commit()
                before = db.execute("SELECT type,name,sql FROM sqlite_schema ORDER BY name").fetchall()
                with self.assertRaises(sqlite3.Error):
                    try:
                        db.executescript((ROOT / 'migrations/002_to_003.sql').read_text())
                    except sqlite3.Error:
                        db.rollback()
                        raise
                self.assertEqual(db.execute("SELECT type,name,sql FROM sqlite_schema ORDER BY name").fetchall(), before)
                self.assertEqual(db.execute('SELECT count(*) FROM records').fetchone()[0], 2)


if __name__ == '__main__':
    unittest.main()
