"""Pinned CLI transport. No credentials, account discovery or implicit dispatch.

Only a separately authorized preflight caller may invoke this transport. The
public preflight CLI never does so. Tests inject a fake subprocess runner.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import stat
import subprocess

from qlab.dynamic_factor.contract import is_sha
from qlab.shadow15k.ledger import FORBIDDEN, FORBIDDEN_LINE

from .contract import BINDINGS, bindings, canonical, digest, sha

DEFAULT_VERSION = "2.1.306"
DEFAULT_BINARY_SHA = "b5d795b7760032d79954b55a9cd1876dcf3a8dc9608fd6bb9f618593f69fd44b"
DEFAULT_APPROVAL_SHA = BINDINGS["EVO896-prereg-LLMCLI-v0.1.2.json"]
# Category checks plus a closed allowlist: unknown future variables cannot
# accidentally opt a child into a paid route. Never inspect their values.
DENIED_ENV_CATEGORIES = {
    "api_key": re.compile(r"API_?KEY", re.I),
    "authentication": re.compile(r"TOKEN|SECRET|PASSWORD|CREDENTIAL|AUTH", re.I),
    "service_routing": re.compile(r"BASE_?URL|ENDPOINT|PROXY|GATEWAY|SERVER|HOST|ROUTE", re.I),
    "cloud_provider": re.compile(r"AWS|AMAZON|AZURE|GOOGLE|GCLOUD|VERTEX|BEDROCK|FOUNDRY|USE_", re.I),
}


class LaunchRejected(ValueError):
    """Only fixed, non-sensitive gate reasons may enter a public manifest."""

    REASONS = {
        "metered_route_environment_forbidden", "unapproved_child_environment",
        "updates_not_disabled", "bare_forbidden", "settings_sources_must_be_empty",
        "separate_dispatch_authorization_required",
        "isolated_config_not_verified",
    }

    def __init__(self, code):
        if code not in self.REASONS:
            raise ValueError("launcher.invalid_rejection_code")
        self.code = code
        super().__init__("launcher." + code)


@dataclass(frozen=True)
class BinaryBinding:
    executable: Path
    isolated_root: Path
    version: str = DEFAULT_VERSION
    binary_sha256: str = DEFAULT_BINARY_SHA
    approval_sha256: str = DEFAULT_APPROVAL_SHA

    def manifest(self):
        if (
            not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", self.version)
            or not is_sha(self.binary_sha256)
            or not is_sha(self.approval_sha256)
        ):
            raise ValueError("launcher.invalid_binding")
        # Paths are local-only; public manifests contain only their digest.
        return dict(
            cli_version=self.version,
            binary_sha256=self.binary_sha256,
            binding_approval_sha256=self.approval_sha256,
            binary_location_sha256=sha(
                str(self.executable).encode() + b"\0" + str(self.isolated_root).encode()
            ),
        )

    def fingerprint(self):
        self.manifest()
        path, root = Path(self.executable), Path(self.isolated_root)
        # Check containment before reading even one byte. Never inspect the
        # installed CLI, credential/configuration locations or a linked file.
        forbidden = {".local", ".claude", ".codex", ".config", ".git"}
        if (
            not path.is_absolute()
            or not root.is_absolute()
            or root not in path.parents
            or path.name != "claude"
            or forbidden.intersection(path.parts)
            or FORBIDDEN.intersection(p.lower() for p in path.parts)
            or any(FORBIDDEN_LINE.search(p) for p in path.parts)
            or path != path.resolve()
            or root != root.resolve()
            or any(p.is_symlink() for p in [path, *path.parents])
        ):
            raise ValueError("launcher.isolated_binary_required")
        info = path.stat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ValueError("launcher.regular_binary_required")
        actual = sha(path.read_bytes())
        if actual != self.binary_sha256:
            raise ValueError("launcher.binary_sha_mismatch")
        return actual


@dataclass(frozen=True)
class ConfigBinding:
    """An externally approved isolation identity, never an auth-store installer.

    Approval validation belongs to the trusted authority adapter. The launcher
    independently checks this exact canonical root, real path and directory
    identity before each subprocess. No directory contents are read here.
    """

    root: Path
    directory: Path
    realpath: Path
    identity_sha256: str
    approval_sha256: str

    def manifest(self):
        if not is_sha(self.identity_sha256) or not is_sha(self.approval_sha256):
            raise LaunchRejected("isolated_config_not_verified")
        return dict(
            root_sha256=sha(str(self.root).encode()),
            directory_sha256=sha(str(self.directory).encode()),
            realpath_sha256=sha(str(self.realpath).encode()),
            identity_sha256=self.identity_sha256, approval_sha256=self.approval_sha256,
        )

    def verify(self, selected):
        self.manifest()
        root, directory, realpath = map(Path, (self.root, self.directory, self.realpath))
        shared = [
            Path.home() / ".claude", Path.home() / ".config",
            Path.home() / "Library" / "Application Support" / "Claude",
        ]
        root_name, directory_name = str(root).casefold(), str(directory).casefold()
        # Reject shared paths lexically, without opening or resolving them.
        if (
            selected is None or Path(selected) != directory
            or not all(p.is_absolute() for p in (root, directory, realpath))
            or root not in directory.parents or realpath != directory
            or any(
                str(p).casefold() == root_name
                or str(p).casefold().startswith(root_name.rstrip("/") + "/")
                or str(p).casefold() == directory_name
                or directory_name.startswith(str(p).casefold() + "/")
                for p in shared
            )
            or FORBIDDEN.intersection(p.lower() for p in directory.parts)
            or any(FORBIDDEN_LINE.search(p) for p in directory.parts)
        ):
            raise LaunchRejected("isolated_config_not_verified")
        try:
            if (
                root != root.resolve(strict=True)
                or directory != directory.resolve(strict=True)
                or any(p.is_symlink() for p in [directory, *directory.parents])
            ):
                raise LaunchRejected("isolated_config_not_verified")
            identities = []
            for path in (root, directory):
                info = path.lstat()
                if not stat.S_ISDIR(info.st_mode) or info.st_mode & 0o077:
                    raise LaunchRejected("isolated_config_not_verified")
                identities.append(dict(device=info.st_dev, inode=info.st_ino))
            if digest(identities) != self.identity_sha256:
                raise LaunchRejected("isolated_config_not_verified")
        except (OSError, RuntimeError):
            raise LaunchRejected("isolated_config_not_verified") from None
        return str(realpath)


def candidate_argv(binding, prompt, schema):
    """Preserve every frozen flag; nonexistent flags need a reviewed revision."""
    binding.manifest()
    replacements = {
        "<verified_exact_claude_binary>": str(binding.executable),
        "<exact_prompt_file_UTF8>": prompt.decode("utf-8"),
        "<exact_schema_file_UTF8>": schema.decode("utf-8"),
    }
    return [
        replacements.get(arg, arg)
        for arg in bindings()["model_binding"]["candidate_argv_template"]
    ]


def child_environment(workdir, *, config_dir=None):
    """Empty private HOME: no inherited keys, helpers, gateways or user settings.

    Existing-subscription authentication in isolation is deliberately unresolved
    here; evidence B and separate dispatch authorization must resolve it first.
    """
    if config_dir is None or not Path(config_dir).is_absolute():
        raise ValueError("launcher.config_location_must_be_explicit")
    root = Path(workdir).absolute()
    if root != root.resolve() or any(p.is_symlink() for p in [root, *root.parents]):
        raise ValueError("launcher.private_workdir_required")
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    home, temp = root / "home", root / "tmp"
    for path in (home, temp):
        if path.exists() or path.is_symlink():
            raise ValueError("launcher.fresh_workdir_required")
        path.mkdir(mode=0o700)
    return {
        "HOME": str(home),
        "TMPDIR": str(temp),
        "PATH": "/usr/bin:/bin",
        "DISABLE_UPDATES": "1",
        "DISABLE_AUTOUPDATER": "1",
        # Only pass the location. Do not open/copy/create a supplied auth store.
        "CLAUDE_CONFIG_DIR": str(config_dir),
    }


def verify_launch_configuration(argv, env):
    """Chief 01a1e011-0381 layer 1: reject metered routes before any spawn."""
    allowed = {
        "HOME", "TMPDIR", "PATH", "DISABLE_UPDATES", "DISABLE_AUTOUPDATER",
        "CLAUDE_CONFIG_DIR",
    }
    if any(pattern.search(key) for pattern in DENIED_ENV_CATEGORIES.values() for key in env):
        raise LaunchRejected("metered_route_environment_forbidden")
    if set(env) != allowed or any(not isinstance(v, str) for v in env.values()):
        raise LaunchRejected("unapproved_child_environment")
    if env["DISABLE_UPDATES"] != "1" or env["DISABLE_AUTOUPDATER"] != "1":
        raise LaunchRejected("updates_not_disabled")
    if "--bare" in argv or any(a.startswith("--bare=") for a in argv):
        raise LaunchRejected("bare_forbidden")
    sources = []
    for index, arg in enumerate(argv):
        if arg == "--setting-sources":
            sources.append(argv[index + 1] if index + 1 < len(argv) else None)
        elif arg.startswith("--setting-sources="):
            sources.append(arg.split("=", 1)[1])
    if sources != [""] or any(a == "--settings" or a.startswith("--settings=") for a in argv):
        raise LaunchRejected("settings_sources_must_be_empty")


@dataclass(frozen=True)
class LaunchResult:
    stdout: bytes
    stderr: bytes
    returncode: object
    timed_out: bool
    binary_before_sha256: str
    binary_after_sha256: object
    cli_version_before: str
    cli_version_after: object


class SubprocessLauncher:
    def __init__(
        self, binding, *, runner=None, timeout_seconds=60, config_dir=None,
        config_binding=None,
    ):
        if type(timeout_seconds) is not int or not 1 <= timeout_seconds <= 300:
            raise ValueError("launcher.bounded_timeout_required")
        self.binding = binding
        self.runner = runner if runner is not None else subprocess.run
        self.timeout = timeout_seconds
        if config_dir is not None and not Path(config_dir).is_absolute():
            raise ValueError("launcher.absolute_config_location_required")
        self.config_dir = config_dir
        if config_binding is not None and not isinstance(config_binding, ConfigBinding):
            raise LaunchRejected("isolated_config_not_verified")
        self.config_binding = config_binding

    @staticmethod
    def _verify_config(config, selected, env=None):
        if not isinstance(config, ConfigBinding):
            raise LaunchRejected("isolated_config_not_verified")
        realpath = config.verify(selected)
        if env is not None and env.get("CLAUDE_CONFIG_DIR") != realpath:
            raise LaunchRejected("isolated_config_not_verified")
        return realpath

    def _version(self, cwd, env, config, selected):
        self._verify_config(config, selected, env)
        result = self.runner(
            [str(self.binding.executable), "--version"],
            input=b"", capture_output=True, timeout=5, check=False,
            cwd=str(cwd), env=env, shell=False,
        )
        expected = (self.binding.version + " (Claude Code)").encode()
        if result.returncode != 0 or result.stdout.strip() != expected:
            raise ValueError("launcher.cli_version_mismatch")
        return self.binding.version

    def launch(self, *, prompt, schema, input_bytes, workdir, authorize=None):
        plan_sha = digest(self.plan(prompt, schema))
        if not callable(authorize) or authorize(plan_sha) is not True:
            raise LaunchRejected("separate_dispatch_authorization_required")
        config, selected = self.config_binding, self.config_dir
        real_config = self._verify_config(config, selected)
        before = self.binding.fingerprint()
        env = child_environment(workdir, config_dir=real_config)
        argv = candidate_argv(self.binding, prompt, schema)
        verify_launch_configuration(argv, env)
        version_before = self._version(workdir, env, config, selected)
        self.binding.fingerprint()
        self._verify_config(config, selected, env)
        # The caller must archive its dispatch claim before entering this method.
        try:
            process = self.runner(
                argv, input=input_bytes, capture_output=True, timeout=self.timeout,
                check=False, cwd=str(workdir), env=env, shell=False,
            )
            stdout, stderr, code, timed_out = (
                process.stdout, process.stderr, process.returncode, False
            )
        except subprocess.TimeoutExpired as exc:
            stdout, stderr, code, timed_out = (
                exc.stdout or b"", exc.stderr or b"", None, True
            )
        # Preserve captured output even when the after-check fails.
        after, version_after = None, None
        try:
            after = self.binding.fingerprint()
            version_after = self._version(workdir, env, config, selected)
        except (OSError, ValueError, subprocess.SubprocessError):
            pass
        return LaunchResult(
            stdout, stderr, code, timed_out, before, after,
            version_before, version_after,
        )

    def plan(self, prompt, schema):
        return dict(
            binding=self.binding.manifest(),
            argv_sha256=digest(candidate_argv(self.binding, prompt, schema)),
            stdin_transport="bytes",
            shell=False,
            timeout_seconds=self.timeout,
            inherited_environment=False,
            config_location_sha256=(
                sha(str(self.config_dir).encode()) if self.config_dir is not None else None
            ),
            config_isolation_binding=(
                self.config_binding.manifest() if self.config_binding is not None else None
            ),
            context_input_sha256=sha(canonical(dict(
                system_prompt_sha256=sha(prompt), output_schema_sha256=sha(schema),
                tools=[], mcp_servers={},
            ))),
        )
