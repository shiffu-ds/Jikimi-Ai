import pytest

from eval.golden.run import load_cases, run_case

CASES = [(c, s) for c in load_cases() for s in c["seeds"]]


@pytest.mark.slow
@pytest.mark.parametrize(("case", "seed"), CASES, ids=[f"{c['case']}-{s}" for c, s in CASES])
def test_golden(case: dict, seed: int) -> None:
    result = run_case(case, seed)
    assert result.ok, f"{result.reason}: {result.alerts}"
