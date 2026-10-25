"""Synthetic host-only explorer, activity and loopback boundary checks."""

import hashlib
import contextlib
import http.client
import io
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest

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
            db.execute('INSERT INTO records(scope_id,id,kind,title,summary,confidence,validity,source_path,updated_at) VALUES(?,?,?,?,?,?,?,?,?)',
                       (scope, str(i), kind, scope + ' node ' + str(i), 'Synthetic <script>alert(1)</script>', confidence, validity, 'src/example.py', '2026-10-25'))
        for i in range(2):
            db.execute('INSERT INTO relations(scope_id,id,source_id,target_id,kind,summary,confidence,validity,updated_at) VALUES(?,?,?,?,?,?,?,?,?)',
                       (scope, 'e'+str(i), str(i), str(i+1), 'depends_on', 'Synthetic relationship', 'inferred', 'current', '2026-10-25'))
        db.execute('INSERT INTO evidence(scope_id,id,record_id,description,validity,updated_at) VALUES(?,?,?,?,?,?)', (scope, 'proof', '0', 'Observed synthetic fixture', 'current', '2026-10-25'))
    db.commit()
    db.close()


class ViewerTests(unittest.TestCase):
    def setUp(self):
        area = ROOT / '.evomneme-tests'
        area.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=area)
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.path = self.directory / 'host.sqlite3'
        fixture(self.path)
        self.explorer = Explorer(self.path)

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
        self.assertEqual(len(self.explorer.query({'sql':'SELECT * FROM records'})['rows']), 8)
        for sql in ('DELETE FROM records RETURNING *', 'PRAGMA query_only=OFF', "SELECT load_extension('x')", 'SELECT * FROM pragma_query_only(0)'):
            with self.assertRaises((ValueError, sqlite3.Error)):
                self.explorer.query({'sql':sql})
        detail = self.explorer.detail({'type':'nodes', 'id':'["main","0"]'})
        self.assertEqual(len(detail['evidence']), 1)
        self.assertEqual(detail['rows'][0]['scope_id'], 'main')
        self.assertEqual(before, self.path.read_bytes())

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

    def test_custom_schema_mapping_and_generic_inspection(self):
        db = sqlite3.connect(self.path)
        db.executescript('CREATE TABLE things(k TEXT,label TEXT); CREATE TABLE links(k TEXT,a TEXT,b TEXT); INSERT INTO things VALUES(\'a\',\'A\'),(\'b\',\'B\'); INSERT INTO links VALUES(\'e\',\'a\',\'b\'),(\'broken\',\'b\',\'missing\');')
        db.close()
        explorer = Explorer(self.path, {'nodes':'SELECT k AS graph_id,label FROM things','edges':'SELECT k AS graph_id,a AS source,b AS target FROM links'})
        data = explorer.snapshot({})
        self.assertEqual(data['totals'], {'nodes':2,'edges':2})
        self.assertEqual(data['dangling_total'], 1)
        self.assertEqual(len(data['edges']), 1)
        empty = self.directory / 'arbitrary.sqlite3'
        db = sqlite3.connect(empty)
        db.execute('CREATE TABLE custom(value)')
        db.close()
        data = Explorer(empty).snapshot({})
        self.assertFalse(data['graph_available'])
        self.assertEqual(data['tables'][0]['name'], 'custom')

    def test_trace_context_bounded_returned_ids_rollback_and_incremental_cursors(self):
        executor = Executor(self.path)
        self.addCleanup(executor.close)
        traces = self.directory / 'activity'
        configure_trace(executor, traces, 'default')
        result = executor.execute_sql(sql='SELECT scope_id,id FROM records WHERE scope_id=?',params=['main'],max_rows=1,
                                      activity_context={'chat_id':'parent','session_id':'work','agent_id':'worker'})
        self.assertTrue(result['ok'])
        executor.execute_sql(sql=[{'sql':'BEGIN'},{'sql':"UPDATE records SET title='rolled back'"}])
        executor.execute_sql(sql='SELECT count(*) AS n FROM records')
        executor.execute_sql(sql='SELECT id AS trace_node_id FROM records LIMIT 1')
        view = Explorer(self.path, trace_directory=traces)
        first = view.events({})
        self.assertEqual(len(first['events']), 4)
        event = next(e for e in first['events'] if e['chat']=='parent')
        self.assertEqual((event['session'],event['agent']),('work','worker'))
        self.assertEqual(event['references'], [{'table':'records','scope_id':'main','id':'0'}])
        self.assertTrue(event['has_more'])
        self.assertTrue(first['events'][1]['rolled_back'])
        self.assertEqual(first['events'][2]['references'], [])
        self.assertEqual(first['events'][3]['references'][0]['graph_type'], 'nodes')
        self.assertEqual(view.events({'cursors':first['cursors']})['events'], [])
        content = executor.activity_log.path.read_text()
        self.assertNotIn('SELECT',content)
        self.assertNotIn('rolled back',content)
        with executor.activity_log.path.open('ab') as stream:
            stream.write(b'{"incomplete":')
        self.assertEqual(view.events({'cursors':first['cursors']})['cursors'], first['cursors'])

    def test_invalid_context_cannot_write_and_trace_is_optional(self):
        executor = Executor(self.path)
        self.addCleanup(executor.close)
        for value in ({'other':'x'}, {'chat_id':''}, {'session_id':42}, ['x']):
            result = executor.execute_sql(sql='DELETE FROM records',activity_context=value)
            self.assertFalse(result['ok'])
        self.assertFalse((self.directory / 'activity').exists())
        self.assertEqual(len(executor.execute_sql(sql='SELECT * FROM records')['results'][0]['rows']),8)

    def test_trace_io_failure_preserves_committed_sql(self):
        executor = Executor(self.path)
        self.addCleanup(executor.close)
        configure_trace(executor, self.directory / 'activity', 'session')
        executor.activity_log.path = self.directory / 'missing-directory' / 'log.jsonl'
        with contextlib.redirect_stderr(io.StringIO()) as diagnostic:
            result = executor.execute_sql(sql="UPDATE records SET title='committed' WHERE scope_id='main' AND id='0'")
        self.assertTrue(result['ok'])
        self.assertTrue(executor.activity_log.disabled)
        self.assertIn('tracing disabled', diagnostic.getvalue())
        self.assertEqual(self.explorer.query({'sql':"SELECT title FROM records WHERE scope_id='main' AND id='0'"})['rows'][0]['title'],'committed')

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
        args = {'sql':'SELECT scope_id,id FROM records LIMIT 1','activity_context':{'chat_id':'parent','session_id':'s','agent_id':'a'}}
        trace = self.directory / 'activity'
        cli = subprocess.run([sys.executable,str(ROOT/'scripts/evomneme.py'),'--database',str(self.path),'--trace-directory',str(trace),'--session-id','fallback','--input','-'],input=json.dumps(args).encode(),capture_output=True)
        self.assertEqual(cli.returncode,0,cli.stderr)
        messages = [{'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2025-11-25','capabilities':{},'clientInfo':{}}},{'jsonrpc':'2.0','method':'notifications/initialized'}, {'jsonrpc':'2.0','id':2,'method':'tools/call','params':{'name':'execute_sql','arguments':args}}]
        wire = subprocess.run([sys.executable,str(ROOT/'scripts/evomneme_mcp.py'),'--database',str(self.path),'--trace-directory',str(trace),'--session-id','fallback'],input=b''.join(json.dumps(m).encode()+b'\n' for m in messages),capture_output=True)
        self.assertEqual(wire.returncode,0,wire.stderr)
        response = json.loads(wire.stdout.splitlines()[-1])['result']['structuredContent']
        self.assertEqual(response,json.loads(cli.stdout))
        self.assertEqual({e['chat'] for e in Explorer(self.path,trace_directory=trace).events({})['events']},{'parent'})

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
        for path in ('/','/app.js','/style.css','/cytoscape.min.js'):
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
        area=ROOT/'.evomneme-tests'/'viewer-demo'
        area.mkdir(parents=True,exist_ok=True)
        path=area/'host.sqlite3'
        if not path.exists():
            fixture(path)
        explorer=Explorer(path,trace_directory=area/'activity')
        server,token=make_server(explorer)
        print(f'http://127.0.0.1:{server.server_port}/#token={token}',flush=True)
        server.serve_forever()
    else:
        unittest.main()
