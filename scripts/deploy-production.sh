#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

# One-command production installer for Ubuntu 24.04.
# Usage without a domain:
#   curl -fsSL https://raw.githubusercontent.com/shangxin913/xnvgateboxlite/main/scripts/deploy-production.sh | sudo bash
# Usage with automatic HTTPS:
#   curl -fsSL https://raw.githubusercontent.com/shangxin913/xnvgateboxlite/main/scripts/deploy-production.sh | sudo env GATEBOX_DOMAIN=gatebox.example.com bash

REPO_URL="${GATEBOX_REPO:-https://github.com/shangxin913/xnvgateboxlite.git}"
REPO_REF="${GATEBOX_REF:-main}"
DOMAIN="${GATEBOX_DOMAIN:-}"
APP_DIR="${GATEBOX_APP_DIR:-/opt/gateboxlite}"
DATA_DIR="${GATEBOX_DATA_DIR:-/var/lib/gateboxlite}"
CONFIG_DIR="${GATEBOX_CONFIG_DIR:-/etc/gateboxlite}"
CADDYFILE="${GATEBOX_CADDYFILE:-/etc/caddy/Caddyfile}"

log() { printf '\n[%s] %s\n' "$1" "$2"; }
fatal() { echo "部署失败：$*" >&2; exit 1; }

[[ "$EUID" -eq 0 ]] || fatal "请使用 root 运行，或通过 sudo bash 执行。"
[[ -r /etc/os-release ]] || fatal "无法识别操作系统。"
. /etc/os-release
[[ "${ID:-}" == "ubuntu" && "${VERSION_ID:-}" == "24.04" ]] || fatal "仅支持 Ubuntu 24.04；当前为 ${PRETTY_NAME:-未知}。"

if [[ -n "$DOMAIN" ]]; then
  [[ "$DOMAIN" != *://* && "$DOMAIN" != */* && "$DOMAIN" != *" "* ]] || fatal "GATEBOX_DOMAIN 只填写域名，例如 gatebox.example.com。"
  [[ "$DOMAIN" == *.* ]] || fatal "GATEBOX_DOMAIN 看起来不是有效域名。"
fi

[[ ! -e "$APP_DIR" && ! -e "$CONFIG_DIR" && ! -e "$DATA_DIR" ]] || fatal "检测到已有 GateBox 路径，拒绝覆盖：$APP_DIR、$CONFIG_DIR 或 $DATA_DIR。请先备份并手动迁移。"

if [[ -e "$CADDYFILE" ]]; then
  fatal "检测到已有 Caddy 配置 $CADDYFILE，拒绝覆盖。"
fi

TMP_DIR="$(mktemp -d /tmp/gateboxlite-deploy.XXXXXX)"
cleanup() { rm -rf "$TMP_DIR"; }
trap cleanup EXIT

log 1/8 "安装系统依赖"
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y ca-certificates curl git python3 python3-venv rsync

log 2/8 "获取 GitHub 源码：$REPO_REF"
git clone --depth 1 --branch "$REPO_REF" "$REPO_URL" "$TMP_DIR/repo"
SOURCE_DIR="$TMP_DIR/repo"
[[ -f "$SOURCE_DIR/scripts/install.sh" && -f "$SOURCE_DIR/app/main.py" ]] || fatal "GitHub 源码不完整。"

log 3/8 "安装 GateBox API、SQLite 和 systemd 服务"
bash "$SOURCE_DIR/scripts/install.sh"

log 4/8 "安装 Caddy"
if ! apt-get install -y caddy; then
  apt-get install -y software-properties-common
  add-apt-repository -y universe
  apt-get update
  apt-get install -y caddy
fi

log 5/8 "配置反向代理"
install -d -m 0755 /etc/caddy
if [[ -n "$DOMAIN" ]]; then
  cat > "$CADDYFILE" <<CADDY
$DOMAIN {
    reverse_proxy 127.0.0.1:8899
}
CADDY
  COOKIE_SECURE=true
else
  cat > "$CADDYFILE" <<CADDY
:80 {
    reverse_proxy 127.0.0.1:8899
}
CADDY
  COOKIE_SECURE=false
fi

caddy validate --config "$CADDYFILE"
sed -i "s/^GATEBOX_COOKIE_SECURE=.*/GATEBOX_COOKIE_SECURE=$COOKIE_SECURE/" "$CONFIG_DIR/environment"
systemctl restart gateboxlite-api
systemctl enable --now caddy
systemctl reload caddy

log 6/8 "配置 UFW（仅在已启用时放行）"
if command -v ufw >/dev/null 2>&1 && ufw status | grep -q 'Status: active'; then
  ufw allow 80/tcp >/dev/null
  [[ -n "$DOMAIN" ]] && ufw allow 443/tcp >/dev/null
fi

log 7/8 "执行本机健康检查"
for attempt in $(seq 1 30); do
  if curl -fsS --max-time 5 http://127.0.0.1:8899/health >/dev/null 2>&1; then break; fi
  [[ "$attempt" -eq 30 ]] && {
    systemctl status gateboxlite-api --no-pager || true
    journalctl -u gateboxlite-api -n 80 --no-pager || true
    fatal "GateBox API 未通过健康检查。"
  }
  sleep 1
done

PUBLIC_IP="$(curl -4fsS --max-time 10 https://api.ipify.org 2>/dev/null || true)"
[[ -n "$PUBLIC_IP" ]] || PUBLIC_IP="$(hostname -I | awk '{print $1}')"
if [[ -n "$DOMAIN" ]]; then
  ACCESS_URL="https://$DOMAIN"
  echo "请确认 $DOMAIN 的 DNS 已解析到本机，并且 80/443 已由云安全组放行。"
else
  ACCESS_URL="http://$PUBLIC_IP"
fi

log 8/8 "输出生产环境登录信息"
PASSWORD="$(python3 -c 'import json; print(json.load(open("/var/lib/gateboxlite/initial-access.txt"))["password"])')"
cat <<SUMMARY

==============================================
GateBox Lite 生产部署完成
==============================================
登录地址：$ACCESS_URL
登录账号：admin
初始密码：$PASSWORD
凭据文件：$DATA_DIR/initial-access.txt
API 内部地址：127.0.0.1:8899
数据目录：$DATA_DIR
配置目录：$CONFIG_DIR
==============================================
首次登录后必须修改密码。
当前版本不会自动开启 VPN/Xray 转发；自定义 SOCKS5 请登录后台后在“节点管理”添加。
SUMMARY
