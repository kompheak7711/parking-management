#!/bin/sh
set -eu

repo="${PROPERTY_RENTAL_REPO:-/Users/sokompheak/Development/property-rental-management}"
exec python3 "$repo/scripts/openclaw_dispatch.py"
