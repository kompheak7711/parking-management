"""FastAPI application factory."""

import re
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable
from contextlib import AbstractAsyncContextManager, AsyncExitStack, asynccontextmanager
from logging import Logger
from time import perf_counter
from typing import Final, cast
from uuid import uuid4

import psycopg
from fastapi import APIRouter, Depends, FastAPI, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from property_rental.access_admin_api import (
    AccessAdministrationConflict,
    AccessAdministrationFlow,
    AccessAdministrationNotFound,
    AccessAdministrationRejected,
    AccessAdministrationUnavailable,
    UnavailableAccessAdministrationFlow,
    create_access_admin_router,
)
from property_rental.access_admin_flow import PostgresAccessAdministrationFlow
from property_rental.allocation_receipt_api import (
    AllocationReceiptFlow,
    PostgresAllocationReceiptFlow,
    create_allocation_receipt_router,
)
from property_rental.api import create_api_router
from property_rental.audit_api import (
    AuditEventQueryFlow,
    AuditQueryForbidden,
    AuditQueryInvalid,
    AuditQueryNotFound,
    AuditQueryUnavailable,
    PostgresAuditEventQueryFlow,
    UnavailableAuditEventQueryFlow,
    create_audit_router,
)
from property_rental.auth_api import (
    AuthenticationFlow,
    AuthenticationRateLimited,
    AuthenticationUnavailable,
    NewPasswordRejected,
    UnavailableAuthenticationFlow,
    create_auth_router,
)
from property_rental.auth_flow import PostgresAuthenticationFlow
from property_rental.billing_run import PostgresBillingRunService
from property_rental.billing_run_api import (
    BillingRunFlow,
    UnavailableBillingRunFlow,
    create_billing_run_router,
)
from property_rental.browser_security import signed_in_browser_request
from property_rental.configuration_api import (
    ConfigurationFlow,
    ExchangeRateProvider,
    PostgresConfigurationFlow,
    UnavailableConfigurationFlow,
    UnavailableExchangeRateProvider,
    create_configuration_router,
)
from property_rental.credit import CreditIdempotencyKeyReused
from property_rental.credit_refund_api import (
    CreditRefundFlow,
    PostgresCreditRefundFlow,
    create_credit_refund_router,
)
from property_rental.customer import CustomerVersionConflict
from property_rental.customer_api import (
    CustomerIdempotencyKeyReused,
    CustomerIdNumberConflict,
    CustomerLifecycleConflict,
    CustomerResourceFlow,
    CustomerReuseConflict,
    PostgresCustomerResourceFlow,
    UnavailableCustomerResourceFlow,
    create_customer_router,
    customer_id_number_conflict_response,
    customer_idempotency_key_reused_response,
    customer_reuse_conflict_response,
)
from property_rental.customer_ledger_api import CustomerLedgerFlow, create_customer_ledger_router
from property_rental.customer_ledger_read import CustomerLedgerReadService
from property_rental.deposit import (
    DepositIdempotencyKeyReused,
    DepositReceiptReversalDraftRequired,
    LeaseDepositDraftRequired,
)
from property_rental.deposit_api import (
    DepositResourceFlow,
    PostgresDepositResourceFlow,
    UnavailableDepositResourceFlow,
    create_deposit_router,
    deposit_idempotency_key_reused_response,
)
from property_rental.financial_action_context import FinancialActionContextService
from property_rental.financial_action_context_api import (
    FinancialActionContextFlow,
    create_financial_action_context_router,
)
from property_rental.financial_reference import FinancialReferenceService
from property_rental.financial_reference_api import (
    FinancialReferenceFlow,
    create_financial_reference_router,
)
from property_rental.identity import (
    ActorResolver,
    deny_unauthenticated_actor,
    remembered_actor,
)
from property_rental.invoice import (
    InvoiceIdempotencyKeyReused,
    InvoiceLineFullyPaid,
    InvoiceVersionConflict,
    PostgresInvoiceService,
)
from property_rental.invoice_api import (
    InvoiceFlow,
    UnavailableInvoiceFlow,
    create_invoice_router,
    invoice_idempotency_key_reused_response,
    invoice_line_fully_paid_response,
)
from property_rental.late_payment import (
    LatePaymentApplicationReversalRequired,
    LatePaymentIdempotencyKeyReused,
    PostgresLatePaymentService,
)
from property_rental.late_payment_api import (
    LatePaymentFlow,
    UnavailableLatePaymentFlow,
    application_reversal_required_response,
    create_late_payment_router,
    late_payment_idempotency_key_reused_response,
)
from property_rental.lease_api import (
    LeaseResourceFlow,
    PostgresLeaseResourceFlow,
    UnavailableLeaseResourceFlow,
    create_lease_router,
)
from property_rental.lease_enforcement import PostgresLeaseEnforcementService
from property_rental.lease_enforcement_api import (
    EnforcementContextFlow,
    EnforcementFlow,
    create_enforcement_router,
)
from property_rental.lease_enforcement_context import PostgresEnforcementContext
from property_rental.logging import create_application_logger
from property_rental.operations_status_api import create_operations_status_router
from property_rental.payment_allocation import AllocationIdempotencyKeyReused
from property_rental.payment_api import (
    PaymentFlow,
    PostgresPaymentFlow,
    create_payment_router,
    payment_key_reused_response,
)
from property_rental.payment_confirmation import PaymentConfirmationKeyReused
from property_rental.payment_reversal_context import PaymentReversalContextService
from property_rental.payment_reversal_context_api import (
    PaymentReversalContextFlow,
    create_payment_reversal_context_router,
)
from property_rental.property_api import (
    PostgresPropertyResourceFlow,
    PropertyResourceFlow,
    PropertyVersionConflict,
    UnavailablePropertyResourceFlow,
    create_property_router,
)
from property_rental.receipt import ReceiptIdempotencyKeyReused
from property_rental.refund import RefundIdempotencyKeyReused
from property_rental.reservation import (
    ReservationDepositDraftRequired,
    ReservationIdempotencyKeyReused,
)
from property_rental.reservation_api import (
    PostgresReservationResourceFlow,
    ReservationResourceFlow,
    UnavailableReservationResourceFlow,
    create_reservation_router,
)
from property_rental.reservation_deposit_draft import ReservationDepositDraftKeyReused
from property_rental.runtime_secrets import (
    PasswordBlocklistUnavailable,
    ProtectedKeyUnavailable,
    derive_sign_in_try_key,
    read_password_blocklist,
    read_protected_totp_key,
)
from property_rental.session_actor import PostgresSessionActorResolver
from property_rental.settings import Settings
from property_rental.unit_api import (
    PostgresUnitResourceFlow,
    UnavailableUnitResourceFlow,
    UnitResourceFlow,
    UnitVersionConflict,
    create_unit_router,
)
from property_rental.unpaid_initial_termination_api import (
    PostgresUnpaidInitialFlow,
    UnavailableUnpaidInitialFlow,
    UnpaidInitialFlow,
    create_unpaid_initial_termination_router,
)
from property_rental.utility_api import (
    MeterSerialNumberInUse,
    PostgresUtilityResourceFlow,
    UnavailableUtilityResourceFlow,
    UtilityResourceFlow,
    UtilityResourceVersionConflict,
    create_utility_router,
)
from property_rental.utility_lease_api import (
    PostgresUtilityLeaseFlow,
    UnavailableUtilityLeaseFlow,
    UtilityLeaseFlow,
    create_utility_lease_router,
)

REQUEST_ID_HEADER: Final = "X-Request-ID"
REQUEST_ID_PATTERN: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
CUSTOMER_API_PATH_PATTERN: Final = re.compile(
    r"^/api/v1/(?:customers(?:/|$)|properties/[^/]+/customers(?:/|$))"
)
CONFIGURATION_API_PATH_PATTERN: Final = re.compile(
    r"^(?:/properties/[^/]+/configuration(?:/|$)|"
    r"/api/v1/(?:properties/[^/]+/(?:configuration-capabilities|configured-services|service-rates|"
    r"utility-rates|exchange-rates(?::confirm)?)|service-rates/|utility-rates/))"
)
LEASE_API_PATH_PATTERN: Final = re.compile(
    r"^/api/v1/(?:properties/[^/]+/leases(?:/|$)|leases(?:/|$)|"
    r"lease-signers(?:/|$)|occupancies(?:/|$)|"
    r"reservations/[^/]+/complete-move-in$)"
)
RESERVATION_API_PATH_PATTERN: Final = re.compile(r"^(?:/api/v1)?/reservations(?:/|$)")
DEPOSIT_API_PATH_PATTERN: Final = re.compile(
    r"^/api/v1/(?:deposits(?:/|$)|deposit-receipts(?:/|$)|"
    r"deposit-dispositions(?:/|$)|pet-departures(?:/|$)|"
    r"pet-deposit-refund-reviews(?:/|$)|reservations/[^/]+/(?:deposits|security-deposit-dispositions)$|"
    r"leases/[^/]+/(?:deposits|pet-deposits|pet-departures)(?:/|$))"
)
UTILITY_API_PATH_PATTERN: Final = re.compile(
    r"^/api/v1/(?:units/[^/]+/meters(?:/|$)|meters(?:/|$)|"
    r"utility-readings(?:/|$)|properties/[^/]+/utility-readings:batch$|"
    r"properties/[^/]+/unbilled-utility-periods$|"
    r"utility-billing/preview$)"
)
BILLING_RUN_API_PATH_PATTERN: Final = re.compile(
    r"^/api/v1/(?:properties/[^/]+/billing-runs/(?:rent|utilities)$|billing-runs/[^/]+$)"
)
INVOICE_API_PATH_PATTERN: Final = re.compile(
    r"^/api/v1/(?:properties/[^/]+/(?:invoices(?:/|$)|billing-capabilities$|"
    r"one-time-charges$|one-time-charge-due-days$)|invoices(?:/|$))"
)
UNPAID_INITIAL_API_PATH_PATTERN: Final = re.compile(
    r"^/api/v1/properties/[^/]+/lease-terminations/[^/]+/"
    r"unpaid-initial-(?:never-moved-in|moved-in-credit)$"
)
LATE_PAYMENT_API_PATH_PATTERN: Final = re.compile(
    r"^/api/v1/(?:invoices/[^/]+/late-payment-(?:review|decision)$|"
    r"late-payment-charges(?:/|$))"
)
PAYMENT_API_PATH_PATTERN: Final = re.compile(
    r"^/api/v1/(?:financial-workspaces$|properties/[^/]+/(?:financial-capabilities|payment-methods)$|"
    r"properties/[^/]+/(?:payments|refunds|refund-drafts|payment-allocations|receipts|customer-credits|credit-applications)(?:/|$)|"
    r"customer-ledger/customers(?:/|$)|customers/[^/]+/(?:credits|account-ledger)(?:/|$)|"
    r"(?:payments|payment-allocations|receipts|customer-credits|credit-applications|refunds|refund-drafts|refund-sources)(?:/|$))"
)
DATABASE_TIMEOUT_SECONDS: Final = 2
ERROR_STATUS_DETAILS: Final = {
    status.HTTP_400_BAD_REQUEST: ("BAD_REQUEST", "The request could not be processed."),
    status.HTTP_401_UNAUTHORIZED: ("UNAUTHORIZED", "Authentication is required."),
    status.HTTP_403_FORBIDDEN: ("FORBIDDEN", "The request is not permitted."),
    status.HTTP_404_NOT_FOUND: ("NOT_FOUND", "The requested resource was not found."),
    status.HTTP_409_CONFLICT: (
        "CONFLICT",
        "The request conflicts with the current resource state.",
    ),
    status.HTTP_412_PRECONDITION_FAILED: (
        "PRECONDITION_FAILED",
        "A required request precondition was not met.",
    ),
    status.HTTP_422_UNPROCESSABLE_CONTENT: (
        "VALIDATION_ERROR",
        "The request did not match the required schema.",
    ),
    status.HTTP_429_TOO_MANY_REQUESTS: ("RATE_LIMITED", "Too many requests."),
    status.HTTP_500_INTERNAL_SERVER_ERROR: (
        "INTERNAL_ERROR",
        "An unexpected internal error occurred.",
    ),
    status.HTTP_503_SERVICE_UNAVAILABLE: (
        "SERVICE_UNAVAILABLE",
        "A required service is temporarily unavailable.",
    ),
}


# The answer to a new password that breaks the rule (login sub-slice L4, UI-003).
NEW_PASSWORD_RULE_MESSAGE: Final = (
    "Choose a password of 15 to 128 characters that is not a common password, not your name "
    "and not the one-time password."
)
# The only environments where the wrong-try digests may be plain sha256 (login sub-slice L3c-1).
PLAIN_DIGEST_ENVIRONMENTS: Final = frozenset({"development", "test"})


def _totp_protection_key(settings: Settings) -> bytes | None:
    """The TOTP protection key, read once at start-up from the protected key file; the sign-in
    flow checks sign-in codes with it (login sub-slice L3c-2a) and derives the key of the
    wrong-try digests from it (L3c-1). A database without a key file stops the start in every
    environment except `development` and `test` (an allowed list, review round 1), so plain
    digests are used only there."""
    if settings.totp_key_file:
        return read_protected_totp_key(settings.totp_key_file)
    if settings.database_url is not None and settings.environment not in PLAIN_DIGEST_ENVIRONMENTS:
        raise ProtectedKeyUnavailable("APP_TOTP_KEY_FILE is required with a database")
    return None


def _password_blocklist(settings: Settings) -> frozenset[str]:
    """The local password blocklist of every new password (login sub-slice L4), read once at
    start-up; like the key file, a database without it stops the start in every environment
    except `development` and `test`, and an empty setting counts as unset (L3c-1 binding)."""
    if settings.password_blocklist_file:
        return read_password_blocklist(settings.password_blocklist_file)
    if settings.database_url is not None and settings.environment not in PLAIN_DIGEST_ENVIRONMENTS:
        raise PasswordBlocklistUnavailable(
            "APP_PASSWORD_BLOCKLIST_FILE is required with a database"
        )
    return frozenset()


def check_database_readiness(database_url: str) -> None:
    """Confirm PostgreSQL accepts one bounded authenticated query."""
    with psycopg.connect(
        database_url,
        connect_timeout=DATABASE_TIMEOUT_SECONDS,
        options=f"-c statement_timeout={DATABASE_TIMEOUT_SECONDS * 1000}",
    ) as connection:
        result = connection.execute("SELECT 1").fetchone()
        if result != (1,):
            raise RuntimeError("database readiness check returned an unexpected result")


def normalize_request_id(value: str | None) -> str:
    """Return a safe caller correlation ID or a generated fallback."""
    if value is not None:
        normalized = value.strip()
        if REQUEST_ID_PATTERN.fullmatch(normalized):
            return normalized
    return str(uuid4())


def error_response(
    status_code: int,
    request_id: str,
    *,
    fields: list[str] | None = None,
    current_version: int | None = None,
) -> JSONResponse:
    """Build a canonical error envelope without accepting exception details."""
    code, message = ERROR_STATUS_DETAILS.get(
        status_code,
        ("HTTP_ERROR", "The request could not be processed."),
    )
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": code,
                "message": message,
                "fields": fields or [],
                "rule_ids": [],
                "current_version": current_version,
            },
            "meta": {"request_id": request_id},
        },
        headers={REQUEST_ID_HEADER: request_id},
    )


def rule_conflict_response(
    request: Request,
    *,
    code: str,
    message: str,
    fields: list[str],
    rule_ids: list[str],
) -> JSONResponse:
    """Build the 409 envelope of a refused duplicate with a fixed code and message."""
    request_id = request.state.request_id
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content={
            "error": {
                "code": code,
                "message": message,
                "fields": fields,
                "rule_ids": rule_ids,
                "current_version": None,
            },
            "meta": {"request_id": request_id},
        },
        headers={REQUEST_ID_HEADER: request_id, "Cache-Control": "private, no-store"},
    )


def safe_validation_fields(exc: RequestValidationError) -> list[str]:
    """Return bounded field locations while excluding rejected values and diagnostics."""
    fields: set[str] = set()
    for error in exc.errors():
        location = error.get("loc")
        if not isinstance(location, tuple):
            continue
        components = [component for component in location if isinstance(component, str)]
        if components and all(REQUEST_ID_PATTERN.fullmatch(component) for component in components):
            fields.add(".".join(components))
    return sorted(fields)[:50]


def validation_status_code(exc: RequestValidationError) -> int:
    """Classify malformed JSON using only framework error type and location."""
    for error in exc.errors():
        location = error.get("loc")
        if error.get("type") == "json_invalid" and isinstance(location, tuple):
            if location and location[0] == "body":
                return status.HTTP_400_BAD_REQUEST
    return status.HTTP_422_UNPROCESSABLE_CONTENT


def create_app(
    settings: Settings | None = None,
    readiness_check: Callable[[str], None] = check_database_readiness,
    lifecycle_resources: Iterable[AbstractAsyncContextManager[object]] = (),
    application_logger: Logger | None = None,
    actor_resolver: ActorResolver | None = None,
    authentication_flow: AuthenticationFlow | None = None,
    access_administration_flow: AccessAdministrationFlow | None = None,
    audit_query_flow: AuditEventQueryFlow | None = None,
    property_resource_flow: PropertyResourceFlow | None = None,
    unit_resource_flow: UnitResourceFlow | None = None,
    customer_resource_flow: CustomerResourceFlow | None = None,
    configuration_flow: ConfigurationFlow | None = None,
    exchange_rate_provider: ExchangeRateProvider | None = None,
    reservation_resource_flow: ReservationResourceFlow | None = None,
    lease_resource_flow: LeaseResourceFlow | None = None,
    deposit_resource_flow: DepositResourceFlow | None = None,
    utility_resource_flow: UtilityResourceFlow | None = None,
    billing_run_flow: BillingRunFlow | None = None,
    invoice_flow: InvoiceFlow | None = None,
    late_payment_flow: LatePaymentFlow | None = None,
    unpaid_initial_flow: UnpaidInitialFlow | None = None,
    utility_lease_flow: UtilityLeaseFlow | None = None,
    enforcement_flow: EnforcementFlow | None = None,
    enforcement_context_flow: EnforcementContextFlow | None = None,
    payment_flow: PaymentFlow | None = None,
    financial_reference_flow: FinancialReferenceFlow | None = None,
    payment_reversal_context_flow: PaymentReversalContextFlow | None = None,
    financial_action_context_flow: FinancialActionContextFlow | None = None,
    allocation_receipt_flow: AllocationReceiptFlow | None = None,
    credit_refund_flow: CreditRefundFlow | None = None,
    customer_ledger_flow: CustomerLedgerFlow | None = None,
) -> FastAPI:
    """Build an application instance from validated settings."""
    resolved_settings = settings or Settings()
    totp_protection_key = _totp_protection_key(resolved_settings)
    password_blocklist = _password_blocklist(resolved_settings)
    sign_in_try_key = (
        derive_sign_in_try_key(totp_protection_key) if totp_protection_key is not None else None
    )
    if actor_resolver is None:
        # Login sub-slice L3a-2: the session cookie gives the actor when a database is set;
        # otherwise everyone is denied. Tests keep injecting their own resolver.
        actor_resolver = (
            PostgresSessionActorResolver(resolved_settings.database_url.get_secret_value())
            if resolved_settings.database_url is not None
            else deny_unauthenticated_actor
        )
    # Login sub-slice L5: the route guard and the route itself read the same actor, once.
    actor_resolver = remembered_actor(actor_resolver)
    logger = application_logger or create_application_logger(
        service=resolved_settings.service_name,
        environment=resolved_settings.environment,
        level=resolved_settings.log_level,
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        async with AsyncExitStack() as stack:
            for resource in lifecycle_resources:
                await stack.enter_async_context(resource)
            logger.info("application started", extra={"event": "application.started"})
            if totp_protection_key is None and resolved_settings.database_url is not None:
                # Owner item 4 of 2026-10-23: a database without the key file is never used
                # quietly; the warning shows no key, path or file content.
                logger.warning(
                    "APP_TOTP_KEY_FILE is not set: sign-in codes cannot be checked and the "
                    "wrong-try digests are not keyed; allowed only in development and test",
                    extra={"event": "security.protected_key_file_missing"},
                )
            try:
                yield
            finally:
                logger.info("application stopping", extra={"event": "application.stopping"})

    # Login sub-slice L5 (Q-2026-10-24-186): no generated documentation pages, so every route
    # that answers without a session is in the inventory test's list.
    app = FastAPI(
        title=resolved_settings.service_name,
        version=resolved_settings.build_version,
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    @app.exception_handler(RequestValidationError)
    async def request_validation_error(
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        status_code = validation_status_code(exc)
        return error_response(
            status_code,
            request.state.request_id,
            fields=(
                safe_validation_fields(exc)
                if status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
                else None
            ),
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        return error_response(exc.status_code, request.state.request_id)

    @app.exception_handler(PaymentConfirmationKeyReused)
    async def payment_key_reused(request: Request, _: PaymentConfirmationKeyReused) -> JSONResponse:
        return payment_key_reused_response(request)

    @app.exception_handler(AllocationIdempotencyKeyReused)
    @app.exception_handler(ReceiptIdempotencyKeyReused)
    async def allocation_receipt_key_reused(
        request: Request, _: AllocationIdempotencyKeyReused | ReceiptIdempotencyKeyReused
    ) -> JSONResponse:
        return payment_key_reused_response(request)

    @app.exception_handler(CreditIdempotencyKeyReused)
    @app.exception_handler(RefundIdempotencyKeyReused)
    async def credit_refund_key_reused(
        request: Request, _: CreditIdempotencyKeyReused | RefundIdempotencyKeyReused
    ) -> JSONResponse:
        return payment_key_reused_response(request)

    @app.exception_handler(MeterSerialNumberInUse)
    async def meter_serial_number_in_use(
        request: Request, _: MeterSerialNumberInUse
    ) -> JSONResponse:
        return rule_conflict_response(
            request,
            code="METER_SERIAL_NUMBER_IN_USE",
            message=(
                "Another Meter of this Property, current or replaced, already has this serial "
                "number."
            ),
            fields=["serial_number"],
            rule_ids=["DB-UTIL-001"],
        )

    @app.exception_handler(ReservationDepositDraftRequired)
    async def reservation_deposit_draft_required(
        request: Request, _: ReservationDepositDraftRequired
    ) -> JSONResponse:
        request_id = request.state.request_id
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={
                "error": {
                    "code": "RESERVATION_DEPOSIT_DRAFT_REQUIRED",
                    "message": (
                        "A Reservation Deposit Refund, forfeiture or correction is recorded as "
                        "a draft and takes effect only when a financial.approve holder "
                        "confirms it."
                    ),
                    "fields": [],
                    "rule_ids": ["BR-AUTH-010", "BR-RES-021", "BR-RES-022"],
                    "current_version": None,
                },
                "meta": {"request_id": request_id},
            },
            headers={
                REQUEST_ID_HEADER: request_id,
                "Cache-Control": "private, no-store",
            },
        )

    @app.exception_handler(LeaseDepositDraftRequired)
    async def lease_deposit_draft_required(
        request: Request, _: LeaseDepositDraftRequired
    ) -> JSONResponse:
        request_id = request.state.request_id
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={
                "error": {
                    "code": "LEASE_DEPOSIT_DRAFT_REQUIRED",
                    "message": (
                        "A Lease Deposit forfeiture or its reversal is recorded as a draft and "
                        "takes effect only when a financial.approve holder confirms it."
                    ),
                    "fields": [],
                    "rule_ids": ["BR-AUTH-010", "BR-DEP-026"],
                    "current_version": None,
                },
                "meta": {"request_id": request_id},
            },
            headers={
                REQUEST_ID_HEADER: request_id,
                "Cache-Control": "private, no-store",
            },
        )

    @app.exception_handler(DepositReceiptReversalDraftRequired)
    async def deposit_receipt_reversal_draft_required(
        request: Request, _: DepositReceiptReversalDraftRequired
    ) -> JSONResponse:
        request_id = request.state.request_id
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={
                "error": {
                    "code": "DEPOSIT_RECEIPT_REVERSAL_DRAFT_REQUIRED",
                    "message": (
                        "A Deposit receipt reversal is recorded as a draft and takes effect "
                        "only when a financial.approve holder confirms it."
                    ),
                    "fields": [],
                    "rule_ids": ["BR-AUTH-010"],
                    "current_version": None,
                },
                "meta": {"request_id": request_id},
            },
            headers={
                REQUEST_ID_HEADER: request_id,
                "Cache-Control": "private, no-store",
            },
        )

    @app.exception_handler(AuthenticationUnavailable)
    async def authentication_unavailable(
        request: Request,
        _: AuthenticationUnavailable,
    ) -> JSONResponse:
        return error_response(status.HTTP_503_SERVICE_UNAVAILABLE, request.state.request_id)

    @app.exception_handler(AuthenticationRateLimited)
    async def authentication_rate_limited(
        request: Request,
        exc: AuthenticationRateLimited,
    ) -> JSONResponse:
        response = error_response(status.HTTP_429_TOO_MANY_REQUESTS, request.state.request_id)
        if exc.retry_after_seconds is not None:
            # Login sub-slice L3b: the seconds left of the sign-in wait; the body stays the
            # same for every username.
            response.headers["Retry-After"] = str(exc.retry_after_seconds)
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(NewPasswordRejected)
    async def new_password_rejected(
        request: Request,
        _: NewPasswordRejected,
    ) -> JSONResponse:
        # Login sub-slice L4: the rule of every new password, the same answer for every reason.
        request_id = request.state.request_id
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content={
                "error": {
                    "code": "PASSWORD_RULE",
                    "message": NEW_PASSWORD_RULE_MESSAGE,
                    "fields": ["new_password"],
                    "rule_ids": [],
                    "current_version": None,
                },
                "meta": {"request_id": request_id},
            },
            headers={REQUEST_ID_HEADER: request_id, "Cache-Control": "no-store"},
        )

    @app.exception_handler(AccessAdministrationUnavailable)
    async def access_administration_unavailable(
        request: Request,
        _: AccessAdministrationUnavailable,
    ) -> JSONResponse:
        return error_response(status.HTTP_503_SERVICE_UNAVAILABLE, request.state.request_id)

    @app.exception_handler(AccessAdministrationNotFound)
    async def access_administration_not_found(
        request: Request,
        _: AccessAdministrationNotFound,
    ) -> JSONResponse:
        return error_response(status.HTTP_404_NOT_FOUND, request.state.request_id)

    @app.exception_handler(AccessAdministrationConflict)
    async def access_administration_conflict(
        request: Request,
        _: AccessAdministrationConflict,
    ) -> JSONResponse:
        return error_response(status.HTTP_409_CONFLICT, request.state.request_id)

    @app.exception_handler(AccessAdministrationRejected)
    async def access_administration_rejected(
        request: Request,
        exc: AccessAdministrationRejected,
    ) -> JSONResponse:
        # Login sub-slice L2b-2: a stable code and a fixed plain message; no database text.
        request_id = request.state.request_id
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                    "fields": [],
                    "rule_ids": [],
                    "current_version": None,
                },
                "meta": {"request_id": request_id},
            },
            headers={REQUEST_ID_HEADER: request_id},
        )

    @app.exception_handler(AuditQueryUnavailable)
    async def audit_query_unavailable(
        request: Request,
        _: AuditQueryUnavailable,
    ) -> JSONResponse:
        return error_response(status.HTTP_503_SERVICE_UNAVAILABLE, request.state.request_id)

    @app.exception_handler(AuditQueryForbidden)
    async def audit_query_forbidden(
        request: Request,
        _: AuditQueryForbidden,
    ) -> JSONResponse:
        return error_response(status.HTTP_403_FORBIDDEN, request.state.request_id)

    @app.exception_handler(AuditQueryNotFound)
    async def audit_query_not_found(
        request: Request,
        _: AuditQueryNotFound,
    ) -> JSONResponse:
        return error_response(status.HTTP_404_NOT_FOUND, request.state.request_id)

    @app.exception_handler(AuditQueryInvalid)
    async def audit_query_invalid(
        request: Request,
        _: AuditQueryInvalid,
    ) -> JSONResponse:
        return error_response(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            request.state.request_id,
        )

    @app.exception_handler(PropertyVersionConflict)
    async def property_version_conflict(
        request: Request,
        exc: PropertyVersionConflict,
    ) -> JSONResponse:
        return error_response(
            status.HTTP_412_PRECONDITION_FAILED,
            request.state.request_id,
            current_version=exc.current_version,
        )

    @app.exception_handler(UnitVersionConflict)
    async def unit_version_conflict(
        request: Request,
        exc: UnitVersionConflict,
    ) -> JSONResponse:
        return error_response(
            status.HTTP_412_PRECONDITION_FAILED,
            request.state.request_id,
            current_version=exc.current_version,
        )

    @app.exception_handler(UtilityResourceVersionConflict)
    async def utility_resource_version_conflict(
        request: Request,
        exc: UtilityResourceVersionConflict,
    ) -> JSONResponse:
        return error_response(
            status.HTTP_412_PRECONDITION_FAILED,
            request.state.request_id,
            current_version=exc.current_version,
        )

    @app.exception_handler(CustomerVersionConflict)
    async def customer_version_conflict(
        request: Request,
        exc: CustomerVersionConflict,
    ) -> JSONResponse:
        return error_response(
            status.HTTP_412_PRECONDITION_FAILED,
            request.state.request_id,
            current_version=exc.current_version,
        )

    @app.exception_handler(CustomerIdNumberConflict)
    async def customer_id_number_conflict(
        request: Request,
        exc: CustomerIdNumberConflict,
    ) -> JSONResponse:
        return customer_id_number_conflict_response(request, exc)

    @app.exception_handler(CustomerReuseConflict)
    async def customer_reuse_conflict(
        request: Request,
        exc: CustomerReuseConflict,
    ) -> JSONResponse:
        return customer_reuse_conflict_response(request, exc)

    @app.exception_handler(CustomerIdempotencyKeyReused)
    async def customer_idempotency_key_reused(
        request: Request,
        _: CustomerIdempotencyKeyReused,
    ) -> JSONResponse:
        return customer_idempotency_key_reused_response(request)

    @app.exception_handler(DepositIdempotencyKeyReused)
    @app.exception_handler(ReservationIdempotencyKeyReused)
    @app.exception_handler(ReservationDepositDraftKeyReused)
    async def deposit_idempotency_key_reused(
        request: Request,
        _: (
            DepositIdempotencyKeyReused
            | ReservationIdempotencyKeyReused
            | ReservationDepositDraftKeyReused
        ),
    ) -> JSONResponse:
        return deposit_idempotency_key_reused_response(request)

    @app.exception_handler(InvoiceIdempotencyKeyReused)
    async def invoice_idempotency_key_reused(
        request: Request,
        _: InvoiceIdempotencyKeyReused,
    ) -> JSONResponse:
        return invoice_idempotency_key_reused_response(request)

    @app.exception_handler(LatePaymentIdempotencyKeyReused)
    async def late_payment_idempotency_key_reused(
        request: Request,
        _: LatePaymentIdempotencyKeyReused,
    ) -> JSONResponse:
        return late_payment_idempotency_key_reused_response(request)

    @app.exception_handler(LatePaymentApplicationReversalRequired)
    async def late_payment_application_reversal_required(
        request: Request,
        _: LatePaymentApplicationReversalRequired,
    ) -> JSONResponse:
        return application_reversal_required_response(request)

    @app.exception_handler(InvoiceLineFullyPaid)
    async def invoice_line_fully_paid(
        request: Request,
        _: InvoiceLineFullyPaid,
    ) -> JSONResponse:
        return invoice_line_fully_paid_response(request)

    @app.exception_handler(InvoiceVersionConflict)
    async def invoice_version_conflict(
        request: Request,
        exc: InvoiceVersionConflict,
    ) -> JSONResponse:
        return error_response(
            status.HTTP_412_PRECONDITION_FAILED,
            request.state.request_id,
            current_version=exc.current_version,
        )

    @app.exception_handler(CustomerLifecycleConflict)
    async def customer_lifecycle_conflict(
        request: Request,
        exc: CustomerLifecycleConflict,
    ) -> JSONResponse:
        return error_response(
            status.HTTP_409_CONFLICT,
            request.state.request_id,
            current_version=exc.current_version,
        )

    @app.middleware("http")
    async def add_request_id(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request_id = normalize_request_id(request.headers.get(REQUEST_ID_HEADER))
        request.state.request_id = request_id
        started_at = perf_counter()
        try:
            response = await call_next(request)
        except Exception as exc:
            logger.error(
                "request failed",
                extra={
                    "event": "request.exception",
                    "request_id": request_id,
                    "method": request.method,
                    "status_code": status.HTTP_500_INTERNAL_SERVER_ERROR,
                    "exception_type": type(exc).__name__,
                },
            )
            response = error_response(status.HTTP_500_INTERNAL_SERVER_ERROR, request_id)
        response.headers[REQUEST_ID_HEADER] = request_id
        if (
            CUSTOMER_API_PATH_PATTERN.match(request.url.path)
            or CONFIGURATION_API_PATH_PATTERN.match(request.url.path)
            or LEASE_API_PATH_PATTERN.match(request.url.path)
            or RESERVATION_API_PATH_PATTERN.match(request.url.path)
            or DEPOSIT_API_PATH_PATTERN.match(request.url.path)
            or UTILITY_API_PATH_PATTERN.match(request.url.path)
            or BILLING_RUN_API_PATH_PATTERN.match(request.url.path)
            or INVOICE_API_PATH_PATTERN.match(request.url.path)
            or LATE_PAYMENT_API_PATH_PATTERN.match(request.url.path)
            or UNPAID_INITIAL_API_PATH_PATTERN.match(request.url.path)
            or PAYMENT_API_PATH_PATTERN.match(request.url.path)
            or request.url.path.startswith("/api/v1/lease-enforcement-workspaces")
            or request.url.path.startswith("/api/v1/rent-nonpayment-cases")
            or re.fullmatch(
                r"/api/v1/properties/[^/]+/(?:lease-enforcement-leases|rent-nonpayment-alerts|initial-rent-unpaid-alerts)",
                request.url.path,
            )
        ):
            response.headers["Cache-Control"] = "private, no-store"
            response.headers["Vary"] = "Cookie"
        logger.info(
            "request completed",
            extra={
                "event": "request.completed",
                "request_id": request_id,
                "method": request.method,
                "status_code": response.status_code,
                "duration_ms": round((perf_counter() - started_at) * 1000, 3),
            },
        )
        return response

    signed_in = Depends(signed_in_browser_request(actor_resolver, resolved_settings))

    def include_signed_in(router: APIRouter) -> None:
        """Every router but health and sign-in needs a signed-in user first (login sub-slice
        L5); a change also needs the Origin and the CSRF pair first."""
        app.include_router(router, dependencies=[signed_in])

    app.include_router(
        create_api_router(
            resolved_settings,
            readiness_check,
            actor_resolver,
        )
    )
    include_signed_in(
        create_operations_status_router(actor_resolver, resolved_settings, readiness_check)
    )
    app.include_router(
        create_auth_router(
            resolved_settings,
            authentication_flow
            or (
                PostgresAuthenticationFlow(
                    resolved_settings.database_url.get_secret_value(),
                    sign_in_try_key=sign_in_try_key,
                    totp_protection_key=totp_protection_key,
                    password_blocklist=password_blocklist,
                )
                if resolved_settings.database_url is not None
                else UnavailableAuthenticationFlow()
            ),
        )
    )
    include_signed_in(
        create_access_admin_router(
            actor_resolver,
            access_administration_flow
            or (
                PostgresAccessAdministrationFlow(resolved_settings.database_url.get_secret_value())
                if resolved_settings.database_url is not None
                else UnavailableAccessAdministrationFlow()
            ),
            resolved_settings,
        )
    )
    include_signed_in(
        create_audit_router(
            actor_resolver,
            audit_query_flow
            or (
                PostgresAuditEventQueryFlow(resolved_settings.database_url.get_secret_value())
                if resolved_settings.database_url is not None
                else UnavailableAuditEventQueryFlow()
            ),
        )
    )
    include_signed_in(
        create_property_router(
            actor_resolver,
            property_resource_flow
            or (
                PostgresPropertyResourceFlow(resolved_settings.database_url.get_secret_value())
                if resolved_settings.database_url is not None
                else UnavailablePropertyResourceFlow()
            ),
            resolved_settings,
        )
    )
    include_signed_in(
        create_configuration_router(
            actor_resolver,
            configuration_flow
            or cast(
                ConfigurationFlow,
                PostgresConfigurationFlow(resolved_settings.database_url.get_secret_value())
                if resolved_settings.database_url is not None
                else UnavailableConfigurationFlow(),
            ),
            resolved_settings,
            exchange_rate_provider,
        )
    )
    include_signed_in(
        create_unit_router(
            actor_resolver,
            unit_resource_flow
            or (
                PostgresUnitResourceFlow(resolved_settings.database_url.get_secret_value())
                if resolved_settings.database_url is not None
                else UnavailableUnitResourceFlow()
            ),
            resolved_settings,
        )
    )
    include_signed_in(
        create_customer_router(
            actor_resolver,
            customer_resource_flow
            or (
                PostgresCustomerResourceFlow(resolved_settings.database_url.get_secret_value())
                if resolved_settings.database_url is not None
                else UnavailableCustomerResourceFlow()
            ),
            resolved_settings,
        )
    )
    include_signed_in(
        create_reservation_router(
            actor_resolver,
            reservation_resource_flow
            or (
                PostgresReservationResourceFlow(
                    resolved_settings.database_url.get_secret_value(),
                    (
                        resolved_settings.financial_database_url.get_secret_value()
                        if resolved_settings.financial_database_url is not None
                        else None
                    ),
                )
                if resolved_settings.database_url is not None
                else UnavailableReservationResourceFlow()
            ),
            resolved_settings,
        )
    )
    include_signed_in(
        create_lease_router(
            actor_resolver,
            lease_resource_flow
            or (
                PostgresLeaseResourceFlow(resolved_settings.database_url.get_secret_value())
                if resolved_settings.database_url is not None
                else UnavailableLeaseResourceFlow()
            ),
            resolved_settings,
        )
    )
    include_signed_in(
        create_deposit_router(
            actor_resolver,
            deposit_resource_flow
            or cast(
                DepositResourceFlow,
                (
                    PostgresDepositResourceFlow(
                        resolved_settings.database_url.get_secret_value(),
                        (
                            resolved_settings.financial_database_url.get_secret_value()
                            if resolved_settings.financial_database_url is not None
                            else None
                        ),
                    )
                    if resolved_settings.database_url is not None
                    else UnavailableDepositResourceFlow()
                ),
            ),
            resolved_settings,
        )
    )
    include_signed_in(
        create_utility_router(
            actor_resolver,
            utility_resource_flow
            or cast(
                UtilityResourceFlow,
                (
                    PostgresUtilityResourceFlow(
                        resolved_settings.database_url.get_secret_value(),
                        (
                            resolved_settings.financial_database_url.get_secret_value()
                            if resolved_settings.financial_database_url is not None
                            else None
                        ),
                    )
                    if resolved_settings.database_url is not None
                    else UnavailableUtilityResourceFlow()
                ),
            ),
            resolved_settings,
        )
    )
    include_signed_in(
        create_billing_run_router(
            actor_resolver,
            billing_run_flow
            or cast(
                BillingRunFlow,
                (
                    PostgresBillingRunService(
                        resolved_settings.financial_database_url.get_secret_value(),
                        api_service_actor_id=resolved_settings.billing_service_actor_id,
                    )
                    if resolved_settings.financial_database_url is not None
                    else UnavailableBillingRunFlow()
                ),
            ),
            resolved_settings,
        )
    )
    include_signed_in(
        create_invoice_router(
            actor_resolver,
            invoice_flow
            or cast(
                InvoiceFlow,
                (
                    PostgresInvoiceService(
                        resolved_settings.database_url.get_secret_value(),
                        (
                            resolved_settings.financial_database_url.get_secret_value()
                            if resolved_settings.financial_database_url is not None
                            else None
                        ),
                    )
                    if resolved_settings.database_url is not None
                    else UnavailableInvoiceFlow()
                ),
            ),
            resolved_settings,
        )
    )
    include_signed_in(
        create_utility_lease_router(
            actor_resolver,
            utility_lease_flow
            or cast(
                UtilityLeaseFlow,
                (
                    PostgresUtilityLeaseFlow(
                        resolved_settings.database_url.get_secret_value(),
                        (
                            resolved_settings.financial_database_url.get_secret_value()
                            if resolved_settings.financial_database_url is not None
                            else None
                        ),
                    )
                    if resolved_settings.database_url is not None
                    else UnavailableUtilityLeaseFlow()
                ),
            ),
            resolved_settings,
        )
    )
    include_signed_in(
        create_unpaid_initial_termination_router(
            actor_resolver,
            unpaid_initial_flow
            or cast(
                UnpaidInitialFlow,
                (
                    PostgresUnpaidInitialFlow(
                        resolved_settings.financial_database_url.get_secret_value()
                    )
                    if resolved_settings.financial_database_url is not None
                    else UnavailableUnpaidInitialFlow()
                ),
            ),
            resolved_settings,
        )
    )
    include_signed_in(
        create_late_payment_router(
            actor_resolver,
            late_payment_flow
            or cast(
                LatePaymentFlow,
                (
                    PostgresLatePaymentService(
                        resolved_settings.database_url.get_secret_value(),
                        (
                            resolved_settings.financial_database_url.get_secret_value()
                            if resolved_settings.financial_database_url is not None
                            else None
                        ),
                    )
                    if resolved_settings.database_url is not None
                    else UnavailableLatePaymentFlow()
                ),
            ),
            resolved_settings,
        )
    )
    include_signed_in(
        create_enforcement_router(
            actor_resolver,
            enforcement_flow
            or PostgresLeaseEnforcementService(
                resolved_settings.database_url.get_secret_value()
                if resolved_settings.database_url is not None
                else "",
                resolved_settings.financial_database_url.get_secret_value()
                if resolved_settings.financial_database_url is not None
                else None,
            ),
            enforcement_context_flow
            or PostgresEnforcementContext(
                resolved_settings.database_url.get_secret_value()
                if resolved_settings.database_url is not None
                else None,
            ),
            resolved_settings,
        )
    )
    include_signed_in(
        create_financial_reference_router(
            actor_resolver,
            financial_reference_flow
            or FinancialReferenceService(
                resolved_settings.database_url.get_secret_value()
                if resolved_settings.database_url is not None
                else None,
                exchange_rate_provider or UnavailableExchangeRateProvider(),
            ),
            resolved_settings,
        )
    )
    include_signed_in(
        create_customer_ledger_router(
            actor_resolver,
            customer_ledger_flow
            or CustomerLedgerReadService(
                resolved_settings.database_url.get_secret_value()
                if resolved_settings.database_url is not None
                else None
            ),
        )
    )
    include_signed_in(
        create_financial_action_context_router(
            actor_resolver,
            financial_action_context_flow
            or FinancialActionContextService(
                resolved_settings.database_url.get_secret_value()
                if resolved_settings.database_url is not None
                else None
            ),
        )
    )
    include_signed_in(
        create_payment_reversal_context_router(
            actor_resolver,
            payment_reversal_context_flow
            or PaymentReversalContextService(
                resolved_settings.database_url.get_secret_value()
                if resolved_settings.database_url is not None
                else None
            ),
        )
    )
    include_signed_in(
        create_payment_router(
            actor_resolver,
            payment_flow
            or PostgresPaymentFlow(
                resolved_settings.database_url.get_secret_value()
                if resolved_settings.database_url is not None
                else None,
                resolved_settings.financial_database_url.get_secret_value()
                if resolved_settings.financial_database_url is not None
                else None,
                exchange_rate_provider,
            ),
            resolved_settings,
        )
    )
    include_signed_in(
        create_allocation_receipt_router(
            actor_resolver,
            allocation_receipt_flow
            or PostgresAllocationReceiptFlow(
                resolved_settings.database_url.get_secret_value()
                if resolved_settings.database_url is not None
                else None,
                resolved_settings.financial_database_url.get_secret_value()
                if resolved_settings.financial_database_url is not None
                else None,
            ),
            resolved_settings,
        )
    )
    include_signed_in(
        create_credit_refund_router(
            actor_resolver,
            credit_refund_flow
            or PostgresCreditRefundFlow(
                resolved_settings.database_url.get_secret_value()
                if resolved_settings.database_url is not None
                else None,
                resolved_settings.financial_database_url.get_secret_value()
                if resolved_settings.financial_database_url is not None
                else None,
            ),
            resolved_settings,
        )
    )
    return app


app = create_app()
