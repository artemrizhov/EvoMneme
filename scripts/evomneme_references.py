"""Literal saved source-file references for pre-reconciliation maintenance."""
import sqlite3
import time

from evomneme_navigate import fields, quote_command

OUTPUT_BYTES = 64 * 1024
TIMEOUT_SECONDS = 5.0
LIMITATION = ('Structured literal source_path matches only; arbitrary text citations, file-text mentions, '
              'absolute/relative aliases, case and slash variants are not searched. '
              'Zero matches do not prove absence of code or other references.')


class ReferencesError(ValueError):
    pass


def retry_command(paths, shell):
    """Never put raw terminal controls into an error's command example."""
    argv = ['evomneme', 'references', '--all', *(['--'] if any(path.startswith('-') for path in paths) else []), *paths]
    if all(all(char.isprintable() and char not in '\u2028\u2029' for char in arg) for arg in argv):
        return quote_command(argv, shell)
    return ('Rerun the same evomneme references invocation with --all before --, preserving the '
            'original literal arguments; control-bearing arguments have no copyable command example.')


class ReferenceReader:
    def __init__(self, connection, timeout=TIMEOUT_SECONDS, shared=None):
        self.connection = connection
        self.deadline = time.monotonic() + timeout
        self.db = None
        self.warnings = []
        self.context = shared
        self.owns_context = shared is None
        self.check_time()
        try:
            if self.context is not None and self.context.connection != connection:
                raise ReferencesError('Shared read context belongs to another binding')
            if self.context is None:
                from evomneme_context import ReadContext
                self.context = ReadContext(connection, timeout=timeout, timeout_error=ReferencesError,
                                           timeout_message='References timed out; no complete result.')
            self.db = self.context.db
            self.deadline = self.context.deadline
            self.warnings = list(self.context.warnings)
            self.check_time()
            root = self.db.execute('SELECT validity FROM nodes WHERE scope_id=? AND id=?',
                                   (connection.scope, connection.root_id)).fetchone()
            if root is None or root['validity'] != 'current':
                self.warnings.append('Configured root is missing or not current; maintenance references remain '
                                     'available, but the root knowledge gap needs reconciliation.')
        except Exception:
            self.close()
            raise

    def close(self):
        if self.owns_context and self.context is not None:
            self.context.close()
        self.db = None

    def check_time(self):
        if time.monotonic() >= self.deadline:
            raise ReferencesError('References timed out; no complete result.')

    def rows(self, sql, parameters):
        self.check_time()
        for row in self.db.execute(sql, parameters):
            self.check_time()
            yield dict(row)

    def select(self, paths):
        """No filesystem resolution, text search, current-only filter, or variable-sized IN list."""
        direct = {table: {} for table in ('nodes', 'edges', 'evidence')}
        incident = {}
        for path in paths:
            self.check_time()
            for table in direct:
                for row in self.rows('SELECT * FROM ' + table +
                                     ' WHERE scope_id=? AND source_path=? COLLATE BINARY ORDER BY id',
                                     (self.connection.scope, path)):
                    direct[table][row['id']] = row
            for row in self.rows('''SELECT e.* FROM edges e WHERE e.scope_id=? AND EXISTS (
                    SELECT 1 FROM nodes n WHERE n.scope_id=e.scope_id AND n.kind='file'
                    AND n.source_path=? COLLATE BINARY AND (n.id=e.source_id OR n.id=e.target_id))
                    ORDER BY e.id''', (self.connection.scope, path)):
                incident[row['id']] = row
        # Each stored row appears exactly once. Overlapping roles remain visible as reasons.
        selected = {(table, id_): row for table, rows in direct.items() for id_, row in rows.items()}
        dependent = {('edges', id_): row for id_, row in incident.items() if id_ not in direct['edges']}
        selected.update(dependent)
        reasons = {}
        file_ids = {id_ for id_, node in direct['nodes'].items() if node['kind'] == 'file'}
        for id_, row in incident.items():
            self.check_time()
            matched = file_ids.intersection((row['source_id'], row['target_id']))
            reasons[('edges', id_)] = ['incident to directly matched file node ' + id_ for id_ in sorted(matched)]
        context = {}

        def owner(table, id_, reason):
            self.check_time()
            key = (table, id_)
            reasons.setdefault(key, []).append(reason)
            if key not in selected and key not in context:
                row = self.db.execute('SELECT * FROM ' + table + ' WHERE scope_id=? AND id=?',
                                      (self.connection.scope, id_)).fetchone()
                context[key] = dict(row) if row is not None else None
                if row is None:
                    self.warnings.append('Missing ' + table + ' owner/endpoint context; see explicit missing '
                                         'context elements. Context completeness is not established.')

        for evidence in direct['evidence'].values():
            for column, table in (('node_id', 'nodes'), ('edge_id', 'edges')):
                if evidence[column] is not None:
                    owner(table, evidence[column], 'owner of directly matched evidence ' + evidence['id'])
        # Only the selected edges and evidence-owned edges need endpoint context; no recursive fanout.
        edges = [(key, row) for key, row in [*selected.items(), *context.items()]
                 if key[0] == 'edges' and row is not None]
        for (_, id_), edge in edges:
            owner('nodes', edge['source_id'], 'source endpoint of edge ' + id_)
            owner('nodes', edge['target_id'], 'target endpoint of edge ' + id_)
        return direct, dependent, context, reasons

    def card(self, group, table, id_, row, reasons):
        self.check_time()
        card = dict(group=group, table=table)
        if group == 'direct_references':
            card['match_basis'] = 'own source_path equals a selected literal path'
        if reasons:
            card['context_reasons'] = [dict(reason=reason) for reason in sorted(set(reasons))]
        if row is None:
            card.update(scope_id=self.connection.scope, id=id_, status='missing owner/endpoint row')
            return card
        card['stored'] = row
        if table == 'nodes':
            for detail in ('symbol_details', 'file_details'):
                found = self.db.execute('SELECT * FROM ' + detail + ' WHERE scope_id=? AND node_id=?',
                                        (self.connection.scope, id_)).fetchone()
                if found is not None:
                    card[detail] = dict(found)
        return card


def references(connection, paths, all_output=False, timeout=TIMEOUT_SECONDS, shared=None):
    """Return the entire guarded UTF-8 result; caller alone writes stdout."""
    reader = None
    try:
        reader = ReferenceReader(connection, timeout=timeout, shared=shared)
        selected_paths = []
        seen = set()
        for path in paths:
            reader.check_time()
            if not isinstance(path, str) or not path:
                raise ReferencesError('References requires one or more nonempty literal source paths.')
            if path not in seen:
                selected_paths.append(path)
                seen.add(path)
        if not selected_paths:
            raise ReferencesError('References requires one or more nonempty literal source paths.')
        direct, dependent, context, reasons = reader.select(selected_paths)
        counts = dict(direct_nodes=len(direct['nodes']), direct_edges=len(direct['edges']),
                      direct_evidence=len(direct['evidence']), dependent_incident_edges=len(dependent),
                      additional_owner_context=len(context), missing_owner_context=sum(row is None for row in context.values()))
        counts['direct_references'] = sum(len(rows) for rows in direct.values())
        chunks, used = [], 0

        def append(line):
            nonlocal used
            reader.check_time()
            chunk = line + '\n'
            used += len(chunk.encode('utf-8'))
            reader.check_time()
            if not all_output and used > OUTPUT_BYTES:
                retry = retry_command(selected_paths, connection.shell)
                reader.check_time()
                raise ReferencesError('References output exceeds ' + str(OUTPUT_BYTES) + ' bytes; no result emitted. '
                                      + 'direct_references=' + str(counts['direct_references']) +
                                      '; additional_incident_edges=' + str(len(dependent)) +
                                      '; additional_owner_context=' + str(len(context)) + '. Full output: ' + retry)
            chunks.append(chunk)

        header = dict(scope=connection.scope, status='saved-maintenance-references', shell=connection.shell,
                      validity='all stored states', selected_paths=[dict(source_path=path) for path in selected_paths],
                      counts=counts, coverage=LIMITATION,
                      dependency_basis='Incident edges depend on directly matched file nodes; their own locator need not match.')
        for line in fields(header):
            append(line)
        for warning in dict.fromkeys(reader.warnings):
            for line in fields(dict(warning=warning)):
                append(line)
        index = 0
        groups = [('direct_references', {(table, id_): row for table, rows in direct.items() for id_, row in rows.items()}),
                  ('dependent_incident_edges', dependent), ('owner_context', context)]
        for group, rows in groups:
            for (table, id_), row in sorted(rows.items()):
                reader.check_time()
                if index:
                    append('')
                card = reader.card(group, table, id_, row, reasons.get((table, id_), []))
                for line in fields(card):
                    append(line)
                index += 1
        for line in fields(dict(complete=dict(scope=connection.scope, counts=counts,
                                             coverage='complete structured literal matches in selected scope snapshot',
                                             source_completeness='not established'))):
            append(line)
        reader.check_time()
        result = ''.join(chunks)
        reader.check_time()
        return result
    except sqlite3.Error as exc:
        if (reader is not None and time.monotonic() >= reader.deadline) or 'interrupted' in str(exc).lower():
            raise ReferencesError('References timed out; no complete result.') from exc
        raise ReferencesError('Cannot read bound references: ' + str(exc)) from exc
    finally:
        if reader is not None:
            reader.close()


def configure_parser(subparsers):
    parser = subparsers.add_parser('references', help='Find all saved structured literal source-file references',
                                  usage='evomneme references PATH [PATH ...] [--all]',
                                  epilog='Chain reads with --next before --: one snapshot and five-second deadline. '
                                         '-- makes the literal remainder the last segment; a leading-dash literal path therefore belongs in the final segment.')
    parser.add_argument('paths', nargs='+', help='Exact stored source_path; use -- before leading-dash paths')
    parser.add_argument('--all', action='store_true', dest='all_output', help='Remove the 64 KiB output guard; in a read chain opts out for the entire chain; keep the whole-chain five-second deadline')
    parser.set_defaults(references=True)


def run(connection, args):
    return references(connection, args.paths, all_output=args.all_output)
