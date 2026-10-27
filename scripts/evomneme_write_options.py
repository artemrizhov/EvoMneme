"""Optional write attribution, compact rendering and source snapshot checks."""
import hashlib
from pathlib import Path

CONTEXT_FIELDS = ('chat_id', 'chat_title', 'session_id', 'session_title', 'agent_id', 'agent_name')


def configure(parser, stale=False, source=False):
    parser.add_argument('--compact', action='store_true', help='Return identity and changed fields without full stored values; same atomic audit history.')
    for key in CONTEXT_FIELDS:
        parser.add_argument('--' + key.replace('_', '-'), help='Known activity ' + key + '; omit unknown values.')
    if stale:
        parser.add_argument('--expect-updated-at', help='Reject unless the selected row has this exact updated_at value.')
    if source:
        parser.add_argument('--verify-source', action='store_true', help='Verify final locator SHA-256 and line bounds within scope worktree; recheck before commit.')


def context(args):
    result = {key: getattr(args, key) for key in CONTEXT_FIELDS if getattr(args, key, None) is not None}
    return validate_context(result)


def validate_context(value):
    result = dict(value or {})
    if set(result) - set(CONTEXT_FIELDS):
        raise ValueError('Unknown activity context field')
    if any(not isinstance(text, str) or not text.strip() or len(text) > 200 for text in result.values()):
        raise ValueError('Activity context values must be nonempty text of at most 200 characters')
    return result


def guard(row, expected):
    if expected is not None and row['updated_at'] != expected:
        raise ValueError('Stale write: updated_at differs from --expect-updated-at')


def snapshot(connection, row, require_hash=True, check=None):
    """Validate bytes and locations, without interpreting source semantics."""
    for key in ('line_start', 'line_end'):
        if row.get(key) is not None and (type(row[key]) is not int or row[key] < 1):
            raise ValueError('Source ' + key + ' must be a positive integer or NULL')
    if row.get('line_end') is not None and (row.get('line_start') is None or row['line_end'] < row['line_start']):
        raise ValueError('Source line_end requires line_start and must be >= line_start')
    locator = row.get('source_path')
    if not isinstance(locator, str) or not locator.strip():
        raise ValueError('--verify-source requires a source_path')
    relative = Path(locator)
    if relative.is_absolute() or relative.drive:
        raise ValueError('Source path must be relative to the bound source worktree')
    root = Path(connection.scope_worktree).resolve(strict=True)
    path = (root / relative).resolve(strict=True)
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError('Source path escapes the bound source worktree or is not a file')
    digest = hashlib.sha256()
    lines, last = 0, b''
    with path.open('rb') as stream:
        while block := stream.read(65536):
            if check is not None:
                check()
            digest.update(block)
            lines += block.count(b'\n') + block.count(b'\r') - block.count(b'\r\n')
            if last == b'\r' and block.startswith(b'\n'):
                lines -= 1
            last = block[-1:]
    lines += bool(last and last not in (b'\n', b'\r'))
    identity = digest.hexdigest()
    supplied = row.get('source_hash')
    if require_hash and (not isinstance(supplied, str) or not supplied):
        raise ValueError('--verify-source requires an expected SHA-256 source_hash')
    if supplied is not None and supplied != identity:
        raise ValueError('Source SHA-256 does not match source_hash')
    for key in ('line_start', 'line_end'):
        if row.get(key) is not None and row[key] > lines:
            raise ValueError('Source ' + key + ' exceeds file line bounds')
    return (locator, str(path), identity)


def verify_unchanged(connection, expected, check=None):
    actual = snapshot(connection, {'source_path': expected[0]}, require_hash=False, check=check)
    if actual != expected:
        raise ValueError('Source changed before commit; command rolled back')
