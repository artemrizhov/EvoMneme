"""Outcome controls over a hand-understood, executable synthetic job system.

Run directly to print measured lookup/command counts and returned UTF-8 bytes.
Counts describe these fixed tasks, not an efficiency improvement or SQL counts.
No host receipt or knowledge database is opened: discovery is bound to the fixture.
"""
from contextlib import closing, redirect_stderr, redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from evomneme_cli import main
from evomneme_connection import Connection


SOURCE_PATH = 'src/jobs.py'
SOURCE = '''class Cancelled(Exception):
    pass

def cancel(job):
    job['cancelled'] = True

def register_cancel(callbacks, job):
    callbacks.append(lambda: cancel(job))

def report_cancel(error, reports):
    reports.append(type(error).__name__)

def run(job, write, reports):
    try:
        if job.get('cancelled'):
            raise Cancelled('Отменено')
        write(job)
    except Cancelled as error:
        report_cancel(error, reports)

def commit_job(db, job):
    with db:
        db.execute('INSERT INTO jobs VALUES (?)', (job['id'],))
        if job.get('fail'):
            raise RuntimeError('write failed')

def submit(db, job, reports):
    run(job, lambda value: commit_job(db, value), reports)
'''

METRICS = {}


class JobControlFixture:
    """Explicit semantic facts, not a parser or an automatically inferred graph."""

    def __init__(self, project):
        self.project = project
        self.path = project / 'synthetic.sqlite3'
        self.source = project / SOURCE_PATH
        self.source.parent.mkdir()
        self.source.write_text(SOURCE, encoding='utf-8')
        self.digest = hashlib.sha256(self.source.read_bytes()).hexdigest()
        self.code = {}
        exec(compile(SOURCE, SOURCE_PATH, 'exec'), self.code)
        self.connection = Connection(self.path, project, project, 'main', 'project',
                                     'posix', 'synthetic-retrieval', str(project), 'fixture-v1')
        with closing(sqlite3.connect(self.path)) as db, db:
            db.executescript((ROOT / 'schema.sql').read_text(encoding='utf-8'))
            db.execute("INSERT INTO metadata VALUES('project_identity','synthetic-retrieval')")
            db.execute('INSERT INTO scopes VALUES(?,?,?,?,?,?)',
                       ('main', 'fixture', str(project), 'fixture-v1', 'fixture', 'now'))
            self.node(db, 'project', 'Synthetic job processing',
                      'Cancellation, error reporting and atomic job persistence.', None, kind='project')
            self.node(db, 'jobs-file', 'Job source', 'Owns the job processing functions.', 1, kind='file')
            definitions = {
                'Cancelled': 'Signals cancellation before persistence.',
                'cancel': 'Sets the cancellation flag on the captured job.',
                'register_cancel': 'Registers a deferred callback capturing the job.',
                'report_cancel': 'Records the cancellation exception type.',
                'run': 'Runs the injected writer; catches Cancelled and reports it.',
                'commit_job': 'Inserts a job inside a SQLite transaction; errors roll back.',
                'submit': 'Binds commit_job as the writer used by run.',
            }
            for name, summary in definitions.items():
                prefix = 'class ' if name == 'Cancelled' else 'def '
                self.node(db, name, name, summary, self.line(prefix + name + '('),
                          kind='class' if name == 'Cancelled' else 'function')
            self.node(db, 'atomic', 'Atomic persistence invariant',
                      'A failed commit_job leaves no inserted job.', self.line('with db:'))
            # Historical claims remain useful maintenance targets, never current answers.
            self.node(db, 'old-handler', 'Legacy cancellation handler',
                      'Superseded handler claim; must not be used as the current route.',
                      90, validity='superseded')
            self.edge(db, 'owns-file', 'project', 'jobs-file', 'contains', 'Owns source.', 1)
            for name in definitions:
                self.edge(db, 'owns-' + name, 'jobs-file', name, 'contains',
                          'Immediate source ownership.', self.line(('class ' if name == 'Cancelled' else 'def ') + name + '('))
            self.edge(db, 'callback', 'register_cancel', 'cancel', 'registers_callback',
                      'Deferred lambda calls cancel with the captured job.', self.line('callbacks.append'))
            self.edge(db, 'raises', 'run', 'Cancelled', 'raises',
                      'A cancelled job raises Cancelled before invoking its writer.', self.line('raise Cancelled'))
            self.edge(db, 'handler', 'run', 'report_cancel', 'handles_error',
                      'The Cancelled handler calls report_cancel.', self.line('        report_cancel(error, reports)'))
            self.edge(db, 'dispatch', 'submit', 'run', 'calls',
                      'Starts the runner with a persistence callback.', self.line('run(job, lambda'))
            self.edge(db, 'writer', 'submit', 'commit_job', 'binds_callback',
                      'The injected writer calls commit_job with this database.', self.line('run(job, lambda'))
            self.edge(db, 'transaction', 'commit_job', 'atomic', 'guarantees',
                      'SQLite context rolls back the insert when RuntimeError escapes.', self.line('with db:'))
            self.edge(db, 'retired-handler', 'run', 'old-handler', 'handles_error',
                      'Historical route; no longer supported by source.', 91, validity='stale')

    @staticmethod
    def line(fragment, source=SOURCE):
        matches = [number for number, text in enumerate(source.splitlines(), 1) if fragment in text]
        if len(matches) != 1:
            raise AssertionError('Expected unique source anchor: ' + fragment)
        return matches[0]

    def node(self, db, id_, title, summary, line, kind='architecture', validity='current'):
        db.execute('''INSERT INTO nodes(scope_id,id,kind,title,summary,confidence,validity,
            source_path,source_hash,line_start,updated_at) VALUES('main',?,?,?,?, 'confirmed',?,?,?,?, 'now')''',
                   (id_, kind, title, summary, validity, SOURCE_PATH if line else None,
                    self.digest if line else None, line))

    def edge(self, db, id_, source, target, kind, summary, line, validity='current'):
        db.execute('''INSERT INTO edges(scope_id,id,source_id,target_id,kind,summary,confidence,
            validity,source_path,source_hash,line_start,updated_at)
            VALUES('main',?,?,?,?,?,'confirmed',?,?,?,?,'now')''',
                   (id_, source, target, kind, summary, validity, SOURCE_PATH, self.digest, line))
        db.execute('''INSERT INTO evidence(scope_id,id,edge_id,description,source_path,source_hash,
            validity,updated_at) VALUES('main',?,?,?,?,?,?,'now')''',
                   ('proof-' + id_, id_, summary + ' See ' + SOURCE_PATH + ':' + str(line) + '.',
                    SOURCE_PATH, self.digest, validity))


class RetrievalControls(unittest.TestCase):
    def setUp(self):
        area = ROOT / '.evomneme-tests'
        area.mkdir(exist_ok=True)
        temporary = tempfile.TemporaryDirectory(dir=area)
        self.addCleanup(temporary.cleanup)
        self.fixture = JobControlFixture(Path(temporary.name).resolve())
        self.outputs = []
        self.lookup_count = 0
        self.command_count = 0

    def lookup(self, *tokens):
        """One actual bound CLI invocation; wrappers/newlines count toward bytes."""
        self.lookup_count += 1
        self.command_count += 1 + tokens.count('--next')
        stdout, stderr = io.StringIO(), io.StringIO()
        with mock.patch('evomneme_connection.discover', return_value=self.fixture.connection), \
                redirect_stdout(stdout), redirect_stderr(stderr):
            result = main(list(tokens))
        self.assertEqual((result, stderr.getvalue()), (0, ''))
        output = stdout.getvalue()
        self.outputs.append(output)
        return output

    def record_metrics(self, task, expected_lookups, expected_commands):
        self.assertEqual((self.lookup_count, self.command_count), (expected_lookups, expected_commands))
        size = sum(len(output.encode('utf-8')) for output in self.outputs)
        self.assertGreater(size, 0)
        METRICS[task] = {'lookup_invocations': self.lookup_count,
                         'command_segments': self.command_count, 'returned_utf8_bytes': size}

    def assert_anchor(self, output, fragment):
        self.assertIn('source_path: ' + SOURCE_PATH, output)
        self.assertIn('source_hash: ' + self.fixture.digest, output)
        self.assertIn('line_start: ' + str(self.fixture.line(fragment)), output)
        self.assertIn('evidence:', output)

    def test_error_handler_answer_reaches_exception_and_reporter(self):
        # Ground truth: cancellation prevents the write and reaches the typed reporter.
        writes, reports = [], []
        self.fixture.code['run']({'cancelled': True}, writes.append, reports)
        self.assertEqual((writes, reports), ([], ['Cancelled']))
        overview = self.lookup('nodes', 'root', '--next', 'links', 'root')
        self.assertIn('Synthetic job processing', overview)
        ownership = self.lookup('links', 'Job source')
        self.assertIn('Runs the injected writer', ownership)
        route = self.lookup('links', 'run')
        self.assertIn('kind: raises', route)
        self.assertIn('title: Cancelled', route)
        self.assertIn('kind: handles_error', route)
        self.assertIn('title: report_cancel', route)
        self.assertNotIn('Legacy cancellation handler', route)
        answer = self.lookup('links', 'run', 'report_cancel', '--next', 'nodes', 'report_cancel')
        self.assertIn('The Cancelled handler calls report_cancel.', answer)
        self.assert_anchor(answer, '        report_cancel(error, reports)')
        self.record_metrics('error_handler', 4, 6)

    def test_cancellation_answer_preserves_deferred_callback_wiring(self):
        callbacks, reports = [], []
        job = {'id': 'one'}
        self.fixture.code['register_cancel'](callbacks, job)
        self.assertNotIn('cancelled', job)
        callbacks[0]()
        self.fixture.code['run'](job, lambda value: self.fail('cancelled job was written'), reports)
        self.assertEqual(reports, ['Cancelled'])
        route = self.lookup('links', 'register_cancel')
        self.assertIn('kind: registers_callback', route)
        self.assertIn('title: cancel', route)
        self.assertIn('captured job', route)
        answer = self.lookup('links', 'register_cancel', 'cancel', '--next', 'nodes', 'cancel')
        self.assert_anchor(answer, 'callbacks.append')
        self.assertIn('Sets the cancellation flag', answer)
        self.record_metrics('cancellation_callback', 2, 3)

    def test_transaction_answer_matches_observed_rollback(self):
        with closing(sqlite3.connect(':memory:')) as db:
            db.execute('CREATE TABLE jobs(id TEXT)')
            with self.assertRaisesRegex(RuntimeError, 'write failed'):
                self.fixture.code['submit'](db, {'id': 'bad', 'fail': True}, [])
            self.assertEqual(db.execute('SELECT * FROM jobs').fetchall(), [])
            self.fixture.code['submit'](db, {'id': 'good'}, [])
            self.assertEqual(db.execute('SELECT * FROM jobs').fetchall(), [('good',)])
        wiring = self.lookup('links', 'submit')
        self.assertIn('kind: binds_callback', wiring)
        self.assertIn('title: commit_job', wiring)
        answer = self.lookup('links', 'commit_job', 'Atomic persistence invariant',
                             '--next', 'nodes', 'Atomic persistence invariant')
        self.assertIn('A failed commit_job leaves no inserted job.', answer)
        self.assertIn('kind: guarantees', answer)
        self.assert_anchor(answer, 'with db:')
        self.record_metrics('transaction_rollback', 2, 3)

    def test_changed_file_references_preserve_history_and_reanchor_all_rows(self):
        before = self.lookup('references', SOURCE_PATH)
        self.assertIn('id: old-handler', before)
        self.assertIn('validity: superseded', before)
        self.assertIn('id: retired-handler', before)
        self.assertIn('validity: stale', before)
        self.assertIn('id: proof-retired-handler', before)
        # This source edit shifts every existing locator, including untouched functions.
        changed = '# Added source header\n' + SOURCE
        self.fixture.source.write_text(changed, encoding='utf-8')
        digest = hashlib.sha256(self.fixture.source.read_bytes()).hexdigest()
        commands = []
        # The fixed, fully understood fixture permits checking each selected anchor.
        with closing(sqlite3.connect(self.fixture.path)) as db:
            rows = {table: db.execute('SELECT id,validity,line_start FROM ' + table +
                                      ' WHERE source_path=?', (SOURCE_PATH,)).fetchall()
                    for table in ('nodes', 'edges')}
            proofs = db.execute('SELECT id,description,validity FROM evidence WHERE source_path=?',
                                (SOURCE_PATH,)).fetchall()
        for table, records in rows.items():
            for id_, validity, old_line in records:
                command = ['update', 'node' if table == 'nodes' else 'edge', id_]
                if validity == 'current':
                    # Compare the actual old/new text, not just blindly adding an offset.
                    old_text = SOURCE.splitlines()[old_line - 1]
                    self.assertEqual(changed.splitlines()[old_line], old_text)
                    command += ['--line_start', str(old_line + 1), '--source_hash', digest]
                else:
                    command += ['--clear', 'line_start', '--validity', validity]
                commands.append(command)
        for id_, description, validity in proofs:
            command = ['update', 'evidence', id_]
            if validity == 'current':
                old_line = int(description.rsplit(':', 1)[1].rstrip('.'))
                self.assertEqual(changed.splitlines()[old_line], SOURCE.splitlines()[old_line - 1])
                command += ['--description', description.rsplit(':', 1)[0] + ':' + str(old_line + 1) + '.',
                            '--source_hash', digest]
            else:
                command += ['--description', 'Historical route unsupported by current source; locator cleared.']
            commands.append(command)
        tokens = []
        for command in commands:
            if tokens:
                tokens.append('--next')
            tokens.extend(command)
        # Mutation is exercised but excluded from retrieval cost measurements.
        stdout, stderr = io.StringIO(), io.StringIO()
        with mock.patch('evomneme_connection.discover', return_value=self.fixture.connection), \
                redirect_stdout(stdout), redirect_stderr(stderr):
            result = main(tokens)
        self.assertEqual((result, stderr.getvalue()), (0, ''))
        after = self.lookup('references', SOURCE_PATH)
        self.assertIn('source_hash: ' + digest, after)
        for id_ in ('old-handler', 'retired-handler', 'proof-retired-handler'):
            block = next(block for block in after.split('\n\n') if '\n  id: ' + id_ + '\n' in block)
            if id_ != 'proof-retired-handler':
                self.assertIn('line_start: None', block)
            else:
                self.assertNotIn('src/jobs.py:91', block)
            self.assertTrue('validity: stale' in block or 'validity: superseded' in block)
        with closing(sqlite3.connect(self.fixture.path)) as db:
            for table, records in rows.items():
                for id_, validity, old_line in records:
                    line, saved_hash = db.execute('SELECT line_start,source_hash FROM ' + table +
                                                  ' WHERE id=?', (id_,)).fetchone()
                    self.assertEqual(line, old_line + 1 if validity == 'current' else None)
                    if validity == 'current':
                        self.assertEqual(saved_hash, digest)
            for id_, description, validity in proofs:
                saved_description, saved_hash = db.execute(
                    'SELECT description,source_hash FROM evidence WHERE id=?', (id_,)).fetchone()
                if validity == 'current':
                    old_line = int(description.rsplit(':', 1)[1].rstrip('.'))
                    self.assertEqual(saved_description,
                                     description.rsplit(':', 1)[0] + ':' + str(old_line + 1) + '.')
                    self.assertEqual(saved_hash, digest)
                else:
                    self.assertEqual(saved_hash, self.fixture.digest)
        current = self.lookup('links', 'run', 'report_cancel')
        self.assertNotIn('Legacy cancellation handler', current)
        self.assertIn('line_start: ' + str(self.fixture.line('        report_cancel(error, reports)') + 1), current)
        self.record_metrics('changed_file_reconciliation', 3, 3)


if __name__ == '__main__':
    suite = unittest.main(exit=False)
    print(json.dumps({'retrieval_controls': METRICS}, sort_keys=True, indent=2))
    sys.exit(not suite.result.wasSuccessful())
