"""Host contract diagnostics and acceptance use isolated project receipts/stores."""
import argparse
from contextlib import closing, redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import evomneme_contract as contract
import evomneme_connection as connection
from evomneme import Executor


class IntegrationContractTests(unittest.TestCase):
    def setUp(self):
        area = ROOT / '.evomneme-tests'
        area.mkdir(exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=area)
        self.addCleanup(self.tmp.cleanup)
        self.project = Path(self.tmp.name).resolve()
        initialized = subprocess.run(['git', 'init', str(self.project)], capture_output=True, text=True, timeout=5)
        self.assertEqual(initialized.returncode, 0, initialized.stderr)
        self.database = self.project / '.evomneme/knowledge.sqlite3'
        self.database.parent.mkdir()
        with closing(sqlite3.connect(self.database)) as db, db:
            db.executescript((ROOT / 'schema.sql').read_text(encoding='utf-8'))
            db.execute('INSERT INTO scopes VALUES (?,?,?,?,?,?)', ('main', 'main', str(self.project), 'checkpoint', '', 'now'))
            db.execute("INSERT INTO nodes(scope_id,id,kind,title,summary,confidence,validity,updated_at) VALUES ('main','root','architecture','Root','Root','confirmed','current','now')")
            db.execute("INSERT INTO metadata VALUES ('project_identity', 'fixture-contract')")
        self.receipt = self.project / connection.RECEIPT
        self.data = dict(version=1, database=str(self.database), project_root=str(self.project),
                         canonical_root=str(self.project), scope='main', root_id='root', shell='posix',
                         project_identity='fixture-contract', scope_worktree=str(self.project),
                         checkpoint_revision='checkpoint', notes={'unrelated': ['keep']})
        self.save()

    def save(self):
        self.receipt.write_text(json.dumps(self.data), encoding='utf-8')

    def accept(self, **options):
        args = dict(project=self.project, from_version='unversioned', to_version=1,
                    verification='Fixture binding, schema and loader inspected; no semantic changes needed; fresh session unavailable')
        args.update(options)
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            return connection.run_acceptance(argparse.Namespace(**args))

    def command(self, script, *arguments):
        return subprocess.run([sys.executable, str(ROOT / 'scripts' / script), *arguments],
                              cwd=self.project, capture_output=True, text=True, encoding='utf-8', timeout=20)

    def test_missing_old_current_future_invalid_states(self):
        self.assertIn('unversioned', contract.diagnostic(start=self.project, bound=True))
        self.data.update(integration_contract_version=1, verified_schema_version=3)
        self.save()
        self.assertIsNone(contract.diagnostic(start=self.project, bound=True))
        with patch.object(contract, 'REQUIRED_CONTRACT', 3):
            self.assertIn('2..3', contract.diagnostic(start=self.project, bound=True))
        self.data['integration_contract_version'] = 2
        self.save()
        self.assertIn('never downgrade', contract.diagnostic(start=self.project, bound=True))
        for value in (True, '1', 0, -1):
            self.data['integration_contract_version'] = value
            self.save()
            self.assertIn('invalid accepted', contract.diagnostic(start=self.project, bound=True))
        self.data.update(integration_contract_version=1, verified_schema_version='3')
        self.save()
        self.assertIn('schema is missing/incompatible', contract.diagnostic(start=self.project, bound=True))

    def test_corrupt_duplicate_large_and_absent_receipts(self):
        for raw in ('{', '[]', '{"version":1,"version":1}', ' ' * (contract.MAX_RECEIPT_BYTES + 1)):
            self.receipt.write_text(raw, encoding='utf-8')
            self.assertIn('corrupt', contract.diagnostic(start=self.project, bound=True))
        self.receipt.unlink()
        self.assertIn('no connection receipt', contract.diagnostic(start=self.project, bound=True))
        self.assertIsNone(contract.diagnostic(start=self.project, database=self.database))

    def test_checker_has_no_external_work_or_database_access(self):
        with patch('subprocess.run', side_effect=AssertionError('subprocess forbidden')), \
                patch('sqlite3.connect', side_effect=AssertionError('SQL forbidden')):
            self.assertIn('unversioned', contract.diagnostic(start=self.project, database=self.database))

    def test_acceptance_preserves_fields_schema_and_database(self):
        before = self.database.read_bytes()
        self.accept()
        data = json.loads(self.receipt.read_text(encoding='utf-8'))
        self.assertEqual(data['notes'], self.data['notes'])
        self.assertEqual(data['integration_contract_version'], 1)
        self.assertEqual(data['verified_schema_version'], 3)
        self.assertEqual(data['integration_verifications'][0]['from_version'], 'unversioned')
        self.assertEqual(before, self.database.read_bytes())
        self.assertIsNone(contract.diagnostic(start=self.project, bound=True))
        with self.assertRaises(ValueError):
            self.accept()
        with self.assertRaises(ValueError):
            self.accept(from_version='1', to_version=1)

    def test_acceptance_rejects_skips_future_empty_notes_bad_binding_schema(self):
        before = self.receipt.read_bytes()
        for options in ({'to_version': 2}, {'from_version': '1'}, {'verification': ' '}):
            with self.assertRaises(ValueError):
                self.accept(**options)
            self.assertEqual(before, self.receipt.read_bytes())
        self.data['integration_contract_version'] = 2
        self.save()
        with self.assertRaises(ValueError):
            self.accept(from_version='2', to_version=1)
        del self.data['integration_contract_version']
        self.data['project_identity'] = 'wrong'
        self.save()
        with self.assertRaisesRegex(ValueError, 'identity'):
            self.accept()
        self.data['project_identity'] = 'fixture-contract'
        self.save()
        with closing(sqlite3.connect(self.database)) as db, db:
            db.execute('PRAGMA user_version=2')
        with self.assertRaisesRegex(ValueError, 'schema version'):
            self.accept()
        self.assertNotIn('integration_contract_version', json.loads(self.receipt.read_text(encoding='utf-8')))

    def test_interruption_and_concurrent_change_leave_acceptance_pending(self):
        before = self.receipt.read_bytes()
        with patch.object(connection.os, 'replace', side_effect=OSError('interrupted')):
            with self.assertRaisesRegex(OSError, 'interrupted'):
                self.accept()
        self.assertEqual(before, self.receipt.read_bytes())
        self.assertEqual([self.receipt.name, self.database.name], sorted(path.name for path in self.receipt.parent.iterdir()))
        changed = dict(self.data, concurrent='preserve')
        original_validate = connection.validate_binding
        def concurrent(db, binding):
            result = original_validate(db, binding)
            self.receipt.write_text(json.dumps(changed), encoding='utf-8')
            return result
        with patch.object(connection, 'validate_binding', side_effect=concurrent):
            with self.assertRaisesRegex(ValueError, 'changed during'):
                self.accept()
        self.assertEqual(json.loads(self.receipt.read_text(encoding='utf-8')), changed)
        self.accept()
        self.assertEqual(json.loads(self.receipt.read_text(encoding='utf-8'))['integration_contract_version'], 1)

    def test_setup_does_not_certify_new_or_old_host(self):
        for existing in (True, False):
            if not existing:
                self.receipt.unlink()
            args = argparse.Namespace(database=self.database, scope='main', root_id='root',
                                      project=self.project, canonical_root=None, shell=None)
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                connection.run_setup(args)
            self.assertNotIn('integration_contract_version', json.loads(self.receipt.read_text(encoding='utf-8')))

    def test_sequential_transitions_and_cli_acceptance(self):
        result = self.command('evomneme_cli.py', 'accept-integration', '--from-version', 'unversioned',
                              '--to-version', '1', '--verification', 'Fixture binding/schema/loader inspected; environment limits recorded')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(result.stderr.startswith('EvoMneme integration contract:'))
        with patch.object(connection, 'REQUIRED_CONTRACT', 3):
            with self.assertRaises(ValueError):
                self.accept(from_version='1', to_version=3)
            self.accept(from_version='1', to_version=2)
            self.accept(from_version='2', to_version=3)
        data = json.loads(self.receipt.read_text(encoding='utf-8'))
        self.assertEqual([entry['to_version'] for entry in data['integration_verifications']], [1, 2, 3])
        self.assertEqual(data['notes'], self.data['notes'])

    def test_bound_success_chain_parse_runtime_error_first_stderr(self):
        for arguments, success in ((('nodes', 'root'), True),
                                   (('nodes', 'root', '--next', 'links', 'root'), True),
                                   (('unknown-command',), False),
                                   (('nodes', 'root', '--next', 'connect'), False),
                                   (('nodes', 'missing'), False)):
            with self.subTest(arguments=arguments):
                result = self.command('evomneme_cli.py', *arguments)
                self.assertEqual(result.returncode == 0, success, result.stderr)
                self.assertTrue(result.stderr.splitlines()[0].startswith('EvoMneme integration contract:'), result.stderr)
                self.assertEqual(result.stderr.count('EvoMneme integration contract:'), 1)

    def test_machine_routes_keep_json_and_warn_before_errors(self):
        result = self.command('evomneme.py', '--database', str(self.database), '--sql', 'SELECT 1', '--no-history')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)['ok'])
        self.assertTrue(result.stderr.startswith('EvoMneme integration contract:'))
        for script in ('evomneme.py', 'evomneme_viewer.py', 'evomneme_journal.py', 'export_website_demo.py'):
            with self.subTest(script=script):
                result = self.command(script, '--database', str(self.database), '--unknown')
                self.assertNotEqual(result.returncode, 0)
                self.assertTrue(result.stderr.startswith('EvoMneme integration contract:'), result.stderr)

    def test_actual_cli_target_uses_last_abbreviation_equals_and_end_marker(self):
        foreign = self.project / 'foreign.sqlite'
        with closing(sqlite3.connect(foreign)):
            pass
        cases = (
            (['--database', str(foreign), '--database', str(self.database)], True),
            (['--database', str(self.database), '--database', str(foreign)], False),
            (['--dat', str(self.database)], True),
            (['--d=' + str(self.database)], True),
            (['--database=' + str(foreign), '--dat=' + str(self.database)], True),
        )
        for target, warning in cases:
            with self.subTest(target=target):
                result = self.command('evomneme.py', *target, '--sql', 'SELECT 1', '--no-history')
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertTrue(json.loads(result.stdout)['ok'])
                self.assertEqual(result.stderr.startswith('EvoMneme integration contract:'), warning, result.stderr)
        # A literal option after -- cannot replace the parser's earlier target.
        result = self.command('evomneme.py', '--database', str(self.database), '--sql', 'SELECT 1',
                              '--', '--database', str(foreign))
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(result.stderr.startswith('EvoMneme integration contract:'), result.stderr)
        # Setup has its own --project target; abbreviated/repeated options must
        # diagnose the actual project even when cwd's receipt is already current.
        current = self.project / 'current'
        (current / '.evomneme').mkdir(parents=True)
        (current / '.git').mkdir()
        (current / connection.RECEIPT).write_text(json.dumps(dict(self.data,
            project_root=str(current), integration_contract_version=1, verified_schema_version=3)), encoding='utf-8')
        for options in (['--project', str(current), '--project', str(self.project)],
                        ['--project=' + str(current), '--pro=' + str(self.project)]):
            with self.subTest(options=options):
                result = self.command('evomneme_cli.py', 'connect', str(self.database), '--scope', 'main',
                                      '--root', 'root', *options)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertTrue(result.stderr.startswith('EvoMneme integration contract:'), result.stderr)
                self.assertIn(str(self.receipt), result.stderr.splitlines()[0])

    def test_acceptance_final_utf8_receipt_bound_preserves_predecessor(self):
        before = self.receipt.read_bytes()
        for verification in ('x' * contract.MAX_RECEIPT_BYTES, '界' * (contract.MAX_RECEIPT_BYTES // 2)):
            with self.subTest(unicode=verification[0] == '界'):
                with self.assertRaisesRegex(ValueError, 'exceeds 256 KiB'):
                    self.accept(verification=verification)
                self.assertEqual(self.receipt.read_bytes(), before)
                self.assertIn('unversioned', contract.diagnostic(start=self.project, bound=True))
        # Input itself is readable but appending acceptance fields crosses bound.
        self.data['near_limit'] = '界' * ((contract.MAX_RECEIPT_BYTES - 1000) // 3)
        self.receipt.write_text(json.dumps(self.data, ensure_ascii=False), encoding='utf-8')
        self.assertLess(len(self.receipt.read_bytes()), contract.MAX_RECEIPT_BYTES)
        near_limit = self.receipt.read_bytes()
        with self.assertRaisesRegex(ValueError, 'exceeds 256 KiB'):
            self.accept(verification='verified ' * 200)
        self.assertEqual(self.receipt.read_bytes(), near_limit)
        # A substantial Unicode note below the bound remains readable afterwards.
        self.data.pop('near_limit')
        self.save()
        self.accept(verification='界' * (contract.MAX_RECEIPT_BYTES // 6))
        self.assertLessEqual(len(self.receipt.read_bytes()), contract.MAX_RECEIPT_BYTES)
        self.assertEqual(contract.read_receipt(self.receipt)['integration_contract_version'], 1)

    def test_direct_sql_checks_each_request_and_foreign_database_stays_generic(self):
        output = io.StringIO()
        with redirect_stderr(output):
            executor = Executor(str(self.database), history=False)
            try:
                result = executor.execute_sql(sql='SELECT 1')
                self.assertTrue(result['ok'])
                self.data.update(integration_contract_version=1, verified_schema_version=3)
                self.save()
                executor.execute_sql(sql='SELECT 1')
            finally:
                executor.close()
        self.assertEqual(output.getvalue().count('EvoMneme integration contract:'), 2)
        foreign = self.project / 'foreign.sqlite'
        with closing(sqlite3.connect(foreign)):
            pass
        self.assertIsNone(contract.diagnostic(start=self.project, database=foreign))
        before = self.receipt.read_bytes()
        result = self.command('evomneme.py', '--database', str(foreign), '--sql', 'SELECT 1', '--no-history')
        self.assertTrue(json.loads(result.stdout)['ok'])
        self.assertEqual(result.stderr, '')
        self.assertEqual(before, self.receipt.read_bytes())


if __name__ == '__main__':
    unittest.main()
