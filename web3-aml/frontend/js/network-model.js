// Pure view construction: grouped nodes and links never alter trace evidence.
export const relationKey = (source, target) => JSON.stringify([source, target]);
export const groupNodeId = groupId => 'group-view:' + groupId;
export const scoreLevel = score => score >= 80 ? 'CRITICAL' : score >= 60 ? 'HIGH' : score >= 30 ? 'MEDIUM' : 'LOW';

export function buildNetworkModel(record, loadedGroups = new Map(), selectedGroupId = null, collapsedGroupId = null) {
  const graph = record.result.subgraph, nodes = new Map(), edges = new Map();
  const addNode = node => {
    if (!node?.address_id || node.is_scored === false || !Number.isFinite(node.risk_score)) {
      throw new Error('群组成员与当前评分范围不匹配，请重新追踪。');
    }
    const existing = nodes.get(node.address_id);
    if (existing && Math.abs(existing.risk_score - node.risk_score) > 1e-8) {
      throw new Error('群组成员评分与当前追踪结果不一致，请重新追踪。');
    }
    if (!existing) nodes.set(node.address_id, { ...node, risk_level: node.risk_level || scoreLevel(node.risk_score), group_ids: [] });
  };
  const addEdge = (edge, groupId = null) => {
    const key = relationKey(edge.src, edge.dst);
    let value = edges.get(key);
    if (!value) { value = { ...edge, group_ids: [] }; edges.set(key, value); }
    if (groupId && !value.group_ids.includes(groupId)) value.group_ids.push(groupId);
  };
  graph.nodes.forEach(addNode);
  graph.edges.forEach(edge => addEdge(edge));
  for (const [id, group] of loadedGroups) {
    group.nodes.forEach(node => { addNode(node); nodes.get(node.address_id).group_ids.push(id); });
    group.edges.forEach(edge => addEdge(edge, id));
  }
  for (const edge of edges.values()) {
    if (!nodes.has(edge.src) || !nodes.has(edge.dst)) throw new Error('群组关系缺少完整成员，请重试加载。');
  }
  const selected = loadedGroups.get(selectedGroupId), collapsed = loadedGroups.get(collapsedGroupId);
  const selectedMembers = new Set(selected?.nodes.map(node => node.address_id) || []);
  const selectedEdges = new Set(selected?.edges.map(edge => relationKey(edge.src, edge.dst)) || []);
  const collapsedMembers = new Set(collapsed?.nodes.map(node => node.address_id) || []);
  const visibleNodes = [...nodes.values()].filter(node => !collapsedMembers.has(node.address_id)).map(node => ({
    ...node, id: node.address_id, isGroup: false, inGroup: selectedMembers.has(node.address_id),
    isSeed: node.address_id === record.result.seed_address
  }));
  if (collapsed) visibleNodes.push({
    id: groupNodeId(collapsedGroupId), isGroup: true, group_id: collapsedGroupId,
    group_score: collapsed.summary?.group_score, member_count: collapsed.nodes.length,
    edge_count: collapsed.edges.length, label: collapsed.label || '关联群组',
    containsSeed: collapsedMembers.has(record.result.seed_address), inGroup: true,
    members: [...collapsedMembers]
  });
  const visibleEdges = new Map();
  for (const edge of edges.values()) {
    const srcInside = collapsedMembers.has(edge.src), dstInside = collapsedMembers.has(edge.dst);
    if (srcInside && dstInside) continue;
    const source = srcInside ? groupNodeId(collapsedGroupId) : edge.src;
    const target = dstInside ? groupNodeId(collapsedGroupId) : edge.dst;
    const key = relationKey(source, target);
    let visible = visibleEdges.get(key);
    if (!visible) {
      visible = { id: 'relation-view:' + key, source, target, isAggregate: srcInside || dstInside,
        inGroup: selectedEdges.has(relationKey(edge.src, edge.dst)), original_edges: [], count: 0 };
      visibleEdges.set(key, visible);
    }
    visible.original_edges.push({ ...edge }); visible.count++;
  }
  return { nodes: visibleNodes, edges: [...visibleEdges.values()], allNodes: [...nodes.values()], allEdges: [...edges.values()],
    extra_nodes: nodes.size - graph.nodes.length, extra_edges: edges.size - new Set(graph.edges.map(e => relationKey(e.src, e.dst))).size };
}
