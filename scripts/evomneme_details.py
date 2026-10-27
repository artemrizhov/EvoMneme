"""Scoped schema-v3 detail records, sharing graph mutation transactions."""
import argparse
import json
import sqlite3
import time
import uuid

from evomneme import empty_result
from evomneme_journal import CALLS, LOG, ident
from evomneme_navigate import fields
from evomneme_trace import build_event
from evomneme_write_options import configure, snapshot

COLUMNS = {
    'symbol-details': ('scope_id', 'node_id', 'qualified_name', 'signature', 'language'),
    'file-details': ('scope_id', 'node_id', 'declaration_status', 'relationship_status',
                     'inspected_hash', 'exclusion_reason', 'remaining_work'),
}
NULLABLE = {'signature', 'language', 'inspected_hash', 'exclusion_reason', 'remaining_work'}
STATUSES = ('pending', 'partial', 'verified', 'stale', 'blocked', 'excluded')


def configure_parser(subparsers):
    from evomneme_mutate import UniqueValue
    for action in ('add', 'update', 'delete'):
        kinds = next(item for item in subparsers.choices[action]._actions if isinstance(item, argparse._SubParsersAction))
        for entity, columns in COLUMNS.items():
            parser = kinds.add_parser(entity, description='Maintain one schema-v3 detail row keyed by scope_id,node_id; no id or updated_at column.')
            parser.add_argument('selector', metavar='NODE', help='Exact node ID/title, root, or qualified @scope/id; historical nodes supported.')
            if action != 'delete':
                for key in columns[2:]:
                    options = dict(default=argparse.SUPPRESS, action=UniqueValue,
                                   help='Stored ' + key + '; omitted updates retain value.')
                    if key.endswith('_status'):
                        options['choices'] = STATUSES
                    if key == 'qualified_name' and action == 'add':
                        options['required'] = True
                    parser.add_argument('--' + key, **options)
                if action == 'update':
                    parser.add_argument('--clear', action='append', default=[], choices=sorted(NULLABLE.intersection(columns)))
            configure(parser, source=True)
            parser.set_defaults(mutation=True)


def run(connection, args, session=None, activity_context=None, compact=False,
        expect_updated_at=None, verify_source=False):
    from evomneme_mutate import MutationSession, reject_external_dependencies, resolve_node, verify_delete_history
    started = time.monotonic()
    owns = session is None
    active = session if session is not None else MutationSession(connection)
    if active.connection != connection:
        raise ValueError('Shared mutation session belongs to another binding')
    db, executor = active.db, active.executor
    entity, action = args.entity, args.command
    table, columns = entity.replace('-', '_'), COLUMNS[entity]
    try:
        active.check_time()
        node = resolve_node(db, connection, args.selector)
        identity = (connection.scope, node['id'])
        before = db.execute('SELECT * FROM ' + table + ' WHERE scope_id=? AND node_id=?', identity).fetchone()
        if action != 'add' and before is None:
            raise ValueError('Missing same-scope ' + table + ' for node: ' + node['id'])
        if action == 'add' and before is not None:
            raise ValueError('Detail row already exists')
        patch = {key: getattr(args, key) for key in columns[2:] if hasattr(args, key)}
        clear = getattr(args, 'clear', ())
        if len(set(clear)) != len(clear) or set(clear).intersection(patch):
            raise ValueError('Repeated clear or field both set and cleared')
        patch.update({key: None for key in clear})
        row = (dict(before) if before is not None else
               {key: ('pending' if key.endswith('_status') else None) for key in columns})
        row.update(scope_id=connection.scope, node_id=node['id'])
        row.update(patch)
        if verify_source:
            locator = dict(node)
            if entity == 'file-details' and row.get('inspected_hash') is not None:
                locator['source_hash'] = row['inspected_hash']
            active.capture_source(node, locator=locator)
        if action != 'delete':
            if entity == 'symbol-details' and (not isinstance(row['qualified_name'], str) or not row['qualified_name'].strip()):
                raise ValueError('qualified_name must be nonempty text')
            for key in ('declaration_status', 'relationship_status'):
                if key in row and row[key] not in STATUSES:
                    raise ValueError('Invalid ' + key)
        changed = [key for key in columns[2:] if before is None or before[key] != row[key]]
        if action == 'update' and not changed:
            raise ValueError('Update has no changed fields')
        plan = {name: [] for name in ('nodes', 'edges', 'evidence', 'symbol_details', 'file_details')} if action == 'delete' else None
        if plan is not None:
            plan[table] = [dict(before)]
        if plan:
            reject_external_dependencies(db, plan)
        history = active.ensure_history()
        event_id = uuid.uuid4().hex
        event = build_event(empty_result(), [], 0, activity_context, executor.session_id, executor.path,
                            {'name': 'EvoMneme graph CLI'}, event_id)
        history.scope(event)
        if action == 'add':
            db.execute('INSERT INTO ' + table + '(' + ','.join(columns) + ') VALUES(' + ','.join('?' for _ in columns) + ')', [row[key] for key in columns])
        elif action == 'update':
            db.execute('UPDATE ' + table + ' SET ' + ','.join(key + '=?' for key in changed) + ' WHERE scope_id=? AND node_id=?', [row[key] for key in changed] + list(identity))
        else:
            db.execute('DELETE FROM ' + table + ' WHERE scope_id=? AND node_id=?', identity)
        actual = db.execute('SELECT * FROM ' + table + ' WHERE scope_id=? AND node_id=?', identity).fetchone()
        if action == 'delete' and actual is not None:
            raise ValueError('Detail row remains after deletion')
        if action != 'delete' and (actual is None or dict(actual) != row):
            raise ValueError('Stored detail row differs from validated values')
        response = empty_result()
        response.update(completed_statements=1, autocommit_effects_possible=True)
        event = build_event(response, [{'read': {table}, 'write': {table}}], (time.monotonic() - started) * 1000,
                            activity_context, executor.session_id, executor.path, {'name': 'EvoMneme graph CLI'}, event_id)
        event.update(source='graph-cli', command=action, entity=entity, scope_id=connection.scope, node_id=node['id'], changed_fields=changed)
        db.execute('INSERT INTO ' + ident(CALLS) + '(activity_id,event_json) VALUES(?,?)',
                   (event_id, json.dumps(event, ensure_ascii=True, separators=(',', ':'))))
        if plan:
            verify_delete_history(db, plan, event_id)
        else:
            changes = db.execute('SELECT table_name,operation,key_after_json FROM ' + ident(LOG)
                                 + ' WHERE activity_id=? AND table_name IN (?,?,?,?,?)',
                                 (event_id, 'nodes', 'edges', 'evidence', 'symbol_details', 'file_details')).fetchall()
            if len(changes) != 1 or changes[0]['table_name'] != table or changes[0]['operation'] != ('insert' if action == 'add' else 'update'):
                raise ValueError('Unexpected graph writes during detail mutation; command rolled back')
            key = json.loads(changes[0]['key_after_json'])
            for column, value in zip(('scope_id', 'node_id'), identity):
                field = key.get(column, {})
                if field.get('type') != 'text' or field.get('truncated') or field.get('value') != value:
                    raise ValueError('Detail identity differs from validated row; command rolled back')
        rendered = ({'scope_id': connection.scope, 'node_id': node['id']} if compact or action == 'delete' else row)
        output = '\n'.join(fields(dict(action=action, entity=entity, changed_fields=', '.join(changed), **rendered))) + '\n'
        for warning in active.warnings:
            output += '\n' + '\n'.join(fields(dict(warning=warning))) + '\n'
        if len(output.encode('utf-8')) > 65536:
            raise ValueError('Mutation output exceeds 65536 UTF-8 bytes; command rolled back')
        active.check_time()
        if owns:
            active.commit()
        return output
    except sqlite3.Error as exc:
        raise ValueError('Cannot maintain bound details: ' + str(exc)) from exc
    finally:
        if owns:
            active.close()
