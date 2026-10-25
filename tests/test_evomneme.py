"""Isolated tests for the thin SQL executor and its CLI/MCP transports."""

import base64
import concurrent.futures
import contextlib
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest

REPOSITORY = Path(__file__).resolve().parent.parent
SCRIPT = REPOSITORY / 'scripts' / 'evomneme.py'
MCP_SCRIPT = REPOSITORY / 'scripts' / 'evomneme_mcp.py'
SPEC = importlib.util.spec_from_file_location('evomneme_sql_test', SCRIPT)
runtime = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runtime)
TEST_AREA = REPOSITORY / '.evomneme-tests'


class ExecutorTests(unittest.TestCase):
    """Use fixture databases only; never activate EvoMneme in the tool project."""

    def setUp(self):
        """Create one explicitly selected empty SQLite fixture."""
        TEST_AREA.mkdir(exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=TEST_AREA)
        self.addCleanup(self.temporary.cleanup)
        self.area = Path(self.temporary.name)
        self.database = self.area / 'host.sqlite3'
        self.executor = runtime.Executor(self.database, create=True)
        self.addCleanup(self.executor.close)

    def execute(self, sql, **options):
        """Run SQL through the shared public execution contract."""
        return self.executor.execute({'sql': sql, **options})

    def rows(self, sql):
        """Require success before inspecting a fixture query result."""
        result = self.execute(sql)
        self.assertTrue(result['ok'], result)
        return result['results'][-1]['rows']

    def cli(self, *arguments, input_bytes=None, database=None):
        """Run the actual CLI process with byte-exact UTF-8 input/output."""
        return subprocess.run([sys.executable, str(SCRIPT), '--database', str(database or self.database), *arguments],
                              input=input_bytes, capture_output=True)

    def wire(self, messages):
        """Run a real MCP subprocess through initialization, requests and clean EOF."""
        incoming = b''.join((message if isinstance(message, bytes) else runtime.json_bytes(message)) + b'\n' for message in messages)
        result = subprocess.run([sys.executable, str(MCP_SCRIPT), '--database', str(self.database)],
                                input=incoming, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr.decode('utf-8', 'replace'))
        self.assertEqual(result.stderr, b'')
        return [json.loads(line) for line in result.stdout.decode('utf-8').splitlines()]

    def handshake(self, version='2025-11-25'):
        """Provide the supported MCP initialize request and initialized notification."""
        return [
            {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {
                'protocolVersion': version, 'capabilities': {}, 'clientInfo': {'name': 'isolated-wire-test', 'version': '1'}}},
            {'jsonrpc': '2.0', 'method': 'notifications/initialized'},
        ]

    def test_explicit_empty_creation_and_existing_database_only(self):
        """No schema is bootstrapped and missing paths are never silently created."""
        self.assertEqual(self.rows("SELECT name FROM sqlite_master WHERE type='table'"), [])
        missing = self.area / 'missing.sqlite3'
        with self.assertRaises(FileNotFoundError):
            runtime.Executor(missing)
        self.assertFalse(missing.exists())
        with self.assertRaises(FileExistsError):
            runtime.Executor(self.database, create=True)
        with self.assertRaises(runtime.RequestError):
            runtime.Executor(Path('relative.sqlite3'))

    def test_arbitrary_schema_cte_joins_and_schema_evolution(self):
        """Let SQLite run arbitrary application tables and normal migration SQL."""
        result = self.execute("""
            CREATE TABLE team(id INTEGER PRIMARY KEY, name TEXT);
            CREATE TABLE person(name TEXT, team_id INTEGER REFERENCES team(id));
            INSERT INTO team VALUES(1,'Infrastructure');
            INSERT INTO person VALUES('Ada',1);
            WITH selected AS (SELECT * FROM person)
            SELECT selected.name,team.name FROM selected JOIN team ON team.id=selected.team_id;
            ALTER TABLE person ADD COLUMN active INTEGER DEFAULT 1;
            CREATE INDEX person_team ON person(team_id);
        """)
        self.assertTrue(result['ok'], result)
        self.assertEqual(result['results'][4]['rows'], [['Ada', 'Infrastructure']])
        self.assertEqual(self.rows('SELECT active FROM person'), [[1]])
        self.assertTrue(self.execute('DROP INDEX person_team')['ok'])

    def test_semicolons_comments_and_triggers_use_sqlite_framing(self):
        """Preserve SQL strings and trigger bodies rather than splitting on every semicolon."""
        result = self.execute("""
            -- A comment containing ; is not a statement boundary.
            CREATE TABLE events(text TEXT);
            CREATE TABLE audit(message TEXT);
            CREATE TRIGGER event_logged AFTER INSERT ON events BEGIN
              INSERT INTO audit VALUES('seen; event');
              INSERT INTO audit VALUES(NEW.text);
            END;
            INSERT INTO events VALUES('a; ''quoted'' value');
            SELECT message FROM audit ORDER BY rowid;
            -- trailing comment;
        """)
        self.assertTrue(result['ok'], result)
        self.assertEqual(result['results'][4]['rows'], [['seen; event'], ["a; 'quoted' value"]])

    def test_comment_and_empty_fragments_do_not_count_as_parameterized_statements(self):
        """Bind one actual statement despite leading/trailing comments and delimiters."""
        for sql in ('SELECT ?; -- trailing comment', 'SELECT ?; /* trailing ; comment */',
                    '; ; /* leading ; comment */ SELECT ?; ; -- tail\n;',
                    '-- initial ; comment\n SELECT ? /* inside */; ;'):
            with self.subTest(sql=sql):
                result = self.execute(sql, params=["quoted; ' 世界"])
                self.assertTrue(result['ok'], result)
                self.assertEqual(len(result['results']), 1)
                self.assertEqual(result['results'][0]['rows'], [["quoted; ' 世界"]])
        result = self.cli('--sql-file', '-', '--params', '[7]', input_bytes=b'SELECT ?; -- trailing comment')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['results'][0]['rows'], [[7]])

    def test_statement_indexes_ignore_comments_empty_fragments_and_trigger_delimiters(self):
        """Errors and results index only executable SQL statements, including full triggers."""
        result = self.execute('''
            ; /* initial */ ; CREATE TABLE event(value); -- comment;
            CREATE TRIGGER event_logged AFTER INSERT ON event BEGIN
              SELECT 'body; value'; /* body ; comment */ SELECT 2;
            END; ; /* trailing */ SELECT * FROM missing; -- final
        ''')
        self.assertFalse(result['ok'])
        self.assertEqual(result['error']['failed_statement_index'], 2)
        self.assertEqual(self.rows("SELECT name FROM sqlite_master WHERE name='event'"), [])

    def test_bound_quotes_unicode_named_parameters_and_duplicate_columns(self):
        """Bind user values directly, preserving Unicode and duplicate column labels."""
        value = "O'Reilly; Привет 世界\nnext line"
        self.assertTrue(self.execute('CREATE TABLE value(text TEXT)')['ok'])
        self.assertTrue(self.execute('INSERT INTO value VALUES(?)', params=[value])['ok'])
        self.assertEqual(self.rows('SELECT text FROM value'), [[value]])
        result = self.execute('SELECT :text AS same, :number AS same', params={'text': value, 'number': 3})
        self.assertEqual(result['results'][0]['columns'], ['same', 'same'])
        self.assertEqual(result['results'][0]['rows'], [[value, 3]])
        rejected = self.execute('SELECT ?; SELECT 2', params=[1])
        self.assertFalse(rejected['ok'])
        self.assertIn('exactly one', rejected['error']['message'])

    def test_batch_error_rolls_back_reads_writes_and_ddl(self):
        """A failing statement leaves no half-applied schema or earlier writes."""
        result = self.execute("CREATE TABLE half(value); INSERT INTO missing VALUES('private input')")
        self.assertFalse(result['ok'])
        self.assertFalse(result['committed'])
        self.assertEqual(result['error']['failed_statement_index'], 1)
        self.assertEqual(result['error']['sqlite_errorname'], 'SQLITE_ERROR')
        self.assertNotIn('private input', result['error']['message'])
        self.assertEqual(self.rows("SELECT name FROM sqlite_master WHERE name='half'"), [])
        self.assertTrue(self.execute('CREATE TABLE durable(value UNIQUE); INSERT INTO durable VALUES(1)')['ok'])
        result = self.execute('INSERT INTO durable VALUES(2); INSERT INTO durable VALUES(1)')
        self.assertFalse(result['ok'])
        self.assertEqual(self.rows('SELECT value FROM durable'), [[1]])

    def test_commit_failure_is_error_and_rolls_back(self):
        """A deferred foreign-key failure at COMMIT must never report success."""
        self.assertTrue(self.execute('CREATE TABLE parent(id PRIMARY KEY); CREATE TABLE child(id REFERENCES parent(id) DEFERRABLE INITIALLY DEFERRED)')['ok'])
        result = self.execute('INSERT INTO child VALUES(99)')
        self.assertFalse(result['ok'])
        self.assertFalse(result['committed'])
        self.assertEqual(result['error']['sqlite_errorname'], 'SQLITE_CONSTRAINT_FOREIGNKEY')
        self.assertEqual(self.rows('SELECT * FROM child'), [])

    def test_transaction_controls_and_cross_file_escapes_are_refused(self):
        """The caller cannot commit half a batch or access another database file."""
        external = self.area / 'external.sqlite3'
        for sql, params in (
            ('CREATE TABLE leaked(value); COMMIT', []),
            ('SAVEPOINT caller', []),
            ('ATTACH DATABASE ? AS other', [str(external)]),
            ("SELECT load_extension('unused')", []),
            ('VACUUM INTO ?', [str(external)]),
            ('PRAGMA foreign_keys=OFF', []),
        ):
            with self.subTest(sql=sql):
                result = self.execute(sql, params=params)
                self.assertFalse(result['ok'], result)
        self.assertFalse(external.exists())
        self.assertEqual(self.rows("SELECT name FROM sqlite_master WHERE name='leaked'"), [])

    def test_journal_mode_setter_is_refused_atomically_but_reads_are_allowed(self):
        """A request cannot disable the rollback journal that guarantees batch atomicity."""
        self.assertTrue(self.rows('PRAGMA journal_mode'))
        result = self.execute('CREATE TABLE not_committed(value); PRAGMA journal_mode=OFF')
        self.assertFalse(result['ok'])
        self.assertEqual(result['error']['failed_statement_index'], 1)
        self.assertIn('journal_mode', result['error']['message'])
        self.assertEqual(self.rows("SELECT name FROM sqlite_master WHERE name='not_committed'"), [])

    def test_sqlite_error_messages_obey_output_budget_with_explicit_truncation(self):
        """Large SQLite diagnostics fit the same budget without pretending to be complete."""
        result = self.execute('SELECT ' + ('private_identifier_' * 200), max_output_bytes=1024)
        self.assertFalse(result['ok'])
        self.assertTrue(result['error']['message_truncated'])
        self.assertLessEqual(len(runtime.json_bytes(result)), 1024)
        self.assertEqual(result['error']['failed_statement_index'], 0)

    def test_concurrent_writers_use_sqlite_locking_without_lost_updates(self):
        """Independent connections safely commit their own atomic batches."""
        self.assertTrue(self.execute('CREATE TABLE concurrent(value INTEGER)')['ok'])

        def writer(value):
            """Create and close each SQLite connection within its owning thread."""
            executor = runtime.Executor(self.database)
            try:
                return executor.execute({'sql': 'INSERT INTO concurrent VALUES(?)', 'params': [value]})
            finally:
                executor.close()

        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(writer, range(18)))
        self.assertTrue(all(result['ok'] for result in results), results)
        self.assertEqual(self.rows('SELECT count(*),sum(value) FROM concurrent'), [[18, sum(range(18))]])

    def test_busy_wait_respects_request_deadline(self):
        """A blocked write returns a bounded error rather than waiting indefinitely."""
        self.assertTrue(self.execute('CREATE TABLE locked(value)')['ok'])
        with contextlib.closing(sqlite3.connect(self.database, isolation_level=None)) as blocker:
            blocker.execute('BEGIN IMMEDIATE')
            start = time.monotonic()
            result = self.execute('INSERT INTO locked VALUES(1)', timeout_ms=40)
            elapsed = time.monotonic() - start
            blocker.execute('ROLLBACK')
        self.assertFalse(result['ok'])
        self.assertLess(elapsed, 1)
        self.assertEqual(self.rows('SELECT * FROM locked'), [])

    def test_output_rows_and_bytes_are_bounded_without_cell_truncation(self):
        """Omit complete suffix rows and keep SQLite values exactly as returned."""
        result = self.execute('WITH RECURSIVE n(x) AS (VALUES(1) UNION ALL SELECT x+1 FROM n WHERE x<20) SELECT x FROM n', max_rows=3)
        output = result['results'][0]
        self.assertEqual(output['rows'], [[1], [2], [3]])
        self.assertEqual(output['rows_omitted'], 17)
        self.assertTrue(result['output_truncated'])
        result = self.execute("SELECT printf('%02000d',1) AS payload", max_output_bytes=1024)
        self.assertTrue(result['ok'], result)
        self.assertEqual(result['results'][0]['rows'], [])
        self.assertEqual(result['results'][0]['rows_omitted'], 1)
        self.assertLessEqual(len(runtime.json_bytes(result)), 1024)
        value = '世界' * 200
        result = self.execute('SELECT ?', params=[value], max_output_bytes=4096)
        self.assertEqual(result['results'][0]['rows'], [[value]])

    def test_output_budget_includes_large_columns_and_many_resultsets(self):
        """Metadata overflow rolls back instead of returning an oversized response."""
        alias = 'column_' + ('x' * 2000)
        result = self.execute('CREATE TABLE half(value); SELECT 1 AS "' + alias + '"', max_output_bytes=1024)
        self.assertFalse(result['ok'])
        self.assertFalse(result['committed'])
        self.assertEqual(self.rows("SELECT name FROM sqlite_master WHERE name='half'"), [])
        result = self.execute(';'.join('SELECT 1 AS x' for _ in range(30)), max_output_bytes=1024)
        self.assertFalse(result['ok'])
        self.assertIn('metadata', result['error']['message'])

    def test_returning_truncation_drains_writes_before_commit(self):
        """A truncated RETURNING response still accurately commits every inserted row."""
        self.assertTrue(self.execute('CREATE TABLE returned(value)')['ok'])
        result = self.execute('INSERT INTO returned VALUES(1),(2),(3),(4),(5) RETURNING value', max_rows=1)
        self.assertTrue(result['ok'], result)
        self.assertTrue(result['committed'])
        self.assertEqual(result['results'][0]['rows'], [[1]])
        self.assertEqual(result['results'][0]['rows_omitted'], 4)
        self.assertEqual(result['results'][0]['affected_rows'], 5)
        self.assertEqual(self.rows('SELECT count(*) FROM returned'), [[5]])

    def test_binary_and_nonfinite_values_have_explicit_json_tags(self):
        """BLOB bytes round-trip without text decoding or invisible coercion."""
        value = b'\x00\xffbinary'
        tag = {'$blob_base64': base64.b64encode(value).decode('ascii')}
        result = self.execute('SELECT ? AS bytes,1e999 AS positive,-1e999 AS negative', params=[tag])
        self.assertEqual(result['results'][0]['rows'], [[tag, {'$float': 'Infinity'}, {'$float': '-Infinity'}]])

    def test_timeout_rolls_back_earlier_writes(self):
        """A VM budget interruption rolls back the entire script."""
        self.assertTrue(self.execute('CREATE TABLE timed(value)')['ok'])
        result = self.execute('INSERT INTO timed VALUES(1); WITH RECURSIVE n(x) AS (VALUES(1) UNION ALL SELECT x+1 FROM n) SELECT sum(x) FROM n', timeout_ms=10)
        self.assertFalse(result['ok'])
        self.assertEqual(result['error']['kind'], 'timeout')
        self.assertEqual(result['error']['failed_statement_index'], 1)
        self.assertEqual(self.rows('SELECT * FROM timed'), [])

    def test_databases_are_explicit_and_separate(self):
        """Two projects cannot share data unless the agent deliberately selects one file."""
        second_path = self.area / 'other.sqlite3'
        second = runtime.Executor(second_path, create=True)
        self.addCleanup(second.close)
        self.assertTrue(self.execute('CREATE TABLE private(value); INSERT INTO private VALUES(7)')['ok'])
        self.assertEqual(second.execute({'sql': "SELECT name FROM sqlite_master WHERE type='table'"})['results'][0]['rows'], [])
        self.assertFalse(second.execute({'sql': 'SELECT * FROM private'})['ok'])
        self.assertFalse((REPOSITORY / '.evomneme').exists())

    def test_bound_symlink_retarget_is_rejected_without_touching_second_database(self):
        """One executor never follows a changed symlink into a different database."""
        second_path = self.area / 'second.sqlite3'
        other = runtime.Executor(second_path, create=True)
        self.addCleanup(other.close)
        link = self.area / 'selected.sqlite3'
        try:
            link.symlink_to(self.database)
        except OSError as exc:
            self.skipTest('Symlink creation unavailable: ' + str(exc))
        selected = runtime.Executor(link)
        self.addCleanup(selected.close)
        link.unlink()
        link.symlink_to(second_path)
        result = selected.execute({'sql': 'CREATE TABLE escaped(value)'})
        self.assertFalse(result['ok'])
        self.assertIn('retargeted', result['error']['message'])
        self.assertEqual(other.execute({'sql': "SELECT name FROM sqlite_master WHERE type='table'"})['results'][0]['rows'], [])

    def test_existing_v2_store_and_unknown_user_version_remain_agent_owned(self):
        """Read/write old v2 data without migration and permit arbitrary future version SQL."""
        script = (REPOSITORY / 'schema.sql').read_text(encoding='utf-8')
        self.assertTrue(self.execute(script)['ok'])
        result = self.execute("""
            INSERT INTO scopes VALUES('scope','main','host','head','snapshot','now');
            INSERT INTO records VALUES('scope','old','finding','Old title','Preserved summary','confirmed','current',NULL,NULL,NULL,NULL,'now');
            SELECT title,summary FROM records WHERE id='old';
        """)
        self.assertTrue(result['ok'], result)
        self.assertEqual(result['results'][-1]['rows'], [['Old title', 'Preserved summary']])
        self.assertTrue(self.execute("ALTER TABLE records ADD COLUMN agent_extension TEXT; UPDATE records SET agent_extension='new' WHERE id='old'; PRAGMA user_version=999")['ok'])
        self.assertEqual(self.rows('PRAGMA user_version'), [[999]])
        self.assertEqual(self.rows("SELECT title,agent_extension FROM records WHERE id='old'"), [['Old title', 'new']])

    def test_cli_sql_file_stdin_and_json_input_preserve_utf8(self):
        """Avoid nested shell quoting with UTF-8 SQL files and exact JSON parameters."""
        sql_file = self.area / 'query.sql'
        sql_file.write_text("SELECT 'Привет; 世界' AS greeting", encoding='utf-8')
        result = self.cli('--sql-file', str(sql_file))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['results'][0]['rows'], [['Привет; 世界']])
        result = self.cli('--sql-file', '-', input_bytes=b"SELECT 'stdin; SQL'")
        self.assertEqual(json.loads(result.stdout)['results'][0]['rows'], [['stdin; SQL']])
        arguments = {'sql': 'SELECT ? AS quoted', 'params': ["O'Reilly 世界"]}
        result = self.cli('--input', '-', input_bytes=runtime.json_bytes(arguments))
        self.assertEqual(json.loads(result.stdout), self.executor.execute(arguments))

    def test_mcp_wire_negotiation_list_call_and_sql_error(self):
        """Actual wire requests share exact executor output and structured SQL errors."""
        arguments = {'sql': 'SELECT ? AS greeting', 'params': ['世界']}
        messages = self.handshake() + [
            {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'},
            {'jsonrpc': '2.0', 'id': 3, 'method': 'tools/call', 'params': {'name': 'execute_sql', 'arguments': arguments}},
            {'jsonrpc': '2.0', 'id': 4, 'method': 'tools/call', 'params': {'name': 'execute_sql', 'arguments': {'sql': 'SELECT * FROM missing'}}},
            {'jsonrpc': '2.0', 'id': 5, 'method': 'ping'},
        ]
        responses = self.wire(messages)
        self.assertEqual(responses[0]['result']['protocolVersion'], '2025-11-25')
        self.assertEqual([tool['name'] for tool in responses[1]['result']['tools']], ['execute_sql'])
        output = responses[2]['result']
        self.assertEqual(output['structuredContent'], self.executor.execute(arguments))
        self.assertEqual(json.loads(output['content'][0]['text']), output['structuredContent'])
        self.assertFalse(output['isError'])
        self.assertTrue(responses[3]['result']['isError'])
        self.assertEqual(responses[3]['result']['structuredContent']['error']['sqlite_errorname'], 'SQLITE_ERROR')
        self.assertEqual(responses[4]['result'], {})

    def test_mcp_malformed_requests_and_notifications_have_no_side_effects(self):
        """No tool notification, wrong protocol, unknown method or premature call executes SQL."""
        write = {'name': 'execute_sql', 'arguments': {'sql': 'CREATE TABLE forbidden(value)'}}
        responses = self.wire([
            b'not JSON',
            {'jsonrpc': '2.0', 'id': 10, 'method': 'tools/call', 'params': write},
            *self.handshake(),
            {'jsonrpc': '2.0', 'method': 'tools/call', 'params': write},
            {'jsonrpc': '2.0', 'id': 11, 'method': 'tools/call', 'params': {'name': 'unknown', 'arguments': write['arguments']}},
            {'jsonrpc': '1.0', 'id': 12, 'method': 'tools/call', 'params': write},
            {'jsonrpc': '2.0', 'id': 13, 'method': 'unknown'},
            {'jsonrpc': '2.0', 'id': 14, 'method': 'tools/call', 'params': {'name': 'execute_sql', 'arguments': {'sql': 'CREATE TABLE forbidden(value)', 'database': 'other'}}},
        ])
        self.assertEqual(responses[0]['error']['code'], -32700)
        self.assertEqual(responses[1]['error']['code'], -32000)
        self.assertEqual(responses[3]['error']['code'], -32602)
        self.assertEqual(responses[4]['error']['code'], -32600)
        self.assertEqual(responses[5]['error']['code'], -32601)
        self.assertTrue(responses[6]['result']['isError'])
        self.assertEqual(self.rows("SELECT name FROM sqlite_master WHERE name='forbidden'"), [])

    def test_nonstandard_json_constants_are_rejected_before_cli_or_mcp_side_effects(self):
        """Invalid NaN/Infinity JSON never executes SQL and later MCP frames still work."""
        invalid = []
        for constant in ('NaN', 'Infinity', '-Infinity'):
            invalid.append(('{"jsonrpc":"2.0","id":2,"method":"tools/call","params":'
                            '{"name":"execute_sql","arguments":{"sql":"CREATE TABLE forbidden(value)"}},'
                            '"unused":' + constant + '}').encode('utf-8'))
            result = self.cli('--input', '-', input_bytes=(
                '{"sql":"CREATE TABLE forbidden(value)","unused":' + constant + '}').encode('utf-8'))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('Nonstandard JSON', json.loads(result.stdout)['error']['message'])
            result = self.cli('--sql', 'SELECT ?', '--params', '[' + constant + ']')
            self.assertNotEqual(result.returncode, 0)
        responses = self.wire(self.handshake() + invalid + [
            {'jsonrpc': '2.0', 'id': 9, 'method': 'tools/call', 'params': {
                'name': 'execute_sql', 'arguments': {'sql': 'SELECT 1 AS still_serving'}}}])
        self.assertEqual([response['error']['code'] for response in responses[1:4]], [-32700] * 3)
        self.assertEqual(responses[4]['result']['structuredContent']['results'][0]['rows'], [[1]])
        self.assertEqual(self.rows("SELECT name FROM sqlite_master WHERE name='forbidden'"), [])

    def test_mcp_bounded_input_recovers_and_negotiates_supported_versions(self):
        """Oversized wire messages fail cleanly without corrupting the next frame."""
        responses = self.wire([b'x' * (runtime.MAX_INPUT_BYTES + 1), *self.handshake('2025-06-18'),
                               {'jsonrpc': '2.0', 'id': 9, 'method': 'ping'}])
        self.assertEqual(responses[0]['error']['code'], -32600)
        self.assertEqual(responses[1]['result']['protocolVersion'], '2025-06-18')
        self.assertEqual(responses[2]['result'], {})
        negotiated = self.wire(self.handshake('unknown-version'))
        self.assertEqual(negotiated[0]['result']['protocolVersion'], '2025-11-25')


if __name__ == '__main__':
    unittest.main()
