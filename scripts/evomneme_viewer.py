#!/usr/bin/env python3
"""Loopback Cytoscape explorer; read-only unless row-history recording is requested."""

import argparse
from contextlib import contextmanager
import gzip
import hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from pathlib import Path
import secrets
import sqlite3
import time
import threading
from urllib.parse import urlsplit

from evomneme import cell, json_bytes
from evomneme_graph import projection_sql, validate_schema
from evomneme_journal import install as install_journal, read as read_changes, status as journal_status

ASSETS = Path(__file__).parent / 'viewer'
MAX_ROWS = 2000
MAX_RESPONSE = 8 * 1024 * 1024
MAX_GRAPH_RESPONSE = 128 * 1024 * 1024
MAX_GRAPH_NODES = 100000
MAX_GRAPH_EDGES = 200000
QUERY_SECONDS = 5
GRAPH_SECONDS = 30
OVERVIEW_NODE_FIELDS = {'graph_id', 'label', 'scope_id', 'id', 'kind', 'confidence', 'validity', 'source_path', 'source_table', 'evidence_count', 'layer', 'fingerprint'}
OVERVIEW_EDGE_FIELDS = {'graph_id', 'source', 'target', 'scope_id', 'id', 'kind', 'confidence', 'validity', 'resolution', 'source_table', 'layer', 'fingerprint'}


def read_authorizer(action, first, second, database, trigger):
    if action in {sqlite3.SQLITE_ATTACH, sqlite3.SQLITE_DETACH}:
        return sqlite3.SQLITE_DENY
    if action == sqlite3.SQLITE_FUNCTION and (second or '').lower() in {'load_extension', 'readfile', 'writefile'}:
        return sqlite3.SQLITE_DENY
    if action == sqlite3.SQLITE_PRAGMA:
        if (first or '').lower() not in {'table_info', 'table_list', 'foreign_key_list', 'page_count', 'page_size', 'freelist_count', 'query_only', 'user_version', 'schema_version'}:
            return sqlite3.SQLITE_DENY
        if (first or '').lower() in {'query_only', 'user_version', 'schema_version'} and second is not None:
            return sqlite3.SQLITE_DENY
    return sqlite3.SQLITE_OK


def quote(name):
    return '"' + name.replace('"', '""') + '"'


def bounded_cell(value):
    if isinstance(value, (str, bytes)) and len(value) > 16384:
        return {'preview': cell(value[:16384]), 'truncated': True, 'length': len(value)}
    return cell(value)


class Explorer:
    def __init__(self, database, mapping=None, trace_directory=None, record_changes=False):
        requested = Path(database)
        if not requested.is_absolute() or str(database).startswith(('\\\\', '//')):
            raise ValueError('database must be an absolute local file path')
        self.requested = requested
        self.path = requested.resolve(strict=True)
        if not self.path.is_file():
            raise ValueError('database must be a regular file')
        self.identity = self.file_identity()
        self.mapping = mapping
        if mapping and (set(mapping) != {'nodes', 'edges'} or
                        any(not isinstance(v, str) for v in mapping.values())):
            raise ValueError('Mapping requires nodes and edges SQL strings')
        self.trace_directory = Path(trace_directory) if trace_directory else None
        self.watch = None
        self.watch_lock = threading.Lock()
        self.watch_token = secrets.token_hex(8)
        self.snapshot_key = None
        self.manage_changes = record_changes
        self.journal_schema_version = None
        with self.connect():
            pass  # Validate before --record-changes can modify the selected store.
        if record_changes:
            self.journal_schema_version = install_journal(self.path)['schema_version']

    def maintain_journal(self):
        if not self.manage_changes:
            return
        with self.connect() as db:
            version = db.execute('PRAGMA schema_version').fetchone()[0]
        if version != self.journal_schema_version:
            self.journal_schema_version = install_journal(self.path)['schema_version']

    def changes(self, values):
        self.maintain_journal()
        with self.connect() as db:
            return read_changes(db, values)

    def close(self):
        with self.watch_lock:
            if self.watch:
                self.watch.close()
                self.watch = None

    def revision(self):
        if self.requested.resolve(strict=True) != self.path or self.file_identity() != self.identity:
            raise ValueError('Database replaced or retargeted; restart the viewer')
        with self.watch_lock:
            if self.watch is None:
                self.watch = sqlite3.connect(self.path.as_uri() + '?mode=ro', uri=True, check_same_thread=False, timeout=1)
                self.watch.execute('PRAGMA query_only=ON')
            return self.watch_token + ':' + str(self.watch.execute('PRAGMA data_version').fetchone()[0])

    def file_identity(self):
        info = self.path.stat()
        return info.st_dev, info.st_ino

    @contextmanager
    def connect(self, seconds=None):
        if self.requested.resolve(strict=True) != self.path or self.file_identity() != self.identity:
            raise ValueError('Database replaced or retargeted; restart the viewer')
        db = sqlite3.connect(self.path.as_uri() + '?mode=ro', uri=True, timeout=1)
        seconds = QUERY_SECONDS if seconds is None else seconds
        deadline = time.monotonic() + seconds
        try:
            db.execute('PRAGMA query_only=ON')
            db.execute('PRAGMA temp_store=MEMORY')
            db.enable_load_extension(False)
            db.create_function('viewer_fingerprint', -1,
                               lambda *values: hashlib.sha256(json_bytes([cell(v) for v in values])).hexdigest(),
                               deterministic=True)
            db.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, 8 * 1024 * 1024)
            db.setlimit(sqlite3.SQLITE_LIMIT_SQL_LENGTH, 65536)
            db.set_progress_handler(lambda: time.monotonic() > deadline, 1000)
            db.execute('BEGIN')
            db.set_authorizer(read_authorizer)
            validate_schema(db)
            yield db
        except sqlite3.OperationalError as exc:
            if getattr(exc, 'sqlite_errorcode', None) == sqlite3.SQLITE_INTERRUPT and time.monotonic() >= deadline:
                raise ValueError(f'Read exceeded the {seconds:g}-second time limit. Narrow graph layers/filters or use a grouped view.') from exc
            raise
        finally:
            db.close()

    def rows(self, db, sql, params=(), limit=MAX_ROWS, max_bytes=MAX_RESPONSE):
        cursor = db.execute(sql, params)
        columns = [c[0] for c in cursor.description or []]
        if len(set(columns)) != len(columns):
            raise ValueError('Use unique column aliases')
        rows, used = [], 0
        for row in cursor:
            if len(rows) >= limit:
                return rows, True
            encoded = {c: bounded_cell(v) for c, v in zip(columns, row)}
            used += len(json_bytes(encoded))
            if used > max_bytes:
                raise ValueError('Graph output exceeds its byte budget; narrow layers, filters, or projections')
            rows.append(encoded)
        return rows, False

    def projections(self, db):
        if self.mapping:
            mapping = dict(self.mapping)
            for key in ('nodes', 'edges'):
                columns = [c[0] for c in db.execute('SELECT * FROM (' + mapping[key] + ') LIMIT 0').description]
                if 'layer' not in columns:
                    mapping[key] = "SELECT *, 'custom' AS layer FROM (" + mapping[key] + ')'
                else:
                    fields = ["CAST(coalesce(layer,'custom') AS TEXT) AS layer" if c == 'layer' else quote(c) for c in columns]
                    mapping[key] = 'SELECT ' + ','.join(fields) + ' FROM (' + mapping[key] + ')'
            return mapping
        if db.execute("SELECT 1 FROM temp.sqlite_schema WHERE name='viewer_nodes'").fetchone():
            return {'nodes': 'SELECT * FROM temp.viewer_nodes', 'edges': 'SELECT * FROM temp.viewer_edges'}
        mapping = projection_sql(db)
        if mapping is None:
            return None
        # Only our fixed built-in projections may create request-local, in-memory
        # workspace. The main database remains mode=ro; caller SQL stays query_only.
        db.set_authorizer(None)
        try:
            db.execute('PRAGMA query_only=OFF')
            db.execute('CREATE TEMP TABLE viewer_nodes AS ' + mapping['nodes'])
            db.execute('CREATE UNIQUE INDEX temp.viewer_node_id ON viewer_nodes(graph_id)')
            db.execute('CREATE TEMP TABLE viewer_edges AS ' + mapping['edges'])
            db.execute('CREATE UNIQUE INDEX temp.viewer_edge_id ON viewer_edges(graph_id)')
            db.execute('CREATE INDEX temp.viewer_edge_source ON viewer_edges(source)')
            db.execute('CREATE INDEX temp.viewer_edge_target ON viewer_edges(target)')
        finally:
            db.execute('PRAGMA query_only=ON')
            db.set_authorizer(read_authorizer)
        return {'nodes': 'SELECT * FROM temp.viewer_nodes', 'edges': 'SELECT * FROM temp.viewer_edges',
                'warnings': mapping['warnings']}

    def schema(self, db):
        tables = []
        definitions = db.execute("SELECT name,sql FROM sqlite_schema WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name").fetchmany(201)
        if len(definitions) > 200:
            raise ValueError('Schema exceeds 200 tables; use a reduced database copy')
        for name, sql in definitions:
            tables.append({'name': name, 'sql': sql,
                           'count': db.execute('SELECT count(*) FROM ' + quote(name)).fetchone()[0],
                           'columns': self.rows(db, 'PRAGMA table_info(' + quote(name) + ')')[0],
                           'foreign_keys': self.rows(db, 'PRAGMA foreign_key_list(' + quote(name) + ')')[0]})
        return tables

    @staticmethod
    def filters(sql, values, columns):
        terms, params = [], []
        excluded = values.get('excluded_layers', [])
        if not isinstance(excluded, list) or len(excluded) > 200 or any(not isinstance(v, str) or len(v) > 200 for v in excluded):
            raise ValueError('excluded_layers requires at most 200 layer names')
        if excluded and 'layer' in columns:
            terms.append('layer NOT IN (' + ','.join('?' for _ in excluded) + ')')
            params.extend(excluded)
        if values.get('null_field') in {'scope_id', 'kind', 'validity', 'confidence', 'source_path'} and values['null_field'] in columns:
            terms.append(quote(values['null_field']) + ' IS NULL')
        for field in ('scope_id', 'kind', 'validity', 'confidence', 'source_path'):
            if values.get(field) and field in columns:
                terms.append(quote(field) + '=?')
                params.append(values[field])
        if values.get('search'):
            searchable = [c for c in ('label', 'graph_id', 'summary', 'source_path') if c in columns]
            terms.append('(' + ' OR '.join('CAST(' + quote(c) + ' AS TEXT) LIKE ?' for c in searchable) + ')')
            params.extend(['%' + values['search'] + '%'] * len(searchable))
        return 'SELECT * FROM (' + sql + ') ' + ('WHERE ' + ' AND '.join(terms) if terms else ''), params

    def snapshot(self, values):
        started = time.monotonic()
        self.maintain_journal()
        whole = values.get('whole_graph') is True
        revision = self.revision() if whole else None
        snapshot_key = json.dumps({k: v for k, v in values.items() if k != 'revision'}, sort_keys=True)
        if whole and values.get('revision') == revision and self.snapshot_key == snapshot_key:
            return {'unchanged': True, 'revision': revision}
        limit = MAX_GRAPH_NODES if whole else max(1, min(int(values.get('limit', 500)), MAX_ROWS))
        offset = 0 if whole else max(0, min(int(values.get('offset', 0)), 100000000))
        with self.connect(GRAPH_SECONDS) as db:
            tables = self.schema(db)
            mapping = self.projections(db)
            result = {'tables': tables, 'bytes': db.execute('PRAGMA page_count').fetchone()[0] * db.execute('PRAGMA page_size').fetchone()[0],
                      'nodes': [], 'edges': [], 'graph_available': bool(mapping), 'facets': {}, 'edge_facets': {}, 'totals': {}, 'offset': offset,
                      'node_has_more': False, 'edge_has_more': False, 'whole_graph': whole,
                      'revision': revision, 'layers': [], 'journal': journal_status(db, False)}
            if mapping:
                columns = [c[0] for c in db.execute('SELECT * FROM (' + mapping['nodes'] + ') LIMIT 0').description]
                edge_columns = [c[0] for c in db.execute('SELECT * FROM (' + mapping['edges'] + ') LIMIT 0').description]
                if not {'graph_id', 'label'} <= set(columns) or not {'graph_id', 'source', 'target'} <= set(edge_columns):
                    raise ValueError('Projection columns: nodes need graph_id,label; edges need graph_id,source,target')
                for key in ('nodes', 'edges'):
                    result['totals'][key] = db.execute('SELECT count(*) FROM (' + mapping[key] + ')').fetchone()[0]
                catalog = {}
                for key in ('nodes', 'edges'):
                    for layer, count in db.execute('SELECT layer,count(*) FROM (' + mapping[key] + ') GROUP BY layer'):
                        item = catalog.setdefault(layer, {'id': layer, 'nodes': 0, 'edges': 0})
                        item[key] = count
                result['layers'] = list(catalog.values())
                result['reference_total'] = catalog.get('unresolved', {}).get('nodes', 0)
                result['projection_warnings'] = mapping.get('warnings', [])
                for field in ('scope_id', 'kind', 'validity', 'confidence', 'source_path'):
                    if field in columns:
                        result['facets'][field] = self.rows(db, 'SELECT ' + quote(field) + ' AS value,count(*) AS count FROM (' + mapping['nodes'] + ') GROUP BY ' + quote(field) + ' ORDER BY count(*) DESC', limit=200)[0]
                for field in ('kind', 'validity', 'confidence'):
                    if field in edge_columns:
                        result['edge_facets'][field] = self.rows(db, 'SELECT ' + quote(field) + ' AS value,count(*) AS count FROM (' + mapping['edges'] + ') GROUP BY ' + quote(field) + ' ORDER BY count(*) DESC', limit=200)[0]
                edge_values = {field: values.get('edge_' + field) for field in ('kind', 'validity', 'confidence')}
                edge_values['excluded_layers'] = values.get('excluded_layers', [])
                edges_sql, edge_params = self.filters(mapping['edges'], edge_values, edge_columns)
                result['isolated_total'] = db.execute('WITH endpoints AS (SELECT source AS id FROM (' + mapping['edges'] + ') UNION SELECT target FROM (' + mapping['edges'] + ')) SELECT count(*) FROM (' + mapping['nodes'] + ') n LEFT JOIN endpoints p ON p.id=n.graph_id WHERE p.id IS NULL').fetchone()[0]
                result['dangling_total'] = db.execute('WITH ns AS MATERIALIZED (SELECT graph_id FROM (' + mapping['nodes'] + ')) SELECT count(*) FROM (' + mapping['edges'] + ') e LEFT JOIN ns s ON s.graph_id=e.source LEFT JOIN ns t ON t.graph_id=e.target WHERE s.graph_id IS NULL OR t.graph_id IS NULL').fetchone()[0]
                nodes_sql, params = self.filters(mapping['nodes'], values, columns)
                if values.get('excluded_layers'):
                    visible_sql, visible_params = self.filters(mapping['nodes'], {'excluded_layers': values['excluded_layers']}, columns)
                    edges_sql = 'WITH enabled AS MATERIALIZED (' + visible_sql + ') SELECT e.* FROM (' + edges_sql + ') e JOIN enabled s ON s.graph_id=e.source JOIN enabled t ON t.graph_id=e.target'
                    edge_params = visible_params + edge_params
                if values.get('focus') == 'unsupported':
                    if 'evidence_count' not in columns:
                        raise ValueError('This projection has no evidence_count column')
                    nodes_sql = 'SELECT * FROM (' + nodes_sql + ') WHERE evidence_count=0'
                elif values.get('focus') == 'isolated':
                    nodes_sql = 'WITH endpoints AS (SELECT source AS id FROM (' + mapping['edges'] + ') UNION SELECT target FROM (' + mapping['edges'] + ')) SELECT n.* FROM (' + nodes_sql + ') n LEFT JOIN endpoints p ON p.id=n.graph_id WHERE p.id IS NULL'
                if values.get('aggregate'):
                    field = values['aggregate']
                    if field not in {'kind', 'scope_id', 'source_path', 'validity', 'confidence', 'layer'} or field not in columns:
                        raise ValueError('Grouping field is unavailable in this projection')
                    self.aggregate(db, result, nodes_sql, params, edges_sql, edge_params, field, columns, limit, offset)
                    result['elapsed_ms'] = round((time.monotonic() - started) * 1000, 1)
                    if whole:
                        self.snapshot_key = snapshot_key
                    return result
                if values.get('root'):
                    # Bounded depth, cycles deduplicated at each depth; query deadline also applies.
                    depth = max(0, min(int(values.get('depth', 1)), 4))
                    nodes_sql = ('WITH RECURSIVE reach(id,depth) AS (SELECT ?,0 UNION SELECT CASE WHEN e.source=r.id THEN e.target ELSE e.source END,r.depth+1 FROM reach r JOIN (' + edges_sql + ') e ON e.source=r.id OR e.target=r.id WHERE r.depth<?) SELECT n.* FROM (' + nodes_sql + ') n WHERE n.graph_id IN (SELECT id FROM reach)')
                    params = [values['root']] + edge_params + [depth] + params
                result['matched_nodes'] = db.execute('SELECT count(*) FROM (' + nodes_sql + ')', params).fetchone()[0]
                # Omit large detail columns before Python serialization/budget checks.
                # The built-in fingerprint already covers them; custom mappings need
                # their full rows below to compute equivalent fingerprints.
                node_output = ','.join(quote(c) for c in columns if c in OVERVIEW_NODE_FIELDS) if whole and not self.mapping else '*'
                node_query = 'SELECT ' + node_output + ' FROM (' + nodes_sql + ') ORDER BY graph_id LIMIT ? OFFSET ?'
                result['nodes'], result['node_has_more'] = self.rows(db, node_query, params + [limit + 1, offset], limit, MAX_GRAPH_RESPONSE if whole else MAX_RESPONSE)
                if whole and result['node_has_more']:
                    raise ValueError('Whole graph exceeds 100,000 nodes; use layers, filters, or an aggregate view')
                ids = [n['graph_id'] for n in result['nodes']]
                if any(not isinstance(i, str) for i in ids) or len(ids) != len(set(ids)):
                    raise ValueError('graph_id must be unique text; use composite keys across scopes')
                if ids:
                    if whole:
                        # Joins need identities only, not copies of every summary,
                        # locator and fingerprint for each selected node.
                        prefix = 'WITH selected AS MATERIALIZED (SELECT graph_id FROM (' + nodes_sql + ')) '
                        edge_output = ','.join('e.' + quote(c) for c in edge_columns if c in OVERVIEW_EDGE_FIELDS) if not self.mapping else 'e.*'
                        query = prefix + 'SELECT ' + edge_output + ' FROM (' + edges_sql + ') e JOIN selected s ON s.graph_id=e.source JOIN selected t ON t.graph_id=e.target ORDER BY e.graph_id'
                        result['edges'], result['edge_has_more'] = self.rows(db, query, params + edge_params, MAX_GRAPH_EDGES, MAX_GRAPH_RESPONSE)
                        if result['edge_has_more']:
                            raise ValueError('Whole graph exceeds 200,000 relationships; use layers, filters, or an aggregate view')
                        result['boundary_edges'] = db.execute(prefix + 'SELECT count(*) FROM (' + edges_sql + ') e LEFT JOIN selected s ON s.graph_id=e.source LEFT JOIN selected t ON t.graph_id=e.target WHERE (s.graph_id IS NULL)!=(t.graph_id IS NULL)', params + edge_params).fetchone()[0]
                    else:
                        marks = ','.join('?' for _ in ids)
                        edge_sql = 'SELECT * FROM (' + edges_sql + ') WHERE source IN (' + marks + ') AND target IN (' + marks + ') ORDER BY graph_id'
                        result['edges'], result['edge_has_more'] = self.rows(db, edge_sql, edge_params + ids + ids)
                        result['boundary_edges'] = db.execute('SELECT count(*) FROM (' + edges_sql + ') WHERE (source IN (' + marks + ')) != (target IN (' + marks + '))', edge_params + ids + ids).fetchone()[0]
                edge_ids = [e['graph_id'] for e in result['edges']]
                if any(not isinstance(i, str) for i in edge_ids) or len(set(edge_ids)) != len(edge_ids):
                    raise ValueError('Edge graph_id must be unique text')
                if whole:
                    if self.mapping:
                        for row in result['nodes'] + result['edges']:
                            row['fingerprint'] = hashlib.sha256(json_bytes(row)).hexdigest()
                    result['nodes'] = [{k: v for k, v in row.items() if k in OVERVIEW_NODE_FIELDS} for row in result['nodes']]
                    result['edges'] = [{k: v for k, v in row.items() if k in OVERVIEW_EDGE_FIELDS} for row in result['edges']]
            result['elapsed_ms'] = round((time.monotonic() - started) * 1000, 1)
            if whole:
                self.snapshot_key = snapshot_key
            return result

    def aggregate(self, db, result, nodes_sql, params, edges_sql, edge_params, field, columns, limit, offset):
        """Group the full filtered projections in SQLite, never a loaded browser sample."""
        category = quote(field)
        ns = 'SELECT *, ' + category + ' AS __category FROM (' + nodes_sql + ')'
        prefix = 'WITH ns AS MATERIALIZED (' + ns + ') '
        counts = ['count(*) AS member_count']
        if 'validity' in columns:
            counts += ["sum(validity='current') AS current_count", "sum(validity='stale') AS stale_count"]
        if 'confidence' in columns:
            counts += ["sum(confidence='uncertain') AS uncertain_count"]
        if 'evidence_count' in columns:
            counts += ['sum(evidence_count=0) AS without_evidence_count']
        grouped = ('SELECT json_array(\'group\',\'' + field + '\',__category) AS graph_id, '
                   "coalesce(CAST(__category AS TEXT),'(unspecified)') AS label, "
                   '__category AS group_value, ' + ','.join(counts) + ' FROM ns GROUP BY __category')
        result['matched_nodes'] = db.execute(prefix + 'SELECT count(*) FROM (' + grouped + ')', params).fetchone()[0]
        result['nodes'], result['node_has_more'] = self.rows(db, prefix + grouped + ' ORDER BY graph_id LIMIT ? OFFSET ?', params + [limit + 1, offset], limit)
        for node in result['nodes']:
            node['_aggregate'] = field
            node[field] = node['group_value']
        ids = [n['graph_id'] for n in result['nodes']]
        if ids:
            marks = ','.join('?' for _ in ids)
            source = "json_array('group','" + field + "',s.__category)"
            target = "json_array('group','" + field + "',t.__category)"
            pairs = ('SELECT ' + source + ' AS source,' + target + ' AS target, count(*) AS member_count '
                     'FROM es e JOIN ns s ON s.graph_id=e.source JOIN ns t ON t.graph_id=e.target '
                     'GROUP BY s.__category,t.__category')
            eprefix = 'WITH ns AS MATERIALIZED (' + ns + '), es AS MATERIALIZED (' + edges_sql + ') '
            esql = ("SELECT json_array('group-edge',source,target) AS graph_id,source,target,member_count "
                    'FROM (' + pairs + ') WHERE source IN (' + marks + ') AND target IN (' + marks + ') ORDER BY graph_id')
            result['edges'], result['edge_has_more'] = self.rows(db, eprefix + esql, params + edge_params + ids + ids)
            for edge in result['edges']:
                edge['_aggregate'] = field
            result['boundary_edges'] = db.execute(eprefix + 'SELECT coalesce(sum(member_count),0) FROM (' + pairs + ') WHERE (source IN (' + marks + ')) != (target IN (' + marks + '))', params + edge_params + ids + ids).fetchone()[0]
        result['aggregate'] = field
        result['grouped_members'] = db.execute('SELECT count(*) FROM (' + nodes_sql + ')', params).fetchone()[0]

    def query(self, values):
        """Arbitrary schema exploration remains bounded and cannot mutate the host."""
        sql = values.get('sql', '')
        if not isinstance(sql, str) or not sql.strip():
            raise ValueError('A read-only SELECT is required')
        with self.connect() as db:
            rows, more = self.rows(db, 'SELECT * FROM (' + sql + ') LIMIT 201', values.get('params', []), 200)
            return {'rows': rows, 'has_more': more}

    def detail(self, values):
        with self.connect() as db:
            mapping = self.projections(db)
            if not mapping or values.get('type') not in {'nodes', 'edges'}:
                raise ValueError('Unknown graph projection')
            rows, _ = self.rows(db, 'SELECT * FROM (' + mapping[values['type']] + ') WHERE graph_id=?', [values.get('id')], 1)
            evidence = []
            coverage = []
            if rows and not self.mapping:
                row = rows[0]
                table = row.get('source_table')
                if table in {'nodes', 'edges'}:
                    raw, _ = self.rows(db, 'SELECT * FROM ' + quote(table) + ' WHERE scope_id=? AND id=?', [row['scope_id'], row['id']], 1)
                    if raw:
                        row.update(raw[0])
                if table == 'nodes':
                    extra, _ = self.rows(db, 'SELECT qualified_name,signature,language FROM symbol_details WHERE scope_id=? AND node_id=?', [row['scope_id'], row['id']], 1)
                    if extra:
                        row.update(extra[0])
                    coverage, more = self.rows(db, '''SELECT f.*,n.source_path FROM file_details f
                        JOIN nodes n ON n.scope_id=f.scope_id AND n.id=f.node_id
                        WHERE f.scope_id=? AND (f.node_id=? OR (
                            n.kind='file' AND n.validity='current'
                            AND n.source_path=NULLIF(?, '')))
                        ORDER BY f.node_id''',
                        [row['scope_id'], row['id'], row.get('source_path')], 200)
                    row['coverage_has_more'] = more
            if rows and not self.mapping and rows[0].get('source_table') in {'nodes', 'edges'}:
                row = rows[0]
                field = 'node_id' if values['type'] == 'nodes' else 'edge_id'
                evidence, more = self.rows(db, 'SELECT * FROM evidence WHERE scope_id=? AND ' + field + '=?', [row['scope_id'], row['id']], 200)
                return {'rows': rows, 'evidence': evidence, 'evidence_has_more': more, 'coverage': coverage}
            return {'rows': rows, 'evidence': evidence, 'coverage': coverage}

    def events(self, values):
        cursors = values.get('cursors', {})
        if not isinstance(cursors, dict):
            raise ValueError('Invalid trace cursor')
        output, updated, backlog = [], dict(cursors), False
        if not self.trace_directory:
            return {'events': [], 'cursors': {}, 'enabled': False, 'has_more': False}
        files = sorted(self.trace_directory.glob('*.jsonl'))
        if len(files) > 1000:
            raise ValueError('More than 1000 trace files; archive old logs before continuing')
        budget = 2 * 1024 * 1024
        for path in files:
            if path.is_symlink():
                continue
            position = cursors.get(path.name, 0)
            if type(position) is not int or position < 0:
                raise ValueError('Invalid trace cursor')
            if position > path.stat().st_size:
                position = 0
            with path.open('rb') as stream:
                stream.seek(position)
                while budget > 0:
                    raw = stream.readline(1024 * 1024)
                    if not raw:
                        break
                    if not raw.endswith(b'\n'):
                        break  # Writer may still be appending; retry the complete line.
                    position = stream.tell()
                    budget -= len(raw)
                    event = json.loads(raw)
                    if event.get('database') == str(self.path):
                        output.append(event)
                updated[path.name] = position
                backlog |= position < path.stat().st_size
        return {'events': sorted(output, key=lambda e: e['time']), 'cursors': updated,
                'enabled': True, 'has_more': backlog}


def make_server(explorer, port=0):
    token = secrets.token_urlsafe(32)

    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(5)

        def log_message(self, *args):
            pass  # Never log tokens, queries, or host contents.

        def respond(self, code, data, mime='application/json; charset=utf-8'):
            whole = isinstance(data, dict) and data.get('whole_graph') is True
            if not isinstance(data, bytes):
                data = json.dumps(data, ensure_ascii=True, allow_nan=False).encode('utf-8')
            if len(data) > (MAX_GRAPH_RESPONSE if whole else MAX_RESPONSE):
                code, data = 413, b'{"error":"Response exceeds the graph output budget; narrow the layers or selection"}'
            compressed = 'gzip' in self.headers.get('Accept-Encoding', '') and len(data) > 262144 and mime.startswith('application/json')
            if compressed:
                data = gzip.compress(data, compresslevel=3)
            self.send_response(code)
            self.send_header('Content-Type', mime)
            self.send_header('Content-Length', str(len(data)))
            if compressed:
                self.send_header('Content-Encoding', 'gzip')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")
            self.end_headers()
            self.wfile.write(data)

        def allowed(self):
            host = '127.0.0.1:' + str(self.server.server_port)
            return self.headers.get('Host') == host and self.headers.get('Origin', 'http://' + host) == 'http://' + host

        def do_GET(self):
            if not self.allowed():
                return self.respond(403, {'error': 'Loopback origin required'})
            path = urlsplit(self.path).path
            assets = {'/': ('index.html', 'text/html; charset=utf-8'),
                      '/app.js': ('app.js', 'text/javascript; charset=utf-8'),
                      '/graph-layout.js': ('graph-layout.js', 'text/javascript; charset=utf-8'),
                      '/style.css': ('style.css', 'text/css; charset=utf-8'),
                      '/cytoscape.min.js': ('vendor/cytoscape.min.js', 'text/javascript; charset=utf-8')}
            if path == '/favicon.ico':
                return self.respond(204, b'', 'image/x-icon')
            if path not in assets:
                return self.respond(404, {'error': 'Not found'})
            file, mime = assets[path]
            self.respond(200, (ASSETS / file).read_bytes(), mime)

        def do_POST(self):
            if not self.allowed() or not secrets.compare_digest(self.headers.get('X-Viewer-Token', '').encode('utf-8'), token.encode('utf-8')):
                return self.respond(403, {'error': 'Viewer token required'})
            try:
                size = int(self.headers.get('Content-Length', '0'))
                if not 0 < size <= 65536:
                    return self.respond(413, {'error': 'Request limit is 64 KiB'})
                values = json.loads(self.rfile.read(size))
                if not isinstance(values, dict):
                    raise ValueError('Expected object')
                routes = {'/api/snapshot': explorer.snapshot, '/api/query': explorer.query,
                          '/api/detail': explorer.detail, '/api/events': explorer.events,
                          '/api/changes': explorer.changes}
                if self.path not in routes:
                    return self.respond(404, {'error': 'Not found'})
                self.respond(200, routes[self.path](values))
            except (ValueError, TypeError, KeyError, OverflowError, OSError, sqlite3.Error) as exc:
                self.respond(400, {'error': str(exc)[:1000]})

    server = HTTPServer(('127.0.0.1', port), Handler)
    server.timeout = 1
    return server, token


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', required=True)
    parser.add_argument('--mapping', help='JSON file with read-only nodes and edges SQL projections')
    parser.add_argument('--trace-directory', help='Same explicit directory used by traced executors')
    parser.add_argument('--port', type=int, default=0)
    parser.add_argument('--record-changes', action='store_true', help='Explicitly install/maintain versioned row-history tables and triggers in this database; default is read-only')
    args = parser.parse_args()
    mapping = json.loads(Path(args.mapping).read_text(encoding='utf-8')) if args.mapping else None
    explorer = Explorer(args.database, mapping, args.trace_directory, record_changes=args.record_changes)
    server, token = make_server(explorer, args.port)
    print('EvoMneme viewer: http://127.0.0.1:' + str(server.server_port) + '/#token=' + token, flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        explorer.close()


if __name__ == '__main__':
    main()
