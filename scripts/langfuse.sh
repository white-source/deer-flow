#!/usr/bin/env bash
# Start/stop self-hosted Langfuse for local DeerFlow tracing.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LF_DIR="$REPO_ROOT/docker/langfuse"
UPSTREAM="$LF_DIR/docker-compose.upstream.yml"
OVERRIDE="$LF_DIR/docker-compose.override.yml"
ENV_FILE="$LF_DIR/.env"
ENV_EXAMPLE="$LF_DIR/.env.example"

download_compose() {
    if [[ ! -f "$UPSTREAM" ]]; then
        echo "Downloading Langfuse docker-compose.yml..."
        curl -fsSL "https://raw.githubusercontent.com/langfuse/langfuse/main/docker-compose.yml" -o "$UPSTREAM"
    fi
}

# Compose merges `ports` by appending; override alone cannot drop upstream host bindings.
patch_compose_for_deerflow() {
    download_compose
    local changed=0
    if grep -qE '[[:space:]]+- 3000:3000' "$UPSTREAM"; then
        sed -i 's/- 3000:3000/- 3100:3000/' "$UPSTREAM"
        echo "Langfuse UI host port: 3100 (DeerFlow frontend uses 3000)."
        changed=1
    fi
    if grep -qE '127\.0\.0\.1:6379:6379' "$UPSTREAM"; then
        sed -i 's/127.0.0.1:6379:6379/127.0.0.1:6399:6379/' "$UPSTREAM"
        echo "Langfuse Redis host port: 6399 (container still listens on 6379)."
        changed=1
    fi
    if [[ "$changed" -eq 0 ]]; then
        : # already patched
    fi
}

rand_b64() {
    openssl rand -base64 "${1:?}"
}

rand_hex() {
    openssl rand -hex "${1:?}"
}

ensure_env() {
    if [[ -f "$ENV_FILE" ]]; then
        return
    fi
    echo "Creating $ENV_FILE with generated secrets (local dev defaults for DB/Redis/MinIO)..."
    cat >"$ENV_FILE" <<EOF
# Auto-generated $(date -u +%Y-%m-%dT%H:%M:%SZ) — see docker/langfuse/README.md
NEXTAUTH_URL=http://localhost:3100
NEXTAUTH_SECRET=$(rand_b64 32)
SALT=$(rand_b64 16)
ENCRYPTION_KEY=$(rand_hex 32)
EOF
}

compose() {
    docker compose -f "$UPSTREAM" -f "$OVERRIDE" --env-file "$ENV_FILE" "$@"
}

# All services required for trace ingestion (order matches compose dependencies).
LANGFUSE_SERVICES=(postgres clickhouse minio redis langfuse-worker langfuse-web)

_verify_langfuse_stack() {
    local missing=0
    echo ""
    echo "Container status (need all six running for traces):"
    compose ps
    echo ""
    for svc in "${LANGFUSE_SERVICES[@]}"; do
        if ! compose ps "$svc" 2>/dev/null | grep -qE 'Up|running'; then
            echo "MISSING or not running: ${svc}"
            missing=1
        fi
    done
    if [[ "$missing" -eq 1 ]]; then
        echo ""
        echo "Trace ingestion requires langfuse-worker. Check logs:"
        echo "  $0 logs-worker"
        return 1
    fi
    echo "All Langfuse services are running."
    return 0
}

cmd="${1:-help}"
shift || true

case "$cmd" in
up)
    patch_compose_for_deerflow
    ensure_env
    # Full stack is required for trace ingestion (postgres, clickhouse, minio,
    # redis, langfuse-worker, langfuse-web). Starting only langfuse-web shows
    # a healthy UI but traces never appear.
    compose up -d "${LANGFUSE_SERVICES[@]}"
    echo ""
    echo "Langfuse UI: http://localhost:3100"
    echo "Wait 1–2 minutes for ClickHouse migrations, then open the UI."
    echo "After signup, add project keys to $REPO_ROOT/.env (see docker/langfuse/README.md)."
    _verify_langfuse_stack || exit 1
    ;;
down)
    patch_compose_for_deerflow
    [[ -f "$ENV_FILE" ]] || ensure_env
    compose down
    ;;
status)
    patch_compose_for_deerflow
    [[ -f "$ENV_FILE" ]] || { echo "No $ENV_FILE — run: make langfuse-up"; exit 1; }
    _verify_langfuse_stack || exit 1
    ;;
logs)
    patch_compose_for_deerflow
    [[ -f "$ENV_FILE" ]] || ensure_env
    compose logs -f langfuse-web
    ;;
logs-worker)
    patch_compose_for_deerflow
    [[ -f "$ENV_FILE" ]] || ensure_env
    compose logs -f langfuse-worker
    ;;
help | *)
    echo "Usage: $0 {up|down|status|logs|logs-worker}"
    exit 0
    ;;
esac
