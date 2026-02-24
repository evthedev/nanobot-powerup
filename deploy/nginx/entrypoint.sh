#!/bin/sh
# Generate a self-signed TLS cert on first boot if one doesn't exist
if [ ! -f /etc/nginx/ssl/cert.pem ]; then
  echo "Generating self-signed TLS certificate..."
  mkdir -p /etc/nginx/ssl
  openssl req -x509 -nodes -newkey rsa:2048 -days 3650 \
    -keyout /etc/nginx/ssl/key.pem \
    -out    /etc/nginx/ssl/cert.pem \
    -subj   "/C=AU/ST=NSW/L=Sydney/O=nanobot/CN=nanobot"
  echo "Certificate generated."
fi

exec nginx -g 'daemon off;'
