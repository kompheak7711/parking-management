"""Login sub-slice L7c: the local run on the Mac mini (owner answers (a) to Q-2026-10-21-155 and
Q-2026-10-21-159; technical points Q-2026-10-24-189). The scripts of `scripts/local` pass no
secret as a command argument and print none; the helper opens the root-only key file and runs
one command as the sudo user with only that key descriptor."""

from __future__ import annotations

import ast
import os
import pwd
import shutil
import stat
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Final

import pytest

from property_rental.bootstrap_cli import _parser

REPOSITORY_ROOT: Final = Path(__file__).resolve().parents[2]
LOCAL_SCRIPTS: Final = REPOSITORY_ROOT / "scripts" / "local"
HELPER: Final = LOCAL_SCRIPTS / "with-protected-key.py"
NOBODY: Final = 65534
running_as_root = pytest.mark.skipif(
    os.geteuid() != 0, reason="the helper's privilege drop can only be tried as root"
)


@pytest.fixture
def copied_repository(tmp_path: Path) -> Iterator[Path]:
    """A copy of the local scripts and the blocklist in a throwaway repository folder."""
    shutil.copytree(LOCAL_SCRIPTS, tmp_path / "scripts" / "local")
    (tmp_path / "config").mkdir()
    shutil.copy(REPOSITORY_ROOT / "config" / "password-blocklist.txt", tmp_path / "config")
    yield tmp_path


def test_every_local_script_parses_and_reads_secrets_only_from_files() -> None:
    scripts = sorted(LOCAL_SCRIPTS.glob("*.sh"))
    assert {script.name for script in scripts} == {
        "bootstrap-owner.sh",
        "common.sh",
        "database.sh",
        "make-certificate.sh",
        "make-secrets.sh",
        "migrate.sh",
        "start-api.sh",
    }
    for script in scripts:
        assert subprocess.run(["sh", "-n", str(script)], check=False).returncode == 0
        text = script.read_text(encoding="utf-8")
        # No secret value in a command line: database addresses are read into the process
        # (`read -r`) or opened as descriptors, never expanded from `cat` into an argument.
        assert "$(cat" not in text
        assert "`cat" not in text
        assert "set -x" not in text
    start_api = (LOCAL_SCRIPTS / "start-api.sh").read_text(encoding="utf-8")
    assert 'IFS= read -r APP_DATABASE_URL < "$PRM_SECRETS/runtime_database_url"' in start_api
    assert "APP_ENVIRONMENT=production" in start_api
    assert "APP_TOTP_KEY_FILE=/dev/fd/4" in start_api
    assert "--host 127.0.0.1 --port 8000" in start_api
    bootstrap = (LOCAL_SCRIPTS / "bootstrap-owner.sh").read_text(encoding="utf-8")
    assert '3< "$PRM_SECRETS/bootstrap_database_url"' in bootstrap
    assert '5< "$PRM_BLOCKLIST"' in bootstrap


def test_the_secrets_script_makes_private_files_and_prints_no_secret(
    copied_repository: Path,
) -> None:
    script = copied_repository / "scripts" / "local" / "make-secrets.sh"
    first = subprocess.run(
        ["sh", str(script)],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "POSTGRES_PORT": "5433"},
    )
    assert first.returncode == 0, first.stderr
    secrets = copied_repository / ".local" / "secrets"
    assert stat.S_IMODE(secrets.stat().st_mode) == 0o700
    names = "admin migration runtime financial backup restore human_admin bootstrap".split()
    passwords = {}
    for name in names:
        file = secrets / f"postgres_{name}_password"
        # The database container reads it as its own postgres user; the 0700 folder keeps it
        # private on the Mac.
        assert stat.S_IMODE(file.stat().st_mode) == 0o444
        passwords[name] = file.read_text(encoding="utf-8").strip()
        assert len(passwords[name]) == 48
    assert len(set(passwords.values())) == 8
    roles = {"migration": "prm_migrator", "runtime": "prm_runtime"}
    roles |= {"financial": "prm_financial", "bootstrap": "prm_bootstrap"}
    for name, role in roles.items():
        address = secrets / f"{name}_database_url"
        assert stat.S_IMODE(address.stat().st_mode) == 0o600
        expected = f"postgresql://{role}:{passwords[name]}@127.0.0.1:5433/prm\n"
        assert address.read_text(encoding="utf-8") == expected
    for password in passwords.values():
        assert password not in first.stdout + first.stderr

    # A second run keeps every file as it is.
    before = {file.name: file.read_bytes() for file in secrets.iterdir()}
    second = subprocess.run(["sh", str(script)], capture_output=True, text=True, check=False)
    assert second.returncode == 0, second.stderr
    assert {file.name: file.read_bytes() for file in secrets.iterdir()} == before
    assert "made: 0 of 8" in second.stdout


@pytest.mark.skipif(shutil.which("openssl") is None, reason="openssl is not installed")
def test_the_certificate_covers_the_local_name_and_localhost_and_chains_to_the_local_authority(
    copied_repository: Path,
) -> None:
    script = copied_repository / "scripts" / "local" / "make-certificate.sh"
    result = subprocess.run(
        ["sh", str(script)],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "PRM_LOCAL_HOSTNAME": "office-mac"},
    )
    assert result.returncode == 0, result.stderr
    folder = copied_repository / ".local" / "https"
    for name in ("local-ca-key.pem", "server-key.pem"):
        assert stat.S_IMODE((folder / name).stat().st_mode) == 0o600
        assert (folder / name).read_text(encoding="ascii") not in result.stdout
    text = subprocess.run(
        ["openssl", "x509", "-in", str(folder / "server.pem"), "-noout", "-text"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert "DNS:office-mac.local, DNS:localhost, IP Address:127.0.0.1" in text
    assert "TLS Web Server Authentication" in text
    assert "CA:FALSE" in text
    verified = subprocess.run(
        ["openssl", "verify", "-CAfile", str(folder / "local-ca.pem"), str(folder / "server.pem")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert verified.returncode == 0, verified.stderr

    refused = subprocess.run(
        ["sh", str(script)],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "PRM_LOCAL_HOSTNAME": "office mac;rm"},
    )
    assert refused.returncode == 1
    assert "not usable" in refused.stderr


def test_the_local_address_is_lower_case_as_browsers_send_it(copied_repository: Path) -> None:
    common = copied_repository / "scripts" / "local" / "common.sh"
    result = subprocess.run(
        ["sh", "-c", '. "$0"; prm_origin', str(common)],
        capture_output=True,
        text=True,
        check=True,
        env={**os.environ, "PRM_LOCAL_HOSTNAME": "Soks-Mac-mini"},
    )
    assert result.stdout == "https://soks-mac-mini.local:5173\n"

    # A name the API could never match is refused before the API starts (review round 2).
    refused = subprocess.run(
        ["sh", "-c", '. "$0"; prm_origin', str(common)],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "PRM_LOCAL_HOSTNAME": "Soks Mac"},
    )
    assert refused.returncode != 0
    assert refused.stdout == ""
    assert "not usable" in refused.stderr


def test_the_inner_parts_refuse_to_start_without_the_key_descriptor(
    copied_repository: Path,
) -> None:
    script = copied_repository / "scripts" / "local" / "start-api.sh"
    environment = {k: v for k, v in os.environ.items() if k != "PRM_PROTECTED_KEY_FD"}
    # Without the helper's variable, and with the variable but no descriptor 4 open (review
    # round 2): both refused before any address file is read.
    for extra in ({}, {"PRM_PROTECTED_KEY_FD": "4"}):
        result = subprocess.run(
            ["sh", str(script), "--inner", "/bin/false", "https://office-mac.local:5173"],
            capture_output=True,
            text=True,
            check=False,
            env={**environment, **extra},
        )
        assert result.returncode == 1
        assert "Start it with: sh scripts/local/start-api.sh" in result.stderr
        # The Owner set-up's inner part checks the same (review round 3).
        bootstrap = copied_repository / "scripts" / "local" / "bootstrap-owner.sh"
        result = subprocess.run(
            ["sh", str(bootstrap), "--inner", "/bin/false", "--username", "owner"],
            capture_output=True,
            text=True,
            check=False,
            env={**environment, **extra},
        )
        assert result.returncode == 1
        assert "Start it with: sh scripts/local/bootstrap-owner.sh" in result.stderr


def test_the_owner_set_up_refuses_the_options_it_sets_itself(copied_repository: Path) -> None:
    script = copied_repository / "scripts" / "local" / "bootstrap-owner.sh"
    for option in ("--totp-key-fd=9", "--database-url-fd", "--ceremony-timeout-seconds=60"):
        controller, terminal = os.openpty()
        try:
            result = subprocess.run(
                ["sh", str(script), "--username", "owner", option],
                stdin=terminal,
                stdout=terminal,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )
        finally:
            os.close(controller)
            os.close(terminal)
        assert result.returncode == 1
        assert "is set by this script" in result.stderr
    # The set-up itself takes no shortened option, which could slip past that check.
    with pytest.raises(SystemExit):
        _parser().parse_args(["--username", "o", "--totp-key-f", "9"])


def test_the_helper_is_python_3_9_syntax_for_macos() -> None:
    ast.parse(HELPER.read_text(encoding="utf-8"), feature_version=(3, 9))
    assert HELPER.read_text(encoding="utf-8").startswith("#!/usr/bin/python3 -I\n")


def test_the_owner_set_up_refuses_to_run_without_a_terminal(copied_repository: Path) -> None:
    script = copied_repository / "scripts" / "local" / "bootstrap-owner.sh"
    result = subprocess.run(
        ["sh", str(script), "--username", "owner"],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    assert "Run it in Terminal" in result.stderr


def run_helper(
    key: Path,
    *command: str,
    uid: int = NOBODY,
    gid: int = NOBODY,
    fd: int = 4,
    pass_fds: tuple[int, ...] = (),
) -> subprocess.CompletedProcess[str]:
    environment = {
        "PATH": "/usr/bin:/bin",
        "SUDO_UID": str(uid),
        "SUDO_GID": str(gid),
        "USERNAME": "root",
        "MAIL": "/var/mail/root",
    }
    return subprocess.run(
        [sys.executable, "-I", str(HELPER), "--key", str(key), "--fd", str(fd), "--", *command],
        capture_output=True,
        text=True,
        check=False,
        env=environment,
        pass_fds=pass_fds,
    )


@pytest.fixture
def protected_key(tmp_path: Path) -> Path:
    folder = tmp_path / "keys"
    folder.mkdir(mode=0o755)
    key = folder / "totp_protection_key"
    key.write_text("ab" * 32 + "\n", encoding="ascii")
    os.chmod(key, 0o600)
    os.chmod(tmp_path, 0o755)
    return key


@running_as_root
def test_the_helper_runs_the_command_as_the_sudo_user_with_only_the_key_descriptor(
    protected_key: Path,
) -> None:
    probe = (
        "import os,sys;"
        "print(os.getuid(),os.geteuid(),os.getgid());"
        "print(os.environ['PRM_PROTECTED_KEY_FD'],os.environ['USER'],os.environ['HOME']);"
        "print(len(os.read(4,128)));"
        "print(sorted(int(n) for n in os.listdir('/proc/self/fd')));"
        "print(sorted(k for k in os.environ if k.startswith('SUDO_') or k in ('USERNAME','MAIL')));"
        "print(sorted(os.getgroups()), os.environ['SHELL'])"
    )
    # Another descriptor is passed on to the helper too (as sudo might leave one): it closes it.
    with open(protected_key.parent.parent / "other", "w", encoding="ascii") as other:
        assert other.fileno() > 4
        result = run_helper(
            protected_key, sys.executable, "-I", "-c", probe, pass_fds=(other.fileno(),)
        )
    assert result.returncode == 0, result.stderr
    lines = result.stdout.splitlines()
    assert lines[0] == f"{NOBODY} {NOBODY} {NOBODY}"
    assert lines[1].split()[:2] == ["4", "nobody"]
    assert lines[2] == "65"
    # 0, 1 and 2, the key on 4, and 3, the descriptor `listdir` itself opened: nothing else.
    assert lines[3] == "[0, 1, 2, 3, 4]"
    assert lines[4] == "[]"
    nobody = pwd.getpwuid(NOBODY)
    groups = sorted(set(os.getgrouplist(nobody.pw_name, NOBODY)))
    assert lines[5] == f"{groups} {nobody.pw_shell}"
    assert "ab" * 32 not in result.stdout + result.stderr


@running_as_root
def test_the_helper_refuses_an_unprotected_key_root_itself_a_missing_sudo_user_and_other_files(
    protected_key: Path,
) -> None:
    os.chmod(protected_key, 0o640)
    refused = run_helper(protected_key, "/bin/true")
    assert refused.returncode == 1
    assert "only root can read" in refused.stderr
    os.chmod(protected_key, 0o600)
    os.chown(protected_key, NOBODY, NOBODY)
    refused = run_helper(protected_key, "/bin/true")
    assert refused.returncode == 1
    assert "only root can read" in refused.stderr
    os.chown(protected_key, 0, 0)

    refused = run_helper(protected_key, "/bin/true", uid=0)
    assert refused.returncode == 1
    assert "not from root" in refused.stderr

    missing = subprocess.run(
        [sys.executable, "-I", str(HELPER), "--key", str(protected_key), "--fd", "4", "--", "true"],
        capture_output=True,
        text=True,
        check=False,
        env={"PATH": "/usr/bin:/bin"},
    )
    assert missing.returncode == 1
    assert "with sudo from your own account" in missing.stderr

    for fd in ("2", "10"):
        refused = run_helper(protected_key, "/bin/true", fd=int(fd))
        assert refused.returncode == 1
        assert "--fd must be between 3 and 9" in refused.stderr

    # Only a file called totp_protection_key: the helper cannot pass on another root-only file.
    other = protected_key.with_name("other_root_only_file")
    other.write_text("not a key\n", encoding="ascii")
    os.chmod(other, 0o600)
    refused = run_helper(other, "/bin/cat", "/dev/fd/4")
    assert refused.returncode == 1
    assert "must name a file called totp_protection_key" in refused.stderr
    assert "not a key" not in refused.stdout

    # Nor under that name: a hard link, a symbolic link, a folder, or a folder others can change.
    elsewhere = protected_key.parent.parent / "elsewhere"
    elsewhere.mkdir(mode=0o755)
    linked = elsewhere / "totp_protection_key"
    os.link(other, linked)
    refused = run_helper(linked, "/bin/cat", "/dev/fd/4")
    assert refused.returncode == 1
    assert "only root can read" in refused.stderr
    assert "not a key" not in refused.stdout
    linked.unlink()
    linked.symlink_to(other)
    refused = run_helper(linked, "/bin/cat", "/dev/fd/4")
    assert refused.returncode == 1
    assert "cannot be opened" in refused.stderr
    linked.unlink()
    linked.mkdir()
    refused = run_helper(linked, "/bin/true")
    assert refused.returncode == 1
    assert "only root can read" in refused.stderr
    os.chmod(protected_key.parent, 0o777)
    refused = run_helper(protected_key, "/bin/true")
    os.chmod(protected_key.parent, 0o755)
    assert refused.returncode == 1
    assert "folder only root can change" in refused.stderr

    refused = run_helper(protected_key, "/bin/true", gid=NOBODY - 1)
    assert refused.returncode == 1
    assert "group does not match" in refused.stderr


def test_the_helper_refuses_to_run_without_root() -> None:
    command = [sys.executable, "-I", str(HELPER), "--fd", "4", "--", "/bin/true"]
    if os.geteuid() == 0:
        if shutil.which("setpriv") is None:
            pytest.skip("setpriv is not installed")
        command = ["setpriv", f"--reuid={NOBODY}", f"--regid={NOBODY}", "--clear-groups"]
        command += [sys.executable, "-I", str(HELPER), "--fd", "4", "--", "/bin/true"]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    assert result.returncode == 1
    assert "run it with sudo" in result.stderr
