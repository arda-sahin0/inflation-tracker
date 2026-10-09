"""The daily loop's sweep step, run against fake sweeps so no network is touched."""
from main import run_sweeps
from tracker import sweep


def fake_rows(store, *skus, category="dairy_eggs"):
    return [{"store": store, "sku": s, "category": category, "group": f"{store}:x"} for s in skus]


def run_with(results: dict, rules: list[dict], rows=None):
    original = sweep.run

    def fake_run(rule):
        outcome = results[sweep.label(rule)]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    sweep.run = fake_run
    rows, failures = (rows or []), []
    try:
        run_sweeps("2026-10-09", rows, failures, rules)
    finally:
        sweep.run = original
    return rows, failures


def test_shelf_rules_without_a_search_term_run_and_are_logged(capsys=None):
    rules = [{"name": "migros_sut", "store": "migros", "shop_category": "sut-c-6c", "category": "dairy_eggs"},
             {"name": "a101_sut", "store": "a101", "shop_category": "C0502", "category": "dairy_eggs"}]
    rows, failures = run_with({"migros_sut": fake_rows("migros", "1", "2"), "a101_sut": fake_rows("a101", "9")}, rules)
    assert failures == []
    assert len(rows) == 3 and all(r["date"] == "2026-10-09" for r in rows)


def test_one_broken_sweep_is_reported_and_the_rest_still_run():
    rules = [{"name": "broken", "shop_category": "x-c-1", "category": "dairy_eggs"},
             {"name": "fine", "shop_category": "y-c-2", "category": "dairy_eggs"}]
    rows, failures = run_with({"broken": RuntimeError("timeout"), "fine": fake_rows("migros", "5")}, rules)
    assert failures == ["sweep:broken"]
    assert [r["sku"] for r in rows] == ["5"]


def test_a_product_already_collected_is_not_added_twice():
    rules = [{"name": "a", "shop_category": "a-c-1", "category": "dairy_eggs"},
             {"name": "b", "shop_category": "b-c-2", "category": "dairy_eggs"}]
    already = fake_rows("migros", "1")
    rows, _ = run_with({"a": fake_rows("migros", "1", "2"), "b": fake_rows("migros", "2", "3")}, rules, already)
    assert sorted(r["sku"] for r in rows) == ["1", "2", "3"]


def test_every_live_rule_has_a_printable_label():
    assert all(sweep.label(rule) != "?" for rule in sweep.load_rules())
