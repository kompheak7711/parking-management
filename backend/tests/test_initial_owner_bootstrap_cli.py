"""Focused deterministic tests for the protected initial Owner bootstrap CLI service."""

from __future__ import annotations

import os
import stat
import threading
import time
import tty
from dataclasses import dataclass, field, replace
from types import SimpleNamespace
from typing import cast
from uuid import UUID

import pytest
from starlette.routing import BaseRoute

import property_rental.bootstrap_cli as bootstrap_cli
from property_rental.app import create_app
from property_rental.initial_owner_bootstrap import (
    BOOTSTRAP_ACKNOWLEDGEMENT,
    RECOVERY_CODE_COUNT,
    BootstrapFailed,
    BootstrapPasswordPolicy,
    BootstrapRequest,
    BootstrapSecretBundle,
    InitialOwnerBootstrapService,
)
from property_rental.settings import Settings
from property_rental.totp_security import TotpSecret, TotpService


@dataclass
class RecordingRepository:
    open: bool = True
    establish_success: bool = True
    fail_commit: bool = False
    events: list[str] = field(default_factory=list)
    persisted: BootstrapSecretBundle | None = None
    statement_timeouts: list[int] = field(default_factory=list)

    def begin_attempt(self, request: BootstrapRequest) -> bool:
        self.events.append("begin")
        return self.open

    def establish(
        self,
        request: BootstrapRequest,
        bundle: BootstrapSecretBundle,
        *,
        timeout_milliseconds: int,
    ) -> bool:
        self.events.append("establish")
        self.persisted = bundle
        self.statement_timeouts.append(timeout_milliseconds)
        return self.establish_success

    def commit(self) -> None:
        self.events.append("commit")
        if self.fail_commit:
            raise RuntimeError("simulated commit failure")

    def rollback(self) -> None:
        self.events.append("rollback")


@dataclass
class RecordingTerminal:
    password: str = "correct horse battery staple"
    totp_code: str = "123456"
    acknowledgement: str = BOOTSTRAP_ACKNOWLEDGEMENT
    fail_presentation: bool = False
    events: list[str] = field(default_factory=list)
    presented_codes: tuple[str, ...] | None = None
    deadlines: list[float] = field(default_factory=list)

    def read_password(self) -> str:
        self.events.append("password")
        return self.password

    def present_totp_and_read_code(self, secret: str, *, deadline: float) -> str:
        assert secret == "TOTP-SECRET"
        self.deadlines.append(deadline)
        self.events.append("totp")
        return self.totp_code

    def present_recovery_codes(self, codes: tuple[str, ...], *, deadline: float) -> None:
        self.deadlines.append(deadline)
        self.events.append("recovery")
        self.presented_codes = codes
        if self.fail_presentation:
            raise OSError("tty unavailable")

    def read_acknowledgement(self, *, deadline: float) -> str:
        self.deadlines.append(deadline)
        self.events.append("ack")
        return self.acknowledgement


class DeterministicMaterialFactory:
    def create(
        self, *, request: BootstrapRequest, normalized_password: str
    ) -> BootstrapSecretBundle:
        del request
        assert normalized_password == "correct horse battery staple"
        return BootstrapSecretBundle(
            password_verifier="password-verifier",
            password_algorithm="argon2id",
            password_work_factors={"time_cost": 3},
            totp_plaintext="TOTP-SECRET",
            totp_ciphertext=b"ciphertext" * 4,
            totp_nonce=b"n" * 12,
            totp_key_identifier="bootstrap-test-key",
            recovery_plaintexts=tuple(f"recovery-{index}" for index in range(RECOVERY_CODE_COUNT)),
            recovery_verifiers=tuple(f"verifier-{index}" for index in range(RECOVERY_CODE_COUNT)),
            recovery_algorithm="argon2id",
            recovery_work_factors={"time_cost": 3},
        )

    def verify_totp(self, bundle: BootstrapSecretBundle, candidate: str) -> bool:
        del bundle
        return candidate == "123456"


REQUEST = BootstrapRequest(
    actor_id=UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"),
    correlation_id=UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"),
    enrollment_id=UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc"),
    recovery_set_id=UUID("dddddddd-dddd-4ddd-8ddd-dddddddddddd"),
    recovery_code_ids=tuple(UUID(int=index + 10) for index in range(RECOVERY_CODE_COUNT)),
    username="owner",
    display_name="Initial Owner",
    audit_name="initial-owner",
)


def _service(
    repository: RecordingRepository, terminal: RecordingTerminal
) -> InitialOwnerBootstrapService:
    return InitialOwnerBootstrapService(
        repository=repository,
        terminal=terminal,
        password_policy=BootstrapPasswordPolicy(
            blocked_passwords={"password", "property-rental-management"}
        ),
        material_factory=DeterministicMaterialFactory(),
        ceremony_timeout_seconds=30,
    )


@pytest.mark.parametrize(
    "password",
    ["x" * 14, "x" * 129, "password", "Property-Rental-Management", "owner"],
)
def test_password_policy_rejects_length_blocklist_and_project_context(password: str) -> None:
    policy = BootstrapPasswordPolicy(blocked_passwords={"password", "property-rental-management"})

    with pytest.raises(ValueError, match="bootstrap password rejected") as failure:
        policy.accept(password, context=("owner", "Initial Owner"))

    assert str(failure.value) == "bootstrap password rejected"


def test_password_policy_accepts_boundaries_spaces_and_nfc_without_composition_rules() -> None:
    policy = BootstrapPasswordPolicy(blocked_passwords=set())
    decomposed = "e\u0301" + " phrase with spaces 9!"  # 24 code points before NFC.

    accepted = policy.accept(decomposed, context=("owner",))

    assert accepted.startswith("é")
    assert len(policy.accept("x" * 15, context=())) == 15
    assert len(policy.accept("x" * 128, context=())) == 128
    assert (
        policy.accept("all lowercase words are allowed", context=())
        == "all lowercase words are allowed"
    )


@pytest.mark.parametrize(
    "password",
    [
        "e\u0301" + "x" * 13,
        "e\u0301" * 64 + "x",
    ],
)
def test_password_policy_revalidates_nfc_result_without_waiving_supplied_length(
    password: str,
) -> None:
    policy = BootstrapPasswordPolicy(blocked_passwords=set())

    with pytest.raises(ValueError, match=r"^bootstrap password rejected$"):
        policy.accept(password, context=())


def test_password_policy_blocks_the_complete_untruncated_128_code_point_value() -> None:
    blocked = "x" * 127 + "y"
    policy = BootstrapPasswordPolicy(blocked_passwords={blocked})

    with pytest.raises(ValueError, match="bootstrap password rejected"):
        policy.accept(blocked, context=())

    assert policy.accept("x" * 128, context=()) == "x" * 128


def test_success_persists_then_presents_exactly_ten_codes_and_acknowledges_before_commit() -> None:
    repository = RecordingRepository()
    terminal = RecordingTerminal()

    _service(repository, terminal).run(REQUEST)

    assert repository.events == ["begin", "establish", "commit"]
    assert terminal.events == ["password", "totp", "recovery", "ack"]
    assert len(set(terminal.deadlines)) == 1
    assert len(repository.statement_timeouts) == 1
    assert 0 < repository.statement_timeouts[0] <= 30_000
    assert terminal.presented_codes == tuple(
        f"recovery-{index}" for index in range(RECOVERY_CODE_COUNT)
    )
    assert repository.persisted is not None
    assert "correct horse" not in repr(repository.persisted)
    assert "TOTP-SECRET" not in repr(repository.persisted)
    assert "recovery-0" not in repr(repository.persisted)


@pytest.mark.parametrize("failure_mode", ["presentation", "acknowledgement", "timeout", "totp"])
def test_presentation_acknowledgement_timeout_or_totp_failure_rolls_back_completely(
    failure_mode: str,
) -> None:
    repository = RecordingRepository()
    terminal = RecordingTerminal(
        fail_presentation=failure_mode == "presentation",
        acknowledgement=(
            "wrong" if failure_mode == "acknowledgement" else BOOTSTRAP_ACKNOWLEDGEMENT
        ),
        totp_code=("000000" if failure_mode == "totp" else "123456"),
    )
    if failure_mode == "timeout":
        terminal.acknowledgement = ""

    with pytest.raises(BootstrapFailed, match=r"^initial Owner bootstrap failed$") as failure:
        _service(repository, terminal).run(REQUEST)

    assert repository.events[-1] == "rollback"
    assert "recovery-0" not in repr(failure.value)
    assert failure.value.__cause__ is None


@pytest.mark.parametrize(
    "typed",
    [
        BOOTSTRAP_ACKNOWLEDGEMENT.lower(),
        "  " + BOOTSTRAP_ACKNOWLEDGEMENT.replace(" ", "   ") + "  ",
    ],
)
def test_acknowledgement_in_lower_case_or_with_extra_spaces_commits(typed: str) -> None:
    # Login L8 review: the sentence is compared without case and with runs of spaces made one.
    repository = RecordingRepository()
    terminal = RecordingTerminal(acknowledgement=typed)

    _service(repository, terminal).run(REQUEST)

    assert repository.events == ["begin", "establish", "commit"]


def _real_factory_bundle(now: float) -> tuple[bootstrap_cli.RealBootstrapMaterialFactory, str]:
    factory = bootstrap_cli.RealBootstrapMaterialFactory(
        totp_key=b"k" * 32, totp_key_identifier="bootstrap-test-key", clock=lambda: now
    )
    return factory, TotpSecret.from_bytes(b"s" * 20).get_base32_value()


def _bundle_with_totp(totp_plaintext: str) -> BootstrapSecretBundle:
    bundle = DeterministicMaterialFactory().create(
        request=REQUEST, normalized_password="correct horse battery staple"
    )
    return replace(bundle, totp_plaintext=totp_plaintext)


def test_set_up_code_of_this_or_the_previous_step_is_accepted_and_spaces_are_removed() -> None:
    # Login L8 review: as sign-in, a code read just before the 30-second step changes is accepted.
    now = 1_800_000_015.0
    factory, encoded = _real_factory_bundle(now)
    bundle = _bundle_with_totp(encoded)
    secret = TotpSecret.from_base32(encoded)
    service = TotpService()
    current = service.generate_code(secret, at_time=int(now))
    previous = service.generate_code(secret, at_time=int(now) - 30)
    older = service.generate_code(secret, at_time=int(now) - 60)
    following = service.generate_code(secret, at_time=int(now) + 30)
    assert len({current, previous, older, following}) == 4

    assert factory.verify_totp(bundle, current)
    assert factory.verify_totp(bundle, previous)
    assert factory.verify_totp(bundle, f"{current[:3]} {current[3:]}")
    assert factory.verify_totp(bundle, f" {previous} ")
    assert not factory.verify_totp(bundle, older)
    assert not factory.verify_totp(bundle, following)
    assert not factory.verify_totp(bundle, current[:5])
    assert not factory.verify_totp(bundle, "")


@pytest.mark.parametrize("failure_mode", ["establish", "commit"])
def test_establishment_or_commit_failure_rolls_back_without_secret_detail(
    failure_mode: str,
) -> None:
    repository = RecordingRepository(
        establish_success=failure_mode != "establish",
        fail_commit=failure_mode == "commit",
    )

    with pytest.raises(BootstrapFailed, match=r"^initial Owner bootstrap failed$") as failure:
        _service(repository, RecordingTerminal()).run(REQUEST)

    assert repository.events[-1] == "rollback"
    assert "recovery-0" not in repr(failure.value)
    assert failure.value.__cause__ is None


def test_ceremony_deadline_never_resets_and_timeout_before_commit_rolls_back() -> None:
    now = [100.0]

    class DeadlineRepository(RecordingRepository):
        def establish(
            self,
            request: BootstrapRequest,
            bundle: BootstrapSecretBundle,
            *,
            timeout_milliseconds: int,
        ) -> bool:
            assert timeout_milliseconds == 25_000
            now[0] = 115.0
            return super().establish(request, bundle, timeout_milliseconds=timeout_milliseconds)

    class DeadlineTerminal(RecordingTerminal):
        def present_totp_and_read_code(self, secret: str, *, deadline: float) -> str:
            assert deadline == 130.0
            now[0] = 105.0
            return super().present_totp_and_read_code(secret, deadline=deadline)

        def present_recovery_codes(self, codes: tuple[str, ...], *, deadline: float) -> None:
            assert deadline == 130.0
            now[0] = 120.0
            super().present_recovery_codes(codes, deadline=deadline)

        def read_acknowledgement(self, *, deadline: float) -> str:
            assert deadline == 130.0
            now[0] = 130.0
            return super().read_acknowledgement(deadline=deadline)

    repository = DeadlineRepository()
    terminal = DeadlineTerminal()
    service = InitialOwnerBootstrapService(
        repository=repository,
        terminal=terminal,
        password_policy=BootstrapPasswordPolicy(blocked_passwords=set()),
        material_factory=DeterministicMaterialFactory(),
        ceremony_timeout_seconds=30,
        monotonic_clock=lambda: now[0],
    )

    with pytest.raises(BootstrapFailed, match=r"^initial Owner bootstrap failed$"):
        service.run(REQUEST)

    assert terminal.deadlines == [130.0, 130.0, 130.0]
    assert repository.events == ["begin", "establish", "rollback"]


def test_closed_bootstrap_audits_through_preflight_without_reading_or_generating_secrets() -> None:
    repository = RecordingRepository(open=False)
    terminal = RecordingTerminal()

    with pytest.raises(BootstrapFailed, match=r"^initial Owner bootstrap failed$"):
        _service(repository, terminal).run(REQUEST)

    assert repository.events == ["begin", "commit"]
    assert terminal.events == []
    assert repository.persisted is None


def test_request_requires_exactly_ten_distinct_recovery_code_identifiers() -> None:
    with pytest.raises(ValueError, match="exactly 10"):
        BootstrapRequest(
            actor_id=REQUEST.actor_id,
            correlation_id=REQUEST.correlation_id,
            enrollment_id=REQUEST.enrollment_id,
            recovery_set_id=REQUEST.recovery_set_id,
            recovery_code_ids=(UUID(int=1),),
            username="owner",
            display_name="Owner",
            audit_name="owner",
        )


def test_request_refuses_a_username_that_sign_in_would_tidy() -> None:
    """DL-081, Q-2026-10-22-170 (a) (login sub-slice L2d review round 1, security): sign-in
    tidies the typed username, so the bootstrap refuses a username with two spaces in a row.
    Since login sub-slice L7b the bootstrap stores the sign-in form; the refusal stays, so the
    Owner signs in with what they typed."""

    def request_for(username: str) -> BootstrapRequest:
        return BootstrapRequest(
            actor_id=REQUEST.actor_id,
            correlation_id=REQUEST.correlation_id,
            enrollment_id=REQUEST.enrollment_id,
            recovery_set_id=REQUEST.recovery_set_id,
            recovery_code_ids=REQUEST.recovery_code_ids,
            username=username,
            display_name="Initial Owner",
            audit_name="initial-owner",
        )

    for refused in ("sokha  chan", "sokha\u00a0chan", " sokha chan"):
        with pytest.raises(ValueError, match="invalid initial Owner bootstrap identity"):
            request_for(refused)
    assert request_for("sokha chan").username == "sokha chan"


def test_request_refuses_a_username_whose_stored_form_would_not_be_nfc() -> None:
    """DL-081 (login sub-slice L7b review round 1): the bootstrap stores the lower-case sign-in
    form, and lower case can undo NFC: "J\u030cohn" is NFC, but its lower case "j\u030cohn" is
    not (NFC makes it "\u01f0ohn"). Account creation refuses such a name, so the bootstrap
    refuses it too; an NFC-safe accented name is still accepted."""

    def request_for(username: str) -> BootstrapRequest:
        return BootstrapRequest(
            actor_id=REQUEST.actor_id,
            correlation_id=REQUEST.correlation_id,
            enrollment_id=REQUEST.enrollment_id,
            recovery_set_id=REQUEST.recovery_set_id,
            recovery_code_ids=REQUEST.recovery_code_ids,
            username=username,
            display_name="Initial Owner",
            audit_name="initial-owner",
        )

    for refused in ("J\u030cohn", "W\u030aill"):
        with pytest.raises(ValueError, match="invalid initial Owner bootstrap identity"):
            request_for(refused)
    assert request_for("Sokha\u0301 Stra\u00dfe").username == "Sokha\u0301 Stra\u00dfe"


def test_request_refuses_names_that_account_creation_refuses() -> None:
    """DL-081 (login sub-slice L7b review round 2): the bootstrap applies the rest of the
    account name rule of account creation (`app.assert_account_names`): a hidden but printable
    character (U+3164 Hangul filler, which looks like nothing, or U+034F), more than 128
    characters in the stored username (100 dotted capital I become 200 after lower case), and a
    display or audit name that is not NFC, holds a hidden character or two spaces in a row
    (review round 3), are refused."""

    def request_for(
        username: str, display_name: str = "Initial Owner", audit_name: str = "initial-owner"
    ) -> BootstrapRequest:
        return BootstrapRequest(
            actor_id=REQUEST.actor_id,
            correlation_id=REQUEST.correlation_id,
            enrollment_id=REQUEST.enrollment_id,
            recovery_set_id=REQUEST.recovery_set_id,
            recovery_code_ids=REQUEST.recovery_code_ids,
            username=username,
            display_name=display_name,
            audit_name=audit_name,
        )

    for refused in (
        {"username": "admin\u3164"},
        {"username": "ad\u034fmin"},
        {"username": "\u0130" * 100},
        {"username": "o" * 129},
        {"username": "owner", "display_name": "Initial\u3164Owner"},
        {"username": "owner", "display_name": "Cafe\u0301"},
        {"username": "owner", "audit_name": "initial\u2800owner"},
        {"username": "owner", "display_name": "Sok  Pheak"},
        {"username": "owner", "audit_name": "Owner  X"},
    ):
        with pytest.raises(ValueError, match="invalid initial Owner bootstrap identity"):
            request_for(**refused)
    assert request_for("o" * 128).username == "o" * 128
    assert request_for("owner", display_name="Caf\u00e9").display_name == "Caf\u00e9"


def test_recovery_codes_are_written_to_the_dedicated_tty_descriptor_not_stdout(
    capsys: pytest.CaptureFixture[str],
) -> None:
    read_fd, write_fd = os.pipe()
    terminal = object.__new__(bootstrap_cli.ControllingTerminal)
    terminal._fd = write_fd
    codes = tuple(f"code-{index}" for index in range(RECOVERY_CODE_COUNT))
    try:
        terminal.present_recovery_codes(codes, deadline=time.monotonic() + 5)
        os.close(write_fd)
        presented = os.read(read_fd, 4096).decode()
    finally:
        os.close(read_fd)

    assert capsys.readouterr() == ("", "")
    assert all(code in presented for code in codes)


def test_totp_key_reader_requires_root_owned_private_regular_descriptor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    read_fd, write_fd = os.pipe()
    os.write(write_fd, b"k" * 32)
    os.close(write_fd)
    monkeypatch.setattr(
        os,
        "fstat",
        lambda fd: SimpleNamespace(st_mode=stat.S_IFREG | 0o400, st_uid=0),
    )
    try:
        assert bootstrap_cli.read_root_controlled_totp_key(read_fd) == b"k" * 32
    finally:
        os.close(read_fd)


def test_totp_key_reader_rejects_nonroot_or_group_readable_descriptor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    read_fd, write_fd = os.pipe()
    os.write(write_fd, b"k" * 32)
    os.close(write_fd)
    monkeypatch.setattr(
        os,
        "fstat",
        lambda fd: SimpleNamespace(st_mode=stat.S_IFREG | 0o440, st_uid=501),
    )
    try:
        with pytest.raises(ValueError, match="root-controlled"):
            bootstrap_cli.read_root_controlled_totp_key(read_fd)
    finally:
        os.close(read_fd)


def test_tty_timeout_is_an_absolute_deadline_after_partial_input() -> None:
    master_fd, slave_fd = os.openpty()
    terminal = object.__new__(bootstrap_cli.ControllingTerminal)
    terminal._fd = slave_fd
    tty.setcbreak(slave_fd)
    os.write(master_fd, b"I")
    closer = threading.Timer(2.0, os.close, args=(master_fd,))
    closer.start()
    started = time.monotonic()
    try:
        assert terminal._readline(deadline=started + 1) == ""
    finally:
        elapsed = time.monotonic() - started
        closer.cancel()
        try:
            os.close(master_fd)
        except OSError:
            pass
        os.close(slave_fd)

    assert elapsed < 1.5


def test_tty_timeout_is_not_extended_by_trickled_input() -> None:
    master_fd, slave_fd = os.openpty()
    terminal = object.__new__(bootstrap_cli.ControllingTerminal)
    terminal._fd = slave_fd
    tty.setcbreak(slave_fd)
    stop = threading.Event()

    def trickle() -> None:
        while not stop.wait(0.2):
            try:
                os.write(master_fd, b"I")
            except OSError:
                return

    writer = threading.Thread(target=trickle)
    writer.start()
    started = time.monotonic()
    try:
        assert terminal._readline(deadline=started + 1) == ""
    finally:
        elapsed = time.monotonic() - started
        stop.set()
        writer.join(timeout=1)
        os.close(master_fd)
        os.close(slave_fd)

    assert elapsed < 1.5


def test_controlling_tty_write_completes_short_writes(monkeypatch: pytest.MonkeyPatch) -> None:
    terminal = object.__new__(bootstrap_cli.ControllingTerminal)
    terminal._fd = 99
    written = bytearray()

    def short_write(fd: int, value: bytes | memoryview) -> int:
        assert fd == 99
        chunk = bytes(value[:2])
        written.extend(chunk)
        return len(chunk)

    monkeypatch.setattr("property_rental.bootstrap_cli.os.write", short_write)

    terminal._write("recovery-secret")

    assert written == b"recovery-secret"


def test_main_uses_protected_descriptors_and_dedicated_identity_without_process_output(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    descriptor_reads: list[int] = []
    service_runs: list[BootstrapRequest] = []

    class FakeCursor:
        def __enter__(self) -> FakeCursor:
            return self

        def __exit__(self, *args: object) -> None:
            del args

        def execute(self, query: str) -> None:
            assert query == "SELECT current_user"

        def fetchone(self) -> tuple[str]:
            return ("prm_bootstrap",)

    class FakeConnection:
        def __enter__(self) -> FakeConnection:
            return self

        def __exit__(self, *args: object) -> None:
            del args

        def cursor(self) -> FakeCursor:
            return FakeCursor()

    class FakeTerminal:
        def __enter__(self) -> FakeTerminal:
            return self

        def __exit__(self, *args: object) -> None:
            del args

    class FakeService:
        def __init__(self, **kwargs: object) -> None:
            assert kwargs["ceremony_timeout_seconds"] == 120
            password_policy = cast(BootstrapPasswordPolicy, kwargs["password_policy"])
            with pytest.raises(ValueError, match=r"^bootstrap password rejected$"):
                password_policy.accept("  blocked boundary phrase  ", context=())

        def run(self, request: BootstrapRequest) -> None:
            service_runs.append(request)

    def protected_read(fd: int, *, maximum_bytes: int) -> bytes:
        descriptor_reads.append(fd)
        assert maximum_bytes > 0
        return b"postgresql://protected-source" if fd == 3 else b"  blocked boundary phrase  \n"

    monkeypatch.setattr("property_rental.bootstrap_cli._read_fd", protected_read)
    monkeypatch.setattr(
        "property_rental.bootstrap_cli.read_root_controlled_totp_key", lambda fd: b"k" * 32
    )
    monkeypatch.setattr(
        "property_rental.bootstrap_cli.psycopg.connect", lambda url: FakeConnection()
    )
    monkeypatch.setattr("property_rental.bootstrap_cli.ControllingTerminal", FakeTerminal)
    monkeypatch.setattr("property_rental.bootstrap_cli.InitialOwnerBootstrapService", FakeService)

    arguments = [
        "--username",
        "owner",
        "--display-name",
        "Initial Owner",
        "--audit-name",
        "initial-owner",
        "--totp-key-identifier",
        "bootstrap-v1",
    ]
    assert bootstrap_cli.main(arguments) == 0

    assert descriptor_reads == [3, 5]
    assert service_runs and service_runs[0].username == "owner"
    assert "postgresql://protected-source" not in repr(arguments)
    assert capsys.readouterr() == ("", "")


def _collect_runtime_http_operations(routes: list[BaseRoute]) -> dict[str, set[str]]:
    operations: dict[str, set[str]] = {}
    for route in routes:
        path = getattr(route, "path", None)
        methods = getattr(route, "methods", None)
        if isinstance(path, str) and isinstance(methods, set):
            operations.setdefault(path, set()).update(
                method.casefold() for method in methods if isinstance(method, str)
            )
        nested_routes = getattr(route, "routes", None)
        if nested_routes is None:
            nested_routes = getattr(getattr(route, "original_router", None), "routes", None)
        if isinstance(nested_routes, list):
            nested_operations = _collect_runtime_http_operations(
                cast(list[BaseRoute], nested_routes)
            )
            for nested_path, nested_methods in nested_operations.items():
                operations.setdefault(nested_path, set()).update(nested_methods)
    return operations


def test_fastapi_openapi_inventory_has_no_bootstrap_or_unauthenticated_owner_reset_route() -> None:
    app = create_app(Settings())
    http_methods = {
        "delete",
        "get",
        "head",
        "options",
        "patch",
        "post",
        "put",
        "trace",
    }
    expected_api_operations = {
        "/api/v1/properties/{property_id}/payments/{source_id}/allocation-context": {"get"},
        "/api/v1/properties/{property_id}/payment-allocations/{source_id}/reversal-context": {
            "get"
        },
        "/api/v1/properties/{property_id}/receipts/{source_id}/reprint-context": {"get"},
        "/api/v1/properties/{property_id}/payments/{source_id}/credit-recognition-context": {"get"},
        "/api/v1/properties/{property_id}/customer-credits/{source_id}/reversal-context": {"get"},
        "/api/v1/properties/{property_id}/customer-credits/{source_id}/application-context": {
            "get"
        },
        "/api/v1/properties/{property_id}/credit-applications/{source_id}/reversal-context": {
            "get"
        },
        "/api/v1/properties/{property_id}/refunds/{source_id}/verified-return-context": {"get"},
        (
            "/api/v1/properties/{property_id}/refunds/{refund_id}/corrections/"
            "{source_id}/reversal-context"
        ): {"get"},
        "/api/v1/health/live": {"get"},
        "/api/v1/health/ready": {"get"},
        # V1-059 part A: the health page data (API-081), signed in with operations.status.read.
        "/api/v1/operations/status": {"get"},
        "/api/v1/identity/me": {"get"},
        "/api/v1/identity/me/access": {"get"},
        "/api/v1/auth/login": {"post"},
        "/api/v1/auth/password-change": {"post"},
        "/api/v1/auth/mfa/challenge": {"post"},
        "/api/v1/auth/mfa/enrollment": {"post"},
        "/api/v1/auth/mfa/enrollment/confirm": {"post"},
        "/api/v1/auth/session": {"get"},
        "/api/v1/auth/logout": {"post"},
        "/api/v1/auth/reauthenticate": {"post"},
        "/api/v1/auth/recovery-codes": {"get", "post"},
        "/api/v1/auth/recovery-codes/regenerate": {"post"},
        "/api/v1/properties/{property_id}/users": {"get", "post"},
        "/api/v1/users/{user_id}": {"patch"},
        "/api/v1/users/{user_id}/revoke-sessions": {"post"},
        "/api/v1/capabilities": {"get"},
        "/api/v1/properties/{property_id}/role-bundles": {"get", "post"},
        "/api/v1/role-bundles/{role_bundle_id}": {"patch"},
        "/api/v1/users/{user_id}/role-assignments": {"post"},
        # Login sub-slice L2b-1 (DL-081; Q-2026-10-21-158 (a), Q-2026-10-21-166 (a)).
        "/api/v1/users/{user_id}/role-assignments/remove": {"post"},
        "/api/v1/users/{user_id}/settings-access": {"post"},
        "/api/v1/users/{user_id}/settings-access/remove": {"post"},
        "/api/v1/properties/{property_id}/authorization-history": {"get"},
        "/api/v1/users/{user_id}/administrative-recovery": {"post"},
        "/api/v1/properties/{property_id}/audit-events": {"get"},
        "/api/v1/{resource_family}/{resource_id}/audit-events": {"get"},
        "/properties/{property_id}": {"get", "patch"},
        "/properties/{property_id}/configuration": {"get", "patch"},
        "/api/v1/properties/{property_id}/configuration-capabilities": {"get"},
        "/api/v1/properties/{property_id}/configured-services": {"get"},
        "/api/v1/properties/{property_id}/service-rates": {"get", "post"},
        "/api/v1/service-rates/{rate_id}": {"get"},
        "/api/v1/properties/{property_id}/utility-rates": {"get", "post"},
        "/api/v1/utility-rates/{rate_id}": {"get"},
        "/api/v1/units/{unit_id}/meters": {"get", "post"},
        "/api/v1/meters/{meter_id}": {"get"},
        "/api/v1/meters/{meter_id}/replace": {"post"},
        "/api/v1/meters/{meter_id}/report-broken": {"post"},
        "/api/v1/meters/{meter_id}/readings": {"get", "post"},
        "/api/v1/utility-readings/{reading_id}/correct": {"post"},
        "/api/v1/properties/{property_id}/utility-readings:batch": {"post"},
        "/api/v1/properties/{property_id}/utility-readings/sheet": {"post"},
        "/api/v1/properties/{property_id}/utility-readings/blank-sheet": {"post"},
        "/api/v1/utility-billing/preview": {"post"},
        "/api/v1/properties/{property_id}/billing-runs/rent": {"post"},
        "/api/v1/properties/{property_id}/billing-runs/utilities": {"post"},
        "/api/v1/billing-runs/{run_id}": {"get"},
        "/api/v1/properties/{property_id}/billing-capabilities": {"get"},
        "/api/v1/properties/{property_id}/invoices": {"get", "post"},
        "/api/v1/properties/{property_id}/invoices/drafts": {"post"},
        # V1-055 slice 9b adds the one-time charge and its due-days setting (docs/010 DL-067).
        "/api/v1/properties/{property_id}/one-time-charges": {"post"},
        # V1-058 R7b-4: the Settings Business tab reads the due days (GET).
        "/api/v1/properties/{property_id}/one-time-charge-due-days": {"get", "post"},
        "/api/v1/properties/{property_id}/leases/{lease_id}/initial-rent-due-date": {"post"},
        # V1-056 slice 11a: the move-out cleaning charge and the hand-back month (API-102).
        "/api/v1/properties/{property_id}/units/{unit_id}/cleaning-rate": {"get"},
        "/api/v1/properties/{property_id}/units/{unit_id}/cleaning-rates": {"post"},
        "/api/v1/properties/{property_id}/leases/{lease_id}/cleaning-charge": {"post"},
        "/api/v1/invoices/{invoice_id}/hand-back-assessment": {"get"},
        "/api/v1/invoices/{invoice_id}/hand-back-resolution": {"post"},
        # V1-056 slice 11b: the shared financial draft routes (API-101).
        "/api/v1/properties/{property_id}/financial-drafts": {"get"},
        "/api/v1/properties/{property_id}/financial-drafts/{draft_id}": {"get"},
        "/api/v1/properties/{property_id}/financial-drafts-waiting": {"get"},
        "/api/v1/properties/{property_id}/financial-drafts/{draft_id}/reject": {"post"},
        "/api/v1/properties/{property_id}/financial-drafts/{draft_id}/withdraw": {"post"},
        "/api/v1/properties/{property_id}/financial-drafts/{draft_id}/confirm": {"post"},
        "/api/v1/properties/{property_id}/leases/{lease_id}/utility-baseline": {"get", "post"},
        "/api/v1/properties/{property_id}/leases/{lease_id}/move-out-final-utility-inputs": {
            "get",
            "post",
        },
        "/api/v1/properties/{property_id}/leases/{lease_id}/final-utility-invoice": {"post"},
        "/api/v1/properties/{property_id}/leases/{lease_id}/utility-catch-up-invoice": {"post"},
        "/api/v1/properties/{property_id}/unbilled-utility-periods": {"get"},
        "/api/v1/properties/{property_id}/lease-terminations/{termination_event_id}"
        "/unpaid-initial-never-moved-in": {"post"},
        "/api/v1/properties/{property_id}/lease-terminations/{termination_event_id}"
        "/unpaid-initial-moved-in-credit": {"post"},
        "/api/v1/properties/{property_id}/leases/{lease_id}/termination-notices": {"get", "post"},
        "/api/v1/financial-workspaces": {"get"},
        "/api/v1/properties/{property_id}/financial-capabilities": {"get"},
        "/api/v1/properties/{property_id}/payment-methods": {"get"},
        "/api/v1/properties/{property_id}/payments/khr-preview": {"post"},
        "/api/v1/properties/{property_id}/payments/receive": {"post"},
        "/api/v1/properties/{property_id}/payments/payable": {"get"},
        "/api/v1/properties/{property_id}/payments/summary": {"get"},
        # V1-057: Home, reports, report files and the audit file (DL-072, DL-079).
        "/api/v1/properties/{property_id}/home": {"get"},
        "/api/v1/properties/{property_id}/reports/totals/{report}": {"get"},
        "/api/v1/properties/{property_id}/reports/{name}": {"get"},
        "/api/v1/properties/{property_id}/exports": {"post"},
        "/api/v1/properties/{property_id}/exports/{export_id}": {"get"},
        "/api/v1/properties/{property_id}/audit-exports": {"post"},
        # V1-058 R3 Move-out: the hand-back record and the move-out inspection.
        "/api/v1/properties/{property_id}/leases/{lease_id}/move-outs": {"get", "post"},
        "/api/v1/properties/{property_id}/leases/{lease_id}/move-out-inspections": {
            "get",
            "post",
        },
        "/api/v1/properties/{property_id}/payments/{payment_id}/receipt-lines": {"get"},
        "/api/v1/properties/{property_id}/invoices/{invoice_id}/late-charge": {"get"},
        "/api/v1/properties/{property_id}/payments/{payment_id}/reversal-context": {"get"},
        "/api/v1/properties/{property_id}/payments": {"get", "post"},
        "/api/v1/payments/{payment_id}": {"get"},
        "/api/v1/payments/{payment_id}/allocation-proposal": {"get"},
        "/api/v1/payments/{payment_id}/allocations": {"get", "post"},
        "/api/v1/payment-allocations/{allocation_id}/reverse": {"post"},
        "/api/v1/payments/{payment_id}/reverse": {"post"},
        "/api/v1/payments/{payment_id}/receipt": {"get"},
        "/api/v1/receipts/{receipt_id}": {"get"},
        "/api/v1/receipts/{receipt_id}/reprints": {"post"},
        "/api/v1/customers/{customer_id}/credits": {"get"},
        "/api/v1/customers/{customer_id}/account-ledger": {"get"},
        "/api/v1/customer-ledger/customers": {"get"},
        "/api/v1/customer-credits/{credit_id}": {"get"},
        "/api/v1/customer-credits/{credit_id}/ledger": {"get"},
        "/api/v1/payments/{payment_id}/credit-recognitions": {"post"},
        "/api/v1/customer-credits/{credit_id}/reverse": {"post"},
        "/api/v1/customer-credits/{credit_id}/application-proposal": {"get"},
        "/api/v1/customer-credits/{credit_id}/applications": {"post"},
        "/api/v1/credit-applications/{application_id}": {"get"},
        "/api/v1/credit-applications/{application_id}/reverse": {"post"},
        "/api/v1/properties/{property_id}/refunds": {"get"},
        "/api/v1/refunds/{refund_id}": {"get"},
        "/api/v1/refund-sources/{source_type}/{source_id}": {"get"},
        # V1-056 slice 11c-1: the Refund methods a draft may name.
        # V1-056 slice 11h: adding a Refund method and turning one off or on (Settings access).
        "/api/v1/properties/{property_id}/refund-methods": {"get", "post"},
        "/api/v1/properties/{property_id}/refund-methods/{refund_method_id}/state": {"post"},
        # V1-056 slice 11c-3: Deposit forfeiture, Deposit correction and returned-Payment drafts.
        "/api/v1/properties/{property_id}/deposits/{deposit_id}/forfeiture-drafts": {"post"},
        "/api/v1/properties/{property_id}/deposit-dispositions/{disposition_id}/reversal-drafts": {
            "post"
        },
        "/api/v1/properties/{property_id}/deposit-receipts/{receipt_id}/reversal-drafts": {"post"},
        "/api/v1/properties/{property_id}/payments/{payment_id}/return-drafts": {"post"},
        # V1-056 slice 11c-4: the walk-in Security Deposit and a receipt into a Deposit.
        "/api/v1/leases/{lease_id}/security-deposit": {"post"},
        "/api/v1/deposits/{deposit_id}/receipts": {"post"},
        # V1-056 slice 11d: the wrong-Unit Payment move draft.
        "/api/v1/properties/{property_id}/payment-allocations/{allocation_id}/move-drafts": {
            "post"
        },
        # V1-056 slice 11e-1: the Final Settlement start, preview and draft routes.
        "/api/v1/properties/{property_id}/leases/{lease_id}/final-settlement": {"post"},
        "/api/v1/properties/{property_id}/final-settlements": {"get"},
        # V1-058 R7b-6a: Services and Service types in Settings.
        "/api/v1/properties/{property_id}/service-settings": {"get"},
        "/api/v1/properties/{property_id}/services": {"post"},
        "/api/v1/properties/{property_id}/services/{service_id}": {"post"},
        "/api/v1/properties/{property_id}/service-types": {"post"},
        "/api/v1/properties/{property_id}/service-types/{type_id}": {"post"},
        "/api/v1/properties/{property_id}/service-types/{type_id}/remove": {"post"},
        # V1-058 R7b-6d: move-out cleaning rates by Unit Type.
        "/api/v1/properties/{property_id}/cleaning-settings": {"get"},
        "/api/v1/properties/{property_id}/cleaning-rates": {"post"},
        "/api/v1/properties/{property_id}/cleaning-rates/{rate_id}": {"post"},
        "/api/v1/properties/{property_id}/cleaning-rates/{rate_id}/remove": {"post"},
        "/api/v1/properties/{property_id}/final-settlements/{settlement_id}/preview": {"get"},
        "/api/v1/properties/{property_id}/final-settlements/{settlement_id}/drafts": {"post"},
        # V1-056 slice 11e-2: the post-settlement correction drafts and the Adjustment reversal.
        "/api/v1/properties/{property_id}/final-settlements/{settlement_id}"
        "/corrections/extra-charges": {"post"},
        "/api/v1/properties/{property_id}/final-settlements/{settlement_id}"
        "/corrections/charge-reductions": {"post"},
        "/api/v1/properties/{property_id}/final-settlements/{settlement_id}"
        "/corrections/late-charge-reductions": {"post"},
        "/api/v1/properties/{property_id}/final-settlements/{settlement_id}"
        "/corrections/returned-payments": {"post"},
        "/api/v1/properties/{property_id}/final-settlements/{settlement_id}"
        "/corrections/payment-moves": {"post"},
        "/api/v1/properties/{property_id}/final-settlements/{settlement_id}"
        "/corrections/adjustment-reversals": {"post"},
        # V1-056 slice 11e-3: the corrections with a DL-032 plan and the return reversal.
        "/api/v1/properties/{property_id}/final-settlements/{settlement_id}/corrections/refunds": {
            "post"
        },
        "/api/v1/properties/{property_id}/final-settlements/{settlement_id}"
        "/corrections/late-charge-refunds": {"post"},
        "/api/v1/properties/{property_id}/final-settlements/{settlement_id}"
        "/corrections/pet-classifications": {"post"},
        "/api/v1/properties/{property_id}/final-settlements/{settlement_id}"
        "/corrections/refund-returns": {"post"},
        "/api/v1/properties/{property_id}/final-settlements/{settlement_id}"
        "/corrections/held-value-refunds": {"post"},
        "/api/v1/properties/{property_id}/final-settlements/{settlement_id}"
        "/corrections/forfeiture-reversals": {"post"},
        "/api/v1/properties/{property_id}/final-settlements/{settlement_id}"
        "/corrections/deposit-receipt-corrections": {"post"},
        "/api/v1/properties/{property_id}/final-settlements/{settlement_id}"
        "/corrections/return-reversals": {"post"},
        "/api/v1/properties/{property_id}/invoice-adjustments/{adjustment_id}/reversal-drafts": {
            "post"
        },
        "/api/v1/refunds": {"post"},
        "/api/v1/refund-drafts": {"post"},
        "/api/v1/properties/{property_id}/refund-drafts/{draft_id}/confirm": {"post"},
        "/api/v1/refunds/{refund_id}/verified-returns": {"post"},
        "/api/v1/refunds/{refund_id}/verified-returns/{correction_id}/reverse": {"post"},
        "/api/v1/invoices/{invoice_id}": {"get", "patch"},
        "/api/v1/invoices/{invoice_id}/issue": {"post"},
        "/api/v1/invoices/{invoice_id}/items": {"put"},
        "/api/v1/invoices/{invoice_id}/adjustments": {"post"},
        "/api/v1/invoices/{invoice_id}/void": {"post"},
        "/api/v1/invoices/{invoice_id}/late-payment-review": {"get"},
        "/api/v1/invoices/{invoice_id}/late-payment-decision": {"get", "post"},
        "/api/v1/late-payment-charges/{charge_id}": {"get"},
        "/api/v1/late-payment-charges/{charge_id}/corrections": {"post"},
        # V1-056 slice 11g-2: reduce or waive a Late-payment Charge (DL-076 answer 4).
        "/api/v1/late-payment-charges/{charge_id}/reductions": {"post"},
        "/api/v1/properties/{property_id}/exchange-rates": {"get"},
        "/api/v1/properties/{property_id}/exchange-rates:confirm": {"post"},
        "/properties/{property_id}/units": {"get", "post"},
        "/units/{unit_id}": {"get", "patch"},
        "/units/{unit_id}/timeline": {"get"},
        "/properties/{property_id}/unit-setup": {"get"},
        "/properties/{property_id}/unit-setup/items": {"post"},
        "/unit-setup/items/{item_id}": {"patch"},
        "/unit-setup/items/{item_id}/remove": {"post"},
        "/units/{unit_id}/inventory": {"get", "put"},
        "/properties/{property_id}/unit-inventory-items": {"get"},
        "/api/v1/properties/{property_id}/customers": {"get", "post"},
        "/api/v1/properties/{property_id}/customers/{customer_id}/command-status": {"get"},
        "/api/v1/customers/{customer_id}": {"get", "patch"},
        "/api/v1/customers/{customer_id}/financial-summary": {"get"},
        "/properties/{property_id}/reservations": {"get", "post"},
        "/reservations/{reservation_id}": {"get"},
        "/reservations/{reservation_id}/extend": {"post"},
        "/reservations/{reservation_id}/cancel": {"post"},
        "/reservations/{reservation_id}/deposit-drafts": {"post"},
        "/reservations/{reservation_id}/deposit-correction-drafts": {"post"},
        "/reservations/{reservation_id}/deposit-drafts/{draft_id}/confirm": {"post"},
        "/reservations/{reservation_id}/deposit-drafts/{draft_id}/reject": {"post"},
        "/reservations/{reservation_id}/deposit-drafts/{draft_id}/withdraw": {"post"},
        "/properties/{property_id}/reservation-deposit-decisions": {"get"},
        "/api/v1/reservations/{reservation_id}/complete-move-in": {"post"},
        "/api/v1/properties/{property_id}/leases": {"get", "post"},
        "/api/v1/leases/{lease_id}": {"get", "patch"},
        "/api/v1/leases/{lease_id}/timeline": {"get"},
        "/api/v1/leases/{lease_id}/violation-warnings": {"get", "post"},
        "/api/v1/leases/{lease_id}/rent-nonpayment-cases": {"get", "post"},
        "/api/v1/rent-nonpayment-cases/{case_id}": {"get"},
        "/api/v1/rent-nonpayment-cases/{case_id}/events": {"get", "post"},
        "/api/v1/lease-enforcement-workspaces": {"get"},
        "/api/v1/properties/{property_id}/lease-enforcement-leases": {"get"},
        "/api/v1/properties/{property_id}/rent-nonpayment-alerts": {"get"},
        "/api/v1/properties/{property_id}/initial-rent-unpaid-alerts": {"get"},
        "/api/v1/leases/{lease_id}/violation-warning-context": {"get"},
        "/api/v1/leases/{lease_id}/rent-nonpayment-sources": {"get"},
        "/api/v1/leases/{lease_id}/rent-nonpayment-action-cases": {"get"},
        "/api/v1/rent-nonpayment-cases/{case_id}/action-context": {"get"},
        "/api/v1/leases/{lease_id}/signers": {"get", "post"},
        "/api/v1/lease-signers/{signer_id}": {"patch"},
        "/api/v1/leases/{lease_id}/occupancies": {"get", "post"},
        "/api/v1/occupancies/{occupancy_id}/end": {"post"},
        "/api/v1/leases/{lease_id}/signing-preview": {"get"},
        "/api/v1/leases/{lease_id}/planned-security-deposit": {"put"},
        "/api/v1/leases/{lease_id}/sign-with-payment": {"post"},
        "/api/v1/leases/{lease_id}/renew": {"post"},
        "/api/v1/leases/{lease_id}/cancel": {"post"},
        "/api/v1/leases/{lease_id}/move-in": {"post"},
        "/api/v1/leases/{lease_id}/occupants": {"post"},
        "/api/v1/leases/{lease_id}/terminate": {"post"},
        "/api/v1/reservations/{reservation_id}/deposits": {"get"},
        "/api/v1/reservations/{reservation_id}/security-deposit-dispositions": {"post"},
        "/api/v1/leases/{lease_id}/deposits": {"get"},
        "/api/v1/deposits/{deposit_id}": {"get"},
        "/api/v1/deposits/{deposit_id}/ledger": {"get"},
        "/api/v1/leases/{lease_id}/pet-deposits": {"post"},
        "/api/v1/deposit-receipts/{receipt_id}/reverse": {"post"},
        "/api/v1/deposit-dispositions/{disposition_id}/reverse": {"post"},
        "/api/v1/leases/{lease_id}/pet-departures": {"get", "post"},
        "/api/v1/pet-departures/{departure_id}/refund-review": {"post"},
        "/api/v1/pet-deposit-refund-reviews/{review_id}": {"get"},
    }
    openapi_operations = {
        path: set(path_item) & http_methods for path, path_item in app.openapi()["paths"].items()
    }
    # Login sub-slice L5 (Q-2026-10-24-186): the generated documentation pages are turned off.
    expected_runtime_operations = expected_api_operations
    runtime_operations = _collect_runtime_http_operations(app.routes)

    assert openapi_operations == expected_api_operations
    assert runtime_operations == expected_runtime_operations
