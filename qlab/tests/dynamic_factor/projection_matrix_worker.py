"""Subprocess DUT host: input only, with OS-denied oracle reads and clocks."""

import base64
import datetime
import json
from pathlib import Path
import random
import sys
import time

from projection_test_helpers import case, plan
from qlab.dynamic_factor.execution_projection import _canonical
from qlab.dynamic_factor import noncash_v3


def main():
    inputs = json.loads(sys.stdin.buffer.read())
    seed, clock, oracle, guard_layer = sys.argv[1:]
    random.seed(int(seed))
    oracle_root = Path(oracle).resolve().parent
    if guard_layer == "python_audit_in_inherited_OS_network_sandbox":

        def audit(event, args):
            if event == "open" and isinstance(args[0], (str, bytes)):
                path = Path(args[0]).resolve()
                if path == oracle_root or oracle_root in path.parents:
                    raise PermissionError("DUT_ORACLE_READ_FORBIDDEN")

        sys.addaudithook(audit)
    denied = False
    try:
        Path(oracle).read_bytes()
    except PermissionError:
        denied = True
    if not denied:
        raise RuntimeError("DUT_ORACLE_READ_CAPABILITY_NOT_DENIED")
    original_datetime, original_date = datetime.datetime, datetime.date
    attempts = []

    def forbidden(*args, **kwargs):
        attempts.append("forbidden_clock_or_random_read")
        raise RuntimeError(attempts[-1])

    class NoClock(original_datetime):
        now = utcnow = today = staticmethod(forbidden)

    class NoDateClock(original_date):
        today = staticmethod(forbidden)

    protected_time = (
        "time",
        "monotonic",
        "perf_counter",
        "process_time",
        "time_ns",
        "monotonic_ns",
        "perf_counter_ns",
    )
    original_clocks = [getattr(time, name) for name in protected_time]
    for name in protected_time:
        setattr(time, name, forbidden)
    for name in (
        "random",
        "randrange",
        "randint",
        "choice",
        "choices",
        "shuffle",
        "sample",
        "getrandbits",
    ):
        setattr(random, name, forbidden)
    datetime.datetime, datetime.date = NoClock, NoDateClock
    noncash_v3.datetime = NoClock
    aliases = []
    for name, module in list(sys.modules.items()):
        if not name.startswith("qlab.") or module is None:
            continue
        for key, value in list(vars(module).items()):
            replacement = (
                NoClock
                if value is original_datetime
                else NoDateClock
                if value is original_date
                else forbidden
                if any(value is f for f in original_clocks)
                else None
            )
            if replacement is not None:
                setattr(module, key, replacement)
                aliases.append(name + "." + key)
    for provider in (
        time.time,
        time.monotonic,
        time.perf_counter,
        datetime.datetime.now,
        datetime.datetime.utcnow,
        datetime.date.today,
    ):
        try:
            provider()
        except RuntimeError:
            pass
        else:
            raise RuntimeError("CLOCK_INTERCEPTION_SELF_CHECK_FAILED")
    controls = list(attempts)
    attempts.clear()
    outputs = []
    for _ in range(2):
        outputs.append(base64.b64encode(_canonical(plan(*case(inputs)))).decode())
    print(
        json.dumps(
            dict(
                outputs=outputs,
                clock_control=clock,
                forbidden_attempts=attempts,
                clock_interception_self_checks=len(controls),
                intercepted_product_aliases=aliases,
                oracle_read_denied=denied,
                oracle_guard_layer=guard_layer,
                reader_calls=0,
                product_worker_roles=[],
            ),
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
