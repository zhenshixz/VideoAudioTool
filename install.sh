#!/bin/bash
# ==============================================================================
#  VideoAudioTool 极简一键部署脚本 (终极稳固版)
# ==============================================================================

set -e

echo -e "\n======================================================="
echo -e "🚀 正在为您准备服务器环境并安装 VideoAudioTool 核心服务..."
echo -e "=======================================================\n"

# 1. 检查并安装系统级依赖
if command -v apt-get &> /dev/null; then
    echo "[1/4] 📦 检测到 Debian/Ubuntu 系统..."
    sudo apt-get update -y
    sudo apt-get install -y git python3-pip python3-venv curl xz-utils
elif command -v yum &> /dev/null; then
    echo "[1/4] 📦 检测到 CentOS/RedHat 系统..."
    sudo yum install -y git python3-pip curl xz || true
else
    echo "❌ 无法识别的操作系统包管理器，请手动安装 git, python3-pip, curl"
    exit 1
fi

# 安装全平台通用的 FFmpeg 静态核心包（绕过所有源冲突和找不到包的问题）
if ! command -v ffmpeg &> /dev/null; then
    echo "⏬ 正在通过国内加速节点下载 FFmpeg 静态核心..."
    curl -L -# -o ffmpeg.tar.xz https://mirror.ghproxy.com/https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-linux64-gpl.tar.xz
    tar xf ffmpeg.tar.xz
    sudo cp ffmpeg-master-latest-linux64-gpl/bin/ffmpeg /usr/local/bin/
    sudo cp ffmpeg-master-latest-linux64-gpl/bin/ffprobe /usr/local/bin/
    sudo chmod +x /usr/local/bin/ffmpeg /usr/local/bin/ffprobe
    rm -rf ffmpeg*
fi

PROJECT_DIR=$(pwd)
echo -e "\n[2/4] 📁 检测到当前项目路径: $PROJECT_DIR"

# 2. 准备 Python 虚拟环境
echo -e "\n[3/4] 🐍 正在配置专属 Python 运行环境..."
if [ ! -d "venv" ]; then
    python3 -m venv venv || python3 -m virtualenv venv || true
fi

# 某些老系统上 venv 可能创建失败，直接使用系统级 pip 安装
if [ -f "venv/bin/activate" ]; then
    source venv/bin/activate
    # 使用阿里云镜像源极速安装，忽略版本冲突
    pip install -i https://mirrors.aliyun.com/pypi/simple/ --upgrade pip || true
    pip install -i https://mirrors.aliyun.com/pypi/simple/ -r requirements.txt
    PYTHON_EXEC="$PROJECT_DIR/venv/bin/python"
    GUNICORN_EXEC="$PROJECT_DIR/venv/bin/gunicorn"
else
    pip3 install -i https://mirrors.aliyun.com/pypi/simple/ -r requirements.txt
    PYTHON_EXEC="python3"
    GUNICORN_EXEC="gunicorn"
fi

# 3. 配置 Systemd 后台自启守护进程
echo -e "\n[4/4] ⚙️ 正在向操作系统注册持久化后台服务..."

SERVICE_FILE="/etc/systemd/system/videoaudiotool.service"
sudo bash -c "cat > $SERVICE_FILE" <<EOF
[Unit]
Description=VideoAudioTool Gunicorn Web Service
After=network.target

[Service]
User=root
Group=root
WorkingDirectory=$PROJECT_DIR
ExecStart=$GUNICORN_EXEC --workers 2 --bind 0.0.0.0:5000 app:app
Restart=always
RestartSec=2

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable videoaudiotool
sudo systemctl restart videoaudiotool

echo -e "\n======================================================="
echo -e "🎉 部署大功告成！"
echo -e "======================================================="
echo -e "👉 您的应用正在后台稳定运行，并且具有防崩溃守护机制。"
echo -e "👉 请确保您的 阿里云安全组 和 宝塔面板安全设置 中已开放 5000 端口。"
echo -e "👉 您现在可以直接通过 http://公网IP:5000 访问应用。\n"
