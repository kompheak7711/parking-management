#!/bin/sh
# Makes the local HTTPS certificate of the screens (owner answer (a) to Q-2026-10-21-159, with
# the owner's addition: it covers localhost and the Mac mini's local network name, so an iPad on
# the same Wi-Fi can open the app). Login sub-slice L7c.
#
# It makes a small local certificate authority (kept only on this Mac, in .local/https) and a
# server certificate signed by it. You trust the authority once on the Mac and once on the iPad
# (README, "Local run on the Mac mini"). Nothing is downloaded; macOS's openssl does the work.
# The authority lasts 10 years (Apple's 825-day limit is for server certificates, not for an
# authority you trust yourself); the server certificate lasts 365 days: run this again each year
# and restart the screens. When the authority has less than 60 days left, it says so.
set -eu
. "$(dirname -- "$0")/common.sh"

command -v openssl >/dev/null 2>&1 || prm_fail "openssl is needed (it comes with macOS)."
name=$(prm_checked_hostname) || exit 1

umask 077
mkdir -p "$PRM_HTTPS"
chmod 700 "$PRM_LOCAL" "$PRM_HTTPS"
cd "$PRM_HTTPS"

if [ ! -e local-ca.pem ]; then
  cat > local-ca.cnf <<CONFIG
[req]
distinguished_name = subject
prompt = no
x509_extensions = authority
[subject]
CN = CHETANA local development authority ($name)
[authority]
basicConstraints = critical,CA:TRUE,pathlen:0
keyUsage = critical,keyCertSign,cRLSign
subjectKeyIdentifier = hash
CONFIG
  openssl req -x509 -newkey rsa:3072 -sha256 -days 3650 -nodes \
    -keyout local-ca-key.pem -out local-ca.pem -config local-ca.cnf 2>/dev/null ||
    prm_fail "openssl could not make the local authority."
fi
if ! openssl x509 -in local-ca.pem -noout -checkend 5184000 >/dev/null 2>&1; then
  printf 'The local authority ends within 60 days. Move .local/https away, run this again, and\n'
  printf 'trust the new local-ca.pem on the Mac and the iPad (README step 6).\n'
fi

cat > server.cnf <<CONFIG
[req]
distinguished_name = subject
prompt = no
[subject]
CN = $name.local
[server]
basicConstraints = critical,CA:FALSE
keyUsage = critical,digitalSignature,keyEncipherment
extendedKeyUsage = serverAuth
subjectAltName = DNS:$name.local,DNS:localhost,IP:127.0.0.1
authorityKeyIdentifier = keyid
CONFIG

openssl req -new -newkey rsa:2048 -nodes -keyout server-key.pem -out server.csr \
  -config server.cnf 2>/dev/null || prm_fail "openssl could not make the server key."
openssl x509 -req -in server.csr -CA local-ca.pem -CAkey local-ca-key.pem -CAcreateserial \
  -out server.pem -days 365 -sha256 -extfile server.cnf -extensions server 2>/dev/null ||
  prm_fail "openssl could not sign the server certificate."
rm -f server.csr

printf 'Certificate ready for https://%s.local:5173 (365 days); sign in only at that address.\n' "$name"
printf 'Trust this file once on the Mac and on the iPad: %s/local-ca.pem\n' "$PRM_HTTPS"
