"""Read-only, snapshot-consistent navigation of a bound v3 knowledge graph."""
import json
from pathlib import Path
import shlex
import sqlite3
import time
from urllib.parse import quote, unquote

from evomneme_graph import validate_schema

OUTPUT_BYTES = 64 * 1024
TIMEOUT_SECONDS = 5.0
ROOT_ALIASES = {'root'}


class NavigationError(ValueError):
    pass


def quote_command(argv, shell):
    """Copyable commands for PowerShell or POSIX shells, never cmd.exe quoting."""
    if shell == 'powershell':
        return '& ' + ' '.join("'" + str(arg).replace("'", "''") + "'" for arg in argv)
    if shell == 'posix':
        return shlex.join([str(arg) for arg in argv])
    raise NavigationError('Unsupported command-example shell: ' + str(shell))


def qualified(scope, id_):
    return '@' + quote(scope, safe='') + '/' + quote(id_, safe='')


def compact(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'))


def location(row):
    return {key: row[key] for key in ('source_path', 'source_hash', 'line_start', 'line_end')
            if key in row.keys() and row[key] is not None}


class Reader:
    def __init__(self, connection, timeout=TIMEOUT_SECONDS):
        self.connection = connection
        self.scope = connection.scope
        self.deadline = time.monotonic() + timeout
        self.db = None
        self.warnings = []
        self.arguments = {}
        if timeout <= 0:
            raise NavigationError('Navigation timed out before execution; no complete result.')
        try:
            self.db = sqlite3.connect(Path(connection.database).resolve().as_uri() + '?mode=ro',
                                      uri=True, isolation_level=None, timeout=timeout)
            self.db.row_factory = sqlite3.Row
            self.db.execute('PRAGMA query_only=ON')
            self.db.set_progress_handler(lambda: int(time.monotonic() >= self.deadline), 1000)
            self.db.execute('BEGIN')
            validate_schema(self.db)
            from evomneme_connection import validate_binding
            self.warnings = list(dict.fromkeys([*connection.warnings, *validate_binding(self.db, connection)]))
            root = self.db.execute("SELECT * FROM nodes WHERE scope_id=? AND id=?", (self.scope, connection.root_id)).fetchone()
            if root is None or root['validity'] != 'current':
                raise NavigationError('Configured root is missing or not current; repair the binding/knowledge gap explicitly.')
            self.root = root
            self.check_time()
        except Exception:
            self.close()
            raise

    def close(self):
        if self.db is not None:
            self.db.close()
            self.db = None

    def check_time(self):
        if time.monotonic() >= self.deadline:
            raise NavigationError('Navigation timed out; no complete result.')

    def matches(self, name):
        return self.db.execute("SELECT * FROM nodes WHERE scope_id=? AND validity='current' AND (id=? OR title=?) ORDER BY id",
                               (self.scope, name, name)).fetchall()

    def resolve(self, name):
        self.check_time()
        if name in ROOT_ALIASES:
            return self.root
        if name.startswith('@') and '/' in name:
            scope, id_ = name[1:].split('/', 1)
            try:
                scope, id_ = unquote(scope, errors='strict'), unquote(id_, errors='strict')
            except UnicodeError as exc:
                raise NavigationError('Invalid qualified node argument.') from exc
            if scope != self.scope:
                raise NavigationError('Qualified node belongs to another scope; this connection uses ' + compact(self.scope))
            found = self.db.execute("SELECT * FROM nodes WHERE scope_id=? AND id=? AND validity='current'", (self.scope, id_)).fetchall()
        else:
            id_ = name
            found = self.matches(name)
        if len(found) == 1:
            return found[0]
        if not found:
            old = self.db.execute('SELECT validity FROM nodes WHERE scope_id=? AND id=?', (self.scope, id_)).fetchone()
            if old:
                raise NavigationError('Node ' + compact(name) + ' is not current (' + old['validity'] + ').')
            raise NavigationError('No current node matches ' + compact(name) + '; this does not prove source absence.')
        examples = ' ; '.join(quote_command(['evomneme', 'nodes', '--', qualified(self.scope, row['id'])],
                                            self.connection.shell) for row in found[:3])
        raise NavigationError('Ambiguous node ' + compact(name) + ': ' + str(len(found)) + ' current matches. Use ' + examples)

    def argument(self, node):
        id_ = node['id']
        if id_ not in self.arguments:
            candidates = ([node['title']] if len(node['title']) <= 80 else []) + [id_]
            argument = qualified(self.scope, id_)
            for name in candidates:
                if not name or name in ROOT_ALIASES or (name.startswith('@') and '/' in name):
                    continue
                matches = self.matches(name)
                if len(matches) == 1 and matches[0]['id'] == id_:
                    argument = name
                    break
            self.arguments[id_] = argument
        return self.arguments[id_]

    def edges_sql(self, ids, count=False):
        predicate = '(e.source_id=? OR e.target_id=?)'
        bindings = [self.scope, ids[0], ids[0]]
        if len(ids) == 2:
            predicate = '((e.source_id=? AND e.target_id=?) OR (e.source_id=? AND e.target_id=?))'
            bindings = [self.scope, ids[0], ids[1], ids[1], ids[0]]
        sql = ''' FROM edges e
            JOIN nodes s ON s.scope_id=e.scope_id AND s.id=e.source_id AND s.validity='current'
            JOIN nodes t ON t.scope_id=e.scope_id AND t.id=e.target_id AND t.validity='current'
            WHERE e.scope_id=? AND e.validity='current' AND ''' + predicate
        return ('SELECT count(*)' + sql if count else 'SELECT e.*' + sql + ' ORDER BY e.id'), bindings

    def count(self, ids):
        return self.db.execute(*self.edges_sql(ids, count=True)).fetchone()[0]

    def evidence(self, node=None, edge=None):
        column, id_ = ('node_id', node) if node is not None else ('edge_id', edge)
        return [dict(description=row['description'], validity=row['validity'],
                     **location(row)) for row in self.db.execute(
            'SELECT * FROM evidence WHERE scope_id=? AND ' + column + '=? ORDER BY id', (self.scope, id_))]

    def node_card(self, node):
        self.check_time()
        return dict(argument=self.argument(node), type=node['kind'], title=node['title'],
                    summary=node['summary'], confidence=node['confidence'], validity=node['validity'],
                    locator=location(node), evidence=self.evidence(node=node['id']), link_count=self.count([node['id']]),
                    links_command=quote_command(['evomneme', 'links', '--', self.argument(node)], self.connection.shell))

    def edge_card(self, edge, root_id, pair=False):
        self.check_time()
        source = self.db.execute('SELECT * FROM nodes WHERE scope_id=? AND id=?', (self.scope, edge['source_id'])).fetchone()
        target = self.db.execute('SELECT * FROM nodes WHERE scope_id=? AND id=?', (self.scope, edge['target_id'])).fetchone()
        direction = 'self' if source['id'] == target['id'] else 'outgoing' if source['id'] == root_id else 'incoming'
        neighbor = target if source['id'] == root_id else source
        card = dict(direction=direction, kind=edge['kind'], neighbor=self.argument(neighbor),
                    title=neighbor['title'], summary=neighbor['summary'], neighbor_confidence=neighbor['confidence'],
                    relationship_summary=edge['summary'], confidence=edge['confidence'],
                    validity=edge['validity'], resolution=edge['resolution'],
                    nodes_command=quote_command(['evomneme', 'nodes', '--', self.argument(neighbor)],
                                                self.connection.shell))
        if pair:
            card.update(source=self.argument(source), target=self.argument(target),
                        locator=location(edge), evidence=self.evidence(edge=edge['id']))
        return card


def navigate(connection, command, names, all_output=False, timeout=TIMEOUT_SECONDS):
    """Return one complete UTF-8 text result or raise; never emit partial cards."""
    if command not in ('nodes', 'links') or not names or (command == 'links' and len(names) > 2):
        raise NavigationError('Use nodes NAME [NAME ...], links NAME, or links NAME1 NAME2.')
    reader = None
    try:
        reader = Reader(connection, timeout=timeout)
        selected = [reader.resolve(name) for name in names]
        if command == 'nodes':
            selected = list({node['id']: node for node in selected}.values())
            count = len(selected)
            cards = (reader.node_card(node) for node in selected)
        else:
            ids = [node['id'] for node in selected]
            count = reader.count(ids)
            cards = (reader.edge_card(edge, ids[0], pair=len(ids) == 2)
                     for edge in reader.db.execute(*reader.edges_sql(ids)))
        chunks = []
        used = 0

        def append(line):
            nonlocal used
            reader.check_time()
            used += len((line + '\n').encode('utf-8'))
            if not all_output and used > OUTPUT_BYTES:
                retry = quote_command(['evomneme', command, '--all', '--', *names], connection.shell)
                raise NavigationError('Output exceeds 65536 bytes; no cards emitted. scope=' + compact(connection.scope)
                                      + '; ' + command + '=' + str(count) + '. Full output: ' + retry)
            chunks.append(line + '\n')

        append('scope=' + compact(connection.scope) + ' status=current-knowledge shell=' + connection.shell
               + ' ' + command + '=' + str(count))
        for warning in reader.warnings:
            append('warning=' + compact(warning))
        for card in cards:
            append(compact(card))
        append('complete scope=' + compact(connection.scope) + ' ' + command + '=' + str(count)
               + '; source completeness is not established')
        reader.check_time()
        return ''.join(chunks)
    except sqlite3.Error as exc:
        if (reader is not None and time.monotonic() >= reader.deadline) or 'interrupted' in str(exc).lower():
            raise NavigationError('Navigation timed out; no complete result.') from exc
        raise NavigationError('Cannot read the bound graph: ' + str(exc)) from exc
    finally:
        if reader is not None:
            reader.close()
