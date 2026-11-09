# XNV GateBox Lite

## B 版 MVP 整体架构设计

- 目标平台：Ubuntu 24.04 LTS
- 产品形态：部署在用户 VPS 上的代理出口管理服务
- 第一阶段范围：VPN Gate 候选池、自定义 SOCKS5、本机直出、节点检测、周期任务、Web 管理后台、V2Ray/Clash 订阅
- 暂不纳入：多 VPS 集群、复杂 RBAC、计费、多租户、UDP 转发、Xray 多出口编排、原始 SSTP 导出

## 1. 产品边界

系统运行在用户自己的 Ubuntu 24.04 VPS 上。它从公开来源获取 VPN Gate 候选节点，保存候选配置并执行受控检测；同时允许用户手动添加 SOCKS5 代理和 VPS 本机直出。系统根据启用状态和检测结果生成订阅，供 v2rayN、Clash 或 Mihomo 客户端导入。

系统只负责管理和编排出口，不承诺 VPN Gate 节点长期在线，也不把“候选节点存在”当作“节点已验证可用”。检测结果应包含时间、失败原因和探测证据，订阅生成时只使用当前策略允许的节点。

## 2. 逻辑架构

```text
                    ┌────────────────────────┐
                    │  v2rayN / Clash 客户端 │
                    └───────────┬────────────┘
                                │ 订阅请求
                                ▼
┌──────────────┐       ┌────────────────────────┐
│ 管理员浏览器  │──────▶│ FastAPI HTTP API       │
└──────────────┘       │ 认证 / 管理 / 订阅输出 │
                       └───────────┬────────────┘
                                   │
             ┌─────────────────────┼─────────────────────┐
             ▼                     ▼                     ▼
   ┌────────────────┐    ┌────────────────┐    ┌────────────────┐
   │ 节点池服务      │    │ 检测任务服务    │    │ 订阅生成服务    │
   │ 来源获取/解析    │    │ 并发/超时/重试  │    │ V2Ray/Clash     │
   └───────┬────────┘    └───────┬────────┘    └───────┬────────┘
           │                     │                     │
           └─────────────────────┼─────────────────────┘
                                 ▼
                       ┌──────────────────┐
                       │ SQLite + 文件存储 │
                       │ 状态/配置/审计    │
                       └──────────────────┘
                                 ▲
                                 │
                       ┌─────────┴─────────┐
                       │ systemd timers     │
                       │ 或内置任务调度器    │
                       └───────────────────┘
```

## 3. 服务拆分

### 3.1 API 服务

建议使用 Python 3.12、FastAPI、Uvicorn。API 服务负责：

- 管理员登录、会话和密码修改；
- 候选池刷新、节点查询、节点启用/禁用；
- 自定义 SOCKS5 的新增、修改、删除和连通性检测；
- 本机直出开关；
- 手动触发检测和查看任务状态；
- 订阅 Token 管理；
- 系统设置和运行状态；
- 输出 V2Ray/Base64 与 Clash/Mihomo 订阅。

API 服务不应直接执行长时间网络检测。长任务统一写入 `jobs` 表，由任务执行器领取，接口只返回任务 ID。

### 3.2 Source Fetcher

负责从 VPN Gate 官方 CSV 或可选镜像获取候选数据。

处理流程：

1. 请求来源，限制连接和响应大小；
2. 校验 HTTP 状态、内容类型和 CSV 结构；
3. 解析国家、IP、端口、协议、延迟、速度、会话数和配置内容；
4. 对节点生成稳定指纹，避免重复插入；
5. 保存来源快照和抓取时间；
6. 更新候选节点状态；
7. 只在新数据通过校验后替换当前池，不因一次失败清空旧池。

不得把来源提供的配置字段直接当作 shell 命令执行。配置应按白名单解析，未知字段原样保存但不参与执行。

### 3.3 Checker

负责检测节点是否可用。第一阶段建议采用“受控外部命令 + Python 编排”的方式，不在 API 进程内持有网络隧道。

检测器需要具备：

- 全局并发上限；
- 单节点连接超时和总超时；
- 节点级互斥，避免同一节点重复检测；
- 子进程启动、日志截断和退出清理；
- 失败分类：连接失败、认证失败、超时、出口探测失败、协议不支持、资源不足；
- 每次检测写入 `node_checks`，仅把最新有效状态回写 `nodes`。

MVP 阶段可以先对 SOCKS5 使用 TCP 连接和 HTTPS 出口探测；VPN Gate 节点检测可先落地“配置解析 + TCP 可达性 + 外部检测适配器”接口，再根据实际协议工具完成真实链路验活。

### 3.4 Scheduler

建议第一阶段使用一个独立 Python worker，由 systemd service 常驻，内部使用 asyncio 定时调度。这样可以统一处理：

- 来源刷新；
- VPN Gate 节点检测；
- 自定义 SOCKS5 检测；
- 清理过期检测记录；
- 生成订阅缓存。

同一任务类型只能有一个运行实例。任务通过数据库锁或 `jobs.lock_key` 实现幂等。服务重启后，超过超时时间仍为 running 的任务应被标记为 abandoned，然后允许重新排队。

### 3.5 Subscription Service

订阅生成服务从当前有效出口读取数据，应用筛选策略后生成：

- V2Ray/Base64 格式；
- Clash/Mihomo YAML 格式；
- 可选仅输出启用节点或仅输出检测通过节点。

订阅内容不得直接返回管理密码、SOCKS5 密码明文或内部错误堆栈。订阅通过高熵 Token 访问，并支持单独撤销。

### 3.6 文件存储

SQLite 负责结构化数据，文件系统负责大块或敏感内容：

```text
/opt/xnvgatebox/
├── app/                    # 应用代码
├── data/
│   ├── app.db              # SQLite 数据库
│   ├── sources/             # 来源原始快照，可按保留策略清理
│   ├── configs/             # 节点配置文件，权限 0700
│   ├── generated/           # 订阅缓存，权限 0700
│   └── backups/             # 数据库和配置备份
├── logs/
└── run/
```

节点配置不建议全部塞进数据库。`nodes.config_path` 保存受控文件路径，文件名使用节点指纹，不使用用户输入拼接路径。

## 4. 关键状态模型

### 节点状态

```text
new → queued → checking → healthy
                         ├→ unhealthy
                         ├→ blocked
                         └→ expired
```

- `new`：刚进入候选池，尚未检测。
- `queued`：等待检测。
- `checking`：正在检测。
- `healthy`：最近一次检测通过。
- `unhealthy`：最近一次检测失败，但仍在保留期内。
- `blocked`：管理员手动禁用或策略禁止。
- `expired`：来源中长期不存在或超过保留时间。

### 任务状态

```text
queued → running → succeeded
                 ├→ failed
                 ├→ cancelled
                 └→ abandoned
```

任务必须记录 `started_at`、`finished_at`、`error_code` 和可供管理员查看的脱敏摘要。

## 5. 主要 API 设计

### 认证

```text
POST /api/auth/login
POST /api/auth/logout
GET  /api/auth/me
POST /api/auth/password
```

### 候选池

```text
GET  /api/pool/summary
POST /api/pool/refresh
GET  /api/nodes
GET  /api/nodes/{id}
POST /api/nodes/{id}/enable
POST /api/nodes/{id}/disable
POST /api/nodes/{id}/check
```

### 自定义出口

```text
GET    /api/egress
POST   /api/egress/socks5
PATCH  /api/egress/{id}
DELETE /api/egress/{id}
POST   /api/egress/{id}/check
POST   /api/egress/local/toggle
```

### 任务与设置

```text
GET  /api/jobs
GET  /api/jobs/{id}
POST /api/jobs/{id}/cancel
GET  /api/settings
PATCH /api/settings
```

### 订阅

```text
GET    /api/subscriptions
POST   /api/subscriptions
DELETE /api/subscriptions/{id}
GET    /sub/{token}/v2ray
GET    /sub/{token}/clash
```

订阅接口与管理 API 分开鉴权。管理 API 使用 Cookie 会话；订阅接口只接受不可预测 Token，不创建管理员会话。

## 6. Ubuntu 24.04 部署设计

### 系统依赖

- Ubuntu 24.04 LTS；
- root 安装，运行时使用专用系统用户 `xnvgatebox`；
- Python 3.12；
- SQLite 3；
- curl、ca-certificates、iproute2、procps；
- 可选检测工具按协议单独安装；
- systemd。

### systemd 单元

```text
xnvgatebox-api.service       # FastAPI/Uvicorn
xnvgatebox-worker.service    # 调度与检测任务
xnvgatebox-refresh.timer     # 周期刷新候选池
xnvgatebox-cleanup.timer     # 清理历史检测与日志
```

API 和 worker 使用同一数据库，但通过不同进程职责隔离。SQLite 开启 WAL 模式，写入事务尽量短；检测结果批量提交，避免长事务阻塞管理后台。

### 网络与权限

- 管理端口默认监听 `127.0.0.1:8899`；公网访问建议由 Nginx/Caddy 反向代理提供 HTTPS；
- 订阅端点可以与管理端点共用 HTTPS，但必须使用独立 Token；
- 配置目录属于 `xnvgatebox:xnvgatebox`，权限 0700；
- 日志不得打印 SOCKS5 密码、订阅 Token、Cookie 和完整节点配置；
- 默认不自动修改系统防火墙；安装器只提示需要放行的端口。

## 7. 安全与可靠性要求

1. 首次安装生成随机管理密码，并强制用户首次登录后修改。
2. 密码使用 Argon2id 或 bcrypt 哈希，数据库不保存明文。
3. 管理会话使用随机 Token，设置过期时间，Cookie 使用 `HttpOnly`、`Secure` 和合适的 `SameSite`。
4. 所有修改操作写入 `audit_logs`，但审计内容必须脱敏。
5. 对来源请求使用 HTTPS、超时、最大响应体和重定向限制。
6. 外部命令使用参数数组调用，禁止 `shell=True`，禁止把 CSV 字段拼接到 shell 命令。
7. 每个节点检测必须设置资源上限和清理逻辑，防止僵尸进程与文件描述符泄漏。
8. 订阅 Token 使用至少 32 字节随机数的 URL-safe 编码，支持撤销和轮换。
9. 数据库每日备份，保留最近 7 份；备份文件权限 0600。
10. 节点连续失败达到阈值后暂时退避，但不要自动切换到用户未允许的直出出口。

## 8. 推荐代码结构

```text
xnvgatebox/
├── app/
│   ├── main.py
│   ├── api/
│   │   ├── auth.py
│   │   ├── nodes.py
│   │   ├── egress.py
│   │   ├── jobs.py
│   │   ├── settings.py
│   │   └── subscriptions.py
│   ├── core/
│   │   ├── config.py
│   │   ├── security.py
│   │   ├── logging.py
│   │   └── database.py
│   ├── models/
│   ├── repositories/
│   ├── services/
│   │   ├── source_fetcher.py
│   │   ├── node_parser.py
│   │   ├── checker.py
│   │   ├── scheduler.py
│   │   ├── subscription.py
│   │   └── backup.py
│   └── templates/
├── migrations/
├── scripts/
│   ├── install.sh
│   ├── backup.sh
│   └── uninstall.sh
├── systemd/
├── tests/
├── web/
├── pyproject.toml
└── README.md
```

## 9. 分阶段实现顺序

### Phase 1：可运行骨架

完成数据库、认证、节点 CRUD、SOCKS5 CRUD、本机直出、基本管理页面和健康检查。

### Phase 2：候选池

完成 VPN Gate CSV 获取、解析、指纹去重、快照保存、候选池刷新接口和节点列表。

### Phase 3：检测与调度

完成并发控制、检测历史、失败分类、任务队列、周期刷新、周期检测和重启恢复。

### Phase 4：订阅

完成 V2Ray/Base64 和 Clash/Mihomo 输出、Token 管理、订阅缓存和订阅访问审计。

### Phase 5：安装与运维

完成 Ubuntu 24.04 安装脚本、systemd 单元、备份恢复、更新检查、卸载和最小回归测试。

### Phase 6：后续扩展

在不修改核心数据模型的情况下接入 Xray 多出口、真实 VPN Gate 隧道、更多来源、策略路由和多用户权限。

## 10. 与参考项目的关系

本设计参考了 `xnvgatebox` 的产品边界和公开文档，但不要求复制其实现。原项目公开说明了 VPN Gate、SOCKS5、本机直出、Web 控制台、统一订阅和定时任务等能力，并使用 GPL-3.0-only；如果后续复用其代码，应单独完成许可证和第三方依赖审查。

参考：[xnvgatebox README](https://github.com/hanhaoops/xnvgatebox)、[开发与测试说明](https://raw.githubusercontent.com/hanhaoops/xnvgatebox/main/docs/TESTING.md)、[第三方依赖说明](https://raw.githubusercontent.com/hanhaoops/xnvgatebox/main/THIRD_PARTY.md)。
