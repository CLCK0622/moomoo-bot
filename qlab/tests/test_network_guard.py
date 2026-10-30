"""Exercise the real pytest policy in child sessions, without fetching data."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys
import textwrap

import pytest


def _pytest_session(tmp_path, source, live_net=None):
    tests = Path(__file__).parent
    shutil.copyfile(tests / "conftest.py", tmp_path / "conftest.py")
    shutil.copyfile(tests.parent / "pytest.ini", tmp_path / "pytest.ini")
    (tmp_path / "test_probe.py").write_text(textwrap.dedent(source), encoding="utf-8")
    env = os.environ.copy()
    env.pop("QLAB_LIVE_NET", None)
    env.pop("PYTEST_ADDOPTS", None)
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    if live_net is not None:
        env["QLAB_LIVE_NET"] = live_net
    # Keep a reference from BEFORE conftest loads: patching socket.connect alone
    # would leave this reference unguarded. Audit events cover it as well.
    bootstrap = (
        "import socket,sys; socket._saved_connect = socket.socket.connect; "
        "import pytest; raise SystemExit(pytest.main(sys.argv[1:]))"
    )
    return subprocess.run(
        [sys.executable, "-c", bootstrap, "-q", "-rs", "--tb=short", "-p", "no:cacheprovider"],
        cwd=tmp_path, env=env, capture_output=True, text=True, timeout=30,
    )


def test_unmarked_external_io_fails_instead_of_skipping(tmp_path):
    result = _pytest_session(tmp_path, '''
        import os
        import socket
        import pytest

        @pytest.mark.parametrize("operation", [
            "connect", "connect_ex", "saved_connect", "ipv6", "sendto", "sendmsg",
            "getaddrinfo", "gethostbyname", "gethostbyname_ex", "gethostbyaddr",
            "getnameinfo", "env_change",
        ])
        def test_external(operation):
            # These are documentation-only addresses/domains, never data sources.
            address = ("192.0.2.1", 443)
            try:
                if operation in {"getaddrinfo", "gethostbyname", "gethostbyname_ex"}:
                    if operation == "getaddrinfo":
                        socket.getaddrinfo("example.invalid", 443)
                    else:
                        getattr(socket, operation)("example.invalid")
                elif operation == "gethostbyaddr":
                    socket.gethostbyaddr(address[0])
                elif operation == "getnameinfo":
                    socket.getnameinfo(address, 0)
                else:
                    family = socket.AF_INET6 if operation == "ipv6" else socket.AF_INET
                    kind = socket.SOCK_DGRAM if operation in {"sendto", "sendmsg"} else socket.SOCK_STREAM
                    with socket.socket(family, kind) as sock:
                        sock.settimeout(0.05)
                        if operation == "sendto":
                            sock.sendto(b"probe", address)
                        elif operation == "sendmsg":
                            sock.sendmsg([b"probe"], [], 0, address)
                        elif operation == "saved_connect":
                            socket._saved_connect(sock, address)
                        elif operation == "ipv6":
                            sock.connect(("2001:db8::1", 443))
                        elif operation == "env_change":
                            os.environ["QLAB_LIVE_NET"] = "1"
                            sock.connect(address)
                        else:
                            getattr(sock, operation)(address)
            except Exception:
                pytest.skip("a fetcher might otherwise hide a network error")
    ''')
    assert result.returncode == 1, result.stdout + result.stderr
    assert "12 failed" in result.stdout, result.stdout
    assert "external network blocked" in result.stdout
    assert "skipped" not in result.stdout


def test_swallowed_and_threaded_violations_still_fail(tmp_path):
    result = _pytest_session(tmp_path, '''
        import socket
        import threading
        import pytest

        def swallowed():
            try:
                socket.getaddrinfo("example.invalid", 443)
            except BaseException:
                pass

        @pytest.mark.parametrize("mode", ["swallowed", "thread", "skip"])
        def test_violation(mode):
            if mode == "thread":
                worker = threading.Thread(target=swallowed)
                worker.start()
                worker.join()
            else:
                swallowed()
                if mode == "skip":
                    pytest.skip("cannot hide a violation")
    ''')
    assert result.returncode == 1, result.stdout + result.stderr
    assert "3 failed" in result.stdout and "external network blocked" in result.stdout


@pytest.mark.parametrize("phase", ["collection", "setup", "teardown"])
def test_guard_covers_collection_and_session_fixtures(tmp_path, phase):
    if phase == "collection":
        source = 'import socket\nsocket.getaddrinfo("example.invalid", 443)\n'
    else:
        body = (
            'socket.getaddrinfo("example.invalid", 443)\nyield'
            if phase == "setup" else
            'yield\nsocket.getaddrinfo("example.invalid", 443)'
        )
        source = (
            "import socket,pytest\n"
            '@pytest.fixture(scope="session", autouse=True)\n'
            "def fixture():\n" + textwrap.indent(body, "    ") + "\n"
            "def test_body(): pass\n"
        )
    result = _pytest_session(tmp_path, source)
    assert result.returncode == (2 if phase == "collection" else 1), result.stdout + result.stderr
    assert "1 error" in result.stdout and "external network blocked" in result.stdout


@pytest.mark.parametrize("live_net", [None, "0", "true"])
def test_live_marker_skips_without_exact_opt_in(tmp_path, live_net):
    result = _pytest_session(tmp_path, '''
        import pytest
        @pytest.mark.live_net
        def test_live():
            raise AssertionError("live body must not execute")
    ''', live_net)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "1 skipped" in result.stdout
    assert "set QLAB_LIVE_NET=1" in result.stdout
    assert "PytestUnknownMarkWarning" not in result.stdout


def test_explicit_opt_in_runs_marker_and_allows_external_socket_event(tmp_path):
    result = _pytest_session(tmp_path, '''
        import socket
        import sys
        import pytest

        @pytest.mark.live_net
        def test_live(monkeypatch):
            calls = []
            def fake_connect(sock, address):
                # Emit the same event as CPython's connect, then use a fake
                # transport. Proves guard opt-in without making a real request.
                sys.audit("socket.connect", sock, address)
                calls.append(address)
            monkeypatch.setattr(socket.socket, "connect", fake_connect)
            with socket.socket() as sock:
                sock.connect(("192.0.2.1", 443))
            assert calls == [("192.0.2.1", 443)]
    ''', "1")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "1 passed" in result.stdout


def test_loopback_and_unix_are_allowed(tmp_path):
    result = _pytest_session(tmp_path, '''
        import socket
        import sys

        def test_local():
            for host, family in [("127.0.0.1", socket.AF_INET), ("::1", socket.AF_INET6)]:
                with socket.socket(family) as server, socket.socket(family) as client:
                    server.settimeout(1)
                    client.settimeout(1)
                    server.bind((host, 0))
                    server.listen(1)
                    client.connect(server.getsockname())
                    with server.accept()[0] as accepted:
                        client.sendall(b"local")
                        assert accepted.recv(5) == b"local"
            assert socket.getaddrinfo("localhost", 443)
            left, right = socket.socketpair()
            with left, right:
                sys.audit("socket.connect", left, "/fake-local-socket")
                left.sendall(b"unix")
                assert right.recv(4) == b"unix"
            # Other loopback spellings use synthetic events, no I/O.
            with socket.socket(socket.AF_INET6) as sock:
                sys.audit("socket.connect", sock, ("::ffff:127.0.0.1", 443))
    ''')
    assert result.returncode == 0, result.stdout + result.stderr
    assert "1 passed" in result.stdout
