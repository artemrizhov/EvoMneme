"""Advisory graph checks and measured storage statistics; never writes the store."""
import hashlib
from pathlib import Path, PureWindowsPath
import sqlite3
import time

from evomneme_context import ReadContext
from evomneme_graph import quoted
from evomneme_navigate import fields

OUTPUT_BYTES = 64 * 1024
TIMEOUT_SECONDS = 5.0
SOURCE_BYTES = 16 * 1024 * 1024
GRAPH_TABLES = {'metadata', 'scopes', 'nodes', 'edges', 'evidence', 'symbol_details', 'file_details'}


class DiagnosticError(ValueError):
    pass


class DiagnosticReader:
    def __init__(self, connection, shared=None, timeout=TIMEOUT_SECONDS):
        if shared is not None and shared.connection != connection:
            raise DiagnosticError('Shared read context belongs to another binding')
        self.owns_context = shared is None
        self.context = shared or ReadContext(connection, timeout=timeout, timeout_error=DiagnosticError,
                                             timeout_message='Diagnostics timed out; no complete result.')
        self.connection, self.db = connection, self.context.db

    def check_time(self):
        self.context.check_time()

    def rows(self, sql, params=()):
        self.check_time()
        for row in self.db.execute(sql, params):
            self.check_time()
            yield dict(row)

    def scalar(self, sql, params=()):
        self.check_time()
        value = self.db.execute(sql, params).fetchone()[0]
        self.check_time()
        return value

    def graph_check(self):
        scope = (self.connection.scope,)
        nodes = {r['id']: set() for r in self.rows("SELECT id FROM nodes WHERE scope_id=? AND validity='current' ORDER BY id", scope)}
        kinds = {id_: set() for id_ in nodes}
        triples = {}
        inactive_endpoints = []
        for edge in self.rows("SELECT id,source_id,target_id,kind FROM edges WHERE scope_id=? AND validity='current' ORDER BY id", scope):
            a, b, kind = edge['source_id'], edge['target_id'], edge['kind']
            triples.setdefault((a, b, kind), []).append(edge['id'])
            if a not in nodes or b not in nodes:
                inactive_endpoints.append(dict(edge_id=edge['id'], source_id=a, target_id=b))
                continue
            nodes[a].add(b)
            nodes[b].add(a)
            kinds[a].add(kind)
            kinds[b].add(kind)
        components, unseen = [], set(nodes)
        for seed in nodes:
            self.check_time()
            if seed not in unseen:
                continue
            unseen.remove(seed)
            pending, component = [seed], []
            while pending:
                self.check_time()
                item = pending.pop()
                component.append(dict(id=item))
                for neighbor in sorted(nodes[item]):
                    self.check_time()
                    if neighbor in unseen:
                        unseen.remove(neighbor)
                        pending.append(neighbor)
            components.append(dict(size=len(component), nodes=component))
        coverage = {}
        for table, owner in (('nodes', 'node_id'), ('edges', 'edge_id')):
            total = self.scalar('SELECT count(*) FROM ' + table + " WHERE scope_id=? AND validity='current'", scope)
            covered = self.scalar('SELECT count(*) FROM ' + table + " t WHERE scope_id=? AND validity='current' AND EXISTS "
                                  '(SELECT 1 FROM evidence p WHERE p.scope_id=t.scope_id AND p.' + owner + "=t.id AND p.validity='current')", scope)
            coverage[table] = dict(current=total, with_current_evidence=covered, without_current_evidence=total-covered)
        return dict(advisory='Structural signals require source review; leaf nodes can be legitimate. No links are created. Semantic completeness is not established.',
                    adjacency='Current nodes and current edges with current endpoints; undirected distinct neighbors, including self-loops.',
                    current_nodes=len(nodes), current_edges=sum(len(ids) for ids in triples.values()),
                    weak_components=components, component_count=len(components),
                    isolated_nodes=[dict(id=k) for k, v in nodes.items() if not v],
                    degree_one_nodes=[dict(id=k) for k, v in nodes.items() if len(v) == 1],
                    contains_only_nodes=[dict(id=k) for k, v in kinds.items() if v == {'contains'}],
                    current_edges_without_current_endpoints=inactive_endpoints,
                    duplicate_relationships=[dict(source_id=a, target_id=b, kind=k, edges=[dict(id=i) for i in ids])
                                             for (a, b, k), ids in triples.items() if len(ids) > 1], evidence_coverage=coverage)

    def source_check(self, paths):
        """Match literal saved paths; filesystem normalization is used only for confinement."""
        root = Path(self.connection.scope_worktree).resolve(strict=True)
        results = []
        for literal in dict.fromkeys(paths):
            self.check_time()
            if not isinstance(literal, str) or not literal:
                raise DiagnosticError('Sources requires nonempty literal source paths.')
            refs = []
            for table in ('nodes', 'edges', 'evidence'):
                for row in self.rows('SELECT * FROM ' + table + ' WHERE scope_id=? AND source_path=? COLLATE BINARY ORDER BY id',
                                     (self.connection.scope, literal)):
                    refs.append(dict(table=table, stored=row))
            item = dict(source_path=literal, references=refs, reference_count=len(refs))
            results.append(item)
            path = Path(literal)
            # Reject absolute, drive-relative, UNC and traversal even if they happen to resolve inside.
            if path.is_absolute() or PureWindowsPath(literal).drive or PureWindowsPath(literal).root or '..' in PureWindowsPath(literal).parts:
                item['file_status'] = 'rejected unsafe path; no source read'
                continue
            try:
                candidate = (root / path).resolve(strict=False)
                if not candidate.is_relative_to(root):
                    item['file_status'] = 'rejected symlink escape; no source read'
                    continue
                if not candidate.exists():
                    item['file_status'] = 'missing file'
                    continue
                if not candidate.is_file():
                    item['file_status'] = 'not a regular file; no source read'
                    continue
                digest, size, newlines, last = hashlib.sha256(), 0, 0, b''
                with candidate.open('rb') as stream:
                    while True:
                        self.check_time()
                        block = stream.read(65536)
                        if not block:
                            break
                        size += len(block)
                        if size > SOURCE_BYTES:
                            break
                        digest.update(block)
                        newlines += block.count(b'\n') + block.count(b'\r') - block.count(b'\r\n')
                        if last == b'\r' and block.startswith(b'\n'):
                            newlines -= 1
                        last = block[-1:]
                if size > SOURCE_BYTES:
                    item['file_status'] = 'source exceeds bounded read limit; hash/lines not checked'
                    continue
                lines = newlines + int(bool(size) and last not in (b'\n', b'\r'))
                actual = digest.hexdigest()
                item.update(file_status='read', sha256=actual, line_count=lines)
                for ref in refs:
                    self.check_time()
                    row = ref['stored']
                    saved = row['source_hash']
                    ref['hash_status'] = 'not recorded' if not saved else ('match' if saved in (actual, 'sha256:' + actual) else 'mismatch or unsupported hash format')
                    if ref['table'] != 'evidence':
                        start, end = row['line_start'], row['line_end']
                        ref['line_status'] = ('out of bounds' if any(v is not None and (not isinstance(v, int) or v < 1 or v > lines) for v in (start, end))
                                              or (start is not None and end is not None and start > end)
                                              else 'within file bounds' if start is not None or end is not None else 'not recorded')
            except OSError as exc:
                item['file_status'] = 'source unavailable: ' + str(exc)
        return dict(matching='Exact literal source_path in selected scope, all validity states; aliases are not searched.',
                    caveat='Textual citations in summaries/descriptions require manual review; valid hashes and line bounds do not verify claims or semantic completeness.',
                    files=results)

    def stats(self):
        distributions = {}
        for table in ('nodes', 'edges', 'evidence'):
            columns = ('kind', 'layer', 'validity') if table != 'evidence' else ('validity',)
            distributions[table] = dict(rows=self.scalar('SELECT count(*) FROM ' + table + ' WHERE scope_id=?', (self.connection.scope,)))
            for column in columns:
                distributions[table][column] = list(self.rows('SELECT ' + quoted(column) + ' AS value,count(*) AS count FROM ' + table +
                                                              ' WHERE scope_id=? GROUP BY ' + quoted(column) + ' ORDER BY ' + quoted(column), (self.connection.scope,)))
        tables = [r['name'] for r in self.rows("SELECT name FROM sqlite_schema WHERE type='table'")]
        groups = {name: dict(rows=0, tables=[]) for name in ('graph', 'history', 'calls', 'other')}
        table_group = {}
        for table in tables:
            name = ('graph' if table in GRAPH_TABLES else 'calls' if table == 'evomneme_change_calls' else
                    'history' if table == 'history' or table.startswith('evomneme_change_') else 'other')
            table_group[table] = name
            count = self.scalar('SELECT count(*) FROM ' + quoted(table))
            groups[name]['rows'] += count
            groups[name]['tables'].append(dict(name=table, rows=count))
        page_size = self.scalar('PRAGMA page_size')
        storage = dict(scope='whole database, all scopes', page_size=page_size, page_count=self.scalar('PRAGMA page_count'),
                       free_pages=self.scalar('PRAGMA freelist_count'), groups=groups,
                       measurement_caveat='File sizes are observed filesystem values, not transactional; WAL bytes can include multiple versions and are not attributed to graph rows.')
        storage['files'] = []
        for suffix, label in (('', 'database'), ('-wal', 'wal'), ('-shm', 'shm'), ('-journal', 'rollback_journal')):
            self.check_time()
            path = Path(str(self.connection.database) + suffix)
            try:
                size = path.stat().st_size
            except FileNotFoundError:
                size = 0
            storage['files'].append(dict(kind=label, observed_bytes=size))
        try:
            allocation = list(self.rows('SELECT name,sum(pgsize) AS bytes FROM dbstat GROUP BY name'))
        except sqlite3.OperationalError as exc:
            if time.monotonic() >= self.context.deadline or 'interrupted' in str(exc).lower():
                raise
            if 'no such table' not in str(exc).lower() and 'no such module' not in str(exc).lower():
                raise
            allocation = None
        if allocation is not None:
            owners = {r['name']: r['tbl_name'] for r in self.rows('SELECT name,tbl_name FROM sqlite_schema')}
            for group in groups.values():
                group['allocated_page_bytes'] = 0
            for row in allocation:
                group = table_group.get(owners.get(row['name'], row['name']), 'other')
                groups[group]['allocated_page_bytes'] += row['bytes']
            storage['method'] = 'dbstat allocated B-tree pages including table/index overhead; excludes free pages, WAL and database header allocation outside these B-trees'
        else:
            storage['method'] = 'payload estimate: sum of column values as BLOB bytes; excludes record, page and index overhead; not allocated storage'
            for group in groups.values():
                group['payload_estimate_bytes'] = 0
            for table in tables:
                columns = [r['name'] for r in self.rows('PRAGMA table_info(' + quoted(table) + ')')]
                expression = '+'.join('coalesce(length(CAST(' + quoted(column) + ' AS BLOB)),0)' for column in columns)
                groups[table_group[table]]['payload_estimate_bytes'] += self.scalar('SELECT coalesce(sum(' + expression + '),0) FROM ' + quoted(table))
        return dict(scope_graph=distributions, storage=storage)


def diagnose(connection, args, shared=None):
    """Return complete guarded output, sharing a chain's snapshot and deadline."""
    reader = None
    try:
        reader = DiagnosticReader(connection, shared=shared)
        command = args.diagnostic_command
        result = dict(command=command, scope=connection.scope,
                      warnings=[dict(warning=w) for w in reader.context.warnings])
        if command == 'check':
            result['database_checks'] = dict(integrity=list(reader.rows('PRAGMA integrity_check')),
                                             foreign_keys=list(reader.rows('PRAGMA foreign_key_check')))
            result['graph'] = reader.graph_check()
            if getattr(args, 'sources', None):
                result['sources'] = reader.source_check(args.sources)
        elif command == 'stats':
            result.update(reader.stats())
        else:
            raise DiagnosticError('Unknown diagnostic command')
        chunks, size = [], 0
        for line in fields(result):
            reader.check_time()
            chunk = line + '\n'
            size += len(chunk.encode('utf-8'))
            if not getattr(args, 'all_output', False) and size > OUTPUT_BYTES:
                graph = result.get('graph', {})
                counts = (' current_nodes=' + str(graph['current_nodes']) + '; current_edges=' + str(graph['current_edges']) +
                          '; weak_components=' + str(graph['component_count']) + '.' if graph else '')
                raise DiagnosticError('Diagnostics output exceeds ' + str(OUTPUT_BYTES) + ' bytes; no result emitted.' + counts +
                                      ' Rerun the same invocation with --all.')
            chunks.append(chunk)
        reader.check_time()
        output = ''.join(chunks)
        reader.check_time()
        return output
    except sqlite3.Error as exc:
        if reader is not None and (time.monotonic() >= reader.context.deadline or 'interrupted' in str(exc).lower()):
            raise DiagnosticError('Diagnostics timed out; no complete result.') from exc
        raise DiagnosticError('Cannot read bound diagnostics: ' + str(exc)) from exc
    finally:
        if reader is not None and reader.owns_context:
            reader.context.close()


def configure_parser(subparsers):
    for name in ('check', 'stats'):
        parser = subparsers.add_parser(name, help='Read-only advisory checks' if name == 'check' else 'Graph counts and whole-database storage measurements')
        parser.add_argument('--all', action='store_true', dest='all_output', help='Remove the 64 KiB output guard; chain deadline remains')
        if name == 'check':
            parser.add_argument('--sources', nargs='+', action='extend', default=[], metavar='PATH', help='Target literal source paths for bounded reconciliation preflight; repeatable')
        parser.set_defaults(diagnostic=True, diagnostic_command=name)


def run(connection, args):
    return diagnose(connection, args)
