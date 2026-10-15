from tracebrain import scoring

T, W = 10_000, 3_600
W8 = {k: 1.0 for k in scoring.FEATURES}


def row(deploy, service, hops, age, size=10):
    return {"deploy": deploy, "service": service, "proximity": hops, "ts": T - age, "change_size": size}


def test_closer_beats_farther_at_equal_recency():
    ranked = scoring.rank([row("far", "redis", 2, 600), row("near", "checkout", 0, 600)], T, W, {}, {}, weights=W8)
    assert [r["deploy"] for r in ranked] == ["near", "far"]


def test_lesson_match_flips_the_ranking():
    rows = [row("newer", "frontend", 1, 60), row("older", "redis", 2, 3000)]
    assert scoring.rank(rows, T, W, {}, {}, weights=W8)[0]["deploy"] == "newer"
    with_lesson = scoring.rank(rows, T, W, {}, {}, lesson_boosts={"redis": 1.0},
                               weights={**W8, "lesson_match": 3.0})
    assert with_lesson[0]["deploy"] == "older"


def test_features_are_bounded_and_rank_is_deterministic():
    rows = [row("a", "s", 0, 0, 10**6), row("b", "s", 0, 0, 10**6)]
    ranked = scoring.rank(rows, T, W, {"s": 99}, {"s": 7.0}, lesson_boosts={"s": 5.0}, weights=W8)
    assert all(0 <= v <= 1 for r in ranked for v in r["features"].values())
    assert [r["deploy"] for r in ranked] == ["a", "b"] and [r["rank"] for r in ranked] == [1, 2]


def test_deploy_outside_window_gets_zero_recency():
    f = scoring.features({"ts": T - 2 * W, "proximity": 0, "change_size": 1}, T, W, 0, 0.0)
    assert f["recency"] == 0.0
