from copy import deepcopy

import pytest

from qlab.dynamic_factor.harness import _wf
from qlab.dynamic_factor.validation import wf_manifest_check


def test_valid_manifest_is_validation_only():
    r = wf_manifest_check(_wf())
    assert r["ok"] and not r["certifiable"]
    assert r["metrics"]["beta"] is None


@pytest.mark.parametrize(
    "mutation,reason",
    [
        (lambda m: m["series"]["SPY"].pop(2), "data.calendar_gap"),
        (lambda m: m["series"]["SPY"].pop(), "data.benchmark_calendar_gap"),
        (
            lambda m: m["series"]["SPY"][2].update(date="2026-01-10"),
            "data.nontrading_bar",
        ),
        (
            lambda m: m["series"]["SPY"][2].update(close=-1),
            "data.nonpositive_or_unknown_price",
        ),
        (
            lambda m: m["series"]["SPY"][2].update(close=0),
            "data.nonpositive_or_unknown_price",
        ),
        (
            lambda m: m["series"]["SPY"][2].update(close=None),
            "data.nonpositive_or_unknown_price",
        ),
        (
            lambda m: m["series"]["SPY"].append(m["series"]["SPY"][0]),
            "data.duplicate_or_unsorted_dates",
        ),
        (lambda m: m["series"].update(SPY=[]), "data.empty_series"),
    ],
)
def test_data_fail_closed_without_mutation(mutation, reason):
    manifest = _wf()
    mutation(manifest)
    before = deepcopy(manifest)
    r = wf_manifest_check(manifest)
    assert reason in r["reasons"] and not r["certifiable"]
    assert manifest == before
    assert r["metrics"]["beta"] is r["metrics"]["information_ratio"] is None


def test_checks_only_own_range_but_requires_benchmark_alignment():
    manifest = _wf()
    manifest["series"]["IPO"] = manifest["series"]["SPY"][-2:]
    r = wf_manifest_check(manifest)
    assert r["ok"]
    assert r["metrics"]["series_checks"]["IPO"]["missing_dates"] == []


def test_calendar_itself_must_be_sorted_unique_and_present():
    for calendar in ([], ["2026-01-01", "2026-01-01"], ["not-a-date"]):
        manifest = _wf()
        manifest["calendar"] = calendar
        assert not wf_manifest_check(manifest)["ok"]
