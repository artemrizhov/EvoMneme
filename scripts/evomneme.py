#!/usr/bin/env python3
"""Thin, schema-agnostic SQLite execution shared by the CLI and stdio MCP."""

import argparse
import base64
import binascii
import json
import math
import os
from pathlib import Path
import sqlite3
import sys
import time

DEFAULT_MAX_ROWS = 50
DEFAULT_MAX_OUTPUT_BYTES = 16384
DEFAULT_TIMEOUT_MS = 5000
MAX_INPUT_BYTES = 1048576
MAX_OUTPUT_BYTES = 1048576
MAX_ROWS = 1000
MAX_STATEMENTS = 100
MAX_TIMEOUT_MS = 60000
MAX_VALUE_BYTES = 8388608
ERROR_MESSAGE_LIMIT = 2048
PROGRESS_STEPS = 1000


class RequestError(ValueError):
    """A malformed execution request with no database side effects."""


def json_bytes(value):
    """Encode deterministic compact UTF-8 JSON without nonstandard numeric values."""
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8')


def json_loads(value):
    """Reject nonstandard NaN/Infinity constants before inspecting any JSON fields."""
    def reject_constant(constant):
        """Turn Python's permissive JSON extension into a boundary validation error."""
        raise RequestError('Nonstandard JSON numeric constant: ' + constant)
    return json.loads(value, parse_constant=reject_constant)


def failure(kind, message, index=None, exception=None, max_bytes=DEFAULT_MAX_OUTPUT_BYTES):
    """Describe a bounded error without echoing SQL or parameter contents."""
    result = {'kind': kind, 'message': message[:ERROR_MESSAGE_LIMIT],
              'message_truncated': len(message) > ERROR_MESSAGE_LIMIT,
              'failed_statement_index': index}
    if exception is not None:
        result['sqlite_errorcode'] = getattr(exception, 'sqlite_errorcode', None)
        result['sqlite_errorname'] = getattr(exception, 'sqlite_errorname', None)
    output = {'ok': False, 'committed': False, 'error': result}
    while len(json_bytes(output)) > max_bytes and result['message']:
        excess = len(json_bytes(output)) - max_bytes
        result['message'] = result['message'][:max(0, len(result['message']) - excess)]
        result['message_truncated'] = True
    return output


def has_sql(fragment):
    """Identify executable fragments while leaving SQL strings and trigger text untouched."""
    position = 0
    while position < len(fragment):
        if fragment[position].isspace() or fragment[position] == ';':
            position += 1
        elif fragment.startswith('--', position):
            newline = fragment.find('\n', position + 2)
            position = len(fragment) if newline < 0 else newline + 1
        elif fragment.startswith('/*', position):
            end = fragment.find('*/', position + 2)
            position = len(fragment) if end < 0 else end + 2
        else:
            return True
    return False


def statements(sql):
    """Frame SQL scripts with SQLite's parser, including quoted semicolons and triggers."""
    if not isinstance(sql, str) or not sql.strip():
        raise RequestError('sql must be nonempty text')
    if len(sql.encode('utf-8')) > MAX_INPUT_BYTES:
        raise RequestError('SQL input exceeds the 1 MiB limit')
    framed, pending = [], ''
    for character in sql:
        pending += character
        if character == ';' and sqlite3.complete_statement(pending):
            if has_sql(pending):
                framed.append(pending)
            pending = ''
            if len(framed) > MAX_STATEMENTS:
                raise RequestError('At most 100 SQL statements are allowed per request')
    if has_sql(pending):
        if not sqlite3.complete_statement(pending + '\n;'):
            raise RequestError('Incomplete SQL statement')
        framed.append(pending)
    if len(framed) > MAX_STATEMENTS:
        raise RequestError('At most 100 SQL statements are allowed per request')
    return framed


def parameter(value):
    """Bind JSON scalars or explicitly tagged base64 bytes without SQL interpolation."""
    if isinstance(value, dict) and set(value) == {'$blob_base64'}:
        try:
            return base64.b64decode(value['$blob_base64'], validate=True)
        except (ValueError, TypeError, binascii.Error) as exc:
            raise RequestError('Invalid $blob_base64 parameter') from exc
    if value is None or isinstance(value, (str, bool)):
        return value
    if type(value) is int and -(2 ** 63) <= value < 2 ** 63:
        return value
    if type(value) is float and math.isfinite(value):
        return value
    raise RequestError('Parameters must be SQLite-compatible JSON scalars or $blob_base64 objects')


def cell(value):
    """Keep SQLite text/numbers/null exact and tag bytes or non-finite floats for JSON."""
    if isinstance(value, bytes):
        return {'$blob_base64': base64.b64encode(value).decode('ascii')}
    if isinstance(value, float) and not math.isfinite(value):
        return {'$float': 'NaN' if math.isnan(value) else ('Infinity' if value > 0 else '-Infinity')}
    return value


def validate(arguments):
    """Validate one shared CLI/MCP request before starting its transaction."""
    allowed = {'sql', 'params', 'max_rows', 'max_output_bytes', 'timeout_ms'}
    if not isinstance(arguments, dict) or set(arguments) - allowed:
        raise RequestError('Arguments must contain only sql, params, max_rows, max_output_bytes and timeout_ms')
    framed = statements(arguments.get('sql'))
    supplied = arguments.get('params', [])
    if not isinstance(supplied, (list, dict)):
        raise RequestError('params must be a JSON array or object')
    if len(json_bytes(supplied)) > MAX_INPUT_BYTES:
        raise RequestError('Parameters exceed the 1 MiB limit')
    if supplied and len(framed) != 1:
        raise RequestError('Parameter binding requires exactly one SQL statement')
    params = {key: parameter(value) for key, value in supplied.items()} if isinstance(supplied, dict) else [parameter(value) for value in supplied]
    limits = {}
    for key, default, lower, upper in (
        ('max_rows', DEFAULT_MAX_ROWS, 0, MAX_ROWS),
        ('max_output_bytes', DEFAULT_MAX_OUTPUT_BYTES, 1024, MAX_OUTPUT_BYTES),
        ('timeout_ms', DEFAULT_TIMEOUT_MS, 1, MAX_TIMEOUT_MS),
    ):
        value = arguments.get(key, default)
        if type(value) is not int or not lower <= value <= upper:
            raise RequestError(key + ' must be an integer from ' + str(lower) + ' to ' + str(upper))
        limits[key] = value
    return framed, params, limits


class Executor:
    """Bind one existing local SQLite file for the lifetime of this executor."""

    def __init__(self, database, create=False):
        self.requested_path = Path(database)
        if not self.requested_path.is_absolute() or str(database).startswith(('\\\\', '//')):
            raise RequestError('database must be an absolute local filesystem path')
        self.path = self.requested_path.resolve(strict=not create)
        if create:
            descriptor = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.close(descriptor)
        if not self.path.is_file():
            raise RequestError('database must be a regular file')
        self.identity = self._identity()
        self.connection = sqlite3.connect(self.path.as_uri() + '?mode=rw', uri=True,
                                          isolation_level=None, timeout=DEFAULT_TIMEOUT_MS / 1000)
        self.closed = False
        try:
            self.connection.execute('PRAGMA foreign_keys=ON')
            self.connection.execute('PRAGMA temp_store=MEMORY')
            self.connection.enable_load_extension(False)
            self.connection.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, MAX_VALUE_BYTES)
            self.connection.setlimit(sqlite3.SQLITE_LIMIT_SQL_LENGTH, MAX_INPUT_BYTES)
            self._check_binding()
        except BaseException:
            self.connection.close()
            raise

    def _identity(self):
        """Use the opened path's filesystem identity to detect external replacement."""
        info = self.path.stat()
        return info.st_dev, info.st_ino

    def _check_binding(self):
        """Refuse a retargeted input symlink or replaced bound database file."""
        if self.requested_path.resolve(strict=True) != self.path or self._identity() != self.identity:
            raise RequestError('Bound database path was replaced or retargeted; restart explicitly with the intended database')

    def close(self):
        """Close the one bound SQLite connection on CLI exit or MCP EOF."""
        if not self.closed:
            self.connection.close()
            self.closed = True

    @staticmethod
    def _authorize(action, first, second, database, trigger):
        """Deny cross-file access and caller-owned transaction boundaries."""
        denied = {sqlite3.SQLITE_ATTACH, sqlite3.SQLITE_DETACH, sqlite3.SQLITE_TRANSACTION, sqlite3.SQLITE_SAVEPOINT}
        if action in denied:
            return sqlite3.SQLITE_DENY
        if action == sqlite3.SQLITE_FUNCTION and (second or '').lower() in {'load_extension', 'readfile', 'writefile'}:
            return sqlite3.SQLITE_DENY
        if action == sqlite3.SQLITE_PRAGMA and second is not None and (first or '').lower() in {'foreign_keys', 'temp_store', 'temp_store_directory', 'data_store_directory', 'journal_mode'}:
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK

    def execute(self, arguments):
        """Execute SQL atomically; drain omitted rows before commit and report real limits."""
        try:
            framed, params, limits = validate(arguments)
            self._check_binding()
        except (RequestError, OSError, ValueError, TypeError) as exc:
            return failure('request', str(exc))
        deadline = time.monotonic() + limits['timeout_ms'] / 1000
        response = {'ok': True, 'committed': False, 'results': [], 'output_truncated': False}
        returned = 0
        index = None
        cursor = None

        def expired():
            """Use the request's wall-clock deadline during SQLite VM execution."""
            return time.monotonic() >= deadline

        try:
            self.connection.execute('PRAGMA busy_timeout=' + str(limits['timeout_ms']))
            self.connection.set_progress_handler(expired, PROGRESS_STEPS)
            self.connection.execute('BEGIN')
            self.connection.set_authorizer(self._authorize)
            for index, sql in enumerate(framed):
                if expired():
                    raise TimeoutError('SQL execution exceeded timeout_ms')
                self.connection.execute('PRAGMA busy_timeout=' + str(max(1, int((deadline - time.monotonic()) * 1000))))
                before = self.connection.total_changes
                cursor = self.connection.execute(sql, params if len(framed) == 1 else [])
                output = {'columns': [column[0] for column in cursor.description] if cursor.description else [],
                          'rows': [], 'rows_returned': 0, 'rows_omitted': 0, 'affected_rows': 0}
                response['results'].append(output)
                if len(json_bytes(response)) > limits['max_output_bytes']:
                    raise RequestError('Result metadata exceeds max_output_bytes; request fewer statements or columns')
                keep_rows = returned < limits['max_rows']
                if cursor.description:
                    for row in cursor:
                        if expired():
                            raise TimeoutError('SQL execution exceeded timeout_ms')
                        encoded = [cell(value) for value in row]
                        if keep_rows:
                            output['rows'].append(encoded)
                            output['rows_returned'] += 1
                            if len(json_bytes(response)) > limits['max_output_bytes']:
                                output['rows'].pop()
                                output['rows_returned'] -= 1
                                keep_rows = False
                            else:
                                returned += 1
                                keep_rows = returned < limits['max_rows']
                                continue
                        output['rows_omitted'] += 1
                        response['output_truncated'] = True
                cursor.close()
                output['affected_rows'] = self.connection.total_changes - before
            self._check_binding()
            if expired():
                raise TimeoutError('SQL execution exceeded timeout_ms')
            # Authorizer guards request SQL only; the executor owns commit/rollback.
            self.connection.set_authorizer(None)
            response['committed'] = True
            if len(json_bytes(response)) > limits['max_output_bytes']:
                raise RequestError('Result metadata exceeds max_output_bytes')
            self.connection.execute('PRAGMA busy_timeout=' + str(max(1, int((deadline - time.monotonic()) * 1000))))
            self.connection.execute('COMMIT')
            return response
        except (sqlite3.Error, OSError, RequestError, TimeoutError, ValueError, TypeError) as exc:
            self.connection.set_authorizer(None)
            self.connection.set_progress_handler(None, 0)
            if cursor is not None:
                cursor.close()
            if self.connection.in_transaction:
                try:
                    self.connection.execute('ROLLBACK')
                except sqlite3.Error:
                    self.close()
                    return failure('rollback', 'Rollback failed; connection closed. Inspect the database before reopening.', index, exc, limits['max_output_bytes'])
            kind = 'timeout' if isinstance(exc, TimeoutError) or expired() else ('sqlite' if isinstance(exc, sqlite3.Error) else 'request')
            message = str(exc)
            if getattr(exc, 'sqlite_errorcode', None) == sqlite3.SQLITE_AUTH:
                message += '. Transaction controls, ATTACH/DETACH, file access, and changes to foreign_keys/temp_store/journal_mode are controlled by the executor.'
            return failure(kind, message, index, exc if isinstance(exc, sqlite3.Error) else None, limits['max_output_bytes'])
        finally:
            if not self.closed:
                self.connection.set_authorizer(None)
                self.connection.set_progress_handler(None, 0)


def read_input(filename):
    """Read bounded UTF-8 SQL or JSON from a file or stdin without shell quoting."""
    if filename == '-':
        raw = sys.stdin.buffer.read(MAX_INPUT_BYTES + 1)
    else:
        with Path(filename).open('rb') as stream:
            raw = stream.read(MAX_INPUT_BYTES + 1)
    if len(raw) > MAX_INPUT_BYTES:
        raise RequestError('Input exceeds the 1 MiB limit')
    return raw.decode('utf-8-sig')


def main(argv=None):
    """Expose the exact executor through SQL text, SQL file, or JSON request input."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', required=True, help='Absolute local SQLite path; existing unless --create')
    parser.add_argument('--create', action='store_true', help='Explicitly create a new empty file; refuses existing paths')
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--sql')
    source.add_argument('--sql-file', help='UTF-8 SQL file, or - for stdin')
    source.add_argument('--input', help='JSON execution arguments file, or - for stdin')
    parser.add_argument('--params', help='JSON array/object; only with a single SQL statement')
    parser.add_argument('--max-rows', type=int)
    parser.add_argument('--max-output-bytes', type=int)
    parser.add_argument('--timeout-ms', type=int)
    args = parser.parse_args(argv)
    executor = None
    try:
        if args.input:
            if any(value is not None for value in (args.params, args.max_rows, args.max_output_bytes, args.timeout_ms)):
                raise RequestError('--input contains all execution arguments; do not combine it with argument overrides')
            arguments = json_loads(read_input(args.input))
        else:
            arguments = {'sql': args.sql if args.sql is not None else read_input(args.sql_file)}
            if args.params is not None:
                arguments['params'] = json_loads(args.params)
            for key in ('max_rows', 'max_output_bytes', 'timeout_ms'):
                if getattr(args, key) is not None:
                    arguments[key] = getattr(args, key)
        validate(arguments)
        executor = Executor(args.database, args.create)
        result = executor.execute(arguments)
    except (OSError, ValueError, TypeError, sqlite3.Error) as exc:
        result = failure('request', str(exc), exception=exc if isinstance(exc, sqlite3.Error) else None)
    finally:
        if executor:
            executor.close()
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    print(json_bytes(result).decode('utf-8'))
    return 0 if result['ok'] else 1


if __name__ == '__main__':
    sys.exit(main())
