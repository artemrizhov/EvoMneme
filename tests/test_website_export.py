"""Whole-graph publication, saved replay and privacy checks; no live DB required."""

from contextlib import closing, redirect_stderr, redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from export_website_demo import (
    CALL_FIELDS, CHANGE_FIELDS, EDGE_FIELDS, HISTORY_COLUMNS, NODE_FIELDS,
    PRIVATE, PUBLIC_REVISION, REPOSITORY, encoded, export_publication,
    export_snapshot, git_sources, source_url, main,
)
from evomneme_graph import projection_sql, validate_schema
from evomneme_journal import install

REVISION = 'a' * 40
SHA256 = 'f' * 64
PRIVATE_SENTINEL = 'PRIVATE_SENTINEL password=fixture-only'
TIME = '2026-10-27T00:00:00Z'
VERIFIED = {(PUBLIC_REVISION, 'src/public.py'): SHA256}


def fixture(path, history=True):
    """Independent v3 fixture with multiple scopes, all layers and private extras."""
    with closing(sqlite3.connect(path)) as db:
        db.executescript((ROOT / 'schema.sql').read_text(encoding='utf-8'))
        db.executescript('ALTER TABLE nodes ADD COLUMN private_extra TEXT; ALTER TABLE edges ADD COLUMN private_extra TEXT;')
    if history:
        install(path.resolve())
    with closing(sqlite3.connect(path)) as db, db:
        for scope in ('main', 'other'):
            db.execute('INSERT INTO scopes VALUES(?,?,?,?,?,?)',
                       (scope, PRIVATE_SENTINEL, 'C:/private/worktree', REVISION, PRIVATE_SENTINEL, TIME))
        db.execute('INSERT INTO metadata VALUES(?,?)', ('canonical_root', 'C:/private/worktree'))
        db.execute('INSERT INTO metadata VALUES(?,?)', ('project_identity', 'fixture-project'))
        for scope, node_id, layer, prose, path_value, digest in (
                ('main', 'root', 'knowledge', 'Stored architecture meaning.', 'src/public.py', SHA256),
                ('main', 'function', 'code', 'Stored code responsibility.', 'src/public.py', SHA256),
                ('main', 'foreign', 'boundary', 'Stored external boundary.', None, None),
                ('other', 'root', 'knowledge', 'A separate saved scope.', 'src/unpublished.py', 'e' * 64),
                ('main', 'deleted', 'code', 'A genuinely deleted declaration.', 'src/public.py', SHA256)):
            db.execute('INSERT INTO nodes(scope_id,id,kind,title,summary,confidence,validity,source_path,source_hash,line_start,line_end,updated_at,layer,private_extra) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                       (scope, node_id, 'function' if layer == 'code' else 'architecture', node_id,
                        prose, 'inferred', 'current', path_value, digest, 1, 4, TIME, layer, PRIVATE_SENTINEL))
        for edge_id, target, layer in (('implementation', 'root', 'cross'), ('boundary', 'foreign', 'boundary')):
            db.execute('INSERT INTO edges(scope_id,id,source_id,target_id,kind,summary,confidence,validity,source_path,source_hash,updated_at,layer,resolution,line_start,private_extra) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                       ('main', edge_id, 'function', target, 'implements', 'Stored relationship meaning.',
                        'inferred', 'stale', 'src/public.py', SHA256, TIME, layer, 'resolved', 1, PRIVATE_SENTINEL))
        db.execute('INSERT INTO symbol_details VALUES(?,?,?,?,?)',
                   ('main', 'function', PRIVATE_SENTINEL, PRIVATE_SENTINEL, 'python'))
        db.execute('INSERT INTO file_details(scope_id,node_id,exclusion_reason,remaining_work) VALUES(?,?,?,?)',
                   ('main', 'function', PRIVATE_SENTINEL, PRIVATE_SENTINEL))
        for evidence_id, node_id in (('proof', 'root'), ('code-proof', 'function')):
            db.execute('INSERT INTO evidence(scope_id,id,node_id,description,source_path,validity,updated_at) VALUES(?,?,?,?,?,?,?)',
                       ('main', evidence_id, node_id, PRIVATE_SENTINEL, 'src/public.py', 'current', TIME))
        db.execute('INSERT INTO evidence(scope_id,id,edge_id,description,validity,updated_at) VALUES(?,?,?,?,?,?)',
                   ('main', 'edge-proof', 'implementation', PRIVATE_SENTINEL, 'current', TIME))
        db.execute('INSERT INTO history(happened_at,action,detail) VALUES(?,?,?)', (TIME, 'inspection', PRIVATE_SENTINEL))
        if history:
            # Exercise complete native pagination, beyond its 200-row page.
            for i in range(205):
                db.execute("UPDATE nodes SET summary=? WHERE scope_id='main' AND id='function'",
                           ('Stored code responsibility, revision ' + str(i),))
                call = {'source': 'sql', 'activity_id': 'call-' + str(i), 'time': 1000 + i,
                        'ok': True, 'elapsed_ms': i, 'completed': 1, 'rolled_back': False,
                        'read': ['nodes'], 'write': [],
                        'references': [{'table': 'nodes', 'scope_id': 'main', 'id': 'root', 'private': PRIVATE_SENTINEL}],
                        'returned_rows': 1,
                        'database': 'C:/private/worktree/knowledge.sqlite3', 'agent': PRIVATE_SENTINEL,
                        'chat': PRIVATE_SENTINEL, 'session': PRIVATE_SENTINEL, 'chat_title': PRIVATE_SENTINEL,
                        'session_title': PRIVATE_SENTINEL, 'identity': {'private': PRIVATE_SENTINEL},
                        'client': {'private': PRIVATE_SENTINEL}, 'error': PRIVATE_SENTINEL}
                db.execute('INSERT INTO evomneme_change_calls(activity_id,event_json) VALUES(?,?)',
                           (call['activity_id'], json.dumps(call)))
            db.execute("DELETE FROM nodes WHERE id='deleted'")
        else:
            db.execute("DELETE FROM nodes WHERE id='deleted'")


class WebsiteExportTests(unittest.TestCase):
    def temporary_directory(self):
        base = ROOT / '.evomneme-tests'
        base.mkdir(exist_ok=True)
        return tempfile.TemporaryDirectory(prefix='website-export-', dir=base)

    def export(self, path):
        with patch('export_website_demo.git_sources', return_value=VERIFIED):
            return export_publication(path, expected_identity='fixture-project')

    def test_whole_graph_all_scopes_layers_prose_and_read_only(self):
        with self.temporary_directory() as directory:
            path = Path(directory) / 'knowledge.sqlite3'
            fixture(path)
            before = path.read_bytes()
            def extra_projection(memory):
                validate_schema(memory)
                self.assertEqual(memory.execute('PRAGMA user_version').fetchone()[0], 3)
                for table in ('symbol_details', 'file_details', 'history'):
                    self.assertEqual(memory.execute('SELECT count(*) FROM ' + table).fetchone()[0], 0)
                for row in memory.execute('SELECT branch,worktree,snapshot,created_at FROM scopes'):
                    self.assertEqual(tuple(row), ('', '', '', ''))
                mapping = projection_sql(memory)
                return {key: "SELECT *, 'PRIVATE_SENTINEL' AS private_extra FROM (" + value + ')'
                        if key in ('nodes', 'edges') else value for key, value in mapping.items()}
            with patch('export_website_demo.projection_sql', side_effect=extra_projection):
                result = self.export(path)
            self.assertEqual(before, path.read_bytes())
            self.assertEqual([p.name for p in Path(directory).iterdir()], ['knowledge.sqlite3'])
            graph = result['graph']
            self.assertEqual(len(graph['nodes']), 4)
            self.assertEqual(len(graph['edges']), 2)
            self.assertEqual({n['layer'] for n in graph['nodes']}, {'knowledge', 'code', 'boundary'})
            self.assertEqual(len([n for n in graph['nodes'] if n['id'] == 'root']), 2)
            for node in graph['nodes']:
                self.assertEqual(json.loads(node['graph_id']), [node['scope_id'], node['id']])
            code = next(n for n in graph['nodes'] if n['layer'] == 'code')
            self.assertEqual(code['summary'], 'Stored code responsibility, revision 204')
            self.assertEqual(code['evidence_count'], 1)
            for edge in graph['edges']:
                self.assertEqual(edge['summary'], 'Stored relationship meaning.')
                self.assertEqual(edge['confidence'], 'inferred')
                self.assertEqual(edge['validity'], 'stale')
            self.assertNotIn(PRIVATE_SENTINEL, json.dumps(result))
            self.assertIsNone(PRIVATE.search(json.dumps(result)))
            self.assertEqual(result, self.export(path))
            self.assertEqual(len(graph['evidence']), 3)
            self.assertEqual(len(graph['symbol_details']), 1)
            self.assertEqual(len(graph['file_details']), 1)
            self.assertTrue(all('description' not in e for e in graph['evidence']))
            self.assertEqual(graph['metadata']['redacted_attachment_fields']['evidence.description'], 3)

    def test_entire_native_history_replay_and_calls_survive_sanitization(self):
        with self.temporary_directory() as directory:
            path = Path(directory) / 'knowledge.sqlite3'
            fixture(path)
            result = self.export(path)
            with closing(sqlite3.connect(path)) as db:
                changes = db.execute('SELECT id FROM evomneme_change_log ORDER BY id').fetchall()
                graph_changes = db.execute("SELECT id FROM evomneme_change_log WHERE table_name IN ('nodes','edges') ORDER BY id").fetchall()
                calls = db.execute('SELECT id FROM evomneme_change_calls ORDER BY id').fetchall()
                native = [(i, json.loads(old) if old else None, json.loads(new) if new else None)
                          for i, old, new in db.execute("SELECT id,before_json,after_json FROM evomneme_change_log WHERE table_name IN ('nodes','edges') ORDER BY id")]
            self.assertEqual([e['change_id'] for e in result['history']['changes']], [r[0] for r in changes])
            self.assertEqual([e['change_id'] for e in result['replay']['events']], [r[0] for r in graph_changes])
            self.assertEqual([e['activity_record_id'] for e in result['history']['calls']], [r[0] for r in calls])
            self.assertEqual(len(calls), 205)
            self.assertTrue(any(e['before'] and e['before']['id']['value'] == 'deleted' for e in result['replay']['events']))
            for event, (change_id, old, new) in zip(result['replay']['events'], native):
                self.assertEqual(event['change_id'], change_id)
                for field, snapshot in (('before', old), ('after', new)):
                    expected = None if snapshot is None else {k: v for k, v in snapshot.items() if k in HISTORY_COLUMNS[event['table']]}
                    self.assertEqual(event[field], expected)
            for call in result['history']['calls']:
                self.assertLessEqual(set(call), set(CALL_FIELDS))
                self.assertTrue(call['activity_id'].startswith('call-'))
                self.assertEqual(call['references'], [{'table': 'nodes', 'scope_id': 'main', 'id': 'root'}])
            for event in result['history']['changes']:
                self.assertLessEqual(set(event), set(CHANGE_FIELDS) | {'before', 'after', 'key_before', 'key_after'})
                for field in ('before', 'after', 'key_before', 'key_after'):
                    if event[field] is not None:
                        self.assertLessEqual(set(event[field]), set(HISTORY_COLUMNS[event['table']]))
            manifest = result['graph']['metadata']['history']['counts']
            self.assertEqual(manifest, {'replay_changes': len(graph_changes), 'changes': len(changes), 'calls': 205})
            initial = result['graph']['metadata']['history']['initial']
            for route, key, field in (('events', 'calls', 'activity_record_id'), ('changes', 'changes', 'change_id')):
                self.assertEqual(initial[route]['events'], result['history'][key][-100:])
                self.assertEqual(initial[route]['after_id'], result['history'][key][-1][field])
                self.assertEqual(initial[route]['before_id'], result['history'][key][-100][field])
                self.assertTrue(initial[route]['has_older'])
                self.assertFalse(initial[route]['has_more'])

    def test_source_links_require_verified_public_blob_not_analyzed_revision(self):
        revisions = {'main': REVISION}
        row = {'scope_id': 'main', 'source_path': 'src/public.py', 'source_hash': SHA256, 'line_start': 1, 'line_end': 4}
        self.assertEqual(source_url(row, revisions, VERIFIED), REPOSITORY + '/blob/' + PUBLIC_REVISION + '/src/public.py#L1-L4')
        self.assertIsNone(source_url(row, revisions, {(REVISION, 'src/public.py'): SHA256}))
        self.assertIsNone(source_url({**row, 'source_hash': '0' * 64}, revisions, VERIFIED))
        self.assertIsNone(source_url({**row, 'source_hash': None}, revisions, {}))
        self.assertIsNone(source_url({**row, 'source_path': '../private.py'}, revisions, VERIFIED))

    def test_unknown_scope_revisions_preserved_without_fabricated_links(self):
        with self.temporary_directory() as directory:
            path = Path(directory) / 'knowledge.sqlite3'
            fixture(path, history=False)
            with closing(sqlite3.connect(path)) as db, db:
                db.execute('UPDATE scopes SET revision=?', ('not-a-published-revision',))
            with patch('export_website_demo.git_sources', return_value={}):
                result = export_snapshot(path, expected_identity='fixture-project')
            self.assertEqual(len(result['nodes']), 4)
            self.assertTrue(all('source_url' not in r for r in result['nodes'] + result['edges']))
            self.assertEqual({s['revision'] for s in result['metadata']['scopes']}, {'not-a-published-revision'})
            self.assertEqual(git_sources(ROOT, ('not-a-published-revision',)), {})

    def test_public_knowledge_updates_preserved_but_credentials_rejected(self):
        with self.temporary_directory() as directory:
            path = Path(directory) / 'knowledge.sqlite3'
            fixture(path, history=False)
            with closing(sqlite3.connect(path)) as db, db:
                db.execute("UPDATE nodes SET summary='New public conclusion' WHERE scope_id='main' AND id='root'")
            graph = self.export(path)['graph']
            self.assertEqual(next(n['summary'] for n in graph['nodes'] if n['scope_id'] == 'main' and n['id'] == 'root'), 'New public conclusion')
            with closing(sqlite3.connect(path)) as db, db:
                db.execute("UPDATE nodes SET summary=? WHERE id='function'", ('password=unsafe-secret',))
            with self.assertRaisesRegex(ValueError, 'private content'):
                self.export(path)

    def test_unsupported_and_incomplete_schema_rejected_read_only(self):
        for damage, message in (("DELETE FROM metadata WHERE key='schema_version'", 'Unsupported EvoMneme schema'),
                                ('PRAGMA user_version=2', 'Unsupported EvoMneme schema'),
                                ('DROP TABLE symbol_details', 'Incompatible EvoMneme v3 table symbol_details')):
            with self.subTest(damage=damage), self.temporary_directory() as directory:
                path = Path(directory) / 'knowledge.sqlite3'
                fixture(path, history=False)
                with closing(sqlite3.connect(path)) as db, db:
                    db.execute(damage)
                before = path.read_bytes()
                with self.assertRaisesRegex(ValueError, message):
                    self.export(path)
                self.assertEqual(before, path.read_bytes())

    def test_legacy_tables_with_v3_user_version_rejected(self):
        with self.temporary_directory() as directory:
            path = Path(directory) / 'legacy.sqlite3'
            with closing(sqlite3.connect(path)) as db:
                db.executescript('CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT); CREATE TABLE records(id TEXT); PRAGMA user_version=3;')
            before = path.read_bytes()
            with self.assertRaisesRegex(ValueError, 'Unsupported EvoMneme schema'):
                self.export(path)
            self.assertEqual(before, path.read_bytes())

    def test_wrong_host_project_is_rejected_before_publication(self):
        with self.temporary_directory() as directory:
            path = Path(directory) / 'wrong-host.sqlite3'
            fixture(path, history=False)
            before = path.read_bytes()
            with self.assertRaisesRegex(ValueError, 'verified project identity'):
                export_publication(path, expected_identity='another-project')
            self.assertEqual(before, path.read_bytes())

    def test_reusable_public_revision_override_preserves_recorded_scope(self):
        with self.temporary_directory() as directory:
            path = Path(directory) / 'knowledge.sqlite3'
            fixture(path, history=False)
            published = 'b' * 40
            with patch('export_website_demo.git_sources', return_value={(published, 'src/public.py'): SHA256}):
                publication = export_publication(path, expected_identity='fixture-project', public_revision=published)
            data = publication['graph']
            self.assertEqual(data['metadata']['public_revision'], published)
            self.assertEqual({s['revision'] for s in data['metadata']['scopes']}, {REVISION})
            self.assertTrue(any('/blob/' + published + '/' in n.get('source_url', '') for n in data['nodes']))
            with self.assertRaisesRegex(ValueError, '40-character'):
                export_publication(path, expected_identity='fixture-project', public_revision='main')

    def test_cli_three_outputs_and_validation_failure_preserves_previous_export(self):
        with self.temporary_directory() as directory:
            base = Path(directory)
            path, output = base / 'knowledge.sqlite3', base / 'demo.json'
            fixture(path, history=False)
            original = path.read_bytes()
            publication = self.export(path)
            args = ['export_website_demo.py', '--database', str(path), '--output', str(output)]
            with patch.object(sys, 'argv', args), patch('export_website_demo.export_publication', return_value=publication), redirect_stdout(io.StringIO()):
                main()
            for key, name in (('graph', 'demo.json'), ('replay', 'replay.json'), ('history', 'history.json')):
                self.assertEqual((base / name).read_bytes(), encoded(publication[key]))
            previous = {p.name: p.read_bytes() for p in base.iterdir()}
            with patch.object(sys, 'argv', args + ['--public-revision', 'bad']), redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    main()
            with patch.object(sys, 'argv', args), patch('export_website_demo.export_publication', side_effect=ValueError('foreign source')):
                with self.assertRaisesRegex(ValueError, 'foreign source'):
                    main()
            with patch.object(sys, 'argv', args), patch('export_website_demo.export_publication', return_value=publication), patch('export_website_demo.encoded', side_effect=ValueError('invalid JSON')):
                with self.assertRaisesRegex(ValueError, 'invalid JSON'):
                    main()
            self.assertEqual(previous, {p.name: p.read_bytes() for p in base.iterdir()})
            self.assertEqual(original, path.read_bytes())

    def test_checked_publication_integrity_and_lazy_history_manifest(self):
        data = json.loads((ROOT / 'website/data/demo.json').read_text(encoding='utf-8'))
        replay = json.loads((ROOT / 'website/data/replay.json').read_text(encoding='utf-8'))
        timeline = json.loads((ROOT / 'website/data/history.json').read_text(encoding='utf-8'))
        self.assertEqual(data['metadata']['repository'], REPOSITORY)
        self.assertRegex(data['metadata']['public_revision'], r'^[a-f0-9]{40}$')
        self.assertGreaterEqual(len(data['nodes']), 927)
        self.assertGreaterEqual(len(data['edges']), 2055)
        ids = {n['graph_id'] for n in data['nodes']}
        self.assertEqual(len(ids), len(data['nodes']))
        self.assertEqual(len({e['graph_id'] for e in data['edges']}), len(data['edges']))
        for table, fields in (('nodes', NODE_FIELDS), ('edges', EDGE_FIELDS)):
            self.assertEqual(data['metadata']['counts'][table], len(data[table]))
            self.assertEqual(len(replay[table]), len(data[table]))
            for row in data[table]:
                self.assertLessEqual(set(row), fields | {'source_url'})
                self.assertEqual(json.loads(row['graph_id']), [row['scope_id'], row['id']])
                if 'source_url' in row:
                    self.assertTrue(row['source_url'].startswith(REPOSITORY + '/blob/' + data['metadata']['public_revision'] + '/'))
                if table == 'edges':
                    self.assertIn(row['source'], ids)
                    self.assertIn(row['target'], ids)
        graph = {k: data[k] for k in ('nodes', 'edges', 'evidence', 'symbol_details', 'file_details')}
        self.assertEqual(hashlib.sha256(json.dumps(graph, sort_keys=True, ensure_ascii=False).encode()).hexdigest(), data['metadata']['content_sha256'])
        manifest = data['metadata']['history']
        self.assertEqual(manifest['replay'], 'replay.json')
        self.assertEqual(manifest['timeline'], 'history.json')
        self.assertEqual(manifest['counts'], {'replay_changes': len(replay['events']), 'changes': len(timeline['changes']), 'calls': len(timeline['calls'])})
        for value in (data, replay, timeline):
            self.assertIsNone(PRIVATE.search(json.dumps(value)))
        self.assertGreaterEqual(len(replay['events']), 3031)
        self.assertGreaterEqual(len(timeline['changes']), 5025)
        self.assertGreaterEqual(len(timeline['calls']), 5012)
        self.assertEqual(encoded(data), (ROOT / 'website/data/demo.json').read_bytes())


if __name__ == '__main__':
    unittest.main()
