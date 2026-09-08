"""The runtime replay CLI exposes no loose-bars input and prints stable provenance."""
from __future__ import annotations

import json

from tools import run_llm_paper_runtime_replay as cli


def test_cli_reports_hashes_and_authorization_state(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "_resolve_out_dir", lambda _value: tmp_path)
    monkeypatch.setattr(cli, "replay_runtime_equivalence", lambda *_args, **_kwargs: {
        "artifact_file": "RUNTIME.json",
        "content_sha256": "content",
        "file_sha256": "file",
        "input_manifest_sha256": "manifest",
        "shared_bar_snapshot_content_sha256": "snapshot",
        "implementation_source_sha256": "implementation",
        "runtime_source_bundle_sha256": "bundle",
        "payload": {"conclusions": {
            "executor_behavior_equivalence": "established_for_single_overlapping_cell",
            "may_take_over": True,
            "switch_authorized": False,
        }},
    })

    assert cli.main(["--out-dir", "reports"]) == 0
    assert json.loads(capsys.readouterr().out) == {
        "artifact_file": "RUNTIME.json",
        "content_sha256": "content",
        "file_sha256": "file",
        "input_manifest_sha256": "manifest",
        "shared_bar_snapshot_content_sha256": "snapshot",
        "implementation_source_sha256": "implementation",
        "runtime_source_bundle_sha256": "bundle",
        "executor_behavior_equivalence": "established_for_single_overlapping_cell",
        "may_take_over": True,
        "switch_authorized": False,
    }
