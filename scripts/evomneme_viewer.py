#!/usr/bin/env python3
"""Read-only, loopback Cytoscape explorer for an explicitly selected host SQLite file."""

import argparse
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from pathlib import Path
import secrets
import sqlite3
import time
from urllib.parse import urlsplit

from evomneme import cell

ASSETS = Path(__file__).parent / 'viewer'
MAX_ROWS = 2000
MAX_RESPONSE = 8 * 1024 * 1024


def quote(name):
    return '"' + name.replace('"', '""') + '"'


def bounded_cell(value):
    if isinstance(value, (str, bytes)) and len(value) > 16384:
        return {'preview': cell(value[:16384]), 'truncated': True, 'length': len(value)}
    return cell(value)


class Explorer:
    def __init__(self, database, mapping=None, trace_directory=None):
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

    def file_identity(self):
        info = self.path.stat()
        return info.st_dev, info.st_ino

    @contextmanager
    def connect(self):
        if self.requested.resolve(strict=True) != self.path or self.file_identity() != self.identity:
            raise ValueError('Database replaced or retargeted; restart the viewer')
        db = sqlite3.connect(self.path.as_uri() + '?mode=ro', uri=True, timeout=1)
        deadline = time.monotonic() + 5
        try:
            db.execute('PRAGMA query_only=ON')
            db.enable_load_extension(False)
            db.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, 8 * 1024 * 1024)
            db.setlimit(sqlite3.SQLITE_LIMIT_SQL_LENGTH, 65536)
            db.set_progress_handler(lambda: time.monotonic() > deadline, 1000)
            db.execute('BEGIN')
            def authorize(action, first, second, database, trigger):
                if action in {sqlite3.SQLITE_ATTACH, sqlite3.SQLITE_DETACH}:
                    return sqlite3.SQLITE_DENY
                if action == sqlite3.SQLITE_FUNCTION and (second or '').lower() in {'load_extension', 'readfile', 'writefile'}:
                    return sqlite3.SQLITE_DENY
                if action == sqlite3.SQLITE_PRAGMA:
                    # Only introspection required by the explorer and SELECT pragma_* functions.
                    if (first or '').lower() not in {'table_info', 'foreign_key_list', 'page_count', 'page_size', 'freelist_count', 'query_only'}:
                        return sqlite3.SQLITE_DENY
                    if (first or '').lower() == 'query_only' and second is not None:
                        return sqlite3.SQLITE_DENY
                return sqlite3.SQLITE_OK
            db.set_authorizer(authorize)
            yield db
        finally:
            db.close()

    def rows(self, db, sql, params=(), limit=MAX_ROWS):
        cursor = db.execute(sql, params)
        columns = [c[0] for c in cursor.description or []]
        if len(set(columns)) != len(columns):
            raise ValueError('Use unique column aliases')
        rows = cursor.fetchmany(limit + 1)
        return [{c: bounded_cell(v) for c, v in zip(columns, row)} for row in rows[:limit]], len(rows) > limit

    def projections(self, db):
        if self.mapping:
            return self.mapping
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_schema WHERE type='table'")}
        if not {'records', 'relations'} <= tables:
            return None
        required = {'records': {'scope_id', 'id', 'title'}, 'relations': {'scope_id', 'id', 'source_id', 'target_id'}}
        for table, columns in required.items():
            if not columns <= {r[1] for r in db.execute('PRAGMA table_info(' + quote(table) + ')')}:
                return None
        node_evidence = edge_evidence = ''
        if 'evidence' in tables and {'scope_id', 'record_id', 'relation_id'} <= {r[1] for r in db.execute('PRAGMA table_info(evidence)')}:
            node_evidence = ',(SELECT count(*) FROM evidence e WHERE e.scope_id=records.scope_id AND e.record_id=records.id) AS evidence_count'
            edge_evidence = ',(SELECT count(*) FROM evidence e WHERE e.scope_id=relations.scope_id AND e.relation_id=relations.id) AS evidence_count'
        return {'nodes': "SELECT json_array(scope_id,id) AS graph_id, title AS label, *" + node_evidence + " FROM records",
                'edges': "SELECT json_array(scope_id,id) AS graph_id, json_array(scope_id,source_id) AS source, json_array(scope_id,target_id) AS target, *" + edge_evidence + " FROM relations"}

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
        limit = max(1, min(int(values.get('limit', 500)), MAX_ROWS))
        offset = max(0, min(int(values.get('offset', 0)), 100000000))
        with self.connect() as db:
            tables = self.schema(db)
            mapping = self.projections(db)
            result = {'tables': tables, 'bytes': db.execute('PRAGMA page_count').fetchone()[0] * db.execute('PRAGMA page_size').fetchone()[0],
                      'nodes': [], 'edges': [], 'graph_available': bool(mapping), 'facets': {}, 'edge_facets': {}, 'totals': {}, 'offset': offset,
                      'node_has_more': False, 'edge_has_more': False}
            if mapping:
                columns = [c[0] for c in db.execute('SELECT * FROM (' + mapping['nodes'] + ') LIMIT 0').description]
                edge_columns = [c[0] for c in db.execute('SELECT * FROM (' + mapping['edges'] + ') LIMIT 0').description]
                if not {'graph_id', 'label'} <= set(columns) or not {'graph_id', 'source', 'target'} <= set(edge_columns):
                    raise ValueError('Projection columns: nodes need graph_id,label; edges need graph_id,source,target')
                for key in ('nodes', 'edges'):
                    result['totals'][key] = db.execute('SELECT count(*) FROM (' + mapping[key] + ')').fetchone()[0]
                for field in ('scope_id', 'kind', 'validity', 'confidence', 'source_path'):
                    if field in columns:
                        result['facets'][field] = self.rows(db, 'SELECT ' + quote(field) + ' AS value,count(*) AS count FROM (' + mapping['nodes'] + ') GROUP BY ' + quote(field) + ' ORDER BY count(*) DESC', limit=200)[0]
                for field in ('kind', 'validity', 'confidence'):
                    if field in edge_columns:
                        result['edge_facets'][field] = self.rows(db, 'SELECT ' + quote(field) + ' AS value,count(*) AS count FROM (' + mapping['edges'] + ') GROUP BY ' + quote(field) + ' ORDER BY count(*) DESC', limit=200)[0]
                edges_sql, edge_params = self.filters(mapping['edges'], {field: values.get('edge_' + field) for field in ('kind', 'validity', 'confidence')}, edge_columns)
                result['isolated_total'] = db.execute('WITH endpoints AS (SELECT source AS id FROM (' + mapping['edges'] + ') UNION SELECT target FROM (' + mapping['edges'] + ')) SELECT count(*) FROM (' + mapping['nodes'] + ') n LEFT JOIN endpoints p ON p.id=n.graph_id WHERE p.id IS NULL').fetchone()[0]
                result['dangling_total'] = db.execute('WITH ns AS MATERIALIZED (SELECT graph_id FROM (' + mapping['nodes'] + ')) SELECT count(*) FROM (' + mapping['edges'] + ') e LEFT JOIN ns s ON s.graph_id=e.source LEFT JOIN ns t ON t.graph_id=e.target WHERE s.graph_id IS NULL OR t.graph_id IS NULL').fetchone()[0]
                nodes_sql, params = self.filters(mapping['nodes'], values, columns)
                if values.get('focus') == 'unsupported':
                    if 'evidence_count' not in columns:
                        raise ValueError('This projection has no evidence_count column')
                    nodes_sql = 'SELECT * FROM (' + nodes_sql + ') WHERE evidence_count=0'
                elif values.get('focus') == 'isolated':
                    nodes_sql = 'WITH endpoints AS (SELECT source AS id FROM (' + mapping['edges'] + ') UNION SELECT target FROM (' + mapping['edges'] + ')) SELECT n.* FROM (' + nodes_sql + ') n LEFT JOIN endpoints p ON p.id=n.graph_id WHERE p.id IS NULL'
                if values.get('aggregate'):
                    field = values['aggregate']
                    if field not in {'kind', 'scope_id', 'source_path', 'validity', 'confidence'} or field not in columns:
                        raise ValueError('Grouping field is unavailable in this projection')
                    self.aggregate(db, result, nodes_sql, params, edges_sql, edge_params, field, columns, limit, offset)
                    result['elapsed_ms'] = round((time.monotonic() - started) * 1000, 1)
                    return result
                if values.get('root'):
                    # Bounded depth, cycles deduplicated at each depth; query deadline also applies.
                    depth = max(0, min(int(values.get('depth', 1)), 4))
                    nodes_sql = ('WITH RECURSIVE reach(id,depth) AS (SELECT ?,0 UNION SELECT CASE WHEN e.source=r.id THEN e.target ELSE e.source END,r.depth+1 FROM reach r JOIN (' + edges_sql + ') e ON e.source=r.id OR e.target=r.id WHERE r.depth<?) SELECT n.* FROM (' + nodes_sql + ') n WHERE n.graph_id IN (SELECT id FROM reach)')
                    params = [values['root']] + edge_params + [depth] + params
                result['matched_nodes'] = db.execute('SELECT count(*) FROM (' + nodes_sql + ')', params).fetchone()[0]
                result['nodes'], result['node_has_more'] = self.rows(db, nodes_sql + ' ORDER BY graph_id LIMIT ? OFFSET ?', params + [limit + 1, offset], limit)
                ids = [n['graph_id'] for n in result['nodes']]
                if any(not isinstance(i, str) for i in ids) or len(ids) != len(set(ids)):
                    raise ValueError('graph_id must be unique text; use composite keys across scopes')
                if ids:
                    marks = ','.join('?' for _ in ids)
                    # Both endpoints belong to the slice; boundary counts expose omitted connections.
                    edge_sql = 'SELECT * FROM (' + edges_sql + ') WHERE source IN (' + marks + ') AND target IN (' + marks + ') ORDER BY graph_id'
                    result['edges'], result['edge_has_more'] = self.rows(db, edge_sql, edge_params + ids + ids)
                    result['boundary_edges'] = db.execute('SELECT count(*) FROM (' + edges_sql + ') WHERE (source IN (' + marks + ')) != (target IN (' + marks + '))', edge_params + ids + ids).fetchone()[0]
                edge_ids = [e['graph_id'] for e in result['edges']]
                if any(not isinstance(i, str) for i in edge_ids) or len(set(edge_ids)) != len(edge_ids):
                    raise ValueError('Edge graph_id must be unique text')
            result['elapsed_ms'] = round((time.monotonic() - started) * 1000, 1)
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
            if rows and not self.mapping and db.execute("SELECT 1 FROM sqlite_schema WHERE name='evidence' AND type='table'").fetchone():
                row = rows[0]
                field = 'record_id' if values['type'] == 'nodes' else 'relation_id'
                evidence, more = self.rows(db, 'SELECT * FROM evidence WHERE scope_id=? AND ' + field + '=?', [row['scope_id'], row['id']], 200)
                return {'rows': rows, 'evidence': evidence, 'evidence_has_more': more}
            return {'rows': rows, 'evidence': evidence}

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
            if not isinstance(data, bytes):
                data = json.dumps(data, ensure_ascii=True, allow_nan=False).encode('utf-8')
            if len(data) > MAX_RESPONSE:
                code, data = 413, b'{"error":"Response exceeds 8 MiB; narrow the selection"}'
            self.send_response(code)
            self.send_header('Content-Type', mime)
            self.send_header('Content-Length', str(len(data)))
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
                          '/api/detail': explorer.detail, '/api/events': explorer.events}
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
    args = parser.parse_args()
    mapping = json.loads(Path(args.mapping).read_text(encoding='utf-8')) if args.mapping else None
    explorer = Explorer(args.database, mapping, args.trace_directory)
    server, token = make_server(explorer, args.port)
    print('EvoMneme viewer: http://127.0.0.1:' + str(server.server_port) + '/#token=' + token, flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
