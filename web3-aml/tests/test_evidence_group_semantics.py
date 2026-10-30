"""Group descriptions follow the actual feature routes and cannot hide SHAP mass."""
from types import SimpleNamespace

import numpy as np
import pytest

from src.inference.evidence_scoring import EvidenceScoringExplainer, ROLES


class Booster:
    def __init__(self):
        self.called = False

    def predict(self, values, pred_contrib=False, raw_score=False):
        self.called = True
        return np.array([[.1, .2, -.1, .05]]) if pred_contrib else np.array([.25])


def fixture(overrides=None):
    obj = EvidenceScoringExplainer.__new__(EvidenceScoringExplainer)
    obj.model = SimpleNamespace(booster_=Booster())
    obj.info = {'schema': [
        {'group': 'behavior', 'block': 'self', 'feature': 'amount'},
        {'group': 'context', 'block': 'out_in', 'feature': 'amount', 'display_name': '共享收款方群体均值 · 金额'},
        {'group': 'structure', 'block': 'structure', 'feature': 'core'}],
        'positive_weight': 1., 'temperature': 1.}
    obj.x = np.array([[3., 2., 1.]])
    obj.raw = np.array([[100.]])
    obj.raw_names, obj.names = ['amount'], {'amount': '金额'}
    obj.metadata = {'model_name': 'fixture', 'model_version': 'internal', 'risk_revision': 'fixture'}
    if overrides is not None:
        obj.metadata['evidence_groups'] = overrides
    return obj


def explain(obj):
    return obj.explain(0, {'behavior': 10., 'context': 20., 'structure': 30.})


def test_metadata_group_descriptions_match_multihop_and_global_features():
    overrides = {
        'structure': {'label': '全局与有向结构', 'responsibility': '连通群体与资金中心性'},
        'context': {'label': '多跳关系证据', 'responsibility': '两跳和共享资金对手的行为模式'},
        'behavior': {'label': '自身行为', 'responsibility': '地址交易行为'},
    }
    result = explain(fixture(overrides))
    assert [group['key'] for group in result['groups']] == list(ROLES)
    for group in result['groups']:
        assert group['label'] == overrides[group['key']]['label']
        assert group['responsibility'] == overrides[group['key']]['responsibility']
    assert result['evidence']['context'][0]['feature'] == '共享收款方群体均值 · 金额'
    assert result['base_value']+sum(group['contribution'] for group in result['groups']) == pytest.approx(result['raw_margin'])


def test_legacy_metadata_preserves_all_original_group_descriptions():
    result = explain(fixture())
    assert {group['key']: (group['label'], group['responsibility']) for group in result['groups']} == ROLES


def test_partial_group_overrides_fall_back_per_field():
    result = explain(fixture({'context': {'label': '多跳证据'}, 'structure': {'responsibility': '全局结构'}}))
    groups = {group['key']: group for group in result['groups']}
    assert groups['context']['label'] == '多跳证据'
    assert groups['context']['responsibility'] == ROLES['context'][1]
    assert groups['structure']['label'] == ROLES['structure'][0]
    assert groups['structure']['responsibility'] == '全局结构'
    assert groups['behavior']['label'] == ROLES['behavior'][0]


@pytest.mark.parametrize('empty', [None, '', '   '])
def test_empty_override_text_uses_legacy_defaults(empty):
    result = explain(fixture({'context': {'label': empty, 'responsibility': empty}}))
    group = next(group for group in result['groups'] if group['key'] == 'context')
    assert (group['label'], group['responsibility']) == ROLES['context']


@pytest.mark.parametrize('invalid', ['new_graph_group', None, ['context']])
def test_unknown_schema_group_rejected_before_predicting(invalid):
    obj = fixture()
    obj.info['schema'][1]['group'] = invalid
    with pytest.raises(ValueError, match='Unknown evidence schema group'):
        explain(obj)
    assert obj.model.booster_.called is False


def test_missing_group_rejected_instead_of_returning_partial_attribution():
    obj = fixture()
    obj.info['schema'].pop(1)
    with pytest.raises(ValueError, match='missing groups'):
        explain(obj)
    assert obj.model.booster_.called is False


def test_schema_width_rejected_instead_of_dropping_an_input():
    obj = fixture()
    obj.info['schema'].append({'group': 'context', 'block': 'out2', 'feature': 'amount'})
    with pytest.raises(ValueError, match='schema width'):
        explain(obj)
    assert obj.model.booster_.called is False


def test_incomplete_shap_vector_is_rejected():
    obj = fixture()
    obj.model.booster_.predict = lambda values, pred_contrib=False, raw_score=False: (
        np.array([[.1, .2, .05]]) if pred_contrib else np.array([.35]))
    with pytest.raises(RuntimeError, match='TreeSHAP width'):
        explain(obj)


def test_metadata_cannot_introduce_a_fourth_group():
    obj = fixture({'extra': {'label': '额外组'}})
    with pytest.raises(ValueError, match='three existing groups'):
        explain(obj)


def test_invalid_group_text_is_rejected():
    with pytest.raises(ValueError, match='must be text'):
        explain(fixture({'context': {'label': 42}}))
