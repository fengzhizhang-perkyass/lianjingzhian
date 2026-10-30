"""Postprocessor math and release qualification; never fit production labels."""
import json
import hashlib
import numpy as np
import pytest

from src.probability_calibration import (
    apply_calibration_descriptor, load_calibration, model_signature,
)


def test_identity_preserves_exact_frozen_values_including_endpoints():
    p = np.array([0., .000001, .1622163259483896, .5, .9999934414491265, 1.])
    assert np.array_equal(apply_calibration_descriptor(p, {'mode':'identity','parameters':{}}), p)


@pytest.mark.parametrize('descriptor', [
    {'mode':'temperature','parameters':{'temperature':2.}},
    {'mode':'sigmoid','parameters':{'slope':.75,'intercept':-.3}},
])
def test_postprocessing_is_finite_monotone_and_does_not_cap_scores(descriptor):
    p = np.r_[0., np.linspace(.000001,.999999,100), 1.]
    actual = apply_calibration_descriptor(p, descriptor)
    assert np.isfinite(actual).all() and np.all(np.diff(actual)>0)
    assert actual[0]==0 and actual[-1]==1
    assert float(actual[-2]) != .9999


@pytest.mark.parametrize('descriptor', [
    {'mode':'temperature','parameters':{'temperature':0}},
    {'mode':'sigmoid','parameters':{'slope':-1,'intercept':0}},
    {'mode':'identity','parameters':{'scale':.8}},
    {'mode':'temperature','parameters':{'temperature':float('nan')}},
    {'mode':'unsupported','parameters':{}},
])
def test_arbitrary_scaling_or_nonmonotone_mapping_is_rejected(descriptor):
    with pytest.raises(ValueError):apply_calibration_descriptor(.7, descriptor)


def test_source_bound_identity_is_not_advertised_as_calibration(tmp_path):
    manifest={'fingerprint':'dataset','feature_revision':'features','model_path':'model.pkl',
              'source_hashes':{'model.pkl':'frozen'}}
    folder=tmp_path/'artifacts/calibration/bitcoin/current';folder.mkdir(parents=True)
    audit=b'{"status":"needs_data"}'
    (folder/'audit.json').write_bytes(audit)
    record={'dataset_id':'bitcoin','model_signature':model_signature('bitcoin',manifest),
            'status':'needs_data','mode':'identity','parameters':{},
            'audit_sha256':hashlib.sha256(audit).hexdigest()}
    (folder/'manifest.json').write_text(json.dumps(record))
    c=load_calibration(tmp_path,'bitcoin',manifest)
    assert c.describe()['status']=='needs_data' and c.apply(.99999)==.99999
    record.update(mode='temperature',parameters={'temperature':2.},status='enabled')
    (folder/'manifest.json').write_text(json.dumps(record))
    with pytest.raises(ValueError,match='qualification'):load_calibration(tmp_path,'bitcoin',manifest)
    record.update(mode='identity',parameters={},status='needs_data')
    (folder/'manifest.json').write_text(json.dumps(record))
    (folder/'audit.json').write_text('tampered')
    with pytest.raises(ValueError,match='audit hash'):load_calibration(tmp_path,'bitcoin',manifest)
