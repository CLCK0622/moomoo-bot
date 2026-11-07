"""Original fixed protocol/source reads only; never an economic file reader."""

import hashlib
from datetime import datetime
import os
from pathlib import Path
import sys

from .replay_files import REPLAY_COMPILE_SOURCES
from ..execution_state import necessary_execution_state_known
from ..execution_exposure import verify_execution_exposure
from ..lineage_schema import EVENT
from ..event_quarantine import quarantine_check
from ..fee_model import order_cost


def install(expected_reads):
    # Finish these exact lazy core imports before the audit hook. No numerical
    # consumer or receipt parser is called by this preload.
    _ = (
        necessary_execution_state_known,
        verify_execution_exposure,
        EVENT,
        quarantine_check,
        order_cost,
    )
    datetime.strptime("2000-01-01", "%Y-%m-%d")  # load stdlib parser before hook
    source_root = str(Path(__file__).resolve().parents[1])
    paths = {}
    for filename, expected in expected_reads.items():
        path = Path(filename)
        if (
            path.is_symlink()
            or not path.is_file()
            or path.stat().st_nlink != 1
            or str(path.resolve()) != filename
        ):
            raise ValueError("reference.replay_protocol_path_mismatch")
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError("reference.replay_protocol_identity_mismatch")
        paths[filename] = expected
    reads = []
    compile_sources = {value.encode("utf-8") for value in REPLAY_COMPILE_SOURCES}

    def audit(event, args):
        if event == "compile" and args[1] == "<unknown>" and args[0] in compile_sources:
            return  # original conventions ast.parse only; exec remains forbidden
        if event == "os.scandir" and str(Path(args[0]).resolve()) == source_root:
            return  # contract.source_manifest(), exact file opens still checked
        if event == "open":
            path, mode, flags = args
            if (
                not isinstance(path, (str, bytes, os.PathLike))
                or str(Path(path).resolve()) not in paths
                or flags
                & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND)
            ):
                raise ValueError(
                    "reference.replay_input_or_write_forbidden:" + str(path)
                )
            name = str(Path(path).resolve())
            if name not in reads:
                reads.append(name)
        elif event.startswith(
            ("socket.", "subprocess.", "ctypes.", "os.exec", "os.spawn")
        ) or event in {
            "os.system",
            "os.fork",
            "os.chdir",
            "os.listdir",
            "os.scandir",
            "os.remove",
            "os.rename",
            "os.mkdir",
            "os.link",
            "os.symlink",
            "compile",
            "exec",
            "import",
        }:
            raise ValueError(
                "reference.replay_operation_forbidden:"
                + event
                + (":" + str(args[0]) if event == "import" else "")
            )

    sys.addaudithook(audit)
    return reads
