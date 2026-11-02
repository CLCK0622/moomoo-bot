"""Run the fixed peer regression with explicit full refs and real interpreters."""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys


FIXTURES = Path(__file__).parent / "fixtures/authority-stage1/f1-scope-v2"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--head", required=True)
    parser.add_argument("--python39", type=Path, required=True)
    parser.add_argument("--python312", type=Path, required=True)
    parser.add_argument("--deps39", type=Path, required=True)
    parser.add_argument("--deps312", type=Path, required=True)
    args = parser.parse_args()
    repo = args.repo.resolve()
    actual_head = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=repo, text=True
    ).strip()
    if len(args.head) != 40 or args.head != actual_head:
        raise ValueError("Explicit final full SHA must equal source HEAD")
    if subprocess.check_output(["git", "status", "--porcelain"], cwd=repo):
        raise ValueError("Source must be clean")
    for python, expected in (
        (args.python39, [3, 9, 6]),
        (args.python312, [3, 12, 13]),
    ):
        version = json.loads(
            subprocess.check_output(
                [
                    str(python.absolute()),
                    "-B",
                    "-c",
                    "import json,sys;print(json.dumps(list(sys.version_info[:3])))",
                ],
                text=True,
            )
        )
        if version != expected:
            raise ValueError("Interpreter does not match label: " + str(python))
    out = args.out.resolve()
    if repo == out or repo in out.parents:
        raise ValueError("Output must be outside the source checkout")
    scripts = out / "scripts"
    scripts.mkdir(parents=True, exist_ok=False)
    manifest = json.loads((FIXTURES / "manifest.json").read_bytes())
    for name, identity in manifest["files"].items():
        source = FIXTURES / (name + ".fixture" if name.endswith(".py") else name)
        raw = source.read_bytes()
        if (
            len(raw) != identity["bytes"]
            or hashlib.sha256(raw).hexdigest() != identity["sha256"]
        ):
            raise ValueError("Peer regression identity mismatch: " + name)
        (scripts / name).write_bytes(raw)
    command = [
        sys.executable,
        "-B",
        str(scripts / "run_factor_compat_comparison.py"),
        "--repo",
        str(repo),
        "--out",
        str(out / "results"),
        "--refs",
        "98cd60f9d93dba3e44bd23a76261eaa8c9516d88",
        "4cdfcbc0726abeadfff9e143b49281fab815bc43",
        args.head,
        "--python39",
        str(args.python39.absolute()),
        "--python312",
        str(args.python312.absolute()),
        "--deps39",
        str(args.deps39.resolve()),
        "--deps312",
        str(args.deps312.resolve()),
        "--assert-all",
    ]
    completed = subprocess.run(command, check=False)
    (out / "invocation.json").write_text(
        json.dumps(dict(argv=command, exit_code=completed.returncode), indent=2) + "\n"
    )
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
