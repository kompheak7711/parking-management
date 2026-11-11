#!/bin/sh
# Sets up the three Telegram bots for the test run on the Mac mini (owner ask 07/11/2026).
# Double-click "Set up Telegram test.command" in the repository folder, or:
#
#   sh scripts/local/telegram-setup.sh
#
# It does relay/README.md "Setting it up" steps 1 to 7 for this Mac:
#   1. makes the office keys, the Lease check key and the webhook words in .local/telegram (only
#      you can open it);
#   2. asks for each bot's token in a hidden box and checks it with Telegram;
#   3. signs in to Cloudflare in the browser, makes the relay database and photo bucket, puts the
#      relay online and gives it the keys;
#   4. points each bot at the relay;
#   5. finds the Property, the Owner account and the Staff bot's service actor, and writes the
#      operations file the bot jobs read.
# After it, "Start test app.command" also runs the bot jobs every 10 seconds. While the test app
# is closed, the relay answers the Tenant bot itself (DL-210).
#
# No key, token or password is printed, passed as a command argument or written outside
# .local/telegram. Running it again keeps what is already there and only redoes the rest.
set -eu
. "$(dirname -- "$0")/common.sh"
cd "$PRM_ROOT"

[ -t 0 ] && [ -t 1 ] || prm_fail "Run it in Terminal (double-click Set up Telegram test.command)."
# Typing shows again even if the window is closed while a token is being pasted.
trap 'stty echo 2>/dev/null || true' EXIT INT TERM HUP
WRANGLER_VERSION=4.151.3
TG="$PRM_LOCAL/telegram"
CFG="$TG/wrangler.toml"
BOTS="customer tenant staff"
umask 077
mkdir -p "$TG" "$TG/status" "$TG/media"
chmod 700 "$TG"

wrangler() {
  npx --yes "wrangler@$WRANGLER_VERSION" "$@"
}

# Telegram's Bot API, with the token in a curl config read from standard input, never in a
# command line (printf is built into the shell). $1 is the token file, $2 the method, the rest
# are form fields.
telegram() {
  IFS= read -r token_value < "$1" || [ -n "$token_value" ]
  method=$2
  shift 2
  {
    printf 'url = "https://api.telegram.org/bot%s/%s"\n' "$token_value" "$method"
    for field in "$@"; do
      printf 'data-urlencode = "%s"\n' "$field"
    done
  } | curl --silent --show-error --max-time 30 --config -
}

json_field() {
  # Prints one field of a JSON answer read from standard input (empty when it is missing).
  (cd "$PRM_ROOT/backend" && uv run --quiet python -c '
import json, sys
try:
    value = json.load(sys.stdin)
    for key in sys.argv[1].split("."):
        value = value[key]
    print(value if not isinstance(value, bool) else str(value).lower())
except Exception:
    print("")
' "$1")
}

command -v npx >/dev/null 2>&1 || prm_fail "Node.js is not installed. Install Node.js 22 or newer first."
node_major=$(node -p 'process.versions.node.split(".")[0]')
[ "$node_major" -ge 22 ] || prm_fail "Node.js 22 or newer is needed (this Mac has $(node -v))."
command -v uv >/dev/null 2>&1 || prm_fail "uv is not on your PATH."
command -v openssl >/dev/null 2>&1 || prm_fail "openssl is not installed."

printf '\n1 of 6: making the office keys...\n'
if [ ! -s "$TG/office.pem" ]; then
  openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:3072 -out "$TG/office.pem" 2>/dev/null
fi
openssl pkey -in "$TG/office.pem" -pubout -out "$TG/office.pub.pem"
[ -s "$TG/relay-pull.key" ] || openssl rand -hex 32 > "$TG/relay-pull.key"
# The key of the scrambled Lease check list the relay links tenants with while the app is
# closed (DL-210).
[ -s "$TG/link-check.key" ] || openssl rand -hex 32 > "$TG/link-check.key"
for bot in $BOTS; do
  [ -s "$TG/${bot}_webhook_secret" ] || openssl rand -hex 24 > "$TG/${bot}_webhook_secret"
done
chmod 600 "$TG"/*.pem "$TG"/*.key "$TG"/*_webhook_secret
printf '   Done. The keys stay in .local/telegram on this Mac.\n'

printf '\n2 of 6: the bot tokens from @BotFather.\n'
printf '   Paste each token and press Return. Nothing shows while you paste; that is normal.\n'
for bot in $BOTS; do
  file="$TG/${bot}_bot_token"
  if [ -s "$file" ]; then
    name=$(telegram "$file" getMe | json_field result.username)
    if [ -n "$name" ]; then
      printf '   %s bot: @%s is already set. Press Return to keep it, or paste a new token: ' "$bot" "$name"
    else
      printf '   %s bot: the saved token no longer works. Paste the token: ' "$bot"
    fi
  else
    printf '   %s bot token: ' "$bot"
  fi
  stty -echo
  IFS= read -r token || token=
  stty echo
  printf '\n'
  token=$(printf '%s' "$token" | tr -d ' \r\n')
  if [ -n "$token" ]; then
    case "$token" in
      *[!A-Za-z0-9:_-]*|*:*:*|:*|*:) prm_fail "That does not look like a bot token. Copy it again from @BotFather." ;;
      *:*) ;;
      *) prm_fail "That does not look like a bot token. Copy it again from @BotFather." ;;
    esac
    printf '%s' "$token" > "$file.new"
    chmod 600 "$file.new"
    name=$(telegram "$file.new" getMe | json_field result.username)
    if [ -z "$name" ]; then
      rm -f "$file.new"
      prm_fail "Telegram did not accept the $bot bot token. Check it in @BotFather and run this again."
    fi
    mv "$file.new" "$file"
  fi
  [ -s "$file" ] || prm_fail "The $bot bot token is needed."
  name=$(telegram "$file" getMe | json_field result.username)
  printf '   %s bot: @%s\n' "$bot" "$name"
done

printf '\n3 of 6: signing in to Cloudflare...\n'
if ! wrangler whoami 2>/dev/null | grep -q "You are logged in"; then
  printf '   Your browser opens. Sign in to Cloudflare and press Allow, then come back here.\n'
  wrangler login
fi

printf '\n4 of 6: making the relay database and photo bucket...\n'
d1_id() {
  wrangler d1 list --json 2>/dev/null | (cd "$PRM_ROOT/backend" && uv run --quiet python -c '
import json, sys
try:
    rows = json.load(sys.stdin)
except Exception:
    rows = []
print(next((row.get("uuid", "") for row in rows if row.get("name") == "chetana-relay"), ""))
')
}
database_id=$(d1_id)
if [ -z "$database_id" ]; then
  wrangler d1 create chetana-relay >/dev/null
  database_id=$(d1_id)
fi
[ -n "$database_id" ] || prm_fail "The relay database could not be made. Check your Cloudflare account and run this again."
if ! wrangler r2 bucket list 2>/dev/null | grep -q "chetana-relay-media"; then
  if ! wrangler r2 bucket create chetana-relay-media; then
    prm_fail "The photo bucket could not be made. In the Cloudflare dashboard, open R2, turn it on (it asks for a card; the free use is enough), then run this again."
  fi
fi
# A copy of relay/wrangler.toml with the real database id, kept out of the repository.
sed -e "s|^main = .*|main = \"$PRM_ROOT/relay/src/index.ts\"|" \
  -e "s|^database_id = .*|database_id = \"$database_id\"|" \
  "$PRM_ROOT/relay/wrangler.toml" > "$CFG"
wrangler d1 execute chetana-relay --remote --yes --file "$PRM_ROOT/relay/schema.sql" --config "$CFG"

printf '\n5 of 6: putting the relay online and giving it the keys...\n'
deploy_log="$TG/deploy.log"
# script(1) keeps Terminal attached, so Cloudflare can still ask questions (for example the
# first workers.dev name), and keeps a copy of what it says to find the relay address.
script -q "$deploy_log" npx --yes "wrangler@$WRANGLER_VERSION" deploy --config "$CFG"
relay_url=$(grep -o 'https://chetana-relay\.[A-Za-z0-9.-]*\.workers\.dev' "$deploy_log" | head -n 1)
[ -n "$relay_url" ] || prm_fail "The relay address was not found. Run this again."
put_secret() {
  # $1 is the secret's name in Cloudflare, $2 the file that holds it (read from standard input).
  wrangler secret put "$1" --config "$CFG" < "$2" >/dev/null
}
put_secret OFFICE_PUBLIC_KEY "$TG/office.pub.pem"
put_secret OFFICE_PULL_KEY "$TG/relay-pull.key"
put_secret LINK_CHECK_KEY "$TG/link-check.key"
for bot in $BOTS; do
  upper=$(printf '%s' "$bot" | tr '[:lower:]' '[:upper:]')
  put_secret "${upper}_BOT_TOKEN" "$TG/${bot}_bot_token"
  put_secret "${upper}_WEBHOOK_SECRET" "$TG/${bot}_webhook_secret"
done
printf '   The relay is online at %s\n' "$relay_url"

printf '\n6 of 6: pointing the bots at the relay and writing the settings...\n'
for bot in $BOTS; do
  IFS= read -r webhook_secret < "$TG/${bot}_webhook_secret"
  answer=$(telegram "$TG/${bot}_bot_token" setWebhook "url=$relay_url/telegram/$bot" \
    "secret_token=$webhook_secret" "drop_pending_updates=true")
  [ "$(printf '%s' "$answer" | json_field ok)" = "true" ] \
    || prm_fail "Telegram did not accept the $bot bot's relay address. Run this again."
done
sh scripts/local/database.sh start >/dev/null
IFS= read -r APP_DATABASE_URL < "$PRM_SECRETS/runtime_database_url"
IFS= read -r MIGRATION_DATABASE_URL < "$PRM_SECRETS/migration_database_url"
export APP_DATABASE_URL MIGRATION_DATABASE_URL
cli() {
  (cd "$PRM_ROOT/backend" && uv run --quiet python -m property_rental.telegram_local_setup_cli "$@")
}
ids=$(cli ids) || exit 1
property_id=${ids% *}
owner_id=${ids#* }
service_id=$(cli service-actor --property-id "$property_id" --owner-id "$owner_id") || exit 1
cli write-config --template "$PRM_ROOT/config/deployment/production-operations.json" \
  --folder "$TG" --relay-host "$relay_url" >/dev/null || exit 1
{
  printf 'PRM_PROPERTY_ID=%s\n' "$property_id"
  printf 'PRM_TELEGRAM_ACTOR_ID=%s\n' "$owner_id"
  printf 'PRM_TELEGRAM_SERVICE_ACTOR_ID=%s\n' "$service_id"
} > "$TG/jobs.env"
chmod 600 "$TG/jobs.env" "$TG/wrangler.toml"

printf '\nAll done. Next:\n'
printf '  1. Close the test app if it is open, then double-click Start test app.command.\n'
printf '  2. In Telegram, send the word ping to each bot. Within 3 minutes each one answers.\n'
