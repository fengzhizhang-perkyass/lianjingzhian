import _bootstrap
from src.inference.precompute_investigation import precompute_investigation

if __name__ == "__main__":
    result = precompute_investigation()
    print({key: value for key, value in result.items() if key not in {"source_hashes"}})
