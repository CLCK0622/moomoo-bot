"""Read the approved release through the controlled host, with mandatory V5.

There is no filename search, caller path override, v4 fallback or installer.
Until the original deployment/permission inputs exist, the host refuses.
"""

from copy import deepcopy

from . import authority_host as host
from .contract import sha256
from .reception_schema import strict_json


def read_approved_release(*, host_context=None):
    from .authority_prefix import verify_anchor_prefix

    context = host.open_host_context() if host_context is None else host_context
    source = host.observe(context)
    if source.get("release_verified") is not True:
        raise ValueError("ledger.current_release_unbound_or_stale")
    anchor = strict_json(source["published_anchor_bytes"])
    if (
        anchor != source["anchor"]
        or sha256(source["published_anchor_bytes"])
        != source["identities"]["anchor_sha256"]
    ):
        raise ValueError("ledger.current_release_unbound_or_stale")
    checked = verify_anchor_prefix(source["chain_raw"], anchor, source["observation"])
    if checked["status"] != "PASS":
        raise ValueError(checked["reasons"][0])
    # Keep the complete anchor, especially ledger_file_sha256.
    return deepcopy(anchor)
