"""Bound, atomic graph maintenance; values are always SQLite bindings."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import json
import sqlite3
import time
import uuid
from urllib.parse import unquote

from evomneme import Executor, empty_result
from evomneme_activity import DatabaseActivity
from evomneme_connection import validate_binding
from evomneme_journal import CALLS, LOG, ident, install, status
from evomneme_navigate import fields
from evomneme_trace import build_event

TABLE_COLUMNS = {
    'node': ('scope_id', 'id', 'kind', 'title', 'summary', 'confidence', 'validity',
             'source_path', 'source_hash', 'line_start', 'line_end', 'updated_at', 'layer'),
    'edge': ('scope_id', 'id', 'source_id', 'target_id', 'kind', 'summary', 'confidence',
             'validity', 'source_path', 'source_hash', 'updated_at', 'layer', 'resolution', 'line_start', 'line_end'),
    'evidence': ('scope_id', 'id', 'node_id', 'edge_id', 'description', 'source_path',
                 'source_hash', 'validity', 'updated_at'),
}
TABLES = {'node': 'nodes', 'edge': 'edges', 'evidence': 'evidence'}
ENUMS = {'confidence': ('confirmed', 'inferred', 'uncertain'),
         'validity': ('current', 'stale', 'superseded'),
         'resolution': ('resolved', 'unresolved', 'ambiguous')}
DEFAULTS = {'validity': 'current', 'layer': 'knowledge', 'resolution': 'resolved'}
NULLABLE = {'source_path', 'source_hash', 'line_start', 'line_end', 'node_id', 'edge_id'}
REQUIRED = {'node': {'kind', 'title', 'summary', 'confidence'},
            'edge': {'kind', 'summary', 'confidence'}, 'evidence': {'description'}}
HELP = {
    'id': 'Required stable user-supplied ID; immutable after creation.',
    'kind': 'Explicit entity/relationship kind; free text using the host vocabulary.',
    'title': 'Exact display title; free text, may be nonunique.',
    'summary': 'Explicit understood behavior or claim; never inferred by this command.',
    'confidence': 'Explicit confidence; never inferred by this command.',
    'validity': 'Knowledge validity.',
    'layer': 'Free-text graph layer using the host vocabulary.',
    'resolution': 'Relationship target resolution.',
    'source_path': 'Nullable source locator path; recorded literally, not read or normalized.',
    'source_hash': 'Nullable inspected source content identity; recorded literally.',
    'line_start': 'Nullable positive 1-based start line; final merged range is validated.',
    'line_end': 'Nullable positive 1-based end line; must be >= retained/final line_start.',
    'source_id': 'Source node selector: exact title/ID, root, or @scope/id (percent-encoded).',
    'target_id': 'Target node selector: exact title/ID, root, or @scope/id (percent-encoded).',
    'node_id': 'Attach to an exact same-scope node ID (not a title/alias); clears edge_id atomically.',
    'edge_id': 'Attach to an exact same-scope edge ID; clears node_id atomically.',
    'description': 'Explicit evidence description; this command does not inspect the source.',
}


class UniqueValue(argparse.Action):
    def __call__(self, parser, namespace, value, option_string=None):
        if hasattr(namespace, self.dest):
            parser.error('Repeated option: ' + option_string)
        setattr(namespace, self.dest, value)


def configure_parser(subparsers):
    for action in ('add', 'update'):
        command = subparsers.add_parser(action, help=action.capitalize() + ' bound graph knowledge atomically')
        kinds = command.add_subparsers(dest='entity', required=True)
        for entity, columns in TABLE_COLUMNS.items():
            nullable = sorted(NULLABLE.intersection(columns))
            parser = kinds.add_parser(entity, formatter_class=argparse.RawDescriptionHelpFormatter,
                description=('Add one explicit record.' if action == 'add' else
                             'Patch only supplied fields. Omitted fields retain their values. Empty or unchanged patches fail.'),
                epilog='scope_id comes only from the verified connection. id and scope_id are immutable.\n'
                       'updated_at is managed UTC on actual writes and cannot be supplied or cleared.\n'
                       'Empty text is literal text, not NULL; --clear FIELD is the only clearing syntax.\n'
                       'Repeated value options fail. Complete output is limited to 65536 UTF-8 bytes before commit.\n'
                       'No implicit database/root creation, schema migration, or deletion.\n'
                       'A current configured root cannot be invalidated. Preexisting root gaps allow maintenance\n'
                       'with a warning until explicitly repaired; ordinary navigation remains unavailable.\n'
                       + (('Evidence requires exactly one of --node_id or --edge_id.\n' if action == 'add' else
                           'Evidence final stored row requires exactly one attachment; omitted flags retain the parent.\n')
                          if entity == 'evidence' else '') +
                       'Node selectors accept exact titles/IDs, root, @scope/id; ambiguity fails.\n'
                       'Exact IDs also address stale/superseded records. Edge/evidence update IDs are exact.\n'
                       'All changes and released activity history commit together; any failure rolls back.\n'
                       'Nullable fields: ' + ', '.join(nullable) + '\n'
                       'Stored schema fields: ' + ', '.join(columns) + '\n'
                       'Chain mutations with --next before --: one transaction, all-or-nothing; no reads/setup/help.\n'
                       '-- ends separator parsing for the entire remainder. Literal flag value: --summary=--next.')
            if action == 'update':
                parser.add_argument('selector', metavar='NAME' if entity == 'node' else 'ID',
                                    help='Record to patch; exact same-scope ID or unambiguous node selector.')
                parser.add_argument('--clear', action='append', default=[], choices=nullable, metavar='FIELD',
                                    help='Set nullable FIELD to SQL NULL; repeat for several fields. Cannot also set FIELD.')
            elif entity == 'edge':
                parser.add_argument('source', metavar='SOURCE', help=HELP['source_id'])
                parser.add_argument('target', metavar='TARGET', help=HELP['target_id'])
            for column in columns:
                if column in ('scope_id', 'updated_at') or (action == 'update' and column == 'id'):
                    continue
                if action == 'add' and entity == 'edge' and column in ('source_id', 'target_id'):
                    continue
                kwargs = {'help': HELP[column], 'default': argparse.SUPPRESS, 'action': UniqueValue}
                if column in ENUMS:
                    kwargs['choices'] = ENUMS[column]
                if column in ('line_start', 'line_end'):
                    kwargs['type'] = int
                if action == 'add':
                    kwargs['required'] = column == 'id' or column in REQUIRED[entity]
                    if column in DEFAULTS:
                        kwargs['help'] += ' Add default: ' + DEFAULTS[column] + '.'
                    elif column in NULLABLE:
                        kwargs['help'] += ' Add default: NULL.'
                else:
                    kwargs['help'] += ' Omitted: retain existing value.'
                parser.add_argument('--' + column, **kwargs)
            parser.set_defaults(mutation=True)
    command = subparsers.add_parser('delete', help='Physically delete bound graph records; retain audit history')
    kinds = command.add_subparsers(dest='entity', required=True)
    for entity in TABLES:
        parser = kinds.add_parser(entity, formatter_class=argparse.RawDescriptionHelpFormatter,
            description='Physically delete one selected record, preserving released row/activity history.',
            epilog='scope_id/database come only from the verified receipt. All validity states are included.\n'
                   'Configured root cannot be deleted, even when stale or with --cascade.\n'
                   'Default: RESTRICT dependencies; an error lists counts. Unknown external FK dependencies fail.\n'
                   + ('--cascade deletes incident edges, their/node evidence and own symbol_details/file_details;\n'
                      'never neighboring nodes or contains descendants. Self-loops count once; parallel edges all count.\n'
                      if entity == 'node' else
                      '--cascade deletes only evidence attached to this edge, then the edge.\n' if entity == 'edge' else
                      'Evidence deletion affects only the selected evidence row; --cascade is unavailable.\n') +
                   'One validated BEGIN IMMEDIATE transaction includes history, actual deleted counts and output.\n'
                   'UTF-8 output limit: 65536 bytes, checked before commit. Any failure rolls back.\n'
                   'No implicit database/root creation or migration; id/updated_at are not mutable parameters.\n'
                   'Chain mutations with --next before --: one transaction; no reads/setup/help.\n'
                   '-- makes the literal remainder the last segment.')
        parser.add_argument('selector', metavar='NAME' if entity == 'node' else 'ID',
                            help=('Exact title/ID, root, or percent-encoded @scope/id; ambiguity fails, historical IDs supported.'
                                  if entity == 'node' else 'Exact existing same-scope ID, including stale/superseded rows.'))
        if entity != 'evidence':
            parser.add_argument('--cascade', action='store_true', help='Delete only the documented dependent closure. Default: restrict.')
        parser.set_defaults(mutation=True)


def resolve_node(db, connection, selector):
    """Resolve within the write snapshot, including historical IDs for maintenance."""
    if not isinstance(selector, str) or not selector:
        raise ValueError('Node selector must be nonempty text')
    if selector == 'root':
        selector = '@' + connection.scope.replace('%', '%25').replace('/', '%2F') + '/' + connection.root_id.replace('%', '%25').replace('/', '%2F')
    if selector.startswith('@') and '/' in selector:
        scope, id_ = selector[1:].split('/', 1)
        try:
            scope, id_ = unquote(scope, errors='strict'), unquote(id_, errors='strict')
        except UnicodeError as exc:
            raise ValueError('Invalid qualified node selector') from exc
        if scope != connection.scope:
            raise ValueError('Node selector belongs to another scope')
        rows = db.execute('SELECT * FROM nodes WHERE scope_id=? AND id=?', (scope, id_)).fetchall()
    else:
        rows = db.execute('SELECT * FROM nodes WHERE scope_id=? AND (id=? OR title=?)',
                          (connection.scope, selector, selector)).fetchall()
    if len(rows) != 1:
        raise ValueError(('Ambiguous' if rows else 'Missing') + ' same-scope node selector: ' + selector)
    return dict(rows[0])


def exact(db, table, scope, id_):
    row = db.execute('SELECT * FROM ' + table + ' WHERE scope_id=? AND id=?', (scope, id_)).fetchone()
    if row is None:
        raise ValueError('Missing same-scope ' + table + ' ID: ' + str(id_))
    return dict(row)


def validate_row(db, connection, entity, row):
    for key in {'id', *REQUIRED[entity], 'validity', 'layer', 'resolution'}.intersection(row):
        if not isinstance(row[key], str) or not row[key].strip():
            raise ValueError(key + ' must be nonempty text')
    for key, choices in ENUMS.items():
        if key in row and row[key] not in choices:
            raise ValueError('Invalid ' + key)
    for key in ('line_start', 'line_end'):
        if row.get(key) is not None and (type(row[key]) is not int or row[key] < 1):
            raise ValueError(key + ' must be a positive integer or NULL')
    if row.get('line_end') is not None and (row.get('line_start') is None or row['line_end'] < row['line_start']):
        raise ValueError('line_end requires line_start and must be >= line_start in the final row')
    if entity == 'edge':
        for key in ('source_id', 'target_id'):
            exact(db, 'nodes', connection.scope, row[key])
    if entity == 'evidence':
        if (row['node_id'] is None) == (row['edge_id'] is None):
            raise ValueError('Evidence requires exactly one of node_id or edge_id')
        if row['node_id'] is not None:
            exact(db, 'nodes', connection.scope, row['node_id'])
        else:
            edge = exact(db, 'edges', connection.scope, row['edge_id'])
            for key in ('source_id', 'target_id'):
                exact(db, 'nodes', connection.scope, edge[key])


class MutationSession:
    """One identity-validated transaction shared by single writes or a chain."""
    def __init__(self, connection, timeout=None):
        self.connection = connection
        self.deadline = None if timeout is None else time.monotonic() + timeout
        self.executor = None
        self.history = None
        try:
            self.check_time()
            self.executor = Executor(connection.database, history=False)
            self.db = self.executor.connection
            self.db.row_factory = sqlite3.Row
            if self.deadline is not None:
                self.db.set_progress_handler(lambda: int(time.monotonic() >= self.deadline), 1000)
                self.check_time()
            self.db.execute('BEGIN IMMEDIATE')
            self.executor._check_binding()
            self.warnings = list(dict.fromkeys([*connection.warnings, *validate_binding(self.db, connection)]))
            self.check_time()
        except sqlite3.Error as exc:
            self.close()
            raise ValueError('Cannot open bound graph transaction: ' + str(exc)) from exc
        except BaseException:
            self.close()
            raise

    def check_time(self):
        if self.deadline is not None and time.monotonic() >= self.deadline:
            raise ValueError('Mutation chain timed out; command rolled back')
        if self.deadline is not None and self.executor is not None:
            self.db.execute('PRAGMA busy_timeout=' + str(max(1, int((self.deadline - time.monotonic()) * 1000))))

    def ensure_history(self):
        if self.history is None:
            info = status(self.db, False)
            if info.get('version') and not info.get('enabled'):
                raise ValueError('Activity history is suspended; explicitly resume released history before graph maintenance')
            install(self.executor.path, connection=self.db)
            self.history = DatabaseActivity(self.executor)
        return self.history

    def commit(self):
        self.check_time()
        self.executor._check_binding()
        self.db.execute('COMMIT')

    def close(self):
        if self.executor is not None:
            self.db.set_progress_handler(None, 0)
            if self.db.in_transaction:
                self.db.execute('ROLLBACK')
            self.executor.close()


def mutate(connection, action, entity, values, selector=None, clear=(), source=None, target=None, session=None):
    """Render one write; standalone calls commit, shared sessions own commit."""
    if action not in ('add', 'update') or entity not in TABLES:
        raise ValueError('Unsupported mutation command')
    if session is not None and session.connection != connection:
        raise ValueError('Shared mutation session belongs to another binding')
    columns = TABLE_COLUMNS[entity]
    allowed = set(columns) - {'scope_id', 'updated_at'} - ({'id'} if action == 'update' else set())
    if set(values) - allowed:
        raise ValueError('Unknown or immutable fields: ' + ', '.join(sorted(set(values) - allowed)))
    if len(set(clear)) != len(clear) or set(clear) - NULLABLE.intersection(columns):
        raise ValueError('Invalid or repeated clear field')
    if set(clear).intersection(values):
        raise ValueError('Cannot set and clear the same field')
    if action == 'add' and clear:
        raise ValueError('clear is only supported for updates')
    if entity == 'evidence' and 'node_id' in values and 'edge_id' in values:
        raise ValueError('Supply only one evidence attachment')
    started = time.monotonic()
    owns_session = session is None
    active = session if session is not None else MutationSession(connection)
    executor, db = active.executor, active.db
    try:
        active.check_time()
        warnings = list(active.warnings)
        initial_root = db.execute('SELECT validity FROM nodes WHERE scope_id=? AND id=?',
                                  (connection.scope, connection.root_id)).fetchone()
        before = None
        if action == 'update':
            before = (resolve_node(db, connection, selector) if entity == 'node' else
                      exact(db, TABLES[entity], connection.scope, selector))
            row = dict(before)
        else:
            row = {column: DEFAULTS.get(column) for column in columns}
            row['scope_id'] = connection.scope
            if not {'id', *REQUIRED[entity]} <= set(values):
                raise ValueError('Missing required add fields')
        patch = dict(values)
        patch.update({key: None for key in clear})
        if entity == 'edge':
            if action == 'add':
                patch.update(source_id=source, target_id=target)
            for key in ('source_id', 'target_id'):
                if key in patch:
                    patch[key] = resolve_node(db, connection, patch[key])['id']
        if entity == 'evidence':
            if 'node_id' in values:
                patch['edge_id'] = None
            elif 'edge_id' in values:
                patch['node_id'] = None
        row.update(patch)
        validate_row(db, connection, entity, row)
        changed = [key for key in columns if key != 'updated_at' and
                   (before is None or (key in patch and before[key] != row[key]))]
        if action == 'update' and not changed:
            raise ValueError('Update has no changed fields')
        row['updated_at'] = datetime.now(timezone.utc).isoformat(timespec='microseconds').replace('+00:00', 'Z')
        # Released extension installation shares the validated transaction; it
        # cannot modify a wrong-bound store or survive a failed graph command.
        history = active.ensure_history()
        event_id = uuid.uuid4().hex
        event = build_event(empty_result(), [], 0, None, executor.session_id, executor.path,
                            {'name': 'EvoMneme graph CLI'}, event_id)
        history.scope(event)
        table = TABLES[entity]
        if action == 'add':
            db.execute('INSERT INTO ' + table + '(' + ','.join(columns) + ') VALUES('
                       + ','.join('?' for _ in columns) + ')', [row[key] for key in columns])
        else:
            assigned = changed + ['updated_at']
            db.execute('UPDATE ' + table + ' SET ' + ','.join(key + '=?' for key in assigned)
                       + ' WHERE scope_id=? AND id=?', [row[key] for key in assigned] + [connection.scope, row['id']])
        actual = exact(db, table, connection.scope, row['id'])
        validate_row(db, connection, entity, actual)
        final_root = db.execute('SELECT validity FROM nodes WHERE scope_id=? AND id=?',
                               (connection.scope, connection.root_id)).fetchone()
        if final_root is None or final_root['validity'] != 'current':
            if initial_root is not None and initial_root['validity'] == 'current':
                raise ValueError('Configured root must remain current')
            warnings.append('Configured root is missing or not current; maintenance succeeded, but ordinary navigation remains unavailable until explicitly repaired')
        changed = [key for key in columns if key != 'updated_at' and
                   (before is None or before[key] != actual[key])]
        response = empty_result()
        response.update(completed_statements=1, autocommit_effects_possible=True, results=[{'columns': list(columns),
            'rows': [[actual[key] for key in columns]], 'has_more': False, 'affected_rows': 1}])
        event = build_event(response, [{'read': {table}, 'write': {table}}],
                            (time.monotonic() - started) * 1000, None, executor.session_id,
                            executor.path, {'name': 'EvoMneme graph CLI'}, event_id)
        event.update(source='graph-cli', command=action, entity=entity, scope_id=connection.scope,
                     id=actual['id'], changed_fields=changed + ['updated_at'])
        db.execute('INSERT INTO ' + ident(CALLS) + '(activity_id,event_json) VALUES(?,?)',
                   (event_id, json.dumps(event, ensure_ascii=True, separators=(',', ':'))))
        output = '\n'.join(fields(dict(action=action, entity=entity,
                                       changed_fields=', '.join(changed + ['updated_at']), **actual))) + '\n'
        for warning in warnings:
            output += '\n' + '\n'.join(fields(dict(warning=warning))) + '\n'
        if len(output.encode('utf-8')) > 65536:
            raise ValueError('Mutation output exceeds 65536 UTF-8 bytes; command rolled back')
        executor._check_binding()
        active.check_time()
        if owns_session:
            active.commit()
        return output
    except sqlite3.Error as exc:
        raise ValueError('Cannot update bound graph: ' + str(exc)) from exc
    finally:
        if owns_session:
            active.close()


def delete_plan(db, connection, entity, selected):
    """Materialize the bounded semantic closure, never ownership descendants."""
    scope, id_ = connection.scope, selected['id']
    plan = {table: [] for table in ('evidence', 'edges', 'symbol_details', 'file_details', 'nodes')}
    if entity == 'node':
        plan['nodes'] = [selected]
        plan['edges'] = [dict(row) for row in db.execute(
            'SELECT * FROM edges WHERE scope_id=? AND (source_id=? OR target_id=?) ORDER BY id', (scope, id_, id_))]
        plan['evidence'] = [dict(row) for row in db.execute(
            'SELECT * FROM evidence WHERE scope_id=? AND (node_id=? OR edge_id IN '
            '(SELECT id FROM edges WHERE scope_id=? AND (source_id=? OR target_id=?))) ORDER BY id',
            (scope, id_, scope, id_, id_))]
        for table in ('symbol_details', 'file_details'):
            plan[table] = [dict(row) for row in db.execute('SELECT * FROM ' + table + ' WHERE scope_id=? AND node_id=?', (scope, id_))]
    elif entity == 'edge':
        plan['edges'] = [selected]
        plan['evidence'] = [dict(row) for row in db.execute(
            'SELECT * FROM evidence WHERE scope_id=? AND edge_id=? ORDER BY id', (scope, id_))]
    else:
        plan['evidence'] = [selected]
    for edge in plan['edges']:
        for key in ('source_id', 'target_id'):
            exact(db, 'nodes', scope, edge[key])
    return plan


def reject_external_dependencies(db, plan):
    """Never let an unfamiliar incoming FK silently broaden physical deletion."""
    known = {
        ('edges', 'nodes', ('scope_id', 'source_id'), ('scope_id', 'id')),
        ('edges', 'nodes', ('scope_id', 'target_id'), ('scope_id', 'id')),
        ('evidence', 'nodes', ('scope_id', 'node_id'), ('scope_id', 'id')),
        ('evidence', 'edges', ('scope_id', 'edge_id'), ('scope_id', 'id')),
        ('symbol_details', 'nodes', ('scope_id', 'node_id'), ('scope_id', 'id')),
        ('file_details', 'nodes', ('scope_id', 'node_id'), ('scope_id', 'id')),
    }
    tables = [row[0] for row in db.execute("SELECT name FROM sqlite_schema WHERE type='table'")]
    for table in tables:
        groups = {}
        for row in db.execute('PRAGMA foreign_key_list(' + ident(table) + ')'):
            groups.setdefault(row[0], []).append(row)
        for rows in groups.values():
            rows.sort(key=lambda row: row[1])
            parent = rows[0][2].lower()
            if not plan.get(parent):
                continue
            child_columns = tuple(row[3].lower() for row in rows)
            parent_columns = tuple(row[4].lower() if row[4] else None for row in rows)
            if (table, parent, child_columns, parent_columns) in known:
                continue
            if any(column is None for column in parent_columns):
                pk = sorted((row for row in db.execute('PRAGMA table_info(' + ident(parent) + ')') if row[5]), key=lambda row: row[5])
                parent_columns = tuple(row[1] for row in pk)
            if len(parent_columns) != len(child_columns):
                raise ValueError('Unsupported external foreign key from ' + table + '; deletion refused')
            for selected in plan[parent]:
                found = db.execute('SELECT 1 FROM ' + ident(table) + ' WHERE '
                    + ' AND '.join(ident(column) + '=?' for column in child_columns) + ' LIMIT 1',
                    [selected[column] for column in parent_columns]).fetchone()
                if found:
                    raise ValueError('External foreign key dependency from ' + table + ' to ' + parent + '; deletion refused, including --cascade')


def verify_delete_history(db, plan, event_id):
    """Reject balanced trigger side effects that net row counts cannot detect."""
    expected = Counter()
    for table, rows in plan.items():
        key = 'node_id' if table in ('symbol_details', 'file_details') else 'id'
        for row in rows:
            expected[(table, row['scope_id'], row[key])] += 1
    actual = Counter()
    for change in db.execute('SELECT table_name,operation,key_before_json,key_after_json FROM ' + ident(LOG)
                             + ' WHERE activity_id=?', (event_id,)):
        table = change['table_name'].lower()
        if table not in plan:
            continue
        if change['operation'] != 'delete' or change['key_after_json'] is not None:
            raise ValueError('Unexpected graph insert/update during deletion; command rolled back')
        key = 'node_id' if table in ('symbol_details', 'file_details') else 'id'
        identity = json.loads(change['key_before_json'])
        values = []
        for column in ('scope_id', key):
            field = identity.get(column, {})
            if field.get('type') != 'text' or field.get('truncated') or not isinstance(field.get('value'), str):
                raise ValueError('Cannot verify full deleted identity from released history; command rolled back')
            values.append(field['value'])
        actual[(table, *values)] += 1
    if actual != expected:
        raise ValueError('Actual deleted graph identities differ from the validated plan; command rolled back')


def delete(connection, entity, selector, cascade=False, session=None):
    """Delete an exact planned closure and audit it in the same transaction."""
    if entity not in TABLES or (entity == 'evidence' and cascade):
        raise ValueError('Unsupported delete command or cascade option')
    if session is not None and session.connection != connection:
        raise ValueError('Shared mutation session belongs to another binding')
    started = time.monotonic()
    owns_session = session is None
    active = session if session is not None else MutationSession(connection)
    executor, db = active.executor, active.db
    try:
        active.check_time()
        warnings = list(active.warnings)
        selected = (resolve_node(db, connection, selector) if entity == 'node' else
                    exact(db, TABLES[entity], connection.scope, selector))
        if entity == 'node' and selected['id'] == connection.root_id:
            raise ValueError('Configured root cannot be deleted; binding retained, even with --cascade')
        initial_root = db.execute('SELECT validity FROM nodes WHERE scope_id=? AND id=?',
                                 (connection.scope, connection.root_id)).fetchone()
        plan = delete_plan(db, connection, entity, selected)
        counts = {table: len(rows) for table, rows in plan.items()}
        dependencies = {table: count for table, count in counts.items() if table != TABLES[entity] and count}
        if dependencies and not cascade:
            raise ValueError('Delete restricted by dependent counts: ' + ', '.join(table + '=' + str(count) for table, count in dependencies.items())
                             + '; explicitly use --cascade for only the documented dependent closure')
        reject_external_dependencies(db, plan)
        before_counts = {table: db.execute('SELECT count(*) FROM ' + table).fetchone()[0] for table in plan}
        history = active.ensure_history()
        event_id = uuid.uuid4().hex
        event = build_event(empty_result(), [], 0, None, executor.session_id, executor.path,
                            {'name': 'EvoMneme graph CLI'}, event_id)
        history.scope(event)
        for table, rows in plan.items():
            key = 'node_id' if table in ('symbol_details', 'file_details') else 'id'
            for row in rows:
                cursor = db.execute('DELETE FROM ' + table + ' WHERE scope_id=? AND ' + key + '=?',
                                    (connection.scope, row[key]))
                if cursor.rowcount != 1:
                    raise ValueError('Deleted row count differs from the validated plan; command rolled back')
        for table, rows in plan.items():
            key = 'node_id' if table in ('symbol_details', 'file_details') else 'id'
            if before_counts[table] - db.execute('SELECT count(*) FROM ' + table).fetchone()[0] != counts[table]:
                raise ValueError('Deleted table counts differ from the validated plan; command rolled back')
            for row in rows:
                if db.execute('SELECT 1 FROM ' + table + ' WHERE scope_id=? AND ' + key + '=?', (connection.scope, row[key])).fetchone():
                    raise ValueError('A planned row remains after deletion; command rolled back')
        final_root = db.execute('SELECT validity FROM nodes WHERE scope_id=? AND id=?',
                               (connection.scope, connection.root_id)).fetchone()
        if initial_root is not None and (final_root is None or
                (initial_root['validity'] == 'current' and final_root['validity'] != 'current')):
            raise ValueError('Configured root cannot be deleted or invalidated; command rolled back')
        if final_root is None or final_root['validity'] != 'current':
            warnings.append('Configured root is missing or not current; maintenance succeeded, but ordinary navigation remains unavailable until explicitly repaired')
        written = {table for table, count in counts.items() if count}
        response = empty_result()
        response.update(completed_statements=sum(counts.values()), autocommit_effects_possible=True)
        event = build_event(response, [{'read': set(plan), 'write': written}],
                            (time.monotonic() - started) * 1000, None, executor.session_id, executor.path,
                            {'name': 'EvoMneme graph CLI'}, event_id)
        event.update(source='graph-cli', command='delete', entity=entity, scope_id=connection.scope,
                     id=selected['id'], cascade=cascade, deleted_counts=counts)
        db.execute('INSERT INTO ' + ident(CALLS) + '(activity_id,event_json) VALUES(?,?)',
                   (event_id, json.dumps(event, ensure_ascii=True, separators=(',', ':'))))
        verify_delete_history(db, plan, event_id)
        output = '\n'.join(fields(dict(action='delete', entity=entity, scope_id=connection.scope,
                                        id=selected['id'], cascade=cascade, deleted_counts=counts))) + '\n'
        for warning in warnings:
            output += '\n' + '\n'.join(fields(dict(warning=warning))) + '\n'
        if len(output.encode('utf-8')) > 65536:
            raise ValueError('Mutation output exceeds 65536 UTF-8 bytes; command rolled back')
        executor._check_binding()
        active.check_time()
        if owns_session:
            active.commit()
        return output
    except sqlite3.Error as exc:
        raise ValueError('Cannot delete bound graph: ' + str(exc)) from exc
    finally:
        if owns_session:
            active.close()


def run(connection, args, session=None):
    if args.command == 'delete':
        return delete(connection, args.entity, args.selector, cascade=getattr(args, 'cascade', False), session=session)
    values = {key: value for key, value in vars(args).items() if key in TABLE_COLUMNS[args.entity]}
    return mutate(connection, args.command, args.entity, values, selector=getattr(args, 'selector', None),
                  clear=getattr(args, 'clear', ()), source=getattr(args, 'source', None), target=getattr(args, 'target', None), session=session)
