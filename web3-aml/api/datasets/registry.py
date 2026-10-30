"""Lazy, independent dataset contexts; failures do not silently select another chain."""
import threading
from src.utils.io import ROOT


class DatasetRegistry:
    labels = {'bitcoin': '比特币', 'ethereum': '以太坊'}

    def __init__(self, root=ROOT):
        self.root = root
        self._services = {}
        self._locks = {key: threading.RLock() for key in self.labels}

    def get(self, dataset_id):
        if dataset_id not in self.labels:
            raise ValueError('数据集无效，请选择比特币或以太坊。')
        with self._locks[dataset_id]:
            if dataset_id not in self._services:
                if dataset_id == 'bitcoin':
                    from api.datasets.bitcoin import BitcoinService
                    service = BitcoinService(self.root)
                else:
                    from api.datasets.ethereum import EthereumService
                    service = EthereumService(self.root)
                self._services[dataset_id] = service
            return self._services[dataset_id]

    def list(self):
        return {'datasets': [{'dataset_id': key, 'label': label,
                'ready': (self.root/f'artifacts/datasets/{key}/current/manifest.json').exists(),
                'description': '多维证据风险识别' if key == 'bitcoin' else '结构–属性双视图协同融合模型 SA-DCF'}
                for key, label in self.labels.items()], 'default_dataset_id': 'bitcoin'}
