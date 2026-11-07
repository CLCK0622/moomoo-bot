"""Original adopted G14 bytes, separate from the immutable v3.0.1 freeze."""

from pathlib import Path

from ..contract import sha256
from ..reception_schema import strict_json


PROTOCOL_SHA256 = "68200926a94cc672e7f0e47c14cc6473b68920576a7ade1028c07fb5c168334d"


def adopted_protocol():
    raw = (
        Path(__file__).parent
        / "contracts"
        / "EVO883-G14-P1-adopted-protocol-v1.0.0.json"
    ).read_bytes()
    if sha256(raw) != PROTOCOL_SHA256:
        raise ValueError("execution.G14_adoption_identity_changed")
    return strict_json(raw)
