"""Write enhancements use isolated stores; never the connected project store."""
from contextlib import closing, redirect_stderr, redirect_stdout
from dataclasses import replace
import hashlib
import io
import json
from pathlib import Path
import sqlite3
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_mutations as fixtures
from evomneme_cli import build_parser, main
from evomneme_journal import CALLS, LOG
from evomneme_mutate import MutationSession, delete, mutate, run


class ImprovementsTests(unittest.TestCase):
    setUp = fixtures.MutationTests.setUp
    query = fixtures.MutationTests.query
    add_node = fixtures.MutationTests.add_node

    def invoke(self, tokens, session=None):
        return run(self.connection, build_parser().parse_args(tokens), session=session)

    def source(self):
        path = self.connection.project_root / 'source.py'
        path.write_bytes(b'first\nsecond\n')
        return path, hashlib.sha256(path.read_bytes()).hexdigest()

    def test_details_lifecycle_defaults_scoping_and_constraints(self):
        self.add_node()
        self.invoke(['add', 'symbol-details', 'n', '--qualified_name', 'mod.n', '--signature', 'n()'])
        self.invoke(['add', 'file-details', 'n'])
        self.assertEqual(self.query('SELECT declaration_status FROM file_details')[0]['declaration_status'], 'pending')
        self.invoke(['update', 'symbol-details', 'n', '--clear', 'signature'])
        self.assertIsNone(self.query('SELECT signature FROM symbol_details')[0]['signature'])
        for args in (['add', 'file-details', 'n'], ['add', 'symbol-details', 'root', '--qualified_name', ' '],
                     ['update', 'symbol-details', 'n', '--qualified_name', 'mod.n'],
                     ['update', 'file-details', '@other/n', '--remaining_work', 'x']):
            with self.assertRaises(ValueError):
                self.invoke(args)
        self.invoke(['update', 'file-details', 'n', '--declaration_status', 'partial', '--remaining_work', 'Inspect calls'])
        self.invoke(['delete', 'symbol-details', 'n'])
        self.invoke(['delete', 'file-details', 'n'])
        self.assertFalse(self.query('SELECT * FROM symbol_details'))
        self.assertFalse(self.query('SELECT * FROM file_details'))
        self.assertEqual(len(self.query('SELECT * FROM ' + LOG)), 7)

    def test_detail_chain_failure_rolls_back_graph_and_history(self):
        self.add_node()
        count = len(self.query('SELECT * FROM ' + LOG))
        active = MutationSession(self.connection)
        try:
            self.invoke(['add', 'file-details', 'n'], active)
            with self.assertRaises(ValueError):
                self.invoke(['add', 'symbol-details', 'root', '--qualified_name', ' '], active)
        finally:
            active.close()
        self.assertFalse(self.query('SELECT * FROM file_details'))
        self.assertEqual(len(self.query('SELECT * FROM ' + LOG)), count)

    def test_compact_preserves_state_history_and_context(self):
        output = self.invoke(['add', 'node', '--id', 'n', '--kind', 'file', '--title', 'N', '--summary', 'x' * 70000,
                             '--confidence', 'confirmed', '--compact', '--chat-id', 'known-chat', '--chat-title', 'Known title',
                             '--session-id', 'known-session', '--agent-name', 'Known agent'])
        self.assertLess(len(output), 1000)
        self.assertEqual(len(self.query("SELECT summary FROM nodes WHERE id='n'")[0]['summary']), 70000)
        event = json.loads(self.query('SELECT event_json FROM ' + CALLS)[0]['event_json'])
        self.assertEqual((event['chat'], event['chat_title'], event['session'], event['agent_name']),
                         ('known-chat', 'Known title', 'known-session', 'Known agent'))
        self.assertIsNone(event['agent'])
        actor = json.loads(self.query('SELECT actor_json FROM ' + LOG)[0]['actor_json'])
        self.assertEqual(actor['chat'], 'known-chat')
        self.assertNotIn('x' * 100, output)

    def test_compact_full_equivalence_and_detail_trigger_rollback(self):
        common = dict(kind='file', title='Shared title', summary='Same persisted claim', confidence='confirmed')
        full = mutate(self.connection, 'add', 'node', dict(id='full', **common))
        compact = mutate(self.connection, 'add', 'node', dict(id='compact', **common), compact=True)
        rows = self.query("SELECT * FROM nodes WHERE id IN ('full','compact') ORDER BY id")
        self.assertEqual([{key: value for key, value in row.items() if key not in ('id', 'updated_at')} for row in rows][0],
                         [{key: value for key, value in row.items() if key not in ('id', 'updated_at')} for row in rows][1])
        events = [json.loads(row['event_json']) for row in self.query('SELECT event_json FROM ' + CALLS)]
        self.assertEqual(events[0]['changed_fields'], events[1]['changed_fields'])
        self.assertIn('Same persisted claim', full)
        self.assertNotIn('Same persisted claim', compact)
        count = len(self.query('SELECT * FROM ' + LOG))
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("CREATE TRIGGER collateral_detail AFTER INSERT ON file_details BEGIN UPDATE nodes SET summary='Unexpected' WHERE id='root-id'; END")
        with self.assertRaisesRegex(ValueError, 'Unexpected graph writes'):
            self.invoke(['add', 'file-details', 'compact'])
        self.assertFalse(self.query('SELECT * FROM file_details'))
        self.assertEqual(len(self.query('SELECT * FROM ' + LOG)), count)
        self.assertEqual(self.query("SELECT summary FROM nodes WHERE id='root-id'")[0]['summary'], 'Synthetic project')

    def test_stale_update_and_delete_preserve_audit_and_all_types(self):
        self.add_node()
        mutate(self.connection, 'add', 'edge', dict(id='e', kind='uses', summary='Uses', confidence='confirmed'), source='root', target='n')
        mutate(self.connection, 'add', 'evidence', dict(id='p', node_id='n', description='Observed'))
        for entity, id_, table, values in [('node', 'n', 'nodes', {'summary': 'New'}),
                                          ('edge', 'e', 'edges', {'summary': 'New'}),
                                          ('evidence', 'p', 'evidence', {'description': 'New'})]:
            old = self.query('SELECT updated_at FROM ' + table + ' WHERE id=?', (id_,))[0]['updated_at']
            count = len(self.query('SELECT * FROM ' + LOG))
            with self.assertRaisesRegex(ValueError, 'Stale write'):
                mutate(self.connection, 'update', entity, values, selector=id_, expect_updated_at='wrong')
            with self.assertRaisesRegex(ValueError, 'Stale write'):
                delete(self.connection, entity, id_, expect_updated_at='wrong')
            self.assertEqual(count, len(self.query('SELECT * FROM ' + LOG)))
            mutate(self.connection, 'update', entity, values, selector=id_, expect_updated_at=old)

    def test_source_hash_bounds_escape_and_precommit_change(self):
        path, digest = self.source()
        values = dict(id='n', kind='file', title='N', summary='Source', confidence='confirmed',
                      source_path='source.py', source_hash=digest, line_start=1, line_end=2)
        for patch in ({'source_hash': 'wrong'}, {'line_end': 3}, {'source_path': '../outside'},
                      {'source_path': str(path)}, {'source_hash': None}):
            with self.subTest(patch=patch), self.assertRaises((ValueError, OSError)):
                mutate(self.connection, 'add', 'node', values | patch, verify_source=True)
        self.assertFalse(self.query("SELECT * FROM nodes WHERE id='n'"))
        active = MutationSession(self.connection)
        try:
            mutate(self.connection, 'add', 'node', values, verify_source=True, session=active)
            path.write_bytes(b'changed\n')
            with self.assertRaisesRegex(ValueError, 'Source changed'):
                active.commit()
        finally:
            active.close()
        self.assertFalse(self.query("SELECT * FROM nodes WHERE id='n'"))
        self.assertFalse(self.query("SELECT name FROM sqlite_schema WHERE name=?", (LOG,)))

    def test_detail_source_inspected_hash_and_output_rollback(self):
        path, digest = self.source()
        self.add_node(source_path='source.py', source_hash=digest)
        with self.assertRaisesRegex(ValueError, 'SHA-256'):
            self.invoke(['add', 'file-details', 'n', '--inspected_hash', 'wrong', '--verify-source'])
        self.invoke(['add', 'file-details', 'n', '--inspected_hash', digest, '--verify-source'])
        before = self.query('SELECT * FROM ' + LOG)
        with self.assertRaisesRegex(ValueError, 'output exceeds'):
            self.invoke(['update', 'file-details', 'n', '--remaining_work', 'x' * 70000])
        self.assertEqual(self.query('SELECT * FROM ' + LOG), before)
        self.assertIsNone(self.query('SELECT remaining_work FROM file_details')[0]['remaining_work'])

    def test_verified_write_rejects_trigger_changed_stored_locator_and_history(self):
        path, digest = self.source()
        values = dict(id='n', kind='file', title='N', summary='Source', confidence='confirmed',
                      source_path='source.py', source_hash=digest, line_start=1, line_end=2)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("CREATE TRIGGER change_locator AFTER INSERT ON nodes WHEN NEW.id='n' BEGIN "
                       "UPDATE nodes SET source_hash='wrong',line_end=999 WHERE scope_id=NEW.scope_id AND id=NEW.id; END")
        with self.assertRaisesRegex(ValueError, 'Stored source locator changed'):
            mutate(self.connection, 'add', 'node', values, verify_source=True)
        self.assertFalse(self.query("SELECT * FROM nodes WHERE id='n'"))
        self.assertFalse(self.query("SELECT name FROM sqlite_schema WHERE name=?", (LOG,)))
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('DROP TRIGGER change_locator')
        self.add_node(source_path='source.py', source_hash=digest, line_start=1, line_end=2)
        count = len(self.query('SELECT * FROM ' + LOG))
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('CREATE TRIGGER change_locator_after_activity AFTER INSERT ON ' + CALLS +
                       " BEGIN UPDATE nodes SET source_hash='wrong' WHERE id='n'; END")
        with self.assertRaisesRegex(ValueError, 'Stored source locator changed'):
            mutate(self.connection, 'update', 'node', {'summary': 'Changed'}, selector='n', verify_source=True)
        self.assertEqual(self.query("SELECT source_hash FROM nodes WHERE id='n'")[0]['source_hash'], digest)
        self.assertEqual(len(self.query('SELECT * FROM ' + LOG)), count)

    def test_verify_source_rejects_malformed_stored_lines_for_details_and_delete(self):
        path, digest = self.source()
        self.add_node(source_path='source.py', source_hash=digest, line_start=1, line_end=2)
        malformed = ((0, 1), (-1, 1), (1.5, 2), ('invalid', 2), (2, 1), (None, 1), (1, 0))
        for start, end in malformed:
            with closing(sqlite3.connect(self.path)) as db, db:
                db.execute("UPDATE nodes SET line_start=?,line_end=? WHERE id='n'", (start, end))
            count = len(self.query('SELECT * FROM ' + LOG))
            with self.subTest(start=start, end=end):
                with self.assertRaisesRegex(ValueError, 'Source line_'):
                    self.invoke(['add', 'file-details', 'n', '--verify-source'])
                with self.assertRaisesRegex(ValueError, 'Source line_'):
                    delete(self.connection, 'node', 'n', verify_source=True)
            self.assertFalse(self.query('SELECT * FROM file_details'))
            self.assertTrue(self.query("SELECT * FROM nodes WHERE id='n'"))
            self.assertEqual(len(self.query('SELECT * FROM ' + LOG)), count)

    def test_diagnostic_chain_all_is_aggregate_in_both_orders(self):
        from evomneme_chain import ChainParser, parse_segments, run as run_chain, split_segments
        for tokens in (['nodes', 'root', '--all', '--next', 'check'],
                       ['check', '--next', 'nodes', 'root', '--all']):
            segments = split_segments(tokens)
            parsed, category = parse_segments(build_parser(ChainParser), segments)
            with self.subTest(tokens=tokens), mock.patch('evomneme_diagnostics.OUTPUT_BYTES', 1), mock.patch('evomneme_chain.OUTPUT_BYTES', 1):
                output = run_chain(self.connection, parsed, category, segments)
                self.assertIn('command: check', output)
                self.assertIn('title: Project', output)
            self.assertFalse(next(args for args in parsed if args.command == 'check').all_output)
        segments = split_segments(['nodes', 'root', '--next', 'check'])
        parsed, category = parse_segments(build_parser(ChainParser), segments)
        with mock.patch('evomneme_chain.OUTPUT_BYTES', 1), self.assertRaisesRegex(ValueError, 'Chain output exceeds'):
            run_chain(self.connection, parsed, category, segments)

    def test_invalid_chain_parses_before_discovery_and_mixed_diagnostics_fail(self):
        with mock.patch('evomneme_connection.discover') as discover, redirect_stderr(io.StringIO()):
            self.assertEqual(main(['add', 'file-details', 'n', '--next', 'check']), 1)
            discover.assert_not_called()


if __name__ == '__main__':
    unittest.main()
