"""Synthetic saved-reference maintenance contract; never opens a host knowledge store."""
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from dataclasses import replace
import hashlib
import io
from pathlib import Path
import shlex
import sqlite3
import sys
import tempfile
import time
import types
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from evomneme_connection import Connection
from evomneme_references import ReferenceReader, ReferencesError, references, run
from evomneme_navigate import quote_command


class ReferencesTests(unittest.TestCase):
    def setUp(self):
        area = ROOT / '.evomneme-tests'
        area.mkdir(exist_ok=True)
        temporary = tempfile.TemporaryDirectory(dir=area)
        self.addCleanup(temporary.cleanup)
        self.project = Path(temporary.name).resolve()
        self.path = self.project / 'references.sqlite3'
        with self.db() as db:
            db.executescript((ROOT / 'schema.sql').read_text(encoding='utf-8'))
            db.execute("INSERT INTO metadata VALUES('project_identity','synthetic-references')")
            for scope in ('main', 'other'):
                db.execute('INSERT INTO scopes VALUES(?,?,?,?,?,?)',
                           (scope, 'branch', str(self.project), 'rev', 'snapshot', 'now'))
        self.connection = Connection(self.path, self.project, self.project, 'main', 'root', 'powershell',
                                     'synthetic-references', str(self.project), 'rev', ('freshness warning',))
        self.node('root', None)

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path)
        try:
            with db:
                yield db
        finally:
            db.close()

    def node(self, id_, path, kind='architecture', validity='current', scope='main', summary='Saved claim'):
        with self.db() as db:
            db.execute('''INSERT INTO nodes(scope_id,id,kind,title,summary,confidence,validity,
                source_path,source_hash,line_start,line_end,updated_at,layer)
                VALUES(?,?,?,?,?,'uncertain',?,?,'node-hash',3,8,'now','knowledge')''',
                       (scope, id_, kind, 'Title ' + id_, summary, validity, path))

    def edge(self, id_, source, target, path, validity='current', scope='main'):
        with self.db() as db:
            db.execute('''INSERT INTO edges(scope_id,id,source_id,target_id,kind,summary,confidence,
                validity,source_path,source_hash,line_start,line_end,updated_at,resolution)
                VALUES(?,?,?,?,'calls','Saved relationship','inferred',?,?,'edge-hash',11,12,'now','ambiguous')''',
                       (scope, id_, source, target, validity, path))

    def evidence(self, id_, path, node=None, edge=None, validity='current', scope='main'):
        with self.db() as db:
            db.execute('''INSERT INTO evidence(scope_id,id,node_id,edge_id,description,source_path,
                source_hash,validity,updated_at) VALUES(?,?,?,?,'Proof mentions line 99',?,'proof-hash',?,'now')''',
                       (scope, id_, node, edge, path, validity))

    def test_direct_dependency_context_and_all_validity_are_distinct(self):
        self.node('file', 'src/a.py', 'file', 'stale')
        self.node('symbol', 'src/a.py', validity='superseded')
        self.node('neighbor', 'src/b.py', validity='stale')
        self.node('unrelated', 'src/c.py')
        self.edge('direct', 'symbol', 'neighbor', 'src/a.py', 'stale')
        self.edge('incident', 'file', 'neighbor', 'src/b.py', 'superseded')
        self.edge('fanout', 'neighbor', 'unrelated', 'src/z.py')
        self.edge('both', 'file', 'neighbor', 'src/a.py')
        self.evidence('proof-node', 'src/a.py', node='neighbor', validity='stale')
        self.evidence('proof-edge', 'src/a.py', edge='direct', validity='superseded')
        self.evidence('not-selected', 'src/b.py', node='file')
        self.node('file', 'src/a.py', 'file', scope='other')
        self.edge('foreign-edge', 'file', 'file', 'src/a.py', scope='other')
        with self.db() as db:
            db.execute("INSERT INTO symbol_details VALUES('main','symbol','pkg.fn','fn()','python')")
            db.execute("INSERT INTO file_details(scope_id,node_id) VALUES('main','file')")
        result = references(self.connection, ['src/a.py'])
        self.assertIn('direct_nodes: 2', result)
        self.assertIn('direct_edges: 2', result)
        self.assertIn('direct_evidence: 2', result)
        self.assertIn('direct_references: 6', result)
        self.assertIn('dependent_incident_edges: 1', result)
        self.assertIn('additional_owner_context: 1', result)
        self.assertIn('group: dependent_incident_edges\ntable: edges', result)
        self.assertIn('incident to directly matched file node file', result)
        self.assertIn('owner of directly matched evidence proof-node', result)
        self.assertIn('validity: superseded', result)
        self.assertIn('validity: stale', result)
        self.assertIn('resolution: ambiguous', result)
        self.assertIn('source_hash: proof-hash', result)
        self.assertIn('symbol_details:', result)
        self.assertIn('file_details:', result)
        self.assertNotIn('fanout', result)
        self.assertNotIn('not-selected', result)
        self.assertNotIn('foreign-edge', result)
        proof = next(part for part in result.split('\n\n') if 'id: proof-edge\n' in part)
        self.assertNotIn('line_start:', proof)
        self.assertNotIn('line_end:', proof)
        # Header/footer do not add empty lines; there are eight distinct stored rows.
        self.assertEqual(result.count('\n\n'), 7)

    def test_exact_literal_union_dedup_and_safe_values(self):
        strange = '-Пример O\'Brien "x"\n\x1b[2J\u2028.py'
        self.node('special', strange, summary='first\n\ncomplete:\r\x1b[2J')
        self.node('slash', 'src\\a.py')
        self.node('case', 'Src/a.py')
        self.node('absolute', '/src/a.py')
        self.node('normal', 'src/a.py')
        one = references(self.connection, [strange, 'src/a.py'])
        self.assertEqual(one, references(self.connection, [strange, 'src/a.py', strange, 'src/a.py']))
        self.assertIn('direct_references: 2', one)
        self.assertNotIn('id: slash', one)
        self.assertNotIn('id: case', one)
        self.assertNotIn('id: absolute', one)
        self.assertNotIn('\x1b', one)
        self.assertNotIn('\u2028', one)
        self.assertIn('\\u001b', one)
        self.assertEqual(one.count('\ncomplete:\n'), 1)
        self.assertEqual(one.count('\n\n'), 1)
        empty = references(self.connection, ['missing.py'])
        self.assertIn('direct_references: 0', empty)
        self.assertIn('Zero matches do not prove absence', empty)
        self.assertIn('file-text mentions', empty)
        self.assertNotIn('\n\n', empty)
        with mock.patch('evomneme_references.OUTPUT_BYTES', 1):
            with self.assertRaises(ReferencesError) as error:
                references(self.connection, [strange])
            self.assertNotIn('\x1b', str(error.exception))
            self.assertNotIn('\u2028', str(error.exception))
            self.assertIn('preserving the original literal arguments', str(error.exception))

    def test_missing_and_stale_root_warning_preserves_freshness(self):
        for connection in (replace(self.connection, root_id='missing'), self.connection):
            with self.db() as db:
                db.execute("UPDATE nodes SET validity='stale' WHERE id='root'")
            result = references(connection, ['missing.py'])
            self.assertIn('root is missing or not current', result)
            self.assertIn('freshness warning', result)
            self.assertIn('complete:', result)

    def test_dangling_owners_and_endpoints_are_not_silently_filtered(self):
        self.edge('dangling', 'gone-source', 'gone-target', 'changed.py')
        self.evidence('orphan', 'changed.py', edge='gone-edge')
        self.evidence('node-orphan', 'changed.py', node='gone-node')
        result = references(self.connection, ['changed.py'])
        self.assertIn('direct_references: 3', result)
        self.assertIn('missing_owner_context: 4', result)
        self.assertEqual(result.count('status: missing owner/endpoint row'), 4)
        self.assertIn('Context completeness is not established', result)

    def test_evidence_owned_edge_has_its_own_locator_and_only_endpoint_context(self):
        self.node('source', 'owner-source.py', validity='superseded')
        self.node('target', 'owner-target.py', validity='stale')
        self.node('outside', 'outside.py')
        self.edge('owner-edge', 'source', 'target', 'edge-location.py', 'stale')
        self.edge('not-recursive', 'target', 'outside', 'outside.py')
        self.evidence('proof', 'changed.py', edge='owner-edge', validity='superseded')
        result = references(self.connection, ['changed.py'])
        self.assertIn('direct_references: 1', result)
        self.assertIn('additional_owner_context: 3', result)
        self.assertIn('source_path: changed.py', result)
        self.assertIn('source_path: edge-location.py', result)
        self.assertIn('source_path: owner-source.py', result)
        self.assertIn('source_path: owner-target.py', result)
        self.assertIn('owner of directly matched evidence proof', result)
        self.assertNotIn('not-recursive', result)
        self.assertNotIn('id: outside', result)

    def test_readonly_snapshot_no_history_install_or_side_effects(self):
        before = hashlib.sha256(self.path.read_bytes()).hexdigest()
        references(self.connection, ['missing.py'])
        self.assertEqual(before, hashlib.sha256(self.path.read_bytes()).hexdigest())
        with self.db() as db:
            tables = list(db.execute("SELECT name,sql FROM sqlite_schema ORDER BY name"))
            self.assertEqual(db.execute('SELECT count(*) FROM history').fetchone()[0], 0)
            db.execute('PRAGMA journal_mode=WAL')
        reader = ReferenceReader(self.connection)
        try:
            self.node('new', 'new.py')
            self.assertEqual(reader.select(['new.py'])[0]['nodes'], {})
            with self.assertRaises(sqlite3.OperationalError):
                reader.db.execute("DELETE FROM nodes")
        finally:
            reader.close()
        self.assertIn('id: new', references(self.connection, ['new.py']))
        with self.db() as db:
            self.assertEqual(tables, list(db.execute("SELECT name,sql FROM sqlite_schema ORDER BY name")))
            self.assertEqual(db.execute('SELECT count(*) FROM history').fetchone()[0], 0)

    def test_binding_schema_sqlite_and_argument_errors_are_explicit(self):
        for connection in (replace(self.connection, scope='absent'),
                           replace(self.connection, project_identity='wrong'),
                           replace(self.connection, scope_worktree='wrong')):
            with self.assertRaises(ValueError):
                references(connection, ['x'])
        for paths in ([], [''], [None]):
            with self.assertRaisesRegex(ReferencesError, 'nonempty literal'):
                references(self.connection, paths)
        with self.assertRaisesRegex(ReferencesError, 'Cannot read bound references'):
            references(replace(self.connection, database=self.project / 'absent.db'), ['x'])
        with self.db() as db:
            db.execute('PRAGMA user_version=999')
        with self.assertRaisesRegex(ValueError, 'Unsupported'):
            references(self.connection, ['x'])

    def test_output_guard_exact_utf8_bytes_retry_all_and_deadline(self):
        path = '-Отправка O\'Brien.py'
        self.node('unicode', path, summary='📦\n\ncomplete:')
        expected = references(self.connection, [path])
        size = len(expected.encode('utf-8'))
        with mock.patch('evomneme_references.OUTPUT_BYTES', size):
            self.assertEqual(references(self.connection, [path]), expected)
        with mock.patch('evomneme_references.OUTPUT_BYTES', size - 1):
            with self.assertRaisesRegex(ReferencesError, 'no result emitted') as error:
                references(self.connection, [path])
            self.assertIn(quote_command(['evomneme', 'references', '--all', '--', path], 'powershell'), str(error.exception))
            self.assertNotIn('python', str(error.exception))
            self.assertEqual(references(self.connection, [path], all_output=True), expected)
        self.assertEqual(shlex.split(quote_command(['evomneme', 'references', '--all', '--', path], 'posix'))[-1], path)
        with self.assertRaisesRegex(ReferencesError, 'timed out'):
            references(self.connection, [path], timeout=0, all_output=True)
        original = ReferenceReader.card

        def slow(reader, *args):
            time.sleep(.025)
            return original(reader, *args)

        with mock.patch.object(ReferenceReader, 'card', slow):
            with self.assertRaisesRegex(ReferencesError, 'timed out'):
                references(self.connection, [path], timeout=.01, all_output=True)

    def test_cli_stdout_is_atomic_utf8_and_dash_path_is_literal(self):
        from evomneme_cli import main
        self.node('dash', '-📦.py')
        expected = references(self.connection, ['-📦.py'])
        stream = io.BytesIO()
        with mock.patch('evomneme_connection.discover', return_value=self.connection), \
                mock.patch('sys.stdout', types.SimpleNamespace(buffer=stream)):
            self.assertEqual(main(['references', '--', '-📦.py']), 0)
        self.assertEqual(stream.getvalue(), expected.encode('utf-8'))
        stdout, stderr = io.StringIO(), io.StringIO()
        with mock.patch('evomneme_connection.discover', return_value=self.connection), \
                mock.patch('evomneme_references.OUTPUT_BYTES', 1), redirect_stdout(stdout), redirect_stderr(stderr):
            self.assertEqual(main(['references', '--', '-📦.py']), 1)
        self.assertEqual(stdout.getvalue(), '')
        self.assertIn('no result emitted', stderr.getvalue())
        self.assertEqual(run(self.connection, types.SimpleNamespace(paths=['-📦.py'], all_output=False)), expected)

    def test_many_literal_paths_do_not_exceed_sqlite_variable_limit(self):
        self.node('selected', 'last.py')
        paths = ['missing-' + str(index) for index in range(1100)] + ['last.py']
        result = references(self.connection, paths, all_output=True)
        self.assertIn('id: selected', result)
        self.assertIn('direct_references: 1', result)


if __name__ == '__main__':
    unittest.main()
