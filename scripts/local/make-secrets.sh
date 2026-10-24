#!/bin/sh
# Makes the local database password files and the four database address files in the ignored
# .local/secrets folder (login sub-slice L7c). A file that is already there is kept as it is.
# Nothing secret is printed or passed as a command argument: the passwords come from openssl's
# random source straight into their files, and the addresses are written by Python, which
# reads the password files itself. The password files are readable by all (0444, as in
# scripts/database-test.sh), because Docker mounts each one into the database container, where
# its start-up script reads them as the container's postgres user; the folder itself stays
# private (0700), so no other account on the Mac can reach them.
set -eu
. "$(dirname -- "$0")/common.sh"

command -v openssl >/dev/null 2>&1 || prm_fail "openssl is needed (it comes with macOS)."
umask 077
mkdir -p "$PRM_SECRETS"
chmod 700 "$PRM_LOCAL" "$PRM_SECRETS"

made=0
for name in $PRM_PASSWORD_NAMES; do
  file="$PRM_SECRETS/postgres_${name}_password"
  if [ ! -e "$file" ]; then
    openssl rand -hex 24 > "$file"
    made=$((made + 1))
  fi
  chmod 0444 "$file"
done

python3 -I - "$PRM_SECRETS" "$PRM_POSTGRES_PORT" <<'PYTHON'
import os
import sys
from urllib.parse import quote

folder, port = sys.argv[1], sys.argv[2]
if not port.isdigit():
    sys.exit("POSTGRES_PORT must be a number")
addresses = {
    "migration_database_url": ("prm_migrator", "migration"),
    "runtime_database_url": ("prm_runtime", "runtime"),
    "financial_database_url": ("prm_financial", "financial"),
    "bootstrap_database_url": ("prm_bootstrap", "bootstrap"),
}
for file_name, (role, password_name) in addresses.items():
    target = os.path.join(folder, file_name)
    if os.path.exists(target):
        continue
    with open(os.path.join(folder, f"postgres_{password_name}_password"), encoding="utf-8") as f:
        password = f.read().strip()
    if not password:
        sys.exit(f"the {password_name} password file is empty")
    address = f"postgresql://{role}:{quote(password, safe='')}@127.0.0.1:{port}/prm"
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as f:
        f.write(address + "\n")
PYTHON

printf 'Password files made: %s of 8 (the others were already there). Address files ready.\n' "$made"
printf 'Folder: %s (only your account can open it).\n' "$PRM_SECRETS"
