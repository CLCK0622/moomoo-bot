from copy import deepcopy

import pytest

from qlab.dynamic_factor.conventions import load_conventions
from qlab.dynamic_factor.execution import calibrate_gain
from qlab.dynamic_factor.isolation import seal_manifest, score_day
from qlab.dynamic_factor.v1_harness import unit_context
from test_v2_isolation import synthetic_manifest


def calibration_inputs():
    p = load_conventions()
    context = unit_context(p)
    d = context["train_calendar"][50]
    request = synthetic_manifest(p, verified=64, date=d)
    sealed = seal_manifest(request, p)
    ids = p.document["variance_layers"]["family_definitions"]["candidate_members"]
    receipt = score_day(
        sealed,
        d,
        lambda names: {k: {s: float(i) for i, s in enumerate(names)} for k in ids},
        p,
    )
    context["isolation"] = dict(manifest=sealed, rank_receipts={d: receipt})
    names = receipt["day"]["eligible"]
    missing = set(range(0, 64, 5)) | {62}
    assert len(missing) == 14
    rows = [
        dict(
            date=d,
            symbol=s,
            label_entry=context["train_calendar"][51],
            label_end=context["train_calendar"][61],
            stock_h10=0.02 + i / 10000,
            qqq_h10=0.01,
            label_verified=i not in missing,
            ranks={k: receipt["ranks"][k][s] for k in ids},
        )
        for i, s in enumerate(names)
    ]
    return p, context, rows, {d}


def test_rank64_then_filter50_verified_mature_labels_without_reranking():
    p, c, rows, dates = calibration_inputs()
    before = deepcopy(c["isolation"])
    r = calibrate_gain(rows, dates, conventions=p, context=c)
    assert r["label_count_by_date"] == {next(iter(dates)): 50}
    assert c["isolation"] == before
    assert (
        c["isolation"]["rank_receipts"][next(iter(dates))]["day"]["verified_count"]
        == 64
    )
    assert all(len(v) == 10 for v in r["m"].values())


def test_future_label_availability_cannot_rerank_the_trading_cross_section():
    p, c, rows, dates = calibration_inputs()
    selected = [r for r in rows if r["label_verified"]]
    for i, row in enumerate(selected):
        row["ranks"] = dict.fromkeys(row["ranks"], (i + 0.5) / 50)
    with pytest.raises(ValueError, match="future_label_reranking"):
        calibrate_gain(rows, dates, conventions=p, context=c)


@pytest.mark.parametrize(
    "attack",
    [
        "missing_rank",
        "too_few_labels",
        "empty_bucket",
        "outside_train",
        "duplicate",
        "drop_date",
    ],
)
def test_missing_calibration_prerequisites_do_not_fill_zero_merge_or_skip(attack):
    p, c, rows, dates = calibration_inputs()
    if attack == "missing_rank":
        c.pop("isolation")
    elif attack == "too_few_labels":
        next(r for r in rows if r["label_verified"])["label_verified"] = False
    elif attack == "empty_bucket":
        for r in rows:
            r["label_verified"] = next(iter(r["ranks"].values())) <= 0.9
    elif attack == "outside_train":
        next(r for r in rows if r["label_verified"])["label_end"] = "2099-01-01"
    elif attack == "duplicate":
        rows.append(deepcopy(rows[0]))
    else:
        dates = set()
    reason = "calibration_bucket_missing" if attack == "empty_bucket" else "gain."
    with pytest.raises(ValueError, match=reason):
        calibrate_gain(rows, dates, conventions=p, context=c)
