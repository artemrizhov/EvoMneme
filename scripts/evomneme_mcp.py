#!/usr/bin/env python3
"""Minimal synchronous stdio MCP exposing the shared SQLite executor."""

import argparse
import sqlite3
import sys

from evomneme import Executor, INPUT_SCHEMA, MAX_INPUT_BYTES, RequestError, json_bytes, json_loads

PROTOCOL_VERSION = '2025-11-25'
SUPPORTED_PROTOCOLS = {PROTOCOL_VERSION, '2025-06-18'}
TOOL = {
    'name': 'execute_sql',
    'description': 'Execute one native SQLite statement or an explicit array of {sql,params} commands on the bound database. Callers own SQL transactions; unclosed ones roll back at request end. Earlier autocommitted effects remain. Check has_more for bounded rows.',
    'inputSchema': INPUT_SCHEMA,
}


def protocol_error(request_id, code, message):
    """Return JSON-RPC protocol errors separately from SQL execution results."""
    return {'jsonrpc': '2.0', 'id': request_id, 'error': {'code': code, 'message': message}}


class Server:
    """Serve only initialization, ping, tool discovery and synchronous SQL calls."""

    def __init__(self, executor):
        self.executor = executor
        self.initialized = False
        self.negotiated = False

    def handle(self, message):
        """Validate one wire message before considering any database operation."""
        if not isinstance(message, dict) or message.get('jsonrpc') != '2.0' or not isinstance(message.get('method'), str):
            return protocol_error(None, -32600, 'Invalid JSON-RPC request')
        request_id = message.get('id')
        if 'id' in message and (type(request_id) not in (str, int)):
            return protocol_error(None, -32600, 'Request id must be a string or integer')
        if 'id' not in message:
            # Notifications never execute a tool and never receive responses.
            if message['method'] == 'notifications/initialized' and self.negotiated:
                self.initialized = True
            return None
        method = message['method']
        params = message.get('params', {})
        if not isinstance(params, dict):
            return protocol_error(request_id, -32602, 'params must be an object')
        if method == 'initialize':
            if self.negotiated:
                return protocol_error(request_id, -32600, 'Session is already initialized')
            if not isinstance(params.get('protocolVersion'), str) or not isinstance(params.get('capabilities'), dict) or not isinstance(params.get('clientInfo'), dict):
                return protocol_error(request_id, -32602, 'initialize requires protocolVersion, capabilities and clientInfo')
            version = params['protocolVersion'] if params['protocolVersion'] in SUPPORTED_PROTOCOLS else PROTOCOL_VERSION
            self.negotiated = True
            result = {'protocolVersion': version, 'capabilities': {'tools': {}},
                      'serverInfo': {'name': 'evomneme-sqlite', 'version': '1.0.0'}}
        elif method == 'ping':
            result = {}
        elif not self.initialized:
            return protocol_error(request_id, -32000, 'Complete initialize and notifications/initialized before tool requests')
        elif method == 'tools/list':
            result = {'tools': [TOOL]}
        elif method == 'tools/call':
            if params.get('name') != 'execute_sql':
                return protocol_error(request_id, -32602, 'Unknown tool')
            if not isinstance(params.get('arguments'), dict):
                return protocol_error(request_id, -32602, 'Tool arguments must be an object')
            output = self.executor.execute_sql(**params['arguments'])
            result = {'content': [{'type': 'text', 'text': json_bytes(output).decode('utf-8')}],
                      'structuredContent': output, 'isError': not output['ok']}
        else:
            return protocol_error(request_id, -32601, 'Method not found')
        return {'jsonrpc': '2.0', 'id': request_id, 'result': result}


def serve(executor, incoming, outgoing):
    """Use bounded newline-delimited UTF-8 JSON; EOF closes the synchronous server."""
    server = Server(executor)
    while True:
        raw = incoming.readline(MAX_INPUT_BYTES + 1)
        if not raw:
            return
        if len(raw) > MAX_INPUT_BYTES:
            while raw and not raw.endswith(b'\n'):
                raw = incoming.readline(MAX_INPUT_BYTES + 1)
            response = protocol_error(None, -32600, 'Message exceeds the 1 MiB input limit')
        else:
            try:
                message = json_loads(raw.decode('utf-8'))
            except (ValueError, UnicodeError):
                response = protocol_error(None, -32700, 'Invalid or unsupported UTF-8 JSON')
            else:
                response = server.handle(message)
        if response is not None:
            outgoing.write(json_bytes(response) + b'\n')
            outgoing.flush()


def main(argv=None):
    """Bind the explicit local database once; diagnostics never pollute stdout."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', required=True)
    parser.add_argument('--create', action='store_true')
    args = parser.parse_args(argv)
    executor = None
    try:
        executor = Executor(args.database, args.create)
        serve(executor, sys.stdin.buffer, sys.stdout.buffer)
        return 0
    except (OSError, ValueError, sqlite3.Error) as exc:
        print('EvoMneme MCP startup/transport failure: ' + str(exc)[:2048], file=sys.stderr)
        return 1
    finally:
        if executor:
            executor.close()


if __name__ == '__main__':
    sys.exit(main())
