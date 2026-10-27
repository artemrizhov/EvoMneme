"""Synthetic advisory checks and storage diagnostics; no host database access."""
import argparse
from dataclasses import replace
import hashlib
from pathlib import Path
import sqlite3
import sys
from types import SimpleNamespace
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from evomneme_context import ReadContext
from evomneme_diagnostics import DiagnosticError, DiagnosticReader, configure_parser, diagnose, run
import test_references as fixtures


class DiagnosticsTests(unittest.TestCase):
    setUp = fixtures.ReferencesTests.setUp
    db = fixtures.ReferencesTests.db
    node = fixtures.ReferencesTests.node
    edge = fixtures.ReferencesTests.edge
    evidence = fixtures.ReferencesTests.evidence

    def args(self, command='check', **kwargs):
        return SimpleNamespace(diagnostic_command=command, all_output=False, sources=[], **kwargs)

    def test_parser_and_run(self):
        parser = argparse.ArgumentParser()
        configure_parser(parser.add_subparsers(required=True))
        args = parser.parse_args(['check', '--sources', 'one.py', 'two.py', '--sources', 'three.py', '--all'])
        self.assertEqual(args.sources, ['one.py', 'two.py', 'three.py'])
        self.assertTrue(args.diagnostic)
        self.assertEqual(run(self.connection, args), diagnose(self.connection, args))
        self.assertFalse(parser.parse_args(['stats']).all_output)

    def test_scoped_current_graph_signals_and_evidence(self):
        for id_ in ('a', 'b', 'isolated'):
            self.node(id_, id_ + '.py')
        self.node('old', 'old.py', validity='stale')
        self.node('foreign', 'foreign.py', scope='other')
        self.edge('ab', 'a', 'b', 'a.py')
        self.edge('ab2', 'a', 'b', 'a.py')
        self.edge('old-edge', 'root', 'old', 'old.py')
        self.edge('stale-edge', 'root', 'isolated', 'x.py', validity='stale')
        with self.db() as db:
            db.execute("UPDATE edges SET kind='contains' WHERE id IN ('ab','ab2')")
        self.evidence('proof', 'a.py', node='a')
        self.evidence('stale-proof', 'b.py', node='b', validity='stale')
        reader = DiagnosticReader(self.connection)
        try:
            graph = reader.graph_check()
            self.assertEqual(graph['component_count'], 3)
            self.assertEqual(graph['isolated_nodes'], [dict(id='isolated'), dict(id='root')])
            self.assertEqual(graph['degree_one_nodes'], [dict(id='a'), dict(id='b')])
            self.assertEqual(graph['contains_only_nodes'], [dict(id='a'), dict(id='b')])
            self.assertEqual(len(graph['duplicate_relationships']), 1)
            self.assertEqual(graph['evidence_coverage']['nodes']['with_current_evidence'], 1)
            self.assertEqual(len(graph['current_edges_without_current_endpoints']), 1)
        finally:
            reader.context.close()
        output = diagnose(self.connection, self.args())
        self.assertIn('integrity_check: ok', output)
        self.assertIn('Semantic completeness is not established', output)
        self.assertNotIn('foreign.py', output)

    def test_sources_all_validity_hash_lines_and_text_caveat(self):
        source = self.project / 'source.py'
        source.write_bytes(b'first\nsecond\n')
        actual = hashlib.sha256(source.read_bytes()).hexdigest()
        self.node('file', 'source.py', validity='stale')
        self.node('alias', './source.py')
        self.edge('ref', 'root', 'file', 'source.py', validity='superseded')
        self.evidence('proof', 'source.py', node='file')
        with self.db() as db:
            db.execute("UPDATE nodes SET source_hash=?,line_start=1,line_end=2 WHERE id='file'", (actual,))
            db.execute("UPDATE edges SET line_start=0,line_end=99 WHERE id='ref'")
        args = self.args()
        args.sources = ['source.py', 'missing.py']
        output = diagnose(self.connection, args)
        self.assertIn('reference_count: 3', output)
        self.assertIn('hash_status: match', output)
        self.assertIn('hash_status: mismatch or unsupported hash format', output)
        self.assertIn('line_status: out of bounds', output)
        self.assertIn('line_status: within file bounds', output)
        self.assertIn('file_status: missing file', output)
        self.assertIn('Textual citations', output)
        self.assertNotIn('id: alias', output.split('\nsources:\n', 1)[1])

    def test_sources_confinement_and_bounded_reads(self):
        reader = DiagnosticReader(self.connection)
        try:
            for path in ('../outside.py', str(self.project / 'absolute.py'), 'C:relative.py', '\\server\\file.py'):
                with mock.patch.object(Path, 'open', side_effect=AssertionError('must not read')):
                    result = reader.source_check([path])
                self.assertIn('rejected unsafe', result['files'][0]['file_status'])
            (self.project / 'large.py').write_bytes(b'12345')
            with mock.patch('evomneme_diagnostics.SOURCE_BYTES', 4):
                result = reader.source_check(['large.py'])
            self.assertIn('exceeds bounded read', result['files'][0]['file_status'])
            outside = self.project.parent / (self.project.name + '-outside')
            outside.mkdir()
            self.addCleanup(outside.rmdir)
            link = self.project / 'escape'
            try:
                link.symlink_to(outside, target_is_directory=True)
            except OSError:
                return  # Windows may disallow symlink creation; other confinement cases still ran.
            self.addCleanup(link.unlink)
            self.assertIn('rejected symlink escape', reader.source_check(['escape/x.py'])['files'][0]['file_status'])
        finally:
            reader.context.close()

    def test_snapshot_no_writes_or_journal_changes(self):
        before = hashlib.sha256(self.path.read_bytes()).hexdigest()
        diagnose(self.connection, self.args())
        diagnose(self.connection, self.args('stats'))
        self.assertEqual(before, hashlib.sha256(self.path.read_bytes()).hexdigest())
        with self.db() as db:
            db.execute('PRAGMA journal_mode=WAL')
        shared = ReadContext(self.connection)
        try:
            self.node('later', None)
            output = diagnose(self.connection, self.args(), shared=shared)
            self.assertNotIn('id: later', output)
            self.assertIsNotNone(shared.db)
            with self.assertRaises(sqlite3.OperationalError):
                shared.db.execute('DELETE FROM nodes')
            with self.assertRaisesRegex(DiagnosticError, 'another binding'):
                diagnose(replace(self.connection, root_id='different'), self.args(), shared=shared)
        finally:
            shared.close()
        self.assertIn('id: later', diagnose(self.connection, self.args()))

    def test_stats_storage_groups_and_fallback(self):
        with self.db() as db:
            db.execute('CREATE TABLE evomneme_change_calls(id INTEGER, event_json TEXT)')
            db.execute('CREATE TABLE evomneme_change_log(id INTEGER, payload TEXT)')
            db.execute("INSERT INTO evomneme_change_calls VALUES(1,'call')")
            db.execute("INSERT INTO evomneme_change_log VALUES(1,'history')")
        output = diagnose(self.connection, self.args('stats'))
        self.assertIn('whole database, all scopes', output)
        self.assertIn('page_count:', output)
        self.assertIn('free_pages:', output)
        self.assertIn('evomneme_change_calls', output)
        original = DiagnosticReader.rows

        def no_dbstat(reader, sql, params=()):
            if 'FROM dbstat' in sql:
                raise sqlite3.OperationalError('no such table: dbstat')
            return original(reader, sql, params)

        with mock.patch.object(DiagnosticReader, 'rows', no_dbstat):
            output = diagnose(self.connection, self.args('stats'))
        self.assertIn('payload_estimate_bytes:', output)
        self.assertIn('excludes record, page and index overhead', output)
        self.assertNotIn('allocated_page_bytes:', output)

    def test_guard_and_deadline_apply_with_all(self):
        output = diagnose(self.connection, self.args())
        size = len(output.encode('utf-8'))
        with mock.patch('evomneme_diagnostics.OUTPUT_BYTES', size):
            self.assertEqual(diagnose(self.connection, self.args()), output)
        with mock.patch('evomneme_diagnostics.OUTPUT_BYTES', size - 1):
            with self.assertRaisesRegex(DiagnosticError, 'no result emitted'):
                diagnose(self.connection, self.args())
            args = self.args()
            args.all_output = True
            self.assertEqual(diagnose(self.connection, args), output)
        shared = ReadContext(self.connection)
        try:
            shared.deadline = 0
            with self.assertRaisesRegex(ValueError, 'timed out'):
                diagnose(self.connection, args, shared=shared)
        finally:
            shared.close()


if __name__ == '__main__':
    unittest.main()
