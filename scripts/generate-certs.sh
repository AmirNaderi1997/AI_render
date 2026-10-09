#!/usr/bin/env bash
set -euo pipefail

# Development only. This self-signed certificate is not trusted by browsers.
# For production, obtain/renew certificates with Let's Encrypt (for example,
# Certbot) and place the matching files at:
#   certs/fullchain.pem
#   certs/privkey.pem
# Keep the private key readable only by the deployment operator. The Compose
# nginx service mounts ./certs read-only at /etc/nginx/tls.

if [ "$#" -ne 1 ] || [ -z "$1" ]; then
    echo "Usage: $0 <development-hostname>" >&2
    echo "Example: $0 localhost" >&2
    exit 2
fi

host=$1
if [[ ! "$host" =~ ^[A-Za-z0-9.-]+$ ]]; then
    echo "ERROR: hostname may contain only letters, digits, dots, and hyphens." >&2
    exit 2
fi

if ! command -v openssl >/dev/null 2>&1; then
    echo "ERROR: openssl is required." >&2
    exit 1
fi

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cert_dir="$repo_root/certs"
if [ -e "$cert_dir/fullchain.pem" ] || [ -e "$cert_dir/privkey.pem" ]; then
    echo "ERROR: a TLS file already exists under $cert_dir; move it aside before generating a development certificate." >&2
    exit 1
fi
mkdir -p "$cert_dir"
umask 077
openssl req -x509 -nodes -newkey rsa:2048 -sha256 -days 365 \
    -keyout "$cert_dir/privkey.pem" \
    -out "$cert_dir/fullchain.pem" \
    -subj "/CN=$host" \
    -addext "subjectAltName=DNS:$host"
chmod 600 "$cert_dir/privkey.pem"
chmod 644 "$cert_dir/fullchain.pem"

echo "Created development-only self-signed certificate files in $cert_dir"
echo "For production, replace them with the matching Let's Encrypt fullchain.pem and privkey.pem."
