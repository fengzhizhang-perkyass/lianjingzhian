from pathlib import Path
import pickle
from src.utils.io import ROOT, read_json


class DirectedGraph:
    def __init__(self, outgoing, incoming, address_to_idx, idx_to_address, metadata=None):
        self.outgoing = outgoing
        self.incoming = incoming
        self.address_to_idx = address_to_idx
        self.idx_to_address = {int(k): v for k, v in idx_to_address.items()}
        self.metadata = metadata or {}

    @classmethod
    def load(cls, root: Path = ROOT):
        folder = root / "data/processed"
        with (folder / "outgoing_neighbors.pkl").open("rb") as stream:
            outgoing = pickle.load(stream)
        with (folder / "incoming_neighbors.pkl").open("rb") as stream:
            incoming = pickle.load(stream)
        return cls(outgoing, incoming, read_json(folder / "address_to_idx.json"),
                   read_json(folder / "idx_to_address.json"), read_json(folder / "metadata.json"))

    def iter_out_neighbors(self, address):
        """Stream the stored adjacency order, without materializing an unbounded list."""
        for idx in self.outgoing.get(self.address_to_idx[address], []):
            yield self.idx_to_address[int(idx)]

    def out_neighbors(self, address):
        idx = self.address_to_idx[address]
        return [self.idx_to_address[i] for i in self.outgoing.get(idx, [])]

    def neighbors(self, address):
        idx = self.address_to_idx[address]
        ids = set(self.outgoing.get(idx, [])) | set(self.incoming.get(idx, []))
        ids.discard(idx)
        return [self.idx_to_address[i] for i in sorted(ids)]

    def degrees(self, address):
        idx = self.address_to_idx[address]
        return len(self.outgoing.get(idx, [])), len(self.incoming.get(idx, []))
