#!/bin/sh
set -eu

certificate=/etc/nginx/tls/fullchain.pem
private_key=/etc/nginx/tls/privkey.pem
destination=/etc/nginx/conf.d/site.conf

if [ -s "$certificate" ] && [ -s "$private_key" ]; then
    cp /etc/nginx/conditional/site-tls.conf "$destination"
    echo "TLS certificate and key found; enabling HTTPS and the HTTP redirect"
else
    cp /etc/nginx/conditional/site-http.conf "$destination"
    echo "TLS certificate or key missing; serving HTTP only"
fi
