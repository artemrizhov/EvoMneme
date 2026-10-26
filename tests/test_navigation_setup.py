"""Connection and launcher checks use only isolated synthetic projects/stores."""
import argparse
import base64
from contextlib import closing, redirect_stdout
import io
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import evomneme_connection as connection
import evomneme_install as install


class NavigationSetupTests(unittest.TestCase):
    def setUp(self):
        area = ROOT / '.evomneme-tests'
        area.mkdir(exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=area)
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.project = self.base / "project space ü & ' ! %"
        self.project.mkdir()
        (self.project / '.git').mkdir()
        self.database = self.base / 'knowledge.sqlite'
        with closing(sqlite3.connect(self.database)) as db, db:
            db.executescript((ROOT / 'schema.sql').read_text(encoding='utf-8'))
            db.execute('INSERT INTO scopes VALUES (?,?,?,?,?,?)', ('main', 'main', str(self.project), 'checkpoint', '', 'now'))
            db.execute("INSERT INTO nodes(scope_id,id,kind,title,summary,confidence,validity,updated_at) VALUES ('main','root','architecture','Root','Root','confirmed','current','now')")
        self.before = self.database.read_bytes()

    def connect(self, **kwargs):
        options = dict(database=self.database, scope='main', root_id='root', project=self.project, canonical_root=None, shell=None)
        options.update(kwargs)
        with redirect_stdout(io.StringIO()):
            return connection.run_setup(argparse.Namespace(**options))

    def test_receipt_preserves_fields_nested_discovery_and_store_bytes(self):
        receipt = self.project / connection.RECEIPT
        receipt.parent.mkdir()
        receipt.write_text(json.dumps({'notes': {'private': 'preserved'}, 'database': str(self.database)}), encoding='utf-8')
        self.connect()
        nested = self.project / 'src/nested'
        nested.mkdir(parents=True)
        binding = connection.discover(nested)
        self.assertEqual(binding.database, self.database)
        self.assertEqual(json.loads(receipt.read_text(encoding='utf-8'))['notes'], {'private': 'preserved'})
        with closing(sqlite3.connect(self.database)) as db, db:
            self.assertIn('persistent', ' '.join(connection.validate_binding(db, binding)))
        self.assertEqual(self.before, self.database.read_bytes())

    def test_copied_clone_and_nested_git_boundary_rejected(self):
        self.connect()
        clone = self.base / 'clone'
        shutil.copytree(self.project, clone)
        with self.assertRaisesRegex(connection.ConnectionError, 'copied receipts'):
            connection.discover(clone)
        nested = self.project / 'nested'
        nested.mkdir()
        (nested / '.git').mkdir()
        with self.assertRaisesRegex(connection.ConnectionError, 'No project connection'):
            connection.discover(nested)

    def test_linked_worktree_requires_explicit_canonical_binding(self):
        def git(*args):
            result = subprocess.run(['git', *args], capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr)
        # Only synthetic source repositories; the SQLite store stays outside Git.
        (self.project / '.git').rmdir()
        git('init', str(self.project))
        git('-C', str(self.project), '-c', 'user.name=Synthetic Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '--allow-empty', '-m', 'Synthetic source checkpoint')
        linked = self.base / 'linked'
        git('-C', str(self.project), 'worktree', 'add', '--detach', str(linked))
        self.connect(project=linked, canonical_root=self.project)
        self.assertEqual(connection.discover(linked).canonical_root, self.project)
        own = self.base / 'own-scope-worktree'
        git('-C', str(self.project), 'worktree', 'add', '--detach', str(own))
        with closing(sqlite3.connect(self.database)) as db, db:
            db.execute('INSERT INTO scopes VALUES (?,?,?,?,?,?)', ('own', 'main', str(own), 'checkpoint', '', 'now'))
            db.execute("INSERT INTO nodes(scope_id,id,kind,title,summary,confidence,validity,updated_at) VALUES ('own','root','architecture','Own Root','Root','confirmed','current','now')")
        self.before = self.database.read_bytes()
        self.connect(project=own, canonical_root=self.project, scope='own')
        binding = connection.discover(own)
        with closing(sqlite3.connect(self.database)) as db:
            connection.validate_binding(db, binding)
        clone = self.base / 'independent-clone'
        git('clone', str(self.project), str(clone))
        with self.assertRaisesRegex(connection.ConnectionError, 'independent Git repositories'):
            self.connect(project=clone, canonical_root=self.project)
        self.assertFalse((clone / connection.RECEIPT).exists())
        # A receipt edited to point at the clone must fail during ordinary discovery too.
        receipt = linked / connection.RECEIPT
        data = json.loads(receipt.read_text(encoding='utf-8'))
        (clone / '.evomneme').mkdir()
        data['project_root'] = str(clone)
        (clone / connection.RECEIPT).write_text(json.dumps(data), encoding='utf-8')
        with self.assertRaisesRegex(connection.ConnectionError, 'independent Git repositories'):
            connection.discover(clone)
        self.assertEqual(self.before, self.database.read_bytes())

    def test_unverifiable_cross_root_identity_fails(self):
        other = self.base / 'non-git'
        other.mkdir()
        with self.assertRaisesRegex(connection.ConnectionError, 'both roots must be Git worktrees'):
            connection._validate_root_identity(other, self.project)

    def test_scope_identity_and_receipt_collisions(self):
        self.connect()
        binding = connection.discover(self.project)
        with closing(sqlite3.connect(self.database)) as db, db:
            db.execute("UPDATE scopes SET worktree='different'")
            with self.assertRaisesRegex(connection.ConnectionError, 'worktree changed'):
                connection.validate_binding(db, binding)
            db.rollback()
            db.execute("INSERT INTO metadata VALUES ('project_identity','other')")
            with self.assertRaisesRegex(connection.ConnectionError, 'identity differs'):
                connection.validate_binding(db, binding)
        with self.assertRaisesRegex(connection.ConnectionError, 'different scope'):
            self.connect(scope='other')
        receipt = self.project / connection.RECEIPT
        receipt.write_text('{broken', encoding='utf-8')
        with self.assertRaisesRegex(connection.ConnectionError, 'Cannot read'):
            self.connect()

    def test_missing_scope_root_and_unsupported_store(self):
        for kwargs, message in (({'scope': 'absent'}, 'scope does not exist'), ({'root_id': 'absent'}, 'root does not exist')):
            with self.assertRaisesRegex(ValueError, message):
                self.connect(**kwargs)
        with closing(sqlite3.connect(self.database)) as db, db:
            db.execute('PRAGMA user_version=2')
        with self.assertRaisesRegex(ValueError, 'Unsupported'):
            self.connect()

    def test_checkpoint_and_dirty_warnings_allow_discovery(self):
        self.connect()
        def fake_git(argv, **kwargs):
            return subprocess.CompletedProcess(argv, 0, 'other-head' if 'rev-parse' in argv else ' M source.py', '')
        with patch.object(connection.subprocess, 'run', side_effect=fake_git):
            binding = connection.discover(self.project)
        self.assertIn('HEAD differs', ' '.join(binding.warnings))
        self.assertIn('working tree', ' '.join(binding.warnings))

    def test_install_path_collision_and_activation_no_environment_mutation(self):
        bin_dir = self.project / 'bin'
        bin_dir.mkdir()
        options = argparse.Namespace(bin_dir=bin_dir, activate=None)
        with patch.dict(os.environ, {'PATH': str(self.base)}):
            with self.assertRaisesRegex(install.InstallError, 'already in PATH'):
                install.run_setup(options)
        with patch.dict(os.environ, {'PATH': str(bin_dir)}), redirect_stdout(io.StringIO()):
            install.run_setup(options)
            with self.assertRaisesRegex(install.InstallError, 'existing command'):
                install.run_setup(options)
        activate = self.project / 'session'
        before = dict(os.environ)
        with patch.object(Path, 'cwd', return_value=self.project), redirect_stdout(io.StringIO()):
            install.run_setup(argparse.Namespace(bin_dir=None, activate=activate))
        self.assertEqual(dict(os.environ), before)
        self.assertIn("''", (activate / 'activate.ps1').read_text(encoding='utf-8'))
        self.assertIn('exec ', install.launcher_text('/python path', '/cli path', windows=False))

    @unittest.skipUnless(os.name == 'nt', 'native PowerShell launch requires Windows')
    def test_native_fresh_powershell_installed_command_from_nested_project(self):
        self.connect()
        bin_dir = self.project / 'bin'
        bin_dir.mkdir()
        with patch.dict(os.environ, {'PATH': str(bin_dir) + os.pathsep + os.environ.get('PATH', '')}), redirect_stdout(io.StringIO()):
            install.run_setup(argparse.Namespace(bin_dir=bin_dir, activate=None))
            environment = dict(os.environ)
        nested = self.project / 'src'
        nested.mkdir()
        result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', 'evomneme nodes root'], cwd=nested, env=environment, capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn('Root', result.stdout)
        links = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', 'evomneme links root root'], cwd=nested, env=environment, capture_output=True, text=True, timeout=20)
        self.assertEqual(links.returncode, 0, links.stderr + links.stdout)
        self.assertEqual(self.before, self.database.read_bytes())

    @unittest.skipUnless(os.name == 'nt', 'native PowerShell roundtrip requires Windows')
    def test_native_returned_commands_preserve_names_and_pipes(self):
        from evomneme_navigate import quote_command
        combined = '-Quarter "one" & O\'Brien %PATH% 📦'
        oversized = '-Huge "one" & O\'Brien %PATH% 📦'
        names = ['Quarter "one"', 'rate%PATH%', '-leading', 'a&b', "O'Brien", 'Квартал ü', combined]
        with closing(sqlite3.connect(self.database)) as db, db:
            for name in names:
                db.execute('INSERT INTO nodes(scope_id,id,kind,title,summary,confidence,validity,updated_at) VALUES (?,?,?,?,?,?,?,?)', ('main', name, 'architecture', name, name, 'confirmed', 'current', 'now'))
            db.execute('INSERT INTO edges(scope_id,id,source_id,target_id,kind,summary,confidence,validity,updated_at) VALUES (?,?,?,?,?,?,?,?,?)', ('main', 'special-link', 'root', combined, 'contains', 'Selected special name', 'confirmed', 'current', 'now'))
            db.execute('INSERT INTO nodes(scope_id,id,kind,title,summary,confidence,validity,updated_at) VALUES (?,?,?,?,?,?,?,?)', ('main', oversized, 'architecture', oversized, 'Large synthetic summary ' * 4000, 'confirmed', 'current', 'now'))
        self.before = self.database.read_bytes()
        self.connect()
        bin_dir = self.project / 'bin'
        bin_dir.mkdir()
        with patch.dict(os.environ, {'PATH': str(bin_dir) + os.pathsep + os.environ.get('PATH', '')}), redirect_stdout(io.StringIO()):
            install.run_setup(argparse.Namespace(bin_dir=bin_dir, activate=None))
            environment = dict(os.environ)
        def run(command):
            encoded = base64.b64encode(command.encode('utf-16le')).decode('ascii')
            return subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-EncodedCommand', encoded], cwd=self.project, env=environment, capture_output=True, encoding='utf-8', timeout=20)
        for name in names:
            command = quote_command(['evomneme', 'nodes', '--', name], 'powershell')
            result = run('[Console]::OutputEncoding = New-Object Text.UTF8Encoding($false); ' + command + ' | ForEach-Object { $_ }')
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            # The plain-text field must retain the exact name across every parser boundary.
            self.assertIn('title: ' + name + '\n', result.stdout)
            links_command = next(line.removeprefix('links_command: ') for line in result.stdout.splitlines() if line.startswith('links_command: '))
            returned = run('[Console]::OutputEncoding = New-Object Text.UTF8Encoding($false); ' + links_command + ' | ForEach-Object { $_ }')
            self.assertEqual(returned.returncode, 0, returned.stderr + returned.stdout)
            self.assertIn('complete:\n  scope: main\n', returned.stdout)
        failed = run(quote_command(['evomneme', 'nodes', '--', 'missing-name'], 'powershell'))
        self.assertNotEqual(failed.returncode, 0)
        # Follow the ready command returned for a link neighbor, without rebuilding it.
        linked = run('[Console]::OutputEncoding = New-Object Text.UTF8Encoding($false); ' + quote_command(['evomneme', 'links', '--', 'root'], 'powershell'))
        self.assertEqual(linked.returncode, 0, linked.stderr + linked.stdout)
        nodes_command = next(line.removeprefix('nodes_command: ') for line in linked.stdout.splitlines() if line.startswith('nodes_command: '))
        followed = run('[Console]::OutputEncoding = New-Object Text.UTF8Encoding($false); ' + nodes_command)
        self.assertEqual(followed.returncode, 0, followed.stderr + followed.stdout)
        self.assertIn('title: ' + combined + '\n', followed.stdout)
        # The guard's returned retry must traverse the installed bridge as well.
        bounded_command = quote_command(['evomneme', 'nodes', '--', oversized], 'powershell')
        bounded = run('[Console]::OutputEncoding = New-Object Text.UTF8Encoding($false); ' + bounded_command + ' 2>&1 | ForEach-Object { $_.ToString() }; exit $LASTEXITCODE')
        self.assertNotEqual(bounded.returncode, 0)
        error_text = bounded.stdout + bounded.stderr
        self.assertIn('Full output: ', error_text)
        retry = error_text.split('Full output: ', 1)[1].splitlines()[0]
        self.assertTrue(retry.startswith("& 'evomneme' 'nodes' '--all' '--' "), retry)
        expanded = run('[Console]::OutputEncoding = New-Object Text.UTF8Encoding($false); ' + retry)
        self.assertEqual(expanded.returncode, 0, expanded.stderr + expanded.stdout)
        self.assertIn('title: ' + oversized + '\n', expanded.stdout)
        self.assertIn('complete:\n  scope: main\n', expanded.stdout)
        self.assertGreater(len(expanded.stdout.encode('utf-8')), 65536)
        self.assertEqual(self.before, self.database.read_bytes())


if __name__ == '__main__':
    unittest.main()
