#!/bin/bash
# ==============================================================================
#  VideoAudioTool 极简一键部署脚本 (适用于 Ubuntu/Debian/CentOS)
# ==============================================================================

set -e

echo -e "\n======================================================="
echo -e "🚀 正在为您准备服务器环境并安装 VideoAudioTool 核心服务..."
echo -e "=======================================================\n"

# 1. 检查并安装系统级依赖 (FFmpeg, Python3)
if command -v apt-get &> /dev/null; then
    echo "[1/4] 📦 检测到 Debian/Ubuntu 系统，正在安装底层组件..."
    sudo apt-get update -y
    sudo apt-get install -y ffmpeg git python3-pip python3-venv
elif command -v yum &> /dev/null; then
    echo "[1/4] 📦 检测到 CentOS/RedHat 系统，正在安装底层组件..."
    sudo yum install -y epel-release || true
    sudo yum install -y git python3-pip
    if ! command -v ffmpeg &> /dev/null; then
        echo "⏬ 正在通过国内加速节点下载 FFmpeg 静态免安装版..."
        wget -qO /usr/local/bin/ffmpeg https://mirror.ghproxy.com/https://github.com/eugeneware/ffmpeg-static/releases/download/b4.4/linux-x64
        wget -qO /usr/local/bin/ffprobe https://mirror.ghproxy.com/https://github.com/eugeneware/ffprobe-static/releases/download/b4.4/linux-x64
        chmod +x /usr/local/bin/ffmpeg /usr/local/bin/ffprobe
    fi
else
    echo "❌ 无法识别的操作系统包管理器，请手动安装 ffmpeg, git, python3-pip"
    exit 1
fi

# 确保位于代码目录
PROJECT_DIR=$(pwd)
echo -e "\n[2/4] 📁 检测到当前项目路径: $PROJECT_DIR"

# 2. 准备 Python 虚拟环境
echo -e "\n[3/4] 🐍 正在配置专属 Python 运行环境..."
if [ ! -d "venv" ]; then
    python3 -m venv venv
fi

# 激活虚拟环境并安装依赖
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
pip install gunicorn

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
# 启动 Gunicorn，绑定所有网卡的 5000 端口，工作线程数为 2
ExecStart=$PROJECT_DIR/venv/bin/gunicorn --workers 2 --bind 0.0.0.0:5000 app:app
# 遇到错误或收到 exit(0) 指令时，自动在 2 秒后重启
Restart=always
RestartSec=2

[Install]
WantedBy=multi-user.target
EOF

# 重新加载 Systemd，开启自启并立刻启动服务
sudo systemctl daemon-reload
sudo systemctl enable videoaudiotool
sudo systemctl restart videoaudiotool

echo -e "\n======================================================="
echo -e "🎉 部署大功告成！"
echo -e "======================================================="
echo -e "👉 请确保您的 阿里云安全组 和 宝塔面板安全设置 中已开放 5000 端口。"
echo -e "👉 您现在可以直接通过 http://服务器公网IP:5000 访问应用。"
echo -e "👉 【自动更新机制已就绪】: 在 GitHub 仓库设置 Webhook 指向 http://公网IP:5000/api/webhook (事件选 push)。未来只要推送代码，系统会自动热更新！\n"
