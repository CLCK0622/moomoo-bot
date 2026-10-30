"""Default-off external networking for the whole qlab pytest session.

CPython socket audit events run before DNS/connection/datagram I/O, including
connect_ex and references imported before this conftest. Install at configure
time so collection and fixtures are covered as well as test bodies. This is a
test guard, not an OS sandbox for subprocesses or native networking libraries.
"""
from __future__ import annotations

import ipaddress
import os
import socket
import sys

import pytest


def _loopback(host):
    if isinstance(host, bytes):
        host = host.decode("ascii")
    if not isinstance(host, str):
        return False
    if host.lower() in {"localhost", "localhost."}:
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    mapped = getattr(address, "ipv4_mapped", None)
    return address.is_loopback or (mapped is not None and mapped.is_loopback)


class _NetworkGuard:
    def __init__(self):
        self.active = True
        self.attempts = []
        self.reported_attempts = 0

    def __call__(self, event, args):
        if not self.active:
            return
        if event in {"socket.connect", "socket.sendto", "socket.sendmsg"}:
            sock, address = args
            if sock.family == socket.AF_UNIX or address is None:
                return
            allowed = (
                sock.family in {socket.AF_INET, socket.AF_INET6}
                and _loopback(address[0])
            )
        elif event in {
            "socket.getaddrinfo", "socket.gethostbyname", "socket.gethostbyaddr"
        }:
            address = args[0]
            # getaddrinfo(None, ...) is a local bind address lookup.
            allowed = (
                event == "socket.getaddrinfo" and address is None
            ) or _loopback(address)
        elif event == "socket.getnameinfo":
            address = args[0]
            allowed = _loopback(address[0])
        else:
            return
        if not allowed:
            # pytest failures derive from BaseException: fetchers catching
            # ordinary network errors cannot turn a violation into a skip/gap.
            message = (
                f"external network blocked: {event} {address!r}; "
                "live tests require @pytest.mark.live_net and QLAB_LIVE_NET=1"
            )
            self.attempts.append(message)
            pytest.fail(message, pytrace=False)


def pytest_configure(config):
    # Capture once: a test changing its environment cannot disable the guard.
    config._qlab_live_net = os.environ.get("QLAB_LIVE_NET") == "1"
    if not config._qlab_live_net:
        guard = config._qlab_network_guard = _NetworkGuard()
        sys.addaudithook(guard)


def pytest_collection_modifyitems(config, items):
    if not config._qlab_live_net:
        skip = pytest.mark.skip(
            reason="external network disabled; set QLAB_LIVE_NET=1 to run live_net tests"
        )
        for item in items:
            if item.get_closest_marker("live_net"):
                item.add_marker(skip)


@pytest.hookimpl(hookwrapper=True, tryfirst=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    guard = getattr(item.config, "_qlab_network_guard", None)
    if guard is not None and len(guard.attempts) > guard.reported_attempts:
        # A worker thread or an overbroad exception handler can swallow the
        # immediate failure. The test must still fail, including xfail/skip.
        report = outcome.get_result()
        report.outcome = "failed"
        # Session.testsfailed excludes reports carrying wasxfail, even after
        # their outcome is changed to failed. This is an unconditional failure.
        if hasattr(report, "wasxfail"):
            del report.wasxfail
        report.longrepr = "\n".join(guard.attempts[guard.reported_attempts:])
        # Keep every violation for sessionfinish; only advance the reporting
        # cursor so later, unrelated tests are not blamed for the same attempt.
        guard.reported_attempts = len(guard.attempts)


def pytest_sessionfinish(session, exitstatus):
    guard = getattr(session.config, "_qlab_network_guard", None)
    if guard is not None and guard.attempts and exitstatus in {
        pytest.ExitCode.OK, pytest.ExitCode.NO_TESTS_COLLECTED
    }:
        # Any violation makes a successful session impossible, even if a
        # report was already emitted or no test report can carry the failure.
        session.config.get_terminal_writer().line("\n".join(guard.attempts), red=True)
        session.exitstatus = pytest.ExitCode.TESTS_FAILED


def pytest_unconfigure(config):
    # Audit hooks cannot be removed. Disable this instance for pytest.main()
    # callers that run another session in the same process.
    guard = getattr(config, "_qlab_network_guard", None)
    if guard is not None:
        guard.active = False
