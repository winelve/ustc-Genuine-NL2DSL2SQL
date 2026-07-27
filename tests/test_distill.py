"""蒸馏与测量的纯函数：闸门统计、泛化黑名单。"""


def test_measure_counts_useful_and_harmful():
    from scripts.measure_checks import measure
    # 题 0/2 判错，题 1/3 判对
    match = {0: False, 1: True, 2: False, 3: True}
    hits = {"S1": [0, 1, 2]}
    out = measure(hits, match)
    assert out["S1"]["trigger"] == 3
    assert out["S1"]["useful"] == 2
    assert out["S1"]["harmful"] == 1
    assert out["S1"]["useful_ids"] == [0, 2]
    assert out["S1"]["harmful_ids"] == [1]
    assert abs(out["S1"]["precision"] - 2 / 3) < 1e-9


def test_measure_zero_trigger_precision_is_zero():
    """从不触发的检查 precision 记 0，不是除零也不是 1。"""
    from scripts.measure_checks import measure
    out = measure({"S9": []}, {0: False})
    assert out["S9"] == {"trigger": 0, "useful": 0, "harmful": 0,
                         "precision": 0.0, "useful_ids": [], "harmful_ids": []}


def test_measure_ignores_indices_absent_from_results():
    """预测比结果长时，多出来的题号不参与统计而不是崩掉。"""
    from scripts.measure_checks import measure
    out = measure({"S1": [0, 99]}, {0: False})
    assert out["S1"]["trigger"] == 1
