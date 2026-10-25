"""Read-only graph projections for knowledge, code, and unresolved references."""

def quoted(name):
    return '"' + name.replace('"', '""') + '"'


NODE_COLUMNS = ('graph_id', 'label', 'scope_id', 'id', 'kind', 'summary', 'confidence',
                'validity', 'source_path', 'source_hash', 'line_start', 'line_end',
                'updated_at', 'evidence_count', 'layer', 'source_table', 'fingerprint')
EDGE_COLUMNS = ('graph_id', 'source', 'target', 'scope_id', 'id', 'kind', 'summary',
                'confidence', 'validity', 'source_path', 'source_hash', 'line_start',
                'updated_at', 'resolution', 'layer', 'source_table', 'fingerprint')


def projection_sql(db):
    """Namespace identities; resolve endpoints only when their meaning is unique."""
    tables = {r[0] for r in db.execute("SELECT name FROM sqlite_schema WHERE type='table'")}
    columns = {name: {r[1] for r in db.execute('PRAGMA table_info(' + quoted(name) + ')')}
               for name in ('records', 'relations', 'code_symbols', 'code_edges', 'evidence') if name in tables}
    nodes, edges, warnings = [], [], []

    def select(table, fields, names):
        return 'SELECT ' + ','.join(fields.get(c, 'NULL') + ' AS ' + quoted(c) for c in names) + ' FROM ' + quoted(table)

    def fingerprint(table):
        fields = [quoted(c) for c in sorted(columns[table])]
        chunks = ['viewer_fingerprint(' + ','.join(fields[i:i+64]) + ')' for i in range(0, len(fields), 64)]
        return chunks[0] if len(chunks) == 1 else 'viewer_fingerprint(' + ','.join(chunks) + ')'

    for table, layer, required in (
            ('records', 'knowledge', {'scope_id', 'id', 'title'}),
            ('code_symbols', 'code', {'scope_id', 'id', 'qualified_name', 'kind'})):
        if table not in columns:
            continue
        if not required <= columns[table]:
            warnings.append(table + ' requires a custom graph mapping: expected ' + ', '.join(sorted(required)))
            continue
        fields = {c: quoted(c) for c in NODE_COLUMNS if c in columns[table]}
        fields.update(graph_id=("json_array(scope_id,id)" if table == 'records' else "json_array('code',scope_id,id)"),
                      label=('title' if table == 'records' else 'qualified_name'),
                      layer="'" + layer + "'", source_table="'" + table + "'", fingerprint=fingerprint(table))
        if table == 'code_symbols':
            for alias, field in (('source_path', 'file_path'), ('source_hash', 'sha256')):
                if field in columns[table]:
                    fields[alias] = quoted(field)
        if table == 'records' and {'scope_id', 'record_id'} <= columns.get('evidence', set()):
            fields['evidence_count'] = '(SELECT count(*) FROM evidence e WHERE e.scope_id=records.scope_id AND e.record_id=records.id)'
        nodes.append(select(table, fields, NODE_COLUMNS))

    for table in ('relations', 'code_edges'):
        if table not in columns:
            continue
        if not {'scope_id', 'id', 'source_id', 'target_id'} <= columns[table]:
            warnings.append(table + ' requires a custom graph mapping for endpoints')
            continue
        fields = {c: quoted(c) for c in EDGE_COLUMNS if c in columns[table]}
        fields.update(graph_id=("json_array(scope_id,id)" if table == 'relations' else "json_array('code-edge',scope_id,id)"),
                      source='source_id', target='target_id', source_table="'" + table + "'", fingerprint=fingerprint(table))
        if table == 'code_edges':
            for alias, field in (('source_path', 'file_path'), ('source_hash', 'sha256'), ('summary', 'detail')):
                if field in columns[table]:
                    fields[alias] = quoted(field)
        edges.append(select(table, fields, EDGE_COLUMNS))
    if not nodes:
        return None
    node_sql = ' UNION ALL '.join(nodes)
    edge_sql = ' UNION ALL '.join(edges) if edges else 'SELECT ' + ','.join('NULL AS ' + quoted(c) for c in EDGE_COLUMNS) + ' WHERE 0'
    # Knowledge-only FK edges use the records namespace. Code edges may bridge
    # domains using a raw record ID or an explicit record:/knowledge-record: ID.
    common = '''WITH base_nodes AS MATERIALIZED (''' + node_sql + '''),
      names AS MATERIALIZED (
        SELECT 'all' AS domain,scope_id,id AS raw_id,graph_id,layer FROM base_nodes
        UNION ALL SELECT 'records',scope_id,id,graph_id,layer FROM base_nodes WHERE source_table='records'
        UNION ALL SELECT 'all',scope_id,'record:'||id,graph_id,layer FROM base_nodes WHERE source_table='records'
        UNION ALL SELECT 'all',scope_id,'knowledge-record:'||id,graph_id,layer FROM base_nodes WHERE source_table='records'
      ), resolved AS MATERIALIZED (
        SELECT domain,scope_id,raw_id,count(DISTINCT graph_id) AS candidates,
          CASE WHEN count(DISTINCT graph_id)=1 THEN min(graph_id) END AS graph_id,
          CASE WHEN count(DISTINCT graph_id)=1 THEN min(layer) END AS layer
        FROM names GROUP BY domain,scope_id,raw_id
      ), raw_edges AS MATERIALIZED (''' + edge_sql + '''),
      endpoints AS MATERIALIZED (
        SELECT CASE WHEN source_table='relations' THEN 'records' ELSE 'all' END AS domain,scope_id,source AS raw_id FROM raw_edges
        UNION SELECT CASE WHEN source_table='relations' THEN 'records' ELSE 'all' END,scope_id,target FROM raw_edges
      ), refs AS MATERIALIZED (
        SELECT ep.*,coalesce(r.candidates,0) AS candidates,
          json_array('unresolved',ep.domain,ep.scope_id,ep.raw_id) AS graph_id
        FROM endpoints ep LEFT JOIN resolved r USING(domain,scope_id,raw_id) WHERE r.graph_id IS NULL
      ), linked AS (
        SELECT e.*,coalesce(s.graph_id,json_array('unresolved',CASE WHEN e.source_table='relations' THEN 'records' ELSE 'all' END,e.scope_id,e.source)) AS linked_source,
          coalesce(t.graph_id,json_array('unresolved',CASE WHEN e.source_table='relations' THEN 'records' ELSE 'all' END,e.scope_id,e.target)) AS linked_target,
          CASE WHEN (s.layer='code' AND t.layer='knowledge') OR (s.layer='knowledge' AND t.layer='code') THEN 'cross'
            WHEN s.layer='code' OR t.layer='code' THEN 'code'
            WHEN s.layer='knowledge' OR t.layer='knowledge' THEN 'knowledge'
            WHEN e.source_table='relations' THEN 'knowledge' ELSE 'code' END AS linked_layer
        FROM raw_edges e
        LEFT JOIN resolved s ON s.domain=CASE WHEN e.source_table='relations' THEN 'records' ELSE 'all' END AND s.scope_id=e.scope_id AND s.raw_id=e.source
        LEFT JOIN resolved t ON t.domain=CASE WHEN e.source_table='relations' THEN 'records' ELSE 'all' END AND t.scope_id=e.scope_id AND t.raw_id=e.target
      ) '''
    ref_fields = {c: 'NULL' for c in NODE_COLUMNS}
    ref_fields.update(graph_id='graph_id', label="coalesce(CAST(raw_id AS TEXT),'(missing identifier)')",
                      scope_id='scope_id', id='raw_id', kind="CASE WHEN candidates>1 THEN 'ambiguous_reference' ELSE 'unresolved_reference' END",
                      summary="CASE WHEN candidates>1 THEN 'Multiple stored nodes match this endpoint; no target was guessed.' ELSE 'Reference target is absent from the connected graph tables; this is not a verified declaration.' END",
                      confidence="'uncertain'", layer="'unresolved'", source_table="'unresolved_reference'")
    ref_sql = 'SELECT ' + ','.join(ref_fields[c] + ' AS ' + quoted(c) for c in NODE_COLUMNS) + ' FROM refs'
    out_edges = {c: quoted(c) for c in EDGE_COLUMNS}
    out_edges.update(source='linked_source', target='linked_target', layer='linked_layer')
    return {'nodes': common + 'SELECT * FROM base_nodes UNION ALL ' + ref_sql,
            'edges': common + 'SELECT ' + ','.join(out_edges[c] + ' AS ' + quoted(c) for c in EDGE_COLUMNS) + ' FROM linked',
            'warnings': warnings}
