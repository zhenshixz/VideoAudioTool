# VideoAudioTool 小白部署说明

适用服务器：Alibaba Cloud Linux 3，x86_64。

## 第一次部署

### 1. 把代码推送到 GitHub

在本地项目中提交并推送本次修改：

```bash
git add .
git commit -m "Add safe one-click deployment"
git push
```

### 2. 在服务器运行一条命令

进入阿里云或宝塔终端，复制：

```bash
cd /opt/VideoAudioTool && git pull && sudo bash install.sh
```

脚本显示“部署成功”后，程序已经启动并设置为开机自启。

### 3. 开放 5000 端口

需要同时检查两个地方：

1. 阿里云 ECS 安全组：入方向放行 TCP 5000。
2. 宝塔面板安全：放行 TCP 5000。

然后访问：

```text
http://8.138.252.219:5000
```

测试期间建议把安全组来源限制为自己的公网 IP，不要长期对
`0.0.0.0/0` 开放。

## 以后如何更新

本地修改完成后只需要：

```bash
git add .
git commit -m "描述本次修改"
git push
```

服务器每分钟检查一次 GitHub。发现更新后自动安装依赖、重启并检查。
如果新版本启动失败，会自动恢复上一版本。

不需要 GitHub Webhook，也不需要 GitHub Actions。

## 常用排错命令

查看程序状态：

```bash
sudo systemctl status videoaudiotool --no-pager
```

查看最近日志：

```bash
sudo journalctl -u videoaudiotool -n 100 --no-pager
```

查看自动更新定时器：

```bash
sudo systemctl status videoaudiotool-update.timer --no-pager
```

立即手动检查一次更新：

```bash
sudo systemctl start videoaudiotool-update.service
```

重启程序：

```bash
sudo systemctl restart videoaudiotool
```

## 域名备案完成后

备案完成后，用宝塔创建站点并反向代理到：

```text
http://127.0.0.1:5000
```

然后申请 HTTPS 证书，并从安全组关闭公网 5000 端口。程序本身不需要
重新安装。
