#!/usr/bin/env bash
# Manage the Sendora app and its database in Docker.
# Usage: ./dev.sh <command> [args]   (run "./dev.sh help" for the list)
set -euo pipefail

cd "$(dirname "$0")"

APP_COMPOSE=(-f docker-compose.yaml -f docker-compose.app.yaml)
TEST_COMPOSE=(-f docker-compose.test.yaml)
APP_PORT="${PORT:-8020}"

die() {
    echo "error: $*" >&2
    exit 1
}

require_docker() {
    command -v docker >/dev/null 2>&1 || die "docker is not installed"
    docker info >/dev/null 2>&1 || die "Docker daemon is not running; start Docker Desktop first"
}

app() {
    docker compose "${APP_COMPOSE[@]}" "$@"
}

usage() {
    cat <<'EOF'
Sendora dev helper

  up                 Build and start the database and the app, wait until healthy
  down               Stop and remove the containers (database data is kept)
  restart [svc...]   Restart all services or the named ones
  build [svc...]     Build images
  ps                 Show service status
  logs [svc]         Follow logs (default: app)
  shell              Open a shell in the app container
  psql [args...]     Open psql in the database container (extra args go to psql)
  check              Run ruff check, ruff format --check and mypy in the test image
  test [args...]     Run pytest in the test image (extra args go to pytest)
  reset-db           Delete the development database volume (asks for confirmation)
  help               Show this help
EOF
}

cmd_up() {
    require_docker
    app up -d --build --wait "$@"
    echo "App is running: http://localhost:${APP_PORT}/v0/docs"
}

cmd_down() {
    require_docker
    app down "$@"
}

cmd_restart() {
    require_docker
    app restart "$@"
}

cmd_build() {
    require_docker
    app build "$@"
}

cmd_ps() {
    require_docker
    app ps "$@"
}

cmd_logs() {
    require_docker
    app logs -f --tail=200 "${1:-app}"
}

cmd_shell() {
    require_docker
    app exec app sh
}

cmd_psql() {
    require_docker
    # Credentials come from the container environment; nothing is printed here.
    app exec postgres sh -c 'exec psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" "$@"' sh "$@"
}

cmd_check() {
    require_docker
    docker compose "${TEST_COMPOSE[@]}" run --build --rm test-app \
        sh -c 'ruff check app tests && ruff format --check app tests && mypy app'
    docker compose "${TEST_COMPOSE[@]}" down
}

cmd_test() {
    require_docker
    docker compose "${TEST_COMPOSE[@]}" run --build --rm test-app pytest "$@"
    docker compose "${TEST_COMPOSE[@]}" down
}

cmd_reset_db() {
    require_docker
    echo "This deletes the development database volume (project_sendora-db) with all its data."
    read -r -p "Type 'yes' to continue: " answer
    [[ "$answer" == "yes" ]] || die "aborted"
    app down -v
}

main() {
    local command="${1:-help}"
    shift || true
    case "$command" in
        up) cmd_up "$@" ;;
        down) cmd_down "$@" ;;
        restart) cmd_restart "$@" ;;
        build) cmd_build "$@" ;;
        ps) cmd_ps "$@" ;;
        logs) cmd_logs "$@" ;;
        shell) cmd_shell "$@" ;;
        psql) cmd_psql "$@" ;;
        check) cmd_check "$@" ;;
        test) cmd_test "$@" ;;
        reset-db) cmd_reset_db "$@" ;;
        help | -h | --help) usage ;;
        *) usage; die "unknown command: $command" ;;
    esac
}

main "$@"
