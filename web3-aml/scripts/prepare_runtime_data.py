"""Restore the compressed runtime files before legacy UI or command-line checks."""
import _bootstrap
from api.runtime_data import ensure_runtime_data


if __name__ == '__main__':
    restored = ensure_runtime_data()
    print(f'运行数据已就绪，本次还原 {restored} 个文件。')
