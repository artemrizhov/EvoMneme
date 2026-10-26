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
    """Read the documented text layout for semantic navigation assertions."""
    def mapping(lines, indent=0):
        result = {}
        index = 0
        while index < len(lines):
            key, _, value = lines[index][indent:].partition(':')
            value = value.removeprefix(' ')
            index += 1
            children = []
            while index < len(lines) and lines[index].startswith(' ' * (indent + 2)):
                children.append(lines[index])
                index += 1
            if key in ('locator', 'neighbor'):
                result[key] = mapping(children, indent + 2)
            elif key == 'evidence':
                entries = []
                for line in children:
                    if line == ' ' * (indent + 2) + '-':
                        entries.append([])
                    else:
                        entries[-1].append(line)
                result[key] = [mapping(entry, indent + 4) for entry in entries]
            else:
                value += ''.join('\n' + line[indent + 2:] for line in children)
                result[key] = int(value) if key in ('link_count', 'line_start', 'line_end') else value
        return result

    groups = []
    for line in text.split('\n'):
        if line.startswith(('argument:', 'direction:')):
            groups.append([])
        if line == 'complete:':
            break
        if groups and line:
            groups[-1].append(line)
    return [mapping(group) for group in groups]


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
        self.assertEqual(special['links_command'], quote_command(['evomneme', 'links', qualified('main', 'special/id %')], 'powershell'))
        self.edge('special-link', 'draft', 'special/id %')
        self.edge('qualified-link', 'draft', 'one')
        links = cards(navigate(self.connection, 'links', ['draft']))
        special_link = next(row for row in links if row['neighbor']['argument'] == special['argument'])
        self.assertEqual(special_link['nodes_command'], quote_command(['evomneme', 'nodes', qualified('main', 'special/id %')], 'powershell'))
        qualified_link = next(row for row in links if row['neighbor']['argument'] == qualified('main', 'one'))
        self.assertEqual(qualified_link['nodes_command'], "& 'evomneme' 'nodes' '@main/one'")

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
        self.assertIn("Full output: & 'evomneme' 'links' '--all' 'root'", stderr.getvalue())
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

    def test_plain_text_fields_use_schema_names_and_only_separate_result_elements(self):
        single = navigate(self.connection, 'nodes', ['root'])
        self.assertTrue(single.startswith('scope: main\nstatus: current-knowledge\nshell: powershell\nnodes: 1\n'))
        self.assertIn('kind: project\ntitle: Project overview\nsummary: Real project responsibility\n', single)
        self.assertIn('locator:\nevidence:\nlink_count: 1\n', single)
        self.assertTrue(single.endswith('complete:\n  scope: main\n  nodes: 1\n  source_completeness: not established\n'))
        self.assertNotIn('\n\n', single)
        multiple = navigate(self.connection, 'nodes', ['root', 'draft', 'commit'])
        self.assertEqual(multiple.count('\n\n'), 2)
        self.assertTrue(all(section.startswith('argument: ') for section in multiple.split('\n\n')[1:]))
        with self.db() as db:
            db.execute("DELETE FROM edges WHERE source_id='project-root'")
        empty = navigate(self.connection, 'links', ['root'])
        self.assertEqual(cards(empty), [])
        self.assertNotIn('\n\n', empty)
        self.assertIn('links: 0\ncomplete:\n', empty)

    def test_nested_relationship_fields_and_multiline_evidence_cannot_forge_boundaries(self):
        title = 'First line\n\ncomplete:\nargument: forged\n  indented'
        summary = '\nsummary: nested fake\n\nlast line\n'
        self.node('multiline', title, summary=summary)
        self.edge('multiline-link', 'draft', 'multiline', confidence='inferred')
        with self.db() as db:
            db.execute("INSERT INTO evidence(scope_id,id,node_id,description,validity,updated_at) VALUES('main','first','multiline',?,'stale','now')",
                       ('Proof\n\ndirection: forged\ncomplete:',))
            db.execute("INSERT INTO evidence(scope_id,id,node_id,description,validity,updated_at) VALUES('main','second','multiline','','current','now')")
        text = navigate(self.connection, 'nodes', ['multiline', 'root'])
        self.assertEqual(text.count('\n\n'), 1)
        self.assertEqual(text.count('\ncomplete:\n'), 1)
        node, _ = cards(text)
        self.assertEqual(node['title'], title)
        self.assertEqual(node['summary'], summary)
        self.assertEqual(node['argument'], 'multiline')
        self.assertEqual(node['evidence'][0]['description'], 'Proof\n\ndirection: forged\ncomplete:')
        self.assertEqual(node['evidence'][1]['description'], '')
        self.assertIn('evidence:\n  -\n    description: Proof\n      \n      direction: forged\n', text)
        link = cards(navigate(self.connection, 'links', ['draft', 'multiline']))[0]
        self.assertEqual(link['summary'], 'Synthetic direct relationship')
        self.assertEqual(link['confidence'], 'inferred')
        self.assertEqual(link['neighbor']['title'], title)
        self.assertEqual(link['neighbor']['summary'], summary)
        self.assertEqual(link['neighbor']['confidence'], 'confirmed')
        self.assertNotIn('relationship_summary', link)
        self.assertNotIn('neighbor_confidence', link)

    def test_control_characters_and_newline_ids_use_safe_qualified_commands(self):
        id_ = 'new\nline\x1b[2J'
        self.node(id_, 'title\ncomplete:\r\x1b[2J\u2028scope: fake')
        text = navigate(self.connection, 'nodes', [qualified('main', id_)])
        card = cards(text)[0]
        self.assertEqual(card['argument'], qualified('main', id_))
        self.assertIn('\\u000d\\u001b[2J\\u2028scope: fake', text)
        self.assertNotIn('\x1b', text)
        self.assertIn(quote_command(['evomneme', 'links', qualified('main', id_)], 'powershell'), text)

    def test_guard_includes_separators_header_footer_and_indented_utf8_values(self):
        self.node('multibyte', 'Многострочный 📦', summary='line\n\n📦')
        expected = navigate(self.connection, 'nodes', ['multibyte', 'root'])
        size = len(expected.encode('utf-8'))
        with mock.patch('evomneme_navigate.OUTPUT_BYTES', size):
            self.assertEqual(navigate(self.connection, 'nodes', ['multibyte', 'root']), expected)
        with mock.patch('evomneme_navigate.OUTPUT_BYTES', size - 1):
            with self.assertRaisesRegex(NavigationError, 'no cards emitted'):
                navigate(self.connection, 'nodes', ['multibyte', 'root'])
            self.assertEqual(navigate(self.connection, 'nodes', ['multibyte', 'root'], all_output=True), expected)

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
