"""Cheap integration status diagnostics; acceptance remains an agent decision.

No Git, subprocess, SQL, migration parsing or source hashing on this path.
Diagnostics use stderr so public JSON and API result shapes remain unchanged.
"""
from contextvars import ContextVar
from functools import wraps
import json
from pathlib import Path
import sys

REQUIRED_CONTRACT = 1
REQUIRED_SCHEMA = 3
RECEIPT = Path('.evomneme/connection.json')
_cli_active = ContextVar('evomneme_contract_cli', default=False)
MAX_RECEIPT_BYTES = 262144


def read_receipt(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('duplicate receipt field: ' + key)
            result[key] = value
        return result
    with path.open('rb') as stream:
        raw = stream.read(MAX_RECEIPT_BYTES + 1)
    if len(raw) > MAX_RECEIPT_BYTES:
        raise ValueError('receipt exceeds 256 KiB')
    data = json.loads(raw.decode('utf-8'), object_pairs_hook=unique)
    if not isinstance(data, dict):
        raise ValueError('receipt is not an object')
    return data


def status(data):
    if type(data.get('version', 1)) is not int or data.get('version', 1) != 1:
        return 'unsupported receipt format; inspect receipt before recovery'
    accepted = data.get('integration_contract_version')
    schema = data.get('verified_schema_version')
    if accepted is None:
        return 'unversioned host; inspect existing integration and every published transition'
    if type(accepted) is not int or accepted < 1:
        return 'invalid accepted contract version; inspect receipt before recovery'
    if accepted > REQUIRED_CONTRACT:
        return 'host contract is newer than this tool; use a compatible tool, never downgrade'
    if accepted < REQUIRED_CONTRACT:
        return 'pending integration transitions ' + str(accepted + 1) + '..' + str(REQUIRED_CONTRACT)
    if type(schema) is not int or schema != REQUIRED_SCHEMA:
        return 'verified schema is missing/incompatible; inspect actual database and published migrations'
    return None


def diagnostic(*, start=None, database=None, bound=False):
    """Return a warning from small local files only; never accept or migrate."""
    current = Path(start or Path.cwd()).resolve()
    selected = Path(database).resolve() if database is not None else None
    candidates = []
    for directory in (current, *current.parents):
        path = directory / RECEIPT
        if path.is_file():
            candidates.append(path)
            break
        if (directory / '.git').exists():
            break
    if selected is not None and selected.parent.name == '.evomneme':
        path = selected.parent / 'connection.json'
        if path.is_file() and path not in candidates:
            candidates.append(path)
    for path in candidates:
        try:
            data = read_receipt(path)
            if selected is not None:
                value = data.get('database')
                if not isinstance(value, str) or Path(value).resolve() != selected:
                    continue  # A generic SQL database is not this bound host.
            reason = status(data)
        except (OSError, ValueError, TypeError, RecursionError):
            if selected is not None and path.parent != selected.parent:
                continue
            reason = 'unreadable/corrupt receipt; inspect and recover without assuming acceptance'
        if reason:
            return ('EvoMneme integration contract: ' + reason + '; required=' + str(REQUIRED_CONTRACT)
                    + ', schema=' + str(REQUIRED_SCHEMA) + '; receipt=' + str(path)
                    + '; read live SKILL.md and upgrades/README.md; runtime success does not complete migration.')
        return None
    if bound:
        return ('EvoMneme integration contract: no connection receipt; integration is unverified; required='
                + str(REQUIRED_CONTRACT) + '; read live SKILL.md and upgrades/README.md.')
    return None


def check(*, force=False, **kwargs):
    if force or not _cli_active.get():
        message = diagnostic(**kwargs)
        if message:
            print(message, file=sys.stderr, flush=True)


def cli_check(*, bound=False):
    """Diagnose before argparse, dispatch, database work and application errors."""
    def decorate(function):
        @wraps(function)
        def invoke(*args, **kwargs):
            argv = list(args[0] if args and args[0] is not None else
                        kwargs.get('argv') if kwargs.get('argv') is not None else sys.argv[1:])
            def option(name):
                selected = None
                for index, value in enumerate(argv):
                    if value == '--':
                        break
                    flag, separator, supplied = value.partition('=')
                    # These target flags have unique long-option prefixes in
                    # their respective released parsers. Match argparse's
                    # abbreviations, = syntax and last-occurrence selection.
                    if flag.startswith('--') and name.startswith(flag):
                        if separator:
                            selected = supplied
                        elif index + 1 < len(argv):
                            selected = argv[index + 1]
                return selected
            database = None if bound else option('--database')
            # connect has a positional database, but is always a bound setup route.
            try:
                check(start=option('--project') if bound else None, database=database, bound=bound)
            except (OSError, ValueError):
                print('EvoMneme integration contract: cannot inspect local binding; inspect receipt and upgrades/README.md.',
                      file=sys.stderr, flush=True)
            token = _cli_active.set(True)
            try:
                return function(*args, **kwargs)
            finally:
                _cli_active.reset(token)
        return invoke
    return decorate
