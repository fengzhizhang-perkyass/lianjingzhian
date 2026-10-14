"""Offline multi-source reverse BFS: shortest directed distance to a risk anchor.

This is a graph reachability certificate derived from predictions, not an AML
label or trained model. Witness links strictly decrease distance, preventing
cycles. Whole-snapshot construction cost must be reported separately.
"""
from collections import deque
from pathlib import Path
import time
import numpy as np
from src.utils.io import save_json, read_json, file_sha256


class RiskAnchorIndex:
    def __init__(self, graph, distance, next_node, metadata):
        self.graph, self.distance, self.next_node, self.metadata = graph,distance,next_node,metadata

    @classmethod
    def build(cls,graph,risks,threshold,max_depth,provenance):
        started = time.perf_counter()
        n = len(graph.address_to_idx)
        distance = np.full(n,-1,dtype=np.int16)
        next_node = np.full(n,-1,dtype=np.int64)
        # Deterministic anchor order. BFS assigns a shortest witness; ties follow
        # stored incoming order and highest-score initial anchor order.
        anchors = sorted((a for a in risks if risks[a] >= threshold),key=lambda a:(-risks[a],a))
        queue = deque()
        for a in anchors:
            idx = graph.address_to_idx[a]
            distance[idx] = 0
            queue.append(idx)
        inspected = 0
        while queue:
            dst = queue.popleft()
            if distance[dst] >= max_depth:
                continue
            for src in graph.incoming.get(dst,[]):
                inspected += 1
                if distance[src] == -1:
                    distance[src] = distance[dst]+1
                    next_node[src] = dst
                    queue.append(int(src))
        metadata = {**provenance,'threshold':threshold,'max_depth':max_depth,
            'algorithm':'multi_source_reverse_bfs_v1','construction_edge_inspections':inspected,
            'algorithm_sha256':file_sha256(Path(__file__)),
            'construction_seconds':time.perf_counter()-started,'anchor_count':len(anchors),
            'reachable_nodes':int((distance >= 0).sum()),'tie_break':'anchor_risk_then_address_then_stored_incoming_order'}
        return cls(graph,distance,next_node,metadata)

    def save(self,folder:Path):
        folder.mkdir(parents=True,exist_ok=True)
        np.save(folder/'distance.npy',self.distance)
        np.save(folder/'next_node.npy',self.next_node)
        self.metadata['array_sha256'] = {name:file_sha256(folder/name) for name in ('distance.npy','next_node.npy')}
        save_json(folder/'metadata.json',self.metadata)

    @classmethod
    def load(cls,graph,folder:Path,provenance,threshold,max_depth):
        metadata = read_json(folder/'metadata.json')
        for key,value in {**provenance,'threshold':threshold}.items():
            if metadata.get(key) != value:
                raise ValueError(f'Risk anchor index {key} mismatch')
        if metadata['max_depth'] < max_depth:
            raise ValueError('Risk anchor index depth is insufficient')
        if metadata.get('algorithm_sha256') != file_sha256(Path(__file__)):
            raise ValueError('Risk anchor index algorithm revision mismatch')
        for name in ('distance.npy','next_node.npy'):
            if metadata.get('array_sha256',{}).get(name) != file_sha256(folder/name):
                raise ValueError('Risk anchor index array hash mismatch')
        distance = np.load(folder/'distance.npy',mmap_mode='r')
        next_node = np.load(folder/'next_node.npy',mmap_mode='r')
        if len(distance) != len(graph.address_to_idx) or len(next_node) != len(distance):
            raise ValueError('Risk anchor index shape mismatch')
        return cls(graph,distance,next_node,metadata)

    def connection(self,address,blocked,max_bridge_nodes,remaining_hops,budget):
        idx = self.graph.address_to_idx[address]
        distance = int(self.distance[idx])
        if distance < 1 or distance > max_bridge_nodes or distance > remaining_hops:
            return None
        path = [address]
        for _ in range(distance):
            if not budget.consume('index_witness'):
                return None
            previous_distance = int(self.distance[idx])
            idx = int(self.next_node[idx])
            if idx < 0 or idx >= len(self.distance) or int(self.distance[idx]) != previous_distance-1:
                raise ValueError('Corrupted anchor witness index')
            node = self.graph.idx_to_address[idx]
            if node in blocked or node in path:
                return None
            path.append(node)
        return path[:-1],path[-1]
