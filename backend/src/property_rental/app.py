"""FastAPI application factory."""

import re
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable
from contextlib import AbstractAsyncContextManager, AsyncExitStack, asynccontextmanager
from logging import Logger
from time import perf_counter
from typing import Final, cast
from uuid import uuid4

import psycopg
from fastapi import FastAPI, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from property_rental.access_admin_api import (
    AccessAdministrationConflict,
    AccessAdministrationFlow,
    AccessAdministrationNotFound,
    AccessAdministrationUnavailable,
    UnavailableAccessAdministrationFlow,
    create_access_admin_router,
)
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
    UnavailableAuthenticationFlow,
    create_auth_router,
)
from property_rental.billing_run import PostgresBillingRunService
from property_rental.billing_run_api import (
    BillingRunFlow,
    UnavailableBillingRunFlow,
    create_billing_run_router,
)
from property_rental.configuration_api import (
    ConfigurationFlow,
    ExchangeRateProvider,
    PostgresConfigurationFlow,
    UnavailableConfigurationFlow,
    create_configuration_router,
)
from property_rental.customer import CustomerVersionConflict
from property_rental.customer_api import (
    CustomerIdempotencyKeyReused,
    CustomerLifecycleConflict,
    CustomerResourceFlow,
    CustomerReuseConflict,
    PostgresCustomerResourceFlow,
    UnavailableCustomerResourceFlow,
    create_customer_router,
    customer_idempotency_key_reused_response,
    customer_reuse_conflict_response,
)
from property_rental.deposit import DepositIdempotencyKeyReused
from property_rental.deposit_api import (
    DepositResourceFlow,
    PostgresDepositResourceFlow,
    UnavailableDepositResourceFlow,
    create_deposit_router,
    deposit_idempotency_key_reused_response,
)
from property_rental.identity import ActorResolver, deny_unauthenticated_actor
from property_rental.invoice import (
    InvoiceIdempotencyKeyReused,
    InvoiceVersionConflict,
    PostgresInvoiceService,
)
from property_rental.invoice_api import (
    InvoiceFlow,
    UnavailableInvoiceFlow,
    create_invoice_router,
    invoice_idempotency_key_reused_response,
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
from property_rental.logging import create_application_logger
from property_rental.payment_allocation import AllocationIdempotencyKeyReused
from property_rental.payment_api import (
    PaymentFlow,
    PostgresPaymentFlow,
    create_payment_router,
    payment_key_reused_response,
)
from property_rental.payment_confirmation import PaymentConfirmationKeyReused
from property_rental.property_api import (
    PostgresPropertyResourceFlow,
    PropertyResourceFlow,
    PropertyVersionConflict,
    UnavailablePropertyResourceFlow,
    create_property_router,
)
from property_rental.receipt import ReceiptIdempotencyKeyReused
from property_rental.reservation_api import (
    PostgresReservationResourceFlow,
    ReservationResourceFlow,
    UnavailableReservationResourceFlow,
    create_reservation_router,
)
from property_rental.settings import Settings
from property_rental.unit_api import (
    PostgresUnitResourceFlow,
    UnavailableUnitResourceFlow,
    UnitResourceFlow,
    UnitVersionConflict,
    create_unit_router,
)
from property_rental.utility_api import (
    PostgresUtilityResourceFlow,
    UnavailableUtilityResourceFlow,
    UtilityResourceFlow,
    UtilityResourceVersionConflict,
    create_utility_router,
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
    r"utility-billing/preview$)"
)
BILLING_RUN_API_PATH_PATTERN: Final = re.compile(
    r"^/api/v1/(?:properties/[^/]+/billing-runs/(?:rent|utilities)$|billing-runs/[^/]+$)"
)
INVOICE_API_PATH_PATTERN: Final = re.compile(
    r"^/api/v1/(?:properties/[^/]+/(?:invoices(?:/|$)|billing-capabilities$)|invoices(?:/|$))"
)
LATE_PAYMENT_API_PATH_PATTERN: Final = re.compile(
    r"^/api/v1/(?:invoices/[^/]+/late-payment-(?:review|decision)$|"
    r"late-payment-charges(?:/|$))"
)
PAYMENT_API_PATH_PATTERN: Final = re.compile(
    r"^/api/v1/(?:properties/[^/]+/payments(?:/|$)|(?:payments|payment-allocations|receipts)(?:/|$))"
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
    actor_resolver: ActorResolver = deny_unauthenticated_actor,
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
    payment_flow: PaymentFlow | None = None,
    allocation_receipt_flow: AllocationReceiptFlow | None = None,
) -> FastAPI:
    """Build an application instance from validated settings."""
    resolved_settings = settings or Settings()
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
            try:
                yield
            finally:
                logger.info("application stopping", extra={"event": "application.stopping"})

    app = FastAPI(
        title=resolved_settings.service_name,
        version=resolved_settings.build_version,
        lifespan=lifespan,
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

    @app.exception_handler(AuthenticationUnavailable)
    async def authentication_unavailable(
        request: Request,
        _: AuthenticationUnavailable,
    ) -> JSONResponse:
        return error_response(status.HTTP_503_SERVICE_UNAVAILABLE, request.state.request_id)

    @app.exception_handler(AuthenticationRateLimited)
    async def authentication_rate_limited(
        request: Request,
        _: AuthenticationRateLimited,
    ) -> JSONResponse:
        return error_response(status.HTTP_429_TOO_MANY_REQUESTS, request.state.request_id)

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
    async def deposit_idempotency_key_reused(
        request: Request,
        _: DepositIdempotencyKeyReused,
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
            or PAYMENT_API_PATH_PATTERN.match(request.url.path)
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

    app.include_router(
        create_api_router(
            resolved_settings,
            readiness_check,
            actor_resolver,
        )
    )
    app.include_router(
        create_auth_router(
            resolved_settings,
            authentication_flow or UnavailableAuthenticationFlow(),
        )
    )
    app.include_router(
        create_access_admin_router(
            actor_resolver,
            access_administration_flow or UnavailableAccessAdministrationFlow(),
            resolved_settings,
        )
    )
    app.include_router(
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
    app.include_router(
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
    app.include_router(
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
    app.include_router(
        create_unit_router(
            actor_resolver,
            unit_resource_flow
            or (
                PostgresUnitResourceFlow(resolved_settings.database_url.get_secret_value())
                if resolved_settings.database_url is not None
                else UnavailableUnitResourceFlow()
            ),
        )
    )
    app.include_router(
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
    app.include_router(
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
    app.include_router(
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
    app.include_router(
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
    app.include_router(
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
    app.include_router(
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
    app.include_router(
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
    app.include_router(
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
    app.include_router(
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
    app.include_router(
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
    return app


app = create_app()
