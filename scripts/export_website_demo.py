#!/usr/bin/env python3
"""Export the authorized project's whole graph and complete saved history.

python scripts/export_website_demo.py --database <absolute knowledge.sqlite3> \
    --output website/data/demo.json

The source is read-only. Lazy replay and timeline files contain every saved
event; explicit field lists exclude non-graph private/runtime attributes.
"""

import argparse
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import subprocess
import tempfile
from urllib.parse import quote

from evomneme_graph import projection_sql, validate_schema
from evomneme_journal import read as read_changes, read_calls, status as journal_status

REPOSITORY = 'https://github.com/artemrizhov/EvoMneme'
# Independently checked against the public GitHub repository. The analyzed
# scope may be ahead of public history; local object availability is not proof
# of publication and must never produce a broken public source link.
PUBLIC_REVISION = '4b6476c4b76d8ab246c0fae0835346c3c8c7a496'
ROOT = Path(__file__).resolve().parents[1]
# Preserve all graph rows and their meaningful prose. Never copy runtime
# identities or scope worktrees. Public evidence descriptions are preserved;
# only actually sensitive attachment cells are redacted explicitly.
NODE_FIELDS = frozenset(('graph_id', 'label', 'scope_id', 'id', 'kind', 'summary',
                         'confidence', 'validity', 'source_path', 'source_hash',
                         'line_start', 'line_end', 'updated_at', 'evidence_count', 'layer', 'source_table'))
EDGE_FIELDS = frozenset(('graph_id', 'source', 'target', 'scope_id', 'id', 'kind',
                         'summary', 'confidence', 'validity', 'source_path', 'source_hash',
                         'line_start', 'updated_at', 'resolution', 'layer', 'source_table'))
PUBLIC_NODE_COLUMNS = ('scope_id', 'id', 'kind', 'title', 'summary', 'confidence',
                       'validity', 'source_path', 'source_hash', 'line_start', 'line_end', 'layer', 'updated_at')
PUBLIC_EDGE_COLUMNS = ('scope_id', 'id', 'source_id', 'target_id', 'kind', 'confidence',
                       'validity', 'source_path', 'source_hash', 'layer', 'resolution',
                       'line_start', 'line_end', 'summary', 'updated_at')
JOURNAL_FIELDS = ('enabled', 'version', 'activity_enabled', 'started_at', 'tracked_tables',
                  'untracked_tables', 'unsupported_tables', 'error')
CHANGE_FIELDS = ('source', 'change_id', 'time', 'table', 'operation', 'references',
                 'changed', 'removed', 'ok', 'read', 'write', 'returned_rows', 'elapsed_ms', 'activity_id')
CALL_FIELDS = ('source', 'activity_id', 'activity_record_id', 'time', 'ok', 'elapsed_ms',
               'completed', 'rolled_back', 'durable_effects_possible', 'read', 'write',
               'references', 'returned_rows', 'has_more')
CHANGE_REFERENCE_FIELDS = ('graph_type', 'graph_id', 'phase', 'role')
CALL_REFERENCE_FIELDS = ('table', 'scope_id', 'id')
ATTACHMENT_COLUMNS = {
    'evidence': ('scope_id', 'id', 'node_id', 'edge_id', 'description', 'source_path', 'source_hash', 'validity', 'updated_at'),
    'symbol_details': ('scope_id', 'node_id', 'qualified_name', 'signature', 'language'),
    'file_details': ('scope_id', 'node_id', 'declaration_status', 'relationship_status',
                     'inspected_hash', 'exclusion_reason', 'remaining_work'),
}
HISTORY_COLUMNS = {
    'nodes': PUBLIC_NODE_COLUMNS, 'edges': PUBLIC_EDGE_COLUMNS,
    'scopes': ('id', 'revision'), 'metadata': ('key',),
    **ATTACHMENT_COLUMNS,
    'history': ('id', 'happened_at', 'action'),
}
PRIVATE = re.compile(
    r'(?i)(?:\b[a-z]:[\\/]|/Users/|/home/|\\\\|'
    r'\b(?:sk-[a-z0-9_-]{12,}|AKIA[A-Z0-9]{16})\b|'
    r'-----BEGIN [A-Z ]*PRIVATE KEY|'
    r'\b(?:api[_-]?key|password|secret|access[_-]?token)\s*[:=]\s*[\"\x27]?\S+)'
)


def public_value(value):
    if isinstance(value, dict):
        return {key: public_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [public_value(item) for item in value]
    if value is not None and (not isinstance(value, (str, int, float)) or
                              PRIVATE.search(str(value))):
        raise ValueError('Potential private content in retained public fields')
    return value


def retained(row, columns):
    return {key: public_value(value) for key, value in row.items() if key in columns}


def public_event(row, fields, reference_fields):
    result = retained(row, tuple(key for key in fields if key != 'references'))
    if 'references' in row:
        result['references'] = [retained(reference, reference_fields) for reference in row['references']]
    return result


def safe_path(value):
    return (isinstance(value, str) and bool(value) and '\\' not in value and
            not value.startswith('/') and ':' not in value and
            all(part not in ('', '.', '..') for part in value.split('/')))


def git_sources(repository_root, revisions):
    """Only available scoped Git blobs may establish public source links."""
    result, blob_hashes = {}, {}
    revisions = sorted({r for r in revisions if isinstance(r, str) and re.fullmatch('[a-f0-9]{40}', r)})
    if not revisions:
        return result
    known = subprocess.run(['git', 'cat-file', '--batch-check=%(objectname) %(objecttype)'],
                           input=''.join(r + '\n' for r in revisions), text=True,
                           capture_output=True, check=True, cwd=repository_root)
    for revision, answer in zip(revisions, known.stdout.splitlines()):
        if not answer.endswith(' commit'):
            continue
        tree = subprocess.check_output(['git', 'ls-tree', '-r', '-z', '--full-tree', revision], cwd=repository_root)
        for entry in tree.split(b'\0'):
            if not entry:
                continue
            header, encoded_path = entry.split(b'\t', 1)
            _, kind, oid = header.decode('ascii').split()
            path = encoded_path.decode('utf-8')
            if kind != 'blob' or not safe_path(path):
                continue
            if oid not in blob_hashes:
                blob = subprocess.check_output(['git', 'cat-file', 'blob', oid], cwd=repository_root)
                blob_hashes[oid] = hashlib.sha256(blob).hexdigest()
            result[(revision, path)] = blob_hashes[oid]
    return result


def source_url(row, revisions, sources, public_revision=PUBLIC_REVISION):
    path, revision = row.get('source_path'), public_revision
    expected_hash = sources.get((revision, path))
    if row.get('scope_id') not in revisions or not safe_path(path) or not expected_hash or expected_hash != row.get('source_hash'):
        return None
    url = REPOSITORY + '/blob/' + revision + '/' + quote(path, safe='/')
    start, end = row.get('line_start'), row.get('line_end')
    if isinstance(start, int) and start > 0:
        url += '#L' + str(start)
        if isinstance(end, int) and end >= start:
            url += '-L' + str(end)
    return url


def annotate(row, revisions, sources, public_revision=PUBLIC_REVISION):
    url = source_url(row, revisions, sources, public_revision)
    if url:
        row['source_url'] = url
    return row


def public_snapshot(snapshot, table):
    if snapshot is None:
        return None
    result = {}
    for key in HISTORY_COLUMNS.get(table, ()):
        if key not in snapshot:
            continue
        try:
            result[key] = retained(snapshot[key], ('type', 'value', 'length', 'truncated'))
        except ValueError:
            if table not in ATTACHMENT_COLUMNS:
                raise
            # Retain the event and all other cells; only an actually sensitive
            # attachment attribute is omitted. Graph snapshots never lose cells.
    return result


def read_all(reader, source):
    events, cursor = [], 0
    while True:
        page = reader(source, {'after_id': cursor, 'limit': 200})
        events.extend(page['events'])
        if not page.get('has_more'):
            return events
        if page['after_id'] <= cursor:
            raise ValueError('History cursor did not advance; no truncated export was written')
        cursor = page['after_id']


def initial_history(timeline):
    """Exact latest native envelopes, bounded to 100 calls and 100 changes."""
    result = {}
    for route, key, field in (('events', 'calls', 'activity_record_id'), ('changes', 'changes', 'change_id')):
        all_events = timeline[key]
        events = all_events[-100:]
        page = {'events': events, 'after_id': events[-1][field] if events else 0,
                'before_id': events[0][field] if events else 0,
                'has_older': len(all_events) > len(events), 'has_more': False}
        if route == 'events':
            page.update(cursors={}, enabled=bool(timeline['journal'].get('activity_enabled')), storage='database')
        else:
            page['journal'] = timeline['journal']
        result[route] = page
    return result


def export_publication(database, repository_root=ROOT, expected_identity=None, public_revision=PUBLIC_REVISION):
    """Return the whole graph, replay and timeline from one read-only snapshot."""
    path = Path(database).resolve(strict=True)
    source = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)
    source.row_factory = sqlite3.Row
    memory = sqlite3.connect(':memory:')
    memory.row_factory = sqlite3.Row
    memory.create_function('viewer_fingerprint', -1, lambda *args: '', deterministic=True)
    try:
        source.execute('PRAGMA query_only=ON')
        source.execute('BEGIN')
        validate_schema(source)
        if not re.fullmatch('[a-f0-9]{40}', public_revision):
            raise ValueError('Public revision must be a complete 40-character lowercase Git SHA')
        if expected_identity is None:
            receipt = json.loads((Path(repository_root) / '.evomneme/connection.json').read_text(encoding='utf-8-sig'))
            expected_identity = receipt['project_identity']
        identity = source.execute("SELECT value FROM metadata WHERE key='project_identity'").fetchone()
        if not expected_identity or not identity or identity[0] != expected_identity:
            raise ValueError('Source database does not match the verified project identity')
        scopes = [retained(dict(r), ('id', 'revision')) for r in source.execute('SELECT id,revision FROM scopes ORDER BY id')]
        revisions = {r['id']: r['revision'] for r in scopes}
        sources = git_sources(repository_root, (public_revision,))
        raw = {}
        for table, columns in (('nodes', PUBLIC_NODE_COLUMNS), ('edges', PUBLIC_EDGE_COLUMNS)):
            raw[table] = [retained(dict(r), columns) for r in source.execute(
                'SELECT ' + ','.join(columns) + ' FROM ' + table + ' ORDER BY scope_id,id')]
        attachments, redactions = {}, {}
        for table, columns in ATTACHMENT_COLUMNS.items():
            attachments[table] = []
            for original in source.execute('SELECT ' + ','.join(columns) + ' FROM ' + table +
                                           ' ORDER BY scope_id,' + ('id' if table == 'evidence' else 'node_id')):
                row = {}
                for key, value in dict(original).items():
                    try:
                        row[key] = public_value(value)
                    except ValueError:
                        field = table + '.' + key
                        redactions[field] = redactions.get(field, 0) + 1
                attachments[table].append(annotate(row, revisions, sources, public_revision))
        evidence = [retained(dict(r), ('scope_id', 'node_id', 'validity')) for r in source.execute(
            'SELECT scope_id,node_id,validity FROM evidence WHERE node_id IS NOT NULL ORDER BY scope_id,id')]
        memory.executescript((ROOT / 'schema.sql').read_text(encoding='utf-8'))
        memory.executemany('INSERT INTO scopes VALUES(?,?,?,?,?,?)',
                           [(r['id'], '', '', r['revision'], '', '') for r in scopes])
        for table, columns in (('nodes', PUBLIC_NODE_COLUMNS), ('edges', PUBLIC_EDGE_COLUMNS)):
            memory.executemany('INSERT INTO ' + table + '(' + ','.join(columns) + ') VALUES (' +
                               ','.join('?' for _ in columns) + ')', [tuple(r[c] for c in columns) for r in raw[table]])
        memory.executemany('INSERT INTO evidence(scope_id,id,node_id,description,validity,updated_at) VALUES(?,?,?,?,?,?)',
                           [(r['scope_id'], 'public-evidence-' + str(i), r['node_id'], '', r['validity'], '')
                            for i, r in enumerate(evidence)])
        mapping = projection_sql(memory)
        result = {}
        for name, allowed in (('nodes', NODE_FIELDS), ('edges', EDGE_FIELDS)):
            result[name] = []
            for projected in memory.execute(mapping[name]):
                row = annotate(retained(dict(projected), allowed), revisions, sources, public_revision)
                result[name].append(row)
            result[name].sort(key=lambda r: r['graph_id'])
        result.update(attachments)
        ids = {row['graph_id'] for row in result['nodes']}
        if len(ids) != len(result['nodes']) or len({e['graph_id'] for e in result['edges']}) != len(result['edges']):
            raise ValueError('Graph identities are not unique')
        if any(e['source'] not in ids or e['target'] not in ids for e in result['edges']):
            raise ValueError('Source graph has dangling endpoints; no partial graph was published')
        # The shared journal reader serializes PRAGMA rows and expects SQLite's
        # native tuple factory, unlike the dictionary reads above.
        source.row_factory = None
        journal = retained(journal_status(source), JOURNAL_FIELDS)
        timeline = {'journal': journal, 'changes': [], 'calls': []}
        replay = {'journal': journal, 'nodes': [], 'edges': [], 'events': []}
        for table in ('nodes', 'edges'):
            replay[table] = [annotate(dict(r), revisions, sources, public_revision) for r in raw[table]]
        for original in read_all(read_changes, source):
            event = public_event(original, CHANGE_FIELDS, CHANGE_REFERENCE_FIELDS)
            for field in ('before', 'after', 'key_before', 'key_after'):
                event[field] = public_snapshot(original.get(field), original['table'])
            timeline['changes'].append(event)
        if journal.get('version'):
            for number, occurred, table, old, new in source.execute(
                    "SELECT id,occurred_at,table_name,before_json,after_json FROM evomneme_change_log WHERE table_name IN ('nodes','edges') ORDER BY id"):
                replay['events'].append({'change_id': number, 'time': public_value(occurred), 'table': table,
                                         'before': public_snapshot(json.loads(old) if old else None, table),
                                         'after': public_snapshot(json.loads(new) if new else None, table)})
        timeline['calls'] = [public_event(event, CALL_FIELDS, CALL_REFERENCE_FIELDS)
                             for event in read_all(read_calls, source)]
        content = json.dumps(result, sort_keys=True, ensure_ascii=False).encode()
        result['metadata'] = {
            'schema_version': 1, 'repository': REPOSITORY,
            'revision': scopes[0]['revision'] if len(scopes) == 1 else None, 'scopes': scopes,
            'public_revision': public_revision,
            'title': 'EvoMneme: the complete saved project graph',
            'source_schema_version': 3,
            'provenance': 'Every stored node, edge and layer from the authorized EvoMneme project database. Source summaries, confidence and validity are preserved; completeness of code understanding is not implied.',
            'privacy': 'Graph and provenance attachments are public by user authorization. Runtime caller identities, host locations, credential-bearing attachment attributes and SQLite are excluded.',
            'redacted_attachment_fields': redactions,
            'limitations': 'Links exist only when a stored file hash matches the independently verified public Git revision; the analyzed scope may be ahead of it. History starts at the saved journal boundary; earlier changes are not invented.',
            'counts': {'nodes': len(result['nodes']), 'edges': len(result['edges']),
                       'knowledge': sum(n['layer'] == 'knowledge' for n in result['nodes']),
                       'code': sum(n['layer'] == 'code' for n in result['nodes']),
                       'source_evidence': len(attachments['evidence']), 'node_evidence': len(evidence),
                       'verified_node_links': sum('source_url' in n for n in result['nodes']),
                       'verified_edge_links': sum('source_url' in e for e in result['edges'])},
            'content_sha256': hashlib.sha256(content).hexdigest(),
            'history': {'replay': 'replay.json', 'timeline': 'history.json', 'journal': journal,
                        'initial': initial_history(timeline),
                        'counts': {'replay_changes': len(replay['events']), 'changes': len(timeline['changes']),
                                   'calls': len(timeline['calls'])}},
        }
        return {'graph': result, 'replay': replay, 'history': timeline}
    finally:
        source.close()
        memory.close()


def export_snapshot(database, repository_root=ROOT, expected_identity=None, public_revision=PUBLIC_REVISION):
    return export_publication(database, repository_root, expected_identity, public_revision)['graph']


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode('utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, required=True, help='Explicit authorized SQLite source; opened read-only and matched against the local project receipt')
    parser.add_argument('--output', type=Path, required=True, help='Graph JSON destination; replay.json and history.json are written beside it')
    parser.add_argument('--public-revision', help='Complete lowercase 40-character SHA of a commit the caller has verified is publicly published; must exist locally. Default: ' + PUBLIC_REVISION)
    args = parser.parse_args()
    outputs = (args.output, args.output.with_name('replay.json'), args.output.with_name('history.json'))
    if len({p.resolve() for p in outputs}) != 3 or any(p.resolve() == args.database.resolve() for p in outputs):
        parser.error('graph, replay, timeline and source must be distinct files')
    revision = args.public_revision or PUBLIC_REVISION
    if not re.fullmatch('[a-f0-9]{40}', revision):
        parser.error('--public-revision requires a complete lowercase 40-character Git SHA')
    if args.public_revision:
        known = subprocess.run(['git', 'cat-file', '--batch-check=%(objectname) %(objecttype)'],
                               input=revision + '\n', text=True, capture_output=True, check=True, cwd=ROOT)
        if not known.stdout.strip().endswith(' commit'):
            parser.error('--public-revision does not identify an available local commit; verify publication and fetch it using the configured Git integration')
    publication = export_publication(args.database, public_revision=revision)
    payloads = [(path, encoded(publication[key])) for key, path in
                (('replay', outputs[1]), ('history', outputs[2]), ('graph', outputs[0]))]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    staged = []
    try:
        for path, payload in payloads:
            with tempfile.NamedTemporaryFile(dir=path.parent, prefix='.' + path.name + '.', delete=False) as stream:
                staged.append((Path(stream.name), path))
                stream.write(payload)
        # Complete every file before replacing any published output; graph last.
        # The three renames are not a filesystem-wide transaction.
        for temporary, path in staged:
            temporary.replace(path)
    finally:
        for temporary, _ in staged:
            temporary.unlink(missing_ok=True)
    print(json.dumps({'graph': publication['graph']['metadata']['counts'],
                      'history': publication['graph']['metadata']['history']['counts']}))


if __name__ == '__main__':
    main()
