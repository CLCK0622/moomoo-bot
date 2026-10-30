# Vendored, verbatim

| file | upstream | version | sha256 |
|------|----------|---------|--------|
| `dump_bin.py` | `microsoft/qlib` `scripts/dump_bin.py` | tag `v0.9.7` | `b8f34c57ce1ef4b1772f3909735e66058f21b25bd7ab8a5f16318822401fe53f` |

Fetched from
`https://raw.githubusercontent.com/microsoft/qlib/v0.9.7/scripts/dump_bin.py`.

**Why vendored, not pip-run:** `dump_bin.py` ships only in the Qlib *source
tree*, never in the `pyqlib` wheel. Pinning the exact-tag copy here keeps the
CSV→`.bin` binary layout locked to the installed wheel version (`pyqlib==0.9.7`)
so the on-disk format can never silently drift under us.

**Do not edit.** It is byte-identical to upstream (verify with the sha256
above). All Qlib-facing glue lives in the sibling `build_qlib_data.py`, which
only *calls* this file's `DumpDataAll` class. To bump Qlib, re-fetch the script
at the new tag, update this table, and re-run the sha check.

Runtime deps (all already in the `qlab-py312` venv): `fire`, `loguru`, `tqdm`,
`pandas`, `numpy`, and `qlib.utils.{fname_to_code,code_to_fname}`.
