import base64
import json
from urllib.parse import quote

import yaml


def select_nodes(conn, scope):
    clauses = ["n.protocol='socks5'", "n.is_enabled=1", "e.kind='socks5'", "e.is_enabled=1", "e.include_in_subscription=1"]
    values = []
    if scope.get("require_healthy", False):
        clauses.append("n.status='healthy'")
    codes = scope.get("country_codes", [])
    if codes:
        clauses.append("n.country_code IN (" + ",".join("?" for _ in codes) + ")")
        values.extend(codes)
    return conn.execute("SELECT n.* FROM nodes n JOIN egresses e ON e.node_id=n.id WHERE " + " AND ".join(clauses) + " ORDER BY e.priority,n.id", values).fetchall()


def token_scope(row):
    return json.loads(row["scope_json"])


def socks_uri(node, password=None):
    authority = ""
    if node["username"] is not None:
        userinfo = base64.urlsafe_b64encode((node["username"] + ":" + password).encode("utf-8")).decode("ascii").rstrip("=")
        authority = userinfo + "@"
    host = "[" + node["host"] + "]" if ":" in node["host"] else node["host"]
    return f"socks://{authority}{host}:{node['port']}#{quote(node['display_name'], safe='')}"


def build_subscription(conn, security, token_row, format_name, *, encoded=False):
    scope = token_scope(token_row)
    nodes = select_nodes(conn, scope)
    passwords = {}
    for node in nodes:
        if node["secret_ref"] is not None:
            secret = conn.execute("SELECT ciphertext FROM secrets WHERE id=?", (node["secret_ref"],)).fetchone()
            if secret is None:
                raise RuntimeError("节点认证密文缺失")
            passwords[node["id"]] = security.decrypt(secret["ciphertext"])
    if format_name == "v2ray":
        content = "\n".join(socks_uri(node, passwords.get(node["id"])) for node in nodes)
        if encoded:
            content = base64.b64encode(content.encode("utf-8")).decode("ascii")
    else:
        proxies, names = [], []
        used = {"GATEBOX", "DIRECT", "REJECT"}
        for node in nodes:
            name = node["display_name"]
            if name in used:
                name = f"{name} ({node['id']})"
                while name in used:
                    name += "_"
            used.add(name)
            names.append(name)
            proxy = {"name": name, "type": "socks5", "server": node["host"], "port": node["port"], "udp": False}
            if node["username"] is not None:
                proxy.update(username=node["username"], password=passwords[node["id"]])
            proxies.append(proxy)
        document = {"proxies": proxies, "proxy-groups": [{"name": "GATEBOX", "type": "select", "proxies": names or ["REJECT"]}], "rules": ["MATCH,GATEBOX"]}
        content = yaml.safe_dump(document, allow_unicode=True, sort_keys=False, default_flow_style=False)
    warnings = ["订阅及预览为私密数据，包含客户端连接所需代理凭据，请勿公开。", "仅输出启用的 SOCKS5 引用；不包含 VPS 本机直出或 VPN Gate OpenVPN；未部署 VPS 转发执行层。"]
    if not scope.get("require_healthy", False):
        warnings.append("健康过滤未开启，未检测配置可能被输出；配置不代表链路可用。")
    if not nodes:
        warnings.append("没有符合筛选条件的节点；Clash/Mihomo 使用 REJECT 回退。")
    return content, len(nodes), warnings
