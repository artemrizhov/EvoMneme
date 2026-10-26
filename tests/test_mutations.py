"""Synthetic bound graph writes, atomic history and patch semantics."""
from contextlib import closing, redirect_stderr, redirect_stdout
from dataclasses import replace
import io
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from evomneme_connection import Connection
from evomneme_cli import main
from evomneme_journal import CALLS, LOG, META, install
from evomneme_mutate import TABLE_COLUMNS, delete, mutate
from evomneme import Executor
from evomneme_navigate import navigate, qualified


class MutationTests(unittest.TestCase):
    def setUp(self):
        area = ROOT / '.evomneme-tests'
        area.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=area)
        self.addCleanup(self.temp.cleanup)
        project = Path(self.temp.name).resolve()
        self.path = project / 'synthetic.sqlite3'
        with closing(sqlite3.connect(self.path)) as db, db:
            db.executescript((ROOT / 'schema.sql').read_text(encoding='utf-8'))
            db.execute("INSERT INTO metadata VALUES('project_identity','synthetic-write')")
            for scope in ('main', 'other'):
                db.execute('INSERT INTO scopes VALUES(?,?,?,?,?,?)', (scope, 'branch', str(project), 'rev', 'snap', 'now'))
            db.execute("INSERT INTO nodes(scope_id,id,kind,title,summary,confidence,validity,updated_at) VALUES('main','root-id','project','Project','Synthetic project','confirmed','current','now')")
        self.connection = Connection(self.path, project, project, 'main', 'root-id', 'posix',
                                     'synthetic-write', str(project), 'rev')

    def query(self, sql, params=()):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.row_factory = sqlite3.Row
            return [dict(row) for row in db.execute(sql, params)]

    def add_node(self, id_='n', **values):
        return mutate(self.connection, 'add', 'node', dict(id=id_, kind='function', title=id_,
                      summary='Synthetic behavior', confidence='confirmed', **values))

    def test_add_and_patch_all_record_types_with_history(self):
        self.add_node(source_path='src.py', source_hash='h', line_start=2, line_end=6)
        edge = dict(id='e', kind='calls', summary='Direct call', confidence='inferred')
        mutate(self.connection, 'add', 'edge', edge, source='root', target='n')
        mutate(self.connection, 'add', 'evidence', dict(id='p', node_id='n', description='Observed'))
        mutate(self.connection, 'update', 'node', {'summary': 'Verified'}, selector='n')
        row = self.query("SELECT * FROM nodes WHERE id='n'")[0]
        self.assertEqual((row['source_path'], row['line_start'], row['line_end'], row['title']), ('src.py', 2, 6, 'n'))
        mutate(self.connection, 'update', 'edge', {'resolution': 'unresolved', 'layer': 'code'}, selector='e')
        mutate(self.connection, 'update', 'evidence', {'edge_id': 'e'}, selector='p')
        row = self.query("SELECT * FROM evidence WHERE id='p'")[0]
        self.assertIsNone(row['node_id'])
        self.assertEqual(row['edge_id'], 'e')
        mutate(self.connection, 'update', 'evidence', {'node_id': 'n'}, selector='p')
        logs = self.query('SELECT * FROM ' + LOG)
        calls = self.query('SELECT * FROM ' + CALLS)
        self.assertEqual(len(logs), 7)
        self.assertEqual(len(calls), 7)
        self.assertEqual({row['activity_id'] for row in logs}, {row['activity_id'] for row in calls})
        event = json.loads(calls[-1]['event_json'])
        self.assertEqual((event['source'], event['entity'], event['id'], event['write']), ('graph-cli', 'evidence', 'p', ['evidence']))
        self.assertTrue(row['updated_at'].endswith('Z'))

    def test_nullable_clears_and_final_merged_line_range(self):
        self.add_node(source_path='src.py', line_start=2, line_end=6)
        for values, clear in (({'line_start': 7}, ()), ({}, ('line_start',)),
                              ({'source_path': 'x'}, ('source_path',)), ({}, ('title',)),
                              ({}, ('source_hash', 'source_hash'))):
            with self.subTest(values=values, clear=clear), self.assertRaises(ValueError):
                mutate(self.connection, 'update', 'node', values, selector='n', clear=clear)
        mutate(self.connection, 'update', 'node', {}, selector='n', clear=('line_start', 'line_end', 'source_path'))
        row = self.query("SELECT * FROM nodes WHERE id='n'")[0]
        self.assertIsNone(row['line_start'])
        self.assertIsNone(row['source_path'])
        self.assertEqual(row['summary'], 'Synthetic behavior')

    def test_exact_stale_ids_ambiguity_and_foreign_scope(self):
        self.add_node('old', validity='stale')
        mutate(self.connection, 'update', 'node', {'validity': 'superseded'}, selector='old')
        self.add_node('n')
        mutate(self.connection, 'update', 'node', {'title': 'old'}, selector='n')
        with self.assertRaisesRegex(ValueError, 'Ambiguous'):
            mutate(self.connection, 'update', 'node', {'summary': 'x'}, selector='old')
        mutate(self.connection, 'update', 'node', {'summary': 'Maintained'}, selector=qualified('main', 'old'))
        with self.assertRaisesRegex(ValueError, 'another scope'):
            mutate(self.connection, 'add', 'edge', dict(id='e', kind='calls', summary='x', confidence='uncertain'), source='root', target=qualified('other', 'n'))
        with self.assertRaises(ValueError):
            mutate(self.connection, 'add', 'evidence', dict(id='p', node_id='Project', description='x'))

    def test_invalid_or_empty_updates_preserve_rows(self):
        self.add_node()
        before = self.query("SELECT * FROM nodes WHERE id='n'")
        for values in ({}, {'summary': 'Synthetic behavior'}, {'validity': 'invalid'}, {'id': 'new'},
                       {'scope_id': 'other'}, {'updated_at': 'now'}, {'unknown': 'x'}, {'line_start': 0}):
            with self.subTest(values=values), self.assertRaises(ValueError):
                mutate(self.connection, 'update', 'node', values, selector='n')
        self.assertEqual(before, self.query("SELECT * FROM nodes WHERE id='n'"))
        with self.assertRaisesRegex(ValueError, 'root must remain current'):
            mutate(self.connection, 'update', 'node', {'validity': 'stale'}, selector='root')

    def test_wrong_binding_never_installs_history(self):
        with self.assertRaises(ValueError):
            mutate(replace(self.connection, project_identity='wrong'), 'add', 'node',
                   dict(id='n', kind='file', title='n', summary='x', confidence='confirmed'))
        self.assertFalse(self.query("SELECT name FROM sqlite_schema WHERE name LIKE 'evomneme_change_%'"))

    def test_standalone_locked_transaction_failure_is_clean_and_closes_executor(self):
        created = []
        def short_wait(*args, **kwargs):
            executor = Executor(*args, **kwargs)
            executor.connection.execute('PRAGMA busy_timeout=1')
            created.append(executor)
            return executor
        with closing(sqlite3.connect(self.path, isolation_level=None)) as lock:
            lock.execute('BEGIN IMMEDIATE')
            with mock.patch('evomneme_mutate.Executor', side_effect=short_wait):
                with self.assertRaisesRegex(ValueError, 'Cannot open bound graph transaction:.*locked'):
                    self.add_node()
                stdout, stderr = io.StringIO(), io.StringIO()
                with mock.patch('evomneme_connection.discover', return_value=self.connection), redirect_stdout(stdout), redirect_stderr(stderr):
                    result = main(['delete', 'node', 'root'])
                self.assertEqual((result, stdout.getvalue()), (1, ''))
                self.assertIn('locked', stderr.getvalue())
                self.assertNotIn('Traceback', stderr.getvalue())
            lock.execute('ROLLBACK')
        self.assertEqual(len(created), 2)
        self.assertTrue(all(executor.closed for executor in created))
        self.assertFalse(self.query("SELECT name FROM sqlite_schema WHERE name=?", (LOG,)))

    def test_standalone_malformed_database_constructor_error_is_clean(self):
        self.path.write_bytes(b'Synthetic malformed SQLite fixture')
        stdout, stderr = io.StringIO(), io.StringIO()
        with mock.patch('evomneme_connection.discover', return_value=self.connection), redirect_stdout(stdout), redirect_stderr(stderr):
            result = main(['delete', 'node', 'root'])
        self.assertEqual((result, stdout.getvalue()), (1, ''))
        self.assertIn('Cannot open bound graph transaction', stderr.getvalue())
        self.assertNotIn('Traceback', stderr.getvalue())

    def test_preexisting_root_gap_warns_until_explicit_repair(self):
        self.add_node()
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("UPDATE nodes SET validity='stale' WHERE id='root-id'")
        output = mutate(self.connection, 'update', 'node', {'summary': 'Maintenance'}, selector='n')
        self.assertIn('ordinary navigation remains unavailable', output)
        output = mutate(self.connection, 'update', 'node', {'summary': 'Root maintenance'}, selector='root')
        self.assertIn('ordinary navigation remains unavailable', output)
        with self.assertRaises(ValueError):
            navigate(self.connection, 'nodes', ['root'])
        output = mutate(self.connection, 'update', 'node', {'validity': 'current'}, selector='root')
        self.assertNotIn('ordinary navigation remains unavailable', output)
        self.assertIn('title: Project', navigate(self.connection, 'nodes', ['root']))
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("DELETE FROM nodes WHERE id='root-id'")
        output = mutate(self.connection, 'update', 'node', {'summary': 'More maintenance'}, selector='n')
        self.assertIn('ordinary navigation remains unavailable', output)
        output = self.add_node('root-id')
        self.assertNotIn('ordinary navigation remains unavailable', output)
        self.assertIn('title: root-id', navigate(self.connection, 'nodes', ['root']))

    def test_evidence_attachments_and_endpoint_references_are_scoped(self):
        self.add_node()
        for attachment in ({}, {'node_id': 'n', 'edge_id': 'missing'}, {'edge_id': 'missing'}):
            with self.subTest(attachment=attachment), self.assertRaises(ValueError):
                mutate(self.connection, 'add', 'evidence', dict(id='p', description='Observed', **attachment))
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("INSERT INTO nodes(scope_id,id,kind,title,summary,confidence,validity,updated_at) VALUES('other','foreign','file','Foreign','x','confirmed','current','now')")
        for entity, values in (('evidence', dict(id='p', node_id='foreign', description='x')),
                               ('edge', dict(id='e', kind='calls', summary='x', confidence='confirmed'))):
            with self.subTest(entity=entity), self.assertRaises(ValueError):
                mutate(self.connection, 'add', entity, values, source='root', target='foreign')
        self.assertFalse(self.query("SELECT * FROM evidence WHERE id='p'"))
        self.assertFalse(self.query("SELECT * FROM edges WHERE id='e'"))

    def test_failure_rolls_back_graph_and_new_history(self):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("CREATE TRIGGER reject_node AFTER INSERT ON nodes BEGIN SELECT RAISE(ABORT,'synthetic failure'); END")
        with self.assertRaisesRegex(ValueError, 'synthetic failure'):
            self.add_node()
        self.assertFalse(self.query("SELECT * FROM nodes WHERE id='n'"))
        self.assertFalse(self.query("SELECT name FROM sqlite_schema WHERE name LIKE 'evomneme_change_%'"))

    def test_activity_failure_rolls_back_graph_and_history(self):
        install(self.path)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('CREATE TRIGGER reject_activity BEFORE INSERT ON ' + CALLS + " BEGIN SELECT RAISE(ABORT,'activity failure'); END")
        with self.assertRaisesRegex(ValueError, 'activity failure'):
            self.add_node()
        self.assertFalse(self.query("SELECT * FROM nodes WHERE id='n'"))
        self.assertFalse(self.query('SELECT * FROM ' + LOG))

    def test_output_budget_rolls_back_everything(self):
        with self.assertRaisesRegex(ValueError, 'output exceeds'):
            mutate(self.connection, 'add', 'node', dict(id='large', kind='file', title='Large',
                   summary='x' * 65536, confidence='confirmed'))
        self.assertFalse(self.query("SELECT * FROM nodes WHERE id='large'"))
        self.assertFalse(self.query("SELECT name FROM sqlite_schema WHERE name=?", (LOG,)))

    def test_standalone_and_caller_installer_ownership(self):
        db = sqlite3.connect(self.path, isolation_level=None)
        self.addCleanup(db.close)
        with self.assertRaisesRegex(ValueError, 'active caller transaction'):
            install(self.path, connection=db)
        db.execute('BEGIN IMMEDIATE')
        install(self.path, connection=db)
        self.assertTrue(db.in_transaction)
        db.execute('ROLLBACK')
        self.assertFalse(self.query("SELECT name FROM sqlite_schema WHERE name=?", (LOG,)))
        self.assertTrue(install(self.path)['enabled'])
        self.assertTrue(install(self.path)['activity_enabled'])
        db.execute('BEGIN IMMEDIATE')
        with self.assertRaisesRegex(ValueError, 'does not match'):
            install(ROOT / 'schema.sql', connection=db)
        self.assertTrue(db.in_transaction)
        db.execute('ROLLBACK')

    def test_installer_failure_preserves_caller_transaction_with_savepoint(self):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('CREATE TABLE ' + CALLS + '(unowned TEXT)')
        db = sqlite3.connect(self.path, isolation_level=None)
        self.addCleanup(db.close)
        db.execute('BEGIN IMMEDIATE')
        db.execute("UPDATE nodes SET summary='Caller work' WHERE id='root-id'")
        with self.assertRaisesRegex(ValueError, 'Reserved activity table'):
            install(self.path, connection=db)
        self.assertTrue(db.in_transaction)
        self.assertEqual(db.execute("SELECT summary FROM nodes WHERE id='root-id'").fetchone()[0], 'Caller work')
        db.execute('ROLLBACK')
        self.assertFalse(self.query("SELECT name FROM sqlite_schema WHERE name=?", (LOG,)))

    def test_suspended_history_is_preserved(self):
        install(self.path)
        install(self.path, suspend=True)
        with self.assertRaisesRegex(ValueError, 'suspended'):
            self.add_node()
        self.assertEqual(self.query('SELECT value FROM ' + META + " WHERE key='enabled'")[0]['value'], '0')

    def test_bound_values_and_terminal_controls_and_navigation(self):
        literal = "x'); DROP TABLE nodes;--\n\n\x1b[31m"
        output = self.add_node(literal, source_path='literal\npath')
        self.assertNotIn('\x1b', output)
        self.assertNotIn('\n\n', output.split('\nwarning:')[0])
        self.assertIn('\\u001b', output)
        self.assertEqual(self.query('SELECT summary FROM nodes WHERE id=?', (literal,))[0]['summary'], 'Synthetic behavior')
        self.assertIn('title: Project', navigate(self.connection, 'nodes', ['root']))
        deleted = delete(self.connection, 'node', qualified('main', literal))
        self.assertNotIn('\x1b', deleted)
        self.assertIn('\\u001b', deleted)
        self.assertFalse(self.query('SELECT * FROM nodes WHERE id=?', (literal,)))

    def delete_fixture(self):
        self.add_node('owner')
        self.add_node('neighbor', validity='stale')
        for id_, source, target in (('one', 'owner', 'neighbor'), ('two', 'owner', 'neighbor'), ('self', 'owner', 'owner')):
            mutate(self.connection, 'add', 'edge', dict(id=id_, kind='contains', summary='Synthetic edge', confidence='confirmed', validity='superseded'), source=source, target=target)
        mutate(self.connection, 'add', 'evidence', dict(id='node-proof', node_id='owner', description='Node proof', validity='stale'))
        for id_ in ('one', 'two', 'self'):
            mutate(self.connection, 'add', 'evidence', dict(id=id_ + '-proof', edge_id=id_, description='Edge proof'))
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("INSERT INTO symbol_details(scope_id,node_id,qualified_name) VALUES('main','owner','Owner')")
            db.execute("INSERT INTO file_details(scope_id,node_id) VALUES('main','owner')")
            db.execute("INSERT INTO nodes(scope_id,id,kind,title,summary,confidence,validity,updated_at) VALUES('other','owner','file','owner','Other scope','confirmed','current','now')")

    def test_delete_node_restrict_counts_and_exact_cascade_history(self):
        self.delete_fixture()
        before = len(self.query('SELECT * FROM ' + LOG))
        with self.assertRaisesRegex(ValueError, r'evidence=4.*edges=3.*symbol_details=1.*file_details=1.*--cascade'):
            delete(self.connection, 'node', 'owner')
        self.assertEqual(len(self.query('SELECT * FROM ' + LOG)), before)
        output = delete(self.connection, 'node', 'owner', cascade=True)
        for field, count in (('evidence', 4), ('edges', 3), ('symbol_details', 1), ('file_details', 1), ('nodes', 1)):
            self.assertIn(field + ': ' + str(count), output)
        self.assertTrue(self.query("SELECT * FROM nodes WHERE id='neighbor'"))
        self.assertEqual(len(self.query("SELECT * FROM nodes WHERE id='owner'")), 1)
        self.assertEqual(self.query("SELECT * FROM nodes WHERE id='owner'")[0]['scope_id'], 'other')
        deleted = self.query('SELECT * FROM ' + LOG + " WHERE operation='delete'")
        self.assertEqual(len(deleted), 10)
        activity = json.loads(self.query('SELECT event_json FROM ' + CALLS + ' ORDER BY id DESC LIMIT 1')[0]['event_json'])
        self.assertEqual(activity['deleted_counts'], dict(evidence=4, edges=3, symbol_details=1, file_details=1, nodes=1))
        self.assertEqual({row['activity_id'] for row in deleted}, {activity['activity_id']})
        self.assertTrue(self.query('SELECT * FROM evomneme_change_elements WHERE phase=\'before\''))
        self.assertIn('title: Project', navigate(self.connection, 'nodes', ['root']))

    def test_delete_edge_restrict_cascade_and_evidence_single_row(self):
        self.delete_fixture()
        with self.assertRaisesRegex(ValueError, 'evidence=1.*--cascade'):
            delete(self.connection, 'edge', 'one')
        output = delete(self.connection, 'evidence', 'one-proof')
        self.assertIn('evidence: 1', output)
        self.assertTrue(self.query("SELECT * FROM edges WHERE id='one'"))
        delete(self.connection, 'edge', 'one')
        output = delete(self.connection, 'edge', 'two', cascade=True)
        self.assertIn('evidence: 1', output)
        self.assertIn('edges: 1', output)
        self.assertTrue(self.query("SELECT * FROM edges WHERE id='self'"))
        self.assertTrue(self.query("SELECT * FROM nodes WHERE id='owner' AND scope_id='main'"))

    def test_delete_root_always_forbidden_before_history_setup(self):
        for validity in ('current', 'stale', 'superseded'):
            with closing(sqlite3.connect(self.path)) as db, db:
                db.execute('UPDATE nodes SET validity=? WHERE id=?', (validity, 'root-id'))
            for cascade in (False, True):
                with self.assertRaisesRegex(ValueError, 'Configured root cannot be deleted'):
                    delete(self.connection, 'node', 'root', cascade=cascade)
        self.assertFalse(self.query("SELECT name FROM sqlite_schema WHERE name=?", (LOG,)))

    def test_delete_ambiguous_foreign_and_historical_selectors(self):
        self.add_node('old', validity='stale')
        self.add_node('other')
        mutate(self.connection, 'update', 'node', {'title': 'old'}, selector='other')
        with self.assertRaisesRegex(ValueError, 'Ambiguous'):
            delete(self.connection, 'node', 'old')
        with self.assertRaisesRegex(ValueError, 'another scope'):
            delete(self.connection, 'node', qualified('other', 'old'))
        delete(self.connection, 'node', qualified('main', 'old'))
        self.assertFalse(self.query("SELECT * FROM nodes WHERE id='old'"))
        self.assertTrue(self.query("SELECT * FROM nodes WHERE id='other'"))

    def test_delete_external_cascade_fk_is_restricted(self):
        self.add_node()
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('CREATE TABLE extra(scope TEXT, parent TEXT, FOREIGN KEY(scope,parent) REFERENCES nodes(scope_id,id) ON DELETE CASCADE)')
            db.execute("INSERT INTO extra VALUES('main','n')")
        before = len(self.query('SELECT * FROM ' + LOG))
        for cascade in (False, True):
            with self.assertRaisesRegex(ValueError, 'External foreign key dependency'):
                delete(self.connection, 'node', 'n', cascade=cascade)
        self.assertTrue(self.query("SELECT * FROM nodes WHERE id='n'"))
        self.assertTrue(self.query('SELECT * FROM extra'))
        self.assertEqual(len(self.query('SELECT * FROM ' + LOG)), before)

    def test_delete_trigger_failure_rolls_back_closure_and_history(self):
        self.delete_fixture()
        before = len(self.query('SELECT * FROM ' + LOG))
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("CREATE TRIGGER reject_delete BEFORE DELETE ON nodes BEGIN SELECT RAISE(ABORT,'delete failure'); END")
        with self.assertRaisesRegex(ValueError, 'delete failure'):
            delete(self.connection, 'node', 'owner', cascade=True)
        self.assertEqual(len(self.query('SELECT * FROM ' + LOG)), before)
        self.assertEqual(len(self.query('SELECT * FROM edges')), 3)
        self.assertEqual(len(self.query('SELECT * FROM evidence')), 4)

    def test_delete_unknown_fk_without_matching_rows_and_root_gap_warning(self):
        self.add_node()
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('CREATE TABLE extra(scope TEXT, parent TEXT, FOREIGN KEY(scope,parent) REFERENCES nodes(scope_id,id) ON DELETE CASCADE)')
            db.execute("UPDATE nodes SET validity='stale' WHERE id='root-id'")
        output = delete(self.connection, 'node', 'n')
        self.assertIn('ordinary navigation remains unavailable', output)

    def test_delete_output_and_activity_failures_roll_back(self):
        self.add_node()
        before = len(self.query('SELECT * FROM ' + LOG))
        with self.assertRaisesRegex(ValueError, 'output exceeds'):
            delete(replace(self.connection, warnings=('x' * 65536,)), 'node', 'n')
        self.assertTrue(self.query("SELECT * FROM nodes WHERE id='n'"))
        self.assertEqual(len(self.query('SELECT * FROM ' + LOG)), before)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('CREATE TRIGGER reject_delete_activity BEFORE INSERT ON ' + CALLS + " BEGIN SELECT RAISE(ABORT,'delete activity failure'); END")
        with self.assertRaisesRegex(ValueError, 'delete activity failure'):
            delete(self.connection, 'node', 'n')
        self.assertTrue(self.query("SELECT * FROM nodes WHERE id='n'"))
        self.assertEqual(len(self.query('SELECT * FROM ' + LOG)), before)

    def test_delete_collateral_trigger_count_or_root_change_rolls_back(self):
        self.add_node()
        self.add_node('neighbor')
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("CREATE TRIGGER delete_neighbor AFTER DELETE ON nodes WHEN OLD.id='n' BEGIN DELETE FROM nodes WHERE id='neighbor' AND scope_id='main'; END")
        with self.assertRaisesRegex(ValueError, 'counts differ'):
            delete(self.connection, 'node', 'n')
        self.assertTrue(self.query("SELECT * FROM nodes WHERE id='neighbor'"))
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('DROP TRIGGER delete_neighbor')
            db.execute("CREATE TRIGGER invalidate_root AFTER DELETE ON nodes BEGIN UPDATE nodes SET validity='stale' WHERE id='root-id'; END")
        with self.assertRaisesRegex(ValueError, 'root cannot be deleted or invalidated'):
            delete(self.connection, 'node', 'n')
        self.assertEqual(self.query("SELECT validity FROM nodes WHERE id='root-id'")[0]['validity'], 'current')

    def test_delete_balanced_collateral_trigger_writes_roll_back(self):
        self.add_node()
        self.add_node('neighbor')
        before = self.query('SELECT * FROM nodes ORDER BY scope_id,id')
        log_count = len(self.query('SELECT * FROM ' + LOG))
        for replacement in ('replacement', 'neighbor'):
            with self.subTest(replacement=replacement):
                with closing(sqlite3.connect(self.path)) as db, db:
                    db.execute("CREATE TRIGGER balanced_delete AFTER DELETE ON nodes WHEN OLD.id='n' BEGIN "
                               "DELETE FROM nodes WHERE scope_id='main' AND id='neighbor'; "
                               "INSERT INTO nodes(scope_id,id,kind,title,summary,confidence,validity,updated_at) "
                               "VALUES('main','" + replacement + "','file','Replacement','Altered','confirmed','current','now'); END")
                with self.assertRaisesRegex(ValueError, 'Unexpected graph insert/update'):
                    delete(self.connection, 'node', 'n')
                self.assertEqual(self.query('SELECT * FROM nodes ORDER BY scope_id,id'), before)
                self.assertEqual(len(self.query('SELECT * FROM ' + LOG)), log_count)
                with closing(sqlite3.connect(self.path)) as db, db:
                    db.execute('DROP TRIGGER balanced_delete')

    def test_delete_activity_trigger_cannot_mutate_graph_after_validation(self):
        self.add_node()
        self.add_node('neighbor')
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('CREATE TRIGGER activity_graph_write AFTER INSERT ON ' + CALLS
                       + " BEGIN UPDATE nodes SET summary='Unexpected' WHERE id='neighbor'; END")
        with self.assertRaisesRegex(ValueError, 'Unexpected graph insert/update'):
            delete(self.connection, 'node', 'n')
        self.assertTrue(self.query("SELECT * FROM nodes WHERE id='n'"))
        self.assertEqual(self.query("SELECT summary FROM nodes WHERE id='neighbor'")[0]['summary'], 'Synthetic behavior')

    def test_cli_missing_control_id_errors_are_safe(self):
        stdout, stderr = io.StringIO(), io.StringIO()
        with mock.patch('evomneme_connection.discover', return_value=self.connection), redirect_stdout(stdout), redirect_stderr(stderr):
            result = main(['delete', 'node', 'missing\n\n\x1b[31m'])
        self.assertEqual(result, 1)
        self.assertEqual(stdout.getvalue(), '')
        self.assertNotIn('\x1b', stderr.getvalue())
        self.assertNotIn('\n\n', stderr.getvalue())
        self.assertIn('\\u001b', stderr.getvalue())

    def test_delete_wrong_binding_and_restrict_create_no_history(self):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("INSERT INTO nodes(scope_id,id,kind,title,summary,confidence,validity,updated_at) VALUES('main','n','file','N','x','confirmed','current','now')")
            db.execute("INSERT INTO file_details(scope_id,node_id) VALUES('main','n')")
        with self.assertRaises(ValueError):
            delete(replace(self.connection, project_identity='wrong'), 'node', 'n', cascade=True)
        with self.assertRaisesRegex(ValueError, 'file_details=1.*--cascade'):
            delete(self.connection, 'node', 'n')
        self.assertFalse(self.query("SELECT name FROM sqlite_schema WHERE name=?", (LOG,)))

    def test_delete_help_and_unknown_flags(self):
        for entity in TABLE_COLUMNS:
            stdout = io.StringIO()
            with redirect_stdout(stdout), self.assertRaises(SystemExit):
                main(['delete', entity, '--help'])
            text = ' '.join(stdout.getvalue().split())
            self.assertIn('Physically delete', text)
            self.assertIn('preserving released row/activity history', text)
            self.assertIn('Configured root cannot be deleted', text)
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            main(['delete', 'evidence', 'proof', '--cascade'])

    def test_help_lists_every_mutable_field_and_cli_failure_is_stderr(self):
        for action in ('add', 'update'):
            for entity, columns in TABLE_COLUMNS.items():
                stdout = io.StringIO()
                with redirect_stdout(stdout), self.assertRaises(SystemExit) as raised:
                    main([action, entity, '--help'])
                self.assertEqual(raised.exception.code, 0)
                help_ = stdout.getvalue()
                for column in columns:
                    self.assertIn(column, help_)
                normalized = ' '.join(help_.split())
                self.assertIn('updated_at is managed UTC', normalized)
                self.assertIn('Empty text is literal text, not NULL', normalized)
                if action == 'add':
                    self.assertIn('Add default: NULL.', normalized)
                else:
                    self.assertIn('Omitted fields retain their values', normalized)
                if entity == 'evidence':
                    self.assertIn(('Evidence requires exactly one of --node_id or --edge_id.' if action == 'add' else
                                   'Evidence final stored row requires exactly one attachment; omitted flags retain the parent.'), normalized)
        stdout, stderr = io.StringIO(), io.StringIO()
        with mock.patch('evomneme_connection.discover', return_value=self.connection), redirect_stdout(stdout), redirect_stderr(stderr):
            result = main(['update', 'node', 'root', '--validity', 'stale'])
        self.assertEqual(result, 1)
        self.assertEqual(stdout.getvalue(), '')
        self.assertIn('root must remain current', stderr.getvalue())
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            main(['update', 'node', 'root', '--summary', 'one', '--summary', 'two'])


if __name__ == '__main__':
    unittest.main()
