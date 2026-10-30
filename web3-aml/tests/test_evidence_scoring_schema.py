"""Feature semantics must survive new graph blocks without relabelling legacy inputs."""
from types import SimpleNamespace
import numpy as np
import pytest

from src.inference.evidence_scoring import EvidenceScoringExplainer


class FrozenBooster:
    def predict(self, values, pred_contrib=False, raw_score=False):
        return np.array([[.1,.2,-.1,.05]]) if pred_contrib else np.array([.25])


def explainer(context_schema, behavior_display=None):
    obj=EvidenceScoringExplainer.__new__(EvidenceScoringExplainer)
    behavior={'block':'self','group':'behavior','feature':'amount'}
    if behavior_display is not None:behavior['display_name']=behavior_display
    obj.model=SimpleNamespace(booster_=FrozenBooster())
    obj.info={'schema':[behavior,context_schema,{'block':'structure','group':'structure','feature':'out_degree'}],
              'positive_weight':1.,'temperature':1.}
    obj.x=np.array([[3.,2.,1.]])
    obj.raw=np.array([[100.]])
    obj.raw_names=['amount'];obj.names={'amount':'交易金额'}
    obj.metadata={'model_name':'fixture','model_version':'internal','risk_revision':'frozen-fixture'}
    return obj


def test_new_graph_block_uses_explicit_semantics_instead_of_wrong_upstream_prefix():
    obj=explainer({'block':'shared_counterparty','group':'context','feature':'cowalk_17',
                   'display_name':'共交易对手 · 二阶行为关联'},'自身金额统计')
    result=obj.explain(0,{'behavior':10.,'context':20.,'structure':30.})
    assert result['evidence']['context'][0]['feature']=='共交易对手 · 二阶行为关联'
    assert result['evidence']['behavior'][0]['feature']=='自身金额统计'
    assert result['evidence']['behavior'][0]['feature_value']==100.
    assert result['base_value']+sum(g['contribution'] for g in result['groups'])==pytest.approx(result['raw_margin'])


@pytest.mark.parametrize('display_name',[None,'','  '])
def test_legacy_schema_keeps_original_directional_display_fallback(display_name):
    schema={'block':'out_zscore','group':'context','feature':'amount'}
    if display_name is not None:schema['display_name']=display_name
    result=explainer(schema).explain(0,{'behavior':10.,'context':20.,'structure':30.})
    assert result['evidence']['context'][0]['feature']=='下游标准化偏离 · 交易金额'
    assert result['evidence']['behavior'][0]['feature']=='交易金额'
