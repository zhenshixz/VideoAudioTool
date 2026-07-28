#!/usr/bin/env bash
#
# Called by systemd once per minute. It deploys origin/main and automatically
# rolls back when dependency installation or the health check fails.

set -Eeuo pipefail

APP_NAME="videoaudiotool"
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${PROJECT_DIR}/.venv"
HEALTH_URL="http://127.0.0.1:5000/api/health"
LOCK_FILE="/run/${APP_NAME}-update.lock"

exec 9>"${LOCK_FILE}"
if ! flock -n 9; then
    exit 0
fi

if [[ ! -d "${PROJECT_DIR}/.git" ]]; then
    echo "[update] Skipped: ${PROJECT_DIR} is not a Git repository."
    exit 0
fi

git_safe() {
    git -c safe.directory="${PROJECT_DIR}" -C "${PROJECT_DIR}" "$@"
}

wait_for_health() {
    local attempt
    for attempt in {1..30}; do
        if curl -fsS "${HEALTH_URL}" >/dev/null 2>&1; then
            return 0
        fi
        sleep 1
    done
    return 1
}

CURRENT_COMMIT="$(git_safe rev-parse HEAD)"

ORIGIN_URL="$(git_safe remote get-url origin)"
FETCH_URLS=("${ORIGIN_URL}")
if [[ "${ORIGIN_URL}" == https://github.com/* ]]; then
    FETCH_URLS+=(
        "https://ghfast.top/${ORIGIN_URL}"
        "https://gh-proxy.com/${ORIGIN_URL}"
    )
fi

FETCH_SUCCEEDED=0
for fetch_url in "${FETCH_URLS[@]}"; do
    echo "[update] Trying source: ${fetch_url}"
    if timeout 60 git_safe \
        -c http.lowSpeedLimit=1024 \
        -c http.lowSpeedTime=20 \
        fetch --quiet "${fetch_url}" \
        "+refs/heads/main:refs/remotes/origin/main"; then
        FETCH_SUCCEEDED=1
        break
    fi
done

if [[ "${FETCH_SUCCEEDED}" -ne 1 ]]; then
    echo "[update] All GitHub sources are temporarily unreachable; the next timer run will retry."
    exit 0
fi

REMOTE_COMMIT="$(git_safe rev-parse origin/main)"
if [[ "${CURRENT_COMMIT}" == "${REMOTE_COMMIT}" ]]; then
    exit 0
fi

echo "[update] Deploying ${REMOTE_COMMIT} (previous ${CURRENT_COMMIT})"

rollback() {
    echo "[update] Deployment failed. Rolling back to ${CURRENT_COMMIT}."
    git_safe reset --hard "${CURRENT_COMMIT}"
    "${VENV_DIR}/bin/python" -m pip install \
        --disable-pip-version-check \
        -i https://mirrors.aliyun.com/pypi/simple/ \
        -r "${PROJECT_DIR}/requirements.txt"
    systemctl restart "${APP_NAME}.service"
    if wait_for_health; then
        echo "[update] Rollback completed."
    else
        echo "[update] Rollback also failed. Check: journalctl -u ${APP_NAME} -n 100"
    fi
}

trap rollback ERR

git_safe reset --hard "${REMOTE_COMMIT}"
"${VENV_DIR}/bin/python" -m pip install \
    --disable-pip-version-check \
    -i https://mirrors.aliyun.com/pypi/simple/ \
    -r "${PROJECT_DIR}/requirements.txt"

systemctl restart "${APP_NAME}.service"
wait_for_health

trap - ERR
echo "[update] Deployment succeeded: ${REMOTE_COMMIT}"
