"""B01 metadata reception. No caller-mintable authority or runtime permission.

The deployment's original permission adapter is deliberately unconnected. Tests
may replace the private adapter to exercise reception; this does not certify a
real installation, source permission, A publication or a producer's proofs.
"""

import csv
from datetime import datetime
import io
import json
from weakref import WeakKeyDictionary

from .catalog_v21 import (
    BINDINGS as _CATALOG_BINDINGS,
    FIXTURES as _CATALOG_FIXTURES,
    derive as _derive_catalog,
)
from .contract import code_sha, sha256


ADOPTION_SHA256 = "ff5da6ef748d5f1fca592559e73656d5283e28ec9d279b65b3ac0fd5943069ff"
ANNOTATION_COMMENT = "01a19e47-bff6-7dc8-9d06-0ca0b4369576"
PUBLICATION_COMMENT = "01a19dda-830d-7b82-b549-b4d64129a6af"
ISSUE = "01a18a61-21a5-7763-8cd3-9c781f80499d"
_CONTEXTS = WeakKeyDictionary()


def _fail(reason):
    raise ValueError("B.release_context_" + reason)


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            _fail("encoding_invalid")
        result[key] = value
    return result


def _constant(value):
    _fail("encoding_invalid")


def _canonical(value):
    # Do not use contract.clean: NaN/Infinity must be rejected, never nullified.
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise ValueError("B.release_context_encoding_invalid") from exc


def _json(raw, *, canonical=False):
    if type(raw) is not bytes:
        _fail("encoding_invalid")
    try:
        value = json.loads(
            raw.decode("utf-8"), object_pairs_hook=_pairs, parse_constant=_constant
        )
    except (ValueError, UnicodeError) as exc:
        raise ValueError("B.release_context_encoding_invalid") from exc
    encoded = _canonical(value)
    if canonical and encoded != raw:
        _fail("encoding_invalid")
    return value


def _utc(value):
    if type(value) is not str or len(value) != 20 or value[19:] != "Z":
        _fail("encoding_invalid")
    if any(
        value[i] not in "0123456789"
        for i in (0, 1, 2, 3, 5, 6, 8, 9, 11, 12, 14, 15, 17, 18)
    ):
        _fail("encoding_invalid")
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as exc:
        raise ValueError("B.release_context_encoding_invalid") from exc
    return parsed


def _read_trusted_release():
    """Fixed package originals and original-authority platform registration.

    C1 deliberately omits the root file. C2 installs only the platform comment
    readback after BR-A. Its content is the strict JSON registration below;
    platform created_at supplies acceptance evidence; performance is a separate event.
    No request, environment, cwd or caller parameter selects an input.
    """
    from pathlib import Path

    try:
        self_path = Path(_read_trusted_release.__code__.co_filename).resolve()
        if type(__file__) is not str or self_path != Path(__file__).resolve():
            _fail("acceptance_mismatch")
    except (NameError, AttributeError, OSError, RuntimeError, TypeError) as exc:
        raise ValueError("B.release_context_acceptance_mismatch") from exc
    try:
        root_raw = (
            Path(__file__).parent
            / "b_release_originals"
            / "trust-root-platform-readback.json"
        ).read_bytes()
    except OSError as exc:
        raise ValueError("B.release_context_trust_binding_missing") from exc
    try:
        root = _json(root_raw)
        if (
            type(root) is not dict
            or root.get("type") != "comment"
            or root.get("author_type") != "agent"
            or root.get("author_id") != "cc562115-7ef6-4b8f-b4b6-a5b7584b1340"
            or type(root.get("id")) is not str
            or not root["id"]
            or type(root.get("revision")) is not int
            or root["revision"] < 1
            or type(root.get("content")) is not str
            or root.get("issue_id") != "01a19dab-15f2-7e58-96a0-cf92c87162c2"
        ):
            _fail("trust_binding_missing")
        accepted_at = root["created_at"]
        _utc(accepted_at)
        registration = _json(root["content"].encode("utf-8"))
        if type(registration) is not dict or set(registration) != {
            "schema",
            "context_version",
            "receiver_id",
            "implementation_id",
            "r_sha256",
            "p_sha256",
            "adoption_sha256",
            "policy_binding",
            "run_time_binding",
            "purpose",
            "limitations",
        }:
            _fail("trust_binding_missing")
        if (
            registration["schema"] != "EVO884.BReleaseTrustRegistration/v1"
            or registration["receiver_id"]
            != "gongbu.original-host:5a307571-9534-4bbc-932c-93ffc9c94d73"
            or any(
                type(registration[k]) is not str or not registration[k]
                for k in ("context_version", "purpose", "limitations")
            )
            or type(registration["policy_binding"]) is not dict
        ):
            _fail("trust_binding_missing")
        # Anti-cycle: the root SHA is data-only, never embedded in any code.
        # This sole self-read is used only for the module implementation_id.
        try:
            self_raw = Path.read_bytes(self_path)
        except OSError as exc:
            raise ValueError("B.release_context_acceptance_mismatch") from exc
        implementation_id = sha256(self_raw)
        if registration["implementation_id"] != implementation_id:
            _fail("acceptance_mismatch")
        original_sha256 = {
            "EVO883-B-RUNTIME-RELEASE-P1-adopted-protocol-v1.0.0.json": "ff5da6ef748d5f1fca592559e73656d5283e28ec9d279b65b3ac0fd5943069ff",
            "EVO883-EVO893-v10-ruling.json": "834bf9546dda93c3fb613833b59ac87842c2825b71c11bc09edc13608f5d42e4",
            "EVO883-S1-BRKB-field-receipt.json": "ff8dee166c469310b915f903a32164351647e61dd8340437ffa09b45da9e0442",
            "EVO883-S2-v14-field-receipt.json": "9b5fd1e87a2cae26df8a0c1a8ee9fbd880c07234e05a9253ff9886d4dcb7711f",
            "EVO883-S3-v12-final-receipt.json": "1df425a328539f4cddfe3d574feabc1b753fc0abe2ff15d318634aee7dff3836",
            "EVO883-S4-v11-receipt.json": "d44ce4e0b13d68a129f6aca0ad2187f459ea978f117510cc48d910fb8b44b11f",
            "EVO883-v10-engineering-scope-receipt.json": "4da26596777a62595664ba9b9e17480113f96ccbd2c1d0226df083ac2e7ecc0f",
            "EVO883-v20.1-final-receipt.json": "cdd7954a20102e1053f932fe559153b26336475afdb41b772004795708bf3c4e",
            "EVO883-v21-final-receipt.json": "b8b930396e7caf42ad8bde0f2f7ff190c40f36fd4c4686964a39154926f6644a",
            "EVO893-B-CMI-guard-v21.json": "08ed088405cbefa9bd24e8cb0756d5d10a62b105153b9cfba02af504d9371f77",
            "EVO893-B-noncash-catalog-v21.csv": "5040272302cf675b99e0b954669dde72bfc6431f47fb9d835f3acb6f408d1a13",
            "EVO938-B-runtime-release-P-v1.0.0.json": "4a4b24b0a6ee2b6b561d285fa6f3f9233960959500b6e02fc137c83ca31deae1",
            "EVO938-B-runtime-release-R-v1.0.0.json": "68f06b15ded4cb1ec5219a5456a2e0f0f376cab54a9e3ac33aee653dacfa877c",
            "annotation-platform-readback.json": "d25ba025d42fea6ad908566384f97f6fd1ed567eb1f4474bba46105e9aa77c81",
            "publication-platform-readback.json": "f847be9a107b9293e134bfc4d9a03a3c3cb1eeb823f40991d7b8d28d1533455e",
        }
        originals = {}
        for name, expected in original_sha256.items():
            try:
                raw = (
                    Path(__file__).parent / "b_release_originals" / name
                ).read_bytes()
            except OSError as exc:
                raise ValueError("B.release_context_release_mismatch") from exc
            if sha256(raw) != expected:
                _fail("release_mismatch")
            originals[name] = raw
        r_raw = originals["EVO938-B-runtime-release-R-v1.0.0.json"]
        p_raw = originals["EVO938-B-runtime-release-P-v1.0.0.json"]
        adoption_raw = originals[
            "EVO883-B-RUNTIME-RELEASE-P1-adopted-protocol-v1.0.0.json"
        ]
        if (
            registration["r_sha256"] != sha256(r_raw)
            or registration["p_sha256"] != sha256(p_raw)
            or registration["adoption_sha256"] != sha256(adoption_raw)
        ):
            _fail("release_mismatch")
        r, p = _json(r_raw, canonical=True), _json(p_raw, canonical=True)
        readback = _json(originals["publication-platform-readback.json"])
        publication = dict(
            comment_id=readback["id"],
            revision=readback["revision"],
            created_at=readback["created_at"],
            R=dict(sha256=sha256(r_raw), platform=p["actual_core_attachment"]),
            P=dict(sha256=sha256(p_raw)),
        )
        readback = _json(originals["annotation-platform-readback.json"])
        annotation = dict(
            issue_id=ISSUE,
            comment_id=readback["id"],
            revision=readback["revision"],
            content=readback["content"],
        )
        inputs = {}
        for entry in r["accepted_input_manifest"]["entries"][:-1]:
            name = entry["accepted_receipt"]["file"]
            inputs[name] = originals[name]
        for key in ("catalog_csv", "CMI_guard"):
            name = r["accepted_input_manifest"]["entries"][0][key]["file"]
            inputs[name] = originals[name]
        time = dict(
            context_version=registration["context_version"],
            receiver_id=registration["receiver_id"],
            accepted_at=accepted_at,
        )
        run = registration["run_time_binding"]
        if type(run) is not dict or run.get("mode") not in {"history", "forward"}:
            _fail("trust_binding_missing")
        if run.get("first_performance_at") is None:
            if (
                set(run)
                != {"mode", "first_performance_at", "signal_close", "performance_state"}
                or run["performance_state"] != "pre_performance"
            ):
                _fail("trust_binding_missing")
        else:
            if set(run) != {"mode", "first_performance_at", "signal_close"}:
                _fail("trust_binding_missing")
            if _utc(run["first_performance_at"]) <= _utc(accepted_at):
                _fail("scope_mismatch")
        if run["mode"] == "history":
            if run["signal_close"] is not None:
                _fail("scope_mismatch")
        elif run["first_performance_at"] is not None and _utc(
            run["signal_close"]
        ) < _utc(accepted_at):
            _fail("scope_mismatch")
        source = dict(
            r_raw=r_raw,
            p_raw=p_raw,
            adoption_raw=adoption_raw,
            original_inputs=inputs,
            publication_raw=_canonical(publication),
            annotation_raw=_canonical(annotation),
            acceptance_time_evidence_raw=root_raw,
            **time,
            implementation_id=implementation_id,
            expected_policy_binding_bytes=_canonical(registration["policy_binding"]),
            expected_publication_bytes=_canonical(publication),
            expected_annotation_bytes=_canonical(annotation),
            expected_acceptance_time_bytes=_canonical(root),
            run_time_binding_bytes=_canonical(run),
        )
        source["expected_sha256"] = {
            k: sha256(source[k])
            for k in (
                "r_raw",
                "p_raw",
                "adoption_raw",
                "publication_raw",
                "annotation_raw",
                "acceptance_time_evidence_raw",
            )
        }
        source["expected_sha256"].update(
            implementation_sha256=implementation_id,
            original_inputs={name: sha256(raw) for name, raw in inputs.items()},
        )
        return source
    except (KeyError, TypeError, AttributeError, IndexError, UnicodeError) as exc:
        raise ValueError("B.release_context_encoding_invalid") from exc


class ReleaseContext:
    """Immutable process-local capability. Persist bindings, never this object."""

    __slots__ = ("__weakref__",)

    def __new__(cls, *args, **kwargs):
        raise TypeError("B.release_context_trust_binding_missing")

    def __getattr__(self, name):
        record = _CONTEXTS.get(self)
        if record is None:
            _fail("trust_binding_missing")
        fields, _ = record
        if name not in fields:
            raise AttributeError(name)
        return fields[name]

    def __setattr__(self, name, value):
        raise AttributeError("immutable ReleaseContext")

    def __copy__(self):
        return self

    def __deepcopy__(self, memo):
        return self

    def __reduce_ex__(self, protocol):
        raise TypeError("B.release_context_trust_binding_missing")


def _policy_binding(policy):
    return dict(
        policy.binding,
        date_manifest_sha256=sha256(policy.raw_date_manifest),
        common_calendar_sha256=policy.date_manifest["common_calendar_sha256"],
        universe=list(policy.profile["universe"]),
    )


def _source():
    source = _read_trusted_release()
    required = {
        "r_raw",
        "p_raw",
        "adoption_raw",
        "original_inputs",
        "expected_sha256",
        "publication_raw",
        "annotation_raw",
        "acceptance_time_evidence_raw",
        "context_version",
        "receiver_id",
        "implementation_id",
        "accepted_at",
        "expected_policy_binding_bytes",
        "expected_publication_bytes",
        "expected_annotation_bytes",
        "expected_acceptance_time_bytes",
        "run_time_binding_bytes",
    }
    if type(source) is not dict or set(source) != required:
        _fail("trust_binding_missing")
    # Freeze the host response before any work; no shared caller-owned dicts.
    expected = source["expected_sha256"]
    inputs = source["original_inputs"]
    if type(expected) is not dict or type(inputs) is not dict:
        _fail("trust_binding_missing")
    raw_keys = {
        "r_raw",
        "p_raw",
        "adoption_raw",
        "publication_raw",
        "annotation_raw",
        "acceptance_time_evidence_raw",
    }
    if set(expected) != raw_keys | {"implementation_sha256", "original_inputs"}:
        _fail("trust_binding_missing")
    if type(expected["original_inputs"]) is not dict or set(inputs) != set(
        expected["original_inputs"]
    ):
        _fail("trust_binding_missing")
    for value in [expected[k] for k in raw_keys | {"implementation_sha256"}] + list(
        expected["original_inputs"].values()
    ):
        if (
            type(value) is not str
            or len(value) != 64
            or any(c not in "0123456789abcdef" for c in value)
        ):
            _fail("encoding_invalid")
    copied = dict(
        source,
        expected_sha256=dict(
            expected, original_inputs=dict(expected["original_inputs"])
        ),
        original_inputs=dict(inputs),
    )
    for key in raw_keys:
        _json(copied[key], canonical=key in {"r_raw", "p_raw"})
    for raw in inputs.values():
        if type(raw) is not bytes:
            _fail("encoding_invalid")
    _json(copied["expected_policy_binding_bytes"], canonical=True)
    for key in (
        "expected_publication_bytes",
        "expected_annotation_bytes",
        "expected_acceptance_time_bytes",
    ):
        _json(copied[key], canonical=True)
    _json(copied["run_time_binding_bytes"], canonical=True)
    return copied


def _verify_release(source, policy):
    expected = source["expected_sha256"]
    for key in ("r_raw", "p_raw", "adoption_raw", "publication_raw"):
        if sha256(source[key]) != expected[key]:
            _fail("release_mismatch")
    if sha256(source["adoption_raw"]) != ADOPTION_SHA256:
        _fail("release_mismatch")
    r, p = (
        _json(source["r_raw"], canonical=True),
        _json(source["p_raw"], canonical=True),
    )
    publication = _json(source["publication_raw"])
    if _canonical(publication) != source["expected_publication_bytes"]:
        _fail("release_mismatch")
    if (
        publication["comment_id"] != PUBLICATION_COMMENT
        or type(publication["revision"]) is not int
        or publication["revision"] < 1
        or publication["R"]["sha256"] != sha256(source["r_raw"])
        or publication["P"]["sha256"] != sha256(source["p_raw"])
        or p["actual_core_attachment"] != publication["R"]["platform"]
        or p["core_raw_sha256"] != sha256(source["r_raw"])
        or r["formal_clause_adoption_sha256"] != ADOPTION_SHA256
        or p["core_version_and_formal_adoption_sha256"][
            "formal_adoption_machine_sha256"
        ]
        != ADOPTION_SHA256
        or r["schema"] != "EVO938.BRuntimeCatalogRelease/v1"
        or p["schema"] != "EVO938.BRuntimeCatalogPublicationEnvelope/v1"
        or p["release_id"] != r["release_id"]
        or p["core_version"] != r["version"]
    ):
        _fail("release_mismatch")
    entries = r["accepted_input_manifest"]["entries"]
    if [e["input_id"] for e in entries] != [
        "V21",
        "CMI",
        "S1",
        "S2",
        "S3",
        "S4",
        "S5a",
        "S5b",
        "QUARANTINE",
    ]:
        _fail("release_mismatch")
    required = {}
    for entry in entries[:-1]:
        item = entry["accepted_receipt"]
        required[item["file"]] = item["raw_sha256"]
        raw = source["original_inputs"].get(item["file"])
        if (
            type(raw) is not bytes
            or sha256(raw) != item["raw_sha256"]
            or sha256(raw) != expected["original_inputs"].get(item["file"])
        ):
            _fail("release_mismatch")
        receipt = _json(raw)
        scope = entry["accepted_scope_verbatim"]
        if {k: receipt[k] for k in scope["keys"]} != scope["value"]:
            _fail("release_mismatch")
    v21 = entries[0]
    for key in ("catalog_csv", "CMI_guard"):
        item = v21[key]
        required[item["file"]] = item["raw_sha256"]
    if required != expected["original_inputs"]:
        _fail("release_mismatch")
    for name, identity in required.items():
        if sha256(source["original_inputs"][name]) != identity:
            _fail("release_mismatch")
    csv_raw = source["original_inputs"][v21["catalog_csv"]["file"]]
    rows = list(csv.reader(io.StringIO(csv_raw.decode("utf-8"), newline="")))
    catalog = r["catalog"]
    if [catalog["v21_catalog"]["columns"]] + catalog["v21_catalog"][
        "rows"
    ] != rows or catalog["CMI_guard_mapping"]["value"] != _json(
        source["original_inputs"][v21["CMI_guard"]["file"]]
    ):
        _fail("release_mismatch")
    # Recompute every fact/protective row from the original v21 columns.
    original = [dict(zip(rows[0], row)) for row in rows[1:]]
    ordered = {row["symbol"]: row for row in original}
    derived = r["derivation_payload"]
    if [row["symbol"] for row in derived["per_symbol"]] != r[
        "policy_profile_calendar_domain_bindings"
    ]["U64"]["order_and_ids"]:
        _fail("release_mismatch")
    for row in derived["per_symbol"]:
        old = ordered[row["symbol"]]
        protected = old["candidate_guard"].startswith(
            ("B 防护", "guard_pending_review=true")
        )
        if (
            row["fact_state_v21"] != old["fact_state"]
            or row["candidate_guard_v21"] != old["candidate_guard"]
            or row["protective_membership"] is not protected
            or row["guard_pending_review"]
            is not old["candidate_guard"].startswith("guard_pending_review=true")
            or row["fact_class"]
            != (
                "KNOWN_UNCLOSED"
                if old["fact_state"].startswith("未闭合")
                else "UNKNOWN"
            )
        ):
            _fail("release_mismatch")
    h_c, h_d = sha256(_canonical(catalog)), sha256(_canonical(derived))
    if h_c != r["catalog_sha256"] or h_d != r["derivation_sha256"]:
        _fail("release_mismatch")
    binding = _json(source["expected_policy_binding_bytes"], canonical=True)
    domain = r["policy_profile_calendar_domain_bindings"]
    if (
        domain["U64"]["order_and_ids"] != binding["universe"]
        or domain["policy"]["raw_sha256"] != binding["prereg_sha256"]
        or domain["common_profile"]["raw_sha256"]
        != "07b71b3fc59dc6dae1c96cadd3155622a18f4c4ad29b7c69b8f79c1455efc2d3"
        or domain["calendar"]["calendar_sha256"] != binding["common_calendar_sha256"]
    ):
        _fail("scope_mismatch")
    return r, p, publication, h_c, h_d, binding


def _acceptance(source, policy, *, a_raw=None):
    try:
        r, p, publication, h_c, h_d, binding = _verify_release(source, policy)
        if source["expected_sha256"]["implementation_sha256"] != code_sha(
            receive_release_context
        ) or any(
            type(source[k]) is not str or not source[k]
            for k in ("context_version", "receiver_id", "implementation_id")
        ):
            _fail("acceptance_mismatch")
        time = _json(source["acceptance_time_evidence_raw"])
        if (
            sha256(source["acceptance_time_evidence_raw"])
            != source["expected_sha256"]["acceptance_time_evidence_raw"]
            or _canonical(time) != source["expected_acceptance_time_bytes"]
            or type(time) is not dict
            or time.get("type") != "comment"
            or time.get("author_type") != "agent"
            or time.get("author_id") != "cc562115-7ef6-4b8f-b4b6-a5b7584b1340"
            or time.get("issue_id") != "01a19dab-15f2-7e58-96a0-cf92c87162c2"
            or time.get("created_at") != source["accepted_at"]
            or type(time.get("content")) is not str
            or type(_json(time["content"].encode("utf-8"))) is not dict
            or _json(time["content"].encode("utf-8")).get("context_version")
            != source["context_version"]
            or _json(time["content"].encode("utf-8")).get("receiver_id")
            != source["receiver_id"]
        ):
            _fail("acceptance_mismatch")
        if _utc(source["accepted_at"]) < _utc(publication["created_at"]):
            _fail("acceptance_mismatch")
        # Rebuild A from the independent host binding before checking the
        # supplied annotation. C05 requires A mismatch to win a double fault.
        annotation = _json(source["expected_annotation_bytes"], canonical=True)
        annotation_binding = {
            k: annotation[k] for k in ("issue_id", "comment_id", "revision")
        }
        annotation_binding["content_sha256"] = sha256(
            annotation["content"].encode("utf-8")
        )
        a = dict(
            schema="EVO884.BReleaseAcceptance/v1",
            context_version=source["context_version"],
            release_id=r["release_id"],
            release_version=r["version"],
            h_r=sha256(source["r_raw"]),
            h_p=sha256(source["p_raw"]),
            h_c=h_c,
            h_d=h_d,
            adoption_sha256=ADOPTION_SHA256,
            publication=publication,
            accepted_input_manifest=r["accepted_input_manifest"],
            fact_scope=r["derivation_payload"],
            unverified_runtime_obligations=r["proof_obligations_and_UNVERIFIED_status"],
            receiver_id=source["receiver_id"],
            implementation_id=source["implementation_id"],
            implementation_sha256=code_sha(receive_release_context),
            accepted_at=source["accepted_at"],
            acceptance_time_evidence_sha256=sha256(
                source["acceptance_time_evidence_raw"]
            ),
            policy_binding=binding,
            annotation_binding=annotation_binding,
            run_time_binding=_json(source["run_time_binding_bytes"], canonical=True),
            runtime_consumable=False,
            certifiable=False,
            seal_status="seal_pending",
        )
        if a_raw is not None:
            _json(a_raw, canonical=True)
            if a_raw != _canonical(a):
                _fail("acceptance_mismatch")
        actual_annotation = _json(source["annotation_raw"])
        if (
            type(actual_annotation) is not dict
            or sha256(source["annotation_raw"])
            != source["expected_sha256"]["annotation_raw"]
            or _canonical(actual_annotation) != source["expected_annotation_bytes"]
            or actual_annotation.get("comment_id") != ANNOTATION_COMMENT
            or actual_annotation.get("issue_id") != ISSUE
            or type(actual_annotation.get("revision")) is not int
            or actual_annotation["revision"] < 1
            or type(actual_annotation.get("content")) is not str
            or not actual_annotation["content"]
        ):
            _fail("annotation_missing_or_invalid")
        return a
    except (KeyError, TypeError, IndexError, UnicodeError) as exc:
        raise ValueError("B.release_context_encoding_invalid") from exc


def receive_release_context(*, policy, a_raw=None):
    """Host-only reception or reloading of the exact existing A. No re-signing."""
    source = _source()
    a = _acceptance(source, policy, a_raw=a_raw)
    if source["expected_policy_binding_bytes"] != _canonical(_policy_binding(policy)):
        _fail("scope_mismatch")
    expected_a = _canonical(a)
    if a_raw is not None:
        _json(a_raw, canonical=True)
        if a_raw != expected_a:
            _fail("acceptance_mismatch")
    fields = {
        key: a[key]
        for key in (
            "context_version",
            "release_id",
            "release_version",
            "receiver_id",
            "implementation_id",
            "implementation_sha256",
            "accepted_at",
            "adoption_sha256",
            "acceptance_time_evidence_sha256",
            "h_r",
            "h_p",
            "h_c",
            "h_d",
        )
    }
    fields.update(
        a_raw=expected_a,
        h_a=sha256(expected_a),
        r_raw=source["r_raw"],
        p_raw=source["p_raw"],
        acceptance_time_evidence_raw=source["acceptance_time_evidence_raw"],
        policy_binding_bytes=_canonical(a["policy_binding"]),
        annotation_binding_bytes=_canonical(a["annotation_binding"]),
    )
    context = object.__new__(ReleaseContext)
    _CONTEXTS[context] = (fields, source)
    return context


def _consumer_catalog(source, release, policy):
    """Use the original derivation only after all three local originals match R.

    Gongbu 01a1b818-7cf9 permits R-bound receipt and frozen policy dependencies.
    The original module retains its own SHA checks on the subsequent re-read.
    """
    binding = _json(source["expected_policy_binding_bytes"], canonical=True)
    calendar_raw = "".join(day + "\n" for day in policy.calendar).encode("utf-8")
    if sha256(calendar_raw) != binding["common_calendar_sha256"]:
        _fail("scope_mismatch")
    v21 = release["accepted_input_manifest"]["entries"][0]
    expected = {
        v21[key]["file"]: v21[key]["raw_sha256"]
        for key in ("catalog_csv", "CMI_guard", "accepted_receipt")
    }
    if expected != _CATALOG_BINDINGS:
        _fail("release_mismatch")
    for name in (
        "EVO893-B-noncash-catalog-v21.csv",
        "EVO893-B-CMI-guard-v21.json",
        "EVO883-v21-final-receipt.json",
    ):
        try:
            raw = (_CATALOG_FIXTURES / "catalog-v21" / name).read_bytes()
        except OSError as exc:
            raise ValueError("B.release_context_release_mismatch") from exc
        if sha256(raw) != expected[name] or raw != source["original_inputs"][name]:
            _fail("release_mismatch")
    try:
        return _derive_catalog(policy)["catalog"]
    except (ValueError, OSError) as exc:
        raise ValueError("B.release_context_release_mismatch") from exc


def check_release_context(
    release_context, *, policy, request, expected_release_identity_bytes=None
) -> bytes:
    """Recompute from original host inputs on every call; never read economics."""
    if release_context is None:
        _fail("required")
    if type(release_context) is not ReleaseContext:
        _fail("type_mismatch")
    record = _CONTEXTS.get(release_context)
    if record is None:
        _fail("trust_binding_missing")
    fields, original = record
    source = _source()
    a = _acceptance(source, policy, a_raw=fields["a_raw"])
    if source != original or _canonical(a) != fields["a_raw"]:
        _fail("acceptance_mismatch")
    identity = {
        key: fields[key]
        for key in (
            "context_version",
            "release_id",
            "release_version",
            "adoption_sha256",
            "h_a",
            "h_r",
            "h_p",
            "h_c",
            "h_d",
            "receiver_id",
            "implementation_id",
            "implementation_sha256",
            "accepted_at",
            "acceptance_time_evidence_sha256",
        )
    }
    identity.update(
        schema="EVO884.BReleaseContextIdentity/v1",
        policy_binding=a["policy_binding"],
        annotation_binding=a["annotation_binding"],
    )
    raw = _canonical(
        dict(
            schema="EVO884.BReleaseContextBinding/v1",
            identity=identity,
            identity_sha256=sha256(_canonical(identity)),
        )
    )
    if expected_release_identity_bytes is not None:
        _json(expected_release_identity_bytes, canonical=True)
        if expected_release_identity_bytes != raw:
            _fail("persistent_identity_mismatch")
    if source["expected_policy_binding_bytes"] != _canonical(_policy_binding(policy)):
        _fail("scope_mismatch")
    try:
        release = _json(fields["r_raw"], canonical=True)
        catalog = _consumer_catalog(source, release, policy)
        required = {"h_r": fields["h_r"], "h_a": fields["h_a"], "h_d": fields["h_d"]}
        if (
            type(request) is not dict
            or request.get("synthetic") is not False
            or request.get("release_binding") != required
            or request.get("mode") not in {"history", "forward"}
            or _canonical(request.get("catalog")) != _canonical(catalog)
        ):
            _fail("scope_mismatch")
        sealed = _utc(request["sealed_at"])
        accepted = _utc(a["accepted_at"])
        if sealed < accepted:
            _fail("scope_mismatch")
        run = a["run_time_binding"]
        if type(run) is not dict or run.get("mode") != request["mode"]:
            _fail("scope_mismatch")
        if run.get("first_performance_at") is None:
            if (
                set(run)
                != {"mode", "first_performance_at", "signal_close", "performance_state"}
                or run["performance_state"] != "pre_performance"
            ):
                _fail("scope_mismatch")
            first = _utc(request["first_performance_at"])
            signal_close = request.get("signal_close")
            if first <= accepted:
                _fail("scope_mismatch")
        else:
            if (
                set(run) != {"mode", "first_performance_at", "signal_close"}
                or run["first_performance_at"] != request.get("first_performance_at")
                or run["signal_close"] != request.get("signal_close")
            ):
                _fail("scope_mismatch")
            first = _utc(run["first_performance_at"])
            signal_close = run["signal_close"]
        if request["mode"] == "history":
            if sealed >= first or signal_close is not None:
                _fail("scope_mismatch")
        elif _utc(signal_close) < sealed or _utc(signal_close) < accepted:
            _fail("scope_mismatch")
    except (KeyError, TypeError) as exc:
        raise ValueError("B.release_context_scope_mismatch") from exc
    return raw
