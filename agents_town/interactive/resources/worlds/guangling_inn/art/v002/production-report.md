# 停云客栈 v002 地图生产报告

## 结果

- 投影：`orthogonal-side-elevation`，明亮、满画幅、纯 2D 正面房间侧视。
- 规则：12 个地点、13 条无向连接，未修改 `world.json` 的玩法拓扑。
- 画布：每层逻辑尺寸 768×512；`render_scale=2` 后为 1536×1024。
- 生产资产：12 张房间底图、1 张挑空装饰、3 张楼梯/石阶透明叠层。
- 前端：v002 整层图与门框/石阶/楼梯透明素材已发布到 `/static/assets/maps/guangling_inn/v002/`。DOM 负责房间交互，SVG 分离建筑端点、按需 connector 和隐藏 motion path，可见角色层保持最上方。

## 连通渲染修复

- 13 条 route 均增加 `visual`：`seam-door` 1 条、`paired-door` 9 条、`covered-passage` 1 条、`cellar-steps` 1 条、`stairs` 1 条。
- `ports` 是可见端点坐标权威；边缘端口由房间矩形和 offset 换算，地窖/主楼梯 4 个 interior 端口分别声明 `[672,230]`、`[672,384]`、`[96,297]`、`[96,224]`。
- `segments` 只作为移动动画采样路径。`courtyard--lobby`、`front_gate--lobby` 和二层 4 条房间路线已从非法零长度改为非零短路径；`lobby--kitchen` 终点从 x=768 修正为 x=704。
- 默认显示门和带屋檐入口端点；石阶和楼梯直接使用 AI 生成建筑美术。完整 connector 只由“显示连通图”开关或主动邻接聚焦显示，活动移动使用独立 motion path。旧绑定缺少 `visual` 时仍回退为低亮线路。
- 固定右下角 `room-door-hint` 已删除。可达房间使用文字角标与边框，端点使用形状和金色高亮，不只依赖颜色。

### 首轮审阅修订

- 玩家态长线根因为 `is-reachable` 曾错误触发完整 connector；已取消该规则。玩家可达关系现在只高亮房间和建筑端点，默认可见 connector 为 0。
- 一楼楼梯、二层平台和地窖石阶均继续使用 v002 AI 生图/标准化资产；已移除后叠加的楼梯/石阶 SVG 图形与常驻圆底，只保留按需光晕和文字。
- 第二轮复审进一步移除悬停/聚焦对完整 connector 的显示触发。完整线现在只能由显式“显示连通图”开关显示；普通、玩家可达、马厩悬停和大堂悬停状态均验证为 0 条。
- 第三轮复审加入 `connectivity-r4` 缓存版本和页面可见版本标记；3 张 AI 楼梯/石阶素材改为独立 `.portal-art` 图片层，浏览器验证 3/3 均成功加载。5002 服务已完整重启，排除旧进程与无版本静态引用干扰。
- 第四轮确认二层旧素材本身只有栏杆，并非加载失败。使用内置 imagegen 直接编辑整层二楼图，生成 `floor-2-r5.png`：左侧回廊现连接一段包含 10 级以上踏步的下行木楼梯。透明候选因没有真实 alpha 被拒绝；旧栏杆素材设置 `render_independent: false`，避免重复叠加。前端版本升级为 `connectivity-r5`。
- 第五轮根据用户 R5 实机截图确认完整连通图开关处于开启状态，横跨房间的线来自 connector 概览层。R6 已彻底移除概览按钮、connector SVG 层和全部 connector 节点；兼容 API 只能关闭概览，无法再打开。移动动画路径保持独立，不受影响。
- 第六轮按用户模块化建筑参考改为“小型边界连接件”。一楼 `floor-1-r7.png` 移除房间级木楼梯和石阶，二层恢复无大斜梯版本；三张旧 portal 叠层停止独立渲染。同层路线使用 14×24 像素真实透明小门，额外 SVG 门线框与常驻光晕已移除。地图生成 Skill 同步增加拓扑类型与连接件尺寸约束。
- 第七轮将孤立小门升级为“窄连接舱”。同层使用不透明的带屋檐门廊模块 `connector-door-bay-r8.png`，跨层使用不透明的 6 级短直梯井模块 `connector-ladder-shaft-r8.png`；短距离/相接房间只在共同边界渲染一个共享模块，避免两端重复贴门。两张完整参考案例保存于 `results/interactive/connectivity-repair/connector-reference-cases/`。前端版本升级为 `connectivity-r8`。
- 第八轮修正 R8 与参考案例的比例偏差。门廊从图标级 `28×42` 恢复为完整建筑切片 `36×112`，梯井从 `20×48` 恢复为贯穿上下接缝的 `28×128`；厨房同一边界上的两条 route 共用一张门廊图，避免重复堆叠但不合并玩法拓扑。前端版本升级为 `connectivity-r9`。

## 精确尺寸与拼装

- 回廊：生成 3×2 模块，先 LANCZOS 缩放为 384×256，再镜像交替拼接 4 次，输出 1536×256。
- 大堂挑空：生成 3×3 模块，先 LANCZOS 缩放为 384×384，再镜像交替拼接 3 次，输出 1152×384。
- 其余房间由 `prepare_map_assets.py` 根据 `rect × 64 × 2` 计算目标，保持比例并 cover-crop，不进行自由拉伸。

## 本地编辑记录

- 门框、主楼梯上下端、地窖石阶：保留 RGB 生成母版；经用户授权后，用 `extract_alpha.py --include-enclosed --background-floor 215 --neutral-spread 32` 提取真实 Alpha，并在米白、深灰、高饱和洋红三种底色上检查。
- `马厩 ↔ 后院`：首轮边缘 QA 发现独立底图材质断裂。使用 `apply_seam_door.py` 在双方安全带内建立同一暗门洞、共享门框和 0.86 基线；母版未覆盖，修订写入 `source/edited/`。
- 所有生成母版、淘汰候选、编辑修订、冻结选择、标准化产物和提示词账本分别保存。

## 验证

- `validate_map.py --require-assets`：通过。
- `validate_side_edges.py`：通过端口像素坐标、interior point、路径首尾 ≤1px、边界、最小长度、visual mode/可见表达和物理接缝检查。
- Skill 脚本单测：18/18 通过（资产管线 8，侧边端口 10）；`skill-creator` quick validation 通过。
- 地图/API/信息隔离相关 pytest：31/31 通过。
- 全量 pytest：170 通过、1 跳过、1 个环境性失败；失败仍为归档旧入口缺少 `llama_index`，与地图改动无关。
- R8 无头 Edge：12 房间、13 路线、14 motion path、15 个连接端点、10 个同层门廊图、3 个跨层梯井图、10 个共享连接件；概览开关、connector 层、connector line、房间级 portal 与 synthetic shape 均为 0。同层/跨层移动、邻接高亮、reduced-motion、旧绑定回退与三种视口全部通过。
- 1600×1100、1280×800、390×844 均无地图横向溢出、浏览器异常或活动路线残留。

## 角色立绘说明

地图 token 已接入公共立绘 URL，并保留首字回退。当前工作区实际只有 `左慈/portrait.png`；其余角色虽有下载/重建脚本，但文件不在公共资源目录且被 `.gitignore` 排除。因此本批次不把缺失立绘冒充为已完成资产。

## 主要交付路径

- 选定源：`art/v002/source/selected/`
- 最终构建：`art/v002/build-rev2/`
- 边缘 QA：`art/v002/build-rev2/edge-connectivity-qa.png`
- 提示词/编辑账本：`art/v002/prompt-ledger.json`
- 浏览器验收截图：`results/interactive/map-v002-acceptance.png`
- 连通修复前截图：`results/interactive/connectivity-repair/before/`
- 连通修复后与专项截图：`results/interactive/connectivity-repair/after/`
- 1600×1100 前后对比：`results/interactive/connectivity-repair/comparison/`
- R8 连接舱参考案例：`results/interactive/connectivity-repair/connector-reference-cases/`
- R8 最终验收截图：`results/interactive/connectivity-repair/review-r8-connector-bays.png`
- R9 参考匹配验收截图：`results/interactive/connectivity-repair/review-r9-reference-matched-final.png`
