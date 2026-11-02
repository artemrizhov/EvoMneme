"""One validated read-only snapshot and deadline, reusable across read commands."""
from pathlib import Path
import sqlite3
import time
import json

from evomneme_connection import validate_binding


class ReadContext:
    def __init__(self, connection, timeout=5.0, timeout_error=ValueError, timeout_message='Read chain timed out; no complete result.'):
        self.connection = connection
        self.deadline = time.monotonic() + timeout
        self.db = None
        self.warnings = []
        self.read_tables = set()
        self.returned_nodes = set()
        self.returned_edges = set()
        self.returned_rows = 0
        self.completed = 0
        self.timeout_error = timeout_error
        self.timeout_message = timeout_message
        try:
            self.check_time()
            self.db = sqlite3.connect(Path(connection.database).resolve().as_uri() + '?mode=ro',
                                      uri=True, isolation_level=None, timeout=timeout)
            self.db.row_factory = sqlite3.Row
            self.db.execute('PRAGMA busy_timeout=' + str(max(1, int((self.deadline - time.monotonic()) * 1000))))
            self.db.execute('PRAGMA query_only=ON')
            self.db.set_progress_handler(lambda: int(time.monotonic() >= self.deadline), 1000)
            self.db.execute('BEGIN')
            self.warnings = list(dict.fromkeys([*connection.warnings, *validate_binding(self.db, connection)]))
            self.db.set_authorizer(self.observe)
            self.check_time()
        except BaseException:
            self.close()
            raise

    def check_time(self):
        if time.monotonic() >= self.deadline:
            raise self.timeout_error(self.timeout_message)

    def observe(self, action, table, column, database, trigger):
        if action == sqlite3.SQLITE_READ and database == 'main' and table and not table.startswith('sqlite_'):
            self.read_tables.add(table)
        return sqlite3.SQLITE_OK

    def returned(self, table, id_, count=True):
        """Only output cards, never selectors/counts/internal examined rows."""
        self.returned_rows += int(count)
        if table in ('nodes', 'edges'):
            graph_id = json.dumps([self.connection.scope, id_], ensure_ascii=False, separators=(',', ':'))
            (self.returned_nodes if table == 'nodes' else self.returned_edges).add(graph_id)

    def close(self):
        if self.db is not None:
            self.db.close()
            self.db = None
