# Phase 1 API 契约

全部管理 API 要求真实管理员会话。GET /health 不鉴权。浏览器 API 使用相对路径。JSON 错误为 {"detail":"中文说明"}，校验错误可能为 FastAPI detail 数组。成功时间戳 UTC。

## 认证

POST /api/auth/login {username,password} -> {user:{id,username,must_change_password},csrf_token}，设置 gatebox_session Cookie。GET /api/auth/me 同一结构，未登录 401。POST /api/auth/logout -> {ok:true}。

POST /api/auth/password {current_password,new_password} -> {ok:true}；新密码至少 12 字符、最多 128，修改后撤销全部会话，返回登录页。首次 must_change_password=true 时仅允许 me/password/logout，其他管理 API 返回 403 “请先修改初始密码”。

所有写操作（登录除外）要求 X-CSRF-Token，值从 login/me 返回，校验与当前会话绑定。默认 HTTPS Cookie Secure/SameSite=None/HttpOnly；纯 HTTP 启动配置 GATEBOX_COOKIE_SECURE=false 才使用 Lax。不得绕过登录。

## 仪表盘

GET /api/dashboard -> {stats:{nodes_total,nodes_enabled,nodes_healthy,egresses_total,egresses_enabled,subscriptions_active},recent_nodes:[节点结构],recent_audit:[{action,resource_type,created_at}],runtime:{platform:"Ubuntu 24.04 target",version:"0.1.0",executor_ready:false,vpngate_ready:false,checker_ready:false,default_egress_id:int|null}}。不报告未检测节点为 healthy。

## 节点

GET /api/nodes?q=&protocol=&status=&page=1&page_size=20 -> {items:[...],total,page,page_size}。节点结构：id,source_type(vpngate/manual),protocol(openvpn/socks5),display_name,country_code,city,host,port,username,has_password(bool),notes,status,is_enabled,first_seen_at,last_check_at,last_success_at,latency_ms,created_at,updated_at。不返回 secret_ref、密文、配置绝对路径。

POST /api/nodes：{display_name:string,host:string,port:int,username:string|null,password:string|null,country_code:string|null,city:string|null,notes:string|null,is_enabled:bool} -> 节点。只支持创建 manual/socks5；事务中创建关联出口 kind=socks5。认证 username/password 必须同时提供或均为空。username 不含冒号；host 验证域名或 IP（IPv6 可去方括号），不得含 URL/路径/控制字符；禁止本服务端口等自引用但不进行联网检测。display_name 1–100、notes <=1000、country_code 两位大写或空、port 1–65535；合法域名允许 ASCII/IDNA。

GET /api/nodes/{id} -> 节点。PATCH /api/nodes/{id} 支持上述字段及 clear_auth:bool；password 留空/省略保留已有密码；clear_auth=true 同时清空账号密码。变更连接参数重置 status=new 和当前检测摘要。PATCH 只启停应保留连接配置。DELETE /api/nodes/{id} -> {ok:true}，删除关联出口和密文。PUT/POST 未实现检测入口返回 501。

## 出口

GET /api/egresses -> {items:[{id,node_id,kind,name,host,port,username,priority,is_enabled,include_in_subscription,is_default,status,created_at}]}，数据包含本机直出（初始禁用）和已建 SOCKS5。status 表达配置而非运行：local=unprovisioned、socks5=configured/new/healthy 等。

PATCH /api/egresses/{id} {name?,priority?(0..1000),is_enabled?,include_in_subscription?} -> 出口。POST /api/egresses/{id}/default -> {ok:true}，仅启用出口可设为默认；默认策略并不改变系统路由。禁用/删除默认出口会清除默认。无单独创建 API，新增 SOCKS5 使用节点页表单；本机直出配置不可删除。

## 订阅

GET /api/subscriptions -> {items:[{id,name,is_enabled,scope:{require_healthy:bool,country_codes:[]},created_at,last_used_at,revoked_at,node_count}]}，不返回 Token/hash。POST /api/subscriptions {name,require_healthy:false,country_codes:[]} -> {id,name,token,paths:{v2ray:"/sub/{token}/v2ray",clash:"/sub/{token}/clash",mihomo:"/sub/{token}/mihomo"},node_count}；仅这一次返回高熵随机 Token。

DELETE /api/subscriptions/{id} -> {ok:true}，软撤销、立即禁止访问。GET /api/subscriptions/{id}/preview?format=clash|mihomo|v2ray -> {content,node_count,format,warnings:[]}。预览 v2ray content 为解码后的多行 socks:// URI；订阅端点返回整体 Base64。Clash/Mihomo content 为合法 YAML。

GET /sub/{token}/{format}：只 Token 鉴权，无 Cookie；format 限 v2ray/clash/mihomo；过期/撤销/错误 Token 404；Cache-Control:private,no-store；不得访问日志中泄漏 token。仅输出节点+出口均启用且 include_in_subscription=true 的 SOCKS5；require_healthy=true 时还要求 status=healthy；不输出 VPS direct 或 VPN Gate OpenVPN。空列表 Clash 使用 REJECT 组，不写 DIRECT 假装 VPS。

SOCKS URI 格式：socks://base64url(username:password)@host:port#percent_encoded_name；无认证不含 userinfo；IPv6 URI 使用方括号。用户名不得有冒号，密码支持冒号。依据 v2rayN SocksFmt 解析源码；仅实现格式兼容，不宣称所有 GUI 客户端已实测。YAML 使用 safe_dump 支持特殊字符并配置 udp:false。Socks 凭据对授权订阅访问者输出是协议必要行为，界面明确私密提醒。

## 设置与占位框架

GET /api/settings -> {node_check_concurrency:4,node_check_timeout_seconds:45,subscription_require_healthy:false,source_refresh_interval_seconds:3600}；PATCH 支持字段范围：1–16、5–120、bool、1800–86400。GET /api/jobs -> {items:[]} 初始真实空记录。GET /api/schedules -> {items:[{id,name,job_type,interval_seconds,is_enabled:false,last_run_at,next_run_at}]}。PATCH /api/schedules/{id} 可保存 interval_seconds>=1800，但请求 is_enabled=true 返回501，执行器未接入。GET /api/pool/summary -> {total,new,healthy,last_fetch_at:null,available:false,message:"VPN Gate 抓取适配器尚未接入"}。

GET /api/audit?limit=20 -> {items:[{id,action,resource_type,resource_id,created_at}]}。不返回敏感审计参数。

## 扩展接口

source_fetcher、checker、executor 模块定义显式 NotImplementedError 的边界，不启动外部命令，不使用模拟通过。所有未实现 actions 对 API 返回明确 501。当前阶段不运行计划 worker，不写假任务成功。
