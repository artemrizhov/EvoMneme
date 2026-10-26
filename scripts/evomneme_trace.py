"""Optional, local per-process activity logs. Never store SQL or result contents."""

import json
from pathlib import Path
import sys
import time
import uuid
from types import SimpleNamespace


def build_event(response, accesses, elapsed_ms, context, session, database, client, activity_id):
    metadata = SimpleNamespace(session=session, database=str(database), client=client)
    return ActivityLog.build_event(metadata, response, accesses, elapsed_ms, context, activity_id)


class ActivityLog:
    """Separate writers avoid interleaved writes; an explicit session joins processes."""

    def __init__(self, directory, session, database):
        if not session or len(session) > 200:
            raise ValueError('A session id of 1..200 characters is required for tracing')
        self.directory = Path(directory)
        if not self.directory.is_absolute():
            raise ValueError('trace directory must be absolute and inside the host local area')
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / (uuid.uuid4().hex + '.jsonl')
        self.session = session
        self.database = str(Path(database).resolve(strict=True))
        self.disabled = False
        self.client = None

    def build_event(self, response, accesses, elapsed_ms, context=None, activity_id=None):
        """References identify returned rows only, never every row examined by SQLite."""
        references = []
        for result, access in zip(response['results'], accesses):
            for field, graph_type in (('trace_node_id', 'nodes'), ('trace_edge_id', 'edges')):
                if result['columns'].count(field) == 1:
                    for row in result['rows']:
                        value = row[result['columns'].index(field)]
                        if isinstance(value, str):
                            references.append({'graph_type': graph_type, 'graph_id': value})
            tables = set(access['read']) | set(access['write'])
            graph_tables = tables & {'nodes', 'edges'}
            if len(graph_tables) != 1 or tables != graph_tables:
                continue
            columns = result['columns']
            if columns.count('id') != 1 or columns.count('scope_id') != 1:
                continue
            for row in result['rows']:
                references.append({'table': next(iter(graph_tables)),
                                   'scope_id': row[columns.index('scope_id')],
                                   'id': row[columns.index('id')]})
        context = context or {}
        event = {'source': 'sql', 'activity_id': activity_id or uuid.uuid4().hex,
                 'time': time.time(), 'session': context.get('session_id', self.session),
                 'chat': context.get('chat_id'), 'agent': context.get('agent_id'),
                 'client': self.client,
                 'chat_title': context.get('chat_title'), 'session_title': context.get('session_title'),
                 'agent_name': context.get('agent_name'),
                 'identity': {'chat': 'chat_id' in context, 'agent': 'agent_id' in context},
                 'database': self.database,
                 'ok': response['ok'], 'elapsed_ms': round(elapsed_ms, 2),
                 'completed': response['completed_statements'],
                 'rolled_back': response['transaction_rolled_back'],
                 'durable_effects_possible': response['autocommit_effects_possible'],
                 'read': sorted({t for a in accesses for t in a['read']}),
                 'write': sorted({t for a in accesses for t in a['write']}),
                 'references': references, 'returned_rows': sum(len(r['rows']) for r in response['results']),
                 'has_more': any(r['has_more'] for r in response['results'])}
        encoded = json.dumps(event, ensure_ascii=True, separators=(',', ':'))
        if len(encoded) > 512 * 1024:
            event['references'] = []
            event['references_truncated'] = True
        return event

    def record(self, response=None, accesses=None, elapsed_ms=0, context=None, event=None):
        if self.disabled:
            return
        event = event or self.build_event(response, accesses, elapsed_ms, context)
        try:
            encoded = json.dumps(event, ensure_ascii=True, separators=(',', ':')) + '\n'
            if len(encoded) > 512 * 1024:
                event['references'] = []
                event['references_truncated'] = True
                encoded = json.dumps(event, ensure_ascii=True, separators=(',', ':')) + '\n'
            if len(encoded) > 1024 * 1024:
                raise ValueError('Trace metadata exceeds the 1 MiB event limit')
            if self.path.exists() and self.path.stat().st_size >= 32 * 1024 * 1024:
                raise OSError('32 MiB per-process trace limit reached; restart tracing with a new log')
            with self.path.open('a', encoding='utf-8') as stream:
                stream.write(encoded)
        except (OSError, ValueError) as exc:
            self.disabled = True
            print('EvoMneme tracing disabled: ' + str(exc), file=sys.stderr)


def configure_trace(executor, directory, session):
    if bool(directory) != bool(session):
        raise ValueError('--trace-directory and --session-id must be supplied together')
    if directory:
        executor.activity_log = ActivityLog(directory, session, executor.path)
        executor.session_id = session
