import torch
from src.model.multievidence_model import MultiEvidenceModel


def test_pointwise_evidence_model_routes_are_different_and_gate_normalized():
    model = MultiEvidenceModel([3, 4, 2], hidden_dim=8, embedding_dim=5, dropout=0)
    inputs = [torch.randn(7, width) for width in [3, 4, 2]]
    outputs = model(inputs)
    assert outputs['logits'].shape == (7,)
    assert outputs['route_logits'].shape == outputs['weights'].shape == (7, 3)
    assert torch.allclose(outputs['weights'].sum(1), torch.ones(7))
    assert ((outputs['weights'] >= 0)&(outputs['weights'] <= 1)).all()
    outputs['logits'].sum().backward()
    assert all(encoder[0].weight.grad is not None for encoder in model.encoders)


def test_single_route_and_concat_have_finite_outputs():
    model = MultiEvidenceModel([3], hidden_dim=8, embedding_dim=5, fusion='concat')
    result = model([torch.ones(2, 3)])
    assert torch.isfinite(result['logits']).all()
    assert torch.equal(result['weights'], torch.ones(2, 1))
