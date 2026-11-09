#!/usr/bin/env bash
set -euo pipefail
if [[ ${EUID} -ne 0 ]]; then
  echo '请以 root 运行：sudo bash scripts/uninstall.sh' >&2; exit 1
fi
if [[ ${1:-} == --help ]]; then
  echo '移除 /opt/gateboxlite 和 API 服务，保留 /var/lib/gateboxlite 数据、主钥及 /etc/gateboxlite 配置。'; exit 0
fi
if [[ ! -f /etc/systemd/system/gateboxlite-api.service ]]; then
  echo '未找到 GateBox Lite service，拒绝删除任何目录。' >&2; exit 1
fi
read -r -p '将停止服务并删除 /opt/gateboxlite 源码。保留数据和配置。输入 UNINSTALL 确认：' answer
[[ "$answer" == UNINSTALL ]] || { echo '已取消'; exit 0; }
systemctl disable --now gateboxlite-api.service
rm -f /etc/systemd/system/gateboxlite-api.service
systemctl daemon-reload
rm -rf -- /opt/gateboxlite
echo '服务和源码已移除，/var/lib/gateboxlite、/etc/gateboxlite 仍保留。未卸载共享依赖或删除系统用户。'
