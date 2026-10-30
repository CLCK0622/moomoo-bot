"""D ruling: complete synthetic N must never upgrade an omitted identity."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from qlab.dynamic_factor import arm_n, pipeline, statistics
from qlab.dynamic_factor.authority_ledger import AuthorityLedger
from qlab.dynamic_factor.contract import sha256
from qlab.dynamic_factor.ledger import AttemptLedger


class ConsumerSentinel(RuntimeError):
    pass


def complete_projection(tag):
    return dict(
        arm_tag=tag,
        cumulative_n=7,
        cumulative_n_lower_bound=7,
        n_complete=True,
        certifiable=True,
        reasons=[],
        n_ledger_hash="a" * 64,
        rows=[
            dict(role="PRIMARY_GATE", observed_N=7, complete_N=7),
            dict(role="SENSITIVITY", observed_N=11, complete_N=11),
        ],
    )


class ReadyLedger:
    """No file, writer or real authority capability exists on this synthetic object."""

    def __init__(self):
        self.formal_reads = []
        self.writes = []
        self.callbacks = []

    def safe_snapshot(self):
        return dict(
            genesis={},
            events=[],
            cumulative_n=7,
            cumulative_n_lower_bound=7,
            n_complete=True,
            certifiable=True,
            n_ledger_hash="a" * 64,
            reasons=[],
        )

    def arm_readout(self, tag):
        self.formal_reads.append(tag)
        arm = complete_projection(tag)
        return dict(
            metrics=dict(
                arm_n=arm,
                n_complete=True,
                N_rows=arm["rows"],
                cumulative_n=7,
                cumulative_n_lower_bound=7,
            ),
            artifacts=dict(ledger=self.safe_snapshot()),
            reasons=[],
        )

    def recorded(self, key):
        return None

    def record(self, *args, **kwargs):
        raise ConsumerSentinel("before_S0_write")

    def observe_self_report_n(self, *args):
        self.writes.append("self_report")
        raise AssertionError("self-report observer reached")


@pytest.fixture
def ready_consumers(monkeypatch):
    # Inject a truly complete projection; never use the real projector's fixed false.
    monkeypatch.setattr(
        arm_n, "project", lambda snapshot, tag: complete_projection(tag)
    )
    original_stats_result, original_arm_result = statistics.result, arm_n.result
    original_snapshot = statistics.arm_snapshot

    def stop_result(original):
        def wrapped(*args, **kwargs):
            if kwargs.get("metrics", {}).get("n_complete") is True:
                raise ConsumerSentinel("before_formal_readout_consumer")
            return original(*args, **kwargs)

        return wrapped

    def stop_snapshot(*args, **kwargs):
        value = original_snapshot(*args, **kwargs)
        if value["n_complete"]:
            raise ConsumerSentinel("before_N_consumer")
        return value

    monkeypatch.setattr(statistics, "result", stop_result(original_stats_result))
    monkeypatch.setattr(arm_n, "result", stop_result(original_arm_result))
    monkeypatch.setattr(statistics, "arm_snapshot", stop_snapshot)


def formal_call(entry, ledger, tag):
    request = {} if tag is arm_n.MISSING else {"arm_tag": tag}
    kwargs = {} if tag is arm_n.MISSING else {"arm_tag": tag}
    if entry == "dsr_eval_arm":
        return statistics.dsr_eval_arm(request, ledger)
    if entry == "evaluate_arm":
        return pipeline.evaluate_arm(request, ledger, None)
    if entry == "_n_snapshot":
        return pipeline._n_snapshot(ledger, 10**9, None, **kwargs)
    if entry == "AttemptLedger.arm_readout":
        return AttemptLedger.arm_readout(ledger, **kwargs)
    return AuthorityLedger.arm_readout(ledger, **kwargs)


FORMAL = [
    "dsr_eval_arm",
    "evaluate_arm",
    "_n_snapshot",
    "AttemptLedger.arm_readout",
    "AuthorityLedger.arm_readout",
]


@pytest.mark.parametrize("entry", FORMAL)
@pytest.mark.parametrize("tag", [arm_n.MISSING, None, "", "UNKNOWN", [], {}])
def test_formal_missing_and_invalid_identity_with_complete_N_has_no_consumer_or_write(
    ready_consumers, entry, tag
):
    ledger = ReadyLedger()
    value = formal_call(entry, ledger, tag)
    assert "arm_n.arm_tag_missing_or_invalid" in value["reasons"]
    assert not ledger.formal_reads and not ledger.writes and not ledger.callbacks
    metrics = value.get("metrics", value)
    assert metrics.get("cumulative_n") is None and metrics.get("gate_n") is None
    assert not metrics.get("n_complete")


@pytest.mark.parametrize("entry", FORMAL)
@pytest.mark.parametrize("tag", ["EVO883_FACTOR", "EVO896_LLMCLI"])
def test_same_formal_conditions_only_valid_label_reaches_consumer_sentinel(
    ready_consumers, entry, tag
):
    ledger = ReadyLedger()
    with pytest.raises(ConsumerSentinel):
        formal_call(entry, ledger, tag)
    assert not ledger.writes and not ledger.callbacks


@pytest.mark.parametrize("entry", ["dsr_eval", "pipeline.evaluate"])
def test_omission_is_permanent_diagnostic_with_complete_N_and_ready_consumer(
    ready_consumers, monkeypatch, entry
):
    ledger = ReadyLedger()
    original = statistics.dsr_eval_arm
    routed = []

    def formal_spy(*args, **kwargs):
        routed.append(True)
        return original(*args, **kwargs)

    monkeypatch.setattr(statistics, "dsr_eval_arm", formal_spy)
    call = (
        statistics.dsr_eval
        if entry == "dsr_eval"
        else lambda request, ledger: pipeline.evaluate(request, ledger, None)
    )
    value = call({}, ledger)
    assert not routed, "omitted identity entered formal dispatch"
    assert not ledger.formal_reads and not ledger.writes and not ledger.callbacks
    metrics = value["metrics"]
    assert (
        metrics["gate_N"]
        is metrics["cumulative_n"]
        is metrics["dsr"]
        is metrics["trials_variance"]
        is None
    )
    assert (
        metrics["factor_arm_N_complete"]
        is metrics["passed"]
        is value["certifiable"]
        is value["runtime_consumable"]
        is False
    )


@pytest.mark.parametrize("entry", ["dsr_eval", "pipeline.evaluate"])
@pytest.mark.parametrize("tag", ["EVO883_FACTOR", "EVO896_LLMCLI"])
def test_same_compat_conditions_only_valid_label_reaches_formal_sentinel(
    ready_consumers, entry, tag
):
    ledger = ReadyLedger()
    with pytest.raises(ConsumerSentinel):
        if entry == "dsr_eval":
            statistics.dsr_eval({"arm_tag": tag}, ledger)
        else:
            pipeline.evaluate({"arm_tag": tag}, ledger, None)
    assert not ledger.writes and not ledger.callbacks


@pytest.mark.parametrize("entry", ["dsr_eval", "pipeline.evaluate"])
@pytest.mark.parametrize("tag", [None, "", "UNKNOWN", [], {}])
def test_explicit_invalid_labels_never_enter_diagnostic_fallback(
    monkeypatch, entry, tag
):
    def forbidden(*args, **kwargs):
        raise AssertionError("diagnostic fallback reached")

    monkeypatch.setattr(statistics, "_diagnostic_dsr", forbidden)
    ledger = ReadyLedger()
    request = {"arm_tag": tag}
    value = (
        statistics.dsr_eval(request, ledger)
        if entry == "dsr_eval"
        else pipeline.evaluate(request, ledger, None)
    )
    assert "arm_n.arm_tag_missing_or_invalid" in value["reasons"]
    assert not ledger.formal_reads and not ledger.writes


@pytest.mark.parametrize("entry", ["dsr_eval", "pipeline.evaluate"])
def test_conflicting_explicit_and_embedded_labels_never_fall_back(monkeypatch, entry):
    monkeypatch.setattr(
        statistics,
        "_diagnostic_dsr",
        lambda *a, **kw: (_ for _ in ()).throw(AssertionError("fallback")),
    )
    kwargs = dict(arm_tag="EVO896_LLMCLI")
    ledger = ReadyLedger()
    if entry == "dsr_eval":
        report = statistics.dsr_eval({"arm_tag": "EVO883_FACTOR"}, ledger, **kwargs)
    else:
        report = pipeline.evaluate({"arm_tag": "EVO883_FACTOR"}, ledger, None, **kwargs)
    assert report["reasons"] == ["arm_n.request_arm_tag_conflict"]
    assert not ledger.formal_reads and not ledger.writes


def train(ledger, context, policy):
    return pipeline.run_train_pipeline(
        policy=policy,
        ledger=ledger,
        run_id="SYNTHETIC",
        context=context,
        registry=None,
        proposals=[],
        self_report_n=10**9,
        probe=lambda *a: ledger.callbacks.append("probe"),
        calibrate=lambda *a: ledger.callbacks.append("calibrate"),
        build_meta=lambda *a: ledger.callbacks.append("meta"),
    )


@pytest.fixture
def ready_training(monkeypatch):
    def complete(*a, **kw):
        return complete_projection(kw.get("arm_tag"))

    monkeypatch.setattr(pipeline, "_n_snapshot", complete)
    return SimpleNamespace(
        document=dict(
            runtime_consumable=True,
            variance_layers=dict(
                family_definitions=dict(candidate_members=[], meta_members=["meta"])
            ),
        ),
        binding={},
    )


@pytest.mark.parametrize("tag", [arm_n.MISSING, None, "", "UNKNOWN", [], {}])
def test_ready_training_label_guard_precedes_S0_observer_and_all_callbacks(
    ready_training, tag
):
    ledger = ReadyLedger()
    context = {"fold_id": "synthetic"}
    if tag is not arm_n.MISSING:
        context["arm_tag"] = tag
    value = train(ledger, context, ready_training)
    assert value["reason"] == "arm_n.arm_tag_missing_or_invalid"
    assert not ledger.writes and not ledger.callbacks and not ledger.formal_reads


@pytest.mark.parametrize("tag", ["EVO883_FACTOR", "EVO896_LLMCLI"])
def test_same_ready_training_only_valid_label_reaches_before_S0_sentinel(
    ready_training, tag
):
    ledger = ReadyLedger()
    with pytest.raises(ConsumerSentinel, match="before_S0_write"):
        train(ledger, {"fold_id": "synthetic", "arm_tag": tag}, ready_training)
    assert not ledger.writes and not ledger.callbacks


def test_incomplete_arm_history_precedes_S0_even_for_valid_identity(
    monkeypatch, ready_training
):
    monkeypatch.setattr(
        pipeline, "_n_snapshot", lambda *a, **kw: dict(n_complete=False)
    )
    ledger = ReadyLedger()
    value = train(
        ledger, {"fold_id": "synthetic", "arm_tag": "EVO883_FACTOR"}, ready_training
    )
    assert value["reason"] == "ledger.factor_arm_projection_missing"
    assert not ledger.writes and not ledger.callbacks


def test_frozen_pending_omission_but_explicit_null_refuses_without_writes():
    policy = SimpleNamespace(document=dict(runtime_consumable=False))
    ledger = ReadyLedger()
    assert train(ledger, {}, policy)["reason"] == "dsr.runtime_bindings_pending"
    assert (
        train(ledger, {"arm_tag": None}, policy)["reason"]
        == "arm_n.arm_tag_missing_or_invalid"
    )
    assert not ledger.writes and not ledger.formal_reads and not ledger.callbacks


def test_third_positional_argument_stays_policy_not_arm_tag():
    import inspect

    assert list(inspect.signature(pipeline._n_snapshot).parameters)[2] == "policy"
    ledger = ReadyLedger()
    with pytest.raises(ValueError, match="dsr.policy_invalid"):
        pipeline._n_snapshot(ledger, 99, "EVO883_FACTOR")
    assert not ledger.formal_reads and not ledger.writes


def test_final_D_ruling_raw_bytes_remain_bound():
    p = (
        Path(__file__).parents[2]
        / "qlab/llm_direct/rulings/EVO897-armtag-supplement-v1.0.0.json"
    )
    assert sha256(p.read_bytes()) == arm_n.RULING_SHA256
