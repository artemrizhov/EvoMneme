"""Graph projections for the controlled EvoMneme schema."""

SCHEMA_VERSION = '3'
V3_COLUMNS = {
    'metadata': {'key', 'value'},
    'scopes': {'id', 'branch', 'worktree', 'revision', 'snapshot', 'created_at'},
    'nodes': {'scope_id', 'id', 'kind', 'title', 'summary', 'confidence', 'validity',
              'source_path', 'source_hash', 'line_start', 'line_end', 'updated_at', 'layer'},
    'edges': {'scope_id', 'id', 'source_id', 'target_id', 'kind', 'summary', 'confidence',
              'validity', 'source_path', 'source_hash', 'updated_at', 'layer', 'resolution',
              'line_start', 'line_end'},
    'evidence': {'scope_id', 'id', 'node_id', 'edge_id', 'description', 'source_path',
                 'source_hash', 'validity', 'updated_at'},
    'symbol_details': {'scope_id', 'node_id', 'qualified_name', 'signature', 'language'},
    'file_details': {'scope_id', 'node_id', 'declaration_status', 'relationship_status',
                     'inspected_hash', 'exclusion_reason', 'remaining_work'},
    'history': {'id', 'happened_at', 'action', 'detail'},
}

def quoted(name):
    return '"' + name.replace('"', '""') + '"'


NODE_COLUMNS = ('graph_id', 'label', 'scope_id', 'id', 'kind', 'summary', 'confidence',
                'validity', 'source_path', 'source_hash', 'line_start', 'line_end',
                'updated_at', 'evidence_count', 'layer', 'source_table', 'fingerprint')
EDGE_COLUMNS = ('graph_id', 'source', 'target', 'scope_id', 'id', 'kind', 'summary',
                'confidence', 'validity', 'source_path', 'source_hash', 'line_start',
                'updated_at', 'resolution', 'layer', 'source_table', 'fingerprint')


def validate_schema(db):
    """Reject unsupported stores before reads, custom projections or journal writes."""
    tables = {r[0] for r in db.execute("SELECT name FROM sqlite_schema WHERE type='table'")}
    version = None
    if 'metadata' in tables:
        columns = {r[1] for r in db.execute('PRAGMA table_info(metadata)')}
        if {'key', 'value'} <= columns:
            row = db.execute("SELECT value FROM metadata WHERE key='schema_version'").fetchone()
            version = row[0] if row else None
    user_version = db.execute('PRAGMA user_version').fetchone()[0]
    if version != SCHEMA_VERSION or user_version != int(SCHEMA_VERSION):
        raise ValueError('Unsupported EvoMneme schema version ' + str(version) + ' / user_version=' + str(user_version) +
                         '; this viewer requires v3. Apply a compatible published migration before opening this database.')
    for table, expected in V3_COLUMNS.items():
        columns = {r[1] for r in db.execute('PRAGMA table_info(' + quoted(table) + ')')} if table in tables else set()
        if not expected <= columns:
            raise ValueError('Incompatible EvoMneme v3 table ' + table + ': missing ' + ', '.join(sorted(expected - columns)))


def projection_sql(db):
    """One identity namespace and adjacency model, regardless of node kind."""
    validate_schema(db)

    def fingerprint(alias, table):
        return 'viewer_fingerprint(' + ','.join(alias + '.' + quoted(c) for c in sorted(V3_COLUMNS[table])) + ')'

    node_fields = {c: 'n.' + quoted(c) for c in NODE_COLUMNS if c in V3_COLUMNS['nodes']}
    node_fields.update(graph_id='json_array(n.scope_id,n.id)', label='n.title', source_table="'nodes'",
                       evidence_count='(SELECT count(*) FROM evidence p WHERE p.scope_id=n.scope_id AND p.node_id=n.id)',
                       fingerprint='viewer_fingerprint(' + ','.join([fingerprint('n', 'nodes'), fingerprint('s', 'symbol_details'), fingerprint('f', 'file_details')]) + ')')
    edge_fields = {c: 'e.' + quoted(c) for c in EDGE_COLUMNS if c in V3_COLUMNS['edges']}
    edge_fields.update(graph_id='json_array(e.scope_id,e.id)', source='json_array(e.scope_id,e.source_id)',
                       target='json_array(e.scope_id,e.target_id)', source_table="'edges'", fingerprint=fingerprint('e', 'edges'))
    nodes = 'SELECT ' + ','.join(node_fields.get(c, 'NULL') + ' AS ' + quoted(c) for c in NODE_COLUMNS)
    nodes += ' FROM nodes n LEFT JOIN symbol_details s ON s.scope_id=n.scope_id AND s.node_id=n.id LEFT JOIN file_details f ON f.scope_id=n.scope_id AND f.node_id=n.id'
    edges = 'SELECT ' + ','.join(edge_fields.get(c, 'NULL') + ' AS ' + quoted(c) for c in EDGE_COLUMNS) + ' FROM edges e'
    return {'nodes': nodes, 'edges': edges, 'warnings': []}
