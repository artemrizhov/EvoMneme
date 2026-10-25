"""Isolated operational tests: never build an index for the tool repository."""

import concurrent.futures
import contextlib
import copy
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest

REPOSITORY = Path(__file__).resolve().parent.parent
SCRIPT = REPOSITORY / 'scripts' / 'evomneme.py'
SPEC = importlib.util.spec_from_file_location('evomneme_test_runtime', SCRIPT)
runtime = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runtime)
TEST_AREA = REPOSITORY / '.evomneme-tests'


class RuntimeTests(unittest.TestCase):
    """Exercise project boundaries and useful knowledge operations in host fixtures."""

    def setUp(self):
        """Create a fresh host fixture with an existing Git installation."""
        TEST_AREA.mkdir(exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=TEST_AREA)
        self.addCleanup(self.temporary.cleanup)
        self.area = Path(self.temporary.name)
        self.project = self.area / 'host'
        self.project.mkdir()
        self.git('init', '-b', 'main')
        self.git('config', 'user.name', 'Isolated Test')
        self.git('config', 'user.email', 'isolated@example.invalid')
        (self.project / 'source.txt').write_text('original source\n', encoding='utf-8')
        (self.project / '.gitignore').write_text('ignored/\n', encoding='utf-8')
        self.git('add', '.')
        self.git('commit', '-m', 'Isolated fixture')
        self.host = runtime.Host(self.project)
        with runtime.connect(self.host, initialize=True):
            pass

    def git(self, *args, project=None):
        """Use Git solely in the selected isolated host fixture."""
        result = subprocess.run(['git', '-C', str(project or self.project), *args], capture_output=True)
        if result.returncode:
            raise AssertionError(result.stderr.decode('utf-8', 'replace'))
        return result.stdout

    def cli(self, *args, project=None, payload=None):
        """Run the public CLI with JSON stdin and capture its honest exit status."""
        return subprocess.run([sys.executable, str(SCRIPT), '--project', str(project or self.project), *args], input=json.dumps(payload) if payload is not None else None, capture_output=True, text=True)

    def sample(self):
        """Return a small agent-authored graph with a decision and source evidence."""
        return {'records': [
            {'id': 'caller', 'kind': 'function', 'title': 'Caller', 'summary': 'Starts the workflow', 'confidence': 'confirmed', 'source_path': 'source.txt', 'line_start': 1},
            {'id': 'callee', 'kind': 'function', 'title': 'Callee', 'summary': 'Processes requests', 'confidence': 'inferred'},
            {'id': 'choice', 'kind': 'decision', 'title': 'Use a queue', 'summary': 'A queue preserves ordering; direct calls were rejected', 'confidence': 'confirmed'}],
            'relations': [
                {'id': 'calls', 'source_id': 'caller', 'target_id': 'callee', 'kind': 'calls', 'summary': 'Runtime dynamic dispatch', 'confidence': 'inferred'},
                {'id': 'rationale', 'source_id': 'choice', 'target_id': 'caller', 'kind': 'constrains', 'summary': 'Ordering requirement'}],
            'evidence': [
                {'id': 'observed', 'record_id': 'caller', 'description': 'Inspected implementation', 'source_path': 'source.txt'},
                {'id': 'edge-observed', 'relation_id': 'calls', 'description': 'Inspected runtime wiring', 'source_path': 'source.txt'}]}

    def put_sample(self):
        """Write sample knowledge into only the fixture's current scope."""
        with runtime.connect(self.host) as connection:
            runtime.update(connection, self.host, self.sample())

    def test_compact_graph_decisions_and_inference(self):
        """Retrieve decisions and indirect dependencies with visible inference."""
        self.put_sample()
        with runtime.connect(self.host, readonly=True) as connection:
            decisions = runtime.search(connection, self.host, 'queue')
            self.assertEqual(decisions['records'][0]['kind'], 'decision')
            graph = runtime.traverse(connection, self.host, 'choice', depth=2)
            self.assertEqual({x['id'] for x in graph['records']}, {'caller', 'callee', 'choice'})
            self.assertEqual(len(graph['relations']), 2)
            self.assertEqual(len(graph['evidence']), 2)
            self.assertEqual(next(x for x in graph['relations'] if x['id'] == 'calls')['confidence'], 'inferred')
            self.assertTrue(all(x['effective_validity'] == 'current' for x in graph['records']))

    def test_atomic_batch_rollback(self):
        """Reject dangling graph edges without retaining earlier batch records."""
        batch = self.sample()
        batch['relations'][0]['target_id'] = 'missing'
        with runtime.connect(self.host) as connection:
            with self.assertRaises(sqlite3.IntegrityError):
                runtime.update(connection, self.host, batch)
            self.assertEqual(connection.execute('SELECT count(*) FROM records').fetchone()[0], 0)
            self.assertEqual(connection.execute('SELECT count(*) FROM scopes').fetchone()[0], 0)
            self.assertEqual(connection.execute('SELECT count(*) FROM history').fetchone()[0], 0)

    def test_changed_and_deleted_sources_invalidate_claims_and_edges(self):
        """Reconcile changed evidence and dependent edges, retaining uncertainty."""
        self.put_sample()
        (self.project / 'source.txt').write_text('changed source\n', encoding='utf-8')
        changed = runtime.Host(self.project)
        with runtime.connect(changed) as connection:
            result = runtime.reconcile(connection, changed)
            self.assertEqual(result['direct_invalidations'], {'records': 1, 'relations': 0, 'evidence': 2})
            states = {row['id']: row['validity'] for row in connection.execute('SELECT id,validity FROM relations')}
            self.assertEqual(states, {'calls': 'stale', 'rationale': 'stale'})
            self.assertEqual(runtime.search(connection, changed, '')['records'], [])
            old = runtime.search(connection, changed, '', include_stale=True, all_scopes=True)['records']
            self.assertTrue(all(x['effective_validity'] == 'out_of_scope' for x in old))
        (self.project / 'source.txt').unlink()
        deleted = runtime.Host(self.project)
        with runtime.connect(deleted) as connection:
            runtime.reconcile(connection, deleted)
        self.assertNotEqual(changed.snapshot, deleted.snapshot)

    def test_evidence_invalidates_sourceless_claim_and_connected_relation(self):
        """A claim supported only by evidence cannot remain current after deletion."""
        sample = self.sample()
        del sample['records'][0]['source_path']
        del sample['records'][0]['line_start']
        with runtime.connect(self.host) as connection:
            runtime.update(connection, self.host, sample)
        (self.project / 'source.txt').unlink()
        with runtime.connect(runtime.Host(self.project)) as connection:
            runtime.reconcile(connection, runtime.Host(self.project))
            self.assertEqual(connection.execute("SELECT validity FROM records WHERE id='caller'").fetchone()[0], 'stale')
            self.assertEqual(connection.execute("SELECT validity FROM relations WHERE id='rationale'").fetchone()[0], 'stale')

    def test_stale_evidence_updates_invalidate_record_and_relation_immediately(self):
        """Explicit evidence invalidation must affect default retrieval before reconcile."""
        self.put_sample()
        with runtime.connect(self.host) as connection:
            runtime.update(connection, self.host, {'evidence': [
                {'id': 'edge-observed', 'relation_id': 'calls', 'description': 'Previous wiring inference disproved', 'validity': 'stale'}]})
            self.assertEqual(connection.execute("SELECT validity FROM relations WHERE id='calls'").fetchone()[0], 'stale')
            self.assertEqual(connection.execute("SELECT validity FROM records WHERE id='caller'").fetchone()[0], 'current')
            self.assertNotIn('calls', {row['id'] for row in runtime.traverse(connection, self.host, 'caller')['relations']})
            runtime.update(connection, self.host, {'evidence': [
                {'id': 'observed', 'record_id': 'caller', 'description': 'Previous claim disproved', 'validity': 'stale'}]})
            self.assertEqual(connection.execute("SELECT validity FROM records WHERE id='caller'").fetchone()[0], 'stale')
            self.assertEqual(connection.execute("SELECT validity FROM relations WHERE id='rationale'").fetchone()[0], 'stale')
            self.assertEqual(runtime.search(connection, self.host, 'Caller')['records'], [])

    def test_evidence_invalidation_and_dependents_roll_back_together(self):
        """A failure after propagation restores evidence, claims and connected edges."""
        from unittest.mock import patch
        self.put_sample()
        with runtime.connect(self.host) as connection:
            with patch.object(runtime, 'Host', side_effect=runtime.KnowledgeError('scope check failure')):
                with self.assertRaisesRegex(runtime.KnowledgeError, 'scope check failure'):
                    runtime.update(connection, self.host, {'evidence': [
                        {'id': 'observed', 'record_id': 'caller', 'description': 'Invalidated observation', 'validity': 'stale'},
                        {'id': 'edge-observed', 'relation_id': 'calls', 'description': 'Invalidated wiring', 'validity': 'stale'}]})
            for table in ('records', 'relations', 'evidence'):
                self.assertEqual(connection.execute('SELECT count(*) FROM ' + table + " WHERE validity!='current'").fetchone()[0], 0)
            self.assertEqual(len(runtime.search(connection, self.host, 'Caller')['records']), 1)

    def test_same_head_dirty_contents_are_distinct(self):
        """Equal Git status entries with different bytes cannot share a snapshot."""
        source = self.project / 'source.txt'
        source.write_text('dirty one\n', encoding='utf-8')
        first = runtime.Host(self.project)
        source.write_text('dirty two\n', encoding='utf-8')
        second = runtime.Host(self.project)
        self.assertEqual(first.revision, second.revision)
        self.assertNotEqual(first.snapshot, second.snapshot)
        self.assertNotEqual(first.scope, second.scope)

    def test_branch_switch_does_not_invalidate_other_version_history(self):
        """Keep historical facts tied to the version actually inspected."""
        self.put_sample()
        self.git('checkout', '-b', 'changed-version')
        (self.project / 'source.txt').write_text('new branch implementation\n', encoding='utf-8')
        self.git('add', 'source.txt')
        self.git('commit', '-m', 'Different implementation')
        changed = runtime.Host(self.project)
        with runtime.connect(changed) as connection:
            runtime.reconcile(connection, changed)
            row = connection.execute("SELECT validity FROM records WHERE scope_id=? AND id='caller'", (self.host.scope,)).fetchone()
            self.assertEqual(row[0], 'current')
            historical = runtime.search(connection, changed, 'Caller', all_scopes=True)['records']
            self.assertEqual(historical[0]['effective_validity'], 'out_of_scope')
            self.assertEqual(runtime.search(connection, changed, 'Caller')['records'], [])

    def test_scope_change_during_update_rolls_back(self):
        """Do not publish inspected knowledge into an outdated scope snapshot."""
        (self.project / 'source.txt').write_text('edited after Host was captured', encoding='utf-8')
        with runtime.connect(self.host) as connection:
            with self.assertRaisesRegex(runtime.KnowledgeError, 'scope changed'):
                runtime.update(connection, self.host, self.sample())
            self.assertEqual(connection.execute('SELECT count(*) FROM records').fetchone()[0], 0)

    def test_clean_head_and_ignored_files_are_not_hashed(self):
        """Scope probes skip clean tracked source and ignored dependency trees."""
        from unittest.mock import patch
        ignored = self.project / 'ignored'
        ignored.mkdir()
        (ignored / 'huge.txt').write_text('dependency', encoding='utf-8')
        with patch.object(runtime, 'file_hash', side_effect=AssertionError('Unexpected content scan')):
            self.assertEqual(runtime.Host(self.project).snapshot, self.host.snapshot)

    def test_local_submodule_revisions_dirty_contents_and_initialization_scope(self):
        """Scope local gitlinks without hashing clean source or initializing modules."""
        from unittest.mock import patch
        dependency = self.area / 'dependency'
        dependency.mkdir()
        self.git('init', '-b', 'main', project=dependency)
        self.git('config', 'user.name', 'Isolated Test', project=dependency)
        self.git('config', 'user.email', 'isolated@example.invalid', project=dependency)
        (dependency / 'module.txt').write_text('module original\n', encoding='utf-8')
        (dependency / '.gitignore').write_text('ignored/\n', encoding='utf-8')
        self.git('add', '.', project=dependency)
        self.git('commit', '-m', 'Isolated module', project=dependency)
        self.git('-c', 'protocol.file.allow=always', 'submodule', 'add', str(dependency), 'module')
        self.git('commit', '-am', 'Add isolated local module')
        module = self.project / 'module'
        self.git('config', 'user.name', 'Isolated Test', project=module)
        self.git('config', 'user.email', 'isolated@example.invalid', project=module)
        self.git('config', 'diff.ignoreSubmodules', 'all')
        with patch.object(runtime, 'file_hash', side_effect=AssertionError('Clean tracked contents scanned')):
            clean = runtime.Host(self.project)
        (module / 'module.txt').write_text('dirty module one\n', encoding='utf-8')
        dirty_one = runtime.Host(self.project)
        (module / 'module.txt').write_text('dirty module two\n', encoding='utf-8')
        dirty_two = runtime.Host(self.project)
        self.assertEqual(clean.revision, dirty_one.revision)
        self.assertNotEqual(clean.scope, dirty_one.scope)
        self.assertNotEqual(dirty_one.scope, dirty_two.scope)
        self.assertEqual(dirty_two.source('module/module.txt')[0], 'module/module.txt')
        (module / 'ignored').mkdir()
        (module / 'ignored' / 'private.txt').write_text('ignored', encoding='utf-8')
        self.assertEqual(runtime.Host(self.project).scope, dirty_two.scope)
        with self.assertRaisesRegex(runtime.KnowledgeError, 'Ignored'):
            dirty_two.source('module/ignored/private.txt')
        self.git('add', 'module.txt', project=module)
        self.git('commit', '-m', 'New module revision', project=module)
        changed_revision = runtime.Host(self.project)
        self.assertEqual(changed_revision.revision, clean.revision)
        self.assertNotEqual(changed_revision.scope, clean.scope)
        self.assertNotEqual(changed_revision.scope, dirty_two.scope)
        # A clean submodule checkout at its committed gitlink is still distinct
        # from the unavailable implementation after deinitialization.
        self.git('add', 'module')
        self.git('commit', '-m', 'Advance module gitlink')
        initialized = runtime.Host(self.project)
        self.git('submodule', 'deinit', '--force', '--', 'module')
        uninitialized = runtime.Host(self.project)
        self.assertNotEqual(initialized.scope, uninitialized.scope)
        self.assertEqual(self.cli('status').returncode, 0)

    def test_worktrees_share_store_but_not_scope(self):
        """A shared canonical DB preserves branch/worktree boundaries and ignores."""
        self.put_sample()
        linked = self.area / 'linked'
        self.git('worktree', 'add', '-b', 'feature', str(linked))
        other = runtime.Host(linked)
        self.assertEqual(other.database, self.host.database)
        self.assertNotEqual(other.scope, self.host.scope)
        with runtime.connect(other) as connection:
            self.assertEqual(runtime.search(connection, other, '')['records'], [])
            rows = runtime.search(connection, other, '', all_scopes=True)['records']
            self.assertTrue(all(x['effective_validity'] == 'out_of_scope' for x in rows))
            runtime.update(connection, other, {'records': [{'id': 'feature', 'kind': 'finding', 'title': 'Feature only', 'summary': 'Specific to branch'}]})
        for project in (self.project, linked):
            self.assertTrue(self.git('check-ignore', '.evomneme/knowledge.sqlite3', project=project))
        (linked / 'source.txt').write_text('feature change', encoding='utf-8')
        with runtime.connect(runtime.Host(linked)) as connection:
            runtime.reconcile(connection, runtime.Host(linked))
            self.assertEqual(connection.execute("SELECT validity FROM records WHERE scope_id=? AND id='caller'", (self.host.scope,)).fetchone()[0], 'current')

    def test_clones_and_copied_databases_cannot_contaminate(self):
        """Clones use separate stores, and a copied store fails its owner check."""
        clone = self.area / 'clone'
        self.git('clone', str(self.project), str(clone), project=self.area)
        other = runtime.Host(clone)
        self.assertNotEqual(other.database, self.host.database)
        self.assertNotEqual(other.identity, self.host.identity)
        with runtime.connect(self.host) as connection:
            copy = sqlite3.connect(str(self.area / 'copied.sqlite3'))
            connection.backup(copy)
            copy.close()
        other.state.mkdir()
        shutil.copyfile(self.area / 'copied.sqlite3', other.database)
        with self.assertRaisesRegex(runtime.KnowledgeError, 'another project identity'):
            with runtime.connect(other):
                pass

    def test_concurrent_cli_writers_do_not_lose_updates(self):
        """Independent processes safely serialize distinct knowledge updates."""
        def writer(number):
            """Write one unique record through a separate SQLite process."""
            return self.cli('update', '-', payload={'records': [{'id': 'item-' + str(number), 'kind': 'finding', 'title': 'Concurrent finding', 'summary': 'Observed in parallel'}]})
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(writer, range(12)))
        self.assertTrue(all(x.returncode == 0 for x in results), [x.stderr for x in results if x.returncode])
        with runtime.connect(self.host) as connection:
            self.assertEqual(connection.execute('SELECT count(*) FROM records').fetchone()[0], 12)
            self.assertEqual(connection.execute('SELECT count(*) FROM history').fetchone()[0], 12)

    def test_concurrent_initializers_publish_identity_atomically(self):
        """Concurrent first use never exposes an ownerless or partial schema."""
        fresh = self.area / 'fresh'
        fresh.mkdir()
        self.git('init', '-b', 'main', project=fresh)
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: self.cli('init', project=fresh), range(4)))
        self.assertTrue(all(x.returncode == 0 for x in results), [x.stderr for x in results if x.returncode])
        host = runtime.Host(fresh)
        with runtime.connect(host, readonly=True) as connection:
            self.assertEqual(connection.execute("SELECT value FROM metadata WHERE key='project_identity'").fetchone()[0], host.identity)

    def test_symlink_evidence_escape_is_refused_when_supported(self):
        """Resolve source links before trusting their project confinement."""
        outside = self.area / 'outside.txt'
        outside.write_text('private', encoding='utf-8')
        link = self.project / 'escape.txt'
        try:
            link.symlink_to(outside)
        except OSError as exc:
            self.skipTest('Windows symlink creation unavailable: ' + str(exc))
        with self.assertRaises(runtime.KnowledgeError):
            self.host.source('escape.txt')

    def test_readonly_sql_is_bounded_and_cannot_modify_or_attach(self):
        """SQL escape hatches remain read-only and computationally bounded."""
        self.put_sample()
        with runtime.connect(self.host, readonly=True) as connection:
            for query in ('DELETE FROM records', "ATTACH DATABASE ':memory:' AS other", "SELECT load_extension('bad')", 'PRAGMA user_version=10'):
                with self.assertRaises(sqlite3.DatabaseError):
                    runtime.readonly_sql(connection, query)
            rows = runtime.readonly_sql(connection, 'WITH RECURSIVE n(x) AS (VALUES(1) UNION ALL SELECT x+1 FROM n WHERE x<200) SELECT x FROM n')
            self.assertEqual(len(rows['rows']), runtime.MAX_RESULTS)
            self.assertTrue(rows['truncated'])
            with self.assertRaises(sqlite3.DatabaseError):
                runtime.readonly_sql(connection, 'WITH RECURSIVE n(x) AS (VALUES(1) UNION ALL SELECT x+1 FROM n) SELECT sum(x) FROM n')

    def test_source_paths_cannot_escape_or_capture_ignored_state(self):
        """Prevent traversal, ignored private state and invalid source references."""
        (self.area / 'secret.txt').write_text('private', encoding='utf-8')
        ignored = self.project / 'ignored'
        ignored.mkdir()
        (ignored / 'secret.txt').write_text('private', encoding='utf-8')
        for path in ('../secret.txt', str(self.area / 'secret.txt'), '.git/config', '.evomneme/knowledge.sqlite3', 'ignored/secret.txt', 'absent.txt'):
            with self.assertRaises(runtime.KnowledgeError, msg=path):
                self.host.source(path)

    def test_sources_outside_snapshot_coverage_are_rejected_in_every_batch_section(self):
        """Reject excluded source components before any record, edge or evidence commits."""
        self.put_sample()
        paths = ['.evomneme-tests/source.txt', 'nested/.evomneme-tests/source.txt',
                 'nested/.evomneme/source.txt', 'nested/.git/source.txt',
                 'node_modules/source.txt', '.venv/source.txt', 'nested/__pycache__/source.txt']
        for name in paths:
            path = self.project / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('excluded contents', encoding='utf-8')
        for is_git, names in ((True, paths[:4]), (False, paths)):
            host = copy.copy(self.host)
            host.is_git = is_git
            for name in names:
                for section in ('records', 'relations', 'evidence'):
                    with self.subTest(is_git=is_git, source=name, section=section):
                        item = copy.deepcopy(self.sample()[section][0])
                        item['source_path'] = name
                        with runtime.connect(self.host) as connection:
                            before = connection.execute('SELECT count(*) FROM history').fetchone()[0]
                            with self.assertRaisesRegex(runtime.KnowledgeError, 'snapshot coverage'):
                                runtime.update(connection, host, {section: [item]})
                            self.assertEqual(connection.execute('SELECT count(*) FROM history').fetchone()[0], before)

    def test_live_loader_is_idempotent_and_preserves_host_instructions(self):
        """Preserve CRLF text, link live instructions, and report loading honestly."""
        agents = self.project / 'AGENTS.md'
        before = b'# Host instructions\r\nKeep user settings.\r\n'
        agents.write_bytes(before)
        skill = self.area / 'SKILL.md'
        skill.write_text('Live portable instructions', encoding='utf-8')
        override = self.project / 'AGENTS.override.md'
        override.write_text('Environment override', encoding='utf-8')
        first = runtime.integrate(self.host, skill)
        after = agents.read_bytes()
        self.assertTrue(after.startswith(before))
        self.assertNotIn(b'Live portable instructions', after)
        self.assertEqual(first['fresh_session_loading'], 'unverified')
        self.assertFalse(first['integration_complete'])
        self.assertIn(str(override), first['override_files'])
        second = runtime.integrate(self.host, skill)
        self.assertFalse(second['changed'])
        self.assertEqual(agents.read_bytes(), after)
        skill.write_text('Authorized instruction update', encoding='utf-8')
        third = runtime.integrate(self.host, skill)
        self.assertNotEqual(first['skill_sha256'], third['skill_sha256'])
        self.assertEqual(third['updated_instruction_loading'], 'unverified')
        # Text after the block is outside ownership and must survive replacement.
        agents.write_bytes(after + b'\r\n# Additional host rule\r\n')
        runtime.integrate(self.host, skill)
        self.assertTrue(agents.read_bytes().endswith(b'\r\n# Additional host rule\r\n'))

    def test_migration_and_future_schema_refusal(self):
        """Upgrade known v1 indexes while refusing an unknown future schema."""
        self.put_sample()
        with contextlib.closing(sqlite3.connect(self.host.database)) as connection, connection:
            connection.execute('DROP INDEX evidence_record')
            connection.execute('DROP INDEX evidence_relation')
            connection.execute("UPDATE metadata SET value='1' WHERE key='schema_version'")
            connection.execute('PRAGMA user_version=1')
        with runtime.connect(self.host, initialize=True) as connection:
            self.assertEqual(connection.execute('PRAGMA user_version').fetchone()[0], 2)
            self.assertEqual(connection.execute('SELECT count(*) FROM records').fetchone()[0], 3)
            self.assertEqual(connection.execute("SELECT count(*) FROM history WHERE action='migration'").fetchone()[0], 1)
        with contextlib.closing(sqlite3.connect(self.host.database)) as connection, connection:
            connection.execute('PRAGMA user_version=999')
        with self.assertRaisesRegex(runtime.KnowledgeError, 'newer'):
            with runtime.connect(self.host, initialize=True):
                pass
        with contextlib.closing(sqlite3.connect(self.host.database)) as connection, connection:
            self.assertEqual(connection.execute('PRAGMA user_version').fetchone()[0], 999)

    def test_corruption_reports_recovery_and_verify_checks_integrity(self):
        """Return recovery guidance without deleting the damaged database."""
        self.assertEqual(self.cli('verify').returncode, 0)
        self.host.database.write_bytes(b'not a sqlite database')
        result = self.cli('status')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Preserve the database', result.stderr)
        self.assertEqual(self.host.database.read_bytes(), b'not a sqlite database')

    def test_tool_repository_forks_and_worktrees_refused(self):
        """Keep actual tool code and charter-bearing fixture forks free of stores."""
        with self.assertRaisesRegex(runtime.KnowledgeError, 'own tool repository'):
            runtime.Host(REPOSITORY)
        (self.project / 'PROJECT_CHARTER.md').write_text(runtime.TOOL_CHARTER_MARKER, encoding='utf-8')
        with self.assertRaisesRegex(runtime.KnowledgeError, 'own tool repository'):
            runtime.Host(self.project)
        self.assertFalse((REPOSITORY / '.evomneme').exists())

    def test_state_remains_excluded_from_git(self):
        """Local knowledge and SQLite sidecars never appear as tracked candidates."""
        self.put_sample()
        self.assertEqual(self.git('status', '--porcelain'), b'')
        self.assertTrue(self.git('check-ignore', '.evomneme/knowledge.sqlite3'))


if __name__ == '__main__':
    unittest.main()
