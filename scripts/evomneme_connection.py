"""Explicit project-local navigation receipt; never creates or modifies a store."""
from dataclasses import dataclass
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile

from evomneme_graph import validate_schema

RECEIPT = Path('.evomneme/connection.json')


class ConnectionError(ValueError):
    pass


@dataclass(frozen=True)
class Connection:
    database: Path
    project_root: Path
    canonical_root: Path
    scope: str
    root_id: str
    shell: str
    project_identity: str | None
    scope_worktree: str
    checkpoint_revision: str | None
    warnings: tuple[str, ...] = ()


def _path(value, label):
    if not isinstance(value, str) or not value.strip() or not Path(value).is_absolute():
        raise ConnectionError(label + ' must be a nonempty absolute path')
    return Path(value).resolve()


def _read(path):
    def unique_fields(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('duplicate JSON field: ' + key)
            result[key] = value
        return result
    try:
        data = json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=unique_fields)
    except (OSError, ValueError) as exc:
        raise ConnectionError('Cannot read connection receipt ' + str(path) + ': ' + str(exc)) from exc
    if not isinstance(data, dict) or type(data.get('version', 1)) is not int or data.get('version', 1) != 1:
        raise ConnectionError('Unsupported connection receipt; expected a version 1 JSON object')
    return data


def _project_boundary(project):
    for directory in (project, *project.parents):
        if (directory / '.git').exists():
            if directory != project:
                raise ConnectionError('--project must name the Git project root, not a nested directory')
            break


def _validate_root_identity(project, canonical):
    """Different directories must be actual linked worktrees, never inferred clones."""
    if project == canonical:
        return
    environment = {key: value for key, value in os.environ.items()
                   if key.upper() not in {'GIT_DIR', 'GIT_WORK_TREE', 'GIT_COMMON_DIR', 'GIT_INDEX_FILE'}}
    def git_path(root, option):
        if not (root / '.git').exists():
            raise ConnectionError('Cannot verify linked worktree identity: both roots must be Git worktrees')
        try:
            result = subprocess.run(['git', '-C', str(root), 'rev-parse', '--path-format=absolute', option],
                                    capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=5, env=environment)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ConnectionError('Cannot verify linked worktree identity using Git: ' + str(exc)) from exc
        if result.returncode or not result.stdout.strip():
            raise ConnectionError('Cannot verify linked worktree identity using Git for ' + str(root))
        return _path(result.stdout.strip(), 'Git worktree identity path')
    common = []
    for root in (project, canonical):
        if git_path(root, '--show-toplevel') != root:
            raise ConnectionError('Linked worktree binding must use exact Git project roots')
        common.append(git_path(root, '--git-common-dir'))
    if common[0] != common[1]:
        raise ConnectionError('Project and canonical root are independent Git repositories, not linked worktrees')


def _text(data, key):
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ConnectionError('Connection receipt requires nonempty ' + key)
    return value


def _freshness(connection):
    warnings = []
    if not (connection.project_root / '.git').exists():
        return ['Source freshness cannot be verified: project has no Git checkpoint']
    try:
        def git(*args):
            result = subprocess.run(['git', '-C', str(connection.project_root), *args],
                                    capture_output=True, text=True, timeout=5)
            if result.returncode:
                raise ValueError('Git checkpoint unavailable')
            return result.stdout.strip()
        head = git('rev-parse', 'HEAD')
        if not connection.checkpoint_revision or head != connection.checkpoint_revision:
            warnings.append('Source HEAD differs from the knowledge checkpoint; verify source details')
        if git('status', '--porcelain', '--untracked-files=normal'):
            warnings.append('Source working tree has changes; verify source details against the knowledge checkpoint')
    except (OSError, ValueError, subprocess.TimeoutExpired):
        warnings.append('Source freshness cannot be verified: Git checkpoint unavailable')
    return warnings


def discover(start: Path | None = None) -> Connection:
    current = (start or Path.cwd()).resolve()
    if not current.is_dir():
        raise ConnectionError('Navigation must start in an existing project directory')
    for directory in (current, *current.parents):
        receipt = directory / RECEIPT
        if receipt.exists():
            data = _read(receipt)
            project = _path(data.get('project_root'), 'project_root')
            if project != directory:
                raise ConnectionError('Receipt project_root does not match this project; copied receipts cannot bind another clone')
            _project_boundary(project)
            connection = Connection(
                _path(data.get('database'), 'database'), project,
                _path(data.get('canonical_root'), 'canonical_root'), _text(data, 'scope'),
                _text(data, 'root_id'), data.get('shell', 'powershell' if os.name == 'nt' else 'posix'),
                data.get('project_identity'), _text(data, 'scope_worktree'), data.get('checkpoint_revision'))
            if connection.shell not in ('powershell', 'posix'):
                raise ConnectionError('Unsupported receipt shell: ' + str(connection.shell))
            if connection.project_identity is not None and not isinstance(connection.project_identity, str):
                raise ConnectionError('project_identity must be a string or null')
            if connection.checkpoint_revision is not None and not isinstance(connection.checkpoint_revision, str):
                raise ConnectionError('checkpoint_revision must be a string or null')
            if not connection.canonical_root.is_dir():
                raise ConnectionError('Canonical project directory is missing: ' + str(connection.canonical_root))
            _validate_root_identity(project, connection.canonical_root)
            _validate_root_identity(_path(connection.scope_worktree, 'scope_worktree'), connection.canonical_root)
            if not connection.database.is_file():
                raise ConnectionError('Knowledge database is missing: ' + str(connection.database))
            return Connection(**{**connection.__dict__, 'warnings': tuple(_freshness(connection))})
        if (directory / '.git').exists():
            break
    raise ConnectionError('No project connection receipt found; run evomneme connect DATABASE --scope SCOPE --root ROOT_ID')


def validate_binding(db, connection) -> list[str]:
    """Validate within the caller's read transaction, without opening another snapshot."""
    validate_schema(db)
    _validate_root_identity(connection.project_root, connection.canonical_root)
    row = db.execute('SELECT worktree, revision, branch FROM scopes WHERE id=?', (connection.scope,)).fetchone()
    if row is None:
        raise ConnectionError('Selected knowledge scope does not exist: ' + connection.scope)
    if row[0] != connection.scope_worktree:
        raise ConnectionError('Selected scope worktree changed; explicitly reconnect after investigating the binding')
    _validate_root_identity(_path(row[0], 'scope worktree'), connection.canonical_root)
    identity = db.execute("SELECT value FROM metadata WHERE key='project_identity'").fetchone()
    identity = identity[0] if identity else None
    if identity != connection.project_identity:
        raise ConnectionError('Database project identity differs from the connection receipt')
    warnings = []
    if not identity:
        warnings.append('Database has no persistent project_identity; fixed database path and captured scope are enforced, but persistent identity cannot be cross-checked')
    if row[1] != connection.checkpoint_revision:
        warnings.append('Knowledge scope checkpoint changed since connection; verify source freshness')
    if (connection.project_root / '.git').exists():
        try:
            branch = subprocess.run(['git', '-C', str(connection.project_root), 'branch', '--show-current'],
                                    capture_output=True, text=True, timeout=5)
            if branch.returncode == 0 and branch.stdout.strip() != row[2]:
                warnings.append('Source branch differs from the knowledge scope branch; verify source details')
        except (OSError, subprocess.TimeoutExpired):
            pass  # _freshness already reports that Git could not be verified.
    return warnings


def configure_parser(subparsers):
    parser = subparsers.add_parser('connect', help='Bind an existing project to an existing knowledge scope')
    parser.add_argument('database', type=Path)
    parser.add_argument('--scope', required=True)
    parser.add_argument('--root', required=True, dest='root_id')
    parser.add_argument('--project', type=Path, default=Path.cwd())
    parser.add_argument('--canonical-root', type=Path)
    parser.add_argument('--shell', choices=('powershell', 'posix'))
    parser.set_defaults(setup_handler=run_setup)


def run_setup(args) -> int:
    project = args.project.resolve()
    if not project.is_dir():
        raise ConnectionError('Project directory must already exist')
    _project_boundary(project)
    receipt = project / RECEIPT
    data = _read(receipt) if receipt.exists() else {}
    original = receipt.read_bytes() if receipt.exists() else None
    database = args.database.resolve()
    canonical = args.canonical_root.resolve() if args.canonical_root else _path(data['canonical_root'], 'canonical_root') if 'canonical_root' in data else project
    if not canonical.is_dir() or not database.is_file():
        raise ConnectionError('Canonical project directory and knowledge database must already exist')
    _validate_root_identity(project, canonical)
    for key, value in (('database', str(database)), ('project_root', str(project)),
                       ('canonical_root', str(canonical)), ('scope', args.scope), ('root_id', args.root_id)):
        if key in data and data[key] != value:
            raise ConnectionError('Existing receipt has a different ' + key + '; refusing to replace its binding')
    try:
        with closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True)) as db:
            db.execute('PRAGMA query_only=ON')
            db.execute('BEGIN')
            validate_schema(db)
            row = db.execute('SELECT worktree, revision FROM scopes WHERE id=?', (args.scope,)).fetchone()
            if not row:
                raise ConnectionError('Selected knowledge scope does not exist: ' + args.scope)
            if not db.execute("SELECT 1 FROM nodes WHERE scope_id=? AND id=? AND validity='current'", (args.scope, args.root_id)).fetchone():
                raise ConnectionError('Selected current knowledge root does not exist: ' + args.root_id)
            identity = db.execute("SELECT value FROM metadata WHERE key='project_identity'").fetchone()
            identity = identity[0] if identity else None
            if 'project_identity' in data and data['project_identity'] != identity:
                raise ConnectionError('Existing receipt project identity differs from the database')
            connection = Connection(database, project, canonical, args.scope, args.root_id,
                                    args.shell or data.get('shell', 'powershell' if os.name == 'nt' else 'posix'),
                                    identity, row[0], row[1])
            if connection.shell not in ('powershell', 'posix'):
                raise ConnectionError('Unsupported receipt shell: ' + str(connection.shell))
            if 'scope_worktree' in data and data['scope_worktree'] != row[0]:
                raise ConnectionError('Existing receipt scope worktree differs from the database')
            warnings = validate_binding(db, connection)
    except sqlite3.Error as exc:
        raise ConnectionError('Cannot read knowledge database: ' + str(exc)) from exc
    data.update({key: str(value) if isinstance(value, Path) else value
                 for key, value in connection.__dict__.items() if key != 'warnings'})
    data['version'] = 1
    receipt.parent.mkdir(exist_ok=True)
    serialized = json.dumps(data, indent=2, ensure_ascii=False) + '\n'
    if original is None:
        with receipt.open('x', encoding='utf-8') as stream:
            stream.write(serialized)
    else:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=receipt.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(serialized)
        try:
            if receipt.read_bytes() != original:
                raise ConnectionError('Connection receipt changed during setup; refusing to overwrite it')
            os.replace(temporary, receipt)
        finally:
            temporary.unlink(missing_ok=True)
    print('Connected project using ' + str(receipt))
    for warning in warnings + _freshness(connection):
        print('Warning: ' + warning)
    return 0
