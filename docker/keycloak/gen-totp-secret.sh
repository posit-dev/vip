#!/bin/sh
set -eu
# Generate a random TOTP seed for the mock-IdP E2E stack's test user, and
# render the realm import file with it. Keeps the shared secret out of the
# repo: nobody needs to know a magic string, they read it off the shared
# /certs volume (see `just mock-idp-totp-secret`).
#
# Two representations are produced because Keycloak and pyotp disagree on
# what a "secret" string means:
#   - Keycloak's HmacOTP uses the realm's otp secretData.value's raw bytes
#     directly as the HMAC-SHA1 key (no decoding).
#   - pyotp (src/vip/totp.py, used by VIP_TEST_TOTP_SECRET) always
#     base32-decodes the secret before using it as the key.
# So the realm gets the raw random string, and everything that calls
# VIP_TEST_TOTP_SECRET gets that same string's base32 encoding.
#
# Output layout:
#   $OUT/totp-secret.b32          -- base32 seed, for VIP_TEST_TOTP_SECRET
#   $IMPORT/realm-vip.json        -- realm template with the raw seed baked in
#
# Idempotent: skips generation if $OUT/totp-secret.b32 already exists, so
# re-running `docker compose up` against a warm volume doesn't rotate the
# secret out from under a running Keycloak.

OUT="${OUT:-/certs}"
IMPORT="${IMPORT:-/import}"
TEMPLATE="${TEMPLATE:-/realm-vip.template.json}"
PLACEHOLDER="__TOTP_SECRET__"

if [ -f "${OUT}/totp-secret.b32" ]; then
  echo "gen-totp-secret: ${OUT}/totp-secret.b32 already exists, skipping generation."
  exit 0
fi

mkdir -p "${OUT}" "${IMPORT}"

# base32-encode stdin (RFC 4648, uppercase alphabet, '=' padding).
b32encode() {
  od -An -v -tu1 | tr -s ' \n' ' ' | awk '
    BEGIN {
      split("ABCDEFGHIJKLMNOPQRSTUVWXYZ234567", alpha, "");
      bitbuf = "";
    }
    {
      for (i = 1; i <= NF; i++) {
        if ($i == "") continue;
        byte = $i;
        bits = "";
        for (b = 7; b >= 0; b--) bits = bits (int(byte / (2 ^ b)) % 2);
        bitbuf = bitbuf bits;
      }
    }
    END {
      while (length(bitbuf) % 5 != 0) bitbuf = bitbuf "0";
      out = "";
      for (i = 1; i <= length(bitbuf); i += 5) {
        chunk = substr(bitbuf, i, 5);
        val = 0;
        for (j = 1; j <= 5; j++) val = val * 2 + substr(chunk, j, 1);
        out = out alpha[val + 1];
      }
      while (length(out) % 8 != 0) out = out "=";
      print out;
    }
  '
}

echo "gen-totp-secret: generating random TOTP seed ..."
raw_secret=$(tr -dc 'A-Za-z0-9' < /dev/urandom | head -c 20)

printf "%s" "${raw_secret}" | b32encode > "${OUT}/totp-secret.b32"

sed "s/${PLACEHOLDER}/${raw_secret}/" "${TEMPLATE}" > "${IMPORT}/realm-vip.json"

echo "gen-totp-secret: done."
