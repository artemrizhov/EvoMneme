"""Versioned, transactional SQLite row-change history, without writer-side UDFs."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3

PREFIX = 'evomneme_change_'
LOG = PREFIX + 'log'
LINKS = PREFIX + 'elements'
META = PREFIX + 'meta'
OWNER = 'EvoMneme row journal'
VERSION = '2'
CALLS = PREFIX + 'calls'
ACTOR_FIELDS = ('chat', 'session', 'agent', 'client', 'chat_title', 'session_title', 'agent_name', 'identity')
MAX_COLUMNS = 200


def ident(value):
    return '"' + value.replace('"', '""') + '"'


def literal(value):
    return "'" + value.replace("'", "''") + "'"


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')


def tables(db):
    shadow = {r[1] for r in db.execute('PRAGMA table_list') if r[0] == 'main' and r[2] in {'shadow', 'virtual'}}
    result, unsupported = {}, []
    for name, sql in db.execute("SELECT name,sql FROM sqlite_schema WHERE type='table' ORDER BY name"):
        if name.lower().startswith(('sqlite_', PREFIX)):
            continue
        columns = db.execute('PRAGMA table_info(' + ident(name) + ')').fetchall()
        if name in shadow or (sql or '').upper().startswith('CREATE VIRTUAL TABLE') or len(columns) > MAX_COLUMNS:
            unsupported.append(name)
            continue
        signature = hashlib.sha256(json.dumps([sql, columns], ensure_ascii=True).encode()).hexdigest()
        result[name] = {'columns': columns, 'signature': signature}
    return result, unsupported


def status(db, inspect_schema=True):
    names = {r[0].lower() for r in db.execute("SELECT name FROM sqlite_schema WHERE type='table'")}
    if not {LOG, LINKS, META} <= names:
        return {'enabled': False, 'tracked_tables': [], 'untracked_tables': []}
    values = dict(db.execute('SELECT key,value FROM ' + ident(META)))
    if values.get('owner') != OWNER or values.get('format_version') not in {'1', VERSION}:
        return {'enabled': False, 'error': 'Unrecognized journal format; existing tables were preserved',
                'tracked_tables': [], 'untracked_tables': []}
    managed = {key[6:]: json.loads(value) for key, value in values.items() if key.startswith('table:')}
    untracked, unsupported = [], []
    if inspect_schema:
        current, unsupported = tables(db)
        trigger_names = {r[0] for r in db.execute("SELECT name FROM sqlite_schema WHERE type='trigger'")}
        for name, data in current.items():
            entry = managed.get(name, {})
            if entry.get('signature') != data['signature'] or not set(entry.get('triggers', [])) <= trigger_names:
                untracked.append(name)
    return {'enabled': values.get('enabled') == '1', 'version': values['format_version'],
            'activity_enabled': values['format_version'] == VERSION and CALLS in names,
            'started_at': values.get('started_at'), 'tracked_tables': sorted(managed),
            'untracked_tables': untracked, 'unsupported_tables': unsupported}


def json_object(pairs):
    """Stay below older SQLite function-argument limits, even for wide rows."""
    if len(pairs) <= 24:
        return 'json_object(' + ','.join(literal(k) + ',' + v for k, v in pairs) + ')'
    members = ' UNION ALL '.join('SELECT ' + literal(k) + ' AS k,' + v + ' AS v' for k, v in pairs)
    return '(SELECT json_group_object(k,json(v)) FROM (' + members + '))'


def snapshot(alias, columns):
    cap = max(64, min(16384, 32768 // max(1, len(columns))))
    fields = []
    for column in columns:
        value = alias + '.' + ident(column)
        kind = 'typeof(' + value + ')'
        preview = ("CASE WHEN " + kind + "='blob' THEN hex(substr(" + value + ',1,' + str(cap//2) + '))'
                   " WHEN " + kind + "='text' THEN substr(" + value + ',1,' + str(cap) + ')'
                   " WHEN " + kind + "='real' AND abs(" + value + ")>1.7976931348623157e308 THEN CASE WHEN " + value + ">0 THEN 'Infinity' ELSE '-Infinity' END ELSE " + value + ' END')
        fields.append((column, json_object([
            ('type', kind), ('value', preview),
            ('length', "CASE WHEN " + kind + " IN ('text','blob') THEN length(" + value + ') END'),
            ('truncated', "CASE WHEN " + kind + "='blob' THEN length(" + value + ')>' + str(cap//2)
             + " WHEN " + kind + "='text' THEN length(" + value + ')>' + str(cap) + ' ELSE 0 END')
        ])))
    return json_object(fields)


def graph_links(table, alias, columns):
    """Known physical rows link to stable IDs; unknown custom mappings stay explicit."""
    specs = []
    if {'scope_id', 'id'} <= columns:
        if table == 'nodes':
            specs.append(('nodes', ['scope_id', 'id'], None, 'entity'))
        elif table == 'edges':
            specs.append(('edges', ['scope_id', 'id'], None, 'entity'))
    if 'scope_id' in columns:
        if table in {'symbol_details', 'file_details'} and 'node_id' in columns:
            specs.append(('nodes', ['scope_id', 'node_id'], None, 'detail'))
        if table == 'evidence':
            for column, kind in (('node_id', 'nodes'), ('edge_id', 'edges')):
                if column in columns:
                    specs.append((kind, ['scope_id', column], None, 'evidence'))
    output = []
    for kind, fields, namespace, role in specs:
        values = [alias + '.' + ident(c) for c in fields]
        guard = ' AND '.join("typeof(" + v + ") IN ('text','integer') AND length(" + v + ')<=4096' for v in values)
        args = ([literal(namespace)] if namespace else []) + values
        expression = 'CASE WHEN ' + guard + ' THEN json_array(' + ','.join(args) + ') END'
        output.append((kind, expression, role))
    return output


def trigger_sql(table, operation, columns, keys, name):
    old = snapshot('OLD', columns) if operation != 'INSERT' else 'NULL'
    new = snapshot('NEW', columns) if operation != 'DELETE' else 'NULL'
    key_old = snapshot('OLD', keys) if operation != 'INSERT' else 'NULL'
    key_new = snapshot('NEW', keys) if operation != 'DELETE' else 'NULL'
    condition = ''
    if operation == 'UPDATE':
        terms = ['(typeof(OLD.' + ident(c) + ')!=typeof(NEW.' + ident(c) + ') OR OLD.' + ident(c) + ' IS NOT NEW.' + ident(c) + ' COLLATE BINARY)' for c in columns]
        condition = ' WHEN ' + ' OR '.join(terms)
    body = ["INSERT INTO " + ident(LOG) + "(occurred_at,table_name,operation,key_before_json,key_after_json,before_json,after_json) VALUES(strftime('%Y-%m-%dT%H:%M:%fZ','now'),"
            + literal(table) + ',' + literal(operation.lower()) + ',' + ','.join([key_old, key_new, old, new]) + ');']
    for alias, phase in ([('OLD', 'before')] if operation == 'DELETE' else [('NEW', 'after')] if operation == 'INSERT' else [('OLD', 'before'), ('NEW', 'after')]):
        for kind, expression, role in graph_links(table, alias, set(columns)):
            body.append('INSERT OR IGNORE INTO ' + ident(LINKS) + '(change_id,element_type,graph_id,phase,role) '
                        'SELECT last_insert_rowid(),' + literal(kind) + ',' + expression + ',' + literal(phase) + ',' + literal(role)
                        + ' WHERE (' + expression + ') IS NOT NULL;')
    return 'CREATE TRIGGER ' + ident(name) + ' AFTER ' + operation + ' ON ' + ident(table) + condition + ' BEGIN ' + ' '.join(body) + ' END'


def install(database, suspend=False, connection=None):
    """Install released history, optionally inside a validated caller transaction.

    A supplied connection must already own a transaction; its caller alone owns
    commit, rollback and close. A savepoint rolls back installation on failure.
    This lets bound graph commands record atomically.
    """
    path = Path(database)
    if not path.is_absolute() or str(database).startswith(('\\\\', '//')):
        raise ValueError('Journal database must be an absolute local file path')
    path = path.resolve(strict=True)
    owned_connection = connection is None
    db = connection if connection is not None else sqlite3.connect(path.as_uri() + '?mode=rw', uri=True, timeout=5, isolation_level=None)
    if not owned_connection and not db.in_transaction:
        raise ValueError('History installation requires an active caller transaction')
    if not owned_connection:
        main = next((row[2] for row in db.execute('PRAGMA database_list') if row[1] == 'main'), None)
        if not main or Path(main).resolve(strict=True) != path:
            raise ValueError('History connection does not match the requested database')
    original_factory = db.row_factory
    db.row_factory = None
    try:
        if not owned_connection:
            db.execute('SAVEPOINT evomneme_install_history')
        db.execute('SELECT json_object(\'check\',1)')
        if owned_connection:
            db.execute('BEGIN IMMEDIATE')
        existing = {r[0].lower() for r in db.execute("SELECT name FROM sqlite_schema WHERE type='table'")}
        owned = bool(existing & {LOG, LINKS, META})
        if owned and not status(db, False).get('version'):
            raise ValueError('Journal table names already exist without the supported owner/version; no schema was changed')
        if owned:
            required = {LOG: {'id','occurred_at','table_name','operation','key_before_json','key_after_json','before_json','after_json'},
                        LINKS: {'change_id','element_type','graph_id','phase','role'}, META: {'key','value'}}
            for table, fields in required.items():
                if not fields <= {r[1] for r in db.execute('PRAGMA table_info(' + ident(table) + ')')}:
                    raise ValueError('Journal schema is incompatible; existing history was preserved')
        if CALLS in existing:
            if not owned or status(db, False).get('version') != VERSION or not {'id', 'activity_id', 'event_json'} <= {
                    r[1] for r in db.execute('PRAGMA table_info(' + ident(CALLS) + ')')}:
                raise ValueError('Reserved activity table is incompatible; existing tables were preserved')
        if not owned:
            if suspend:
                if owned_connection:
                    db.execute('ROLLBACK')
                else:
                    db.execute('RELEASE evomneme_install_history')
                return {'enabled': False, 'schema_version': db.execute('PRAGMA schema_version').fetchone()[0]}
            db.execute('CREATE TABLE ' + ident(LOG) + '''(
                id INTEGER PRIMARY KEY AUTOINCREMENT, occurred_at TEXT NOT NULL,
                table_name TEXT NOT NULL, operation TEXT NOT NULL CHECK(operation IN ('insert','update','delete')),
                key_before_json TEXT,key_after_json TEXT,before_json TEXT,after_json TEXT)''')
            db.execute('CREATE TABLE ' + ident(LINKS) + '''(
                change_id INTEGER NOT NULL REFERENCES ''' + ident(LOG) + '''(id) ON DELETE CASCADE,
                element_type TEXT NOT NULL,graph_id TEXT NOT NULL,phase TEXT NOT NULL,role TEXT NOT NULL,
                PRIMARY KEY(change_id,element_type,graph_id,phase,role)) WITHOUT ROWID''')
            db.execute('CREATE INDEX evomneme_change_element_lookup ON ' + ident(LINKS) + '(element_type,graph_id,change_id)')
            db.execute('CREATE TABLE ' + ident(META) + '(key TEXT PRIMARY KEY,value TEXT NOT NULL) WITHOUT ROWID')
            db.executemany('INSERT INTO ' + ident(META) + ' VALUES(?,?)',
                           [('owner', OWNER), ('format_version', VERSION), ('started_at', utc_now()), ('enabled', '1')])
            db.execute('CREATE TRIGGER evomneme_change_cleanup AFTER DELETE ON ' + ident(LOG)
                       + ' BEGIN DELETE FROM ' + ident(LINKS) + ' WHERE change_id=OLD.id; END')
        # A nullable opaque ID deliberately has no FK: native SQL can COMMIT or
        # roll back individual portions before the completed call is recorded.
        columns = {r[1] for r in db.execute('PRAGMA table_info(' + ident(LOG) + ')')}
        for column in ('activity_id', 'actor_json'):
            if column not in columns:
                db.execute('ALTER TABLE ' + ident(LOG) + ' ADD COLUMN ' + column + ' TEXT')
        db.execute('CREATE TABLE IF NOT EXISTS ' + ident(CALLS) + '(id INTEGER PRIMARY KEY AUTOINCREMENT,activity_id TEXT NOT NULL UNIQUE,event_json TEXT NOT NULL)')
        db.execute('INSERT OR REPLACE INTO ' + ident(META) + ' VALUES(\'format_version\',?)', (VERSION,))
        managed = {k[6:]: json.loads(v) for k, v in db.execute('SELECT key,value FROM ' + ident(META)) if k.startswith('table:')}
        current, _ = tables(db)
        for table in sorted(set(managed) | set(current)):
            entry = managed.get(table, {})
            names = [PREFIX + hashlib.sha256(table.encode()).hexdigest()[:20] + '_' + op for op in ('insert', 'update', 'delete')]
            present = {r[0] for r in db.execute("SELECT name FROM sqlite_schema WHERE type='trigger'")}
            if not suspend and table in current and entry.get('signature') == current[table]['signature'] and set(names) <= present:
                continue
            for name in names:
                if name in present and name not in entry.get('triggers', []):
                    raise ValueError('Reserved journal trigger name already exists; no trigger was replaced')
                db.execute('DROP TRIGGER IF EXISTS ' + ident(name))
            if suspend or table not in current:
                continue
            info = current[table]['columns']
            columns = [r[1] for r in info]
            keys = [r[1] for r in sorted(info, key=lambda r: r[5]) if r[5]]
            if not keys:
                keys = [alias for alias in ('_rowid_', 'rowid', 'oid') if alias not in columns][:1]
            for operation, name in zip(('INSERT', 'UPDATE', 'DELETE'), names):
                db.execute(trigger_sql(table, operation, columns, keys, name))
            data = {'signature': current[table]['signature'], 'triggers': names,
                    'started_at': entry.get('started_at', utc_now()), 'refreshed_at': utc_now()}
            db.execute('INSERT OR REPLACE INTO ' + ident(META) + ' VALUES(?,?)', ('table:' + table, json.dumps(data)))
        db.execute('INSERT OR REPLACE INTO ' + ident(META) + ' VALUES(\'enabled\',?)', ('0' if suspend else '1',))
        if owned_connection:
            db.execute('COMMIT')
        result = status(db)
        result['schema_version'] = db.execute('PRAGMA schema_version').fetchone()[0]
        if not owned_connection:
            db.execute('RELEASE evomneme_install_history')
        return result
    except BaseException:
        if owned_connection and db.in_transaction:
            db.execute('ROLLBACK')
        elif not owned_connection and db.in_transaction:
            db.execute('ROLLBACK TO evomneme_install_history')
            db.execute('RELEASE evomneme_install_history')
        raise
    finally:
        db.row_factory = original_factory
        if owned_connection:
            db.close()


def read(db, values):
    info = status(db)
    if not info.get('version'):
        return {'journal': info, 'events': [], 'after_id': 0, 'has_older': False, 'has_more': False}
    limit = max(1, min(int(values.get('limit', 100)), 200))
    after, before = values.get('after_id'), values.get('before_id')
    if after is not None and before is not None:
        raise ValueError('Choose after_id or before_id')
    cursor, params, order = '', [], 'DESC'
    if after is not None:
        if type(after) is not int or after < 0:
            raise ValueError('Invalid after_id')
        cursor, params, order = ' WHERE id>?', [after], 'ASC'
    elif before is not None:
        if type(before) is not int or before < 1:
            raise ValueError('Invalid before_id')
        cursor, params = ' WHERE id<?', [before]
    records = db.execute('SELECT id,occurred_at,table_name,operation,key_before_json,key_after_json,before_json,after_json FROM '
                         + ident(LOG) + cursor + ' ORDER BY id ' + order + ' LIMIT ?', params + [limit+1]).fetchall()
    more = len(records) > limit
    records = records[:limit]
    events, used = [], 0
    for number, occurred, table, operation, key_before, key_after, old, new in records:
        links = [{'graph_type': kind, 'graph_id': graph_id, 'phase': phase, 'role': role}
                 for kind, graph_id, phase, role in db.execute('SELECT element_type,graph_id,phase,role FROM '
                    + ident(LINKS) + ' WHERE change_id=? ORDER BY element_type,graph_id,phase', [number])]
        after_ids = {('n:' if r['graph_type']=='nodes' else 'e:') + r['graph_id'] for r in links if r['phase']=='after'}
        removed = [('n:' if r['graph_type']=='nodes' else 'e:') + r['graph_id'] for r in links
                   if r['role']=='entity' and r['phase']=='before' and ('n:' if r['graph_type']=='nodes' else 'e:') + r['graph_id'] not in after_ids]
        affected = {('n:' if r['graph_type']=='nodes' else 'e:') + r['graph_id'] for r in links}
        event = {'source': 'database_change', 'change_id': number,
                       'time': datetime.fromisoformat(occurred.replace('Z','+00:00')).timestamp(),
                       'table': table, 'operation': operation, 'references': links,
                       'changed': sorted(affected - set(removed)), 'removed': sorted(set(removed)),
                       'before': json.loads(old) if old else None, 'after': json.loads(new) if new else None,
                       'key_before': json.loads(key_before) if key_before else None,
                       'key_after': json.loads(key_after) if key_after else None,
                       'ok': True, 'read': [], 'write': [table], 'returned_rows': 0, 'elapsed_ms': 0}
        if info['version'] == VERSION:
            actor = db.execute('SELECT activity_id,actor_json FROM ' + ident(LOG) + ' WHERE id=?', [number]).fetchone()
            if actor[0]:
                event['activity_id'] = actor[0]
                event.update(json.loads(actor[1] or '{}'))
        size = len(json.dumps(event,ensure_ascii=True))
        if events and used + size > 4 * 1024 * 1024:
            more = True
            break
        used += size
        events.append(event)
    if order == 'DESC':
        events.reverse()
    first = events[0]['change_id'] if events else (before or 0)
    older = bool(first and db.execute('SELECT 1 FROM ' + ident(LOG) + ' WHERE id<? LIMIT 1', [first]).fetchone())
    return {'journal': info, 'events': events,
            'after_id': max([after or 0] + [e['change_id'] for e in events]),
            'before_id': first, 'has_older': older, 'has_more': more if after is not None else False}


def read_calls(db, values):
    """Page persisted calls by a database cursor, independent of timestamps."""
    info = status(db, False)
    empty = {'events': [], 'cursors': {}, 'enabled': bool(info.get('activity_enabled')),
             'storage': 'database', 'after_id': values.get('after_id', 0),
             'before_id': 0, 'has_older': False, 'has_more': False}
    after, before = values.get('after_id'), values.get('before_id')
    if after is not None and before is not None:
        raise ValueError('Choose after_id or before_id')
    for name, value, minimum in (('after_id', after, 0), ('before_id', before, 1)):
        if value is not None and (type(value) is not int or value < minimum):
            raise ValueError('Invalid ' + name)
    limit = max(1, min(int(values.get('limit', 100)), 200))
    if not empty['enabled']:
        return empty
    clause, args, order = '', [], 'DESC'
    if after is not None:
        clause, args, order = ' WHERE id>?', [after], 'ASC'
    elif before is not None:
        clause, args = ' WHERE id<?', [before]
    rows = db.execute('SELECT id,event_json FROM ' + ident(CALLS) + clause + ' ORDER BY id ' + order + ' LIMIT ?', args + [limit + 1])
    events, used = [], 0
    more = False
    for index, (number, encoded) in enumerate(rows):
        if index >= limit or (events and used + len(encoded) > 2 * 1024 * 1024):
            more = True
            break
        event = json.loads(encoded)
        event['activity_record_id'] = number
        events.append(event)
        used += len(encoded)
    if order == 'DESC':
        events.reverse()
    first = events[0]['activity_record_id'] if events else (before or 0)
    return {**empty, 'events': events,
            'after_id': max([after or 0] + [e['activity_record_id'] for e in events]),
            'before_id': first,
            'has_older': bool(first and db.execute('SELECT 1 FROM ' + ident(CALLS) + ' WHERE id<? LIMIT 1', [first]).fetchone()),
            'has_more': more if after is not None else False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('install', 'suspend'))
    parser.add_argument('--database', required=True)
    args = parser.parse_args()
    print(json.dumps(install(args.database, args.action == 'suspend'), ensure_ascii=True))


if __name__ == '__main__':
    main()
