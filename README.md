# GateBox Lite

面向自有 Ubuntu 24.04 VPS 的轻量代理出口管理后台，独立实现并以 MIT 许可证开放源代码。本仓库是 **B 版 MVP 的第一阶段 v0.1.0**，不是完整 xnvgatebox 替代品。

已实现的目标是管理员认证、SQLite 持久化、SOCKS5 节点与出口配置、订阅管理、配置仪表盘和后续任务的数据框架。VPN Gate 真实抓取、链路检测、周期 Worker、Xray/VPS 接入和真实隧道尚未接入，页面会明确显示限制，不把未检测节点当作健康节点。

## 数据面边界

当前订阅直接引用第三方 SOCKS5 地址；客户端直接连这些代理，不经过 VPS 转发。因此客户端必须能访问该 SOCKS5 地址。普通 SOCKS5 协议自身不提供加密，跨公网使用需考虑额外受保护传输。

本机直出只保存 VPS 的出口配置，没有 VPS 接入监听时不能供远端客户端使用，所以不进入订阅。VPN Gate 候选的 OpenVPN 配置也不会被伪造为 VLESS。默认出口仅为后续路由编排配置，不改系统路由，不提供未经验证的 TCP 隧道、UDP 或 IPv6 数据面支持。

Clash/Mihomo YAML 和 v2rayN SOCKS 分享链接经过格式回归；尚未进行所有桌面客户端版本实测。凭据和订阅都是私密信息。订阅可能按协议包含 SOCKS5 用户名和密码；仅有授权者才应持有 Token 和配置。

## 开发启动

需要 Python 3.12，推荐 Ubuntu 24.04。在项目根目录执行：

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
export GATEBOX_DATA_DIR="$PWD/.runtime"
mkdir -p "$GATEBOX_DATA_DIR" && chmod 0700 "$GATEBOX_DATA_DIR"
# 仅纯 HTTP 本地开发。公网 HTTPS / Manus Preview 保持 true。
export GATEBOX_COOKIE_SECURE=false
.venv/bin/python -m app.cli init --username admin --output "$PWD/.runtime/initial-access.txt"
cat .runtime/initial-access.txt
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8899 --no-access-log
```

浏览器打开 `http://127.0.0.1:8899`。使用随机初始密码登录后，必须先改为至少 12 字符的新密码。改密撤销会话，需要重新登录。初始化会拒绝覆盖已有管理员，不存在弱默认密码或开发免登录开关。

环境文件不会被应用自动加载；`.env.example` 只是说明。运行前 export，systemd 使用 `EnvironmentFile` 加载。公网 HTTPS 和嵌入 Preview 设置 `GATEBOX_COOKIE_SECURE=true`（默认），Cookie 为 HttpOnly/Secure/SameSite=None；纯 HTTP 模式独立切换为非 Secure/Lax。

## Ubuntu 24.04 源码安装

仅在你要部署的 VPS 运行以下命令；本项目开发预览并未对用户 VPS 执行安装。安装器安装 Python 依赖、创建低权限 gateboxlite 用户，API 仅监听 127.0.0.1:8899，不自动修改防火墙。

```bash
sudo bash scripts/install.sh
sudo cat /var/lib/gateboxlite/initial-access.txt
sudo systemctl status gateboxlite-api
sudo journalctl -u gateboxlite-api -n 80
```

部署目录是 `/opt/gateboxlite`，数据在 `/var/lib/gateboxlite`，环境配置在 `/etc/gateboxlite/environment`。安装器遇到已有安装拒绝覆盖。公网管理建议由已有 Caddy/Nginx 提供 HTTPS，反向代理到 `127.0.0.1:8899`，并禁用代理访问日志或对 `/sub/` 的 Token 路径脱敏。没有域名时可使用 SSH 转发；如使用纯 HTTP，显式将环境配置设为 `GATEBOX_COOKIE_SECURE=false` 并重启，不要将这种模式直接公开到互联网。

### 一键生产部署

公开仓库提供 Ubuntu 24.04 一键部署脚本。脚本从 GitHub 拉取当前 `main`，拒绝覆盖已有 GateBox 数据/配置，安装 systemd 服务和 Caddy，并在结束时输出访问地址、`admin` 用户名和一次性初始密码。没有域名时使用 VPS 公网 IP 和 HTTP：

```bash
curl -fsSL https://raw.githubusercontent.com/shangxin913/xnvgateboxlite/main/scripts/deploy-production.sh | sudo bash
```

有域名并已把 A/AAAA 记录解析到 VPS 时，设置域名后 Caddy 会自动申请 HTTPS 证书：

```bash
curl -fsSL https://raw.githubusercontent.com/shangxin913/xnvgateboxlite/main/scripts/deploy-production.sh | sudo env GATEBOX_DOMAIN=gatebox.example.com bash
```

脚本默认只放行已启用 UFW 中的 80 端口；域名模式额外放行 443。云厂商安全组仍需手动放行 SSH，以及 HTTP 模式的 80 或 HTTPS 模式的 80/443。脚本不会自动修改已有 Caddy 配置、系统路由、VPN、Xray 或代理转发。

Caddy 参考（需要用户自己的域名、DNS 与 80/443 端口；请按实际环境配置，不由安装器执行）：

```caddyfile
gatebox.example.com {
    reverse_proxy 127.0.0.1:8899
}
```

## 备份、恢复与更新

SQLite 在线备份同时复制主钥；备份含私密数据，权限 0600，不要上传公共仓库：

```bash
sudo /opt/gateboxlite/.venv/bin/python /opt/gateboxlite/scripts/backup.py \
  --data-dir /var/lib/gateboxlite --output /root/gatebox-backup.tar.gz
```

`--output` 已存在会拒绝覆盖。恢复前停止 API，解压到新建的私有临时目录并核对文件，恢复 `app.db` 和 `master.key` 到数据目录，删除旧的 `app.db-wal`/`app.db-shm`，设置数据目录 gateboxlite 所有权、0700，文件0600，再启动并执行健康检查。只恢复数据库、不恢复主钥将无法解密 SOCKS5 密码。不要把备份直接解压进源码目录。

第一阶段没有在线更新器。手动更新先备份并停止服务，再更新 `/opt/gateboxlite` 的源代码（保留独立数据与主钥），安装相应依赖并运行新增数据库迁移。v0.1.0 只有初始迁移；后续版本迁移应按版本说明执行，不重复执行初始 SQL。

```bash
sudo bash /opt/gateboxlite/scripts/uninstall.sh
```

卸载会要求输入 `UNINSTALL`，仅删除固定服务和源码路径，默认保留数据、主钥与配置，不删除共享依赖、其他代理或系统防火墙规则。

## 功能位置

`/` 为仪表盘；`/nodes` 管理节点；`/egresses` 保存出口策略；`/subscriptions` 创建订阅与预览配置；`/pool` 展示候选池扩展入口；`/tasks` 展示任务与计划；`/settings` 调整后续检测并发与超时。管理 API 均受会话保护，写请求带 CSRF，订阅使用独立高熵 Token，撤销即失效。

完整 API 见 [docs/api-contract.md](docs/api-contract.md)，当前数据库见 [docs/database.md](docs/database.md)，阶段进度见 [TODO.md](TODO.md)。历史架构在 docs 下 v0 文件，仅供对照，不用旧 SQL 初始化。

## 回归

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m compileall -q app scripts
bash -n scripts/install.sh scripts/uninstall.sh
```

Python API 和 Ubuntu 安装不需要 Node。前端在途回执安全回归可选使用 Node 22+；未安装 Node 时该项明确跳过。可单独执行 `node --experimental-default-type=module tests/frontend_security.mjs`。`requirements.lock.txt` 留存本次解析的完整依赖版本，便于重现。

测试使用独立临时目录和 SQLite，不向真实 VPN Gate 发请求、不连接代理、不修改预览数据。Ubuntu 安装脚本的语法及权限边界已做静态检查，仍需要一台独立 Ubuntu 24.04 VPS 完成真实安装与网络验收。

附带的 Dockerfile 是可选启动声明，不代表托管生产发布已完成。外部容器部署必须给 `/data` 挂载私有持久卷并通过 CLI 初始化管理员；不要把可丢失的容器文件系统当作 SQLite 和主钥的持久存储。本次只启动开发预览，不发布正式代理服务。

## 开源边界

代码未复制 xnvgatebox，产品边界参考原项目。原项目 GPL-3.0-only 不应被移除或改作 MIT；若未来引入原项目代码，需重新审查衍生作品许可证。第三方资产及依赖见 [THIRD_PARTY.md](THIRD_PARTY.md)，Lucide 的 ISC/Feather MIT 文本随静态资产保留。
