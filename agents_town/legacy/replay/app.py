"""
这个模块实现了一个Web服务器,用于回放模拟结果:
1. 提供Web界面展示代理人的活动
2. 支持调整回放速度和画面缩放
3. 可以从指定步骤开始回放
"""

import os  # 导入操作系统模块,用于文件操作
import sys  # 兼容 PyInstaller 冻结运行时路径
import json  # 导入json模块,用于处理JSON数据
from datetime import datetime, timedelta  # 导入日期时间处理模块
from flask import Flask, render_template, request, jsonify, send_from_directory

from agents_town.common.paths import discover_runtime_paths
from .report import frames_per_step, file_movement

# 强制 UTF-8 I/O，避免中文日志在控制台或重定向时出现乱码
try:
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    os.environ.setdefault("PYTHONUTF8", "1")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


RUNTIME_PATHS = discover_runtime_paths()
BASE_DIR = str(RUNTIME_PATHS.project_root)
RESOURCE_ROOT = str(RUNTIME_PATHS.legacy_resources)
COMMON_CHARACTERS = os.fspath(RUNTIME_PATHS.common_resources / "characters")


app = Flask(
    __name__,
    template_folder=os.path.join(RESOURCE_ROOT, "frontend", "templates"),
    static_folder=os.path.join(RESOURCE_ROOT, "frontend", "static"),
    static_url_path="/static",
)


# 结果根目录（优先环境变量，其次打包目录下 results，再回退当前工作目录）
def _results_root() -> str:
    legacy_env = (os.environ.get("GA_LEGACY_RESULTS_DIR") or "").strip()
    if legacy_env:
        return legacy_env
    env_root = (os.environ.get("GA_RESULTS_DIR") or "").strip()
    if env_root:
        preferred_env = os.path.join(env_root, "legacy")
        if os.path.isdir(preferred_env) or not os.path.isdir(os.path.join(env_root, "compressed")):
            return preferred_env
        return env_root
    preferred = RUNTIME_PATHS.results_root / "legacy"
    old_root = RUNTIME_PATHS.results_root
    if preferred.is_dir() or not (old_root / "compressed").is_dir():
        return os.fspath(preferred)
    return os.fspath(old_root)

# 避免从 start.py 导入 personas（可能触发参数解析等副作用），改为直接扫描资源目录
def _list_personas():
    agents_dir = os.path.join(RESOURCE_ROOT, "frontend", "static", "assets", "village", "agents")
    try:
        return sorted([d for d in os.listdir(agents_dir) if os.path.isdir(os.path.join(agents_dir, d))])
    except Exception:
        return []

personas = _list_personas()


@app.route("/", methods=['GET'])  # 设置根路由,只接受GET请求
def index():
    """处理首页请求的函数"""
    # 从URL参数中获取配置信息
    name = request.args.get("name", "")          # 获取记录名称,默认为空
    step = int(request.args.get("step", 0))      # 获取起始步数,默认为0
    speed = int(request.args.get("speed", 2))    # 获取回放速度(0~5),默认为2
    zoom = float(request.args.get("zoom", 0.8))  # 获取画面缩放比例,默认0.8

    # 检查记录名称是否有效
    if len(name) <= 0:
        return f"Invalid name of the simulation: '{name}'"  # 返回错误信息

    # 构建回放数据文件的完整路径（多重候选，提升健壮性）
    results_root = _results_root()
    # 兼容：若在打包目录找不到，回退到源码目录(generative_agents/results)
    ga_root_1 = os.path.join(os.path.dirname(BASE_DIR), 'generative_agents')
    ga_root_2 = os.path.join(os.path.dirname(RESOURCE_ROOT), 'generative_agents')
    ga_root_3 = os.path.join(os.path.dirname(os.getcwd()), 'generative_agents')
    candidates = [
        os.path.join(results_root, "compressed", name, file_movement),
        os.path.join(BASE_DIR, "results", "compressed", name, file_movement),
        os.path.join(RESOURCE_ROOT, "results", "compressed", name, file_movement),
        os.path.join(os.getcwd(), "results", "compressed", name, file_movement),
        os.path.join(ga_root_1, "results", "compressed", name, file_movement),
        os.path.join(ga_root_2, "results", "compressed", name, file_movement),
        os.path.join(ga_root_3, "results", "compressed", name, file_movement),
    ]
    replay_file = next((p for p in candidates if os.path.exists(p)), None)
    if not replay_file:
        hint_primary = os.path.join(results_root, "compressed", name, file_movement)
        hint_all = "<br/>".join(candidates)
        return (
            "未找到回放数据文件：'" + hint_primary + "'"
            + "<br />已尝试以下位置：<br/>" + hint_all
            + "<br />请先运行 python -m agents_town.legacy.replay.report 生成数据，或在启动器中点击‘完成并查看模拟’。"
        )

    # 读取回放数据文件
    with open(replay_file, "r", encoding="utf-8") as f:
        params = json.load(f)  # 加载JSON数据到params字典

    # 确保起始步数至少为1
    if step < 1:
        step = 1
    # 如果不从头开始回放
    if step > 1:
        # 重新计算回放的起始时间
        t = datetime.fromisoformat(params["start_datetime"])  # 解析原始起始时间
        # 根据步数计算新的起始时间
        dt = t + timedelta(minutes=params["stride"]*(step-1))
        params["start_datetime"] = dt.isoformat()  # 更新起始时间
        
        # 计算对应的帧序号
        step = (step-1) * frames_per_step + 1
        # 确保不超过最大帧数
        if step >= len(params["all_movement"]):
            step = len(params["all_movement"])-1

        # 更新所有代理人的初始位置到指定步骤的位置
        for agent in params["persona_init_pos"].keys():
            persona_init_pos = params["persona_init_pos"]
            persona_step_pos = params["all_movement"][f"{step}"]
            # 将代理人的位置设置为指定步骤的位置
            persona_init_pos[agent] = persona_step_pos[agent]["movement"]

    # 处理回放速度设置
    if speed < 0:
        speed = 0  # 最小速度为0
    elif speed > 5:
        speed = 5  # 最大速度为5
    speed = 2 ** speed  # 速度值转换为2的幂次方

    # 优先：仅展示本次模拟涉及到的角色（来源于 movement.json 的 persona_init_pos）
    sim_personas = []
    try:
        sim_personas = sorted(list((params.get("persona_init_pos") or {}).keys()))
    except Exception:
        sim_personas = []

    # 回退：若 movement.json 中没有有效列表，则回退到资源目录扫描
    if not sim_personas:
        sim_personas = personas

    # 根据静态资源实际存在过滤可展示的角色，避免 portrait.png 404
    available_personas = []
    for p in sim_personas:
        portrait_abs = os.path.join(COMMON_CHARACTERS, p, "portrait.png")
        if os.path.exists(portrait_abs):
            available_personas.append(p)

    # 渲染模板并返回页面
    return render_template(
        "index.html",  # 使用index.html模板
        persona_names=available_personas,  # 仅传入本次模拟且存在资源的角色
        step=step,  # 起始步数
        play_speed=speed,  # 回放速度
        zoom=zoom,  # 画面缩放比例
        simulation_name=name, # 显式传递模拟名称
        **params  # 展开params字典作为模板参数
    )


@app.route("/list_images", methods=['GET'])
def list_images():
    """获取指定角色文件夹中的图片列表"""
    folder_param = request.args.get("folder", "") # folder_param 将是 "sim_name/persona_name"
    
    if not folder_param:
        return jsonify({"error": "请指定文件夹路径 (格式: sim_name/persona_name)"}), 400
    
    # 构建图片目录的完整路径, 相对于 static_folder
    # folder_param 现在是 "sim_name/persona_name"
    image_dir = os.path.join(_results_root(), "generated", "images", folder_param)
    
    # 检查目录是否存在
    if not os.path.exists(image_dir) or not os.path.isdir(image_dir):
        print(f"调试: 请求的图片目录不存在: {image_dir}")
        print(f"调试: app.static_folder = {app.static_folder}")
        print(f"调试: 传入的 folder_param = {folder_param}")
        return jsonify({"error": f"目录不存在: {folder_param}. 预期路径: {image_dir}"}), 404
    
    # 获取目录中的所有PNG文件
    try:
        image_files = [f for f in os.listdir(image_dir) if f.lower().endswith('.png')]
        # 按文件名排序
        image_files.sort()
        return jsonify(image_files)
    except Exception as e:
        return jsonify({"error": f"读取目录失败: {str(e)}"}), 500


@app.route('/list_generated_html_sims/<sim_name>/<agent_name>')
def list_generated_html_sims(sim_name, agent_name):
    """
    列出为指定模拟和智能体生成的HTML模拟文件。
    路径结构: results/legacy/generated/html/<sim_name>/<agent_name>/
    """
    try:
        # 生成媒体使用独立路由，不与旧版静态资源混放。
        # 所以我们在此基础上构建路径
        html_sims_dir = os.path.join(_results_root(), "generated", "html", sim_name, agent_name)

        if not os.path.isdir(html_sims_dir):
            # 如果目录不存在，可以返回一个空列表或者一个错误信息
            print(f"调试: 请求的HTML模拟目录不存在: {html_sims_dir}")
            return jsonify({"sim_name": sim_name, "agent_name": agent_name, "files": [], "error": "Directory not found"}), 404
        
        html_files = [f for f in os.listdir(html_sims_dir) if f.endswith('.html')]
        html_files.sort(reverse=True) # 通常最新的文件更有用，所以降序排列
        
        return jsonify({"sim_name": sim_name, "agent_name": agent_name, "files": html_files})
    except Exception as e:
        print(f"错误: 列出HTML模拟文件失败 for {sim_name}/{agent_name}: {str(e)}")
        return jsonify({"error": str(e)}), 500


@app.route('/list_generated_music/<sim_name>/<agent_name>')
def list_generated_music(sim_name, agent_name):
    """
    列出为指定模拟和智能体生成的音乐文件。
    路径结构: results/legacy/generated/music/<sim_name>/<agent_name>/
    """
    try:
        # 生成媒体使用独立路由，不与旧版静态资源混放。
        # 所以我们在此基础上构建路径
        music_dir = os.path.join(_results_root(), "generated", "music", sim_name, agent_name)

        if not os.path.isdir(music_dir):
            # 如果目录不存在，可以返回一个空列表或者一个错误信息
            print(f"调试: 请求的音乐目录不存在: {music_dir}")
            return jsonify({"sim_name": sim_name, "agent_name": agent_name, "files": [], "error": "Directory not found"}), 404
        
        # 获取所有音频文件（支持常见的音频格式）
        music_files = [f for f in os.listdir(music_dir) if f.lower().endswith(('.mp3', '.wav', '.ogg', '.m4a', '.flac'))]
        music_files.sort(reverse=True) # 通常最新的文件更有用，所以降序排列
        
        return jsonify({"sim_name": sim_name, "agent_name": agent_name, "files": music_files})
    except Exception as e:
        print(f"错误: 列出音乐文件失败 for {sim_name}/{agent_name}: {str(e)}")
        return jsonify({"error": str(e)}), 500


@app.route("/legacy-generated/<kind>/<path:filename>")
def legacy_generated_file(kind, filename):
    roots = {
        "images": os.path.join(_results_root(), "generated", "images"),
        "html": os.path.join(_results_root(), "generated", "html"),
        "music": os.path.join(_results_root(), "generated", "music"),
    }
    if kind not in roots:
        return jsonify({"error": "Unknown generated media kind"}), 404
    return send_from_directory(roots[kind], filename)


@app.route("/common-characters/<path:filename>")
def common_character_file(filename):
    return send_from_directory(COMMON_CHARACTERS, filename)


@app.route("/static/assets/village/agents/<path:filename>")
def compatible_character_asset(filename):
    """Keep legacy sprite URLs while sourcing shared visual assets."""

    return send_from_directory(COMMON_CHARACTERS, filename)


# 只有直接运行此文件时才执行
if __name__ == "__main__":
    # 允许通过环境变量切换端口，默认 5000
    try:
        _port = int(os.environ.get("GA_REPLAY_PORT") or os.environ.get("PORT") or "5000")
    except Exception:
        _port = 5000
    app.run(host="127.0.0.1", port=_port, debug=False, use_reloader=False)
