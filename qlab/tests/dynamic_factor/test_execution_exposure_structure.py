"""Fixed-main structural gate and explicitly bounded host-container differential."""

import ast
from copy import deepcopy
import hashlib
import inspect
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from qlab.dynamic_factor.conventions import load_conventions
from qlab.dynamic_factor.execution_cash import check_cash_state
from qlab.dynamic_factor.execution_exposure import verify_execution_exposure
from qlab.dynamic_factor.execution_state import necessary_execution_state_known
from qlab.dynamic_factor.state_v2 import necessary_state_known
from v3_test_helpers import synthetic_guard, synthetic_zero_state


FIXTURES = Path(__file__).parent / "fixtures/exposure-main-f827776"
MAIN_SHA = "08301f9d7a5ad5bdcd2fcaae8422dec9896e18b59d197a9c183e81057e106744"
MANIFEST_SHA = "8cd5639315f0a46a2f253fa6ea5be2ba9364276a11dc3a9448777ab0b4871ca5"
TRACE = []


def frozen_function():
    raw = (FIXTURES / "noncash_v3.py.fixture").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == MAIN_SHA
    fn = next(
        node
        for node in ast.parse(raw, type_comments=True).body
        if isinstance(node, ast.FunctionDef) and node.name == "zero_exposure"
    )
    assert ast.dump(fn.body[0], include_attributes=False) == ast.dump(
        ast.parse("necessary_state_known(state)").body[0], include_attributes=False
    )
    return fn


def body_nodes(fn):
    body = fn.body
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        body = body[1:]
    return body


def body_dump(body):
    return ast.dump(ast.Module(body=body, type_ignores=[]), include_attributes=False)


def function_dump(fn, *, original=False):
    """Normalize only the allowed exclusions; keep the complete node kind.

    Do not rebuild a FunctionDef: doing so would erase AsyncFunctionDef and
    future AST fields. Decorators, defaults, annotations and the full arguments
    object remain part of the same whole-node comparison.
    """
    fn = deepcopy(fn)
    fn.name = "B_segment"
    fn.body = body_nodes(fn)
    if original:
        # frozen_function already SHA-checks and verifies this exact first call.
        fn.body = fn.body[1:]
    return ast.dump(fn, include_attributes=False)


def assert_B_structure(current):
    assert function_dump(current) == function_dump(frozen_function(), original=True)


def reference(*, B_only=False):
    # Execute only the SHA-pinned trusted function, never product-generated data.
    fn = frozen_function()
    if B_only:
        fn.body = fn.body[1:]
    namespace = {"necessary_state_known": necessary_state_known}
    exec(
        compile(ast.Module(body=[fn], type_ignores=[]), "frozen-main-zero", "exec"),
        namespace,
    )
    return namespace["zero_exposure"]


def observe(call):
    try:
        call()
        return {"accepted": True, "exception_type": None, "reason": None}
    except Exception as exc:
        return {
            "accepted": False,
            "exception_type": type(exc).__name__,
            "reason": str(exc),
        }


def test_B_segment_structure_matches_SHA_pinned_main():
    current = ast.parse(
        inspect.getsource(verify_execution_exposure), type_comments=True
    ).body[0]
    assert_B_structure(current)


def structural_mutation(fn, kind):
    fn = deepcopy(fn)
    if kind == "async":
        return ast.AsyncFunctionDef(
            **{field: getattr(fn, field) for field in fn._fields}
        )
    if kind == "decorator_add":
        fn.decorator_list.append(ast.Name(id="SYNTHETIC_DECORATOR", ctx=ast.Load()))
    elif kind == "returns":
        fn.returns = ast.Name(id="SYNTHETIC_RETURN", ctx=ast.Load())
    elif kind == "default":
        fn.args.kw_defaults[0] = ast.Constant(True)
    elif kind == "parameter_add":
        fn.args.kwonlyargs.append(ast.arg(arg="SYNTHETIC_PARAMETER"))
        fn.args.kw_defaults.append(ast.Constant(None))
    elif kind == "parameter_delete":
        del fn.args.args[-1]
    else:
        raise ValueError(kind)
    return fn


@pytest.mark.parametrize(
    "mutation",
    [
        "async",
        "decorator_add",
        "returns",
        "default",
        "parameter_add",
        "parameter_delete",
    ],
)
def test_whole_function_gate_rejects_kind_decorators_annotations_and_arguments(
    mutation, record_property
):
    original = ast.parse(
        inspect.getsource(verify_execution_exposure), type_comments=True
    ).body[0]
    changed = structural_mutation(original, mutation)
    with pytest.raises(AssertionError):
        assert_B_structure(changed)
    record_property(
        "AST_KIND_actual",
        json.dumps(
            dict(
                mutation=mutation,
                rejected=True,
                expected_node=type(original).__name__,
                actual_node=type(changed).__name__,
            )
        ),
    )


def test_whole_function_dump_detects_decorator_deletion_symmetrically():
    # The pinned main has no decorators. This controlled pair tests deletion
    # from an equal decorated pair; it does not invent a main decorator.
    baseline = ast.parse(
        inspect.getsource(verify_execution_exposure), type_comments=True
    ).body[0]
    baseline.decorator_list = [ast.Name(id="SYNTHETIC_DECORATOR", ctx=ast.Load())]
    changed = deepcopy(baseline)
    assert function_dump(changed) == function_dump(baseline)
    changed.decorator_list.clear()
    assert function_dump(changed) != function_dump(baseline)


def test_whole_function_dump_keeps_only_permitted_exclusions():
    baseline = ast.parse(
        inspect.getsource(verify_execution_exposure), type_comments=True
    ).body[0]
    changed = deepcopy(baseline)
    changed.name = "SYNTHETIC_ALLOWED_NAME"
    changed.body.insert(0, ast.Expr(value=ast.Constant("SYNTHETIC ALLOWED DOCSTRING")))
    assert function_dump(changed) == function_dump(baseline)


@pytest.mark.parametrize("mutation", ["keys", "get", "order", "constant"])
def test_structure_gate_detects_operation_order_and_constant_drift(mutation):
    expected = frozen_function().body[1:]
    changed = deepcopy(expected)
    if mutation == "keys":
        call = next(
            n
            for s in changed
            for n in ast.walk(s)
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute)
            and n.func.attr == "issubset"
        )
        call.func.attr = "keys"
    elif mutation == "get":
        node = next(
            n
            for s in changed
            for n in ast.walk(s)
            if isinstance(n, ast.Subscript)
            and isinstance(n.value, ast.Name)
            and n.value.id == "state"
            and isinstance(n.slice, ast.Constant)
            and n.slice.value == "pending_orders"
        )
        node.value = ast.Call(
            func=ast.Attribute(
                value=ast.Name(id="state", ctx=ast.Load()), attr="get", ctx=ast.Load()
            ),
            args=[ast.Constant("pending_orders")],
            keywords=[],
        )
    elif mutation == "order":
        changed[-1], changed[-2] = changed[-2], changed[-1]
    else:
        node = next(
            n
            for s in changed
            for n in ast.walk(s)
            if isinstance(n, ast.Constant) and n.value == "B.pending_state_unknown"
        )
        node.value = "B.changed_refusal"
    assert body_dump(changed) != body_dump(expected)


class Inventory(dict):
    def __init__(self, original, mode, child, blocked):
        super().__init__(original)
        self.mode, self.child, self.blocked = mode, child, blocked

    def keys(self):
        TRACE.append("inventory.keys")
        if self.mode == "keys-fill":
            return set(dict.keys(self)) | {self.child}
        if self.mode == "keys-hide":
            return set(dict.keys(self)) - {self.child}
        return dict.keys(self)

    def __iter__(self):
        TRACE.append("inventory.iter")
        values = list(dict.__iter__(self))
        if self.mode == "iter-hide":
            values.remove(self.child)
        if self.mode == "iter-extra":
            values.append("SYNTHETIC_ITER_EXTRA")
        return iter(values)

    def items(self):
        TRACE.append("inventory.items")
        if self.mode == "items-held":
            return [(s, 1 if s == self.blocked else q) for s, q in dict.items(self)]
        return dict.items(self)


class Order(dict):
    def __init__(self, original, mode):
        super().__init__(original)
        self.mode = mode

    def keys(self):
        TRACE.append("order.keys")
        return set(dict.keys(self)) | {"VIRTUAL_EXTRA"}

    def __iter__(self):
        TRACE.append("order.iter")
        values = list(dict.__iter__(self))
        if self.mode == "iter-extra":
            values.append("VIRTUAL_EXTRA")
        if self.mode == "iter-hide":
            values.remove("quantity")
        return iter(values)

    def items(self):
        TRACE.append("order.items")
        return list(dict.items(self)) + [("VIRTUAL_EXTRA", 1)]


class State(dict):
    def __init__(self, original, mode):
        super().__init__(original)
        self.mode = mode

    def get(self, key, *default):
        TRACE.append("state.get:" + str(key))
        if self.mode == "get-pending" and key == "pending_orders":
            return None
        return dict.get(self, key, *default)

    def __contains__(self, key):
        TRACE.append("state.contains:" + str(key))
        if self.mode == "contains-pending" and key == "pending_orders":
            return False
        return dict.__contains__(self, key)


class Pending(list):
    def __iter__(self):
        TRACE.append("pending.iter")
        return reversed(list(list.__iter__(self)))


MODES = [
    "plain",
    "order-keys",
    "order-iter-extra",
    "order-iter-hide",
    "order-items",
    "inventory-keys-fill",
    "inventory-keys-hide",
    "inventory-iter-hide",
    "inventory-iter-extra",
    "inventory-items-held",
    "state-get-pending",
    "state-contains-pending",
    "pending-reversed",
]


def specimen(mode, held):
    policy = load_conventions()
    guard = synthetic_guard(policy, blocked=[policy.profile["universe"][0]])
    guard["unknown"] = ["SYNTHETIC_UNKNOWN"]
    state = synthetic_zero_state(guard)
    child, blocked = next(iter(guard["children"])), guard["B"][0]
    allowed = next(s for s in policy.profile["universe"] if s not in guard["B"])
    state["inventory"]["SYNTHETIC_UNKNOWN"] = 0
    for symbol in [blocked, "SYNTHETIC_UNKNOWN", child, "UNDECLARED"]:
        state["age"][symbol], state["origin"][symbol] = 1, "SYNTHETIC"
    if held != "none":
        symbol = {
            "B": blocked,
            "unknown": "SYNTHETIC_UNKNOWN",
            "child": child,
            "undeclared": "UNDECLARED",
        }[held]
        state["inventory"][symbol] = 1
    order = dict(symbol=allowed, side="BUY", quantity=1)
    state["pending_orders"] = [order]
    if mode.startswith("order-"):
        state["pending_orders"] = [Order(order, mode.removeprefix("order-"))]
    if mode.startswith("inventory-"):
        if mode == "inventory-keys-fill":
            state["inventory"].pop(child)
        state["inventory"] = Inventory(
            state["inventory"], mode.removeprefix("inventory-"), child, blocked
        )
    if mode.startswith("state-"):
        state = State(state, mode.removeprefix("state-"))
    if mode == "pending-reversed":
        state["pending_orders"] = Pending(
            [{}, dict(symbol=blocked, side="BUY", quantity=1)]
        )
    return state, guard


@pytest.mark.parametrize("initial", [False, True])
@pytest.mark.parametrize("held", ["none", "B", "unknown", "child", "undeclared"])
@pytest.mark.parametrize("mode", MODES)
def test_real_entry_and_B_segment_host_container_differential(
    mode, held, initial, record_property
):
    state, guard = specimen(mode, held)
    before = repr(state)
    old_prefix = observe(lambda: necessary_state_known(state))
    new_prefix = observe(lambda: necessary_execution_state_known(state))
    assert new_prefix == old_prefix
    TRACE.clear()
    old_B = observe(lambda: reference(B_only=True)(state, guard, initial=initial))
    old_trace = TRACE[:]
    TRACE.clear()
    new_B = observe(lambda: verify_execution_exposure(state, guard, initial=initial))
    assert new_B == old_B
    assert TRACE == old_trace
    expected = observe(lambda: reference()(state, guard, initial=initial))
    actual = observe(lambda: check_cash_state(state, guard, None, initial=initial))
    assert actual == expected, (mode, held, initial, expected, actual)
    assert repr(state) == before
    record_property(
        "host_container_differential",
        json.dumps(
            dict(
                mode=mode,
                held=held,
                initial=initial,
                prefix=old_prefix,
                B=old_B,
                B_operations=old_trace,
                actual_entry=actual,
                first_stop=actual["reason"],
                state_preserved=True,
            )
        ),
    )


@pytest.mark.parametrize(
    "name", ["container_counterexample.py", "independent_exposure.py"]
)
def test_original_review_counterexamples_and_296_observations(
    name, tmp_path, record_property
):
    manifest_raw = (FIXTURES / "manifest.json").read_bytes()
    assert hashlib.sha256(manifest_raw).hexdigest() == MANIFEST_SHA
    manifest = json.loads(manifest_raw)
    for filename, identity in manifest["files"].items():
        raw = (FIXTURES / filename).read_bytes()
        assert len(raw) == identity["bytes"]
        assert hashlib.sha256(raw).hexdigest() == identity["sha256"]
    script = tmp_path / name
    script.write_bytes((FIXTURES / (name + ".fixture")).read_bytes())
    repo = Path(__file__).resolve().parents[3]
    output = tmp_path / "output"
    command = [sys.executable, "-B", str(script), str(repo), str(output)]
    if name == "container_counterexample.py":
        command.append("--expect-legacy")
    env = dict(
        os.environ, PYTHONPATH="", PYTHONNOUSERSITE="1", PYTHONDONTWRITEBYTECODE="1"
    )
    run = subprocess.run(command, cwd=repo / "qlab", env=env, capture_output=True)
    assert run.returncode == 0, (run.stdout.decode(), run.stderr.decode())
    if name == "independent_exposure.py":
        summary = json.loads((output / "summary.json").read_bytes())
        assert summary["cases"] == 296 and summary["B_predicate_mismatches"] == 0
        original_summary = json.loads(
            (FIXTURES / "review-domain-summary.json").read_bytes()
        )
        assert (
            summary["numeric_validator_differences"]
            == original_summary["numeric_validator_differences"]
        )
        assert json.loads((output / "observations.json").read_bytes()) == json.loads(
            (FIXTURES / "review-296-observations.json").read_bytes()
        )
        assert (
            summary["outside_plain_JSON"]["old"] == summary["outside_plain_JSON"]["new"]
        )
    else:
        rows = json.loads((output / "observations.json").read_bytes())
        assert rows[0]["actual_check_cash_state"]["ok"]
        assert (
            rows[1]["actual_check_cash_state"]["reason"]
            == "B.complete_inventory_zero_evidence_required"
        )
    record_property(
        "original_review_script",
        json.dumps(
            dict(
                argv=command,
                exit_code=run.returncode,
                observations=json.loads((output / "observations.json").read_bytes()),
            )
        ),
    )
