# 项目入口与旧包装脚本归档清单

项目根目录只保留 `run.py`。它无参数时直接启动“剧本杀·停云客栈”，避免让使用者在新旧两套系统和多个脚本之间选择。

```powershell
python run.py
```

等价的规范入口是：

```powershell
python -m agents_town interactive
```

## 当前入口

| 入口 | 用途 | 状态 |
| --- | --- | --- |
| `run.py` | 默认启动停云客栈；显式参数转发给 `agents_town.cli` | 唯一根目录 Python 入口 |
| `python -m agents_town interactive` | 启动停云客栈 | 规范入口 |
| `python -m agents_town start` | 运行旧版开放世界模拟 | 保留的旧版模块入口 |
| `python -m agents_town replay` | 运行旧版回放服务 | 保留的旧版模块入口 |
| `python -m agents_town.legacy.launcher.app` | 运行旧版桌面启动器 | 保留的旧版模块入口 |

## 已归档的根目录包装脚本

旧包装脚本统一存放在 `scripts/legacy_entrypoints/`。归档只改变入口位置，没有删除 `agents_town/legacy/` 中的旧版业务实现。

| 归档脚本 | 规范实现 |
| --- | --- |
| `__main__.py` | `agents_town.cli` |
| `interactive_server.py` | `agents_town.interactive.web.app` |
| `AI小镇启动器.py` | `agents_town.legacy.launcher.app` |
| `start.py` | `agents_town.legacy.simulation.runner` |
| `compress.py` | `agents_town.legacy.replay.report` |
| `replay.py` | `agents_town.legacy.replay.app` |
| `liblib_starflow_txt2img_api.py` | `agents_town.legacy.integrations.liblib_starflow` |
| `suno-api.py` | `agents_town.legacy.integrations.suno` |
| `gemini_API.py` | `agents_town.legacy.integrations.gemini` |
| `tiled_to_maze.py` | `agents_town.legacy.tools.tiled_to_maze` |

归档脚本仍可从项目根目录执行，例如：

```powershell
python scripts/legacy_entrypoints/start.py --name my_story --step 60
```

它们用于历史命令追溯，不再属于公开兼容接口。新文档、测试和内部源码均应使用 `run.py` 或规范模块入口。

## 归档验收

- [x] 包内源码不依赖根目录包装脚本。
- [x] 根目录只保留 `run.py`。
- [x] 10 个旧包装脚本完整归档。
- [x] 旧版业务实现继续保留在 `agents_town/legacy/`。
- [x] 归档参数型脚本仍支持 `--help`。
- [x] 最终 150 项自动化测试全部通过。
- [x] `python run.py` 实际启动无重复导入警告；角色席、导演台和剧本列表返回 200。
- [x] 通过实际 HTTP 请求创建 `stormbound_inn` 对局，返回 201、`intervention` 阶段和 3 张事件卡。
