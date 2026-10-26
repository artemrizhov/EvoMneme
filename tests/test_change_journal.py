"""Transactional change history on isolated v3 fixtures, never a live host."""

import concurrent.futures
from contextlib import closing
import json
import http.client
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT/'scripts'))
from evomneme_journal import install, read, status, LOG, LINKS, META
from evomneme_viewer import Explorer, make_server


class JournalTests(unittest.TestCase):
    def setUp(self):
        area=ROOT/'.evomneme-tests'
        area.mkdir(exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=area)
        self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'host.sqlite3'
        with closing(sqlite3.connect(self.path)) as db:
            db.executescript((ROOT/'schema.sql').read_text(encoding='utf-8'))
            db.execute("INSERT INTO scopes VALUES('main','main','fixture','r','s','2026-10-26')")
            db.commit()

    def writer(self):
        db=sqlite3.connect(self.path,timeout=5)
        db.execute('PRAGMA foreign_keys=ON')
        self.addCleanup(db.close)
        return db

    def insert_node(self,db,id='n1',title='Fixture node'):
        db.execute("INSERT INTO nodes(scope_id,id,kind,title,summary,confidence,validity,updated_at,layer) VALUES('main',?,'function',?,'fixture','inferred','current','now','code')",(id,title))

    def events(self,**values):
        viewer=Explorer(self.path)
        self.addCleanup(viewer.close)
        return viewer.changes(values)

    def test_optout_readonly_and_automatic_default(self):
        before=self.path.read_bytes()
        viewer=Explorer(self.path,history=False)
        self.addCleanup(viewer.close)
        self.assertFalse(viewer.changes({})['journal']['enabled'])
        viewer.snapshot({'whole_graph':True})
        self.assertEqual(before,self.path.read_bytes())
        installed=install(self.path)
        self.assertTrue(installed['enabled'])
        self.assertIn('nodes',installed['tracked_tables'])
        self.assertEqual(self.events()['events'],[],'Existing rows are not fabricated as historical changes')
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0],3)
            self.assertEqual(db.execute("SELECT value FROM metadata WHERE key='schema_version'").fetchone()[0],'3')

    def test_row_changes_links_and_reload(self):
        install(self.path)
        db=self.writer()
        self.insert_node(db)
        db.commit()
        db.execute("UPDATE nodes SET title='Updated title' WHERE id='n1'")
        db.commit()
        db.execute("UPDATE nodes SET title=title WHERE id='n1'")
        db.commit()
        db.execute("DELETE FROM nodes WHERE id='n1'")
        db.commit()
        events=self.events()['events']
        self.assertEqual([e['operation'] for e in events],['insert','update','delete'])
        self.assertEqual(events[1]['before']['title']['value'],'Fixture node')
        self.assertEqual(events[1]['after']['title']['value'],'Updated title')
        self.assertEqual(events[2]['removed'],['n:["main","n1"]'])
        self.assertTrue(all(e['references'] for e in events))
        self.assertTrue(all(e['references'][0]['graph_id']=='["main","n1"]' for e in events))
        self.assertEqual([e['change_id'] for e in self.events()['events']],[e['change_id'] for e in events])
        self.assertEqual(self.events(after_id=events[-1]['change_id'])['events'],[])

    def test_rollback_constraint_failure_and_savepoint_do_not_create_history(self):
        install(self.path)
        db=self.writer()
        self.insert_node(db,'rollback')
        db.rollback()
        self.assertEqual(self.events()['events'],[])
        self.insert_node(db,'kept')
        db.execute('SAVEPOINT part')
        db.execute("UPDATE nodes SET title='temporary' WHERE id='kept'")
        db.execute('ROLLBACK TO part')
        db.execute('RELEASE part')
        db.commit()
        try:
            self.insert_node(db,'kept')
        except sqlite3.IntegrityError:
            db.rollback()
        self.assertEqual([e['operation'] for e in self.events()['events']],['insert'])

    def test_multirow_writes_one_entry_per_row_and_concurrent_writers(self):
        install(self.path)
        def work(worker):
            with closing(sqlite3.connect(self.path,timeout=5)) as db:
                for i in range(12):
                    self.insert_node(db,str(worker)+'-'+str(i))
                db.commit()
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            list(pool.map(work,range(3)))
        db=self.writer()
        db.execute("UPDATE nodes SET title='all updated'")
        db.commit()
        events=self.events(limit=200)['events']
        self.assertEqual(len(events),72)
        self.assertEqual(len({e['change_id'] for e in events}),72)
        self.assertEqual(sum(e['operation']=='update' for e in events),36)
        for event in events:
            self.assertTrue(all(r['graph_id'].endswith('"'+event['after']['id']['value']+'"]') for r in event['references']))

    def test_edge_and_metadata_rows_link_to_graph_and_survive_deletion(self):
        install(self.path)
        db=self.writer()
        self.insert_node(db,'n1');self.insert_node(db,'n2')
        db.execute("INSERT INTO edges(scope_id,id,source_id,target_id,kind,summary,confidence,validity,updated_at,layer) VALUES('main','e1','n1','n2','calls','fixture','inferred','current','now','code')")
        db.execute("INSERT INTO symbol_details VALUES('main','n1','Fixture.call','def call(','python')")
        db.execute("INSERT INTO evidence(scope_id,id,node_id,description,validity,updated_at) VALUES('main','proof','n1','fixture','current','now')")
        db.commit()
        db.execute("DELETE FROM evidence WHERE id='proof'")
        db.execute("DELETE FROM edges WHERE id='e1'")
        db.commit()
        events=self.events()['events']
        detail=next(e for e in events if e['table']=='symbol_details')
        self.assertEqual(detail['references'][0]['graph_id'],'["main","n1"]')
        deleted_proof=next(e for e in events if e['table']=='evidence' and e['operation']=='delete')
        self.assertEqual(deleted_proof['removed'],[])
        self.assertEqual(deleted_proof['changed'],['n:["main","n1"]'])
        deleted_edge=next(e for e in events if e['table']=='edges' and e['operation']=='delete')
        self.assertEqual(deleted_edge['removed'],['e:["main","e1"]'])
        self.assertEqual(deleted_edge['before']['source_id']['value'],'n1')

    def test_primary_key_rename_keeps_both_graph_identities(self):
        install(self.path)
        db=self.writer()
        self.insert_node(db,'old')
        db.commit()
        db.execute("UPDATE nodes SET id='new' WHERE id='old'")
        db.commit()
        renamed=self.events()['events'][-1]
        self.assertEqual(renamed['removed'],['n:["main","old"]'])
        self.assertEqual(renamed['changed'],['n:["main","new"]'])
        self.assertEqual({r['graph_id'] for r in renamed['references']},{'["main","old"]','["main","new"]'})

    def test_changes_api_reads_saved_history_but_cannot_mutate_database(self):
        viewer=Explorer(self.path,record_changes=True)
        self.addCleanup(viewer.close)
        db=self.writer()
        self.insert_node(db)
        db.commit()
        server,token=make_server(viewer)
        threading.Thread(target=server.serve_forever,daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        conn=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=5)
        self.addCleanup(conn.close)
        conn.request('POST','/api/changes',body='{}')
        response=conn.getresponse()
        self.assertEqual(response.status,403);response.read()
        conn.request('POST','/api/changes',body='{}',headers={'X-Viewer-Token':token})
        response=conn.getresponse()
        self.assertEqual(response.status,200)
        data=json.loads(response.read())
        self.assertEqual(data['events'][0]['references'][0]['graph_id'],'["main","n1"]')
        conn.request('POST','/api/query',body=json.dumps({'sql':'DELETE FROM nodes RETURNING *'}),headers={'X-Viewer-Token':token})
        response=conn.getresponse()
        self.assertEqual(response.status,400);response.read()
        self.assertEqual(db.execute('SELECT count(*) FROM nodes').fetchone()[0],1)
        snapshot=viewer.snapshot({'whole_graph':True})
        self.assertTrue(snapshot['journal']['enabled'])
        self.assertEqual(snapshot['totals']['nodes'],1)

    def test_pagination_cleanup_and_idempotent_install(self):
        install(self.path)
        db=self.writer()
        for i in range(9): self.insert_node(db,str(i))
        db.commit()
        recent=self.events(limit=3)
        self.assertEqual([e['change_id'] for e in recent['events']],[7,8,9])
        older=self.events(limit=3,before_id=recent['before_id'])
        self.assertEqual([e['change_id'] for e in older['events']],[4,5,6])
        self.assertTrue(older['has_older'])
        install(self.path)
        self.assertEqual(len(self.events()['events']),9)
        db.execute('PRAGMA foreign_keys=OFF')
        db.execute('DELETE FROM '+LOG+' WHERE id=1')
        db.commit()
        self.assertEqual(db.execute('SELECT count(*) FROM '+LINKS+' WHERE change_id=1').fetchone()[0],0)

    def test_bounded_typed_snapshots_blobs_nulls_quotes_and_wide_rows(self):
        db=self.writer()
        db.execute('CREATE TABLE arbitrary(id INTEGER PRIMARY KEY,payload BLOB,text TEXT,real_value REAL)')
        columns=','.join('c'+str(i)+' TEXT' for i in range(30))
        db.execute('CREATE TABLE wide('+columns+')')
        db.commit()
        install(self.path)
        db.execute('INSERT INTO arbitrary VALUES(?,?,?,?)',(1,b'\x00\xff'*20000,'<script>"quoted" 世界</script>'+'x'*50000,float('inf')))
        db.execute('INSERT INTO wide(c29) VALUES(NULL)')
        db.commit()
        changes=self.events()['events']
        raw=next(e for e in changes if e['table']=='arbitrary')['after']
        self.assertEqual(raw['payload']['type'],'blob')
        self.assertTrue(raw['payload']['truncated'])
        self.assertTrue(raw['text']['truncated'])
        self.assertEqual(raw['real_value']['value'],'Infinity')
        wide=next(e for e in changes if e['table']=='wide')['after']
        self.assertEqual(wide['c29']['type'],'null')
        self.assertIsNone(wide['c29']['value'])

    def test_byte_limited_pages_do_not_skip_changes(self):
        db=self.writer()
        db.execute('CREATE TABLE large_rows(id INTEGER PRIMARY KEY,a TEXT,b TEXT)')
        db.commit()
        install(self.path)
        for i in range(40):
            db.execute('INSERT INTO large_rows VALUES(?,?,?)',(i,'界'*20000,'界'*20000))
        db.commit()
        recent=self.events(limit=200)
        self.assertLess(len(recent['events']),40)
        self.assertEqual(recent['events'][-1]['change_id'],40)
        ids=[e['change_id'] for e in recent['events']]
        while recent['has_older']:
            recent=self.events(limit=200,before_id=recent['before_id'])
            ids=[e['change_id'] for e in recent['events']]+ids
        self.assertEqual(ids,list(range(1,41)))
        forward=self.events(limit=200,after_id=0)
        ids=[e['change_id'] for e in forward['events']]
        while forward['has_more']:
            forward=self.events(limit=200,after_id=forward['after_id'])
            ids += [e['change_id'] for e in forward['events']]
        self.assertEqual(ids,list(range(1,41)))

    def test_schema_refresh_and_suspension_preserve_existing_history(self):
        viewer=Explorer(self.path,record_changes=True)
        self.addCleanup(viewer.close)
        db=self.writer()
        self.insert_node(db)
        db.commit()
        db.execute('CREATE TABLE later(id INTEGER PRIMARY KEY,value TEXT)')
        db.commit()
        viewer.changes({})
        db.execute("INSERT INTO later VALUES(1,'future tracked row')")
        db.commit()
        self.assertTrue(any(e['table']=='later' for e in viewer.changes({})['events']))
        # Stop management before suspending for an intentional schema migration.
        viewer.manage_changes=False
        install(self.path,suspend=True)
        db.execute("UPDATE nodes SET title='not recorded while suspended'")
        db.commit()
        self.assertEqual(len(viewer.changes({})['events']),2)
        self.assertFalse(viewer.changes({})['journal']['enabled'])
        install(self.path)
        db.execute("UPDATE nodes SET title='recording resumed'")
        db.commit()
        self.assertEqual(len(viewer.changes({})['events']),3)

    def test_reserved_table_collision_preserves_source_database(self):
        db=self.writer()
        db.execute('CREATE TABLE '+LOG+'(user_data TEXT)')
        db.execute('INSERT INTO '+LOG+" VALUES('keep this')")
        db.commit()
        with self.assertRaisesRegex(ValueError,'already exist'):
            install(self.path)
        self.assertEqual(db.execute('SELECT user_data FROM '+LOG).fetchone()[0],'keep this')
        self.assertFalse(db.execute("SELECT 1 FROM sqlite_schema WHERE name=?",[META]).fetchone())

    def test_cli_opt_in_and_graph_ids(self):
        process=subprocess.run([sys.executable,str(ROOT/'scripts/evomneme_journal.py'),'install','--database',str(self.path)],capture_output=True)
        self.assertEqual(process.returncode,0,process.stderr)
        self.assertTrue(json.loads(process.stdout)['enabled'])
        db=self.writer()
        self.insert_node(db)
        db.commit()
        events=read(db,{})['events']
        self.assertEqual(events[0]['references'][0]['graph_id'],'["main","n1"]')


if __name__=='__main__':
    unittest.main()
