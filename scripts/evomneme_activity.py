"""Connection-local call attribution; permanent triggers remain plain SQLite."""

import json
import sqlite3

from evomneme_graph import validate_schema
from evomneme_journal import ACTOR_FIELDS, CALLS, LINKS, LOG, META, ident, install, literal, status


class DatabaseActivity:
    def __init__(self, executor):
        self.executor = executor
        self.schema_version = None
        self.ready = False
        self.mutations = 0
        self.counter_installed = False
        self.counter_schema_version = None

    def ensure(self):
        """Defer extensions until native callers have built a recognized v3 store."""
        db = self.executor.connection
        version = db.execute('PRAGMA schema_version').fetchone()[0]
        if self.schema_version == version:
            return self.ready
        try:
            validate_schema(db)
        except ValueError:
            self.ready = False
            return False
        if db.in_transaction:
            # Preserve an existing scope for already tracked tables. New table
            # installation waits until the native transaction releases its lock.
            return self.ready
        # Setup and completed-call writes use their own connection so native
        # last_insert_rowid()/changes() on the executor are not overwritten.
        info = status(db)
        if not info.get('enabled') or not info.get('activity_enabled') or info.get('untracked_tables'):
            install(self.executor.path)
        self.ready = bool(status(db, False).get('activity_enabled'))
        self.observe_existing()
        self.schema_version = db.execute('PRAGMA schema_version').fetchone()[0]
        return self.ready

    def observe_existing(self):
        """Count existing bookkeeping without installing or upgrading main history.

        A recording opt-out does not remove permanent row triggers. Their writes
        still need to be excluded from affected_rows and access metadata.
        """
        db = self.executor.connection
        version = db.execute('PRAGMA schema_version').fetchone()[0]
        if self.counter_schema_version == version:
            return
        info = status(db, False)
        self.counter_installed = bool(info.get('version'))
        if self.counter_installed:
            # Only this connection sees these TEMP triggers/functions. Accounting
            # subtracts bookkeeping while retaining native user-trigger effects.
            db.create_function('evomneme_history_mutation', 0, self.count_mutation)
            existing = {row[0] for row in db.execute("SELECT name FROM sqlite_schema WHERE type='table'")}
            for table in (LOG, LINKS, META, CALLS):
                if table not in existing:
                    continue
                for operation in ('INSERT', 'UPDATE', 'DELETE'):
                    name = 'evomneme_counter_' + table + '_' + operation
                    self.temp_ddl('CREATE TEMP TRIGGER IF NOT EXISTS ' + ident(name) + ' AFTER ' + operation + ' ON main.' + ident(table)
                                  + ' BEGIN SELECT evomneme_history_mutation(); END')
        self.counter_schema_version = version

    def count_mutation(self):
        self.mutations += 1
        return None

    def scope(self, event):
        """Attribute only inserts performed by this connection and this call."""
        self.clear()
        actor = json.dumps({key: event.get(key) for key in ACTOR_FIELDS}, ensure_ascii=True)
        self.temp_ddl('CREATE TEMP TRIGGER evomneme_activity_scope AFTER INSERT ON main.' + ident(LOG)
            + ' BEGIN UPDATE ' + ident(LOG) + ' SET activity_id=' + literal(event['activity_id'])
            + ',actor_json=' + literal(actor) + ' WHERE id=NEW.id; END')

    def clear(self):
        self.temp_ddl('DROP TRIGGER IF EXISTS temp.evomneme_activity_scope')

    def temp_ddl(self, statement):
        """Maintain connection-local scopes even after native query_only toggles.

        Restore the caller's setting before any user SQL; only TEMP DDL executes
        while it is temporarily off. A stale caller scope must never survive.
        """
        db = self.executor.connection
        readonly = db.execute('PRAGMA query_only').fetchone()[0]
        if readonly:
            db.execute('PRAGMA query_only=OFF')
        try:
            db.execute(statement)
        finally:
            if readonly:
                db.execute('PRAGMA query_only=ON')

    def record(self, event):
        self.executor._check_binding()
        encoded = json.dumps(event, ensure_ascii=True, separators=(',', ':'))
        if len(encoded) > 1024 * 1024:
            raise ValueError('Activity metadata exceeds the 1 MiB event limit')
        db = sqlite3.connect(self.executor.path.as_uri() + '?mode=rw', uri=True, timeout=1, isolation_level=None)
        try:
            db.execute('INSERT INTO ' + ident(CALLS) + '(activity_id,event_json) VALUES(?,?)',
                       (event['activity_id'], encoded))
        finally:
            db.close()


def managed_table(name):
    return bool(name and name.lower().startswith('evomneme_change_'))
