/* A read-only implementation of the viewer routes over a published graph snapshot.
 * The renderer and its interaction code remain the local viewer's own files. */
(function (root) {
  'use strict';
  const fields = ['scope_id', 'kind', 'validity', 'confidence', 'source_path'];
  const groupFields = [...fields, 'layer'];
  const compare = (a, b) => String(a.graph_id).localeCompare(String(b.graph_id), 'en');
  const bounded = (value, fallback, max) => Math.max(0, Math.min(max, Number.isFinite(Number(value)) ? Math.floor(Number(value)) : fallback));
  const groupId = (field, value) => JSON.stringify(['group', field, value ?? null]);
  function historyPage(events, field, values = {}) {
    const after = values.after_id, before = values.before_id;
    if (after != null && before != null) throw new Error('Choose after_id or before_id');
    if (after != null && (!Number.isSafeInteger(after) || after < 0)) throw new Error('Invalid after_id');
    if (before != null && (!Number.isSafeInteger(before) || before < 1)) throw new Error('Invalid before_id');
    const limit = Math.max(1, bounded(values.limit, 100, 200));
    const ordered = [...events].sort((a, b) => a[field] - b[field]);
    const matching = ordered.filter(event => (after == null || event[field] > after) && (before == null || event[field] < before));
    const selected = after != null ? matching.slice(0, limit) : matching.slice(-limit);
    const first = selected[0]?.[field] ?? before ?? 0;
    return {events: selected, after_id: Math.max(after ?? 0, ...selected.map(event => event[field])),
      before_id: first, has_older: ordered.some(event => event[field] < first), has_more: after != null && matching.length > limit};
  }
  function sourceLink(metadata, row) {
    const repo = String(metadata.repository || '').replace(/\/$/, '');
    const path = String(row.source_path || '');
    if (!/^https:\/\/github\.com\/[\w.-]+\/[\w.-]+$/.test(repo)) return null;
    if (!path || path.startsWith('/') || path.includes('\\') || path.split('/').some(p => p === '..' || p === '.') || /^[a-z]+:/i.test(path)) return null;
    // The exporter emits source_url only when the stored source hash matches a
    // public git blob. A path alone may describe dirty or unavailable source.
    const supplied = String(row.source_url || ''), prefix = repo + '/blob/';
    if (!supplied.startsWith(prefix)) return null;
    const revision = supplied.slice(prefix.length).split('/')[0];
    if (!/^[a-f0-9]{40}$/i.test(revision) || revision !== metadata.public_revision) return null;
    const expected = prefix + revision + '/' + path.split('/').map(encodeURIComponent).join('/');
    const fragment = supplied.slice(expected.length);
    if (!supplied.startsWith(expected) || (fragment && !/^#L[1-9]\d*(?:-L[1-9]\d*)?$/.test(fragment))) return null;
    return supplied;
  }
  function createAPI(data) {
    if (!data || !Array.isArray(data.nodes) || !Array.isArray(data.edges)) throw new Error('Invalid public graph snapshot');
    const nodes = data.nodes, edges = data.edges, metadata = data.metadata || {};
    const byId = new Map(nodes.map(n => [n.graph_id, n]));
    const byIdentity = new Map(nodes.map(n => [JSON.stringify([n.scope_id, n.id]), n]));
    if (byId.size !== nodes.length || nodes.some(n => typeof n.graph_id !== 'string') || new Set(edges.map(e => e.graph_id)).size !== edges.length) throw new Error('Snapshot graph IDs must be unique text');
    const endpoints = new Set(edges.flatMap(e => [e.source, e.target]));
    const facet = (rows, field) => {
      const counts = new Map();
      for (const row of rows) { const value = row[field] ?? null; counts.set(value, (counts.get(value) || 0) + 1); }
      return [...counts].map(([value, count]) => ({value, count})).sort((a, b) => b.count - a.count || String(a.value).localeCompare(String(b.value))).slice(0, 200);
    };
    const layers = new Map();
    for (const [name, rows] of [['nodes', nodes], ['edges', edges]]) for (const row of rows) {
      const layer = row.layer || 'custom';
      if (!layers.has(layer)) layers.set(layer, {id: layer, nodes: 0, edges: 0});
      layers.get(layer)[name]++;
    }
    function snapshot(values = {}) {
      const excluded = values.excluded_layers || [];
      if (!Array.isArray(excluded) || excluded.length > 200 || excluded.some(v => typeof v !== 'string')) throw new Error('Invalid excluded layers');
      const hidden = new Set(excluded), whole = values.whole_graph === true;
      const limit = whole ? 100000 : Math.max(1, bounded(values.limit, 500, 2000));
      const offset = whole ? 0 : bounded(values.offset, 0, 100000000);
      const visible = new Set(nodes.filter(n => !hidden.has(n.layer)).map(n => n.graph_id));
      const selections = {};
      for (const key of [...fields, 'edge_kind', 'edge_validity', 'edge_confidence']) {
        let selected = values[key];
        if (selected == null || selected === '') selected = [];
        if (typeof selected === 'string') selected = [selected];
        if (!Array.isArray(selected) || selected.length > 1000 || selected.some(v => typeof v !== 'string' || v.length > 10000)) throw new Error('Invalid filter values: ' + key);
        selections[key] = new Set(selected);
      }
      const matches = (key, value) => !selections[key].size || selections[key].has(value);
      const matchingEdges = edges.filter(e => !hidden.has(e.layer) && visible.has(e.source) && visible.has(e.target) && ['kind', 'validity', 'confidence'].every(f => matches('edge_' + f, e[f])));
      const search = String(values.search || '').toLowerCase();
      let matching = nodes.filter(n => visible.has(n.graph_id) && fields.every(f => matches(f, n[f])) &&
        (!fields.includes(values.null_field) || n[values.null_field] == null) &&
        (!search || ['label', 'graph_id', 'summary', 'source_path'].some(f => String(n[f] ?? '').toLowerCase().includes(search))) &&
        (values.focus !== 'unsupported' || n.evidence_count === 0) && (values.focus !== 'isolated' || !endpoints.has(n.graph_id)));
      const result = {tables: [], bytes: 0, graph_available: true, offset, whole_graph: whole,
        revision: metadata.revision || metadata.commit || 'published-snapshot', elapsed_ms: 0,
        totals: {nodes: nodes.length, edges: edges.length}, layers: [...layers.values()], journal: metadata.history?.journal || null,
        facets: Object.fromEntries(fields.map(f => [f, facet(nodes, f)])),
        edge_facets: Object.fromEntries(['kind', 'validity', 'confidence'].map(f => [f, facet(edges, f)])),
        isolated_total: nodes.filter(n => !endpoints.has(n.graph_id)).length,
        dangling_total: edges.filter(e => !byId.has(e.source) || !byId.has(e.target)).length,
        reference_total: layers.get('unresolved')?.nodes || 0, projection_warnings: []};
      let selectionEdges = matchingEdges;
      if (values.aggregate) {
        const field = values.aggregate;
        if (!groupFields.includes(field)) throw new Error('Grouping field is unavailable');
        const groups = new Map(), members = new Map();
        for (const node of matching) {
          const value = node[field] ?? null, id = groupId(field, value);
          if (!groups.has(id)) groups.set(id, {graph_id: id, label: String(value ?? '(unspecified)'), group_value: value,
            _aggregate: field, [field]: value, member_count: 0, current_count: 0, stale_count: 0, uncertain_count: 0, without_evidence_count: 0});
          const group = groups.get(id); group.member_count++;
          group.current_count += Number(node.validity === 'current'); group.stale_count += Number(node.validity === 'stale');
          group.uncertain_count += Number(node.confidence === 'uncertain'); group.without_evidence_count += Number(node.evidence_count === 0);
          members.set(node.graph_id, id);
        }
        const pairs = new Map();
        for (const edge of matchingEdges) {
          const source = members.get(edge.source), target = members.get(edge.target);
          if (!source || !target) continue;
          const id = JSON.stringify(['group-edge', source, target]);
          if (!pairs.has(id)) pairs.set(id, {graph_id: id, source, target, member_count: 0, _aggregate: field});
          pairs.get(id).member_count++;
        }
        result.aggregate = field; result.grouped_members = matching.length;
        matching = [...groups.values()]; selectionEdges = [...pairs.values()];
      } else if (values.root) {
        const reached = new Set([values.root]);
        const depth = bounded(values.depth, 1, 4);
        for (let step = 0; step < depth; step++) {
          const next = new Set(reached);
          for (const edge of matchingEdges) {
            if (reached.has(edge.source)) next.add(edge.target);
            if (reached.has(edge.target)) next.add(edge.source);
          }
          if (next.size === reached.size) break;
          next.forEach(id => reached.add(id));
        }
        matching = matching.filter(n => reached.has(n.graph_id));
      }
      matching.sort(compare);
      result.matched_nodes = matching.length;
      result.nodes = matching.slice(offset, offset + limit);
      result.node_has_more = offset + limit < matching.length;
      const selected = new Set(result.nodes.map(n => n.graph_id));
      const internal = selectionEdges.filter(e => selected.has(e.source) && selected.has(e.target)).sort(compare);
      const edgeLimit = whole ? 200000 : 2000;
      result.edges = internal.slice(0, edgeLimit); result.edge_has_more = internal.length > edgeLimit;
      result.boundary_edges = selectionEdges.filter(e => selected.has(e.source) !== selected.has(e.target)).reduce((sum, e) => sum + (e.member_count || 1), 0);
      return result;
    }
    function detail(values = {}) {
      if (!['nodes', 'edges'].includes(values.type)) throw new Error('Unknown graph projection');
      const rows = data[values.type].filter(row => row.graph_id === values.id).map(row => ({...row}));
      const row = rows[0], owner = values.type === 'nodes' ? 'node_id' : 'edge_id';
      const evidence = row?.id != null ? (data.evidence || []).filter(item => item.scope_id === row.scope_id && item[owner] === row.id) : [];
      let coverage = [];
      if (row && values.type === 'nodes') {
        const symbol = (data.symbol_details || []).find(item => item.scope_id === row.scope_id && item.node_id === row.id);
        if (symbol) for (const field of ['qualified_name', 'signature', 'language']) row[field] = symbol[field];
        coverage = (data.file_details || []).filter(item => {
          if (item.scope_id !== row.scope_id) return false;
          if (item.node_id === row.id) return true;
          const file = byIdentity.get(JSON.stringify([item.scope_id, item.node_id]));
          return row.source_path && file?.kind === 'file' && file.validity === 'current' && file.source_path === row.source_path;
        }).map(item => {
          const file = byIdentity.get(JSON.stringify([item.scope_id, item.node_id]));
          return {...item, source_path: file?.source_path, ...(file?.source_url ? {source_url: file.source_url} : {})};
        });
      }
      const supplied = data.details?.[values.type]?.[values.id];
      return {rows, evidence, evidence_has_more: false, coverage, ...supplied};
    }
    function initialHistory(route, values = {}) {
      if (!['events', 'changes'].includes(route)) return null;
      const page = metadata.history?.initial?.[route];
      if (!page || !Array.isArray(page.events) || values.before_id != null) return null;
      if (values.after_id != null) {
        if (!Number.isSafeInteger(values.after_id) || values.after_id < page.after_id) return null;
        // A fixed export has no future events after its saved last cursor.
        return {...page, events: [], after_id: values.after_id, before_id: 0, has_older: false, has_more: false};
      }
      const limit = Math.max(1, bounded(values.limit, 100, 200));
      if (limit > 100) return null;
      const selected = page.events.slice(-limit), field = route === 'events' ? 'activity_record_id' : 'change_id';
      return {...page, events: selected, before_id: selected[0]?.[field] ?? 0,
        has_older: Boolean(page.has_older || page.events.length > limit), has_more: false};
    }
    return {metadata, sourceLink: row => sourceLink(metadata, row), snapshot, detail, initialHistory,
      request(route, values, resource) {
        if (route === 'snapshot') return snapshot(values);
        if (route === 'detail') return detail(values);
        if (route === 'replay') {
          if (!resource || !Array.isArray(resource.nodes) || !Array.isArray(resource.edges) || !Array.isArray(resource.events)) throw new Error('No saved graph history is available in this snapshot.');
          return resource;
        }
        if (route === 'changes') return {journal: resource?.journal || metadata.history?.journal || {}, ...historyPage(resource?.changes || [], 'change_id', values)};
        if (route === 'events') return {cursors: {}, enabled: Boolean(resource?.calls?.length), storage: 'database', ...historyPage(resource?.calls || [], 'activity_record_id', values)};
        throw new Error('This public snapshot supports graph exploration only. Run the local viewer for SQL and activity.');
      }};
  }
  const exported = {createAPI, sourceLink};
  if (typeof module !== 'undefined' && module.exports) module.exports = exported;
  else root.EvoMnemeStatic = exported;
})(typeof globalThis !== 'undefined' ? globalThis : this);
