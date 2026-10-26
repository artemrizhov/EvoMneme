"""Automatic history uses only synthetic local v3 databases."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, redirect_stderr
import io
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
from evomneme import Executor
from evomneme_journal import CALLS, LOG, META, install, read, read_calls
from evomneme_trace import configure_trace
from evomneme_viewer import Explorer


class AutomaticHistoryTests(unittest.TestCase):
    def setUp(self):
        area = ROOT / '.evomneme-tests'
        area.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=area)
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'synthetic.sqlite3'
        with closing(sqlite3.connect(self.path)) as db:
            db.executescript((ROOT / 'schema.sql').read_text())
            db.execute("INSERT INTO scopes VALUES('s','branch','fixture','r','snapshot','now')")
            db.commit()

    def executor(self, **options):
        value = Executor(self.path, **options)
        self.addCleanup(value.close)
        return value

    def viewer(self, **options):
        value = Explorer(self.path, **options)
        self.addCleanup(value.close)
        return value

    def node(self, executor, id='n', **options):
        return executor.execute_sql(sql="INSERT INTO nodes(scope_id,id,kind,title,summary,confidence,validity,updated_at) VALUES('s',?,'function','title','summary','inferred','current','now')", params=[id], **options)

    def test_defaults_persist_and_link_changes_without_returning(self):
        ex = self.executor()
        result = self.node(ex, activity_context={'chat_id':'chat','session_id':'session','agent_id':'worker','agent_name':'Worker'})
        self.assertTrue(result['ok'], result)
        self.assertEqual(result['results'][0]['affected_rows'], 1)
        ex.execute_sql(sql='SELECT scope_id,id FROM nodes')
        ex.close()
        viewer = self.viewer()
        calls = viewer.events({})
        changes = viewer.changes({})['events']
        self.assertEqual(len(calls['events']), 2)
        self.assertTrue(calls['enabled'])
        self.assertEqual(calls['storage'], 'database')
        self.assertEqual(changes[0]['activity_id'], calls['events'][0]['activity_id'])
        self.assertEqual(changes[0]['agent_name'], 'Worker')
        self.assertEqual(calls['events'][0]['references'], [])
        self.assertEqual(calls['events'][0]['write'], ['nodes'])
        self.assertEqual(calls['events'][1]['read'], ['nodes'])
        self.assertEqual(calls['events'][1]['chat'], None)
        self.assertFalse(calls['events'][1]['identity']['chat'])
        self.assertEqual(calls['events'][1]['client']['name'], 'EvoMneme Python')
        self.assertEqual(self.viewer().events({})['events'], calls['events'])

    def test_external_writes_unknown_and_context_never_leaks(self):
        ex = self.executor()
        self.node(ex, 'first', activity_context={'chat_id':'one','agent_id':'a'})
        with closing(sqlite3.connect(self.path)) as db:
            db.execute("UPDATE nodes SET title='external'")
            db.commit()
        self.node(ex, 'second', activity_context={'chat_id':'two','agent_id':'b'})
        self.node(ex, 'third')
        changes = self.viewer().changes({})['events']
        self.assertEqual(changes[0]['chat'], 'one')
        self.assertNotIn('activity_id', changes[1])
        self.assertEqual(changes[2]['chat'], 'two')
        self.assertIsNone(changes[3]['chat'])
        with closing(sqlite3.connect(self.path)) as db:
            sql = ' '.join(row[0] for row in db.execute("SELECT sql FROM sqlite_schema WHERE type='trigger'"))
            self.assertNotIn('evomneme_history_mutation', sql)
            self.assertNotIn('evomneme_activity_scope', sql)

    def test_query_only_toggle_does_not_leave_prior_attribution(self):
        ex = self.executor()
        with redirect_stderr(io.StringIO()) as diagnostic:
            self.assertTrue(ex.execute_sql(sql='PRAGMA query_only=ON', activity_context={'chat_id':'old'})['ok'])
            self.assertTrue(ex.execute_sql(sql='SELECT 1')['ok'])
            self.assertTrue(ex.execute_sql(sql='PRAGMA query_only=OFF')['ok'])
            self.assertTrue(self.node(ex, activity_context={'chat_id':'new'})['ok'])
        self.assertEqual(self.viewer().changes({})['events'][-1]['chat'], 'new')
        self.assertEqual(diagnostic.getvalue(), '')

    def test_native_rollback_savepoint_noop_and_partial_durability(self):
        ex = self.executor()
        self.node(ex)
        result = ex.execute_sql(sql=[{'sql':'BEGIN'}, {'sql':"UPDATE nodes SET title='rollback'"}])
        self.assertFalse(result['ok'])
        self.assertTrue(result['transaction_rolled_back'])
        result = ex.execute_sql(sql=[{'sql':'BEGIN'}, {'sql':"UPDATE nodes SET title='kept'"}, {'sql':'SAVEPOINT part'},
            {'sql':"UPDATE nodes SET title='discarded'"}, {'sql':'ROLLBACK TO part'}, {'sql':'RELEASE part'}, {'sql':'COMMIT'},
            {'sql':"UPDATE nodes SET title=title"}, {'sql':'SELECT * FROM missing'}], activity_context={'chat_id':'partial'})
        self.assertFalse(result['ok'])
        self.assertTrue(result['autocommit_effects_possible'])
        changes = self.viewer().changes({})['events']
        self.assertEqual(len(changes), 2)
        self.assertEqual(changes[1]['after']['title']['value'], 'kept')
        self.assertEqual(changes[1]['chat'], 'partial')
        calls = self.viewer().events({})['events']
        self.assertEqual(changes[1]['activity_id'], calls[-1]['activity_id'])
        self.assertFalse(calls[-1]['ok'])
        self.assertTrue(calls[1]['rolled_back'])

    def test_native_ddl_transaction_preserves_existing_table_attribution(self):
        ex = self.executor()
        self.node(ex)
        result = ex.execute_sql(sql=[{'sql':'BEGIN'}, {'sql':'CREATE TABLE custom(value)'},
            {'sql':"UPDATE nodes SET title='ddl transaction'"}, {'sql':'COMMIT'}], activity_context={'chat_id':'ddl'})
        self.assertTrue(result['ok'], result)
        self.assertEqual(result['results'][2]['affected_rows'], 1)
        viewer = self.viewer()
        self.assertEqual(viewer.changes({})['events'][-1]['chat'], 'ddl')
        self.assertEqual(viewer.events({})['events'][-1]['write'], ['nodes','sqlite_master'])
        self.assertTrue(ex.execute_sql(sql="INSERT INTO custom VALUES('tracked after commit')")['ok'])
        self.assertEqual(viewer.changes({})['events'][-1]['table'], 'custom')

    def test_multiple_writers_have_exact_connection_local_links(self):
        self.viewer()
        def run(index):
            ex = Executor(self.path)
            try:
                result = self.node(ex, str(index), activity_context={'chat_id':str(index)})
                return result
            finally:
                ex.close()
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(run, range(12)))
        self.assertTrue(all(result['ok'] for result in results), results)
        viewer = self.viewer()
        events = viewer.events({})['events']
        self.assertEqual(len(events), 12)
        by_id = {event['activity_id']:event for event in events}
        changes = viewer.changes({})['events']
        self.assertEqual(len(changes), 12)
        for change in changes:
            self.assertEqual(change['after']['id']['value'], by_id[change['activity_id']]['chat'])

    def test_v1_upgrade_preserves_rows_and_base_schema(self):
        install(self.path)
        with closing(sqlite3.connect(self.path)) as db:
            db.execute("UPDATE scopes SET revision='old'")
            db.execute('DROP TABLE ' + CALLS)
            db.execute('ALTER TABLE ' + LOG + ' DROP COLUMN activity_id')
            db.execute('ALTER TABLE ' + LOG + ' DROP COLUMN actor_json')
            db.execute('UPDATE ' + META + " SET value='1' WHERE key='format_version'")
            old = db.execute('SELECT * FROM ' + LOG).fetchall()
            db.commit()
        viewer = self.viewer()
        self.assertNotIn('activity_id', viewer.changes({})['events'][0])
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT id,occurred_at,table_name,operation,key_before_json,key_after_json,before_json,after_json FROM ' + LOG).fetchall(), old)
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 3)
            schema = db.execute('PRAGMA schema_version').fetchone()[0]
        self.assertEqual(install(self.path)['schema_version'], schema)
        self.assertEqual(viewer.events({})['events'], [])
        self.assertTrue(viewer.events({})['enabled'])

    def test_optout_preserves_bytes_and_saved_history_stays_readable(self):
        before = self.path.read_bytes()
        ex = self.executor(history=False)
        self.assertTrue(ex.execute_sql(sql='SELECT * FROM nodes')['ok'])
        viewer = self.viewer(history=False)
        self.assertFalse(viewer.events({})['enabled'])
        self.assertEqual(before, self.path.read_bytes())
        self.node(self.executor(), 'recorded')
        count = len(viewer.events({})['events'])
        self.node(ex, 'optout')
        self.assertEqual(len(viewer.events({})['events']), count)
        self.assertNotIn('activity_id', viewer.changes({})['events'][-1])

    def test_optout_keeps_explicit_legacy_export_on_arbitrary_database(self):
        generic = Path(self.temp.name) / 'generic.sqlite3'
        with closing(sqlite3.connect(generic)) as db:
            db.execute('CREATE TABLE raw(id INTEGER PRIMARY KEY,value TEXT)')
            db.execute("INSERT INTO raw VALUES(1,'fixture')")
            db.commit()
        before = generic.read_bytes()
        ex = Executor(generic, history=False)
        self.addCleanup(ex.close)
        configure_trace(ex, Path(self.temp.name) / 'legacy-optout', 'explicit-session')
        result = ex.execute_sql(sql='SELECT id FROM raw', activity_context={'chat_id':'known'})
        self.assertTrue(result['ok'], result)
        events = [json.loads(line) for line in ex.activity_log.path.read_text().splitlines()]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]['session'], 'explicit-session')
        self.assertEqual(events[0]['chat'], 'known')
        self.assertEqual(events[0]['read'], ['raw'])
        self.assertTrue(events[0]['activity_id'])
        self.assertEqual(generic.read_bytes(), before)
        self.assertFalse(ex.connection.execute("SELECT 1 FROM sqlite_schema WHERE name LIKE 'evomneme_change_%'").fetchone())

    def test_optout_counts_existing_v2_bookkeeping_but_keeps_user_trigger_counts(self):
        with closing(sqlite3.connect(self.path)) as db:
            db.execute('CREATE TABLE sink(scope_id TEXT)')
            db.commit()
        install(self.path)
        ex = self.executor(history=False)
        before = self.path.read_bytes()
        configure_trace(ex, Path(self.temp.name) / 'legacy-installed', 'explicit-session')
        self.assertTrue(ex.execute_sql(sql='SELECT 1')['ok'])
        self.assertEqual(self.path.read_bytes(), before, 'Opt-out observation must not modify main schema/metadata')
        first = ex.execute_sql(sql="UPDATE scopes SET revision='optout'")
        self.assertEqual(first['results'][0]['affected_rows'], 1)
        with closing(sqlite3.connect(self.path)) as db:
            db.execute('CREATE TRIGGER user_scope AFTER UPDATE ON scopes BEGIN INSERT INTO sink VALUES(NEW.id); END')
            db.commit()
        enabled = self.executor()
        expected = enabled.execute_sql(sql="UPDATE scopes SET revision='enabled'")
        actual = ex.execute_sql(sql="UPDATE scopes SET revision='disabled' RETURNING id")
        self.assertTrue(actual['ok'], actual)
        self.assertEqual(expected['results'][0]['affected_rows'], 2)
        self.assertEqual(actual['results'][0]['affected_rows'], 2)
        self.assertEqual(actual['results'][0]['rows'], [['s']])
        self.assertEqual(ex.connection.execute('SELECT count(*) FROM ' + CALLS).fetchone()[0], 1)
        events = [json.loads(line) for line in ex.activity_log.path.read_text().splitlines()]
        self.assertEqual(events[-1]['write'], ['scopes', 'sink'])
        self.assertEqual(events[-1]['read'], ['scopes'])
        changes = self.viewer(history=False).changes({})['events']
        self.assertTrue(all('activity_id' not in change for change in changes[-2:]))

    def test_generic_sql_creation_and_deferred_recognition(self):
        generic = Path(self.temp.name) / 'raw.sqlite3'
        ex = Executor(generic, create=True)
        self.addCleanup(ex.close)
        self.assertTrue(ex.execute_sql(sql='CREATE TABLE raw(id INTEGER PRIMARY KEY)')['ok'])
        self.assertTrue(ex.execute_sql(sql='INSERT INTO raw DEFAULT VALUES')['ok'])
        self.assertEqual(ex.execute_sql(sql='SELECT last_insert_rowid()')['results'][0]['rows'], [[1]])
        self.assertFalse(ex.connection.execute("SELECT 1 FROM sqlite_schema WHERE name LIKE 'evomneme_change_%'").fetchone())
        # Native construction can finish with version metadata (no DDL change).
        ex.connection.executescript((ROOT / 'schema.sql').read_text().replace('PRAGMA user_version = 3;', ''))
        ex.execute_sql(sql='SELECT 1')
        ex.execute_sql(sql='PRAGMA user_version=3')
        self.assertTrue(ex.execute_sql(sql='SELECT 1')['ok'])
        self.assertTrue(ex.connection.execute('SELECT 1 FROM ' + CALLS).fetchone())

    def test_pagination_and_dual_output_deduplicate_stable_id(self):
        ex = self.executor()
        trace = Path(self.temp.name) / 'legacy'
        configure_trace(ex, trace, 'stable-session')
        for index in range(9):
            self.assertTrue(ex.execute_sql(sql='SELECT ?', params=[index])['ok'])
        viewer = self.viewer(trace_directory=trace)
        latest = viewer.events({'limit':3})
        self.assertEqual([event['activity_record_id'] for event in latest['events']], [7,8,9])
        older = viewer.events({'before_id':latest['before_id'], 'limit':3, 'cursors':latest['cursors']})
        self.assertEqual([event['activity_record_id'] for event in older['events']], [4,5,6])
        forward = viewer.events({'after_id':3, 'limit':3, 'cursors':latest['cursors']})
        self.assertEqual([event['activity_record_id'] for event in forward['events']], [4,5,6])
        self.assertTrue(forward['has_more'])
        self.assertEqual(viewer.events({'after_id':9, 'cursors':latest['cursors']})['events'], [])
        exported = [json.loads(line) for line in ex.activity_log.path.read_text().splitlines()]
        self.assertEqual(exported[0]['activity_id'], viewer.events({'after_id':0,'limit':1})['events'][0]['activity_id'])
        self.assertEqual({event['session'] for event in exported}, {'stable-session'})

    def test_history_failure_does_not_fail_committed_sql(self):
        ex = self.executor()
        with patch.object(ex.history, 'record', side_effect=sqlite3.OperationalError('synthetic record failure')):
            with redirect_stderr(io.StringIO()) as diagnostic:
                result = self.node(ex)
        self.assertTrue(result['ok'], result)
        self.assertIn('could not be saved', diagnostic.getvalue())
        self.assertEqual(ex.connection.execute('SELECT count(*) FROM nodes').fetchone()[0], 1)
        changes = self.viewer().changes({})['events']
        self.assertEqual(len(changes), 1)
        self.assertIsNotNone(changes[0]['activity_id'])

    def test_cli_python_defaults_and_client_metadata(self):
        cli = subprocess.run([sys.executable, str(ROOT/'scripts/evomneme.py'), '--database', str(self.path), '--sql', 'SELECT 1'], capture_output=True)
        self.assertEqual(cli.returncode, 0, cli.stderr)
        executor = self.executor()
        result = executor.execute_sql(sql='SELECT 2')
        self.assertTrue(result['ok'], result)
        events = self.viewer().events({})['events']
        self.assertEqual({event['client']['name'] for event in events}, {'EvoMneme CLI','EvoMneme Python'})
        executor.client = {'name':'Synthetic client', 'version':'1'}
        self.assertTrue(executor.execute_sql(sql='SELECT 3')['ok'])
        self.assertEqual(self.viewer().events({})['events'][-1]['client'], executor.client)

    def test_cli_python_no_history_options_preserve_pristine_database(self):
        before = self.path.read_bytes()
        cli = subprocess.run([sys.executable, str(ROOT/'scripts/evomneme.py'), '--database', str(self.path),
            '--no-history', '--sql', 'SELECT 1'], capture_output=True)
        self.assertEqual(cli.returncode, 0, cli.stderr)
        executor = self.executor(history=False)
        self.assertTrue(executor.execute_sql(sql='SELECT 2')['ok'])
        executor.close()
        self.assertEqual(self.path.read_bytes(), before)

    def test_incompatible_reserved_history_is_preserved_and_failure_is_honest(self):
        with closing(sqlite3.connect(self.path)) as db:
            db.execute('CREATE TABLE ' + CALLS + '(private_value TEXT)')
            db.execute('INSERT INTO ' + CALLS + " VALUES('preserved')")
            db.commit()
        with redirect_stderr(io.StringIO()) as diagnostic:
            ex = self.executor()
            result = self.node(ex)
        self.assertTrue(result['ok'])
        self.assertIn('setup failed', diagnostic.getvalue())
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT * FROM ' + CALLS).fetchall(), [('preserved',)])
            self.assertFalse(db.execute("SELECT 1 FROM sqlite_schema WHERE name=?", [LOG]).fetchone())

    def test_bookkeeping_preserves_native_returned_ids_and_user_trigger_counts(self):
        ex = self.executor()
        self.assertTrue(ex.execute_sql(sql='CREATE TABLE source(id INTEGER PRIMARY KEY,value TEXT)')['ok'])
        result = ex.execute_sql(sql="INSERT INTO source(value) VALUES('a') RETURNING id")
        self.assertEqual(result['results'][0]['rows'], [[1]])
        self.assertEqual(result['results'][0]['affected_rows'], 1)
        self.assertEqual(ex.execute_sql(sql='SELECT last_insert_rowid(),changes()')['results'][0]['rows'], [[1,1]])
        ex.execute_sql(sql='UPDATE source SET value=value WHERE id=-1')
        self.assertEqual(ex.execute_sql(sql='SELECT last_insert_rowid(),changes()')['results'][0]['rows'], [[1,0]])
        ex.execute_sql(sql='CREATE TABLE sink(value TEXT)')
        ex.execute_sql(sql='CREATE TRIGGER custom AFTER INSERT ON source BEGIN INSERT INTO sink VALUES(NEW.value); END')
        result = ex.execute_sql(sql="INSERT INTO source(value) VALUES('b'),('c') RETURNING id", max_rows=1)
        self.assertEqual(result['results'][0]['affected_rows'], 4)
        self.assertTrue(result['results'][0]['has_more'])
        self.assertEqual(set(self.viewer().events({})['events'][-1]['write']), {'source','sink'})

    def test_activity_alone_does_not_invalidate_graph_revision(self):
        viewer = self.viewer()
        ex = self.executor()
        before = viewer.snapshot({'whole_graph':True})['revision']
        ex.execute_sql(sql='SELECT 1')
        self.assertEqual(viewer.snapshot({'whole_graph':True,'revision':before})['revision'], before)
        self.node(ex)
        changed = viewer.snapshot({'whole_graph':True})['revision']
        self.assertNotEqual(changed, before)
        with closing(sqlite3.connect(self.path)) as db:
            db.execute("UPDATE nodes SET title='external'")
            db.commit()
        self.assertNotEqual(viewer.revision(), changed)

    def test_raw_revision_fallback_for_missing_disabled_and_custom_history(self):
        viewer = self.viewer(history=False)
        before = viewer.revision()
        with closing(sqlite3.connect(self.path)) as db:
            db.execute("UPDATE scopes SET revision='raw'")
            db.commit()
        self.assertNotEqual(viewer.revision(), before)
        self.node(self.executor())
        install(self.path, suspend=True)
        before = viewer.revision()
        with closing(sqlite3.connect(self.path)) as db:
            db.execute("UPDATE nodes SET title='suspended'")
            db.commit()
        self.assertNotEqual(viewer.revision(), before)
        custom = self.viewer(mapping={'nodes':'SELECT id AS graph_id,title AS label FROM nodes',
            'edges':'SELECT id AS graph_id,source_id AS source,target_id AS target FROM edges'})
        before = custom.revision()
        self.executor().execute_sql(sql='SELECT 1')
        self.assertNotEqual(custom.revision(), before)

    def test_bulk_changes_and_call_pages_obey_bounds_without_gaps(self):
        ex = self.executor()
        result = ex.execute_sql(sql="WITH RECURSIVE n(x) AS (VALUES(1) UNION ALL SELECT x+1 FROM n WHERE x<250) INSERT INTO nodes(scope_id,id,kind,title,summary,confidence,validity,updated_at) SELECT 's',CAST(x AS TEXT),'function','title','summary','inferred','current','now' FROM n")
        self.assertTrue(result['ok'], result)
        self.assertEqual(result['results'][0]['affected_rows'], 250)
        viewer = self.viewer()
        changes = viewer.changes({'after_id':0,'limit':200})
        tail = viewer.changes({'after_id':changes['after_id'],'limit':200})
        self.assertEqual(len(changes['events']) + len(tail['events']), 250)
        self.assertEqual(len({event['activity_id'] for event in changes['events'] + tail['events']}), 1)
        with closing(sqlite3.connect(self.path)) as db:
            # Large synthetic call metadata exercises byte backpressure independently
            # of the normal producer's smaller, bounded metadata payloads.
            for index in range(12):
                event = {'source':'sql','time':index,'activity_id':'large'+str(index),'padding':'x'*300000}
                db.execute('INSERT INTO ' + CALLS + '(activity_id,event_json) VALUES(?,?)', [event['activity_id'], json.dumps(event)])
            db.commit()
            first = read_calls(db, {'after_id':1})
            second = read_calls(db, {'after_id':first['after_id']})
            self.assertTrue(first['has_more'])
            self.assertEqual(len(first['events']) + len(second['events']), 12)
            self.assertEqual([event['activity_record_id'] for event in first['events'] + second['events']], list(range(2,14)))


if __name__ == '__main__':
    unittest.main()
