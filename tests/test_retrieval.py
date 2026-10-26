"""Executable retrieval recipes against synthetic v3 data; --compare prints a probe."""
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from evomneme import Executor


def fixture(path):
    db = sqlite3.connect(path)
    db.executescript((ROOT / 'schema.sql').read_text(encoding='utf-8'))
    for scope in ('main', 'other'):
        db.execute('INSERT INTO scopes VALUES(?,?,?,?,?,?)', (scope, 'branch', 'synthetic', 'rev', 'snapshot', 'now'))

    def node(id_, title, kind='function', validity='current', scope='main', path='src/core.py', confidence='confirmed'):
        db.execute('''INSERT INTO nodes(scope_id,id,kind,title,summary,confidence,validity,
            source_path,source_hash,line_start,line_end,updated_at,layer)
            VALUES(?,?,?,?,?,?,?,?,?,10,12,'now','code')''',
                   (scope, id_, kind, title, 'Synthetic responsibility', confidence, validity, path, 'hash'))

    for term, noise in [('billing', 'rebilling'), ('session', 'possession'), ('policy', 'policyholder')]:
        node('z-' + term, term)
        node('decision-' + term, 'boundary choice', 'decision', confidence='uncertain')
        for index in range(12):
            node('noise-' + term + '-' + str(index).zfill(2), noise)
        node('stale-' + term, term, validity='stale')
        node('z-' + term, term, scope='other')
        if term != 'policy':
            db.execute('''INSERT INTO edges(scope_id,id,source_id,target_id,kind,summary,
                confidence,validity,updated_at) VALUES('main',?,?,?,'constrains',
                'Synthetic incoming boundary','inferred','current','now')''',
                       ('edge-' + term, 'decision-' + term, 'z-' + term))
            db.execute('''INSERT INTO evidence(scope_id,id,edge_id,description,source_path,
                source_hash,validity,updated_at) VALUES('main',?,?,'Synthetic source read',
                'src/core.py','hash','current','now')''', ('proof-' + term, 'edge-' + term))
    node('literal-percent', 'rate%')
    node('literal-other', 'rateX')
    node('tie-a', 'tied', path='src/a.py')
    node('tie-b', 'tied', path='src/b.py')
    node('tie-c', 'tied', path='vendor/a.py')
    db.commit()
    db.close()


def execute(executor, recipe, **params):
    defaults = dict(scope='main', after_id=None, limit=8)
    defaults.update(params)
    result = executor.execute_sql(sql=(ROOT / 'queries' / (recipe + '.sql')).read_text(encoding='utf-8'),
                                  params=defaults, max_rows=defaults['limit'], max_output_bytes=12000)
    if not result['ok']:
        raise AssertionError(result)
    return result


def rows(result):
    table = result['results'][0]
    return [dict(zip(table['columns'], row)) for row in table['rows']]


def anchor(executor, query, **params):
    defaults = dict(query=query, mode='exact', path_prefix=None)
    defaults.update(params)
    return execute(executor, 'anchors', **defaults)


def comparison(executor):
    """Same task term/scope/budget, predefined relevant IDs; bytes include envelopes."""
    reports = []
    for term in ('billing', 'session', 'policy'):
        baseline = executor.execute_sql(sql='''SELECT scope_id,id,kind,layer,title,summary,
            confidence,validity,source_path,source_hash,line_start,line_end FROM nodes
            WHERE scope_id=:scope AND validity='current' AND title LIKE :query ORDER BY id LIMIT 9''',
            params={'scope': 'main', 'query': '%' + term + '%'}, max_rows=8, max_output_bytes=12000)
        exact_lexical = executor.execute_sql(sql='''SELECT scope_id,id,kind,layer,title,summary,
            confidence,validity,source_path,source_hash,line_start,line_end FROM nodes
            WHERE scope_id=:scope AND validity='current' AND title=:query ORDER BY id LIMIT 9''',
            params={'scope': 'main', 'query': term}, max_rows=8, max_output_bytes=12000)
        seeds = anchor(executor, term)
        calls = [seeds]
        hop_calls = [seeds]
        relevant = {'z-' + term, 'decision-' + term}
        found = {row['id'] for row in rows(seeds)}
        for seed in rows(seeds):
            incident = execute(executor, 'incident', root=seed['id'], edge_kind=None)
            calls.append(incident)
            hop_calls.append(incident)
            for edge in rows(incident):
                found.add(edge['neighbor_id'])
                calls.append(execute(executor, 'evidence', target_type='edge', target=edge['edge_id']))
        size = lambda values: sum(len(json.dumps(v, ensure_ascii=False, separators=(',', ':')).encode('utf-8')) for v in values)
        reports.append(dict(task_term=term, baseline_seed_relevant=len({r['id'] for r in rows(baseline)} & relevant),
                            exact_lexical_seed_relevant=len({r['id'] for r in rows(exact_lexical)} & relevant),
                            exact_lexical_matches_anchor_rows=rows(exact_lexical) == rows(seeds),
                            anchor_seed_relevant=len({r['id'] for r in rows(seeds)} & relevant),
                            expanded_relevant=len(found & relevant), expected_relevant=len(relevant),
                            expected_required_ids=sorted(relevant), found_required_ids=sorted(found & relevant),
                            baseline_irrelevant_hits=len({r['id'] for r in rows(baseline)} - relevant),
                            exact_lexical_irrelevant_hits=len({r['id'] for r in rows(exact_lexical)} - relevant),
                            anchor_irrelevant_hits=len({r['id'] for r in rows(seeds)} - relevant),
                            expanded_irrelevant_hits=len(found - relevant),
                            baseline_result_bytes=size([baseline]), new_all_result_bytes=size(calls),
                            exact_lexical_result_bytes=size([exact_lexical]), exact_lexical_calls=1,
                            anchor_only_result_bytes=size([seeds]), anchor_only_calls=1,
                            anchor_plus_hop_result_bytes=size(hop_calls), anchor_plus_hop_calls=len(hop_calls),
                            baseline_calls=1, new_calls=len(calls), missing_edge=(term == 'policy')))
    return {'synthetic_only': True, 'token_or_causal_savings_claim': False,
            'equal_sufficiency_time_measured': False,
            'interpretation': 'Exact lexical and anchors share seeds here; predicate precision removes substring noise. '
                              'Edges add stored dependencies at extra cost; missing edges remain missing.',
            'byte_metric': 'UTF-8 compact shared result objects including all new calls; excludes requests and MCP duplication',
            'scenarios': reports}


class RetrievalTests(unittest.TestCase):
    def setUp(self):
        area = ROOT / '.evomneme-tests'
        area.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=area)
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'retrieval.sqlite3'
        fixture(self.path)
        self.executor = Executor(self.path, history=False)
        self.addCleanup(self.executor.close)

    def test_literal_matching_scope_stale_and_path(self):
        self.assertEqual([r['id'] for r in rows(anchor(self.executor, 'billing'))], ['z-billing'])
        self.assertEqual([r['id'] for r in rows(anchor(self.executor, 'rate%', mode='prefix'))], ['literal-percent'])
        self.assertEqual([r['id'] for r in rows(anchor(self.executor, 'tied', path_prefix='src/'))], ['tie-a', 'tie-b'])
        self.assertEqual(rows(anchor(self.executor, 'absent')), [])
        self.assertEqual(rows(anchor(self.executor, '')), [])
        self.assertEqual(rows(anchor(self.executor, 'billing', mode='invented')), [])

    def test_deterministic_keyset_and_lookahead(self):
        first = anchor(self.executor, 'tied', limit=1)
        self.assertTrue(first['results'][0]['has_more'])
        self.assertEqual(rows(first)[0]['id'], 'tie-a')
        second = anchor(self.executor, 'tied', limit=1, after_id='tie-a')
        self.assertEqual(rows(second)[0]['id'], 'tie-b')
        last = anchor(self.executor, 'tied', limit=1, after_id='tie-b')
        self.assertEqual(rows(last)[0]['id'], 'tie-c')
        self.assertFalse(last['results'][0]['has_more'])

    def test_incoming_direction_uncertainty_and_evidence(self):
        edge = rows(execute(self.executor, 'incident', root='z-billing', edge_kind=None))[0]
        self.assertEqual((edge['source_id'], edge['target_id']), ('decision-billing', 'z-billing'))
        self.assertEqual(edge['neighbor_confidence'], 'uncertain')
        self.assertEqual(edge['edge_confidence'], 'inferred')
        self.assertEqual(edge['neighbor_line_start'], 10)
        proof = rows(execute(self.executor, 'evidence', target_type='edge', target=edge['edge_id']))
        self.assertEqual(proof[0]['evidence_id'], 'proof-billing')
        self.assertEqual(rows(execute(self.executor, 'incident', root='z-billing', edge_kind='calls')), [])
        self.assertEqual(rows(execute(self.executor, 'incident', root='z-policy', edge_kind=None)), [])
        self.assertEqual(rows(execute(self.executor, 'incident', scope='other', root='z-billing', edge_kind=None)), [])

    def test_stale_endpoints_unresolved_edges_and_stale_evidence_are_excluded(self):
        db = self.executor.connection
        for table, column, value, id_ in [('nodes', 'validity', 'stale', 'decision-billing'),
                                         ('nodes', 'validity', 'stale', 'z-billing'),
                                         ('edges', 'validity', 'stale', 'edge-billing'),
                                         ('edges', 'resolution', 'ambiguous', 'edge-billing')]:
            with self.subTest(table=table, column=column, id=id_):
                old = db.execute('SELECT ' + column + ' FROM ' + table + ' WHERE scope_id=? AND id=?', ('main', id_)).fetchone()[0]
                db.execute('UPDATE ' + table + ' SET ' + column + '=? WHERE scope_id=? AND id=?', (value, 'main', id_))
                self.assertEqual(rows(execute(self.executor, 'incident', root='z-billing', edge_kind=None)), [])
                db.execute('UPDATE ' + table + ' SET ' + column + '=? WHERE scope_id=? AND id=?', (old, 'main', id_))
        db.execute("UPDATE evidence SET validity='stale'")
        self.assertEqual(rows(execute(self.executor, 'evidence', target_type='edge', target='edge-billing')), [])

    def test_incident_outgoing_self_loop_and_keyset(self):
        db = self.executor.connection
        db.execute('''INSERT INTO edges(scope_id,id,source_id,target_id,kind,summary,confidence,validity,updated_at)
            VALUES('main','self','z-billing','z-billing','calls','Self call','confirmed','current','now')''')
        first = execute(self.executor, 'incident', root='z-billing', edge_kind=None, limit=1)
        self.assertTrue(first['results'][0]['has_more'])
        self.assertEqual(rows(first)[0]['edge_id'], 'edge-billing')
        final = execute(self.executor, 'incident', root='z-billing', edge_kind=None, limit=1, after_id='edge-billing')
        self.assertEqual([r['edge_id'] for r in rows(final)], ['self'])
        self.assertFalse(final['results'][0]['has_more'])
        outgoing = rows(execute(self.executor, 'incident', root='decision-billing', edge_kind=None))
        self.assertEqual(outgoing[0]['neighbor_id'], 'z-billing')

    def test_selected_node_evidence_pagination_and_target_validity(self):
        db = self.executor.connection
        db.execute('''INSERT INTO edges(scope_id,id,source_id,target_id,kind,summary,confidence,validity,updated_at)
            VALUES('main','z-billing','z-billing','decision-billing','calls','Collision','confirmed','current','now')''')
        db.execute('''INSERT INTO evidence(scope_id,id,edge_id,description,validity,updated_at)
            VALUES('main','collision','z-billing','Edge with same ID as node','current','now')''')
        db.execute('''INSERT INTO evidence(scope_id,id,node_id,description,validity,updated_at)
            VALUES('other','a','z-billing','Other scope','current','now')''')
        for id_ in ('a', 'b'):
            db.execute('''INSERT INTO evidence(scope_id,id,node_id,description,validity,updated_at)
                VALUES('main',?,'z-billing','Synthetic node evidence','current','now')''', (id_,))
        first = execute(self.executor, 'evidence', target_type='node', target='z-billing', limit=1)
        self.assertEqual(rows(first)[0]['evidence_id'], 'a')
        self.assertTrue(first['results'][0]['has_more'])
        final = execute(self.executor, 'evidence', target_type='node', target='z-billing', limit=1, after_id='a')
        self.assertEqual(rows(final)[0]['evidence_id'], 'b')
        self.assertFalse(final['results'][0]['has_more'])
        self.assertEqual([r['evidence_id'] for r in rows(execute(self.executor, 'evidence', target_type='edge', target='z-billing'))], ['collision'])
        db.execute("UPDATE nodes SET validity='stale' WHERE scope_id='main' AND id='z-billing'")
        self.assertEqual(rows(execute(self.executor, 'evidence', target_type='node', target='z-billing')), [])
        db.execute("UPDATE edges SET validity='stale' WHERE scope_id='main' AND id='edge-billing'")
        self.assertEqual(rows(execute(self.executor, 'evidence', target_type='edge', target='edge-billing')), [])

    def test_semantic_miss_and_byte_truncation_do_not_prove_absence(self):
        # The recipe cannot infer an architectural boundary from different task wording.
        self.assertEqual(rows(anchor(self.executor, 'charge customer')), [])
        db = self.executor.connection
        db.execute("UPDATE nodes SET summary=? WHERE scope_id='main' AND id='z-billing'", ('x' * 5000,))
        result = self.executor.execute_sql(sql=(ROOT / 'queries/anchors.sql').read_text(encoding='utf-8'),
            params=dict(scope='main', query='billing', mode='exact', path_prefix=None, after_id=None, limit=8),
            max_rows=8, max_output_bytes=1024)
        self.assertTrue(result['ok'], result)
        self.assertEqual(rows(result), [])
        self.assertTrue(result['results'][0]['has_more'])
        db.execute("UPDATE nodes SET summary=? WHERE scope_id='main' AND id='tie-b'", ('x' * 5000,))
        params = dict(scope='main', query='tied', mode='exact', path_prefix=None, after_id=None, limit=8)
        partial = self.executor.execute_sql(sql=(ROOT / 'queries/anchors.sql').read_text(encoding='utf-8'),
            params=params, max_rows=8, max_output_bytes=1024)
        self.assertEqual([r['id'] for r in rows(partial)], ['tie-a'])
        self.assertTrue(partial['results'][0]['has_more'])
        resumed = anchor(self.executor, 'tied', after_id=rows(partial)[-1]['id'])
        self.assertEqual([r['id'] for r in rows(resumed)], ['tie-b', 'tie-c'])

    def test_probe_reports_missing_graph_coverage_and_whole_result_bytes(self):
        report = comparison(self.executor)
        self.assertFalse(report['token_or_causal_savings_claim'])
        for item in report['scenarios']:
            self.assertEqual(item['baseline_seed_relevant'], 0)
            self.assertEqual(item['anchor_seed_relevant'], 1)
            self.assertEqual(item['exact_lexical_seed_relevant'], 1)
            self.assertEqual(item['exact_lexical_irrelevant_hits'], 0)
            self.assertTrue(item['exact_lexical_matches_anchor_rows'])
            self.assertEqual(item['exact_lexical_result_bytes'], item['anchor_only_result_bytes'])
            self.assertEqual(item['anchor_plus_hop_calls'], 2)
            self.assertGreater(item['anchor_plus_hop_result_bytes'], item['anchor_only_result_bytes'])
            self.assertGreaterEqual(item['new_all_result_bytes'], item['anchor_plus_hop_result_bytes'])
            self.assertEqual(item['expanded_relevant'], 1 if item['missing_edge'] else 2)
            self.assertGreater(item['new_all_result_bytes'], 0)


if __name__ == '__main__':
    if sys.argv[1:] == ['--compare']:
        area = ROOT / '.evomneme-tests'
        area.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=area) as folder:
            path = Path(folder) / 'synthetic.sqlite3'
            fixture(path)
            executor = Executor(path, history=False)
            try:
                print(json.dumps(comparison(executor), ensure_ascii=False, indent=2))
            finally:
                executor.close()
    else:
        unittest.main()
