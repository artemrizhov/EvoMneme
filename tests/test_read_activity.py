"""Bound graph reads journal automatically without acquiring a graph write path."""
import argparse
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import replace
import hashlib
import io
import json
import sqlite3
import threading
import time
import unittest
from unittest import mock

import test_navigation as fixtures
from evomneme_cli import main
from evomneme_diagnostics import diagnose
from evomneme_journal import CALLS, LOG, META, install, read_calls, status
from evomneme_navigate import NavigationError, Reader, navigate
import evomneme_read_activity as activity
from evomneme_references import references
from evomneme_viewer import Explorer


class ReadActivityTests(unittest.TestCase):
    setUp = fixtures.NavigationTests.setUp
    db = fixtures.NavigationTests.db
    node = fixtures.NavigationTests.node
    edge = fixtures.NavigationTests.edge

    def events(self):
        with self.db() as db:
            return read_calls(db, {})['events']

    def invoke(self, tokens, connection=None):
        stdout, stderr = io.StringIO(), io.StringIO()
        with mock.patch('evomneme_connection.discover', return_value=connection or self.connection), \
                redirect_stdout(stdout), redirect_stderr(stderr):
            result = main(tokens)
        return result, stdout.getvalue(), stderr.getvalue()

    def refs(self, event):
        return {(ref['graph_type'], json.loads(ref['graph_id'])[1]) for ref in event['references']}

    def test_default_nodes_and_links_match_only_returned_cards(self):
        warning = io.StringIO()
        with redirect_stderr(warning):
            navigate(self.connection, 'nodes', ['root', 'root'])
            navigate(self.connection, 'links', ['root'])
            navigate(self.connection, 'links', ['draft', 'commit'])
        events = self.events()
        self.assertEqual(warning.getvalue(), '', 'Default rollback journal must not self-lock')
        self.assertEqual(len(events), 3)
        self.assertTrue(all(e['ok'] and e['source'] == 'graph-cli' and e['write'] == [] for e in events))
        self.assertEqual(self.refs(events[0]), {('nodes', 'project-root')})
        self.assertEqual(self.refs(events[1]), {('edges', 'ownership'), ('nodes', 'draft')})
        self.assertEqual(self.refs(events[2]), {('edges', 'flow'), ('edges', 'reverse'), ('edges', 'parallel'),
                                               ('nodes', 'draft'), ('nodes', 'commit')})
        self.assertEqual([e['returned_rows'] for e in events], [1, 1, 3])
        self.assertIsNone(events[0]['chat'])
        self.assertFalse(events[0]['identity']['chat'])
        with self.db() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM ' + LOG).fetchone()[0], 0)

    def test_references_and_diagnostics_log_automatic_calls(self):
        with self.db() as db:
            db.execute("UPDATE nodes SET source_path='draft.py' WHERE id='draft'")
        references(self.connection, ['draft.py'])
        for command in ('check', 'stats'):
            diagnose(self.connection, argparse.Namespace(diagnostic_command=command, all_output=True, sources=[]))
        events = self.events()
        self.assertEqual([e['command'] for e in events], ['references', 'check', 'stats'])
        self.assertIn(('nodes', 'draft'), self.refs(events[0]))
        for event in events[1:]:
            self.assertEqual((event['references'], event['returned_rows'], event['write']), ([], 0, []))
            self.assertIn('nodes', event['read'])
            self.assertIn('edges', event['read'])

    def test_optional_identity_all_reads_and_consistent_aggregate_chain(self):
        for tokens in (['nodes', 'root'], ['links', 'root'], ['references', 'missing.py'], ['check'], ['stats']):
            result, output, warning = self.invoke([*tokens, '--chat-id', 'known', '--agent-name', 'Reader'])
            self.assertEqual((result, warning), (0, ''))
            self.assertTrue(output)
        self.assertTrue(all(e['chat'] == 'known' and e['agent_name'] == 'Reader' for e in self.events()))
        result, output, warning = self.invoke(['nodes', 'root', '--chat-id', 'chain', '--next', 'links', 'root', '--session-id', 'work'])
        self.assertEqual((result, warning), (0, ''))
        event = self.events()[-1]
        self.assertEqual((event['command'], event['completed'], event['chat'], event['session']), ('chain', 2, 'chain', 'work'))
        with mock.patch('evomneme_connection.discover') as discover:
            with redirect_stderr(io.StringIO()):
                self.assertEqual(main(['nodes', 'root', '--chat-id', 'a', '--next', 'links', 'root', '--chat-id', 'b']), 1)
            discover.assert_not_called()
        self.assertEqual(len(self.events()), 6)

    def test_failed_read_chain_output_guard_and_timeout_never_return_buffered_ids(self):
        result, output, warning = self.invoke(['nodes', 'root', '--next', 'nodes', 'absent'])
        self.assertEqual((result, output), (1, ''))
        self.assertIn('Segment 2', warning)
        with mock.patch('evomneme_chain.OUTPUT_BYTES', 20):
            self.assertEqual(self.invoke(['nodes', 'root', '--next', 'links', 'root'])[0], 1)
        original = Reader.node_card

        def slow(reader, node):
            card = original(reader, node)
            time.sleep(.02)
            return card

        with mock.patch.object(Reader, 'node_card', slow):
            with self.assertRaisesRegex(NavigationError, 'timed out'):
                navigate(self.connection, 'nodes', ['root'], timeout=.01)
        for event in self.events():
            self.assertFalse(event['ok'])
            self.assertEqual((event['references'], event['returned_rows']), ([], 0))
        self.assertEqual(len(self.events()), 3)

    def test_wrong_binding_parse_and_invalid_metadata_never_install_history(self):
        before = hashlib.sha256(self.path.read_bytes()).hexdigest()
        self.assertEqual(self.invoke(['nodes', 'root'], replace(self.connection, project_identity='wrong'))[0], 1)
        with mock.patch('evomneme_connection.discover') as discover:
            with redirect_stderr(io.StringIO()):
                self.assertEqual(main(['nodes', 'root', '--next', 'unknown']), 1)
            discover.assert_not_called()
        with self.assertRaisesRegex(ValueError, 'nonempty'):
            navigate(self.connection, 'nodes', ['root'], activity_context={'chat_id': ''})
        self.assertEqual(hashlib.sha256(self.path.read_bytes()).hexdigest(), before)

    def test_rebinding_after_snapshot_is_revalidated_before_any_history_setup(self):
        real_persist = activity.persist

        def rebound(connection, event):
            with self.db() as db:
                db.execute("UPDATE metadata SET value='replacement' WHERE key='project_identity'")
            real_persist(connection, event)

        warning = io.StringIO()
        with mock.patch.object(activity, 'persist', rebound), redirect_stderr(warning):
            output = navigate(self.connection, 'nodes', ['root'])
        self.assertIn('argument:', output)
        self.assertIn('activity history warning', warning.getvalue())
        with self.db() as db:
            self.assertFalse(status(db, False).get('version'))
            self.assertEqual(db.execute("SELECT count(*) FROM sqlite_schema WHERE name=?", (CALLS,)).fetchone()[0], 0)

    def test_locked_history_retains_complete_read_and_warns(self):
        install(self.path)
        warning = io.StringIO()
        with self.db() as writer:
            writer.execute('BEGIN IMMEDIATE')
            with redirect_stderr(warning):
                output = navigate(self.connection, 'nodes', ['root'])
        self.assertIn('complete:', output)
        self.assertIn('locked', warning.getvalue())
        self.assertEqual(self.events(), [])

    def test_suspended_history_is_preserved_with_visible_warning(self):
        install(self.path)
        install(self.path, suspend=True)
        warning = io.StringIO()
        with redirect_stderr(warning):
            output = references(self.connection, ['missing.py'])
        self.assertIn('complete:', output)
        self.assertIn('suspended', warning.getvalue())
        with self.db() as db:
            self.assertFalse(status(db, False)['enabled'])
        self.assertEqual(self.events(), [])

    def test_malformed_journal_metadata_cannot_revoke_successful_read(self):
        install(self.path)
        with self.db() as db:
            db.execute('UPDATE ' + META + " SET value='null' WHERE key='table:nodes'")
        warning = io.StringIO()
        with redirect_stderr(warning):
            output = navigate(self.connection, 'nodes', ['root'])
        self.assertIn('complete:', output)
        self.assertIn('activity history warning', warning.getvalue())
        self.assertEqual(self.events(), [])
        with self.db() as db:
            self.assertEqual(db.execute('SELECT value FROM ' + META + " WHERE key='table:nodes'").fetchone()[0], 'null')

    def test_history_begin_and_commit_share_one_total_lock_budget(self):
        install(self.path)
        with self.db() as reader:
            reader.execute('BEGIN')
            reader.execute('SELECT * FROM nodes').fetchall()
            ready = threading.Event()
            errors = []

            def reserve():
                try:
                    with self.db() as writer:
                        writer.execute('BEGIN IMMEDIATE')
                        ready.set()
                        time.sleep(.6)
                        writer.rollback()
                except Exception as exc:
                    errors.append(exc)
                    ready.set()

            thread = threading.Thread(target=reserve)
            thread.start()
            self.assertTrue(ready.wait(2))
            warning = io.StringIO()
            started = time.monotonic()
            with redirect_stderr(warning):
                output = navigate(self.connection, 'nodes', ['root'])
            elapsed = time.monotonic() - started
            thread.join(2)
            self.assertFalse(thread.is_alive())
            self.assertEqual(errors, [])
        self.assertIn('complete:', output)
        self.assertIn('activity history warning', warning.getvalue())
        self.assertLess(elapsed, 1.4, 'BEGIN and COMMIT must share one second, not spend one second each')
        self.assertGreater(elapsed, .8, 'The final commit should be blocked by the held reader')
        self.assertEqual(self.events(), [])

    def test_graph_read_connection_rejects_writes_and_records_failure(self):
        def forbidden(reader, node):
            self.assertEqual(reader.db.execute('PRAGMA query_only').fetchone()[0], 1)
            reader.db.execute("UPDATE nodes SET summary='Forbidden'")

        with mock.patch.object(Reader, 'node_card', forbidden):
            with self.assertRaisesRegex(NavigationError, 'readonly'):
                navigate(self.connection, 'nodes', ['root'])
        self.assertFalse(self.events()[0]['ok'])
        with self.db() as db:
            self.assertEqual(db.execute("SELECT summary FROM nodes WHERE id='project-root'").fetchone()[0], 'Real project responsibility')
            self.assertEqual(db.execute('SELECT count(*) FROM ' + LOG).fetchone()[0], 0)

    def test_unicode_graph_ids_match_viewer_and_real_calls_are_available(self):
        self.node('узел\n📦', 'Unicode')
        navigate(self.connection, 'nodes', ['узел\n📦'], activity_context={'chat_id': 'viewer-check'})
        view = Explorer(self.path)
        events = view.events({})
        self.assertTrue(events['enabled'])
        event = events['events'][0]
        self.assertEqual((event['chat'], event['command']), ('viewer-check', 'nodes'))
        with self.db() as db:
            graph_id = db.execute("SELECT json_array(scope_id,id) FROM nodes WHERE title='Unicode'").fetchone()[0]
        self.assertEqual(event['references'], [{'graph_type': 'nodes', 'graph_id': graph_id}])
        self.assertEqual(view.events({'after_id': events['after_id']})['events'], [])

    def test_oversized_returned_references_use_existing_explicit_truncation(self):
        def many(active):
            for index in range(6000):
                active.returned('nodes', 'n' + str(index) + 'x' * 100)
            active.completed += 1
            return 'complete\n'

        self.assertEqual(activity.read_call(self.connection, 'fixture', many), 'complete\n')
        event = self.events()[0]
        self.assertTrue(event['references_truncated'])
        self.assertEqual((event['references'], event['returned_rows']), ([], 6000))


if __name__ == '__main__':
    unittest.main()
