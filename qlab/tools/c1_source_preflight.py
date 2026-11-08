"""Controlled C1 source preflight; independent review binds this artifact."""

import sys

_EVENTS = []
_VERIFIED = False
_PHASE = "startup"
_ALLOWED_IMPORTS = set()


def _audit(event, args):
    if event == "import":
        name = args[0]
        _EVENTS.append(
            dict(sequence=len(_EVENTS), event=event, module=name, phase=_PHASE)
        )
        if name == "qlab" or name.startswith("qlab."):
            if not _VERIFIED or name not in _ALLOWED_IMPORTS:
                raise RuntimeError("scope.preflight_import_not_registered")
    elif event == "open" and isinstance(args[0], str):
        _EVENTS.append(
            dict(sequence=len(_EVENTS), event=event, path=args[0], phase=_PHASE)
        )


sys.addaudithook(_audit)
if any(name == "qlab" or name.startswith("qlab.") for name in sys.modules):
    raise SystemExit("scope.preflight_candidate_already_loaded")
if not (sys.flags.isolated and sys.flags.no_site and sys.flags.dont_write_bytecode):
    raise SystemExit("scope.preflight_isolation_required")

import hashlib  # noqa: E402 - isolation and audit checks precede other imports
import json  # noqa: E402
import os  # noqa: E402
import stat  # noqa: E402
import tempfile  # noqa: E402


AUDITOR_SHA256 = "585437899399c91ca4f93e9cbc0d0091bdab0cbfac565bff60863012ddcb9a50"
PINNED_SOURCES = {
    "../__init__.py": "304235cd17e4b3b6c3a0a921695d864d74e48cb1f7c5920b73af466ed07a72c2",
    "__init__.py": "06af6993da8dcb49ff75936b7b5e327424b753802687d92dda74033c15efd797",
    "catalog_members.py": "a4afc328161064689e24c85dfa1e3d946fd1c4fc7563701fd90e08864e82a82b",
    "catalog_v21.py": "12c3b0d33dcee4518ba39905d49f06fa55b62865f4ec041a5e0cf7f4a4189ab4",
    "continuity.py": "ee759682cd58c80195d5acf5e51ca2705f897f4144cd8c8eb99fb0ea5f658f95",
    "contract.py": "ff198c8d9ad05e7f2664af8120a9f6e3d21a242e3ef19e9f0b5cbb65a5beacbb",
    "conventions.py": "4b98838d3fca24664470c1e2fb65921eefc3d93a7bfb9331e857d65f0205064a",
    "event_quarantine.py": "1245c801165b5da94178585932634f6745dc05f2490c64ebbf96b0c4bd32c2c6",
    "execution.py": "d15958dabe5c67d2e47033a62253a2fd19fd6667cf15ca5dac8b3b49c91d9cd8",
    "execution_accounting.py": "f8101633e86d2ee42e75dd66793ae0e153f1454e38ce008cc10bd2d6611a5a4a",
    "execution_amounts.py": "18b2cdf6edaa43c7fd489e63eb8bdac8e209f5a06b317ff2aa1d3f306a4e245d",
    "execution_candidate.py": "90d1a9dcbe46b9881450d1770003212e1daea0b14f3d8e15d90e5f4b1563d16e",
    "execution_cash.py": "a49653574a53ccab01552e18cdecf9f6d41481a7d63c49175904683651150348",
    "execution_clock.py": "c1f9563c645110335cdbf006328b3cee4d1d8952d8433ffd5306b91d07e8ecf6",
    "execution_closure.py": "998ef21c68825ab9254489f29b12095c8dc0d4b3f6f14e507e8fbea6808615ae",
    "execution_exposure.py": "8af9951b19fb454637440f98d74b4a4567cc4b8f8aebefbee647b18e1a4dbaed",
    "execution_numbers.py": "b31df6da61dbde3a864164e31bd8590debf2941040e301f8511914ccd4933aa2",
    "execution_projection.py": "d7a30669a8cfc019318c35e648ea3cd9bea7129e57b12bcd93da0751afa8f5cc",
    "execution_receipts/input_data.py": "d0e86374390f6dab660e2c68eb25390f714120c184abd085fbad781ca6acec68",
    "execution_receipts/input_guard.py": "8c49c72ad42886285270c3ef99f2051c6c0c656927e348eac56a6211ad6507b7",
    "execution_receipts/input_reader.py": "ca5e3fc1c1a336428b784904d5fa85f880f78c39c500718ff6a4909b5f0bb30a",
    "execution_returns.py": "75d09e78605c6951cbaec3c914e7fdfc8090f646ddbd74078d8ceb4a0ec5f83c",
    "execution_risk.py": "b1b616126da4b831dba193f338ca9654c9de148bf1dc0b74d9723448faea8ab3",
    "execution_risk_history.py": "da55c683a2b281b1ece42850e0c4d49dbe81a921bfbb17c0a013a10330ba84d4",
    "execution_signals.py": "226c83a62f887ebf7720452c8ae045bceb699ab6cf7774446a5c72d28db5c0cb",
    "execution_startup.py": "4b675f45605e69869bab8135b77e1b82cca7d4a5a309f1549fc38ea10f0f1c72",
    "execution_state.py": "8e8129e63d084552ce308d84737d1b2851413e438ead3c247cfc3e69e32b4cf4",
    "fees.py": "144ee2bb1b9ca8bd24e480afcd0968e0fa711444ca520c6c6a72d8cf6d628e9a",
    "fold_split.py": "400c417527ca0ed4e04e2c4e4c76fd84c0ae2faf54bf0788f9fca29e7e1c95af",
    "folds.py": "d6f052976cc2bafacf3b7814a1fdf801e71c471ca4aca3b2813471e0666ccb02",
    "historical_authority.py": "fb401e78c115876d73f9f5a6cece6d7d820927c9cd1222dad49eca983629fcce",
    "input_disposition.py": "515945c2ee3de0d8e9a1ec0087f8087b5750258d013ada6ed08060f50e872d65",
    "input_scope.py": "3449f22061560251e19a21268da4c0cee911edc0864e19e08f1cf05b89a91bbe",
    "isolation.py": "910cccfd6fa0fa74405a393cba180ec5a65bceac99d5543722b68e87a7ec20a1",
    "k5.py": "96be5e8a8de9176b3cd24c766f08a4dc24a7d5db158a4bab2c0a468618d8bf97",
    "noncash_v3.py": "ce439592adc936c8715e7515dfb7f6dc8261847a15a737eadf281329cff47ccd",
    "pending.py": "3a1625313ea1d5491a8d0670a6698176ed80bdd98e7efd37a1447b2878349c06",
    "pipeline.py": "a7f4c35d0bb0c70507283fe525869d13b2d7cce6e6a53a5e2da6632e05cf8ffd",
    "reference_check.py": "27c4085c2acc18693d074e70d43961e0620110c37e606b65f46d8a683d11fa98",
    "reference_definition_v301.py": "95a51f2f5c5d3473254e247ac8d1b408c4f89c9253b3622ee2fe4d7941ef1a55",
    "reference_guard.py": "0e0d55ff4632856c59e2627b9da54a621fbd0c64804d6070742c536686e08fd3",
    "reference_inputs.py": "0b9ce35ecdb6806f3469b8ce3e662c659743a6192fc0a80aba28038abb233099",
    "reference_producer.py": "9b354f6d2288d76f515ed16d95f1003469d9c9e7bf92d6af9ff596d38ea6e81c",
    "reference_producer_v3.py": "a7fcff5592195a86923aaf667660ce988323c4bce1a0070432fcbdb65a560e26",
    "reference_profile_v301.py": "184f15302f003356a9d41027ab5fd84fa5917e796f96adee5374a714edc3ccd3",
    "reference_registry_v3.py": "90ff033cb06bbedce4315ec04bb7c84b8a300fdd133015db58a23b1f7fee997a",
    "reference_v3_scope.py": "131eaf7725102c1b86a51146c60f3019faa79bd1f73e0aa585ac3e743590244a",
    "reference_validation.py": "77854b5e4671bf3634bf22e7f49602c90ab47f87e19d394d688e12c6ec078019",
    "scope_reader.py": "3bbb0be2fa7b80e63e2879e947d0268b0f3c93c667ca8815b660afac7dc41f38",
    "state_v2.py": "0c31a71defe68d23126ada28b15dbd3b6574b661508d53f0d1697a9ed1492e2c",
    "validation.py": "5d3d6d97ab350c14bf9e5d62f51b2d42244f4466f9ed7636d7eb77d7c4a2be8d",
    "valuation.py": "4b0a18ebb18b2706926e344a94fd5da32b0f06b969a34d9da294e91ffffb8a8d",
}
PINNED_DATA = {
    "b_release_originals/EVO883-B-RUNTIME-RELEASE-P1-adopted-protocol-v1.0.0.json": "ff5da6ef748d5f1fca592559e73656d5283e28ec9d279b65b3ac0fd5943069ff",
    "b_release_originals/EVO883-EVO893-v10-ruling.json": "834bf9546dda93c3fb613833b59ac87842c2825b71c11bc09edc13608f5d42e4",
    "b_release_originals/EVO883-S1-BRKB-field-receipt.json": "ff8dee166c469310b915f903a32164351647e61dd8340437ffa09b45da9e0442",
    "b_release_originals/EVO883-S2-v14-field-receipt.json": "9b5fd1e87a2cae26df8a0c1a8ee9fbd880c07234e05a9253ff9886d4dcb7711f",
    "b_release_originals/EVO883-S3-v12-final-receipt.json": "1df425a328539f4cddfe3d574feabc1b753fc0abe2ff15d318634aee7dff3836",
    "b_release_originals/EVO883-S4-v11-receipt.json": "d44ce4e0b13d68a129f6aca0ad2187f459ea978f117510cc48d910fb8b44b11f",
    "b_release_originals/EVO883-v10-engineering-scope-receipt.json": "4da26596777a62595664ba9b9e17480113f96ccbd2c1d0226df083ac2e7ecc0f",
    "b_release_originals/EVO883-v20.1-final-receipt.json": "cdd7954a20102e1053f932fe559153b26336475afdb41b772004795708bf3c4e",
    "b_release_originals/EVO883-v21-final-receipt.json": "b8b930396e7caf42ad8bde0f2f7ff190c40f36fd4c4686964a39154926f6644a",
    "b_release_originals/EVO893-B-CMI-guard-v21.json": "08ed088405cbefa9bd24e8cb0756d5d10a62b105153b9cfba02af504d9371f77",
    "b_release_originals/EVO893-B-noncash-catalog-v21.csv": "5040272302cf675b99e0b954669dde72bfc6431f47fb9d835f3acb6f408d1a13",
    "b_release_originals/EVO938-B-runtime-release-P-v1.0.0.json": "4a4b24b0a6ee2b6b561d285fa6f3f9233960959500b6e02fc137c83ca31deae1",
    "b_release_originals/EVO938-B-runtime-release-R-v1.0.0.json": "68f06b15ded4cb1ec5219a5456a2e0f0f376cab54a9e3ac33aee653dacfa877c",
    "b_release_originals/annotation-platform-readback.json": "d25ba025d42fea6ad908566384f97f6fd1ed567eb1f4474bba46105e9aa77c81",
    "b_release_originals/publication-platform-readback.json": "f847be9a107b9293e134bfc4d9a03a3c3cb1eeb823f40991d7b8d28d1533455e",
    "fixtures/calendar-folds-v0.1.json": "d82a4c950c0f5f1ea813585e1496345c173fa8ae9805d65066f49b9132e92b74",
    "fixtures/catalog-v21/EVO883-v21-final-receipt.json": "b8b930396e7caf42ad8bde0f2f7ff190c40f36fd4c4686964a39154926f6644a",
    "fixtures/catalog-v21/EVO893-B-CMI-guard-v21.json": "08ed088405cbefa9bd24e8cb0756d5d10a62b105153b9cfba02af504d9371f77",
    "fixtures/catalog-v21/EVO893-B-noncash-catalog-v21.csv": "5040272302cf675b99e0b954669dde72bfc6431f47fb9d835f3acb6f408d1a13",
    "fixtures/common-calendar-v0.1.txt": "de08ca8969b91dac6f443f07922b8a65cd263dc8c4cc29847bfd979c9412a0fb",
    "fixtures/common-profile-v3.json": "0fdf644c4c78524cf8a1b91e7f8a6e8275cb568662c1e6aafb2a75b4c8fdf464",
    "fixtures/conventions-v0.1.json": "2e65c77849b936d44c864b056be134e030ddf7f27e746072b70fffe631acf69b",
    "fixtures/conventions-v3.0.0.json": "dd13affd23d77b3715a64ffe0403503ea3e6f5850bffdfb7f33bc6f4b44d9e0b",
    "fixtures/disposition/EVO883-EVO886-minimum-scope-ruling-v1.json": "730931cdd7b9c2f62db9841438235e0aa4887f27ef4a842844d63b6570fd7ede",
    "fixtures/disposition/EVO883-EVO886-minimum-scope-ruling-v1.md": "56d97ab77b8389abcd8fcc7c9df2d7094cfc38b3da39954f3b92439d061b05da",
    "fixtures/disposition/EVO883-EVO891-disposition-draft-v1.json": "75685ab429e05a74fb5f1c9187c5da144b98b6932795569516f9137f8f608f87",
    "fixtures/disposition/EVO883-EVO891-ruling-v1.md": "641c03afea7ff86bfab99d5392e3185606e1241669f110a315fa8379b5e7684c",
    "fixtures/disposition/QQQ-source-row-bindings-v1.json": "71953b090c92ca6fc02cb1a2a5e493a02b991ff35e43e3bf4c07136da8441260",
    "fixtures/evo892-v3/candidate_reference_manifest.json": "bcce6f17f3515d66eb5b87569720740efb6eb70eca2d774a853be8e3cdecb4a4",
    "fixtures/evo892-v3/meta_reference_manifest.json": "964e9903e13bd618777f00652bad09272d7aa4ddbb3cec2c28371a8378002ae6",
    "fixtures/evo892-v3/predeclared_reference_registry.json": "f531d65a5ad54fc68a8be40bc25cbb3987d0aeedd4c2c345ed334b1599445c48",
    "fixtures/execution-v3.0.1/EVO883-C06-CLOCK-adopted-protocol-v1.0.0.json": "8cd32345adb5ebe16cb9020687091532c46f803f046d6c1527eeedee41407a5a",
    "fixtures/execution-v3.0.1/EVO883-D12-addendum-v3.0.1.md": "f540dce44e00b7077a94d3155f55db5fdba700b7a48911ec03697724b8dfa8c9",
    "fixtures/execution-v3.0.1/EVO883-D12-common-profile-v3.0.1.json": "07b71b3fc59dc6dae1c96cadd3155622a18f4c4ad29b7c69b8f79c1455efc2d3",
    "fixtures/execution-v3.0.1/EVO883-D12-shared-execution-contract-v3.0.1.json": "f7a0623da88a7e2874ef5e372750ad04a1edca9796acc0c3fee02616f766a496",
    "fixtures/execution-v3.0.1/EVO883-EXEC-CLOSURE-adopted-protocol-v0.1.0.json": "7677b123fa2fe573343fad3fe3f43887c5f5d2c0fd7c12d9a1de8bc625162e1b",
    "fixtures/execution-v3.0.1/EVO883-EXEC-CLOSURE-adopted-protocol-v0.1.0.md": "34f25ce19dcf8687f7068b62f751c83573a858997ab11fa0096794157f3a373f",
    "fixtures/fee_params_x1.json": "7e24f9e9b25802a7d4b50bd4b089a60d288b8f8f448ea92aac9482816b7ffdb2",
    "fixtures/historical-seed-e51f8023.jsonl": "76ece03d62628a2ca2f0cb089103deaa26584ae9522fdde101df782a738a8f0b",
    "fixtures/noncash-exposure-policy-v3.json": "7230a447be8446edbca2e1c1001dfd4748e81b8d99e7d7dbda3e67c16ef790e8",
    "fixtures/prereg-v3.json": "53e570f7d7c912a078606d167f039d65c56ed0f9f5dadcb7e2ae1091bd949421",
    "fixtures/provenance-v2.json": "02b1d075b5a25acdbc3e82c594efed3778eca2710bdcb539c1df4f5b9c7bff30",
    "fixtures/provenance-v3.json": "c40a43af7ff6f1638e1a25df17a7bd19f81287f71c5e1f6a9ae0a0489c0e406d",
    "fixtures/provenance.json": "5a0bf6403b061dc27b0096c2dc72cc3e5ca0b554fa86ddbdac0ba58a08d9d111",
}
POLICY_FILES = {
    "raw_document": "fixtures/conventions-v3.0.0.json",
    "raw_profile": "fixtures/prereg-v3.json",
    "raw_date_manifest": "fixtures/calendar-folds-v0.1.json",
    "seed_raw": "fixtures/historical-seed-e51f8023.jsonl",
}

_HASH = hashlib.sha256
_DUMPS = json.dumps
_LOADS = json.loads
_OPEN = os.open
_READ = os.read
_FSTAT = os.fstat
_CLOSE = os.close
_STORE = {}
_ENTRY = os.path.realpath(__file__)
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(_ENTRY)))
_DF = os.path.join(_ROOT, "qlab", "qlab", "dynamic_factor")


class _Refusal(Exception):
    pass


def _digest(value):
    return _HASH(
        _DUMPS(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _path(relative):
    path = os.path.normpath(os.path.join(_DF, relative))
    if os.path.commonpath((_ROOT, path)) != _ROOT:
        raise _Refusal("scope.preflight_path_not_registered")
    return path


def _read_file(path):
    fd = _OPEN(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = _FSTAT(fd)
        if not stat.S_ISREG(before.st_mode):
            raise _Refusal("scope.preflight_regular_file_required")
        chunks = []
        while True:
            chunk = _READ(fd, 65536)
            if not chunk:
                break
            chunks.append(chunk)
        raw = b"".join(chunks)
        after = _FSTAT(fd)
        if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
        ) or len(raw) != before.st_size:
            raise _Refusal("scope.preflight_file_changed")
        return raw, dict(
            path=path,
            bytes=len(raw),
            st_dev=before.st_dev,
            st_ino=before.st_ino,
            st_mtime_ns=before.st_mtime_ns,
            observed_sha256=_HASH(raw).hexdigest(),
        )
    finally:
        _CLOSE(fd)


class _Snapshot:
    __slots__ = ()

    def validate(self):
        if type(self) is not _Snapshot or self not in _STORE:
            raise ValueError("scope.preflight_evidence_required")
        data = _STORE[self]
        actual = {
            name: dict(sha256=_HASH(raw).hexdigest(), bytes=len(raw))
            for name, raw in data["raw"].items()
        }
        if _digest(actual) != data["anchor"]:
            raise ValueError("scope.preflight_snapshot_mismatch")
        for name, row in actual.items():
            if (
                row["sha256"] != data["metadata"][name]["observed_sha256"]
                or row["bytes"] != data["metadata"][name]["bytes"]
            ):
                raise ValueError("scope.preflight_snapshot_mismatch")
        return True

    def raw(self, relative):
        try:
            return _STORE[self]["raw"][_path(relative)]
        except (KeyError, TypeError) as exc:
            raise ValueError("scope.preflight_snapshot_missing") from exc

    def identity(self, relative):
        try:
            return _STORE[self]["metadata"][_path(relative)]["observed_sha256"]
        except (KeyError, TypeError) as exc:
            raise ValueError("scope.preflight_snapshot_missing") from exc

    def entry_source(self):
        return _STORE[self]["raw"][_ENTRY]

    def entry_path(self):
        return _ENTRY

    def path(self, relative):
        return _path(relative)

    def digest(self, value):
        return _digest(value)

    def bind_policy(self, policy):
        for field, relative in POLICY_FILES.items():
            if getattr(policy, field) != self.raw(relative):
                raise ValueError("scope.preflight_policy_mismatch")
        document = _LOADS(self.raw(POLICY_FILES["raw_document"]))
        profile = _LOADS(self.raw(POLICY_FILES["raw_profile"]))
        _STORE[self]["profile"] = profile
        _STORE[self]["binding"] = dict(
            conventions_version=document["version"],
            conventions_sha256=self.identity(POLICY_FILES["raw_document"]),
            conventions_status=document["status"],
            profile_sha256=self.identity(POLICY_FILES["raw_profile"]),
            prereg_sha256=self.identity(POLICY_FILES["raw_profile"]),
            prereg_version=profile["version"],
            common_profile_sha256=document["variance_layers"]["probe_profile"][
                "common_profile_sha256"
            ],
        )

    def policy_binding(self):
        return dict(_STORE[self]["binding"])

    def policy_profile(self):
        return _LOADS(_DUMPS(_STORE[self]["profile"]))

    def bind_loaded(self):
        self.validate()
        rows = []
        data = _STORE[self]
        imported = {
            e["module"]
            for e in _EVENTS
            if e["event"] == "import"
            and (e["module"] == "qlab" or e["module"].startswith("qlab."))
        }
        for name, module in sorted(sys.modules.items()):
            if name != "qlab" and not name.startswith("qlab."):
                continue
            if name not in imported:
                raise ValueError("scope.preflight_import_event_missing")
            spec = module.__spec__
            if spec is None or spec.origin is None:
                raise ValueError("scope.preflight_loading_mismatch")
            path = os.path.normpath(os.path.abspath(spec.origin))
            if path not in data["metadata"]:
                raise ValueError("scope.preflight_loading_mismatch")
            before = data["metadata"][path]
            fd = _OPEN(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            try:
                current = _FSTAT(fd)
            finally:
                _CLOSE(fd)
            if not stat.S_ISREG(current.st_mode) or (
                current.st_dev,
                current.st_ino,
                current.st_size,
                current.st_mtime_ns,
            ) != (
                before["st_dev"],
                before["st_ino"],
                before["bytes"],
                before["st_mtime_ns"],
            ):
                raise ValueError("scope.preflight_loading_mismatch")
            relative = os.path.relpath(path, _DF)
            kind = (
                "auditor_raw_SHA"
                if relative == "scope_proof.py"
                else "receiver_full_AST"
                if relative == "b_release_context.py"
                else "fixed_raw_SHA"
            )
            if kind == "fixed_raw_SHA" and relative not in PINNED_SOURCES:
                raise ValueError("scope.preflight_import_not_registered")
            rows.append(
                dict(
                    module=name,
                    path=path,
                    observed_sha256=before["observed_sha256"],
                    expected_sha256=AUDITOR_SHA256
                    if kind == "auditor_raw_SHA"
                    else PINNED_SOURCES.get(relative),
                    binding=kind,
                    st_dev=current.st_dev,
                    st_ino=current.st_ino,
                    bytes=current.st_size,
                )
            )
        return rows


def _collect():
    sources = dict(PINNED_SOURCES, **{"scope_proof.py": AUDITOR_SHA256})
    expected = dict(sources, **PINNED_DATA)
    raw, metadata, errors = {}, {}, []
    for relative in sorted(set(expected) | {"b_release_context.py"}):
        path = _path(relative)
        value, row = _read_file(path)
        row.update(relative=relative, expected_sha256=expected.get(relative))
        raw[path], metadata[path] = value, row
        if relative in expected and row["observed_sha256"] != expected[relative]:
            errors.append(row)
    # This observation is for S's later structural consistency check. It does
    # not authenticate this already running entry or provide its trust root.
    value, row = _read_file(_ENTRY)
    row.update(
        relative="../../tools/c1_source_preflight.py",
        expected_sha256=None,
        purpose="post_execution_structure_only",
    )
    raw[_ENTRY], metadata[_ENTRY] = value, row
    if errors:
        return None, list(metadata.values()), errors
    snapshot = object.__new__(_Snapshot)
    _STORE[snapshot] = dict(
        raw=raw,
        metadata=metadata,
        anchor=_digest(
            {
                name: dict(sha256=_HASH(value).hexdigest(), bytes=len(value))
                for name, value in raw.items()
            }
        ),
    )
    return snapshot, list(metadata.values()), []


def main():
    global _VERIFIED, _PHASE
    observations = []
    try:
        if len(sys.argv) != 1 or os.path.realpath(os.getcwd()) != _ROOT:
            raise _Refusal("scope.preflight_workdir_or_arguments_mismatch")
        if (
            __name__ != "__main__"
            or type(__loader__).__name__ != "SourceFileLoader"
            or os.path.realpath(__loader__.get_filename("__main__")) != _ENTRY
        ):
            raise _Refusal("scope.preflight_startup_mismatch")
        original = getattr(sys, "orig_argv", None)
        if original is not None and (
            len(original) != 5
            or original[1:4] != ["-I", "-S", "-B"]
            or os.path.realpath(original[4]) != _ENTRY
        ):
            raise _Refusal("scope.preflight_startup_mismatch")
        _PHASE = "snapshot"
        snapshot, observations, errors = _collect()
        if errors:
            raise _Refusal("scope.preflight_source_identity_mismatch")
        for row in observations:
            path = row["path"]
            if path == _ENTRY or not path.endswith(".py"):
                continue
            relative = os.path.relpath(path, os.path.join(_ROOT, "qlab"))
            name = relative[:-3].replace(os.sep, ".")
            if name.endswith(".__init__"):
                name = name[:-9]
            _ALLOWED_IMPORTS.add(name)
        _EVENTS.append(
            dict(sequence=len(_EVENTS), event="preflight_conclusion", status="VERIFIED")
        )
        _VERIFIED = True
        _PHASE = "candidate_import"
        with tempfile.TemporaryDirectory(prefix="c1-preflight-bytecode-") as bytecode:
            sys.pycache_prefix = bytecode
            sys.path.insert(0, os.path.join(_ROOT, "qlab"))
            from qlab.dynamic_factor import scope_proof

            scope_proof._c1_snapshot_structure(snapshot)
            from qlab.dynamic_factor import b_release_context
            from qlab.dynamic_factor.conventions import load_conventions

            policy = load_conventions()
            if b_release_context.__spec__.origin != snapshot.path(
                "b_release_context.py"
            ):
                raise ValueError("scope.preflight_loading_mismatch")
            snapshot.bind_policy(policy)
            _PHASE = "snapshot_B2"
            proof = scope_proof.b2_isolation_proof_from_snapshot(policy, snapshot)
            _PHASE = "loaded_binding"
            loaded = snapshot.bind_loaded()
            consistency = proof["C1_source_preflight"]["entry_consistency"]
            proof["C1_source_preflight"] = dict(
                dependency_closed=True,
                source="controlled_entry_snapshot",
                snapshot_sha256=_STORE[snapshot]["anchor"],
                auditor_sha256=snapshot.identity("scope_proof.py"),
                entry_consistency=consistency,
                loaded_modules=loaded,
            )
            _EVENTS.append(
                dict(sequence=len(_EVENTS), event="B2_complete", status="VERIFIED")
            )
        result = dict(
            schema="EVO884.C1SourcePreflight/v1",
            status="VERIFIED",
            C1_dependency_closed=True,
            proof=proof,
            observations=observations,
            import_binding=loaded,
            authority="mechanism_only_pending_independent_review",
            startup=dict(
                executable=sys.executable,
                argv=sys.argv,
                original_argv=getattr(sys, "orig_argv", None),
                isolated=sys.flags.isolated,
                no_site=sys.flags.no_site,
                dont_write_bytecode=sys.flags.dont_write_bytecode,
                cwd=os.getcwd(),
                entry=_ENTRY,
            ),
        )
        rc = 0
    except (_Refusal, ValueError, RuntimeError, OSError) as exc:
        _EVENTS.append(dict(sequence=len(_EVENTS), event="refusal", code=str(exc)))
        result = dict(
            schema="EVO884.C1SourcePreflight/v1",
            status="REJECTED",
            C1_dependency_closed=False,
            reason=str(exc),
            observations=observations,
        )
        rc = 2
    result["events"] = _EVENTS
    sys.stdout.write(_DUMPS(result, sort_keys=True, ensure_ascii=False) + "\n")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
