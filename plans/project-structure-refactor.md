# 新旧模拟隔离与工程结构重构计划

## 概要

- 后续工程计划统一放入 `plans/`。
- 建立 `agents_town/interactive/`、`agents_town/legacy/`、`agents_town/common/` 三个明确边界。
- 优先迁移和验证新版互动模拟；旧版模拟随后整理，期间不得影响互动主线。
- LibLib、Suno、Gemini 等生成式媒体能力全部归入 `legacy`。
- 顶层脚本和旧导入路径保留为兼容包装层。

## 目标结构

```text
agents_town/
  common/
    paths/                  项目、资源和结果目录解析
    config/                 两套系统共用的安全配置加载
    model/                  两套系统都调用的模型适配
    resources/
      characters/           两套系统共用的角色视觉资产
      lore/                 共同的角色与世界观原始资料

  interactive/
    domain/                 状态、行动、事件、信念等领域对象
    planning/               启发式与 LLM 角色规划
    application/            会话、回合、视图、传播、终局
    infrastructure/         场景装载、持久化、历史记录
    web/                    Flask 应用、路由与通知
    resources/
      scenarios/            互动剧本
      worlds/               互动系统的结构化地点图
      rules/                互动角色行为规则
      frontend/             互动页面及对应 CSS/JS

  legacy/
    simulation/             开放世界模拟、Agent、记忆、日程和地图
    launcher/               PySide6 桌面启动器
    replay/                 压缩报告与回放服务
    integrations/           LibLib、Suno、Gemini 客户端及批处理任务
    tools/                  Tiled 转换和旧数据构建工具
    resources/
      prompts/              旧版 Agent 提示词
      frontend/             旧地图、回放页面、PixiJS 和样式
      character_templates/  启动器创建角色使用的模板
```

## 资源归属

- 互动场景、互动世界、行为规则和互动页面资源迁入 `interactive/resources/`。
- 旧提示词、village 地图、PixiJS、回放模板和角色创建模板迁入 `legacy/resources/`。
- 生成图片、音乐和 HTML 的逻辑及资源约定迁入 `legacy/integrations/`。
- 两套系统实际读取的角色资产放入 `common/resources/characters/`。
- `data/lore` 作为共同创作来源迁入 `common/resources/lore/`。
- 运行结果保留根目录 `results/`，新写入分为 `results/interactive/` 与 `results/legacy/`。

## 分阶段实施

- [x] 建立保护性基线：记录入口、环境变量、路由、导入、路径与格式，并建立互动特征测试和资源消费者清单。
- [x] 优先独立互动模拟：迁移互动代码和资源，拆分规划与服务职责，Flask 直接服务互动资源和共享角色资源。
- [x] 抽取共享基础层：统一路径、冻结环境、结果目录、配置和模型适配；固定依赖方向。
- [x] 隔离旧版模拟：迁移模拟、记忆、日程、地图、启动器、压缩和回放；人物选择改用结果目录状态文件。
- [x] 归并生成式媒体：在 `legacy/integrations/` 分别建立 LibLib、Suno、Gemini 实现，输出到 `results/legacy/generated/`。
- [x] 建立兼容层并清理：顶层脚本和 `modules.*` 只转发；更新文档和资源生成脚本。仓库当前没有 PyInstaller 构建配置，真实冻结构建另立计划。

## 公共接口与兼容要求

- 根目录只保留 `python run.py`，无参数时直接启动停云客栈。
- 保持 `GameService`、`GameSession`、规划器和领域类型的规范包调用方式。
- 保持互动系统 URL、JSON 字段、环境变量、游戏存档和历史数据库格式。
- 新代码使用 `agents_town.interactive.*`、`agents_town.legacy.*`、`agents_town.common.*`。
- 旧版业务实现继续保留在 `agents_town/legacy/`；原根目录包装脚本归档到 `scripts/legacy_entrypoints/`。
- 互动代码不得回退依赖旧目录；旧版路径只通过兼容解析器读取。

## 依赖约束

- 只允许 `interactive → common`、`legacy → common`。
- `common` 不得导入任一应用。
- `interactive` 与 `legacy` 不得互相导入。
- “共享”必须有两套系统的实际消费者，潜在复用不作为共享依据。

## 测试与验收

旧版运行、安全凭据和生成式媒体的分阶段验收见
[`legacy-runtime-acceptance.md`](legacy-runtime-acceptance.md)。

- [x] 原结构重构、入口归档、API 密钥安全和旧版验收测试继续通过；当前 150 项自动化测试全部通过。
- [x] Flask 测试客户端覆盖页面、场景列表、创建游戏、玩家/导演状态、异步推进和复盘接口。
- [x] AST 依赖测试禁止应用互相导入和 `common` 反向依赖应用。
- [x] 互动资源从独立包加载，不依赖旧版资源位置。
- [x] `run.py` 默认互动入口、归档脚本清单、源码模块命令和冻结目录定位测试通过。
- [x] 完成旧版模拟 1 步、断点继续 1 步、压缩、Flask 回放和 Qt offscreen 启动器自动验收；checkpoint 连续且不含认证字段。
- [x] 用户人工确认旧版桌面启动器可以正常运行；它不再属于当前停云客栈主线。
- [x] LibLib、Suno、Gemini 真实调用和旧版 PyInstaller 验收已从本轮移出，不作为入口归档前置条件。

## 实施结果

- [x] 创建计划目录和本计划文件。
- [x] 建立 `common`、`interactive`、`legacy` 包及单向依赖边界。
- [x] 迁移互动代码、场景、世界、规则和前端，并优先完成回归。
- [x] 迁移旧版模拟、启动器、回放、工具、提示词、地图和模板。
- [x] 将 LibLib、Suno、Gemini 归入旧版集成并分离生成结果目录。
- [x] 保留 `modules.*` 兼容导出；旧顶层脚本完成归档，旧版实现未删除。
- [x] 启动器通过 `results/legacy/selected_personas.json` 传递人物选择，不再解析或改写源码。
- [x] 增加架构边界和兼容测试，并完成全量回归。

## 默认约定

- 新互动模拟具有最高优先级，旧版迁移不得导致互动回归失败。
- 本次只调整结构和依赖边界，不修改玩法、规则、场景内容或前端交互设计。
- 根目录只承担停云客栈启动职责，旧命令通过规范模块或归档脚本访问。
- 文件移动、行为修改和格式化应在后续提交中尽量分离。

## 根目录入口解耦与归档

最终策略调整为“停云客栈单一根入口 + 旧包装脚本集中归档”。旧版功能仍通过 `agents_town.legacy.*` 和 `python -m agents_town start|replay` 使用。

### 已完成

- [x] `agents_town.cli` 直接通过规范模块启动互动、旧版模拟和回放，不再调用根目录脚本。
- [x] 启动器使用独立的纯逻辑命令解析器：源码模式生成 `python -m` 命令，冻结模式保留既有 exe 名称和目录布局。
- [x] 启动器不再检查、拼接或解析根目录 `.py` 文件，冻结 exe 映射集中在唯一组件中。
- [x] 新增 `run.py`；无参数默认启动停云客栈，显式参数继续转发给统一 CLI。
- [x] 根目录 10 个旧包装脚本迁入 `scripts/legacy_entrypoints/`，根目录只剩 `run.py`。
- [x] 归档包装脚本统一使用规范包实现，没有复制旧版业务逻辑。
- [x] README、开发文档、旧版说明、角色指南和命令记录切换到新入口或规范模块命令。
- [x] 更新 [`docs/root-entrypoints.md`](../docs/root-entrypoints.md)，记录单一入口、归档位置和旧版模块命令。
- [x] 增加根目录单一入口、默认互动命令、归档清单和归档脚本 `--help` 测试。
- [x] 最终 150 项自动化测试通过；`python run.py` 实际启动停云客栈，角色席、导演台和剧本 API 均返回 200，创建对局返回 201。

### 根目录入口归档工作记录（2026-08-22）

1. [x] 新建 `run.py`，无参数默认转发到 `interactive`，并保留显式 CLI 参数转发。
2. [x] 将原根目录 10 个 Python 包装脚本归档到 `scripts/legacy_entrypoints/`；旧版实现继续位于 `agents_town/legacy/`。
3. [x] 根目录 Python 文件清单收敛为唯一的 `run.py`。
4. [x] 将测试中的 `interactive_server` 兼容导入迁移为 `agents_town.interactive.web.app` 规范导入。
5. [x] 更新 README、开发文档、旧版说明、角色指南、命令记录和入口清单。
6. [x] 新增 `agents_town.interactive.web.__main__`，消除从统一 CLI 启动时的重复导入警告。
7. [x] 归档入口测试 14 项通过，全量测试 150 项通过。
8. [x] 在启发式模式下从 `run.py` 实际启动服务；创建 `stormbound_inn` 对局成功，状态为 `intervention` 并返回 3 张事件卡。
