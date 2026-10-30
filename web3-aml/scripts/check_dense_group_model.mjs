import assert from 'node:assert/strict';
import { buildNetworkModel, groupNodeId } from '../frontend/js/network-model.js';
const node = (address_id, risk_score) => ({ address_id, risk_score, is_scored: true });
const record = { trace_id: 'fixture_only', result: { seed_address: 'A', subgraph: { nodes: [node('A', 90), node('B', 5), node('X', 10)], edges: [{ src: 'A', dst: 'B' }, { src: 'B', dst: 'X' }, { src: 'X', dst: 'A' }] }, top_paths: [{ nodes: ['A', 'B', 'X'] }] } };
const source = JSON.stringify(record), groups = new Map([
 ['g1', { label: '关联群组01', nodes: [node('A', 90), node('B', 5), node('C', 40)], edges: [{ src: 'A', dst: 'B' }, { src: 'B', dst: 'C' }], summary: { group_score: 73 } }],
 ['g2', { label: '关联群组02', nodes: [node('B', 5), node('C', 40), node('D', 70)], edges: [{ src: 'B', dst: 'C' }, { src: 'C', dst: 'D' }], summary: { group_score: 65 } }]
]);
let model = buildNetworkModel(record); assert.equal(model.nodes.length, 3); assert.equal(model.edges.length, 3);
model = buildNetworkModel(record, groups, 'g1'); assert.equal(model.nodes.length, 5); assert.equal(model.extra_nodes, 2); assert.equal(model.extra_edges, 2); assert.equal(model.nodes.filter(n => n.inGroup).length, 3); assert.equal(model.edges.filter(e => e.inGroup).length, 2); assert.equal(model.nodes.find(n => n.id === 'B').risk_score, 5);
const expandedKeys = model.allEdges.map(e => [e.src, e.dst]);
model = buildNetworkModel(record, groups, 'g1', 'g1'); assert.equal(model.nodes.filter(n => n.isGroup).length, 1); assert.equal(model.nodes.length, 3); assert.equal(model.nodes.find(n => n.id === groupNodeId('g1')).containsSeed, true); assert.equal(model.edges.filter(e => e.isAggregate).length, 3); assert.deepEqual(model.allEdges.map(e => [e.src, e.dst]), expandedKeys);
model = buildNetworkModel(record, groups, 'g2', 'g2'); assert.equal(model.nodes.filter(n => n.isGroup).length, 1); assert.ok(model.nodes.find(n => n.id === 'A')); assert.ok(!model.nodes.find(n => n.id === groupNodeId('g1')));
model = buildNetworkModel(record, groups); assert.equal(model.nodes.length, 5); assert.equal(model.edges.length, 5); assert.deepEqual(model.allEdges.map(e => [e.src, e.dst]), expandedKeys); assert.equal(JSON.stringify(record), source);
assert.throws(() => buildNetworkModel(record, new Map([['bad', { nodes: [node('B', 99)], edges: [] }]])), /不一致/);
assert.throws(() => buildNetworkModel(record, new Map([['bad', { nodes: [{ address_id: 'Z', is_scored: false }], edges: [] }]])), /评分范围/);
assert.throws(() => buildNetworkModel(record, new Map([['bad', { nodes: [], edges: [{ src: 'A', dst: 'missing' }] }]])), /完整成员/);
console.log('PASS graph view: original evidence immutable, low-risk scores unchanged, exact edges, overlap and seed-safe unique aggregation, full restoration, invalid score/edge rejection');
