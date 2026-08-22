# 旧版运行验收与 API 密钥安全重构计划

## 目标

- 先消除 checkpoint、日志和子进程环境中的密钥泄漏，再验证旧版模拟和媒体集成。
- 使用本机 Ollama：`qwen2.5:7b-instruct` 负责文本，`embeddinggemma` 负责记忆向量。
- 验证产物隔离到 `results/legacy/validation/<run-id>/`，不覆盖普通运行结果。
- 真实 LibLib、Suno、Gemini 调用逐项执行；无凭据时记录为 `SKIPPED`。

## 安全改造状态

- [x] 建立按供应商解析的凭据接口，环境变量优先，旧本地 JSON 只读兼容。
- [x] Gemini 不再把 `OPENAI_API_KEY` 当作后备密钥。
- [x] 模拟状态和运行时凭据分离；新 checkpoint 写入前移除认证字段。
- [x] 恢复模拟时重新解析当前凭据，本地 Ollama 允许空凭据映射。
- [x] 启动器按命令提供最小权限环境；压缩和回放不接收媒体密钥。
- [x] LibLib URL、请求异常和服务错误统一脱敏；云端密钥端点强制 HTTPS。
- [x] 增加只读 checkpoint 密钥扫描，不自动修改历史文件。
- [x] 历史 checkpoint 扫描未发现认证字段，因此没有需要清理的数据。

## 分阶段验收

1. [x] 使用项目专属 Python 3.11.15 解释器运行全部自动化测试；入口归档完成后当前 150 项通过。
2. [x] 安装 `llama-index-embeddings-ollama`，确认 Ollama 0.32.14 和 `qwen2.5:7b-instruct` 可用。
3. [x] 拉取 `embeddinggemma`；`/api/embed` 返回 1 个非空的 768 维向量。
4. [x] 运行 `bootstrap`，建立最小双角色资源和无密钥本地配置；重复执行未覆盖任何文件。
5. [x] 扫描新旧两个 checkpoint 根目录；受影响文件和无效 JSON 均为 0。
6. [x] 隔离完成新模拟 1 步、恢复 1 步和压缩；步数、时间、角色、记忆与对话连续，两个 checkpoint 均无认证字段。
7. [x] Flask 测试客户端验证回放页面和静态资源均返回 200；实际浏览器视觉与交互检查仍列为人工验收。
8. [x] Qt offscreen 加载 2 个角色、选择 2 个角色，并确认源码命令指向 `agents_town.legacy.simulation.runner`；可见 GUI 操作仍列为人工验收。
9. [x] 使用模拟 HTTP 响应验证 LibLib、Suno、Gemini 的认证隔离、脱敏、超时和隔离输出路径。
10. [x] 当前三家真实凭据均不存在，LibLib、Suno、Gemini 均记录为 `SKIPPED_NO_CREDENTIALS`，未发出真实请求。

## 本次验收结果（2026-08-22）

- 项目解释器：`D:\Tools\miniconda3\envs\ruyuan-agents-town\python.exe`。
- 自动测试：旧版验收时 147/147 通过；入口归档完成后全项目 150/150 通过。
- 隔离运行：`security-acceptance-20260822-final`，新建、恢复、压缩和 Flask 回放通过。
- 报告：`results/legacy/validation/security-acceptance-20260822-final/validation-report.json`。
- 用户人工确认：旧版程序可以正常运行。
- 延后事项：三家真实媒体服务端到端请求和旧版 PyInstaller 构建；二者不属于停云客栈入口整理前置条件。

## 验证命令

```powershell
python -m agents_town.legacy.validation preflight
python -m agents_town.legacy.validation bootstrap
python -m agents_town.legacy.validation secrets-scan
python -m agents_town.legacy.validation smoke --name legacy-validation-YYYYMMDD
```

验证报告写入 `results/legacy/validation/<run-id>/validation-report.json` 和 `.md`，不记录密钥、密钥片段或指纹。

## 兼容与完成门槛

- 现有环境变量、回放格式和业务存档字段保持兼容；根目录包装脚本已集中归档。
- 旧 JSON 密钥读取保留一个发布周期；新文档只推荐环境变量。
- 旧版模拟、恢复、压缩、Flask 回放、启动器 offscreen 和用户人工运行均已通过。
- 真实媒体服务和旧版 PyInstaller 构建暂不继续，不阻塞根目录入口归档。
