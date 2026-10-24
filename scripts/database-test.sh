#!/bin/sh
set -eu

project_name="prm-database-test-$$"
secret_directory="$(mktemp -d "${TMPDIR:-/tmp}/prm-database-test.XXXXXX")"
umask 077

cleanup() {
  docker compose --project-name "$project_name" down --volumes --remove-orphans >/dev/null 2>&1 || true
  rm -rf "$secret_directory"
}
trap cleanup EXIT HUP INT TERM

redact_container_logs() {
  awk '
    BEGIN {
      paths[1] = ENVIRON["POSTGRES_ADMIN_PASSWORD_FILE"]
      paths[2] = ENVIRON["POSTGRES_MIGRATION_PASSWORD_FILE"]
      paths[3] = ENVIRON["POSTGRES_RUNTIME_PASSWORD_FILE"]
      paths[4] = ENVIRON["POSTGRES_FINANCIAL_PASSWORD_FILE"]
      paths[5] = ENVIRON["POSTGRES_BACKUP_PASSWORD_FILE"]
      paths[6] = ENVIRON["POSTGRES_RESTORE_PASSWORD_FILE"]
      paths[7] = ENVIRON["POSTGRES_HUMAN_ADMIN_PASSWORD_FILE"]
      paths[8] = ENVIRON["POSTGRES_BOOTSTRAP_PASSWORD_FILE"]
      for (secret_index = 1; secret_index <= 8; secret_index++) {
        if ((getline value < paths[secret_index]) > 0 && value != "") {
          secrets[++secret_count] = value
        }
        close(paths[secret_index])
      }
    }
    {
      for (secret_index = 1; secret_index <= secret_count; secret_index++) {
        gsub(secrets[secret_index], "[REDACTED]")
      }
      print
    }
  '
}

POSTGRES_ADMIN_PASSWORD_FILE="$secret_directory/postgres_admin_password"
POSTGRES_MIGRATION_PASSWORD_FILE="$secret_directory/postgres_migration_password"
POSTGRES_RUNTIME_PASSWORD_FILE="$secret_directory/postgres_runtime_password"
POSTGRES_FINANCIAL_PASSWORD_FILE="$secret_directory/postgres_financial_password"
POSTGRES_BACKUP_PASSWORD_FILE="$secret_directory/postgres_backup_password"
POSTGRES_RESTORE_PASSWORD_FILE="$secret_directory/postgres_restore_password"
POSTGRES_HUMAN_ADMIN_PASSWORD_FILE="$secret_directory/postgres_human_admin_password"
POSTGRES_BOOTSTRAP_PASSWORD_FILE="$secret_directory/postgres_bootstrap_password"
POSTGRES_PORT=0

for secret_file in \
  "$POSTGRES_ADMIN_PASSWORD_FILE" \
  "$POSTGRES_MIGRATION_PASSWORD_FILE" \
  "$POSTGRES_RUNTIME_PASSWORD_FILE" \
  "$POSTGRES_FINANCIAL_PASSWORD_FILE" \
  "$POSTGRES_BACKUP_PASSWORD_FILE" \
  "$POSTGRES_RESTORE_PASSWORD_FILE" \
  "$POSTGRES_HUMAN_ADMIN_PASSWORD_FILE" \
  "$POSTGRES_BOOTSTRAP_PASSWORD_FILE"
do
  openssl rand -hex 32 >"$secret_file"
  chmod 0444 "$secret_file"
done

export POSTGRES_ADMIN_PASSWORD_FILE POSTGRES_MIGRATION_PASSWORD_FILE
export POSTGRES_RUNTIME_PASSWORD_FILE POSTGRES_BACKUP_PASSWORD_FILE
export POSTGRES_FINANCIAL_PASSWORD_FILE
export POSTGRES_RESTORE_PASSWORD_FILE POSTGRES_HUMAN_ADMIN_PASSWORD_FILE
export POSTGRES_BOOTSTRAP_PASSWORD_FILE
export POSTGRES_PORT

if docker compose --project-name "$project_name" up --detach --wait postgres >/dev/null; then
  :
else
  startup_status=$?
  printf '%s\n' 'PostgreSQL container startup failed; redacted container logs follow' >&2
  docker compose --project-name "$project_name" logs --no-color postgres 2>&1 \
    | redact_container_logs >&2 || true
  exit "$startup_status"
fi

published_address="$(docker compose --project-name "$project_name" port postgres 5432)"
published_port="${published_address##*:}"
case "$published_port" in
  ''|*[!0-9]*)
    printf '%s\n' 'Unable to resolve the PostgreSQL loopback port' >&2
    exit 1
    ;;
esac

TEST_ADMIN_DATABASE_URL="postgresql://prm_admin:$(cat "$POSTGRES_ADMIN_PASSWORD_FILE")@127.0.0.1:${published_port}/prm"
MIGRATION_DATABASE_URL="postgresql://prm_migrator:$(cat "$POSTGRES_MIGRATION_PASSWORD_FILE")@127.0.0.1:${published_port}/prm"
APP_DATABASE_URL="postgresql://prm_runtime:$(cat "$POSTGRES_RUNTIME_PASSWORD_FILE")@127.0.0.1:${published_port}/prm"
FINANCIAL_DATABASE_URL="postgresql://prm_financial:$(cat "$POSTGRES_FINANCIAL_PASSWORD_FILE")@127.0.0.1:${published_port}/prm"
BACKUP_DATABASE_URL="postgresql://prm_backup:$(cat "$POSTGRES_BACKUP_PASSWORD_FILE")@127.0.0.1:${published_port}/prm"
RESTORE_DATABASE_URL="postgresql://prm_restore:$(cat "$POSTGRES_RESTORE_PASSWORD_FILE")@127.0.0.1:${published_port}/prm"
HUMAN_ADMIN_DATABASE_URL="postgresql://prm_human_admin:$(cat "$POSTGRES_HUMAN_ADMIN_PASSWORD_FILE")@127.0.0.1:${published_port}/prm"
BOOTSTRAP_DATABASE_URL="postgresql://prm_bootstrap:$(cat "$POSTGRES_BOOTSTRAP_PASSWORD_FILE")@127.0.0.1:${published_port}/prm"

export TEST_ADMIN_DATABASE_URL
export MIGRATION_DATABASE_URL
export APP_DATABASE_URL
export FINANCIAL_DATABASE_URL
export BACKUP_DATABASE_URL
export RESTORE_DATABASE_URL
export HUMAN_ADMIN_DATABASE_URL
export BOOTSTRAP_DATABASE_URL

cd backend
database_test_suites='
  tests/test_migrations.py
  tests/test_audit_migration.py
  tests/test_property_migration.py
  tests/test_unit_migration.py
  tests/test_customer_migration.py
  tests/test_configuration_migration.py
  tests/test_reservation_migration.py
  tests/test_reservation_lifecycle_migration.py
  tests/test_reservation_outcome_migration.py
  tests/test_reservation_worker_migration.py
  tests/test_reservation_deposit_draft_migration.py
  tests/test_unit_cleaning_charge_migration.py
  tests/test_hand_back_rent_migration.py
  tests/test_lease_deposit_forfeiture_migration.py
  tests/test_lease_deposit_reversal_draft_migration.py
  tests/test_payment_move_migration.py
  tests/test_final_settlement_migration.py
  tests/test_deposit_receipt_reversal_draft_migration.py
  tests/test_deposit_application_ledger_migration.py
  tests/test_lease_migration.py
  tests/test_lease_lifecycle_migration.py
  tests/test_move_in_migration.py
  tests/test_lease_api_migration.py
  tests/test_lease_enforcement_migration.py
  tests/test_lease_enforcement_api_migration.py
  tests/test_lease_notices_migration.py
  tests/test_lease_termination_migration.py
  tests/test_termination_deposit_migration.py
  tests/test_termination_invoice_migration.py
  tests/test_move_out_inspection_migration.py
  tests/test_move_out_inspection_consumers_migration.py
  tests/test_physical_move_out_migration.py
  tests/test_physical_move_out_consumers_migration.py
  tests/test_deposit_financial_revision_migration.py
  tests/test_deposit_disposition_migration.py
  tests/test_lease_deposit_command_guards_migration.py
  tests/test_deposit_migration.py
  tests/test_deposit_api_migration.py
  tests/test_invoice_migration.py
  tests/test_late_payment_migration.py
  tests/test_payment_migration.py
  tests/test_payment_read_migration.py
  tests/test_financial_reference_migration.py
  tests/test_payment_reversal_context_migration.py
  tests/test_financial_action_context_migration.py
  tests/test_customer_ledger_migration.py
  tests/test_customer_ledger_read_migration.py
  tests/test_payment_confirmation_migration.py
  tests/test_khr_payment_confirmation_migration.py
  tests/test_payment_api_migration.py
  tests/test_financial_fixture_clock_migration.py
  tests/test_payment_allocation_migration.py
  tests/test_allocation_read_migration.py
  tests/test_allocation_receipt_api_migration.py
  tests/test_receipt_migration.py
  tests/test_credit_migration.py
  tests/test_credit_application_migration.py
  tests/test_credit_history_migration.py
  tests/test_refund_migration.py
  tests/test_refund_service_migration.py
  tests/test_credit_refund_read_migration.py
  tests/test_credit_refund_api_migration.py
  tests/test_pet_refund_migration.py
  tests/test_billing_service_migration.py
  tests/test_utility_meter_migration.py
  tests/test_utility_consumption_migration.py
  tests/test_utility_api_migration.py
  tests/test_move_out_final_inputs_migration.py
  tests/test_initial_rent_lease_start_migration.py
  tests/test_one_time_charges_migration.py
  tests/test_debit_adjustment_line_block_migration.py
  tests/test_credit_adjustment_excess_migration.py
  tests/test_rent_nonpayment_recurring_only_migration.py
  tests/test_lease_signing_reservation_migration.py
  tests/test_unpaid_initial_termination_migration.py
  tests/test_initial_rent_override_capability_migration.py
  tests/test_utility_baseline_migration.py
  tests/test_final_utility_invoice_migration.py
  tests/test_utility_unbilled_periods_migration.py
  tests/test_final_settlement_preview_migration.py
  tests/test_final_settlement_draft_migration.py
  tests/test_billing_run_migration.py
  tests/test_lease_timeline_restricted_migration.py
  tests/test_lease_end_date_month_end_migration.py
  tests/test_financial_draft_migration.py
  tests/test_refund_draft_migration.py
  tests/test_refund_signer_recipient_migration.py
  tests/test_final_settlement_refund_migration.py
  tests/test_final_settlement_closed_refusal_migration.py
  tests/test_final_settlement_credit_application_migration.py
  tests/test_final_settlement_confirm_migration.py
  tests/test_credit_customer_refund_migration.py
  tests/test_credit_customer_credit_reversal_migration.py
  tests/test_settlement_correction_migration.py
  tests/test_settlement_extra_charge_migration.py
  tests/test_settlement_charge_reduction_migration.py
  tests/test_settlement_refund_correction_migration.py
  tests/test_deposit_application_reversal_migration.py
  tests/test_settlement_correction_plan_migration.py
  tests/test_settlement_deposit_refund_correction_migration.py
  tests/test_inspection_supersede_after_closure_migration.py
  tests/test_settlement_pet_classification_migration.py
  tests/test_settlement_correction_choice_recheck_migration.py
  tests/test_settlement_refund_return_migration.py
  tests/test_settlement_deposit_refund_return_migration.py
  tests/test_settlement_pet_refund_return_migration.py
  tests/test_settlement_held_value_refund_migration.py
  tests/test_settlement_late_charge_reduction_migration.py
  tests/test_settlement_held_deposit_limit_migration.py
  tests/test_settlement_late_charge_refund_migration.py
  tests/test_settlement_late_charge_deposit_refund_migration.py
  tests/test_settlement_forfeiture_reversal_migration.py
  tests/test_payment_return_migration.py
  tests/test_settlement_returned_payment_migration.py
  tests/test_settlement_real_path_migration.py
  tests/test_payment_return_recovery_migration.py
  tests/test_settlement_pet_payback_migration.py
  tests/test_settlement_deposit_receipt_correction_migration.py
  tests/test_pet_deposit_payback_limit_migration.py
  tests/test_settlement_deposit_receipt_rewrite_migration.py
  tests/test_settlement_deposit_receipt_recovery_line_migration.py
  tests/test_settlement_deposit_receipt_forfeiture_migration.py
  tests/test_settlement_return_reversal_migration.py
  tests/test_returned_payment_after_closure_migration.py
  tests/test_settlement_returned_value_left_migration.py
  tests/test_settlement_return_reversal_swept_migration.py
  tests/test_settlement_return_reversal_successor_migration.py
  tests/test_settlement_return_reversal_own_parts_migration.py
  tests/test_settlement_return_reversal_put_back_migration.py
  tests/test_settlement_return_reversal_changed_payment_migration.py
  tests/test_settlement_returned_value_tie_break_migration.py
  tests/test_settlement_return_reversal_returned_refund_migration.py
  tests/test_settlement_returned_value_other_settlements_migration.py
  tests/test_settlement_return_reversal_companion_migration.py
  tests/test_settlement_return_reversal_other_refunding_take_migration.py
  tests/test_settlement_return_reversal_other_refund_follow_migration.py
  tests/test_settlement_return_reversal_settlement_confirm_migration.py
  tests/test_settlement_pet_classification_superseded_migration.py
  tests/test_settlement_correction_allow_hardening_migration.py
  tests/test_settlement_deposit_paid_charge_reduction_migration.py
  tests/test_adjustment_reversal_migration.py
  tests/test_adjustment_reversal_put_back_migration.py
  tests/test_settlement_adjustment_reversal_migration.py
  tests/test_settlement_payment_move_migration.py
  tests/test_settlement_deposit_receipt_payback_forfeiture_migration.py
  tests/test_settlement_pet_receipt_link_migration.py
  tests/test_pet_payback_recovery_standing_migration.py
  tests/test_pet_payback_restoration_refusal_migration.py
  tests/test_deposit_receipt_record_migration.py
  tests/test_lease_security_deposit_migration.py
  tests/test_deposit_receipt_leftover_migration.py
  tests/test_payment_return_shared_deposit_migration.py
  tests/test_settlement_returned_payment_shared_deposit_migration.py
  tests/test_settlement_returned_payment_payback_first_migration.py
  tests/test_settlement_deposit_receipt_shared_deposit_migration.py
  tests/test_deposit_receipt_refund_out_migration.py
  tests/test_deposit_receipt_reversal_after_refund_migration.py
  tests/test_deposit_required_total_readers_migration.py
  tests/test_settlement_payment_move_credit_migration.py
  tests/test_settlement_relied_on_reversal_migration.py
  tests/test_settlement_returned_credit_refund_migration.py
  tests/test_settlement_forfeiture_reversal_after_closure_migration.py
  tests/test_settlement_preview_waiting_drafts_migration.py
  tests/test_settlement_held_value_wait_migration.py
  tests/test_settlement_closed_change_isolation_migration.py
  tests/test_termination_database_time_migration.py
  tests/test_deposit_increase_ground_delay_migration.py
  tests/test_deposit_created_after_signing_ground_delay_migration.py
  tests/test_settlement_preview_credit_step_wait_migration.py
  tests/test_account_class_migration.py
  tests/test_capability_catalog_migration.py
  tests/test_role_bundle_migration.py
  tests/test_settings_access_migration.py
  tests/test_default_role_bundles_migration.py
  tests/test_settings_access_sign_in_code_migration.py
  tests/test_access_administration_migration.py
  tests/test_settings_access_runtime_revoke_migration.py
  tests/test_access_admin_flow_migration.py
  tests/test_name_hidden_characters_migration.py
  tests/test_auth_flow_migration.py
  tests/test_session_actor_migration.py
  tests/test_session_revocation_time_migration.py
  tests/test_sign_in_wait_migration.py
  tests/test_sign_in_code_migration.py
  tests/test_sign_in_code_enrollment_migration.py
  tests/test_recovery_code_flow_migration.py
  tests/test_recovery_code_sign_in_migration.py
  tests/test_reauthentication_migration.py
  tests/test_one_time_password_migration.py
  tests/test_one_time_password_flow_migration.py
'

for database_test_file in $database_test_suites; do
  if [ ! -f "$database_test_file" ]; then
    printf 'Required PostgreSQL suite is missing: %s\n' "$database_test_file" >&2
    exit 1
  fi
done
for database_test_file in tests/test_*_migration.py; do
  database_test_listed=0
  for required_database_test_file in $database_test_suites; do
    if [ "$required_database_test_file" = "$database_test_file" ]; then
      database_test_listed=1
      break
    fi
  done
  if [ "$database_test_listed" -ne 1 ]; then
    printf 'PostgreSQL suite is omitted from database-test: %s\n' "$database_test_file" >&2
    exit 1
  fi
done

set -- $database_test_suites
REQUIRE_DATABASE_TESTS=1 uv run --extra dev pytest --tb=short --no-header "$@"
