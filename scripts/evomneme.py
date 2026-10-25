#!/usr/bin/env python3
"""Optional dependency-free SQLite stewardship for agent-authored knowledge.

Reasoning, source inspection and integration authorization belong to the agent.
This helper enforces storage, provenance, scope and transaction boundaries.
"""

import argparse
import contextlib
import datetime
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile

SCHEMA_VERSION = 2
BUSY_TIMEOUT_MS = 10000
MAX_RESULTS = 100
MAX_DEPTH = 5
MAX_TEXT = 12000
MAX_BATCH = 1000
SQL_PROGRESS_STEPS = 1000
SQL_PROGRESS_CALLS = 1000
STATE_NAME = '.evomneme'
LOADER_START = '<!-- evomneme:loader:start -->'
LOADER_END = '<!-- evomneme:loader:end -->'
TOOL_CHARTER_MARKER = '# Founding Charter: Autonomous Project Knowledge System'
TOOL_ROOT = Path(__file__).resolve().parent.parent
CONFIDENCES = {'confirmed', 'inferred', 'uncertain'}
VALIDITIES = {'current', 'stale', 'superseded'}
SNAPSHOT_EXCLUDED = {'.git', STATE_NAME, '.evomneme-tests'}
NON_GIT_EXCLUDED = SNAPSHOT_EXCLUDED | {'node_modules', '.venv', '__pycache__'}


class KnowledgeError(Exception):
    """An actionable storage or input failure, safe to show without a traceback."""


def utcnow():
    """Return a sortable UTC timestamp for provenance and migrations."""
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def digest(data):
    """Hash bytes without persisting their private contents."""
    return hashlib.sha256(data).hexdigest()


def git(root, *args, optional=False):
    """Run the existing Git integration in root; fail explicitly on errors."""
    result = subprocess.run(['git', '-C', str(root), *args], capture_output=True)
    if result.returncode:
        if optional and result.returncode == 1:
            return None
        raise KnowledgeError('Git failed: ' + result.stderr.decode('utf-8', 'replace').strip())
    return result.stdout


def inside(root, path):
    """Resolve path and reject traversal or symlink escapes from root."""
    resolved = path.resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise KnowledgeError('Source path must remain inside the host project: ' + str(path))
    return resolved


def excluded_path(path, excluded):
    """Compare excluded components using the host platform's path case rules."""
    components = Path(path).parts
    if os.name == 'nt':
        components = [component.casefold() for component in components]
    return bool(excluded.intersection(components))


def file_hash(path):
    """Hash a source file incrementally, treating absent files as deleted."""
    if not path.exists():
        return None
    if not path.is_file():
        raise KnowledgeError('Expected a regular source file: ' + str(path))
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(65536), b''):
            value.update(chunk)
    return value.hexdigest()


def create_schema(connection):
    """Apply the portable schema inside the caller's identity transaction."""
    source = (Path(__file__).resolve().parent.parent / 'schema.sql').read_text(encoding='utf-8')
    statement = ''
    for line in source.splitlines(keepends=True):
        if line.lstrip().startswith('--'):
            continue
        statement += line
        if sqlite3.complete_statement(statement):
            command = statement.strip()
            if command.upper() not in {'BEGIN IMMEDIATE;', 'COMMIT;', 'PRAGMA FOREIGN_KEYS = ON;'}:
                connection.execute(command)
            statement = ''


def git_snapshot(root, revision, ancestors=()):
    """Hash only changed Git content, following dirty gitlinks without initializing them."""
    root = root.resolve()
    if root in ancestors:
        raise KnowledgeError('Cyclic Git submodule path is not supported')
    if revision == '(unborn)':
        changed = git(root, 'ls-files', '-z')
    else:
        # Ignore settings may suppress submodule dirtiness; scope cannot honor that.
        changed = git(root, 'diff', '--ignore-submodules=none', '--name-only', '-z', 'HEAD')
    untracked = git(root, 'ls-files', '--others', '--exclude-standard', '-z')
    names = set(os.fsdecode(x) for x in (changed + untracked).split(b'\0') if x)
    # Read gitlink metadata even when clean, so initialization state and checked-out
    # submodule revisions affect scope without reading clean tracked source bytes.
    entries = git(root, 'ls-files', '--stage', '-z').split(b'\0')
    gitlinks = {os.fsdecode(entry.split(b'\t', 1)[1]): entry.split(b'\t', 1)[0].split()[1].decode('ascii')
                for entry in entries if entry.startswith(b'160000 ')}
    names.update(gitlinks)
    value = hashlib.sha256()
    for name in sorted(names):
        if excluded_path(name, SNAPSHOT_EXCLUDED):
            continue
        path = inside(root, root / name)
        value.update(name.encode('utf-8', 'surrogateescape'))
        gitlink = gitlinks.get(name)
        if gitlink is not None:
            value.update(('gitlink:' + gitlink).encode())
            if not (path / '.git').exists():
                value.update(b'(uninitialized)')
                continue
            subroot = Path(os.fsdecode(git(path, 'rev-parse', '--show-toplevel')).strip()).resolve()
            if subroot != path:
                raise KnowledgeError('Git submodule root disagrees with its confined gitlink path')
            subrevision = git(path, 'rev-parse', '--verify', '--quiet', 'HEAD', optional=True)
            subrevision = subrevision.decode().strip() if subrevision else '(unborn)'
            value.update(subrevision.encode())
            value.update(git_snapshot(path, subrevision, (*ancestors, root)).encode())
        else:
            value.update((file_hash(path) or '(deleted)').encode())
    return value.hexdigest()


class Host:
    """Resolve one host identity and its current code scope without activation."""

    def __init__(self, project):
        self.root = Path(project).resolve(strict=True)
        if not self.root.is_dir():
            raise KnowledgeError('Project must be a directory')
        # A .git path marks Git intent; do not mask a broken Git integration.
        parent = self.root
        while parent != parent.parent and not (parent / '.git').exists():
            parent = parent.parent
        self.is_git = (parent / '.git').exists()
        if self.is_git:
            self.root = Path(git(self.root, 'rev-parse', '--show-toplevel').decode().strip()).resolve()
            common = git(self.root, 'rev-parse', '--path-format=absolute', '--git-common-dir').decode().strip()
            self.common = Path(common).resolve()
            worktrees = git(self.root, 'worktree', 'list', '--porcelain', '-z').split(b'\0')
            first = next(x[9:] for x in worktrees if x.startswith(b'worktree '))
            self.canonical = Path(os.fsdecode(first)).resolve()
            self.branch = git(self.root, 'symbolic-ref', '--quiet', '--short', 'HEAD', optional=True)
            self.branch = self.branch.decode().strip() if self.branch else '(detached)'
            revision = git(self.root, 'rev-parse', '--verify', '--quiet', 'HEAD', optional=True)
            self.revision = revision.decode().strip() if revision else '(unborn)'
        else:
            self.common = None
            self.canonical = self.root
            self.branch = '(none)'
            self.revision = '(none)'
        for location in {self.root, self.canonical}:
            charter = location / 'PROJECT_CHARTER.md'
            if location == TOOL_ROOT or (charter.is_file() and TOOL_CHARTER_MARKER in charter.read_text(encoding='utf-8-sig')):
                raise KnowledgeError('EvoMneme must not be activated or used in its own tool repository, forks or worktrees. Use isolated host fixtures for tests.')
        state_path = self.canonical / STATE_NAME
        if state_path.is_symlink():
            raise KnowledgeError('Project knowledge state must not be a symlink')
        self.state = inside(self.canonical, state_path)
        self.database = inside(self.canonical, self.state / 'knowledge.sqlite3')
        if (self.state / 'knowledge.sqlite3').is_symlink():
            raise KnowledgeError('Project knowledge database must not be a symlink')
        self.identity = digest(os.fsencode(str(self.canonical)))
        self.snapshot = self._snapshot()
        self.scope = digest(json.dumps([self.branch, str(self.root), self.revision, self.snapshot]).encode())

    def _snapshot(self):
        """Distinguish dirty same-HEAD content while excluding Git-ignored trees."""
        if self.is_git:
            return git_snapshot(self.root, self.revision)
        value = hashlib.sha256()
        # Non-Git hosts have no ignore API; their scope is conservative.
        names = set()
        for directory, dirs, files in os.walk(self.root, followlinks=False):
            dirs[:] = [x for x in dirs if not excluded_path(x, NON_GIT_EXCLUDED)]
            names.update(str((Path(directory) / name).relative_to(self.root)).replace('\\', '/') for name in files)
        for name in sorted(names):
            if excluded_path(name, NON_GIT_EXCLUDED):
                continue
            path = inside(self.root, self.root / name)
            value.update(name.encode('utf-8', 'surrogateescape'))
            value.update((file_hash(path) or '(deleted)').encode())
        return value.hexdigest()

    def source(self, name):
        """Normalize project-relative source names and capture their current hash."""
        if name is None:
            return None, None
        if not isinstance(name, str) or not name or Path(name).is_absolute():
            raise KnowledgeError('source_path must be a nonempty project-relative path')
        path = inside(self.root, self.root / name)
        relative = path.relative_to(self.root).as_posix()
        excluded = SNAPSHOT_EXCLUDED if self.is_git else NON_GIT_EXCLUDED
        if excluded_path(name, excluded) or excluded_path(relative, excluded):
            raise KnowledgeError('Source path is outside supported snapshot coverage: ' + relative)
        if self.is_git:
            repository = self.root
            for parent in path.parents:
                if parent == self.root:
                    break
                if (parent / '.git').exists():
                    repository = parent
                    break
            local_name = path.relative_to(repository).as_posix()
            if git(repository, 'check-ignore', '--', local_name, optional=True):
                raise KnowledgeError('Ignored files cannot be captured as source evidence')
        source_hash = file_hash(path)
        if source_hash is None:
            raise KnowledgeError('Source does not exist: ' + relative)
        return relative, source_hash

    def exclude_state(self):
        """Keep canonical state out of Git through its shared local exclude file."""
        if not self.is_git:
            return
        tracked = git(self.canonical, 'ls-files', '--', STATE_NAME)
        if tracked:
            raise KnowledgeError('Host already tracks .evomneme state; untrack it before initializing')
        exclude = self.common / 'info' / 'exclude'
        exclude.parent.mkdir(parents=True, exist_ok=True)
        content = exclude.read_text(encoding='utf-8') if exclude.exists() else ''
        if '/.evomneme/' not in content.splitlines():
            with exclude.open('a', encoding='utf-8', newline='\n') as stream:
                stream.write(('\n' if content and not content.endswith('\n') else '') + '/.evomneme/\n')

    def scope_info(self):
        """Describe scope explicitly so historical results cannot imply currency."""
        return {'id': self.scope, 'branch': self.branch, 'worktree': str(self.root),
                'revision': self.revision, 'snapshot': self.snapshot}


@contextlib.contextmanager
def connect(host, initialize=False, readonly=False):
    """Open and validate an owned DB; writers serialize with bounded busy waits."""
    if initialize:
        host.exclude_state()
        host.state.mkdir(exist_ok=True)
    if not host.database.exists() and not initialize:
        raise KnowledgeError('No project index. Run init in an authorized host project first.')
    uri = host.database.as_uri() + ('?mode=ro' if readonly else '?mode=rwc')
    connection = sqlite3.connect(uri, uri=True, timeout=BUSY_TIMEOUT_MS / 1000, isolation_level=None)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute('PRAGMA foreign_keys=ON')
        connection.execute('PRAGMA busy_timeout=' + str(BUSY_TIMEOUT_MS))
        version = connection.execute('PRAGMA user_version').fetchone()[0]
        if version > SCHEMA_VERSION:
            raise KnowledgeError('Database schema is newer than this helper; update the helper. No downgrade attempted.')
        if version == 0:
            with transaction(connection):
                # Recheck after taking the write lock: another initializer may win.
                version = connection.execute('PRAGMA user_version').fetchone()[0]
                if version == 0:
                    if not initialize or connection.execute("SELECT 1 FROM sqlite_master WHERE type='table'").fetchone():
                        raise KnowledgeError('Unrecognized database schema; preserve it and inspect before recovery.')
                    create_schema(connection)
                    connection.execute('INSERT INTO metadata VALUES (?,?)', ('project_identity', host.identity))
                    connection.execute('INSERT INTO metadata VALUES (?,?)', ('canonical_root', str(host.canonical)))
                    version = SCHEMA_VERSION
        owner = connection.execute("SELECT value FROM metadata WHERE key='project_identity'").fetchone()
        if not owner or owner[0] != host.identity:
            raise KnowledgeError('Database belongs to another project identity; do not reuse or merge stores implicitly.')
        declared = connection.execute("SELECT value FROM metadata WHERE key='schema_version'").fetchone()
        if not declared or declared[0] != str(version):
            raise KnowledgeError('Database schema metadata disagrees with PRAGMA user_version; preserve and inspect the database before migration.')
        if version == 1:
            if readonly:
                raise KnowledgeError('Schema migration needed. Run init before read-only queries.')
            # v1 has the same data shape; v2 adds provenance lookup indexes.
            with transaction(connection):
                connection.execute('CREATE INDEX IF NOT EXISTS evidence_record ON evidence(scope_id,record_id)')
                connection.execute('CREATE INDEX IF NOT EXISTS evidence_relation ON evidence(scope_id,relation_id)')
                connection.execute("UPDATE metadata SET value='2' WHERE key='schema_version'")
                connection.execute('PRAGMA user_version=2')
                journal(connection, 'migration', 'schema 1 -> 2: evidence lookup indexes')
        if not readonly:
            # WAL and SQLite locking permit concurrent readers without lost writes.
            connection.execute('PRAGMA journal_mode=WAL')
            connection.execute('PRAGMA synchronous=FULL')
        yield connection
    except sqlite3.IntegrityError as exc:
        raise KnowledgeError('Knowledge update rejected: ' + str(exc) + '. The transaction was rolled back; check IDs, scope, and confidence/validity values.') from exc
    except sqlite3.DatabaseError as exc:
        code = getattr(exc, 'sqlite_errorcode', None)
        if code in {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED}:
            raise KnowledgeError('SQLite writer is busy after the bounded timeout; stop overlapping long transactions and retry this same operation.') from exc
        if code in {sqlite3.SQLITE_CORRUPT, sqlite3.SQLITE_NOTADB}:
            raise KnowledgeError('SQLite failure: ' + str(exc) + '. Preserve the database and its -wal/-shm files; stop writers, verify a backup with SQLite integrity_check, then restore or rebuild from source. Never delete the only copy.') from exc
        raise KnowledgeError('SQLite operation failed: ' + str(exc) + '. No alternate integration was used; inspect the query or file permissions before retrying.') from exc
    finally:
        connection.close()


@contextlib.contextmanager
def transaction(connection):
    """Commit an entire batch or roll back every change on any failure."""
    connection.execute('BEGIN IMMEDIATE')
    try:
        yield
        connection.execute('COMMIT')
    except BaseException:
        connection.execute('ROLLBACK')
        raise


def journal(connection, action, detail):
    """Retain concise local operational history without source contents."""
    connection.execute('INSERT INTO history(happened_at,action,detail) VALUES (?,?,?)', (utcnow(), action, detail))


def text_field(item, key, default=None):
    """Validate bounded text input while preserving meaningful agent wording."""
    value = item.get(key, default)
    if not isinstance(value, str) or not value or len(value) > MAX_TEXT:
        raise KnowledgeError(key + ' must be nonempty text of at most ' + str(MAX_TEXT) + ' characters')
    return value


def classification(item):
    """Keep uncertain/inferred knowledge visibly distinct from confirmed facts."""
    confidence = item.get('confidence', 'uncertain')
    validity = item.get('validity', 'current')
    if confidence not in CONFIDENCES or validity not in VALIDITIES:
        raise KnowledgeError('Invalid confidence or validity')
    return confidence, validity


def update(connection, host, batch):
    """Upsert records, graph edges and evidence atomically in the current scope."""
    if not isinstance(batch, dict) or set(batch) - {'records', 'relations', 'evidence'}:
        raise KnowledgeError('Batch must contain only records, relations and evidence arrays')
    for key in ('records', 'relations', 'evidence'):
        if not isinstance(batch.get(key, []), list) or len(batch.get(key, [])) > MAX_BATCH:
            raise KnowledgeError(key + ' must be a bounded array')
        if not all(isinstance(x, dict) for x in batch.get(key, [])):
            raise KnowledgeError('Every update item must be an object')
    with transaction(connection):
        connection.execute('INSERT OR IGNORE INTO scopes VALUES (?,?,?,?,?,?)',
                           (host.scope, host.branch, str(host.root), host.revision, host.snapshot, utcnow()))
        for item in batch.get('records', []):
            confidence, validity = classification(item)
            source, source_hash = host.source(item.get('source_path'))
            first, last = item.get('line_start'), item.get('line_end')
            if any(x is not None and (type(x) is not int or x < 1) for x in (first, last)) or (first and last and first > last):
                raise KnowledgeError('Source line numbers must be positive and ordered')
            if (first or last) and source is None:
                raise KnowledgeError('Source line numbers require source_path')
            connection.execute('INSERT INTO records VALUES (?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(scope_id,id) DO UPDATE SET kind=excluded.kind,title=excluded.title,summary=excluded.summary,confidence=excluded.confidence,validity=excluded.validity,source_path=excluded.source_path,source_hash=excluded.source_hash,line_start=excluded.line_start,line_end=excluded.line_end,updated_at=excluded.updated_at',
                               (host.scope, text_field(item, 'id'), text_field(item, 'kind'), text_field(item, 'title'), text_field(item, 'summary'), confidence, validity, source, source_hash, first, last, utcnow()))
        for item in batch.get('relations', []):
            confidence, validity = classification(item)
            source, source_hash = host.source(item.get('source_path'))
            connection.execute('INSERT INTO relations VALUES (?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(scope_id,id) DO UPDATE SET source_id=excluded.source_id,target_id=excluded.target_id,kind=excluded.kind,summary=excluded.summary,confidence=excluded.confidence,validity=excluded.validity,source_path=excluded.source_path,source_hash=excluded.source_hash,updated_at=excluded.updated_at',
                               (host.scope, text_field(item, 'id'), text_field(item, 'source_id'), text_field(item, 'target_id'), text_field(item, 'kind'), text_field(item, 'summary'), confidence, validity, source, source_hash, utcnow()))
        for item in batch.get('evidence', []):
            source, source_hash = host.source(item.get('source_path'))
            record, relation = item.get('record_id'), item.get('relation_id')
            if (record is None) == (relation is None):
                raise KnowledgeError('Evidence requires exactly one record_id or relation_id')
            connection.execute('INSERT INTO evidence VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(scope_id,id) DO UPDATE SET record_id=excluded.record_id,relation_id=excluded.relation_id,description=excluded.description,source_path=excluded.source_path,source_hash=excluded.source_hash,validity=excluded.validity,updated_at=excluded.updated_at',
                               (host.scope, text_field(item, 'id'), record, relation, text_field(item, 'description'), source, source_hash, item.get('validity', 'current'), utcnow()))
        invalidate_dependents(connection)
        if Host(host.root).scope != host.scope:
            raise KnowledgeError('Code scope changed during the batch; transaction rolled back. Reinspect sources and retry in the current scope.')
        journal(connection, 'update', json.dumps({key: len(batch.get(key, [])) for key in ('records', 'relations', 'evidence')}))
    return {'updated': {key: len(batch.get(key, [])) for key in ('records', 'relations', 'evidence')}, 'scope': host.scope_info()}


def stale_edges(connection):
    """Invalidate relationships whose endpoint claims need renewed verification."""
    connection.execute("UPDATE relations SET validity='stale' WHERE validity='current' AND (EXISTS(SELECT 1 FROM records r WHERE r.scope_id=relations.scope_id AND r.id=relations.source_id AND r.validity!='current') OR EXISTS(SELECT 1 FROM records r WHERE r.scope_id=relations.scope_id AND r.id=relations.target_id AND r.validity!='current'))")


def invalidate_dependents(connection):
    """Propagate stale evidence and endpoint claims inside the active transaction."""
    connection.execute("UPDATE records SET validity='stale' WHERE validity='current' AND EXISTS(SELECT 1 FROM evidence e WHERE e.scope_id=records.scope_id AND e.record_id=records.id AND e.validity='stale')")
    connection.execute("UPDATE relations SET validity='stale' WHERE validity='current' AND EXISTS(SELECT 1 FROM evidence e WHERE e.scope_id=relations.scope_id AND e.relation_id=relations.id AND e.validity='stale')")
    stale_edges(connection)


def reconcile(connection, host):
    """Recheck this worktree/branch/HEAD across its dirty content snapshots."""
    counts = {'records': 0, 'relations': 0, 'evidence': 0}
    with transaction(connection):
        for table in counts:
            rows = connection.execute('SELECT x.scope_id,x.id,x.source_path,x.source_hash FROM ' + table + " x JOIN scopes s ON s.id=x.scope_id WHERE s.worktree=? AND s.branch=? AND s.revision=? AND x.source_path IS NOT NULL AND x.validity='current'", (str(host.root), host.branch, host.revision)).fetchall()
            for row in rows:
                path = inside(host.root, host.root / row['source_path'])
                if file_hash(path) != row['source_hash']:
                    connection.execute('UPDATE ' + table + " SET validity='stale',updated_at=? WHERE scope_id=? AND id=?", (utcnow(), row['scope_id'], row['id']))
                    counts[table] += 1
        invalidate_dependents(connection)
        journal(connection, 'reconcile', json.dumps(counts))
    return {'direct_invalidations': counts, 'scope': host.scope_info(), 'note': 'Dependent claims and relationships also invalidated; refresh requires source inspection and an explicit update.'}


def decorate(row, host):
    """Attach scope compatibility and suppress currency claims for old snapshots."""
    result = dict(row)
    result['scope_matches'] = result['scope_id'] == host.scope
    result['effective_validity'] = result['validity'] if result['scope_matches'] else 'out_of_scope'
    for field in ('summary', 'description'):
        if field in result:
            result[field] = result[field][:600]
    return result


def filters(alias, host, include_stale, all_scopes):
    """Build shared, parameterized filtering for compact graph retrieval."""
    clauses, parameters = [], []
    if not all_scopes:
        clauses.append(alias + '.scope_id=?')
        parameters.append(host.scope)
    if not include_stale:
        clauses.append(alias + ".validity='current'")
    return clauses, parameters


def search(connection, host, query, limit=20, include_stale=False, all_scopes=False):
    """Find short semantic locators, including prior decisions and findings."""
    clauses, params = filters('r', host, include_stale, all_scopes)
    clauses.append("(r.id LIKE ? ESCAPE '\\' OR r.title LIKE ? ESCAPE '\\' OR r.summary LIKE ? ESCAPE '\\' OR r.kind LIKE ? ESCAPE '\\')")
    pattern = '%' + query.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
    params.extend([pattern] * 4)
    params.append(min(MAX_RESULTS, max(1, limit)))
    rows = connection.execute('SELECT r.scope_id,r.id,r.kind,r.title,substr(r.summary,1,600) AS summary,r.confidence,r.validity,r.source_path,r.line_start,r.line_end,s.branch,s.worktree,s.revision,s.snapshot FROM records r JOIN scopes s ON s.id=r.scope_id WHERE ' + ' AND '.join(clauses) + ' ORDER BY r.updated_at DESC,r.id LIMIT ?', params).fetchall()
    return {'records': [decorate(row, host) for row in rows], 'scope': host.scope_info(), 'bounded': True}


def traverse(connection, host, record_id, depth=1, limit=20, include_stale=False, all_scopes=False):
    """Follow both edge directions incrementally without unbounded recursion."""
    limit = min(MAX_RESULTS, max(1, limit))
    depth = min(MAX_DEPTH, max(0, depth))
    clauses, params = filters('r', host, include_stale, all_scopes)
    clauses.append('r.id=?')
    params.append(record_id)
    roots = connection.execute('SELECT r.* FROM records r WHERE ' + ' AND '.join(clauses) + ' LIMIT ?', [*params, limit]).fetchall()
    records = {(row['scope_id'], row['id']): decorate(row, host) for row in roots}
    frontier = list(records)
    relations = {}
    for _ in range(depth):
        next_frontier = []
        for scope, current in frontier:
            condition = '' if include_stale else " AND validity='current'"
            rows = connection.execute('SELECT * FROM relations WHERE scope_id=? AND (source_id=? OR target_id=?)' + condition + ' ORDER BY id LIMIT ?', (scope, current, current, limit)).fetchall()
            for row in rows:
                if len(relations) >= limit:
                    break
                edge_key = (scope, row['id'])
                relations[edge_key] = decorate(row, host)
                for target in (row['source_id'], row['target_id']):
                    key = (scope, target)
                    if key not in records and len(records) < limit:
                        record = connection.execute('SELECT * FROM records WHERE scope_id=? AND id=?' + condition, key).fetchone()
                        if record:
                            records[key] = decorate(record, host)
                            next_frontier.append(key)
        frontier = next_frontier
        if not frontier:
            break
    evidence = []
    for scope, key in records:
        if len(evidence) >= limit:
            break
        condition = '' if include_stale else " AND validity='current'"
        rows = connection.execute('SELECT * FROM evidence WHERE scope_id=? AND record_id=?' + condition + ' LIMIT ?', (scope, key, limit - len(evidence))).fetchall()
        evidence.extend(decorate(row, host) for row in rows)
    for scope, key in relations:
        if len(evidence) >= limit:
            break
        condition = '' if include_stale else " AND validity='current'"
        rows = connection.execute('SELECT * FROM evidence WHERE scope_id=? AND relation_id=?' + condition + ' LIMIT ?', (scope, key, limit - len(evidence))).fetchall()
        evidence.extend(decorate(row, host) for row in rows)
    return {'records': list(records.values()), 'relations': list(relations.values()), 'evidence': evidence,
            'scope': host.scope_info(), 'bounded': True, 'depth': depth}


def readonly_sql(connection, query):
    """Run a single read-only, bounded query with a VM execution budget."""
    allowed = {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_FUNCTION, sqlite3.SQLITE_RECURSIVE}
    dangerous = {'load_extension', 'writefile', 'readfile'}
    connection.set_authorizer(lambda action, a, b, db, trigger: sqlite3.SQLITE_OK if action in allowed and not (action == sqlite3.SQLITE_FUNCTION and (b or '').lower() in dangerous) else sqlite3.SQLITE_DENY)
    calls = 0

    def budget():
        """Abort SQL that exceeds its VM step budget."""
        nonlocal calls
        calls += 1
        return int(calls > SQL_PROGRESS_CALLS)

    connection.set_progress_handler(budget, SQL_PROGRESS_STEPS)
    previous_length = connection.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, MAX_TEXT * MAX_RESULTS)
    try:
        cursor = connection.execute(query)
        rows = cursor.fetchmany(MAX_RESULTS + 1)
        return {'rows': [dict(row) for row in rows[:MAX_RESULTS]], 'truncated': len(rows) > MAX_RESULTS,
                'note': 'Raw SQL includes historical scopes; inspect scopes and validity explicitly.'}
    finally:
        connection.set_authorizer(None)
        connection.set_progress_handler(None, 0)
        connection.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, previous_length)


def integrate(host, skill):
    """Install an authorized live pointer, preserving all surrounding host text."""
    skill = Path(skill).resolve(strict=True)
    if not skill.is_file() or any(x in str(skill) for x in ('\n', '\r', '<', '>')):
        raise KnowledgeError('Skill must be a readable file with a safe path')
    skill.read_text(encoding='utf-8-sig')
    target = inside(host.root, host.root / 'AGENTS.md')
    original = target.read_bytes() if target.exists() else b''
    content = original.decode('utf-8')
    if content.count(LOADER_START) != content.count(LOADER_END) or content.count(LOADER_START) > 1:
        raise KnowledgeError('Malformed or duplicate loader markers; inspect AGENTS.md manually')
    newline = '\r\n' if '\r\n' in content else '\n'
    block = newline.join([LOADER_START, 'For ordinary work in this authorized host project, load and follow the live EvoMneme instructions:', '[Live EvoMneme instructions](<' + skill.as_posix() + '>).', 'Read this file at session start; follow host instructions and user overrides. Do not copy its core instructions here.', LOADER_END])
    if LOADER_START in content:
        start, end = content.index(LOADER_START), content.index(LOADER_END) + len(LOADER_END)
        if content.index(LOADER_END) < start:
            raise KnowledgeError('Loader end precedes its start')
        updated = content[:start] + block + content[end:]
    else:
        updated = content + (newline * 2 if content and not content.endswith(newline * 2) else '') + block + newline
    changed = updated.encode('utf-8') != original
    if changed:
        with tempfile.NamedTemporaryFile(dir=host.root, prefix='.evomneme-loader-', delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(updated.encode('utf-8'))
        try:
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)
    editable = os.access(skill, os.W_OK)
    overrides, nested = [], []
    for directory, dirs, files in os.walk(host.root, followlinks=False):
        dirs[:] = [name for name in dirs if name not in {'.git', STATE_NAME, 'node_modules', '.venv', '__pycache__'}]
        directory = Path(directory)
        if 'AGENTS.override.md' in files:
            overrides.append(str(directory / 'AGENTS.override.md'))
        if 'AGENTS.md' in files and directory != host.root:
            nested.append(str(directory / 'AGENTS.md'))
    for ancestor in host.root.parents:
        override = ancestor / 'AGENTS.override.md'
        if override.is_file():
            overrides.append(str(override))
    return {'configured_pointer': str(target), 'skill': str(skill), 'skill_sha256': file_hash(skill),
            'changed': changed, 'skill_editable_os_check': editable,
            'fresh_session_loading': 'unverified', 'updated_instruction_loading': 'unverified',
            'integration_complete': False,
            'override_files': overrides, 'nested_instruction_files': nested,
            'note': 'Verify the loader in a fresh agent session and after an authorized skill edit. Check sandbox write permission separately. Configure/verify each other or future worktree explicitly.'}


def status(connection, host):
    """Report project ownership, scope, store location and compact counts."""
    return {'database': str(host.database), 'canonical_project': str(host.canonical), 'schema_version': SCHEMA_VERSION,
            'scope': host.scope_info(), 'records_in_scope': connection.execute('SELECT count(*) FROM records WHERE scope_id=?', (host.scope,)).fetchone()[0],
            'records_all_scopes': connection.execute('SELECT count(*) FROM records').fetchone()[0]}


def main(argv=None):
    """Expose a small JSON CLI; operational failures exit nonzero without fallback."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', default='.', help='Authorized host project; never the tool repository')
    commands = parser.add_subparsers(dest='command', required=True)
    for name in ('init', 'status', 'reconcile', 'verify'):
        commands.add_parser(name)
    update_parser = commands.add_parser('update')
    update_parser.add_argument('json_file', help='Batch JSON file, or - for stdin')
    for name in ('search', 'traverse'):
        sub = commands.add_parser(name)
        sub.add_argument('query' if name == 'search' else 'record_id')
        sub.add_argument('--limit', type=int, default=20)
        sub.add_argument('--include-stale', action='store_true')
        sub.add_argument('--all-scopes', action='store_true')
        if name == 'traverse':
            sub.add_argument('--depth', type=int, default=1)
    sql_parser = commands.add_parser('sql')
    sql_parser.add_argument('query')
    integration = commands.add_parser('integrate')
    integration.add_argument('--skill', required=True)
    args = parser.parse_args(argv)
    try:
        host = Host(args.project)
        if args.command == 'integrate':
            result = integrate(host, args.skill)
        else:
            readonly = args.command in {'status', 'search', 'traverse', 'sql', 'verify'}
            with connect(host, initialize=args.command == 'init', readonly=readonly) as connection:
                if args.command in {'init', 'status'}:
                    result = status(connection, host)
                elif args.command == 'update':
                    raw = sys.stdin.read() if args.json_file == '-' else Path(args.json_file).read_text(encoding='utf-8-sig')
                    result = update(connection, host, json.loads(raw))
                elif args.command == 'search':
                    result = search(connection, host, args.query, args.limit, args.include_stale, args.all_scopes)
                elif args.command == 'traverse':
                    result = traverse(connection, host, args.record_id, args.depth, args.limit, args.include_stale, args.all_scopes)
                elif args.command == 'reconcile':
                    result = reconcile(connection, host)
                elif args.command == 'sql':
                    result = readonly_sql(connection, args.query)
                else:
                    checks = [row[0] for row in connection.execute('PRAGMA integrity_check')]
                    foreign = [list(row) for row in connection.execute('PRAGMA foreign_key_check')]
                    result = {'ok': checks == ['ok'] and not foreign, 'integrity_check': checks, 'foreign_key_check': foreign}
                    if not result['ok']:
                        raise KnowledgeError('Database verification failed; preserve state and restore a verified backup or rebuild from source.')
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (KnowledgeError, OSError, ValueError, KeyError, TypeError, StopIteration) as exc:
        print(json.dumps({'error': str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
