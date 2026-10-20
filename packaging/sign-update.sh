#!/bin/sh
# Run only after build/evidence verification. No project code or tests run here.
# Encrypted PEM keys prompt on the terminal; never pass a passphrase in argv/env.
set -eu
test "$#" -eq 3 || { echo 'Usage: sh packaging/sign-update.sh MANIFEST SIGNATURE PRIVATE_KEY' >&2; exit 2; }
test -f "$1"
test -f "$3"
openssl pkeyutl -sign -rawin -inkey "$3" -in "$1" -out "$2"
chmod 0644 "$2"
