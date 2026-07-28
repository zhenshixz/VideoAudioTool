#!/usr/bin/env bash
#
# VideoAudioTool one-click installer for Alibaba Cloud Linux 3.
# Run with: sudo bash install.sh

set -Eeuo pipefail

APP_NAME="videoaudiotool"
APP_USER="videoaudio"
APP_PORT="5000"
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${PROJECT_DIR}/.venv"
DATA_DIR="/var/lib/${APP_NAME}"
SERVICE_FILE="/etc/systemd/system/${APP_NAME}.service"
UPDATE_SERVICE_FILE="/etc/systemd/system/${APP_NAME}-update.service"
UPDATE_TIMER_FILE="/etc/systemd/system/${APP_NAME}-update.timer"

step() {
    printf "\n[%s] %s\n" "$1" "$2"
}

die() {
    printf "\n[ERROR] %s\n" "$1" >&2
    printf "查看安装日志中的上一条错误即可定位原因。\n" >&2
    exit 1
}

on_error() {
    local line_no="$1"
    printf "\n[ERROR] 安装在第 %s 行失败，请把这一屏内容发给维护者。\n" "$line_no" >&2
}

trap 'on_error "$LINENO"' ERR

if [[ "${EUID}" -ne 0 ]]; then
    die "请使用 sudo bash install.sh 运行。"
fi

if [[ ! -f "${PROJECT_DIR}/app.py" || ! -f "${PROJECT_DIR}/requirements.txt" ]]; then
    die "当前目录不是完整的 VideoAudioTool 项目。"
fi

if [[ ! -f /etc/os-release ]]; then
    die "无法识别服务器操作系统。"
fi

# shellcheck disable=SC1091
source /etc/os-release
if [[ "${ID:-}" != "alinux" || "${VERSION_ID:-}" != "3" ]]; then
    die "此脚本仅适用于 Alibaba Cloud Linux 3，当前系统为 ${PRETTY_NAME:-unknown}。"
fi

if command -v dnf >/dev/null 2>&1; then
    PKG="dnf"
elif command -v yum >/dev/null 2>&1; then
    PKG="yum"
else
    die "未找到 dnf 或 yum。"
fi

printf "============================================================\n"
printf " VideoAudioTool 一键部署（Alibaba Cloud Linux 3）\n"
printf "============================================================\n"
printf "项目目录: %s\n" "${PROJECT_DIR}"

step "1/7" "安装 Git、curl 和 Python 3.11"
"${PKG}" install -y git curl python3.11

if ! python3.11 -m pip --version >/dev/null 2>&1; then
    "${PKG}" install -y python3.11-pip
fi

python3.11 --version
python3.11 -m pip --version

step "2/7" "安装 FFmpeg"
if ! command -v ffmpeg >/dev/null 2>&1 || ! command -v ffprobe >/dev/null 2>&1; then
    "${PKG}" install -y epel-release

    if ! rpm -q rpmfusion-free-release >/dev/null 2>&1; then
        if ! "${PKG}" install -y \
            https://download1.rpmfusion.org/free/el/rpmfusion-free-release-8.noarch.rpm; then
            "${PKG}" install -y \
                https://mirrors.rpmfusion.org/free/el/rpmfusion-free-release-8.noarch.rpm
        fi
    fi

    "${PKG}" install -y ffmpeg
fi

ffmpeg -version 2>&1 | awk 'NR == 1 { print }'
ffprobe -version 2>&1 | awk 'NR == 1 { print }'

step "3/7" "创建 Python 独立运行环境"
if [[ ! -x "${VENV_DIR}/bin/python" ]]; then
    rm -rf "${VENV_DIR}"
    python3.11 -m venv "${VENV_DIR}"
fi

"${VENV_DIR}/bin/python" -m pip install \
    --disable-pip-version-check \
    -i https://mirrors.aliyun.com/pypi/simple/ \
    --upgrade pip

"${VENV_DIR}/bin/python" -m pip install \
    --disable-pip-version-check \
    -i https://mirrors.aliyun.com/pypi/simple/ \
    -r "${PROJECT_DIR}/requirements.txt"

"${VENV_DIR}/bin/python" -c "import flask, gunicorn; print('Flask 和 Gunicorn 安装成功')"

step "4/7" "创建安全的应用账户和数据目录"
if ! id "${APP_USER}" >/dev/null 2>&1; then
    useradd --system --home-dir "${DATA_DIR}" --shell /sbin/nologin "${APP_USER}"
fi

install -d -o "${APP_USER}" -g "${APP_USER}" -m 0750 "${DATA_DIR}"
chmod -R a+rX "${PROJECT_DIR}"
chmod 0750 "${PROJECT_DIR}/update.sh"

step "5/7" "注册开机自启服务"
cat > "${SERVICE_FILE}" <<EOF
[Unit]
Description=VideoAudioTool Web Service
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${APP_USER}
Group=${APP_USER}
WorkingDirectory=${PROJECT_DIR}
Environment=VIDEO_TOOL_SERVER_MODE=1
Environment=VIDEO_TOOL_DATA_DIR=${DATA_DIR}
Environment=VIDEO_TOOL_MAX_UPLOAD_GB=2
Environment=PYTHONUNBUFFERED=1
Environment=PYTHONDONTWRITEBYTECODE=1
ExecStart=${VENV_DIR}/bin/gunicorn --workers 1 --threads 4 --timeout 1800 --bind 0.0.0.0:${APP_PORT} app:app
Restart=on-failure
RestartSec=3
TimeoutStopSec=30
NoNewPrivileges=true
PrivateTmp=true
ProtectHome=true
ProtectSystem=full
ReadWritePaths=${DATA_DIR}

[Install]
WantedBy=multi-user.target
EOF

cat > "${UPDATE_SERVICE_FILE}" <<EOF
[Unit]
Description=Check and deploy VideoAudioTool updates
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
ExecStart=/usr/bin/bash ${PROJECT_DIR}/update.sh
EOF

cat > "${UPDATE_TIMER_FILE}" <<EOF
[Unit]
Description=Check VideoAudioTool GitHub updates every minute

[Timer]
OnBootSec=2min
OnUnitActiveSec=1min
AccuracySec=10s
Persistent=true
Unit=${APP_NAME}-update.service

[Install]
WantedBy=timers.target
EOF

systemctl daemon-reload
systemctl enable "${APP_NAME}.service"
systemctl restart "${APP_NAME}.service"

if [[ -d "${PROJECT_DIR}/.git" ]]; then
    systemctl enable --now "${APP_NAME}-update.timer"
else
    printf "[WARN] 当前目录不是 Git 仓库，应用可以运行，但不会自动更新。\n"
fi

step "6/7" "检查网页是否正常"
healthy="0"
for _ in {1..30}; do
    if curl -fsS "http://127.0.0.1:${APP_PORT}/api/health" >/dev/null; then
        healthy="1"
        break
    fi
    sleep 1
done

if [[ "${healthy}" != "1" ]]; then
    systemctl status "${APP_NAME}.service" --no-pager || true
    journalctl -u "${APP_NAME}.service" -n 50 --no-pager || true
    die "服务未通过健康检查。"
fi

step "7/7" "尝试开放系统防火墙端口"
if systemctl is-active --quiet firewalld; then
    firewall-cmd --permanent --add-port="${APP_PORT}/tcp"
    firewall-cmd --reload
    printf "系统防火墙已开放 TCP %s。\n" "${APP_PORT}"
else
    printf "firewalld 未运行，无需处理系统防火墙。\n"
fi

PRIVATE_IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
PUBLIC_IP="$(
    curl -4 -fsS --max-time 3 https://api.ipify.org 2>/dev/null || true
)"

printf "\n============================================================\n"
printf " 部署成功\n"
printf "============================================================\n"
printf "本机检查: http://127.0.0.1:%s\n" "${APP_PORT}"
if [[ -n "${PRIVATE_IP}" ]]; then
    printf "内网地址: http://%s:%s\n" "${PRIVATE_IP}" "${APP_PORT}"
fi
if [[ -n "${PUBLIC_IP}" ]]; then
    printf "公网地址: http://%s:%s\n" "${PUBLIC_IP}" "${APP_PORT}"
else
    printf "公网地址: http://你的ECS公网IP:%s\n" "${APP_PORT}"
fi
printf "\n还需要在阿里云安全组和宝塔防火墙中放行 TCP %s。\n" "${APP_PORT}"
printf "以后只需 git push，服务器会在约 1 分钟内自动更新。\n"
printf "\n常用排错命令：\n"
printf "  sudo systemctl status %s --no-pager\n" "${APP_NAME}"
printf "  sudo journalctl -u %s -n 100 --no-pager\n" "${APP_NAME}"
printf "  sudo systemctl status %s-update.timer --no-pager\n" "${APP_NAME}"
