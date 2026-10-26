"""Read-only user navigation, identity, exact counts, snapshots and output guards."""
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from dataclasses import replace
import hashlib
import importlib.util
import io
import json
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
from evomneme_connection import Connection, discover
from evomneme_navigate import NavigationError, Reader, navigate, qualified, quote_command
from evomneme_cli import main


def cards(text):
    return [json.loads(line) for line in text.splitlines() if line.startswith('{')]


class NavigationTests(unittest.TestCase):
    def setUp(self):
        area = ROOT / '.evomneme-tests'
        area.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=area)
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name).resolve()
        self.path = self.project / 'knowledge.sqlite3'
        db = sqlite3.connect(self.path)
        db.executescript((ROOT / 'schema.sql').read_text(encoding='utf-8'))
        db.execute("INSERT INTO metadata VALUES('project_identity','synthetic-navigation')")
        for scope in ('main', 'other'):
            db.execute('INSERT INTO scopes VALUES(?,?,?,?,?,?)', (scope, 'branch', str(self.project), 'rev', 'snapshot', 'now'))
        db.commit()
        db.close()
        self.connection = Connection(self.path, self.project, self.project, 'main', 'project-root',
                                     'powershell', 'synthetic-navigation', str(self.project), 'rev')
        self.node('project-root', 'Project overview', 'project', 'Real project responsibility')
        self.node('draft', 'Editable draft', summary='Retains raw text until Confirm.')
        self.node('commit', 'Durable local commit', summary='Atomically saves the value and pending bytes.')
        self.edge('ownership', 'project-root', 'draft', 'contains')
        self.edge('flow', 'draft', 'commit', 'depends_on', confidence='inferred')
        self.edge('reverse', 'commit', 'draft', 'constrains', confidence='uncertain', resolution='ambiguous')
        self.edge('parallel', 'draft', 'commit', 'calls', resolution='unresolved')
        self.edge('self', 'draft', 'draft', 'calls')

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path)
        try:
            with db:
                yield db
        finally:
            db.close()

    def node(self, id_, title, kind='architecture', summary='Synthetic responsibility', scope='main', validity='current'):
        with self.db() as db:
            db.execute('''INSERT INTO nodes(scope_id,id,kind,title,summary,confidence,validity,updated_at,layer)
                VALUES(?,?,?,?,?,'confirmed',?,'now','knowledge')''', (scope, id_, kind, title, summary, validity))

    def edge(self, id_, source, target, kind='calls', confidence='confirmed', resolution='resolved', scope='main', validity='current'):
        with self.db() as db:
            db.execute('''INSERT INTO edges(scope_id,id,source_id,target_id,kind,summary,confidence,validity,resolution,updated_at)
                VALUES(?,?,?,?,?,'Synthetic direct relationship',?,?,?,'now')''',
                       (scope, id_, source, target, kind, confidence, validity, resolution))

    def test_real_root_card_has_exact_count_and_no_neighbors(self):
        result = cards(navigate(self.connection, 'nodes', ['root']))
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['title'], 'Project overview')
        self.assertEqual(result[0]['link_count'], 1)
        self.assertNotIn('neighbors', result[0])
        self.assertNotIn('Editable draft', json.dumps(result[0]))
        self.assertIn('evomneme', result[0]['links_command'])

    def test_exact_link_counts_include_parallel_uncertain_self_once_and_directions(self):
        node = cards(navigate(self.connection, 'nodes', ['draft']))[0]
        links = cards(navigate(self.connection, 'links', ['draft']))
        self.assertEqual(node['link_count'], len(links))
        self.assertEqual(len(links), 5)
        self.assertEqual([r['direction'] for r in links].count('self'), 1)
        self.assertEqual({r['resolution'] for r in links}, {'resolved', 'unresolved', 'ambiguous'})
        self.assertIn('uncertain', {r['confidence'] for r in links})
        pair = cards(navigate(self.connection, 'links', ['draft', 'commit']))
        self.assertEqual(len(pair), 3)
        self.assertEqual({r['direction'] for r in pair}, {'incoming', 'outgoing'})
        self.assertTrue(all('source' in r and 'target' in r and 'edge_id' not in r for r in pair))
        self.assertEqual(len(cards(navigate(self.connection, 'links', ['draft', 'draft']))), 1)

    def test_stale_scope_and_missing_root_are_explicit(self):
        self.node('draft', 'Other draft', scope='other')
        self.node('old', 'Old thing', validity='stale')
        self.edge('old-edge', 'draft', 'old')
        self.edge('stale-edge', 'draft', 'commit', validity='stale')
        self.assertEqual(cards(navigate(self.connection, 'nodes', ['draft']))[0]['link_count'], 5)
        with self.assertRaisesRegex(NavigationError, 'not current'):
            navigate(self.connection, 'nodes', ['old'])
        with self.assertRaisesRegex(NavigationError, 'another scope'):
            navigate(self.connection, 'nodes', [qualified('other', 'draft')])
        with self.assertRaisesRegex(NavigationError, 'root is missing'):
            navigate(replace(self.connection, root_id='missing'), 'nodes', ['draft'])
        with self.db() as db:
            db.execute("UPDATE nodes SET validity='stale' WHERE id='project-root'")
        with self.assertRaisesRegex(NavigationError, 'root is missing or not current'):
            navigate(self.connection, 'nodes', ['draft'])

    def test_name_union_collisions_reserved_root_and_quoted_roundtrip(self):
        self.node('one', 'two')
        self.node('two', 'one')
        for name in ('one', 'two'):
            with self.assertRaisesRegex(NavigationError, 'Ambiguous'):
                navigate(self.connection, 'nodes', [name])
        card = cards(navigate(self.connection, 'nodes', [qualified('main', 'one')]))[0]
        self.assertEqual(card['argument'], qualified('main', 'one'))
        self.node('root', 'root')
        reserved = cards(navigate(self.connection, 'nodes', [qualified('main', 'root')]))[0]
        self.assertEqual(reserved['argument'], qualified('main', 'root'))
        self.node('slash', '/')
        self.assertEqual(cards(navigate(self.connection, 'nodes', ['/']))[0]['title'], '/')
        self.node('special/id %', '-Quarter "one" & O\'Brien %PATH% 📦')
        special = cards(navigate(self.connection, 'nodes', [qualified('main', 'special/id %')]))[0]
        self.assertEqual(special['argument'], '-Quarter "one" & O\'Brien %PATH% 📦')
        posix = quote_command(['evomneme', 'nodes', '--', special['argument']], 'posix')
        self.assertEqual(shlex.split(posix)[-1], special['argument'])
        self.assertIn("O''Brien", special['links_command'])
        self.edge('special-link', 'draft', 'special/id %')
        self.edge('qualified-link', 'draft', 'one')
        links = cards(navigate(self.connection, 'links', ['draft']))
        special_link = next(row for row in links if row['neighbor'] == special['argument'])
        self.assertEqual(special_link['nodes_command'], quote_command(['evomneme', 'nodes', '--', special['argument']], 'powershell'))
        qualified_link = next(row for row in links if row['neighbor'] == qualified('main', 'one'))
        self.assertEqual(qualified_link['nodes_command'], "& 'evomneme' 'nodes' '--' '@main/one'")

    def test_node_and_pair_evidence_are_available_and_validity_visible(self):
        with self.db() as db:
            db.execute("UPDATE nodes SET source_path='src/work.py',source_hash='hash',line_start=4,line_end=9 WHERE id='draft'")
            db.execute("UPDATE edges SET source_path='src/work.py',line_start=7 WHERE id='flow'")
            db.execute("INSERT INTO evidence(scope_id,id,node_id,description,source_path,validity,updated_at) VALUES('main','n-proof','draft','Source read','src/work.py','current','now')")
            db.execute("INSERT INTO evidence(scope_id,id,edge_id,description,validity,updated_at) VALUES('main','e-proof','flow','Old observation','stale','now')")
        node = cards(navigate(self.connection, 'nodes', ['draft']))[0]
        self.assertEqual(node['locator']['line_start'], 4)
        self.assertEqual(node['evidence'][0]['description'], 'Source read')
        edge = next(r for r in cards(navigate(self.connection, 'links', ['draft', 'commit'])) if r['kind'] == 'depends_on')
        self.assertEqual(edge['locator']['line_start'], 7)
        self.assertEqual(edge['evidence'][0]['validity'], 'stale')

    def test_sixty_architecture_links_and_thirtyone_named_nodes_fit_normal_output(self):
        for index in range(60):
            id_ = 'arch-' + str(index)
            self.node(id_, 'Responsibility ' + str(index), summary='A compact synthetic responsibility with a defined boundary.')
            self.edge('arch-link-' + str(index), 'project-root', id_, 'contains')
        root = cards(navigate(self.connection, 'nodes', ['root']))[0]
        self.assertEqual(root['link_count'], 61)
        text = navigate(self.connection, 'links', ['root'])
        self.assertEqual(len(cards(text)), 61)
        self.assertLess(len(text.encode('utf-8')), 65536)
        nodes = navigate(self.connection, 'nodes', ['arch-' + str(i) for i in range(31)])
        self.assertEqual(len(cards(nodes)), 31)
        self.assertLess(len(nodes.encode('utf-8')), 65536)

    def test_guard_emits_no_partial_stdout_and_all_returns_every_edge(self):
        for index in range(300):
            self.node('large-' + str(index), 'Large responsibility ' + str(index), summary='x' * 400)
            self.edge('large-link-' + str(index), 'project-root', 'large-' + str(index))
        stdout, stderr = io.StringIO(), io.StringIO()
        with mock.patch('evomneme_connection.discover', return_value=self.connection), redirect_stdout(stdout), redirect_stderr(stderr):
            self.assertEqual(main(['links', 'root']), 1)
        self.assertEqual(stdout.getvalue(), '')
        self.assertIn('links=301', stderr.getvalue())
        self.assertIn('--all', stderr.getvalue())
        self.assertIn("Full output: & 'evomneme' 'links' '--all' '--' 'root'", stderr.getvalue())
        self.assertNotIn('python', stderr.getvalue().lower())
        self.assertNotIn('evomneme_cli.py', stderr.getvalue())
        self.assertEqual(len(cards(navigate(self.connection, 'links', ['root'], all_output=True))), 301)

    def test_database_unchanged_and_reader_snapshot_survives_concurrent_commit(self):
        before = hashlib.sha256(self.path.read_bytes()).hexdigest()
        navigate(self.connection, 'nodes', ['root', 'draft'])
        navigate(self.connection, 'links', ['draft', 'commit'])
        self.assertEqual(hashlib.sha256(self.path.read_bytes()).hexdigest(), before)
        with self.db() as db:
            db.execute('PRAGMA journal_mode=WAL')
        reader = Reader(self.connection)
        try:
            self.assertEqual(reader.count(['draft']), 5)
            self.edge('concurrent', 'draft', 'commit')
            self.assertEqual(reader.node_card(reader.resolve('draft'))['link_count'], 5)
            self.assertEqual(len(reader.db.execute(*reader.edges_sql(['draft'])).fetchall()), 5)
        finally:
            reader.close()
        self.assertEqual(len(cards(navigate(self.connection, 'links', ['draft']))), 6)

    def test_timeout_fails_without_claiming_a_complete_result(self):
        with self.assertRaisesRegex(NavigationError, 'timed out'):
            navigate(self.connection, 'links', ['root'], timeout=0)
        original = Reader.node_card

        def slow(reader, node):
            time.sleep(.025)
            return original(reader, node)

        with mock.patch.object(Reader, 'node_card', slow):
            with self.assertRaisesRegex(NavigationError, 'timed out'):
                navigate(self.connection, 'nodes', ['root'], timeout=.01)

    def test_cli_leading_dash_name_uses_separator_and_failures_are_nonzero(self):
        self.node('dash', '-leading')
        stdout, stderr = io.StringIO(), io.StringIO()
        with mock.patch('evomneme_connection.discover', return_value=self.connection), redirect_stdout(stdout), redirect_stderr(stderr):
            self.assertEqual(main(['nodes', '--', '-leading']), 0)
            self.assertEqual(cards(stdout.getvalue())[0]['title'], '-leading')
            stdout.seek(0)
            stdout.truncate()
            self.assertEqual(main(['nodes', 'does not exist']), 1)
        self.assertEqual(stdout.getvalue(), '')
        self.assertIn('No current node', stderr.getvalue())

    def test_cli_writes_the_same_utf8_bytes_that_guard_measures(self):
        self.node('unicode', 'Отправка 📦')
        expected = navigate(self.connection, 'nodes', ['unicode']).encode('utf-8')
        stream = io.BytesIO()
        with mock.patch('evomneme_connection.discover', return_value=self.connection), \
                mock.patch('sys.stdout', types.SimpleNamespace(buffer=stream)):
            self.assertEqual(main(['nodes', 'unicode']), 0)
        self.assertEqual(stream.getvalue(), expected)

    def test_separate_probe_builder_connects_a_real_root_without_touching_previous_probes(self):
        spec = importlib.util.spec_from_file_location('navigation_fixture_builder',
            ROOT / 'tests/fixtures/navigation/build_fixture.py')
        builder = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(builder)
        result = builder.build(self.project / 'probe')
        connection = discover(Path(result['project_root']))
        self.assertEqual(connection.project_root, connection.canonical_root)
        self.assertEqual(connection.scope_worktree, str(connection.project_root))
        self.assertEqual(cards(navigate(connection, 'nodes', ['root']))[0]['link_count'], 5)
        self.assertEqual(len(cards(navigate(connection, 'links', ['root']))), 5)
        self.assertEqual(len(result['tasks']), 2)
        self.assertTrue(Path(result['activation_powershell']).is_file())
        with self.assertRaises(FileExistsError):
            builder.build(self.project / 'probe')


if __name__ == '__main__':
    unittest.main()
