#!/usr/bin/env bash
set -euo pipefail
umask 077

if [[ ${EUID} -ne 0 ]]; then
  echo '请以 root 运行：sudo bash scripts/install.sh' >&2
  exit 1
fi
source /etc/os-release
if [[ ${ID:-} != ubuntu || ${VERSION_ID:-} != 24.04 ]]; then
  echo '此安装器仅面向 Ubuntu 24.04；其他系统请参考 README 手动部署。' >&2
  exit 1
fi
SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_DIR=/opt/gateboxlite
DATA_DIR=/var/lib/gateboxlite
CONFIG_DIR=/etc/gateboxlite
if [[ -e "$APP_DIR" || -e "$CONFIG_DIR" ]]; then
  echo '发现已有安装，拒绝覆盖。请先备份，并按 README 的手动更新步骤操作。' >&2
  exit 1
fi
[[ -f "$SOURCE_DIR/app/main.py" && -f "$SOURCE_DIR/migrations/001_initial.sql" ]] || {
  echo '源码不完整，请在完整项目中运行安装器。' >&2; exit 1;
}
apt-get update
apt-get install -y python3 python3-venv ca-certificates rsync
if ! id gateboxlite >/dev/null 2>&1; then
  useradd --system --home-dir "$DATA_DIR" --shell /usr/sbin/nologin gateboxlite
fi
install -d -m 0755 "$APP_DIR"
install -d -m 0700 -o gateboxlite -g gateboxlite "$DATA_DIR"
install -d -m 0750 "$CONFIG_DIR"
for item in app migrations web scripts systemd docs requirements.txt README.md LICENSE THIRD_PARTY.md; do
  [[ -e "$SOURCE_DIR/$item" ]] && rsync -a --exclude '__pycache__' "$SOURCE_DIR/$item" "$APP_DIR/"
done
chown -R root:root "$APP_DIR"
chmod -R a+rX "$APP_DIR"
python3 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/pip" install --disable-pip-version-check -r "$APP_DIR/requirements.txt"
chmod -R a+rX "$APP_DIR/.venv"
cat > "$CONFIG_DIR/environment" <<'ENV'
GATEBOX_DATA_DIR=/var/lib/gateboxlite
GATEBOX_COOKIE_SECURE=true
PYTHONDONTWRITEBYTECODE=1
ENV
chmod 0600 "$CONFIG_DIR/environment"
# Initial access stays on disk with 0600 permissions, never inside source control.
(
  cd "$APP_DIR"
  runuser -u gateboxlite -- env GATEBOX_DATA_DIR="$DATA_DIR" \
    "$APP_DIR/.venv/bin/python" -m app.cli init --username admin --output "$DATA_DIR/initial-access.txt"
)
install -m 0644 "$SOURCE_DIR/systemd/gateboxlite-api.service" /etc/systemd/system/gateboxlite-api.service
systemctl daemon-reload
systemctl enable --now gateboxlite-api.service
for attempt in {1..20}; do
  if "$APP_DIR/.venv/bin/python" -c "from urllib.request import urlopen; assert urlopen('http://127.0.0.1:8899/health', timeout=2).status == 200" 2>/dev/null; then
    echo 'API 已启动于 127.0.0.1:8899。请通过 HTTPS 反向代理访问。'
    echo '初始账号保存在 /var/lib/gateboxlite/initial-access.txt，请用 sudo cat 查看并首次改密。'
    echo '未修改防火墙；未开启 VPN/Xray 或系统代理转发。'
    exit 0
  fi
  sleep 1
done
echo 'API 未通过健康检查。请运行 journalctl -u gateboxlite-api -n 80 查看日志。' >&2
exit 1
