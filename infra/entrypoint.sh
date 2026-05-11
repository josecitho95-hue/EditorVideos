#!/usr/bin/env bash
# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  AutoEdit AI — Container entrypoint                                         ║
# ║                                                                              ║
# ║  1. Wait for Redis to be reachable (required by arq worker + GUI)           ║
# ║  2. Wait for Qdrant to be reachable (required by asset retrieval)           ║
# ║  3. Initialise the SQLite database (idempotent)                             ║
# ║  4. exec the CMD passed by compose (autoedit gui | autoedit worker start)   ║
# ╚══════════════════════════════════════════════════════════════════════════════╝
set -euo pipefail

# ── Colour helpers ─────────────────────────────────────────────────────────────
_info()  { echo -e "\033[0;36m[entrypoint]\033[0m $*"; }
_ok()    { echo -e "\033[0;32m[entrypoint]\033[0m $*"; }
_warn()  { echo -e "\033[0;33m[entrypoint]\033[0m $*"; }
_error() { echo -e "\033[0;31m[entrypoint]\033[0m $*" >&2; }

# ── Wait for a TCP port to accept connections ─────────────────────────────────
wait_for_port() {
    local host="$1"
    local port="$2"
    local label="$3"
    local retries="${4:-30}"
    local delay="${5:-2}"

    _info "Waiting for ${label} at ${host}:${port} ..."
    for ((i = 1; i <= retries; i++)); do
        if python - <<EOF 2>/dev/null
import socket, sys
s = socket.socket()
s.settimeout(2)
try:
    s.connect(("${host}", ${port}))
    s.close()
    sys.exit(0)
except Exception:
    sys.exit(1)
EOF
        then
            _ok "${label} is up."
            return 0
        fi
        _warn "  ${label} not ready — attempt ${i}/${retries}, retrying in ${delay}s..."
        sleep "$delay"
    done
    _error "${label} did not become available after $((retries * delay))s. Aborting."
    exit 1
}

# ── Parse service URLs ─────────────────────────────────────────────────────────
# REDIS_URL format: redis://host:port/db
_redis_host=$(python -c "
from urllib.parse import urlparse
u = urlparse('${REDIS_URL:-redis://redis:6379/0}')
print(u.hostname)
")
_redis_port=$(python -c "
from urllib.parse import urlparse
u = urlparse('${REDIS_URL:-redis://redis:6379/0}')
print(u.port or 6379)
")

# QDRANT_URL format: http://host:port
_qdrant_host=$(python -c "
from urllib.parse import urlparse
u = urlparse('${QDRANT_URL:-http://qdrant:6333}')
print(u.hostname)
")
_qdrant_port=$(python -c "
from urllib.parse import urlparse
u = urlparse('${QDRANT_URL:-http://qdrant:6333}')
print(u.port or 6333)
")

# ── Wait for dependencies ──────────────────────────────────────────────────────
wait_for_port "$_redis_host"  "$_redis_port"  "Redis"  30 2
wait_for_port "$_qdrant_host" "$_qdrant_port" "Qdrant" 40 2

# ── Initialise database ────────────────────────────────────────────────────────
_info "Initialising database (idempotent) ..."
autoedit db init
_ok "Database ready."

# ── Hand over to the CMD ───────────────────────────────────────────────────────
_info "Starting: $*"
exec "$@"
