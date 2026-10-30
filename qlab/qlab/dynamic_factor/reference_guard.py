"""Audit capability for the pinned subprocess; installed before data reads.

Trusted reviewed source only. Python audit hooks are not a sandbox for arbitrary
native extensions or a hostile operator rewriting code and sealed inputs.
"""

import os
import sys
from pathlib import Path


def install(root):
    root = Path(root).resolve()
    paths = {
        str(root / (role + ".json")): role for role in ("panel", "benchmark", "profile")
    }
    reads = []

    def audit(event, args):
        if event == "open":
            path, mode, flags = args
            if (
                not isinstance(path, (str, bytes, os.PathLike))
                or str(Path(path).resolve()) not in paths
                or flags
                & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND)
            ):
                raise ValueError("reference.access_boundary_read_or_write_forbidden")
            reads.append(paths[str(Path(path).resolve())])
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
            raise ValueError("reference.access_boundary_operation_forbidden")

    sys.addaudithook(audit)
    return reads
