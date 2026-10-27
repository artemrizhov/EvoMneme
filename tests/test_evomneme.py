"""Isolated contract tests for native SQL over Python and CLI."""

import base64
import concurrent.futures
import contextlib
import importlib.util
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

REPOSITORY = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPOSITORY / 'scripts'))
SCRIPT = REPOSITORY / 'scripts' / 'evomneme.py'
SPEC = importlib.util.spec_from_file_location('evomneme_sql_test', SCRIPT)
runtime = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runtime)
TEST_AREA = REPOSITORY / '.evomneme-tests'


class ExecutorTests(unittest.TestCase):
    """Keep SQL contract checks isolated from every real project store."""

    def setUp(self):
        """Bind a new empty isolated database explicitly."""
        TEST_AREA.mkdir(exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=TEST_AREA)
        self.addCleanup(self.temporary.cleanup)
        self.area = Path(self.temporary.name)
        self.database = self.area / 'host.sqlite3'
        self.executor = runtime.Executor(self.database, create=True)
        self.addCleanup(self.executor.close)

    def execute(self, sql, **kwargs):
        """Use the native Python entry point."""
        return self.executor.execute_sql(sql=sql, **kwargs)

    def rows(self, sql):
        """Require successful execution before inspecting rows."""
        result = self.execute(sql)
        self.assertTrue(result['ok'], result)
        return result['results'][-1]['rows']

    def cli(self, *args, input_bytes=None, database=None):
        """Run the real UTF-8 CLI without shell interpolation."""
        return subprocess.run([sys.executable, str(SCRIPT), '--database', str(database or self.database), *args],
                              input=input_bytes, capture_output=True)

    def test_explicit_binding_creation_and_database_separation(self):
        """Explicit bindings stay independent of an existing project knowledge store."""
        knowledge = self.area / '.evomneme' / 'knowledge.sqlite3'
        knowledge.parent.mkdir()
        with contextlib.closing(sqlite3.connect(knowledge)) as project_store:
            project_store.execute('CREATE TABLE sentinel(value TEXT)')
            project_store.execute("INSERT INTO sentinel VALUES('project knowledge')")
            project_store.commit()
        before = knowledge.read_bytes()
        with contextlib.chdir(self.area):
            with self.assertRaises(TypeError):
                runtime.Executor()
            implicit = subprocess.run([sys.executable, str(SCRIPT), '--sql', 'CREATE TABLE implicit(value)'],
                                      capture_output=True)
            self.assertNotEqual(implicit.returncode, 0)
            self.assertIn(b'--database', implicit.stderr)
            self.assertEqual(self.rows("SELECT name FROM sqlite_master WHERE type='table'"), [])
            with self.assertRaises(FileNotFoundError):
                runtime.Executor(self.area / 'missing.sqlite3')
            with self.assertRaises(FileExistsError):
                runtime.Executor(self.database, create=True)
            with self.assertRaises(runtime.RequestError):
                runtime.Executor('relative.sqlite3')
            second = runtime.Executor(self.area / 'other.sqlite3', create=True)
            self.addCleanup(second.close)
            self.assertTrue(self.execute('CREATE TABLE private(value)')['ok'])
            self.assertEqual(second.execute_sql(sql="SELECT name FROM sqlite_master WHERE type='table'")['results'][0]['rows'], [])
            self.assertTrue(second.execute_sql(sql='CREATE TABLE separate(value)')['ok'])
            self.assertEqual(self.rows("SELECT name FROM sqlite_master WHERE type='table'"), [['private']])
            with contextlib.closing(runtime.Executor(self.database)) as rebound:
                self.assertEqual(rebound.path, self.database)
                self.assertEqual(rebound.execute_sql(sql="SELECT name FROM sqlite_master WHERE type='table'")['results'][0]['rows'], [['private']])
            self.assertFalse((self.area / 'missing.sqlite3').exists())
            self.assertFalse((self.area / 'relative.sqlite3').exists())
        self.assertEqual(knowledge.read_bytes(), before)
        with contextlib.closing(sqlite3.connect(knowledge)) as project_store:
            self.assertEqual(project_store.execute('SELECT * FROM sentinel').fetchall(), [('project knowledge',)])
        self.assertEqual(knowledge.read_bytes(), before)

    def test_single_and_batch_results_are_identical_on_python_and_cli(self):
        """One named API, defaults and result format span both entry points."""
        for sql, params in (('SELECT ? AS value', ["O'Reilly 世界"]),
                            ([{'sql': 'SELECT ? AS value', 'params': ["O'Reilly 世界"]},
                              {'sql': 'SELECT :number AS number', 'params': {'number': 7}}], None)):
            arguments = {'sql': sql}
            if params is not None:
                arguments['params'] = params
            direct = self.executor.execute_sql(**arguments)
            cli = self.cli('--input', '-', input_bytes=runtime.json_bytes(arguments))
            self.assertEqual(cli.returncode, 0, cli.stderr)
            self.assertEqual(json.loads(cli.stdout), direct)

    def test_mutating_batch_with_per_statement_parameters_matches_python_and_cli(self):
        """Explicit arrays preserve bindings and effects on independent empty stores."""
        arguments = {'sql': [{'sql': 'CREATE TABLE value(text)'}, {'sql': 'INSERT INTO value VALUES(?)', 'params': ['quoted; 世界']},
                             {'sql': 'SELECT text FROM value'}]}
        direct = self.executor.execute_sql(**arguments)
        cli_path = self.area / 'cli.sqlite3'
        cli = self.cli('--create', '--input', '-', database=cli_path, input_bytes=runtime.json_bytes(arguments))
        self.assertEqual(json.loads(cli.stdout), direct)
        self.assertTrue(direct['autocommit_effects_possible'])
        self.assertEqual(direct['completed_statements'], 3)

    def test_shared_defaults_bounds_and_validation(self):
        """Python and CLI enforce the shared execution limits."""
        for key, (default, lower, upper) in runtime.LIMITS.items():
            for value in (default, lower, upper, lower - 1, upper + 1):
                with self.subTest(limit=key, value=value):
                    args = {'sql': 'SELECT 1', key: value}
                    direct = self.executor.execute_sql(**args)
                    cli = self.cli('--input', '-', input_bytes=runtime.json_bytes(args))
                    self.assertEqual(direct['ok'], lower <= value <= upper)
                    self.assertEqual(json.loads(cli.stdout), direct)
        self.assertFalse(self.execute([{'sql': 'SELECT 1'}], params=[])['ok'])
        self.assertFalse(self.execute([{'sql': 'SELECT 1', 'unexpected': 2}])['ok'])

    def test_native_single_statement_no_script_splitting_but_trigger_body_is_intact(self):
        """SQLite handles quotes/comments/triggers; raw scripts fail without partial execution."""
        self.assertTrue(self.execute('CREATE TABLE event(value)')['ok'])
        self.assertTrue(self.execute('CREATE TABLE audit(value)')['ok'])
        trigger = "CREATE TRIGGER logged AFTER INSERT ON event BEGIN INSERT INTO audit VALUES('seen; event'); INSERT INTO audit VALUES(NEW.value); END"
        self.assertTrue(self.execute(trigger)['ok'])
        self.assertTrue(self.execute('INSERT INTO event VALUES(?)', params=["O'Reilly; 世界"])['ok'])
        self.assertEqual(self.rows('SELECT value FROM audit'), [['seen; event'], ["O'Reilly; 世界"]])
        self.assertEqual(self.execute('SELECT ?; -- trailing comment', params=[7])['results'][0]['rows'], [[7]])
        raw = self.execute('CREATE TABLE half(value); INSERT INTO half VALUES(1)')
        self.assertFalse(raw['ok'])
        self.assertIn('array', raw['error']['message'])
        self.assertEqual(self.rows("SELECT name FROM sqlite_master WHERE name='half'"), [])
        cli = self.cli('--sql-file', '-', input_bytes=b'CREATE TABLE raw_script(value); SELECT 1')
        self.assertNotEqual(cli.returncode, 0)
        self.assertEqual(self.rows("SELECT name FROM sqlite_master WHERE name='raw_script'"), [])

    def test_native_explicit_transactions_and_savepoints(self):
        """Callers may begin, commit, rollback and use savepoints within one batch."""
        self.assertTrue(self.execute('CREATE TABLE value(number UNIQUE)')['ok'])
        result = self.execute([{'sql': sql} for sql in (
            'BEGIN', 'INSERT INTO value VALUES(1)', 'SAVEPOINT s', 'INSERT INTO value VALUES(2)',
            'ROLLBACK TO s', 'RELEASE s', 'COMMIT')])
        self.assertTrue(result['ok'], result)
        self.assertTrue(result['autocommit_effects_possible'])
        self.assertEqual(self.rows('SELECT number FROM value'), [[1]])
        result = self.execute([{'sql': 'SAVEPOINT outer'}, {'sql': 'INSERT INTO value VALUES(3)'}, {'sql': 'RELEASE outer'}])
        self.assertTrue(result['ok'], result)
        self.assertEqual(self.rows('SELECT number FROM value ORDER BY number'), [[1], [3]])

    def test_partial_autocommit_failure_reports_completed_statements_and_preserves_effects(self):
        """An error cannot pretend already committed native statements were rolled back."""
        result = self.execute([{'sql': 'CREATE TABLE value(number UNIQUE)'}, {'sql': 'INSERT INTO value VALUES(?)', 'params': [1]},
                               {'sql': 'INSERT INTO value VALUES(1)'}])
        self.assertFalse(result['ok'])
        self.assertEqual(result['completed_statements'], 2)
        self.assertEqual(result['error']['failed_statement_index'], 2)
        self.assertTrue(result['autocommit_effects_possible'])
        self.assertFalse(result['transaction_rolled_back'])
        self.assertEqual(self.rows('SELECT * FROM value'), [[1]])

    def test_metadata_failure_reports_commit_or_release_before_output_processing(self):
        """A completed native commit remains reported when its output cannot fit."""
        self.assertTrue(self.execute('CREATE TABLE persisted(value)')['ok'])
        for opener, closer in (('BEGIN', 'COMMIT'), ('SAVEPOINT outer', 'RELEASE outer')):
            for selects in (4, 5):
                with self.subTest(closer=closer, selects=selects):
                    self.assertTrue(self.execute('DELETE FROM persisted')['ok'])
                    batch = [{'sql': opener}, {'sql': 'INSERT INTO persisted VALUES(1)'}]
                    batch += [{'sql': 'SELECT 1'} for _ in range(selects)]
                    batch.append({'sql': closer})
                    result = self.execute(batch, max_output_bytes=1024)
                    self.assertFalse(result['ok'])
                    self.assertIn('metadata', result['error']['message'])
                    if selects == 4:
                        self.assertEqual(result['completed_statements'], 7)
                        self.assertTrue(result['autocommit_effects_possible'])
                        self.assertFalse(result['transaction_rolled_back'])
                        self.assertEqual(self.rows('SELECT count(*) FROM persisted'), [[1]])
                    else:
                        self.assertEqual(result['completed_statements'], 6)
                        self.assertFalse(result['autocommit_effects_possible'])
                        self.assertTrue(result['transaction_rolled_back'])
                        self.assertEqual(self.rows('SELECT count(*) FROM persisted'), [[0]])

    def test_explicit_atomic_batch_failure_and_unclosed_request_cleanup(self):
        """Only an open caller transaction is rolled back; nothing leaks to the next call."""
        self.assertTrue(self.execute('CREATE TABLE value(number UNIQUE)')['ok'])
        failed = self.execute([{'sql': sql} for sql in ('BEGIN', 'INSERT INTO value VALUES(1)', 'INSERT INTO value VALUES(1)', 'COMMIT')])
        self.assertFalse(failed['ok'])
        self.assertTrue(failed['transaction_rolled_back'])
        self.assertFalse(failed['autocommit_effects_possible'])
        self.assertEqual(self.rows('SELECT * FROM value'), [])
        unfinished = self.execute([{'sql': 'BEGIN'}, {'sql': 'INSERT INTO value VALUES(2)'}])
        self.assertFalse(unfinished['ok'])
        self.assertEqual(unfinished['error']['kind'], 'transaction')
        self.assertTrue(unfinished['transaction_rolled_back'])
        self.assertFalse(self.executor.connection.in_transaction)
        self.assertEqual(self.rows('SELECT * FROM value'), [])
        self.assertTrue(self.execute([{'sql': 'BEGIN'}, {'sql': 'INSERT INTO value VALUES(3)'}, {'sql': 'ROLLBACK'}])['ok'])
        self.assertEqual(self.rows('SELECT * FROM value'), [])

    def test_commit_constraint_failure_rolls_back_open_transaction(self):
        """Native deferred constraints must not turn a failed COMMIT into success."""
        self.assertTrue(self.execute([{'sql': 'CREATE TABLE parent(id PRIMARY KEY)'},
                                     {'sql': 'CREATE TABLE child(id REFERENCES parent(id) DEFERRABLE INITIALLY DEFERRED)'}])['ok'])
        result = self.execute([{'sql': 'BEGIN'}, {'sql': 'INSERT INTO child VALUES(99)'}, {'sql': 'COMMIT'}])
        self.assertFalse(result['ok'])
        self.assertTrue(result['transaction_rolled_back'])
        self.assertEqual(result['error']['sqlite_errorname'], 'SQLITE_CONSTRAINT_FOREIGNKEY')
        self.assertEqual(self.rows('SELECT * FROM child'), [])

    def test_native_maintenance_and_temporary_workspace_allow_no_external_destination(self):
        """VACUUM/PRAGMA and temporary attachment cleanup work; persistent escapes do not."""
        self.assertTrue(self.execute('VACUUM')['ok'])
        self.assertTrue(self.execute('PRAGMA journal_mode=WAL')['ok'])
        self.assertTrue(self.execute('PRAGMA user_version=999')['ok'])
        self.assertEqual(self.rows('PRAGMA user_version'), [[999]])
        self.assertTrue(self.execute([{'sql': "ATTACH '' AS scratch"}, {'sql': 'DETACH scratch'}])['ok'])
        external = self.area / 'escape.sqlite3'
        for sql, params in (('ATTACH DATABASE ? AS other', [str(external)]),
                            ("ATTACH ':memory:' AS other", []), ('VACUUM INTO ?', [str(external)]),
                            ("SELECT load_extension('unused')", [])):
            with self.subTest(sql=sql):
                self.assertFalse(self.execute(sql, params=params)['ok'])
        self.assertFalse(external.exists())

    def test_temporary_attach_is_literal_only_and_bound_filenames_stay_denied(self):
        """The authorizer sees an empty literal, not the value of an ATTACH parameter."""
        self.assertTrue(self.execute([{'sql': "ATTACH '' AS literal_scratch"}, {'sql': 'DETACH literal_scratch'}])['ok'])
        external = self.area / 'external.sqlite3'
        for destination in ('', str(external)):
            with self.subTest(destination=destination):
                result = self.execute('ATTACH ? AS bound_scratch', params=[destination])
                self.assertFalse(result['ok'])
                self.assertEqual(result['error']['sqlite_errorname'], 'SQLITE_AUTH')
        self.assertFalse(external.exists())
        self.assertEqual([row[1] for row in self.rows('PRAGMA database_list')], ['main'])

    def test_select_prefix_stops_early_and_does_not_count_omitted_rows(self):
        """A bounded SELECT needs only its prefix/lookahead, not a complete table scan."""
        seen = []
        self.executor.connection.create_function('observed', 1, lambda value: seen.append(value) or value)
        result = self.execute('WITH RECURSIVE n(x) AS (VALUES(1) UNION ALL SELECT x+1 FROM n WHERE x<1000000) SELECT observed(x) FROM n', max_rows=2, timeout_ms=100)
        self.assertTrue(result['ok'], result)
        self.assertEqual(result['results'][0]['rows'], [[1], [2]])
        self.assertTrue(result['results'][0]['has_more'])
        self.assertLess(len(seen), 10)
        self.assertNotIn('rows_omitted', result['results'][0])

    def test_truncated_returning_finishes_all_writes_and_detects_late_busy(self):
        """Engine write metadata distinguishes RETURNING from early-stoppable SELECT."""
        self.assertTrue(self.execute('CREATE TABLE returned(value)')['ok'])
        result = self.execute('INSERT INTO returned VALUES(1),(2),(3),(4),(5) RETURNING value', max_rows=1)
        self.assertTrue(result['ok'], result)
        self.assertEqual(result['results'][0]['rows'], [[1]])
        self.assertTrue(result['results'][0]['has_more'])
        self.assertEqual(result['results'][0]['affected_rows'], 5)
        self.assertEqual(self.rows('SELECT count(*) FROM returned'), [[5]])
        with contextlib.closing(sqlite3.connect(self.database, isolation_level=None)) as blocker:
            blocker.execute('BEGIN')
            blocker.execute('SELECT * FROM returned').fetchall()
            late = self.execute('INSERT INTO returned VALUES(6),(7) RETURNING value', max_rows=0, timeout_ms=40)
            blocker.execute('ROLLBACK')
        self.assertFalse(late['ok'])
        self.assertEqual(late['error']['sqlite_errorname'], 'SQLITE_BUSY')
        self.assertEqual(self.rows('SELECT count(*) FROM returned'), [[5]])

    def test_incremental_byte_budget_and_large_metadata(self):
        """Encoding work is per new row/metadata, not repeated accumulated result serialization."""
        original = runtime.json_bytes
        accumulated_encodes = []
        def observe(value):
            """Record full-response encoding while retaining the real codec."""
            if isinstance(value, dict) and value.get('results'):
                accumulated_encodes.append(len(value['results']))
            return original(value)
        with patch.object(runtime, 'json_bytes', side_effect=observe):
            result = self.execute('WITH RECURSIVE n(x) AS (VALUES(1) UNION ALL SELECT x+1 FROM n WHERE x<50) SELECT x FROM n', max_rows=50)
        self.assertTrue(result['ok'])
        self.assertEqual(accumulated_encodes, [])
        self.assertLessEqual(len(original(result)), runtime.LIMITS['max_output_bytes'][0])
        large = self.execute("SELECT printf('%02000d',1) AS payload", max_output_bytes=1024)
        self.assertTrue(large['ok'])
        self.assertEqual(large['results'][0]['rows'], [])
        self.assertTrue(large['results'][0]['has_more'])
        self.assertLessEqual(len(original(large)), 1024)
        overflow = self.execute('SELECT 1 AS "' + ('column_' * 400) + '"', max_output_bytes=1024)
        self.assertFalse(overflow['ok'])
        self.assertLessEqual(len(original(overflow)), 1024)

    def test_unicode_binary_nonfinite_and_named_values_remain_exact(self):
        """Native bindings and explicit JSON tags preserve compact SQLite values."""
        text = "O'Reilly; Привет 世界\nnext"
        blob = {'$blob_base64': base64.b64encode(b'\x00\xffbinary').decode('ascii')}
        result = self.execute('SELECT :text AS same,:bytes AS same,1e999 AS infinity', params={'text': text, 'bytes': blob})
        self.assertEqual(result['results'][0]['columns'], ['same', 'same', 'infinity'])
        self.assertEqual(result['results'][0]['rows'], [[text, blob, {'$float': 'Infinity'}]])

    def test_deadline_rolls_back_only_open_transaction(self):
        """Timeout cleanup preserves earlier autocommits while reverting an unfinished transaction."""
        self.assertTrue(self.execute('CREATE TABLE timed(value)')['ok'])
        infinite = 'WITH RECURSIVE n(x) AS (VALUES(1) UNION ALL SELECT x+1 FROM n) SELECT sum(x) FROM n'
        result = self.execute([{'sql': 'INSERT INTO timed VALUES(1)'}, {'sql': 'BEGIN'},
                               {'sql': 'INSERT INTO timed VALUES(2)'}, {'sql': infinite}], timeout_ms=10)
        self.assertFalse(result['ok'])
        self.assertEqual(result['error']['kind'], 'timeout')
        self.assertTrue(result['transaction_rolled_back'])
        self.assertTrue(result['autocommit_effects_possible'])
        self.assertEqual(self.rows('SELECT * FROM timed'), [[1]])

    def test_concurrent_native_writers_do_not_lose_updates(self):
        """SQLite locking serializes native autocommit writes across independent connections."""
        self.assertTrue(self.execute('CREATE TABLE value(number)')['ok'])
        def writer(number):
            """Own the SQLite connection within its worker thread."""
            executor = runtime.Executor(self.database)
            try:
                return executor.execute_sql(sql='INSERT INTO value VALUES(?)', params=[number])
            finally:
                executor.close()
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
            result = list(pool.map(writer, range(18)))
        self.assertTrue(all(item['ok'] for item in result), result)
        self.assertEqual(self.rows('SELECT count(*),sum(number) FROM value'), [[18, sum(range(18))]])

    def test_executor_remains_schema_agnostic_for_legacy_databases(self):
        """SQL transport does not enforce the separately governed knowledge schema."""
        with contextlib.closing(sqlite3.connect(self.database)) as direct:
            direct.executescript((REPOSITORY / 'tests/fixtures/schema-v2.sql').read_text(encoding='utf-8'))
            direct.execute("INSERT INTO scopes VALUES('scope','main','host','head','snapshot','now')")
            direct.execute("INSERT INTO records VALUES('scope','old','finding','Old title','Summary','confirmed','current',NULL,NULL,NULL,NULL,'now')")
            direct.commit()
        self.assertEqual(self.rows("SELECT title FROM records WHERE id='old'"), [['Old title']])
        result = self.execute([{'sql': 'ALTER TABLE records ADD COLUMN extension TEXT'}, {'sql': "UPDATE records SET extension='new' WHERE id='old'"},
                               {'sql': 'PRAGMA user_version=999'}])
        self.assertTrue(result['ok'], result)
        self.assertEqual(self.rows("SELECT title,extension FROM records WHERE id='old'"), [['Old title', 'new']])

    def test_bound_symlink_retarget_refuses_different_database(self):
        """No call can silently switch the executor's persistent database."""
        second_path = self.area / 'other.sqlite3'
        second = runtime.Executor(second_path, create=True)
        self.addCleanup(second.close)
        link = self.area / 'selected.sqlite3'
        try:
            link.symlink_to(self.database)
        except OSError as exc:
            self.skipTest(str(exc))
        selected = runtime.Executor(link)
        self.addCleanup(selected.close)
        link.unlink()
        link.symlink_to(second_path)
        self.assertFalse(selected.execute_sql(sql='CREATE TABLE escaped(value)')['ok'])
        self.assertEqual(second.execute_sql(sql="SELECT name FROM sqlite_master WHERE type='table'")['results'][0]['rows'], [])

    def test_utf8_sql_file_and_strict_json_boundaries(self):
        """Single SQL files preserve UTF-8; malformed JSON cannot execute writes."""
        sql_file = self.area / 'query.sql'
        sql_file.write_text("SELECT 'Привет; 世界' AS greeting", encoding='utf-8')
        result = self.cli('--sql-file', str(sql_file))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['results'][0]['rows'], [['Привет; 世界']])
        for constant in ('NaN', 'Infinity', '-Infinity'):
            cli = self.cli('--input', '-', input_bytes=('{"sql":"CREATE TABLE forbidden(value)","unused":' + constant + '}').encode())
            self.assertNotEqual(cli.returncode, 0)
            self.assertIn('Nonstandard JSON', json.loads(cli.stdout)['error']['message'])
        self.assertTrue(json.loads(self.cli('--sql', 'SELECT 1').stdout)['ok'])
        self.assertEqual(self.rows("SELECT name FROM sqlite_master WHERE name='forbidden'"), [])

    def test_cli_malformed_and_oversized_inputs_have_no_write_side_effects(self):
        """Invalid JSON and oversized requests fail before SQL executes."""
        for raw in (b'not JSON', b'{"sql":"CREATE TABLE forbidden(value)","params":[',
                    runtime.json_bytes({'sql': 'CREATE TABLE forbidden(value)',
                                        'params': ['x' * runtime.MAX_INPUT_BYTES]})):
            cli = self.cli('--input', '-', input_bytes=raw)
            self.assertNotEqual(cli.returncode, 0)
            self.assertFalse(json.loads(cli.stdout)['ok'])
        missing = self.cli('--sql', 'SELECT * FROM missing')
        self.assertFalse(json.loads(missing.stdout)['ok'])
        self.assertTrue(json.loads(self.cli('--sql', 'SELECT 1').stdout)['ok'])
        self.assertEqual(self.rows("SELECT name FROM sqlite_master WHERE name='forbidden'"), [])

    def test_deep_json_rejection_recovers_cli_and_python_without_writes(self):
        """A small but excessively nested input fails before SQL."""
        self.assertTrue(self.execute('CREATE TABLE protected(value)')['ok'])
        nested_json = ('[' * 10000) + '0' + (']' * 10000)
        raw = ('{"sql":"INSERT INTO protected VALUES(1)","params":' + nested_json + '}').encode()
        self.assertLess(len(raw), runtime.MAX_INPUT_BYTES)
        cli = self.cli('--input', '-', input_bytes=raw)
        self.assertNotEqual(cli.returncode, 0)
        self.assertIn('nesting', json.loads(cli.stdout)['error']['message'])
        nested = 0
        for _ in range(10000):
            nested = [nested]
        direct = self.execute('INSERT INTO protected VALUES(1)', params=nested)
        self.assertFalse(direct['ok'])
        self.assertEqual(direct['error']['kind'], 'request')
        self.assertIn('nesting', direct['error']['message'])
        self.assertEqual(self.rows('SELECT count(*) FROM protected'), [[0]])

    def test_unencodable_unicode_and_invalid_utf8_fail_before_dispatch_and_recover(self):
        """Lone surrogates fail while valid supplementary characters still round-trip."""
        self.assertTrue(self.execute('CREATE TABLE protected(value)')['ok'])
        invalid_utf8 = b'{"sql":"INSERT INTO protected VALUES(?)","params":["\xff"]}'
        invalid = self.cli('--input', '-', input_bytes=invalid_utf8)
        self.assertNotEqual(invalid.returncode, 0)
        self.assertFalse(json.loads(invalid.stdout)['ok'])
        pair_parameter = b'{"sql":"SELECT ?","params":["\\ud83d\\ude00"]}'
        pair = self.cli('--input', '-', input_bytes=pair_parameter)
        self.assertEqual(pair.returncode, 0, pair.stderr)
        self.assertEqual(json.loads(pair.stdout)['results'][0]['rows'], [['\U0001f600']])
        cli = self.cli('--input', '-', input_bytes=b'{"sql":"INSERT INTO protected VALUES(1)","unused":"\\ud800"}')
        self.assertNotEqual(cli.returncode, 0)
        self.assertIn('Unicode', json.loads(cli.stdout)['error']['message'])
        direct = self.execute('INSERT INTO protected VALUES(?)', params=['\ud800'])
        self.assertFalse(direct['ok'])
        self.assertEqual(direct['error']['kind'], 'request')
        self.assertEqual(self.rows('SELECT count(*) FROM protected'), [[0]])

    def test_self_keyword_uses_shared_validation_without_writes(self):
        """A JSON argument cannot collide with the bound method receiver."""
        self.assertTrue(self.execute('CREATE TABLE protected(value)')['ok'])
        arguments = {'sql': 'INSERT INTO protected VALUES(1)', 'self': None}
        direct = self.executor.execute_sql(**arguments)
        self.assertFalse(direct['ok'])
        self.assertIn('self', direct['error']['message'])
        cli = self.cli('--input', '-', input_bytes=runtime.json_bytes(arguments))
        self.assertEqual(json.loads(cli.stdout), direct)
        self.assertEqual(self.rows('SELECT count(*) FROM protected'), [[0]])


if __name__ == '__main__':
    unittest.main()
