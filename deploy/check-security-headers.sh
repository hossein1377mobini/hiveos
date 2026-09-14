#!/bin/sh
# Proves the security headers actually reach every route, in a real nginx.
#
# This exists because nginx's add_header does not inherit across levels: a
# location that declares any add_header of its own silently discards every
# header from the server block. Reading the config cannot catch that - only
# serving a request can. Run it after touching nginx.conf:
#
#   docker run --rm \
#     -v "$PWD/nginx.conf:/etc/nginx/conf.d/default.conf:ro" \
#     -v "$PWD/security-headers.conf:/etc/nginx/conf.d/security-headers.conf:ro" \
#     -v "$PWD/check-security-headers.sh:/check.sh:ro" \
#     nginx:1.27-alpine sh /check.sh
#
# Exits non-zero if any route is missing a header, so CI can gate on it.
set -e

FIXTURE=/tmp/html
mkdir -p "$FIXTURE/assets" "$FIXTURE/fonts"
echo '<!doctype html><title>fixture</title>' > "$FIXTURE/index.html"
echo x > "$FIXTURE/assets/app.js"
echo x > "$FIXTURE/fonts/f.woff2"
echo x > "$FIXTURE/favicon.svg"
echo x > "$FIXTURE/apple-touch-icon.png"

# Serve from the fixture and stub the upstream so no backend is needed.
cp /etc/nginx/conf.d/security-headers.conf /tmp/security-headers.conf
sed 's#/usr/share/nginx/html#'"$FIXTURE"'#g; s#proxy_pass http://backend:8000;#return 200 ok;#' \
  /etc/nginx/conf.d/default.conf > /tmp/d1.conf
sed 's#include /etc/nginx/conf.d/security-headers.conf;#include /tmp/security-headers.conf;#g' \
  /tmp/d1.conf > /tmp/default.conf
printf 'events{}\nhttp{\ninclude /tmp/default.conf;\n}\n' > /tmp/nginx.conf
nginx -t -c /tmp/nginx.conf
nginx -c /tmp/nginx.conf

fail=0
for path in /index.html /assets/app.js /fonts/f.woff2 /favicon.svg /apple-touch-icon.png /chat; do
  headers=$(curl -s -o /dev/null -D- "http://127.0.0.1$path")
  missing=''
  for name in content-security-policy x-frame-options strict-transport-security x-content-type-options referrer-policy permissions-policy; do
    if ! printf '%s' "$headers" | grep -qi "^$name:"; then missing="$missing $name"; fi
  done
  if [ -n "$missing" ]; then
    printf 'FAIL %-24s missing:%s\n' "$path" "$missing"
    fail=1
  else
    printf 'ok   %-24s %s\n' "$path" "$(printf '%s' "$headers" | grep -i '^cache-control' | head -1 | tr -d '\r')"
  fi
done

if [ "$fail" -ne 0 ]; then
  echo 'security headers are not reaching every route'
  exit 1
fi
echo 'all routes carry the full security header set'