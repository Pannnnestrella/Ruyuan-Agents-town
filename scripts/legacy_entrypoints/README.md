# 旧版根目录入口归档

这些脚本曾位于项目根目录，现在仅作为历史命令入口归档。业务实现仍位于
`agents_town/legacy/`，没有被删除。

新主入口：

```powershell
python run.py
```

旧版功能推荐直接使用规范模块：

```powershell
python -m agents_town start --name my_story --step 60
python -m agents_town replay
python -m agents_town.legacy.launcher.app
python -m agents_town.legacy.replay.report --name my_story
python -m agents_town.legacy.integrations.liblib_starflow --sim_name my_story
python -m agents_town.legacy.integrations.suno --sim_name my_story
python -m agents_town.legacy.integrations.gemini --sim_name my_story
python -m agents_town.legacy.tools.tiled_to_maze
```

归档脚本仍可从项目根目录直接执行，但不再属于公开兼容接口。
