"""Automatic completed-call history for bound, read-only graph access."""
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import sys
import time
import uuid

from evomneme_connection import validate_binding
from evomneme_context import ReadContext
from evomneme_journal import CALLS, ident, install, status
from evomneme_trace import build_event
from evomneme_write_options import CONTEXT_FIELDS, validate_context


class HistoryConnection(sqlite3.Connection):
    """One short deadline shared by lock waits and journal installation SQL."""
    def __init__(self, *args, **kwargs):
        self.deadline = time.monotonic() + 1.0
        super().__init__(*args, **kwargs)
        self.set_progress_handler(lambda: int(time.monotonic() >= self.deadline), 1000)

    def check_time(self):
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError('Activity history timed out; read result retained')
        super().execute('PRAGMA busy_timeout=' + str(max(1, int(remaining * 1000))))

    def execute(self, *args, **kwargs):
        self.check_time()
        return super().execute(*args, **kwargs)

    def executemany(self, *args, **kwargs):
        self.check_time()
        return super().executemany(*args, **kwargs)


def configure(parser):
    for key in CONTEXT_FIELDS:
        parser.add_argument('--' + key.replace('_', '-'), help='Known activity ' + key + '; omit unknown values.')


def persist(connection, event):
    """Validate and journal atomically after releasing the graph snapshot."""
    path = Path(connection.database).resolve(strict=True)
    with closing(sqlite3.connect(path.as_uri() + '?mode=rw', uri=True, timeout=1,
                                isolation_level=None, factory=HistoryConnection)) as db:
        db.execute('BEGIN IMMEDIATE')
        try:
            validate_binding(db, connection)
            info = status(db, False)
            if info.get('version') and not info.get('enabled'):
                raise ValueError('Activity history is suspended; read result retained without recording; explicitly resume history to record future reads')
            install(path, connection=db)
            db.execute('INSERT INTO ' + ident(CALLS) + '(activity_id,event_json) VALUES(?,?)',
                       (event['activity_id'], json.dumps(event, ensure_ascii=True, separators=(',', ':'))))
            db.execute('COMMIT')
        except BaseException:
            if db.in_transaction:
                db.set_progress_handler(None, 0)
                sqlite3.Connection.execute(db, 'ROLLBACK')
            raise


def read_call(connection, command, operation, *, timeout=5.0, error=ValueError,
              timeout_message='Read chain timed out; no complete result.', activity_context=None,
              read_error='Cannot open bound read snapshot'):
    """Keep complete results on history failure; warn visibly, never lose it silently.

    One chain is one activity call. References remain provisional until every
    segment and the aggregate output/deadline checks have succeeded. Failures
    before a validated snapshot exists are deliberately not journaled.
    """
    context = validate_context(activity_context)
    started = time.monotonic()
    try:
        active = ReadContext(connection, timeout=timeout, timeout_error=error, timeout_message=timeout_message)
    except sqlite3.Error as exc:
        if time.monotonic() >= started + timeout or 'interrupted' in str(exc).lower():
            raise error(timeout_message) from exc
        raise error(read_error + ': ' + str(exc)) from exc
    ok = False
    try:
        output = operation(active)
        active.check_time()
        ok = True
        return output
    finally:
        elapsed = (time.monotonic() - started) * 1000
        active.close()
        # Explicit aliases reuse the SQL event builder's graph-ID validation,
        # size bounds, identity fields and viewer-compatible reference format.
        rows = [[ref] for ref in sorted(active.returned_nodes)] if ok else []
        edges = [[ref] for ref in sorted(active.returned_edges)] if ok else []
        response = dict(ok=ok, results=[dict(columns=['trace_node_id'], rows=rows, has_more=False),
                                       dict(columns=['trace_edge_id'], rows=edges, has_more=False)],
                        completed_statements=active.completed if ok else 0,
                        transaction_rolled_back=False, autocommit_effects_possible=False)
        accesses = [dict(read=active.read_tables, write=set())] * 2
        event = build_event(response, accesses, elapsed, context, uuid.uuid4().hex,
                            connection.database, {'name': 'EvoMneme graph CLI'}, uuid.uuid4().hex)
        event.update(source='graph-cli', command=command, scope_id=connection.scope,
                     returned_rows=active.returned_rows if ok else 0)
        try:
            persist(connection, event)
        except Exception as exc:
            # Optional history must not revoke a complete read, even if existing
            # journal metadata is malformed in a way its installer cannot parse.
            from evomneme_navigate import text_lines
            print('EvoMneme activity history warning: ' + '\\n'.join(text_lines(exc)), file=sys.stderr)
