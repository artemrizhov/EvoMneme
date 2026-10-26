"""One validated read-only snapshot and deadline, reusable across read commands."""
from pathlib import Path
import sqlite3
import time

from evomneme_connection import validate_binding


class ReadContext:
    def __init__(self, connection, timeout=5.0, timeout_error=ValueError, timeout_message='Read chain timed out; no complete result.'):
        self.connection = connection
        self.deadline = time.monotonic() + timeout
        self.db = None
        self.warnings = []
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
            self.check_time()
        except BaseException:
            self.close()
            raise

    def check_time(self):
        if time.monotonic() >= self.deadline:
            raise self.timeout_error(self.timeout_message)

    def close(self):
        if self.db is not None:
            self.db.close()
            self.db = None
