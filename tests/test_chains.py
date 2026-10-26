"""Synthetic command chains share one snapshot/transaction and emit no partial results."""
import argparse
from contextlib import closing, redirect_stderr, redirect_stdout
from dataclasses import replace
import io
import json
import os
from pathlib import Path
import shlex
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import evomneme_chain as chain
from evomneme_cli import build_parser, main
from evomneme_connection import Connection, run_setup as connect
from evomneme_install import run_setup as install_launcher
from evomneme_journal import CALLS, LOG
from evomneme_navigate import Reader, navigate, qualified, quote_command
from evomneme_references import ReferenceReader, references


class ChainTests(unittest.TestCase):
    def setUp(self):
        area = ROOT / '.evomneme-tests'
        area.mkdir(exist_ok=True)
        temporary = tempfile.TemporaryDirectory(dir=area)
        self.addCleanup(temporary.cleanup)
        self.project = Path(temporary.name).resolve()
        self.path = self.project / 'synthetic.sqlite3'
        with closing(sqlite3.connect(self.path)) as db, db:
            db.executescript((ROOT / 'schema.sql').read_text(encoding='utf-8'))
            db.execute("INSERT INTO metadata VALUES('project_identity','synthetic-chain')")
            for scope in ('main', 'other'):
                db.execute('INSERT INTO scopes VALUES(?,?,?,?,?,?)', (scope, 'branch', str(self.project), 'rev', 'snap', 'now'))
            for id_, title, path in (('root-id', 'Project', 'root.py'), ('parser', 'Parser', 'src/parser.py')):
                db.execute("INSERT INTO nodes(scope_id,id,kind,title,summary,confidence,validity,source_path,updated_at) VALUES('main',?,'file',?,'Before','confirmed','current',?,'now')", (id_, title, path))
            db.execute("INSERT INTO edges(scope_id,id,source_id,target_id,kind,summary,confidence,validity,updated_at) VALUES('main','owns','root-id','parser','contains','Ownership','confirmed','current','now')")
        self.connection = Connection(self.path, self.project, self.project, 'main', 'root-id', 'posix',
                                     'synthetic-chain', str(self.project), 'rev')

    def query(self, sql, values=()):
        with closing(sqlite3.connect(self.path)) as db:
            db.row_factory = sqlite3.Row
            return [dict(row) for row in db.execute(sql, values)]

    def add(self, id_='new', title='New'):
        return ['add', 'node', '--id', id_, '--kind', 'function', '--title', title,
                '--summary', 'New claim', '--confidence', 'confirmed']

    def invoke(self, tokens, connection=None):
        stdout, stderr = io.StringIO(), io.StringIO()
        with mock.patch('evomneme_connection.discover', return_value=connection or self.connection) as discover, redirect_stdout(stdout), redirect_stderr(stderr):
            result = main(tokens)
        return result, stdout.getvalue(), stderr.getvalue(), discover.call_count

    def test_read_chain_groups_commands_with_one_validation_and_no_history(self):
        import evomneme_context
        with mock.patch('evomneme_context.validate_binding', wraps=evomneme_context.validate_binding) as binding:
            result, output, error, discovered = self.invoke(['nodes', 'root', '--next', 'links', 'root', '--next', 'references', 'src/parser.py'])
        self.assertEqual((result, error, discovered, binding.call_count), (0, '', 1, 1))
        self.assertIn('segment: 1\ncommand: nodes\nresult:', output)
        self.assertIn('segment: 2\ncommand: links', output)
        self.assertIn('segment: 3\ncommand: references', output)
        self.assertIn('source_path: src/parser.py', output)
        self.assertFalse(self.query("SELECT name FROM sqlite_schema WHERE name=?", (LOG,)))

    def test_late_parse_errors_mixed_setup_help_and_empty_segments_precede_discovery(self):
        tails = [self.add('bad')[:-1], ['update', 'node', 'parser', '--line_start', 'bad'],
                 ['update', 'node', 'parser', '--confidence', 'certain'], ['delete', 'evidence', 'x', '--cascade'],
                 ['nodes', 'root'], ['links', 'root', 'x', 'y'], ['install', '--activate', 'local'],
                 ['connect', str(self.path), '--scope', 'main', '--root', 'root-id'],
                 ['unknown'], ['add', 'evidence', '--id', 'proof', '--description', 'No parent'],
                 ['nodes', '--help'], []]
        for tail in tails:
            with self.subTest(tail=tail):
                result, output, error, discovered = self.invoke([*self.add('must-not-exist'), '--next', *tail])
                self.assertNotEqual(result, 0)
                self.assertEqual((output, discovered), ('', 0))
                self.assertIn('Segment 2', error)
                self.assertFalse(self.query("SELECT * FROM nodes WHERE id='must-not-exist'"))
        result, output, error, discovered = self.invoke(['--next', 'nodes', 'root'])
        self.assertEqual((result, output, discovered), (1, '', 0))
        self.assertIn('Segment 1', error)

    def test_sequential_write_chain_one_binding_and_install_per_segment_activity(self):
        import evomneme_mutate
        with mock.patch('evomneme_mutate.validate_binding', wraps=evomneme_mutate.validate_binding) as binding, \
                mock.patch('evomneme_mutate.install', wraps=evomneme_mutate.install) as install:
            result, output, error, discovered = self.invoke([*self.add(), '--next', 'add', 'edge', 'root', 'New',
                '--id', 'new-edge', '--kind', 'contains', '--summary', 'Owns new', '--confidence', 'confirmed',
                '--next', 'update', 'node', 'New', '--summary', 'Updated'])
        self.assertEqual((result, error, discovered, binding.call_count, install.call_count), (0, '', 1, 1, 1))
        self.assertIn('command: add node', output)
        self.assertIn('command: add edge', output)
        self.assertIn('command: update node', output)
        self.assertEqual(self.query("SELECT summary FROM nodes WHERE id='new'")[0]['summary'], 'Updated')
        self.assertEqual(self.query("SELECT target_id FROM edges WHERE id='new-edge'")[0]['target_id'], 'new')
        calls = self.query('SELECT * FROM ' + CALLS)
        self.assertEqual(len(calls), 3)
        self.assertEqual(len({row['activity_id'] for row in calls}), 3)

    def test_late_state_failure_rolls_back_graph_and_new_history_and_stdout(self):
        result, output, error, discovered = self.invoke([*self.add(), '--next', 'update', 'node', 'missing', '--summary', 'No row'])
        self.assertEqual((result, output, discovered), (1, '', 1))
        self.assertIn('Segment 2', error)
        self.assertFalse(self.query("SELECT * FROM nodes WHERE id='new'"))
        self.assertFalse(self.query("SELECT name FROM sqlite_schema WHERE name=?", (LOG,)))

    def test_delete_chain_preserves_per_segment_guard_and_rolls_back_all_audit(self):
        result, output, error, _ = self.invoke([*self.add(), '--next', 'delete', 'edge', 'owns', '--next', 'delete', 'node', 'root'])
        self.assertEqual((result, output), (1, ''))
        self.assertIn('Segment 3', error)
        self.assertIn('Configured root cannot be deleted', error)
        self.assertTrue(self.query("SELECT * FROM edges WHERE id='owns'"))
        self.assertFalse(self.query("SELECT * FROM nodes WHERE id='new'"))
        self.assertFalse(self.query("SELECT name FROM sqlite_schema WHERE name=?", (LOG,)))
        result, output, error, _ = self.invoke([*self.add(), '--next', 'delete', 'node', 'new', '--next', 'update', 'node', 'parser', '--summary', 'Still here'])
        self.assertEqual((result, error), (0, ''))
        self.assertIn('command: delete node', output)
        self.assertFalse(self.query("SELECT * FROM nodes WHERE id='new'"))
        self.assertEqual(len(self.query('SELECT * FROM ' + CALLS)), 3)
        self.assertEqual(len(self.query('SELECT * FROM ' + LOG + " WHERE operation='delete'")), 1)

    def test_aggregate_budget_includes_wrappers_and_optout_any_read_segment(self):
        tokens = ['nodes', 'root', '--next', 'references', 'src/parser.py']
        result, expected, error, _ = self.invoke(tokens)
        self.assertEqual((result, error), (0, ''))
        size = len(expected.encode('utf-8'))
        with mock.patch('evomneme_chain.OUTPUT_BYTES', size):
            self.assertEqual(self.invoke(tokens)[1], expected)
        with mock.patch('evomneme_chain.OUTPUT_BYTES', size - 1):
            result, output, error, _ = self.invoke(tokens)
            self.assertEqual((result, output), (1, ''))
            self.assertIn('Segment 2', error)
            self.assertIn('Full output:', error)
            retry = error.split('Full output: ', 1)[1].strip()
            retry_tokens = shlex.split(retry)
            self.assertEqual(retry_tokens[0], 'evomneme')
            self.assertEqual(self.invoke(retry_tokens[1:])[1], expected)
            self.assertEqual(self.invoke([*tokens, '--all'])[1], expected)

    def test_mutation_aggregate_budget_rolls_back(self):
        original = chain.result_group
        def budget_after_first(index, args, output):
            result = original(index, args, output)
            if index == 1:
                chain.OUTPUT_BYTES = len(result.encode('utf-8')) + 1
            return result
        with mock.patch('evomneme_chain.OUTPUT_BYTES', 65536), mock.patch('evomneme_chain.result_group', side_effect=budget_after_first):
            result, output, error, _ = self.invoke([*self.add(), '--next', 'update', 'node', 'new', '--summary', 'Updated'])
        self.assertEqual((result, output), (1, ''))
        self.assertIn('output exceeds', error)
        self.assertIn('Segment 2', error)
        self.assertFalse(self.query("SELECT * FROM nodes WHERE id='new'"))
        self.assertFalse(self.query("SELECT name FROM sqlite_schema WHERE name=?", (LOG,)))

    def test_one_wal_snapshot_across_navigation_and_references(self):
        with closing(sqlite3.connect(self.path)) as db:
            db.execute('PRAGMA journal_mode=WAL')
        original = chain.navigate
        def concurrent_write(*args, **kwargs):
            output = original(*args, **kwargs)
            with closing(sqlite3.connect(self.path)) as db, db:
                db.execute("UPDATE nodes SET summary='After' WHERE id='parser'")
            return output
        with mock.patch('evomneme_chain.navigate', side_effect=concurrent_write):
            result, output, error, _ = self.invoke(['nodes', 'root', '--next', 'references', 'src/parser.py'])
        self.assertEqual((result, error), (0, ''))
        self.assertIn('summary: Before', output)
        self.assertNotIn('summary: After', output)
        self.assertEqual(self.query("SELECT summary FROM nodes WHERE id='parser'")[0]['summary'], 'After')

    def test_single_deadline_late_failure_has_no_partial_stdout(self):
        original = chain.navigate
        def slow(*args, **kwargs):
            result = original(*args, **kwargs)
            time.sleep(.05)
            return result
        with mock.patch('evomneme_chain.TIMEOUT_SECONDS', .08), mock.patch('evomneme_chain.navigate', side_effect=slow):
            result, output, error, _ = self.invoke(['nodes', 'root', '--next', 'links', 'root'])
        self.assertEqual((result, output), (1, ''))
        self.assertIn('timed out', error)
        self.assertIn('Segment 2', error)

    def test_late_external_fk_rolls_back_earlier_write_and_history_install(self):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('CREATE TABLE extra(scope TEXT, parent TEXT, FOREIGN KEY(scope,parent) REFERENCES nodes(scope_id,id) ON DELETE CASCADE)')
            db.execute("INSERT INTO extra VALUES('main','parser')")
        result, output, error, _ = self.invoke([*self.add(), '--next', 'delete', 'node', 'parser', '--cascade'])
        self.assertEqual((result, output), (1, ''))
        self.assertIn('Segment 2', error)
        self.assertIn('External foreign key dependency', error)
        self.assertTrue(self.query("SELECT * FROM nodes WHERE id='parser'"))
        self.assertFalse(self.query("SELECT * FROM nodes WHERE id='new'"))
        self.assertFalse(self.query("SELECT name FROM sqlite_schema WHERE name=?", (LOG,)))

    def test_references_root_gap_allowed_but_later_navigation_fails(self):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("UPDATE nodes SET validity='stale' WHERE id='root-id'")
        result, output, error, _ = self.invoke(['references', 'root.py', '--next', 'references', 'src/parser.py'])
        self.assertEqual((result, error), (0, ''))
        self.assertIn('root is missing or not current', output)
        result, output, error, _ = self.invoke(['references', 'root.py', '--next', 'nodes', 'parser'])
        self.assertEqual((result, output), (1, ''))
        self.assertIn('Segment 2', error)

    def test_literal_separator_values_and_last_segment_dash_names(self):
        self.assertEqual(chain.split_segments(['nodes', '--', '--next']), [['nodes', '--', '--next']])
        self.assertEqual(chain.split_segments(['nodes', 'root', '--next', 'nodes', '--', '--next']),
                         [['nodes', 'root'], ['nodes', '--', '--next']])
        result, output, error, _ = self.invoke([*self.add('--next', '--next'), '--summary=--next', '--next', 'nodes', 'root'])
        self.assertEqual((result, output), (1, ''))  # A bare separator token cannot be quoted into a flag value.
        self.assertIn('Segment', error)
        result, output, error, _ = self.invoke([*self.add(), '--next', 'update', 'node', 'new', '--summary=--next'])
        self.assertEqual((result, error), (0, ''))
        self.assertEqual(self.query("SELECT summary FROM nodes WHERE id='new'")[0]['summary'], '--next')
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("INSERT INTO nodes(scope_id,id,kind,title,summary,confidence,validity,updated_at) VALUES('main','--next','file','--next','Literal','confirmed','current','now')")
        result, output, error, _ = self.invoke(['nodes', '--', '--next'])
        self.assertEqual((result, error), (0, ''))
        self.assertIn('title: --next', output)
        result, output, error, _ = self.invoke(['nodes', 'root', '--next', 'nodes', '--', '--next'])
        self.assertEqual((result, error), (0, ''))
        self.assertIn('title: --next', output)

    def test_binding_scope_failure_and_control_errors_are_safe(self):
        result, output, error, _ = self.invoke([*self.add(), '--next', 'delete', 'node', qualified('other', 'parser')])
        self.assertEqual((result, output), (1, ''))
        self.assertIn('another scope', error)
        self.assertFalse(self.query("SELECT name FROM sqlite_schema WHERE name=?", (LOG,)))
        result, output, error, _ = self.invoke([*self.add(), '--next', 'delete', 'node', 'missing\n\x1b[2J'])
        self.assertEqual((result, output), (1, ''))
        self.assertNotIn('\x1b', error)
        self.assertIn('\\u001b', error)
        result, output, error, _ = self.invoke([*self.add(), '--next', 'update', 'node', 'new', '--summary', 'x'],
                                             connection=replace(self.connection, project_identity='wrong'))
        self.assertEqual((result, output), (1, ''))
        self.assertFalse(self.query("SELECT * FROM nodes WHERE id='new'"))

    @unittest.skipUnless(os.name == 'nt', 'native PowerShell launcher requires Windows')
    def test_native_returned_commands_then_unicode_write_and_atomic_refusals(self):
        (self.project / '.git').mkdir()
        with redirect_stdout(io.StringIO()):
            connect(argparse.Namespace(database=self.path, project=self.project, canonical_root=None,
                                       scope='main', root_id='root-id', shell='powershell'))
            with mock.patch.object(Path, 'cwd', return_value=self.project):
                install_launcher(argparse.Namespace(bin_dir=None, activate=self.project / 'session'))
        activate = ". '" + str(self.project / 'session/activate.ps1').replace("'", "''") + "'; "
        def shell(command):
            return subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command',
                '[Console]::OutputEncoding = New-Object Text.UTF8Encoding($false); ' + activate + command],
                cwd=self.project, capture_output=True, text=True, encoding='utf-8', timeout=30)
        first = shell('evomneme nodes root')
        self.assertEqual(first.returncode, 0, first.stderr)
        returned_links = next(line.split(': ', 1)[1] for line in first.stdout.splitlines() if line.startswith('links_command:'))
        linked = shell(returned_links)
        self.assertEqual(linked.returncode, 0, linked.stderr)
        returned_node = next(line.split(': ', 1)[1] for line in linked.stdout.splitlines() if line.startswith('nodes_command:'))
        prefix = "& 'evomneme' "
        self.assertTrue(returned_node.startswith(prefix))
        combined = shell(returned_links + ' --next ' + returned_node[len(prefix):])
        self.assertEqual(combined.returncode, 0, combined.stderr)
        self.assertIn('command: links', combined.stdout)
        self.assertIn('command: nodes', combined.stdout)
        literal = 'Квартал "one" & O\'Brien 📦'
        written = shell(quote_command(['evomneme', *self.add('native', literal), '--next', 'update', 'node', 'native', '--summary=--next'], 'powershell'))
        self.assertEqual(written.returncode, 0, written.stderr)
        self.assertEqual(self.query("SELECT title,summary FROM nodes WHERE id='native'")[0], dict(title=literal, summary='--next'))
        for tail in (['nodes', 'root'], ['update', 'node', 'native', '--line_start', 'bad']):
            failed = shell(quote_command(['evomneme', *self.add('refused'), '--next', *tail], 'powershell'))
            self.assertNotEqual(failed.returncode, 0)
            self.assertEqual(failed.stdout, '')
            self.assertFalse(self.query("SELECT * FROM nodes WHERE id='refused'"))


if __name__ == '__main__':
    unittest.main()
