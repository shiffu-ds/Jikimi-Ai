import numpy as np
import pytest
from jikimi_ml.data.paksnatch import augment, group_split
from jikimi_ml.eval.metrics import (
    conformal_calibration_curve,
    expected_calibration_error,
    mean_reciprocal_rank,
    precision_at_recall,
    recall_at_k,
    roc_auc,
)
from jikimi_ml.eval.stats import bootstrap_ci, fa_rate_upper, mcnemar, paired_bootstrap, poisson_upper, wilson


class TestStats:
    def test_wilson_matches_plan_example(self) -> None:
        ci = wilson(85, 100)
        assert ci.estimate == pytest.approx(0.85)
        assert ci.low == pytest.approx(0.767, abs=0.002) and ci.high == pytest.approx(0.907, abs=0.002)

    def test_rule_of_three(self) -> None:
        assert poisson_upper(0) == pytest.approx(3.0, abs=0.01)
        assert poisson_upper(1) == pytest.approx(4.74, abs=0.01)
        assert poisson_upper(2) == pytest.approx(6.30, abs=0.01)
        assert fa_rate_upper(1, 50) == pytest.approx(0.095, abs=0.001)  # < 0.1 target

    def test_bootstrap_and_paired(self) -> None:
        rng = np.random.default_rng(0)
        a = rng.normal(0.7, 0.05, 300)
        ci = bootstrap_ci(a)
        assert ci.low < 0.7 < ci.high
        ci_d, p = paired_bootstrap(a, a + 0.05)
        assert ci_d.low > 0 and p < 0.01

    def test_mcnemar(self) -> None:
        a = [True] * 50 + [False] * 50
        b = [True] * 50 + [True] * 30 + [False] * 20
        b01, b10, p = mcnemar(a, b)
        assert (b01, b10) == (30, 0) and p < 1e-6


class TestMetrics:
    def test_auc(self) -> None:
        assert roc_auc([0, 0, 1, 1], [0.1, 0.2, 0.8, 0.9]) == 1.0
        assert roc_auc([0, 1, 0, 1], [0.5, 0.5, 0.5, 0.5]) == 0.5

    def test_precision_at_recall_and_ece(self) -> None:
        y = [1, 1, 0, 1, 0, 0]
        s = [0.9, 0.8, 0.7, 0.6, 0.2, 0.1]
        assert precision_at_recall(y, s, 0.66) == 1.0
        assert expected_calibration_error([1, 0], [1.0, 0.0]) == 0.0

    def test_retrieval(self) -> None:
        ranked = [["a", "b", "c"], ["x", "y", "z"]]
        rel = [{"b"}, {"q"}]
        assert recall_at_k(ranked, rel, 2) == 0.5
        assert mean_reciprocal_rank(ranked, rel) == pytest.approx(0.25)

    def test_conformal_curve(self) -> None:
        p = np.linspace(0.001, 1, 1000)
        for alpha, fa in conformal_calibration_curve(p):
            assert fa <= alpha * 1.5 + 1e-9


def test_group_split_is_disjoint_and_stable() -> None:
    groups = np.array([f"actor{i % 40}" for i in range(400)])
    s1, s2 = group_split(groups), group_split(groups)
    assert (s1 == s2).all()
    for split in (0, 1, 2):
        mine = set(groups[s1 == split])
        others = set(groups[s1 != split])
        assert not mine & others


def test_augment_flip_swaps_sides() -> None:
    rng = np.random.default_rng(1)
    x = np.zeros((3, 32, 17, 2), np.float32)
    x[0, :, 9, 0] = 1.0  # left wrist x
    seen = set()
    for _ in range(20):
        y = augment(x, rng)
        seen.add(bool(np.abs(y[0, :, 10, 0] + 1.0).mean() < 0.1))
    assert seen == {True, False}  # sometimes flipped (left->right, x mirrored), sometimes not


torch = pytest.importorskip("torch")


def test_stgcn_shapes_and_backward() -> None:
    from jikimi_ml.models.stgcn import FocalLoss, TwoPersonSTGCN, spatial_partition

    a = spatial_partition()
    assert a.shape == (3, 17, 17) and np.allclose(a.sum(axis=(0, 1)), 1.0, atol=1e-3)
    m = TwoPersonSTGCN()
    x = torch.randn(4, 3, 32, 17, 2)
    logits = m(x)
    assert logits.shape == (4,)
    loss = FocalLoss()(logits, torch.tensor([1.0, 0.0, 0.0, 1.0]))
    loss.backward()
    assert sum(p.numel() for p in m.parameters()) < 1_000_000


def test_trajectory_transformer_scores() -> None:
    from jikimi_ml.models.trajectory_tf import TrajectoryTransformer, masked_nll, random_mask

    m = TrajectoryTransformer(num_cameras=3, d_model=32, heads=2, layers=1)
    cams = torch.randint(0, 3, (5, 8))
    cont = torch.randn(5, 8, 6)
    mask = random_mask((5, 8))
    nll = masked_nll(m, cams, cont, mask)
    assert nll.shape == (5,) and torch.isfinite(nll).all()


def test_onnx_export_runs_in_onnxruntime(tmp_path) -> None:
    pytest.importorskip("onnxruntime")
    from jikimi_ml.export.to_onnx import export
    from jikimi_ml.models.stgcn import TwoPersonSTGCN
    from jikimi_ml_runtime import load_engine

    m = TwoPersonSTGCN()
    path = export(m, tmp_path / "stgcn.onnx")
    engine = load_engine(path, "onnxruntime")
    out = engine.infer(np.zeros((1, 3, 32, 17, 2), np.float32))[0]
    with torch.no_grad():
        ref = m(torch.zeros(1, 3, 32, 17, 2)).numpy()
    assert np.allclose(out.reshape(-1), ref.reshape(-1), atol=1e-4)


def test_cluster_bootstrap_widens_ci_for_correlated_windows() -> None:
    from jikimi_ml.eval.metrics import roc_auc
    from jikimi_ml.eval.stats import cluster_bootstrap_ci

    rng = np.random.default_rng(0)
    groups = np.repeat(np.arange(40), 10)  # 40 episodes, 10 near-identical windows each
    y = np.repeat(rng.integers(0, 2, 40), 10)
    s = np.repeat(rng.random(40), 10) + 0.01 * rng.random(400)
    episodes = cluster_bootstrap_ci(y, s, groups, roc_auc)
    windows = cluster_bootstrap_ci(y, s, np.arange(400), roc_auc)  # pretends windows are independent
    assert episodes.low <= episodes.estimate <= episodes.high
    assert episodes.high - episodes.low > 1.5 * (windows.high - windows.low)


def test_evaluate_stgcn_on_held_out_episodes(tmp_path) -> None:
    pytest.importorskip("onnxruntime")
    import json

    from jikimi_ml.eval.evaluate_stgcn import evaluate
    from jikimi_ml.export.to_onnx import export
    from jikimi_ml.models.stgcn import TwoPersonSTGCN

    rng = np.random.default_rng(1)
    groups = np.repeat(np.arange(60), 5)
    np.savez(
        tmp_path / "d.npz",
        x=rng.normal(size=(300, 3, 32, 17, 2)).astype(np.float32),
        y=np.repeat(rng.integers(0, 2, 60), 5).astype(np.int64),
        group=groups,
    )
    model = export(TwoPersonSTGCN(), tmp_path / "m.onnx")
    res = evaluate(model, tmp_path / "d.npz", batch=7)  # odd batch: the tail batch must work too
    test_windows = int((group_split(groups) == 2).sum())
    assert res["test_windows"] == test_windows > 0 and res["test_episodes"] * 5 == test_windows
    assert 0.0 <= res["test_auc_ci95"][0] <= res["test_auc"] <= res["test_auc_ci95"][1] <= 1.0
    json.dumps(res)  # report must stay JSON-serialisable
