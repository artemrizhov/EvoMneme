"""Synthetic host-only explorer, activity and loopback boundary checks."""

import hashlib
import gzip
import contextlib
import http.client
import io
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
from evomneme import Executor
from evomneme_trace import configure_trace
from evomneme_viewer import Explorer, make_server


def fixture(path):
    db = sqlite3.connect(path)
    db.executescript((ROOT / 'schema.sql').read_text())
    for scope in ('main', 'branch'):
        db.execute('INSERT INTO scopes VALUES(?,?,?,?,?,?)', (scope, scope, 'synthetic', 'abc', 'fixture', '2026-10-25'))
        for i, (kind, confidence, validity) in enumerate([('module','confirmed','current'), ('function','inferred','current'), ('decision','uncertain','stale'), ('constraint','confirmed','superseded')]):
            db.execute('INSERT INTO nodes(scope_id,id,kind,title,summary,confidence,validity,source_path,updated_at) VALUES(?,?,?,?,?,?,?,?,?)',
                       (scope, str(i), kind, scope + ' node ' + str(i), 'Synthetic <script>alert(1)</script>', confidence, validity, 'src/example.py', '2026-10-25'))
        for i in range(2):
            db.execute('INSERT INTO edges(scope_id,id,source_id,target_id,kind,summary,confidence,validity,updated_at) VALUES(?,?,?,?,?,?,?,?,?)',
                       (scope, 'e'+str(i), str(i), str(i+1), 'depends_on', 'Synthetic relationship', 'inferred', 'current', '2026-10-25'))
        db.execute('INSERT INTO evidence(scope_id,id,node_id,description,validity,updated_at) VALUES(?,?,?,?,?,?)', (scope, 'proof', '0', 'Observed synthetic fixture', 'current', '2026-10-25'))
    db.commit()
    db.close()


def code_fixture(path):
    db = sqlite3.connect(path)
    db.execute('PRAGMA foreign_keys=ON')
    db.executemany("""INSERT INTO nodes(scope_id,id,title,kind,layer,summary,confidence,validity,source_path,updated_at)
        VALUES(?,?,?,?,?,'Synthetic','inferred','current','src/demo.py','now')""", [
        ('main','c0','Agent','class','code'), ('main','c1','Agent.call','method','code'),
        ('main','cf','demo.py','file','code'), ('branch','c0','branch_function','function','code'),
        ('main','outside.module','Unresolved import','unresolved_reference','unresolved')])
    db.executemany('INSERT INTO symbol_details VALUES(?,?,?,?,?)', [
        ('main','c0','Agent','class Agent:','python'), ('main','c1','Agent.call','def call(','python'),
        ('branch','c0','branch_function','def branch_function():','python')])
    db.execute("INSERT INTO file_details VALUES('main','cf','partial','pending',NULL,NULL,NULL)")
    db.executemany("""INSERT INTO edges(scope_id,id,source_id,target_id,kind,layer,resolution,summary,confidence,validity,updated_at)
        VALUES('main',?,?,?,?,?,?,'Synthetic','inferred','current','now')""", [
        ('contains','c0','c1','contains','code','resolved'),
        ('summary','c1','0','semantic-summary','cross','resolved'),
        ('source','1','c0','knowledge-source','cross','resolved'),
        ('external','c1','outside.module','imports','code','unresolved'),
        ('file','c1','cf','declared_in','code','resolved')])
    db.commit()
    db.close()


class ViewerTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'), 'Optional viewer regression needs an existing Node.js')
    def test_graph_progress_lifecycle_components_and_retry(self):
        result = subprocess.run([shutil.which('node'),str(ROOT/'tests/test_viewer_progress.js')],capture_output=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stderr.decode('utf-8','replace'))

    @unittest.skipUnless(shutil.which('node'), 'Optional layout regression needs an existing Node.js')
    def test_graph_layout_growth_spacing_and_orientation(self):
        result = subprocess.run([shutil.which('node'),str(ROOT/'tests/test_viewer_layout.js')],capture_output=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stderr.decode('utf-8','replace'))

    @unittest.skipUnless(shutil.which('node'), 'Background layout regression needs an existing Node.js')
    def test_background_layout_worker(self):
        result = subprocess.run([shutil.which('node'),str(ROOT/'tests/test_viewer_worker.js')],capture_output=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stderr.decode('utf-8','replace'))

    def setUp(self):
        area = ROOT / '.evomneme-tests'
        area.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=area)
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.path = self.directory / 'host.sqlite3'
        fixture(self.path)
        self.explorer = Explorer(self.path)
        self.addCleanup(self.explorer.close)

    def test_replay_snapshot_is_consistent_and_read_only(self):
        with contextlib.closing(sqlite3.connect(self.path)) as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.execute("UPDATE nodes SET title='Recorded title' WHERE scope_id='main' AND id='0'")
            db.commit()
        original_rows = self.explorer.rows
        wrote = False

        def rows(db, sql, **kwargs):
            nonlocal wrote
            result = original_rows(db, sql, **kwargs)
            if not wrote:
                wrote = True
                with contextlib.closing(sqlite3.connect(self.path)) as writer:
                    writer.execute("UPDATE nodes SET title='Concurrent title' WHERE scope_id='main' AND id='0'")
                    writer.commit()
            return result

        with patch.object(self.explorer, 'rows', side_effect=rows):
            replay = self.explorer.replay({})
        node = next(n for n in replay['nodes'] if n['scope_id']=='main' and n['id']=='0')
        self.assertEqual(node['title'], 'Recorded title')
        self.assertEqual(len(replay['events']), 1)
        self.assertEqual(replay['events'][0]['before']['title']['value'], 'main node 0')
        self.assertEqual(replay['events'][0]['after']['title']['value'], 'Recorded title')
        with contextlib.closing(sqlite3.connect(self.path)) as db:
            before = list(db.iterdump())
        self.assertEqual(len(self.explorer.replay({})['events']), 2)
        with contextlib.closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(before, list(db.iterdump()), 'Replay must not mutate the database or journal')
        custom = Explorer(self.path, {'nodes':'SELECT 1', 'edges':'SELECT 1'})
        try:
            with self.assertRaisesRegex(ValueError, 'standard'):
                custom.replay({})
        finally:
            custom.close()

    def test_replay_bounds_fail_instead_of_returning_partial_history(self):
        with patch('evomneme_viewer.MAX_GRAPH_NODES', 1):
            with self.assertRaisesRegex(ValueError, 'too large'):
                self.explorer.replay({})
        with contextlib.closing(sqlite3.connect(self.path)) as db:
            db.execute("UPDATE nodes SET title='Changed' WHERE scope_id='main' AND id='0'")
            db.commit()
        with patch('evomneme_viewer.MAX_GRAPH_RESPONSE', 1):
            with self.assertRaisesRegex(ValueError, 'byte budget|replay budget'):
                self.explorer.replay({})

    def test_http_replay_over_eight_mib_uses_its_full_budget(self):
        # A real journal, rather than a mocked response, exercises collection,
        # UTF-8 budgeting, HTTP routing and gzip delivery together.
        with contextlib.closing(sqlite3.connect(self.path)) as db:
            db.executemany("UPDATE nodes SET summary=? WHERE scope_id='main' AND id='0'",
                           ((str(i) + ' ' + '\u044f' * 2500,) for i in range(1100)))
            db.commit()
        server, token = make_server(self.explorer)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        conn = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=30)
        self.addCleanup(conn.close)
        conn.request('POST', '/api/replay', body='{}',
                     headers={'X-Viewer-Token':token,'Accept-Encoding':'gzip'})
        response = conn.getresponse()
        self.assertEqual(response.status, 200)
        self.assertEqual(response.getheader('Content-Encoding'), 'gzip')
        body = gzip.decompress(response.read())
        self.assertGreater(len(body), 8 * 1024 * 1024)
        replay = json.loads(body)
        self.assertEqual(len(replay['events']), 1100)
        self.assertIn('\u044f', replay['events'][-1]['after']['summary']['value'])
        self.assertIn('\u044f'.encode(), body, 'HTTP must use the same UTF-8 representation as budget accounting')
        with patch('evomneme_viewer.MAX_RESPONSE', 128):
            # Replay gets its own limit; ordinary query limits stay in effect.
            conn.request('POST', '/api/replay', body='{}', headers={'X-Viewer-Token':token,'Accept-Encoding':'gzip'})
            response = conn.getresponse()
            self.assertEqual(response.status, 200)
            response.read()
            conn.request('POST', '/api/query', body=json.dumps({'sql':"SELECT printf('%1000s','x') AS content"}),
                         headers={'X-Viewer-Token':token})
            response = conn.getresponse()
            self.assertEqual(response.status, 413)
            response.read()

    def test_whole_database_scope_keys_filter_page_boundary_and_neighborhood(self):
        whole = self.explorer.snapshot({})
        self.assertEqual(whole['totals'], {'nodes': 8, 'edges': 4})
        self.assertEqual(whole['isolated_total'], 2)
        self.assertEqual(len({n['graph_id'] for n in whole['nodes']}), 8)
        self.assertEqual(whole['dangling_total'], 0)
        page = self.explorer.snapshot({'scope_id': 'main', 'limit': 2})
        self.assertEqual(page['matched_nodes'], 4)
        self.assertTrue(page['node_has_more'])
        self.assertEqual(page['boundary_edges'], 1)
        self.assertEqual(len(page['edges']), 1)
        focused = self.explorer.snapshot({'root': '["main","0"]', 'depth': 2})
        self.assertEqual({n['id'] for n in focused['nodes']}, {'0','1','2'})
        stale = self.explorer.snapshot({'validity':'stale', 'search':'branch'})
        self.assertEqual([(n['scope_id'], n['id']) for n in stale['nodes']], [('branch','2')])
        unsupported = self.explorer.snapshot({'focus':'unsupported'})
        self.assertEqual(len(unsupported['nodes']), 6)
        self.assertTrue(all(n['evidence_count']==0 for n in unsupported['nodes']))
        isolated = self.explorer.snapshot({'focus':'isolated'})
        self.assertEqual(len(isolated['nodes']), 2)
        filtered = self.explorer.snapshot({'edge_confidence':'confirmed'})
        self.assertEqual(filtered['edges'], [])
        self.assertEqual(filtered['totals']['edges'], 4)
        focused = self.explorer.snapshot({'scope_id':'main','root':'["main","0"]','depth':2,'edge_kind':'depends_on'})
        self.assertEqual(len(focused['nodes']), 3)

    def test_read_only_queries_detail_evidence_and_no_schema_migration(self):
        before = self.path.read_bytes()
        self.assertEqual(len(self.explorer.query({'sql':'SELECT * FROM nodes'})['rows']), 8)
        for sql in ('DELETE FROM nodes RETURNING *', 'PRAGMA query_only=OFF', "SELECT load_extension('x')", 'SELECT * FROM pragma_query_only(0)'):
            with self.assertRaises((ValueError, sqlite3.Error)):
                self.explorer.query({'sql':sql})
        detail = self.explorer.detail({'type':'nodes', 'id':'["main","0"]'})
        self.assertEqual(len(detail['evidence']), 1)
        self.assertEqual(detail['rows'][0]['scope_id'], 'main')
        self.assertEqual(before, self.path.read_bytes())

    def test_unified_layers_cross_links_and_unresolved_references(self):
        code_fixture(self.path)
        before = self.path.read_bytes()
        graph = self.explorer.snapshot({'whole_graph':True})
        self.assertEqual(graph['totals'],{'nodes':13,'edges':9})
        self.assertEqual(len(graph['nodes']),13)
        self.assertEqual(len(graph['edges']),9)
        self.assertEqual(graph['reference_total'],1)
        self.assertEqual({n['layer'] for n in graph['nodes']},{'code','knowledge','unresolved'})
        self.assertEqual(sum(e['layer']=='cross' for e in graph['edges']),2)
        nodes = {n['graph_id'] for n in graph['nodes']}
        self.assertTrue(all(e['source'] in nodes and e['target'] in nodes for e in graph['edges']))
        summary = next(e for e in graph['edges'] if e['id']=='summary')
        self.assertEqual(summary['target'],'["main","0"]')
        self.assertEqual(summary['source'],'["main","c1"]')
        code_only = self.explorer.snapshot({'whole_graph':True,'excluded_layers':['knowledge','unresolved']})
        self.assertEqual(len(code_only['nodes']),4)
        self.assertEqual(len(code_only['edges']),2)
        knowledge_only = self.explorer.snapshot({'whole_graph':True,'excluded_layers':['code','unresolved','cross']})
        self.assertEqual(len(knowledge_only['nodes']),8)
        self.assertEqual(len(knowledge_only['edges']),4)
        no_cross = self.explorer.snapshot({'whole_graph':True,'excluded_layers':['cross']})
        self.assertEqual(len(no_cross['nodes']),13)
        self.assertEqual(len(no_cross['edges']),7)
        empty = self.explorer.snapshot({'whole_graph':True,'excluded_layers':['code','knowledge','unresolved','cross']})
        self.assertEqual(empty['nodes'],[])
        self.assertEqual(empty['edges'],[])
        detail = self.explorer.detail({'type':'nodes','id':'["main","c1"]'})
        self.assertEqual(detail['rows'][0]['signature'],'def call(')
        self.assertEqual(detail['coverage'][0]['declaration_status'],'partial')
        self.assertEqual(detail['evidence'],[])
        self.assertEqual(before,self.path.read_bytes())
        executor = Executor(self.path)
        self.addCleanup(executor.close)
        configure_trace(executor,self.directory/'activity','code-session')
        result = executor.execute_sql(sql='SELECT scope_id,id FROM nodes WHERE scope_id=? AND id=?',params=['main','c1'])
        self.assertTrue(result['ok'])
        events = Explorer(self.path,trace_directory=self.directory/'activity').events({})['events']
        self.assertEqual(events[0]['references'],[{'table':'nodes','scope_id':'main','id':'c1'}])

    def test_legacy_store_is_rejected_without_writes_or_mapping_bypass(self):
        path = self.directory / 'legacy.sqlite3'
        db = sqlite3.connect(path)
        db.executescript((ROOT / 'tests/fixtures/schema-v2.sql').read_text())
        db.close()
        before = path.read_bytes()
        mapping = {'nodes': 'SELECT id AS graph_id,title AS label FROM records',
                   'edges': 'SELECT id AS graph_id,source_id AS source,target_id AS target FROM relations'}
        for options in ({}, {'mapping': mapping}, {'record_changes': True}, {'mapping': mapping, 'record_changes': True}):
            with self.subTest(options=options), self.assertRaisesRegex(ValueError, 'requires v3'):
                Explorer(path, **options)
            self.assertEqual(path.read_bytes(), before)
        cli = subprocess.run([sys.executable, str(ROOT / 'scripts/evomneme_viewer.py'),
                              '--database', str(path), '--record-changes'], capture_output=True, timeout=10)
        self.assertNotEqual(cli.returncode, 0)
        self.assertIn(b'requires v3', cli.stderr)
        self.assertEqual(path.read_bytes(), before)

    def test_neighborhood_does_not_traverse_disabled_node_layers(self):
        code_fixture(self.path)
        db = sqlite3.connect(self.path)
        db.executemany("INSERT INTO nodes(scope_id,id,title,kind,layer,summary,confidence,validity,updated_at) VALUES(?,?,?,?,'code','Synthetic','inferred','current','now')",
                       [('main','isolated-a','A','function'),('main','isolated-b','B','function')])
        db.executemany("INSERT INTO edges(scope_id,id,source_id,target_id,kind,layer,summary,confidence,validity,updated_at) VALUES(?,?,?,?,?,'code','Synthetic','inferred','current','now')",
                       [('main','bridge-a','isolated-a','0','explains'),
                        ('main','bridge-b','0','isolated-b','explains')])
        db.commit()
        db.close()
        values = {'whole_graph':True,'root':'["main","isolated-a"]','depth':2}
        complete = self.explorer.snapshot(values)
        self.assertTrue(any(n['id']=='isolated-b' for n in complete['nodes']))
        hidden = self.explorer.snapshot({**values,'excluded_layers':['knowledge','unresolved']})
        self.assertEqual([n['id'] for n in hidden['nodes']],['isolated-a'])

    def test_code_only_database_and_layer_aggregation(self):
        path = self.directory / 'code-only.sqlite3'
        fixture(path)
        code_fixture(path)
        with contextlib.closing(sqlite3.connect(path)) as db:
            db.execute('DELETE FROM evidence')
            db.execute("DELETE FROM edges WHERE layer IN ('knowledge','cross')")
            db.execute("DELETE FROM nodes WHERE layer='knowledge'")
            db.commit()
        explorer = Explorer(path)
        self.addCleanup(explorer.close)
        graph = explorer.snapshot({'whole_graph':True})
        self.assertTrue(graph['graph_available'])
        self.assertEqual(sum(n['layer']=='code' for n in graph['nodes']),4)
        self.assertEqual(len(graph['edges']),3)
        overview = self.explorer.snapshot({'whole_graph':True,'aggregate':'layer'})
        self.assertEqual(overview['nodes'][0]['group_value'],'knowledge')
        self.assertEqual(overview['grouped_members'],8)

    def test_full_graph_exceeds_old_slice_bounds_and_http_compression(self):
        code_fixture(self.path)
        db = sqlite3.connect(self.path)
        db.executemany("INSERT INTO nodes(scope_id,id,title,kind,layer,summary,confidence,validity,updated_at) VALUES(?,?,?,?,'code','Synthetic','inferred','current','now')",
                       [('main','large'+str(i),'SyntheticFunction'+str(i),'function') for i in range(2501)])
        db.executemany("INSERT INTO edges(scope_id,id,source_id,target_id,kind,layer,summary,confidence,validity,updated_at) VALUES(?,?,?,?,?,'code','Synthetic','inferred','current','now')",
                       [('main','large-edge'+str(i),'large'+str(i),'large'+str(i+1),'calls') for i in range(2500)])
        db.commit()
        db.close()
        whole = self.explorer.snapshot({'whole_graph':True})
        self.assertGreater(len(whole['nodes']),2000)
        self.assertGreater(len(whole['edges']),2000)
        self.assertFalse(whole['node_has_more'])
        self.assertFalse(whole['edge_has_more'])
        page = self.explorer.snapshot({'limit':100})
        self.assertEqual(len(page['nodes']),100)
        self.assertTrue(page['node_has_more'])
        server, token = make_server(self.explorer)
        threading.Thread(target=server.serve_forever,daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        conn = http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=10)
        self.addCleanup(conn.close)
        conn.request('POST','/api/snapshot',body='{"whole_graph":true}',headers={'X-Viewer-Token':token,'Accept-Encoding':'gzip'})
        response = conn.getresponse()
        self.assertEqual(response.status,200)
        self.assertEqual(response.getheader('Content-Encoding'),'gzip')
        graph = json.loads(gzip.decompress(response.read()))
        self.assertEqual(len(graph['nodes']),len(whole['nodes']))
        self.assertEqual(len(graph['edges']),len(whole['edges']))

    def test_revision_cache_invalidates_for_database_changes_and_layer_selection(self):
        code_fixture(self.path)
        writer = sqlite3.connect(self.path)
        self.addCleanup(writer.close)
        writer.execute('PRAGMA journal_mode=WAL')
        first = self.explorer.snapshot({'whole_graph':True})
        cached = self.explorer.snapshot({'whole_graph':True,'revision':first['revision']})
        self.assertTrue(cached['unchanged'])
        filtered = self.explorer.snapshot({'whole_graph':True,'revision':first['revision'],'excluded_layers':['code']})
        self.assertNotIn('unchanged',filtered)
        writer.execute("UPDATE nodes SET title='ChangedName' WHERE scope_id='main' AND id='c0'")
        writer.commit()
        changed = self.explorer.snapshot({'whole_graph':True,'revision':first['revision']})
        self.assertNotEqual(changed['revision'],first['revision'])
        self.assertTrue(any(n['label']=='ChangedName' for n in changed['nodes']))
        old = next(n for n in changed['nodes'] if n['graph_id']=='["main","c1"]')['fingerprint']
        writer.execute("UPDATE symbol_details SET signature='def call(self, value):' WHERE scope_id='main' AND node_id='c1'")
        writer.commit()
        updated = self.explorer.snapshot({'whole_graph':True,'revision':changed['revision']})
        node = next(n for n in updated['nodes'] if n['graph_id']=='["main","c1"]')
        self.assertNotEqual(node['fingerprint'],old)
        self.assertNotIn('signature',node)

    def test_full_graph_bounds_fail_explicitly_instead_of_returning_a_prefix(self):
        with patch('evomneme_viewer.MAX_GRAPH_NODES',2):
            with self.assertRaisesRegex(ValueError,'Whole graph exceeds'):
                self.explorer.snapshot({'whole_graph':True})
        with patch('evomneme_viewer.MAX_GRAPH_EDGES',2):
            with self.assertRaisesRegex(ValueError,'Whole graph exceeds'):
                self.explorer.snapshot({'whole_graph':True})
        with self.explorer.connect() as db:
            with self.assertRaisesRegex(ValueError,'byte budget'):
                self.explorer.rows(db,"SELECT printf('%1000s','x') AS value",max_bytes=100)

    def test_full_graph_budgets_overview_not_omitted_details(self):
        with contextlib.closing(sqlite3.connect(self.path)) as writer:
            writer.execute('UPDATE nodes SET summary=?', ['x'*100000])
            writer.execute('UPDATE edges SET summary=?', ['y'*100000])
            writer.commit()
        with patch('evomneme_viewer.MAX_GRAPH_RESPONSE',20*1024):
            graph=self.explorer.snapshot({'whole_graph':True})
        self.assertEqual(len(graph['nodes']),8)
        self.assertEqual(len(graph['edges']),4)
        self.assertTrue(all('summary' not in row for row in graph['nodes']+graph['edges']))
        fingerprint=graph['nodes'][0]['fingerprint']
        with contextlib.closing(sqlite3.connect(self.path)) as writer:
            writer.execute('UPDATE nodes SET summary=?',['z'*100000])
            writer.commit()
        updated=self.explorer.snapshot({'whole_graph':True})
        self.assertNotEqual(updated['nodes'][0]['fingerprint'],fingerprint)
        detail=self.explorer.detail({'type':'nodes','id':graph['nodes'][0]['graph_id']})
        self.assertTrue(detail['rows'][0]['summary']['truncated'])

    def test_timeout_has_actionable_http_error_and_server_remains_usable(self):
        server, token=make_server(self.explorer)
        threading.Thread(target=server.serve_forever,daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        conn=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=5)
        self.addCleanup(conn.close)
        sql='WITH RECURSIVE n(x) AS (VALUES(1) UNION ALL SELECT x+1 FROM n WHERE x<1000000) SELECT sum(x) FROM n'
        with patch('evomneme_viewer.QUERY_SECONDS',0):
            conn.request('POST','/api/query',body=json.dumps({'sql':sql}),headers={'X-Viewer-Token':token})
            response=conn.getresponse()
            self.assertEqual(response.status,400)
            message=json.loads(response.read())['error']
        self.assertIn('time limit',message)
        self.assertNotIn('interrupted',message)
        conn.request('POST','/api/snapshot',body='{}',headers={'X-Viewer-Token':token})
        response=conn.getresponse()
        self.assertEqual(response.status,200)
        self.assertEqual(json.loads(response.read())['totals']['nodes'],8)
        conn.request('POST','/api/replay',body='{}')
        response = conn.getresponse()
        self.assertEqual(response.status,403)
        response.read()
        conn.request('POST','/api/replay',body='{}',headers={'X-Viewer-Token':token})
        response = conn.getresponse()
        self.assertEqual(response.status,200)
        replay = json.loads(response.read())
        self.assertEqual(len(replay['nodes']),8)
        self.assertIn('events',replay)

    def test_whole_database_grouping_uses_all_members_not_browser_page(self):
        overview = self.explorer.snapshot({'aggregate':'kind','limit':2})
        self.assertEqual(overview['matched_nodes'],4)
        self.assertEqual(overview['grouped_members'],8)
        self.assertEqual(overview['totals'],{'nodes':8,'edges':4})
        self.assertTrue(overview['node_has_more'])
        self.assertEqual([n['member_count'] for n in overview['nodes']],[2,2])
        all_groups = self.explorer.snapshot({'aggregate':'kind'})
        self.assertEqual(sum(n['member_count'] for n in all_groups['nodes']),8)
        self.assertEqual(sum(e['member_count'] for e in all_groups['edges']),4)
        module = next(n for n in all_groups['nodes'] if n['group_value']=='module')
        self.assertEqual(module['without_evidence_count'],0)
        self.assertEqual(module['current_count'],2)
        self.assertEqual(self.explorer.snapshot({'aggregate':'kind','scope_id':'main'})['grouped_members'],4)
        filtered = self.explorer.snapshot({'aggregate':'kind','edge_confidence':'confirmed'})
        self.assertEqual(filtered['edges'],[])

    def test_custom_projection_on_v3_and_rejection_of_arbitrary_store(self):
        db = sqlite3.connect(self.path)
        db.executescript('CREATE TABLE things(k TEXT,label TEXT); CREATE TABLE links(k TEXT,a TEXT,b TEXT); INSERT INTO things VALUES(\'a\',\'A\'),(\'b\',\'B\'); INSERT INTO links VALUES(\'e\',\'a\',\'b\'),(\'broken\',\'b\',\'missing\');')
        db.close()
        explorer = Explorer(self.path, {'nodes':'SELECT k AS graph_id,label FROM things','edges':'SELECT k AS graph_id,a AS source,b AS target FROM links'})
        data = explorer.snapshot({})
        self.assertEqual(data['totals'], {'nodes':2,'edges':2})
        self.assertEqual(data['dangling_total'], 1)
        self.assertEqual(len(data['edges']), 1)
        layered = Explorer(self.path,{'nodes':"SELECT k AS graph_id,label,NULL AS layer FROM things",
                                      'edges':"SELECT k AS graph_id,a AS source,b AS target,'links' AS layer FROM links"})
        self.addCleanup(layered.close)
        graph = layered.snapshot({'whole_graph':True,'excluded_layers':['links']})
        self.assertEqual({n['layer'] for n in graph['nodes']},{'custom'})
        self.assertEqual(graph['edges'],[])
        empty = self.directory / 'arbitrary.sqlite3'
        db = sqlite3.connect(empty)
        db.execute('CREATE TABLE custom(value)')
        db.close()
        with self.assertRaisesRegex(ValueError, 'requires v3'):
            Explorer(empty)

    def test_trace_context_bounded_returned_ids_rollback_and_incremental_cursors(self):
        executor = Executor(self.path)
        self.addCleanup(executor.close)
        traces = self.directory / 'activity'
        configure_trace(executor, traces, 'default')
        result = executor.execute_sql(sql='SELECT scope_id,id FROM nodes WHERE scope_id=?',params=['main'],max_rows=1,
                                      activity_context={'chat_id':'parent','session_id':'work','agent_id':'worker'})
        self.assertTrue(result['ok'])
        executor.execute_sql(sql=[{'sql':'BEGIN'},{'sql':"UPDATE nodes SET title='rolled back'"}])
        executor.execute_sql(sql='SELECT count(*) AS n FROM nodes')
        executor.execute_sql(sql='SELECT id AS trace_node_id FROM nodes LIMIT 1')
        view = Explorer(self.path, trace_directory=traces)
        first = view.events({})
        self.assertEqual(len(first['events']), 4)
        event = next(e for e in first['events'] if e['chat']=='parent')
        self.assertEqual((event['session'],event['agent']),('work','worker'))
        self.assertEqual(event['references'], [{'table':'nodes','scope_id':'main','id':'0'}])
        self.assertTrue(event['has_more'])
        self.assertTrue(first['events'][1]['rolled_back'])
        self.assertEqual(first['events'][2]['references'], [])
        self.assertEqual(first['events'][3]['references'][0]['graph_type'], 'nodes')
        self.assertEqual(view.events({'cursors':first['cursors'], 'after_id':first['after_id']})['events'], [])
        content = executor.activity_log.path.read_text()
        self.assertNotIn('SELECT',content)
        self.assertNotIn('rolled back',content)
        with executor.activity_log.path.open('ab') as stream:
            stream.write(b'{"incomplete":')
        self.assertEqual(view.events({'cursors':first['cursors']})['cursors'], first['cursors'])

    def test_invalid_context_cannot_write_and_trace_is_optional(self):
        executor = Executor(self.path)
        self.addCleanup(executor.close)
        for value in ({'other':'x'}, {'chat_id':''}, {'session_id':42}, {'chat_title':42}, {'agent_name':''}, ['x']):
            result = executor.execute_sql(sql='DELETE FROM nodes',activity_context=value)
            self.assertFalse(result['ok'])
        self.assertFalse((self.directory / 'activity').exists())
        self.assertEqual(len(executor.execute_sql(sql='SELECT * FROM nodes')['results'][0]['rows']),8)

    def test_trace_io_failure_preserves_committed_sql(self):
        executor = Executor(self.path)
        self.addCleanup(executor.close)
        configure_trace(executor, self.directory / 'activity', 'session')
        executor.activity_log.path = self.directory / 'missing-directory' / 'log.jsonl'
        with contextlib.redirect_stderr(io.StringIO()) as diagnostic:
            result = executor.execute_sql(sql="UPDATE nodes SET title='committed' WHERE scope_id='main' AND id='0'")
        self.assertTrue(result['ok'])
        self.assertTrue(executor.activity_log.disabled)
        self.assertIn('tracing disabled', diagnostic.getvalue())
        self.assertEqual(self.explorer.query({'sql':"SELECT title FROM nodes WHERE scope_id='main' AND id='0'"})['rows'][0]['title'],'committed')

    def test_relationship_row_and_value_bounds_are_explicit(self):
        db = sqlite3.connect(self.path)
        db.executescript("CREATE TABLE tiny(k TEXT,label TEXT); INSERT INTO tiny VALUES('a','A'),('b','B'); CREATE TABLE many(k TEXT,a TEXT,b TEXT); WITH RECURSIVE n(x) AS (SELECT 1 UNION ALL SELECT x+1 FROM n WHERE x<2101) INSERT INTO many SELECT CAST(x AS TEXT),'a','b' FROM n;")
        db.execute('CREATE TABLE large(value TEXT)')
        db.execute('INSERT INTO large VALUES(?)', ['x'*17000])
        db.commit()
        db.close()
        explorer = Explorer(self.path, {'nodes':'SELECT k AS graph_id,label FROM tiny','edges':'SELECT k AS graph_id,a AS source,b AS target FROM many'})
        snapshot = explorer.snapshot({})
        self.assertEqual(snapshot['totals']['edges'],2101)
        self.assertEqual(len(snapshot['edges']),2000)
        self.assertTrue(snapshot['edge_has_more'])
        self.assertEqual(len(explorer.query({'sql':'SELECT * FROM many'})['rows']),200)
        self.assertTrue(explorer.query({'sql':'SELECT * FROM many'})['has_more'])
        self.assertTrue(explorer.query({'sql':'SELECT * FROM large'})['rows'][0]['value']['truncated'])

    def test_cli_and_mcp_context_trace_contract(self):
        args = {'sql':'SELECT scope_id,id FROM nodes LIMIT 1','activity_context':{
            'chat_id':'parent','session_id':'s','agent_id':'a',
            'chat_title':'Memory explorer work','session_title':'Investigating graph activity','agent_name':'Main agent'}}
        trace = self.directory / 'activity'
        cli = subprocess.run([sys.executable,str(ROOT/'scripts/evomneme.py'),'--database',str(self.path),'--trace-directory',str(trace),'--session-id','fallback','--input','-'],input=json.dumps(args).encode(),capture_output=True)
        self.assertEqual(cli.returncode,0,cli.stderr)
        messages = [{'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2025-11-25','capabilities':{},'clientInfo':{'name':'Codex-test','version':'fixture'}}},{'jsonrpc':'2.0','method':'notifications/initialized'}, {'jsonrpc':'2.0','id':2,'method':'tools/call','params':{'name':'execute_sql','arguments':args}}]
        wire = subprocess.run([sys.executable,str(ROOT/'scripts/evomneme_mcp.py'),'--database',str(self.path),'--trace-directory',str(trace),'--session-id','fallback'],input=b''.join(json.dumps(m).encode()+b'\n' for m in messages),capture_output=True)
        self.assertEqual(wire.returncode,0,wire.stderr)
        response = json.loads(wire.stdout.splitlines()[-1])['result']['structuredContent']
        self.assertEqual(response,json.loads(cli.stdout))
        events = Explorer(self.path,trace_directory=trace).events({})['events']
        self.assertEqual({e['chat'] for e in events},{'parent'})
        self.assertEqual({e['chat_title'] for e in events},{'Memory explorer work'})
        self.assertEqual({e['session_title'] for e in events},{'Investigating graph activity'})
        self.assertEqual({e['agent_name'] for e in events},{'Main agent'})
        self.assertEqual({e['client']['name'] for e in events},{'EvoMneme CLI','Codex-test'})
        self.assertTrue(all(e['identity']['chat'] and e['identity']['agent'] for e in events))

    def test_http_token_origin_assets_and_post_queries(self):
        server, token = make_server(self.explorer)
        thread = threading.Thread(target=server.serve_forever,daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        conn = http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=5)
        self.addCleanup(conn.close)
        conn.request('POST','/api/snapshot',body='{}',headers={'Content-Type':'application/json'})
        response = conn.getresponse()
        self.assertEqual(response.status,403)
        response.read()
        conn.request('POST','/api/snapshot',body='{}',headers={'X-Viewer-Token':token,'Origin':'https://foreign.invalid'})
        response = conn.getresponse()
        self.assertEqual(response.status,403)
        response.read()
        conn.request('POST','/api/snapshot',body='{}',headers={'X-Viewer-Token':token})
        response = conn.getresponse()
        self.assertEqual(response.status,200)
        self.assertEqual(json.loads(response.read())['totals']['nodes'],8)
        for path in ('/','/app.js','/graph-layout.js','/layout-worker.js','/style.css','/cytoscape.min.js'):
            conn.request('GET',path)
            response=conn.getresponse()
            self.assertEqual(response.status,200)
            self.assertIn("default-src 'self'",response.getheader('Content-Security-Policy'))
            self.assertTrue(response.read())

    def test_vendor_integrity(self):
        folder = ROOT / 'scripts/viewer/vendor'
        manifest = json.loads((folder / 'manifest.json').read_text())
        for file, metadata in manifest['files'].items():
            self.assertEqual(hashlib.sha256((folder / file).read_bytes()).hexdigest(), metadata['sha256'])


if __name__ == '__main__':
    if '--serve-demo' in sys.argv:
        area=ROOT/'.evomneme-tests'/'viewer-demo-v3'
        area.mkdir(parents=True,exist_ok=True)
        path=area/'host.sqlite3'
        if not path.exists():
            fixture(path)
        with contextlib.closing(sqlite3.connect(path)) as check:
            has_code = check.execute("SELECT 1 FROM nodes WHERE scope_id='main' AND id='c0'").fetchone()
        if not has_code:
            code_fixture(path)
        explorer=Explorer(path,trace_directory=area/'activity')
        server,token=make_server(explorer)
        print(f'http://127.0.0.1:{server.server_port}/#token={token}',flush=True)
        server.serve_forever()
    else:
        unittest.main()
