"""The publisher's same byte comparator, now against the real D1/D2 DUT."""

import base64
import hashlib
import itertools
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from projection_test_helpers import ORACLE

COMPARATOR_SHA = "60ca21af7bd8f1f5fedb0c8856f8f049e348901332e2e3564c60e05dafd85fc7"
SUITE_SHA = "30acf166a6012c59636f5559d6b6412f4571e0a145c70ec2b78b246d4c1e08d4"


def comparator():
    raw = (ORACLE / "compare_bytes.source.txt").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == COMPARATOR_SHA
    namespace = {"__name__": "publisher_comparator"}
    exec(compile(raw, "publisher_compare_bytes.py", "exec"), namespace)
    return namespace["compare"]


def reverse_maps(value):
    if isinstance(value, dict):
        return {k: reverse_maps(v) for k, v in reversed(list(value.items()))}
    if isinstance(value, list):
        return [reverse_maps(v) for v in value]
    return value


@pytest.mark.parametrize(
    "hashseed,seed,clock,order",
    itertools.product(
        ("1", "2", "3", "4"),
        ("0", "7"),
        ("2000-01-01T00:00:00Z", "2030-01-01T00:00:00Z"),
        ("canonical", "reverse_objects"),
    ),
)
def test_D1_real_DUT_full_raw_matrix(hashseed, seed, clock, order, tmp_path):
    raw = (ORACLE / "CF01.input.canonical.json").read_bytes()
    if order == "reverse_objects":
        raw = json.dumps(
            reverse_maps(json.loads(raw)),
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode()
    profile = tmp_path / "dut.sb"
    profile.write_text(
        '(version 1)\n(allow default)\n(deny network*)\n(allow network-bind)\n(allow network-inbound (local ip "localhost:*"))\n(allow network-outbound (remote ip "localhost:*"))\n(allow network* (remote unix-socket) (local unix-socket))\n(deny file-read-data (subpath '
        + json.dumps(str(ORACLE.resolve()))
        + "))\n"
    )
    env = dict(os.environ, PYTHONHASHSEED=hashseed, PYTHONDONTWRITEBYTECODE="1")
    package_root = str(Path(__file__).resolve().parents[2])
    env["PYTHONPATH"] = os.pathsep.join(
        path for path in (package_root, env.get("PYTHONPATH")) if path
    )
    outer = os.environ.get("EVO884_MATRIX_EXTERNAL_OS_GUARD") == "1"
    layer = (
        "OS_file_sandbox" if outer else "python_audit_in_inherited_OS_network_sandbox"
    )
    command = (["/usr/bin/sandbox-exec", "-f", str(profile)] if outer else []) + [
        sys.executable,
        "-B",
        str(Path(__file__).with_name("projection_matrix_worker.py")),
        seed,
        clock,
        str(ORACLE / "CF01.expected.canonical.json"),
        layer,
    ]
    child = subprocess.run(command, input=raw, capture_output=True, env=env, timeout=30)
    (tmp_path / "worker.stdout").write_bytes(child.stdout)
    (tmp_path / "worker.stderr").write_bytes(child.stderr)
    assert child.returncode == 0, child.stderr.decode(errors="replace")
    receipt = json.loads(child.stdout)
    assert receipt["oracle_read_denied"] is True
    assert receipt["forbidden_attempts"] == []
    assert receipt["clock_interception_self_checks"] == 6
    assert receipt["reader_calls"] == 0 and receipt["product_worker_roles"] == []
    results = []
    for i, output in enumerate(receipt["outputs"]):
        output = base64.b64decode(output)
        (tmp_path / (str(i) + ".raw")).write_bytes(output)
        result = comparator()(ORACLE / "suite-manifest.json", SUITE_SHA, raw, output)
        assert result["pass_exact_bytes"] is True, result
        results.append(result)
    (tmp_path / "matrix-cell.json").write_text(
        json.dumps(
            dict(
                argv=command,
                returncode=child.returncode,
                python=sys.version,
                hashseed=hashseed,
                randomseed=seed,
                clock=clock,
                input_order=order,
                receipt=receipt,
                comparisons=results,
            ),
            sort_keys=True,
            indent=2,
        )
        + "\n"
    )


def test_D1_matrix_worker_imports_with_empty_pythonpath(monkeypatch, tmp_path):
    monkeypatch.setenv("PYTHONPATH", "")
    monkeypatch.setenv("PYTHONNOUSERSITE", "1")
    test_D1_real_DUT_full_raw_matrix(
        "1", "0", "2000-01-01T00:00:00Z", "canonical", tmp_path
    )
    cell = json.loads((tmp_path / "matrix-cell.json").read_bytes())
    assert cell["returncode"] == 0
    assert len(cell["comparisons"]) == 2
    assert all(result["pass_exact_bytes"] for result in cell["comparisons"])


@pytest.mark.parametrize(
    "mode",
    [
        "quantity",
        "priority",
        "reverse",
        "ticker",
        "nonce",
        "clock",
        "trace",
        "holdings_only",
        "single_order",
    ],
)
def test_D1_original_comparator_rejects_each_independent_bad_output(mode):
    raw = (ORACLE / "CF01.input.canonical.json").read_bytes()
    golden = json.loads((ORACLE / "CF01.expected.canonical.json").read_bytes())
    if mode == "quantity":
        golden["net_orders"][0]["quantity"] += 1
    elif mode == "priority":
        golden["net_orders"][0]["priority"] += 1
    elif mode == "reverse":
        golden["net_orders"].reverse()
    elif mode == "ticker":
        golden["net_orders"].sort(key=lambda o: o["symbol"])
    elif mode == "nonce":
        golden["nonce"] = 1
    elif mode == "clock":
        golden["clock"] = "2000-01-01T00:00:00Z"
    elif mode == "trace":
        golden["trace"].reverse()
    elif mode == "holdings_only":
        golden = {"P": golden["P"]}
    else:
        golden["net_orders"] = golden["net_orders"][:1]
    actual = json.dumps(
        golden,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode()
    result = comparator()(ORACLE / "suite-manifest.json", SUITE_SHA, raw, actual)
    assert result["pass_exact_bytes"] is False
    assert result["reason"] == "FULL_RAW_BYTES_MISMATCH"
