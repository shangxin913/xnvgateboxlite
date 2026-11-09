# 第三方组件与参考边界

本项目独立实现 Python API 与中文管理界面，没有复制 xnvgatebox 的实现代码。产品功能参考 https://github.com/hanhaoops/xnvgatebox ，原项目核心为 GPL-3.0-only；若未来复用其实现，须重新审查许可证与发布方式。

Lucide 静态字型固定版本 0.468.0，下载来源 https://cdn.jsdelivr.net/npm/lucide-static@0.468.0/ 。本地文件位于 web/assets；许可全文为 web/assets/LUCIDE-LICENSE.txt。Lucide 使用 ISC，派生自 Feather 的图标另有 MIT 声明，见 https://lucide.dev/license 。本项目不依赖运行时外部 CDN。

SOCKS 分享链接格式核对自 v2rayN SocksFmt 实现：https://raw.githubusercontent.com/2dust/v2rayN/master/v2rayN/ServiceLib/Handler/Fmt/SocksFmt.cs 。这里只核对协议字段，不复制 C# 实现；测试是格式验证而非所有客户端版本的 GUI 实测。

Python 依赖使用官方 PyPI 发布版本，依赖固定于 requirements.txt：FastAPI（MIT）、Uvicorn（BSD-3-Clause）、argon2-cffi（MIT）、cryptography（Apache-2.0 或 BSD-3-Clause）、PyYAML（MIT）、httpx（BSD-3-Clause）、pytest（MIT）。其传递依赖许可证以各安装发行物自带声明为准；打包源代码不包含第三方 Python 二进制。
