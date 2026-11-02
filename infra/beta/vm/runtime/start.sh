#!/bin/sh
set -eu
# Operator entry point; never invoked by rendering or local checks.
[ "$(id -u)" = 0 ] && [ "$(uname -s)" = Linux ] || { echo 'Linux host root required' >&2; exit 1; }
[ "$#" = 2 ] || { echo 'Usage: start.sh ABSOLUTE_RELEASE_DIRECTORY data|prepare|run|stop' >&2; exit 1; }
release="$1"
action="$2"
case "$action" in data|prepare|run|stop) ;; *) exit 1 ;; esac
umask 077
install -d -m 0700 /run/cosmabot
exec 9>/run/cosmabot/runtime.lock
flock -n 9 || { echo 'Another runtime/migration operation is active; it was left running' >&2; exit 1; }
compose() {
    if command -v docker-compose >/dev/null 2>&1; then
        docker-compose --project-name cosmabot-staging --file "$release/compose.json" "$@"
    else
        docker compose --project-name cosmabot-staging --file "$release/compose.json" "$@"
    fi
}
if [ "$action" = stop ]; then
    compose stop --timeout 120
    exit 0
fi
python3 "$release/host-preflight.py" "$release"
sh "$release/imds-guard.sh"
compose config --quiet
case "$action" in
    data) compose up -d --wait --wait-timeout 180 postgres redis ;;
    prepare)
        # Include stopped, paused, restarting, orphan and one-off project containers.
        # Check the command itself: an inventory error must not look like an empty host.
        if ! inventory="$(docker container ls --all \
            --filter label=com.docker.compose.project=cosmabot-staging \
            --format '{{.ID}}:{{.Label "com.docker.compose.service"}}:{{.State}}')"; then
            echo 'Container inventory failed; database preparation refused' >&2; exit 1
        fi
        if [ -n "$inventory" ]; then
            while IFS= read -r row; do
                case "$row" in
                    *:*:*) ;;
                    *) echo 'Malformed container inventory; database preparation refused' >&2; exit 1 ;;
                esac
                container=${row%%:*}
                fields=${row#*:}
                service=${fields%%:*}
                state=${fields#*:}
                case "$container" in
                    ''|*[!a-f0-9]*) echo 'Malformed container inventory; database preparation refused' >&2; exit 1 ;;
                esac
                case "$service" in
                    ''|*[!a-zA-Z0-9_.-]*) echo 'Malformed service label; database preparation refused' >&2; exit 1 ;;
                esac
                case "$state" in
                    created|running|paused|restarting|removing|exited|dead) ;;
                    *) echo 'Unknown container state; database preparation refused' >&2; exit 1 ;;
                esac
                case "$service:$state" in
                    postgres:*|redis:*|*:exited|*:dead) ;;
                    *) echo 'Stop application and prior preparation containers for the reviewed maintenance window' >&2; exit 1 ;;
                esac
            done <<EOF
$inventory
EOF
        fi
        compose --profile prepare run --rm --no-deps database_prepare
        ;;
    run) compose up -d --wait --wait-timeout 180 ;;
esac
