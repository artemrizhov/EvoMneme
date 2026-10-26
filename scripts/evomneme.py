#!/usr/bin/env python3
"""Thin native-SQL execution shared by Python and CLI."""

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
import uuid

from evomneme_activity import DatabaseActivity, managed_table
from evomneme_trace import build_event

MAX_INPUT_BYTES = 1048576
MAX_VALUE_BYTES = 8388608
MAX_STATEMENTS = 100
PROGRESS_STEPS = 1000
ERROR_MESSAGE_LIMIT = 2048
LIMITS = {
    'max_rows': (50, 0, 1000),
    'max_output_bytes': (16384, 1024, 1048576),
    'timeout_ms': (5000, 1, 60000),
}


class RequestError(ValueError):
    """An invalid request, including an unfinished caller transaction."""


def json_bytes(value):
    """Encode compact UTF-8 JSON with no nonstandard numeric constants."""
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8')


def json_loads(value):
    """Reject unsupported depth, numeric constants and Unicode before dispatch."""
    def reject_constant(constant):
        """Reject the permissive constants otherwise accepted by Python's decoder."""
        raise RequestError('Nonstandard JSON numeric constant: ' + constant)
    try:
        decoded = json.loads(value, parse_constant=reject_constant)
        # Escaped surrogate pairs decode to valid Unicode; lone surrogates must
        # fail here before a diagnostic or result reaches UTF-8 output.
        json_bytes(decoded)
    except RecursionError as exc:
        raise RequestError('JSON nesting exceeds the supported depth') from exc
    except UnicodeEncodeError as exc:
        raise RequestError('JSON contains an unencodable Unicode string') from exc
    return decoded


def parameter(value):
    """Bind JSON scalars or explicitly tagged bytes without SQL interpolation."""
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
    """Preserve SQLite values while explicitly tagging binary/non-finite JSON values."""
    if isinstance(value, bytes):
        return {'$blob_base64': base64.b64encode(value).decode('ascii')}
    if isinstance(value, float) and not math.isfinite(value):
        return {'$float': 'NaN' if math.isnan(value) else ('Infinity' if value > 0 else '-Infinity')}
    return value


def commands(sql, params, limits, unknown):
    """Validate native single statements or an explicit batch with individual bindings."""
    if unknown:
        raise RequestError('Unknown execution arguments: ' + ', '.join(sorted(unknown)))
    for key, value in limits.items():
        _, lower, upper = LIMITS[key]
        if type(value) is not int or not lower <= value <= upper:
            raise RequestError(key + ' must be an integer from ' + str(lower) + ' to ' + str(upper))
    if len(json_bytes({'sql': sql, 'params': params})) > MAX_INPUT_BYTES:
        raise RequestError('Execution input exceeds the 1 MiB limit')
    if isinstance(sql, str):
        batch = [{'sql': sql, 'params': [] if params is None else params}]
    elif isinstance(sql, list) and 1 <= len(sql) <= MAX_STATEMENTS:
        if params is not None:
            raise RequestError('Batch bindings belong to each statement; omit top-level params')
        batch = sql
    else:
        raise RequestError('sql must be one statement string or an array of 1..100 {sql,params} objects')
    result = []
    for command in batch:
        if not isinstance(command, dict) or set(command) - {'sql', 'params'} or not isinstance(command.get('sql'), str) or not command['sql'].strip():
            raise RequestError('Each batch item requires nonempty sql and optional params')
        supplied = command.get('params', [])
        if not isinstance(supplied, (list, dict)):
            raise RequestError('params must be a JSON array or object')
        bindings = ({key: parameter(value) for key, value in supplied.items()} if isinstance(supplied, dict)
                    else [parameter(value) for value in supplied])
        result.append((command['sql'], bindings))
    return result


def empty_result():
    """Keep result shape identical on direct and CLI execution errors."""
    return {'ok': True, 'results': [], 'completed_statements': 0,
            'transaction_rolled_back': False, 'autocommit_effects_possible': False}


def error_result(response, kind, exception, index, budget):
    """Add bounded diagnostics; retain only completed outputs that fit the response budget."""
    message = str(exception)
    if isinstance(exception, sqlite3.ProgrammingError) and 'one statement' in message:
        message += ' Use an array of {sql,params} objects for batches; SQL strings are not scripts.'
    response['ok'] = False
    response['error'] = {'kind': kind, 'message': message[:ERROR_MESSAGE_LIMIT],
                         'message_truncated': len(message) > ERROR_MESSAGE_LIMIT,
                         'failed_statement_index': index}
    if isinstance(exception, sqlite3.Error):
        response['error']['sqlite_errorcode'] = getattr(exception, 'sqlite_errorcode', None)
        response['error']['sqlite_errorname'] = getattr(exception, 'sqlite_errorname', None)
    # Error-only work is bounded by 100 resultsets, independent of fetched row count.
    while len(json_bytes(response)) > budget:
        if response['error']['message']:
            excess = len(json_bytes(response)) - budget
            response['error']['message'] = response['error']['message'][:max(0, len(response['error']['message']) - excess)]
            response['error']['message_truncated'] = True
        elif response['results']:
            response['results'].pop()
            response['results_truncated'] = True
        else:
            break
    return response


class Executor:
    """Bind one persistent local database file for this executor's lifetime."""

    def __init__(self, database, create=False, history=True):
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
                                          isolation_level=None, timeout=LIMITS['timeout_ms'][0] / 1000)
        self.closed = False
        self.activity_log = None
        self.history = DatabaseActivity(self) if history else None
        self.bookkeeping = self.history or DatabaseActivity(self)
        self.session_id = uuid.uuid4().hex
        self.client = {'name': 'EvoMneme Python'}
        try:
            self.connection.execute('PRAGMA foreign_keys=ON')
            self.connection.enable_load_extension(False)
            self.connection.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, MAX_VALUE_BYTES)
            self.connection.setlimit(sqlite3.SQLITE_LIMIT_SQL_LENGTH, MAX_INPUT_BYTES)
            self._check_binding()
            if self.history:
                try:
                    self.history.ensure()
                except (sqlite3.Error, ValueError, OSError) as exc:
                    print('EvoMneme history setup failed: ' + str(exc), file=sys.stderr)
        except BaseException:
            self.close()
            raise

    def _identity(self):
        """Identify the file so external replacement cannot silently change database scope."""
        info = self.path.stat()
        return info.st_dev, info.st_ino

    def _check_binding(self):
        """Reject replacement of the bound file or retargeting of its input symlink."""
        if self.requested_path.resolve(strict=True) != self.path or self._identity() != self.identity:
            raise RequestError('Bound database path was replaced or retargeted; restart with the intended database')

    def close(self):
        """Close the executor connection, including on CLI exit."""
        if not self.closed:
            self.connection.close()
            self.closed = True

    def execute_sql(self, /, sql=None, params=None, max_rows=LIMITS['max_rows'][0],
                    max_output_bytes=LIMITS['max_output_bytes'][0],
                    timeout_ms=LIMITS['timeout_ms'][0], activity_context=None, **unknown):
        """Record recognized-store activity while preserving native SQL results."""
        started = time.monotonic()
        accesses = []
        self._activity_event = None
        if activity_context is not None and (not isinstance(activity_context, dict) or
                set(activity_context) - {'chat_id', 'session_id', 'agent_id', 'chat_title', 'session_title', 'agent_name'} or
                any(not isinstance(v, str) or not 1 <= len(v) <= 200 for v in activity_context.values())):
            return error_result(empty_result(), 'request', RequestError('Invalid activity_context'), None, LIMITS['max_output_bytes'][0])
        if self.history or self.activity_log:
            self._activity_event = build_event(empty_result(), [], 0, activity_context,
                                               self.session_id, self.path, self.client, uuid.uuid4().hex)
        response = self._execute_sql(sql, params, max_rows, max_output_bytes, timeout_ms, accesses, unknown)
        if self._activity_event is not None:
            event = build_event(response, accesses, (time.monotonic() - started) * 1000,
                                activity_context, self.session_id, self.path, self.client,
                                self._activity_event['activity_id'])
            if self.history and not self.closed:
                try:
                    self.history.clear()
                    if self.history.ensure():
                        self.history.record(event)
                except (sqlite3.Error, ValueError, OSError) as exc:
                    print('EvoMneme activity history could not be saved: ' + str(exc), file=sys.stderr)
            if self.activity_log:
                self.activity_log.record(event=event)
        return response

    def _execute_sql(self, sql, params, max_rows, max_output_bytes, timeout_ms, accesses, unknown):
        """Run native statements; callers own SQL transactions, requests clean up open ones."""
        response = empty_result()
        limits = {'max_rows': max_rows, 'max_output_bytes': max_output_bytes, 'timeout_ms': timeout_ms}
        budget = max_output_bytes if type(max_output_bytes) is int and LIMITS['max_output_bytes'][1] <= max_output_bytes <= LIMITS['max_output_bytes'][2] else LIMITS['max_output_bytes'][0]
        try:
            batch = commands(sql, params, limits, unknown)
            self._check_binding()
        except RecursionError as exc:
            return error_result(response, 'request', RequestError('Execution arguments exceed the supported nesting depth'), None, budget)
        except (OSError, ValueError, TypeError) as exc:
            return error_result(response, 'request', exc, None, budget)
        deadline = time.monotonic() + timeout_ms / 1000
        returned = 0
        # Reserve bounded integer/flag growth; encode only new metadata and rows.
        used_bytes = len(json_bytes(response)) + 256
        transaction_dirty = False
        index = None
        cursor = None
        state = {'writes': False, 'transaction': None}
        before_transaction = False

        def expired():
            """Share one wall-clock deadline between SQLite VM work and lock waits."""
            return time.monotonic() >= deadline

        def authorize(action, first, second, database, trigger):
            """Use engine write metadata for RETURNING; prohibit external file capabilities."""
            internal = self.bookkeeping.counter_installed and (
                managed_table(first) or managed_table(trigger)
                or (trigger or '').startswith('evomneme_counter_') or trigger == 'evomneme_activity_scope')
            if (self.history or self.activity_log) and database == 'main' and accesses and not internal:
                if action == sqlite3.SQLITE_READ:
                    accesses[-1]['read'].add(first)
                elif action in {sqlite3.SQLITE_INSERT, sqlite3.SQLITE_UPDATE, sqlite3.SQLITE_DELETE}:
                    accesses[-1]['write'].add(first)
            if action == sqlite3.SQLITE_ATTACH and first != '':
                return sqlite3.SQLITE_DENY
            if action == sqlite3.SQLITE_FUNCTION and (second or '').lower() in {'load_extension', 'readfile', 'writefile'}:
                return sqlite3.SQLITE_DENY
            if action == sqlite3.SQLITE_PRAGMA:
                if second is not None and (first or '').lower() in {'temp_store_directory', 'data_store_directory'}:
                    return sqlite3.SQLITE_DENY
                state['writes'] |= second is not None
            if action in {sqlite3.SQLITE_INSERT, sqlite3.SQLITE_UPDATE, sqlite3.SQLITE_DELETE} and not internal:
                state['writes'] = True
            if action in {sqlite3.SQLITE_TRANSACTION, sqlite3.SQLITE_SAVEPOINT}:
                state['transaction'] = first
            return sqlite3.SQLITE_OK

        try:
            self.connection.set_progress_handler(expired, PROGRESS_STEPS)
            for index, (statement, bindings) in enumerate(batch):
                accesses.append({'read': set(), 'write': set()})
                if expired():
                    raise TimeoutError('SQL execution exceeded timeout_ms')
                self.connection.set_authorizer(None)
                self.connection.set_progress_handler(None, 0)
                if self.history:
                    try:
                        self._check_binding()
                        if self.history.ensure():
                            self.history.scope(self._activity_event)
                    except (sqlite3.Error, ValueError, OSError) as exc:
                        print('EvoMneme history setup failed: ' + str(exc), file=sys.stderr)
                        try:
                            self.history.clear()
                        except sqlite3.Error:
                            pass
                        self.history.ready = False
                try:
                    self.bookkeeping.observe_existing()
                except (sqlite3.Error, ValueError, OSError) as exc:
                    print('EvoMneme bookkeeping observation failed: ' + str(exc), file=sys.stderr)
                self.connection.set_progress_handler(expired, PROGRESS_STEPS)
                self.connection.execute('PRAGMA busy_timeout=' + str(max(1, int((deadline - time.monotonic()) * 1000))))
                state.update(writes=False, transaction=None)
                self.connection.set_authorizer(authorize)
                before_transaction = self.connection.in_transaction
                before_changes = self.connection.total_changes
                before_history = self.bookkeeping.mutations
                cursor = self.connection.execute(statement, bindings)
                # Native COMMIT/RELEASE may have persisted changes before output
                # formatting fails. Record that transition before any byte checks.
                after_transaction = self.connection.in_transaction
                if state['writes']:
                    if after_transaction:
                        transaction_dirty = True
                    elif not before_transaction:
                        response['autocommit_effects_possible'] = True
                if before_transaction and not after_transaction:
                    if state['transaction'] != 'ROLLBACK' and transaction_dirty:
                        response['autocommit_effects_possible'] = True
                    transaction_dirty = False
                native_completed = cursor.description is None
                if native_completed:
                    response['completed_statements'] += 1
                output = {'columns': [column[0] for column in cursor.description] if cursor.description else [],
                          'rows': [], 'has_more': False, 'affected_rows': 0}
                metadata_bytes = len(json_bytes(output)) + 32 + bool(response['results'])
                if used_bytes + metadata_bytes > max_output_bytes:
                    raise RequestError('Result metadata exceeds max_output_bytes; request fewer statements or columns')
                row_bytes = 0
                if cursor.description:
                    for row in cursor:
                        if expired():
                            raise TimeoutError('SQL execution exceeded timeout_ms')
                        if not output['has_more']:
                            encoded = [cell(value) for value in row]
                            size = len(json_bytes(encoded)) + bool(output['rows'])
                            if returned < max_rows and used_bytes + metadata_bytes + row_bytes + size <= max_output_bytes:
                                output['rows'].append(encoded)
                                returned += 1
                                row_bytes += size
                                continue
                            output['has_more'] = True
                        # SELECT stops at one lookahead. Mutating RETURNING must finish
                        # stepping so SQLite exposes late completion/commit failures.
                        if not state['writes']:
                            break
                cursor.close()
                cursor = None
                if not native_completed:
                    response['completed_statements'] += 1
                output['affected_rows'] = self.connection.total_changes - before_changes - (self.bookkeeping.mutations - before_history)
                response['results'].append(output)
                used_bytes += metadata_bytes + row_bytes
            self._check_binding()
            if expired():
                raise TimeoutError('SQL execution exceeded timeout_ms')
            if self.connection.in_transaction:
                raise RequestError('Request ended with an open transaction; it was rolled back. Finish BEGIN/SAVEPOINT with COMMIT/RELEASE in the same batch.')
            return response
        except (sqlite3.Error, OSError, RequestError, TimeoutError, ValueError, TypeError) as exc:
            self.connection.set_authorizer(None)
            self.connection.set_progress_handler(None, 0)
            if cursor is not None:
                try:
                    cursor.close()
                except sqlite3.Error as close_error:
                    exc = close_error
            if state['writes'] and not before_transaction and not self.connection.in_transaction:
                response['autocommit_effects_possible'] = True
            if self.connection.in_transaction:
                try:
                    self.connection.execute('ROLLBACK')
                    response['transaction_rolled_back'] = True
                except sqlite3.Error:
                    self.close()
                    return error_result(response, 'rollback', RequestError('Rollback failed; connection closed. Inspect the database before reopening.'), index, budget)
            kind = ('timeout' if isinstance(exc, TimeoutError) or expired() else
                    'sqlite' if isinstance(exc, sqlite3.Error) else
                    'transaction' if response['transaction_rolled_back'] else 'request')
            return error_result(response, kind, exc, index, budget)
        finally:
            if not self.closed:
                self.connection.set_authorizer(None)
                self.connection.set_progress_handler(None, 0)
                if self.history:
                    try:
                        self.history.clear()
                    except sqlite3.Error as exc:
                        print('EvoMneme activity attribution cleanup failed: ' + str(exc), file=sys.stderr)


def read_input(filename):
    """Read bounded UTF-8 SQL or JSON from a file or stdin."""
    if filename == '-':
        raw = sys.stdin.buffer.read(MAX_INPUT_BYTES + 1)
    else:
        with Path(filename).open('rb') as stream:
            raw = stream.read(MAX_INPUT_BYTES + 1)
    if len(raw) > MAX_INPUT_BYTES:
        raise RequestError('Input exceeds the 1 MiB limit')
    return raw.decode('utf-8-sig')


def main(argv=None):
    """Decode transport inputs and delegate to the one public execute_sql entry point."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', required=True, help='Absolute local SQLite path; existing unless --create')
    parser.add_argument('--create', action='store_true', help='Create a new empty file; refuses existing paths')
    parser.add_argument('--no-history', action='store_true', help='Disable history setup and call recording in this process; existing triggers/history remain')
    parser.add_argument('--trace-directory', help='Optional absolute host-local activity directory')
    parser.add_argument('--session-id', help='Explicit chat/session identity for optional activity tracing')
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--sql', help='One native SQLite statement')
    source.add_argument('--sql-file', help='UTF-8 file containing ONE statement, or - for stdin')
    source.add_argument('--input', help='JSON execute_sql arguments file, or - for stdin; supports batches')
    parser.add_argument('--params', help='JSON array/object for a single SQL string')
    for key, (default, lower, upper) in LIMITS.items():
        parser.add_argument('--' + key.replace('_', '-'), type=int,
                            help='Default ' + str(default) + '; range ' + str(lower) + '..' + str(upper))
    args = parser.parse_args(argv)
    executor = None
    try:
        if args.input:
            if any(value is not None for value in (args.params, *(getattr(args, key) for key in LIMITS))):
                raise RequestError('--input contains all execution arguments; do not combine it with overrides')
            arguments = json_loads(read_input(args.input))
            if not isinstance(arguments, dict):
                raise RequestError('Execution arguments must be a JSON object')
        else:
            arguments = {'sql': args.sql if args.sql is not None else read_input(args.sql_file)}
            if args.params is not None:
                arguments['params'] = json_loads(args.params)
            arguments.update({key: getattr(args, key) for key in LIMITS if getattr(args, key) is not None})
        executor = Executor(args.database, args.create, history=not args.no_history)
        executor.client = {'name': 'EvoMneme CLI'}
        if args.trace_directory or args.session_id:
            from evomneme_trace import configure_trace
            configure_trace(executor, args.trace_directory, args.session_id)
            executor.activity_log.client = {'name': 'EvoMneme CLI'}
        result = executor.execute_sql(**arguments)
    except (OSError, ValueError, TypeError, sqlite3.Error) as exc:
        result = error_result(empty_result(), 'request', exc, None, LIMITS['max_output_bytes'][0])
    finally:
        if executor:
            executor.close()
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    print(json_bytes(result).decode('utf-8'))
    return 0 if result['ok'] else 1


if __name__ == '__main__':
    sys.exit(main())
