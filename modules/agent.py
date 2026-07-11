"""generative_agents.agent"""  # 生成式智能体模块

import os  # 导入操作系统模块,用于文件和路径操作
import math  # 导入数学模块,用于数学计算
import random  # 导入随机模块,用于生成随机数
import datetime  # 导入日期时间模块,用于处理时间相关操作
import json  # 导入 json 库
import time  # 导入 time 模块,用于添加延迟和重试机制

# 从其他模块导入所需的类和函数
from modules import memory, prompt, utils  
from modules.model.llm_model import create_llm_model
from modules.memory.associate import Concept

class Agent:
    """智能体类,实现智能体的核心功能"""
    
    def __init__(self, config, maze, conversation, logger):
        """初始化智能体
        Args:
            config: 配置信息字典
            maze: 迷宫/环境对象
            conversation: 对话历史记录
            logger: 日志记录器
        """
        self.name = config["name"]  # 智能体名称
        self._storage_root = config["storage_root"] # 存储该代理数据的根目录
        os.makedirs(self._storage_root, exist_ok=True) # 确保根目录存在

        self.maze = maze  # 迷宫/环境对象
        self.conversation = conversation  # 对话历史
        self._llm = None  # 语言模型对象
        self.logger = logger  # 日志记录器

        # 从配中加载智能体的各项参数
        self.percept_config = config["percept"]  # 感知配置
        self.think_config = config["think"]  # 思考配置  
        self.chat_iter = config["chat_iter"]  # 对话迭代次数

        # 初始化记忆相关组件
        # 确保 'api_keys' 在传递给Agent的config中存在
        if "api_keys" not in config:
            raise ValueError("API keys are missing in the agent's configuration.")

        self.spatial = memory.Spatial(**config["spatial"])  # 空间记忆
        self.schedule = memory.Schedule(**config["schedule"])  # 日程安排
        self.associate = memory.Associate(  # 关联记忆
            path=self.storage("associate"),
            embedding_config=config["associate"]["embedding"], # 传递 embedding 子配置
            api_keys=config["api_keys"], # 传递全局 API keys
            retention=config["associate"].get("retention", 8),
            max_memory=config["associate"].get("max_memory", -1),
            max_importance=config["associate"].get("max_importance", 10),
            recency_decay=config["associate"].get("recency_decay", 0.995),
            recency_weight=config["associate"].get("recency_weight", 0.5),
            relevance_weight=config["associate"].get("relevance_weight", 3),
            importance_weight=config["associate"].get("importance_weight", 2),
            # memory 参数可以根据需要从config加载或保持默认
        )
        self.concepts = []  # 概念列表
        self.chats = config.get("chats", [])  # 对话记录

        # 初始化提示词生成器
        self.scratch = prompt.Scratch(  # 提示词生成器
            self.name,  # 智能体名称
            config["currently"],  # 当前状态描述
            config["scratch"]  # 提示词配置
        )

        # 初始化状态信息
        status = {"poignancy": 0}  # 初始化状态字典,设置显著性为0
        self.status = utils.update_dict(status, config.get("status", {}))  # 更新状态信息
        self.plan = config.get("plan", {})  # 获取计划息

        # 记录后一次更新时
        self.last_record = utils.get_timer().daily_duration()  # 获当天持续时间作为最后记录时间

        # 初始化动作和事件
        if "action" in config:  # 如果配置中包含动作信息
            self.action = memory.Action.from_dict(config["action"])  # 从字典创建动作对象
            tiles = self.maze.get_address_tiles(self.get_event().address)  # 获取事件地址对应的地块
            config["coord"] = random.choice(list(tiles))  # 随机选择一个地块作为坐标
        else:  # 如果配置中不包含动作信息
            tile = self.maze.tile_at(config["coord"])  # 获取指定坐标的地块
            address = tile.get_address("game_object", as_list=True)  # 获取地块的游戏对象地址
            self.action = memory.Action(  # 创建新的动作对象
                memory.Event(self.name, address=address),  # 创建智能体事件
                memory.Event(address[-1], address=address),  # 创建目标对象事件
            )

        # 更新迷宫中的位置信息
        self.coord, self.path = None, None  # 初始化坐标和路径
        self.move(config["coord"], config.get("path"))  # 移动到指定位置
        if self.coord is None:  # 如果移动失败
            self.coord = config["coord"]  # 接置目标

        self.painting_count = 0  # 初始化绘画计数器
        self.last_painting_time = None  # 上次绘画时间
        self.painting_limit = 1  # 每小时限制次数为 1

        # 音乐创作相关属性
        self.music_composition_count = 0  # 初始化音乐创作计数器
        self.last_music_composition_time = None  # 上次音乐创作时间
        self.music_composition_limit = 1  # 每小时音乐创作限制次数为1

        # 量子计算相关属性
        self.quantum_computing_count = 0  # 初始化量子计算计数器
        self.last_quantum_computing_time = None  # 上次量子计算时间
        self.quantum_computing_limit = 1  # 每小时量子计算限制次数为1

    def storage(self, name):
        """获取并确保指定子模块的存储路径存在"""
        path = os.path.join(self._storage_root, name)
        if not os.path.isdir(path):
            os.makedirs(path)
        return path

    def abstract(self):
        """获取智能体的抽象信息概要
        Returns:
            dict: 包含智能体主要信息的字典
        """
        des = {
            "name": self.name,  # 智能体名称
            "currently": self.scratch.currently,  # 当前状态描述
            "tile": self.maze.tile_at(self.coord).abstract(),  # 当前所在地块的抽象信息
            "status": self.status,  # 状态信息
            "concepts": {c.node_id: c.abstract() for c in self.concepts},  # 概念信息
            "chats": self.chats,  # 对话记录
            "action": self.action.abstract(),  # 当前动作的抽象信息
            "associate": self.associate.abstract(),  # 关联记忆的抽象信息
        }
        if self.schedule.scheduled():  # 如果有计划安排
            des["schedule"] = self.schedule.abstract()  # 添加计划信息
        if self.llm_available():  # 如果语言模型可用
            des["llm"] = self._llm.get_summary()  # 添加语言模型摘要
        return des

    def __str__(self):
        """返回智能体信息的字符串表示
        Returns:
            str: 智能体信息的字符串形式
        """
        return utils.dump_dict(self.abstract())

    def reset(self, keys):
        """重置能体的语型
        Args:
            keys: 语言模型所需的密钥信息
        """
        if self.think_config["mode"] == "llm" and not self._llm:  # 如果使用语言模型且未初始化
            self._llm = create_llm_model(**self.think_config["llm"], keys=keys)  # 创建语言模型实例

    def completion(self, func_hint, *args, **kwargs):
        """执行提示词补全操作
        Args:
            func_hint: 提示词函数的提示
            *args: 可变位置参数
            **kwargs: 可变关键字参数
        Returns:
            str: 补全的结果
        """
        # 确保存在对应的提示词生成函数
        assert hasattr(
            self.scratch, "prompt_" + func_hint
        ), "Can not find func prompt_{} from scratch".format(func_hint)
        
        # 获取提示词生成函数
        func = getattr(self.scratch, "prompt_" + func_hint)
        prompt = func(*args, **kwargs)  # 生成提示词
        
        title = "{}.{}".format(self.name, func_hint)  # 生成日志标题
        msg = {}  # 初始化消息字典
        
        if not self.llm_available():  # 如果语言模型不可用
            error_message = f"LLM for agent '{self.name}' is not available. Cannot proceed with completion for '{func_hint}'. Please check your model configuration and API keys."
            self.logger.error(error_message)
            raise RuntimeError(error_message)
        
        # 语言模型可用，继续执行
        self.logger.info("{} -> {}".format(self.name, func_hint))  # 记录日志
        output = self._llm.completion(**prompt, caller=func_hint)  # 执行补全
        print(f"[MY_DEBUG] Agent.completion - output from self._llm.completion: '{output}'") # <--- 添加这行
        responses = self._llm.meta_responses  # 获取元响应
        print(f"[MY_DEBUG] Agent.completion - self._llm.meta_responses: {responses}") # <--- 添加这行
        msg = {"<PROMPT>": "\n" + prompt["prompt"] + "\n"}  # 添加提示词到消息
        msg.update(
            {
                "<RESPONSE[{}/{}]>".format(idx+1, len(responses)): "\n" + r + "\n"
                for idx, r in enumerate(responses)
            }
        )  # 添加响应到消息
        
        msg["<OUTPUT>"] = "\n" + str(output) + "\n"  # 添加输出到消息
        self.logger.debug(utils.block_msg(title, msg))  # 记录调试信息
        print(f"[MY_DEBUG] Agent.completion - final output to be returned: '{output}'") # <--- 添加这行
        return output

    def think(self, status, agents):
        """智能体的主要思考循环
        Args:
            status: 当前状态信息
            agents: 其他智能体的字典
        Returns:
            dict: 更新后的计划信息
        """

        # 根据状态更新位置和获取事件
        events = self.move(status["coord"], status.get("path"))  # 移动到新位置并获取相关事件

        # 这确保了代理必须在完成移动后的下一个思考周期，才开始执行特殊活动。
        if self.is_awake():
            self._execute_special_action()

        plan, _ = self.make_schedule()  # 制定或获取当前计划

        # 处理睡眠状态
        if (plan["describe"] == "sleeping" or "睡" in plan["describe"]) and self.is_awake():  # 计划睡觉且当前醒着
            self.logger.info("{} is going to sleep...".format(self.name))  # 记录睡眠日志
            address = self.spatial.find_address("睡觉", as_list=True)  # 查找睡觉地点
            
            tiles = self.maze.get_address_tiles(address) # 获取该地址的可用地块集合

            # 确保 tiles 是一个列表并且不为空，才从中选择
            if tiles and isinstance(tiles, (list, set, tuple)) and len(list(tiles)) > 0: # 检查 tiles 是否有效且非空
                list_of_coords = list(tiles) # 转换为列表以用于 random.choice
                coord = random.choice(list_of_coords)  # 从有效坐标中随机选择一个
                
                current_events_after_move = self.move(coord)  # 移动到选定的睡觉地点
                if events is not None and isinstance(events, dict): # 确保 events 是一个可更新的字典
                    events.update(current_events_after_move)
                else: # 如果 events 无效，则直接使用移动后的事件
                    events = current_events_after_move

                # 创建睡眠相关的事件
                self.action = memory.Action(
                    memory.Event(self.name, "正在", "睡觉", address=address, emoji="😴"),
                    memory.Event(
                        address[-1], # 假设 address 至少有一个元素 (对象名称)
                        "被占用",
                        self.name,
                        address=address,
                        emoji="🛌",
                    ),
                    duration=plan["duration"],
                    start=utils.get_timer().daily_time(plan["start"]),
                )
            else:
                # 如果找不到睡觉地点 (tiles 无效或为空)
                self.logger.warning(f"{self.name} 找不到睡觉地点或可用地块 (address: {address}, tiles: {tiles})，跳过睡眠。")
                # 此处可以添加回退逻辑，例如保持当前活动，或者执行其他默认行为
                # 为了简单起见，我们这里不改变 action，智能体将继续当前活动或在下一个循环中重新评估
                # 但我们仍然需要更新 plan 的 emojis 部分，以反映当前状态（可能没有移动）
                # 注意：如果 'events' 在此分支中未被 'move' 更新，它将保留来自 think 方法开始时的值。
                # emojis = {} # 重新初始化或基于现有 events 构建
                # if self.action:
                #     emojis[self.name] = {"emoji": self.get_event().emoji, "coord": self.coord}
                # if events and isinstance(events, dict):
                #     for eve, event_coord_val in events.items():
                #         if eve.subject in agents:
                #             continue
                #         emojis[":".join(eve.address)] = {"emoji": eve.emoji, "coord": event_coord_val}
                # self.plan["emojis"] = emojis # 只更新表情，路径等可能保持不变或在 find_path 中更新
                # return self.plan # 也可以考虑提前返回，取决于期望行为
                # 按照参考代码的风格，它没有复杂的 else 回退并提前返回，而是继续执行后续的 think 逻辑
                pass # 允许继续执行后续的 think 逻辑 (percept, make_plan, reflect)

        # 处理清醒状态
        if self.is_awake():  # 如果智能体醒着
            self.percept()  # 感知环境
            self.make_plan(agents)  # 制定计划
            self.logger.info(f"{self.name} is about to call self.reflect()") # 添加日志
            self.reflect()  # 反思和总结
            self.logger.info(f"{self.name} has finished self.reflect()") # 添加日志
        else:  # 智能体觉
            if self.action.finished():  # 如果当前动作已完成
                self.action = self._determine_action()  # 确定下一个动作

        # 更新表情状态
        emojis = {}  # 初始化表情字典
        if self.action:  # 如果有当前动作
            emojis[self.name] = {"emoji": self.get_event().emoji, "coord": self.coord}  # 添加智能体的表情
        for eve, coord in events.items():  # 遍历所有事件
            if eve.subject in agents:  # 跳过其他智能体的事件
                continue
            emojis[":".join(eve.address)] = {"emoji": eve.emoji, "coord": coord}  # 添加事件相关的表情

        # 更新计划信息
        self.plan = {
            "name": self.name,  # 智能体名称
            "path": [], # 先初始化为空列表
            "emojis": emojis,  # 表情信息
        }
        self.logger.info(f"{self.name} is about to call self.find_path()") # 添加日志
        path_result = self.find_path(agents) # 寻找路径
        self.plan["path"] = path_result
        self.logger.info(f"{self.name} has finished self.find_path(), path found: {'Yes' if path_result else 'No'}") # 添加日志
        return self.plan

    def _execute_special_action(self):
        """
        在代理到达目的地后，执行特殊活动（如绘画、音乐创作等）。
        这个方法应该在 think 循环中被调用。
        """
        # 仅当代理已到达（没有路径要走）、有活动且活动未结束时才执行
        if self.action.finished():
            return

    
        # Agent可能提前到达，但应等到计划时间再开始活动
        current_game_time = utils.get_timer().get_date()
        if current_game_time < self.action.start:
            self.logger.debug(f"{self.name} 已到达目的地，但正在等待计划的开始时间 {self.action.start.strftime('%H:%M:%S')}")
            return

        address = self.get_event().address
        if not address:
            return

        terminal = address[-1]
        
        # 定义各种终端的名称列表
        painting_terminals = ["丹青画案"]
        music_terminals = ["焦尾琴"]
        quantum_terminals = ["太乙推演盘"]

        # 关键修复：验证Agent是否真的在正确的终端位置
        current_tile = self.get_tile()
        current_address = current_tile.get_address("game_object", as_list=True)
        
        # 检查当前位置是否包含目标终端
        if not current_address or terminal not in current_address:
            # Agent还没有真正到达目标终端，不执行特殊活动
            self.logger.debug(f"{self.name} 计划使用 {terminal}，但当前位置 {current_address} 不包含该终端，等待到达")
            return

        # 额外的安全检查：确保Agent的目标地址和当前地址匹配
        if address != current_address:
            self.logger.debug(f"{self.name} 目标地址 {address} 与当前地址 {current_address} 不匹配，等待到达正确位置")
            return

        # 验证通过，Agent确实在正确位置，可以执行特殊活动
        self.logger.info(f"{self.name} 已到达 {terminal}，开始执行特殊活动")
        
        # 根据终端类型调用相应的处理函数
        if terminal in painting_terminals:
            self._handle_painting_action()
        elif terminal in music_terminals:
            self._handle_music_action()
        elif terminal in quantum_terminals:
            self._handle_quantum_computing_action()

    def _handle_painting_action(self):
        """处理绘画创作活动。"""
        print(f"检测到 {self.name} 正在绘画创作")

        # 获取计划中的结束时间
        planned_end_time = self.action.start + datetime.timedelta(minutes=self.action.duration)
        current_time_str = planned_end_time.strftime("%Y-%m-%d %H:%M:%S")

        # 检查是否达到绘画次数限制
        if self.last_painting_time is not None and planned_end_time - self.last_painting_time < datetime.timedelta(hours=1):
            print(f"{self.name} 在过去一小时内已经使用过画架，需等待后才能再次使用。")
            return
        
        # 允许使用画架，并更新计数和时间戳
        self.painting_count += 1
        self.last_painting_time = planned_end_time
        print(f"{self.name} 第 {self.painting_count} 次绘画创作")

        # 构建绘画提示词
        painting_prompt = self.completion("generate_painting_prompt", self)

        # 将时间和提示词写入 JSON 文件
        max_retries = 3
        retry_delay = 0.1

        # 循环尝试删除可能存在的编码错误的文件
        for attempt in range(max_retries):
            try:
                # 检查文件是否存在
                if os.path.exists("results/painting_records.json"):
                    # 打开文件并尝试读取
                    with open("results/painting_records.json", "r", encoding="utf-8") as f:
                        try:
                            # 尝试读取文件前 50 个字符来检测编码错误
                            f.read(50)
                        except UnicodeDecodeError:
                            # 捕获到 Unicode 解码错误，说明文件编码可能错误
                            print("检测到 painting_records.json 文件编码错误，尝试删除...")
                            # 删除文件
                            os.remove("results/painting_records.json")
                            print("已删除 painting_records.json 文件。")
                            break  # 删除成功，跳出循环
            except PermissionError:
                # 捕获到权限错误，说明文件可能被占用
                print(f"删除 painting_records.json 文件失败，尝试 {attempt + 1}/{max_retries}...")
                # 等待一段时间后重试
                time.sleep(retry_delay)
        else:
            # 如果循环结束仍未成功删除文件，则打印错误信息
            print(f"重试 {max_retries} 次后仍然无法删除 painting_records.json 文件。")

        # 尝试读取 JSON 文件
        try:
            with open("results/painting_records.json", "r", encoding="utf-8", errors="replace") as f:
                data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError, PermissionError):
            # 如果文件不存在、JSON 解码错误或权限错误，则初始化一个空列表
            print("读取 painting_records.json 文件失败")
            data = []

        # 检查是否已经存在相同或类似的记录
        similar_record_exists = any(
            record["时间"] == current_time_str and
            record["智能体"] == self.name and
            record["绘画内容"] == painting_prompt
            for record in data
        )

        # 如果不存在相同或类似的记录，则添加新记录
        if not similar_record_exists:
            data.append({
                "时间": current_time_str,  # 将 datetime 对象转换为字符串
                "智能体": self.name,
                "绘画内容": painting_prompt
            })

            # 将更新后的数据写回 JSON 文件
            with open("results/painting_records.json", "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
        else:
            print(f"已存在相同或类似的绘画记录，跳过保存")

        # --- 将绘画内容添加到智能体记忆中 ---
        event_description = f"{self.name} 在 {current_time_str} 创作了一幅画作，其核心内容是：{painting_prompt}"
        
        painting_memory_event = memory.Event(
            subject=self.name,
            predicate="创作了",
            object="一幅画作",
            describe=event_description,
            address=self.get_tile().get_address(),
            emoji="🎨"
        )
        
        new_memory_concept = self._add_concept("thought", painting_memory_event)
        
        if new_memory_concept:
            self.logger.info(f"{self.name} 成功将绘画思考加入记忆。")
            self.logger.info(f"  记忆ID: {new_memory_concept.node_id}")
            self.logger.info(f"  类型: {new_memory_concept.node_type}")
            self.logger.info(f"  创建时间: {new_memory_concept.create.strftime('%Y-%m-%d %H:%M:%S')}")
            self.logger.info(f"  描述: {new_memory_concept.describe[:150]}...")
            self.logger.info(f"  重要性评分 (Poignancy): {new_memory_concept.poignancy}")
            self.logger.info(f"  事件主体: {new_memory_concept.event.subject}, 谓词: {new_memory_concept.event.predicate}, 宾语: {new_memory_concept.event.object}")
        else:
            self.logger.warning(f"{self.name} 尝试添加绘画思考到记忆，但 _add_concept 返回 None。")

    def _handle_music_action(self):
        """处理音乐创作活动。"""
        print(f"检测到 {self.name} 正在使用乐器")
        
        # 获取计划中的结束时间
        planned_end_time = self.action.start + datetime.timedelta(minutes=self.action.duration)
        current_time_str = planned_end_time.strftime("%Y-%m-%d %H:%M:%S")

        if self.last_music_composition_time is not None and planned_end_time - self.last_music_composition_time < datetime.timedelta(hours=self.music_composition_limit):
            print(f"{self.name} 在过去一小时内已经使用过音乐器，需等待后才能再次使用。")
            return
        
        self.music_composition_count += 1
        self.last_music_composition_time = planned_end_time
        print(f"{self.name} 第 {self.music_composition_count} 次使用音乐器")

        music_prompt = self.completion("generate_music_prompt", self)

        music_records_path = "results/music_records.json"
        os.makedirs(os.path.dirname(music_records_path), exist_ok=True)
        
        max_retries = 3
        retry_delay = 0.1
        for attempt in range(max_retries):
            try:
                if os.path.exists(music_records_path):
                    with open(music_records_path, "r", encoding="utf-8") as f:
                        try:
                            f.read(50)
                        except UnicodeDecodeError:
                            print(f"检测到 {music_records_path} 文件编码错误，尝试删除...")
                            os.remove(music_records_path)
                            print(f"已删除 {music_records_path} 文件。")
                            break 
            except PermissionError:
                print(f"删除 {music_records_path} 文件失败，尝试 {attempt + 1}/{max_retries}...")
                time.sleep(retry_delay)
        else:
            if os.path.exists(music_records_path):
                 print(f"重试 {max_retries} 次后仍然无法删除 {music_records_path} 文件。")

        try:
            with open(music_records_path, "r", encoding="utf-8", errors="replace") as f:
                data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError, PermissionError):
            print(f"读取 {music_records_path} 文件失败或文件为空/损坏，初始化新列表。")
            data = []

        similar_record_exists = any(
            record["时间"] == current_time_str and
            record["智能体"] == self.name and
            record["音乐内容"] == music_prompt
            for record in data
        )

        if not similar_record_exists:
            data.append({
                "时间": current_time_str,
                "智能体": self.name,
                "音乐内容": music_prompt
            })
            with open(music_records_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
        else:
            print(f"已存在相同或类似的音乐记录，跳过保存")

        music_event_description = f"{self.name} 在 {current_time_str} 创作了一段音乐，其核心内容是：{music_prompt}"
        
        music_memory_event = memory.Event(
            subject=self.name,
            predicate="创作了", 
            object="一段音乐",   
            describe=music_event_description, 
            address=self.get_tile().get_address(),
            emoji="🎵"  
        )
        
        new_music_memory_concept = self._add_concept("thought", music_memory_event)
        
        if new_music_memory_concept:
            self.logger.info(f"{self.name} 成功将音乐创作思考加入记忆。")
            self.logger.info(f"  记忆ID: {new_music_memory_concept.node_id}")
            self.logger.info(f"  类型: {new_music_memory_concept.node_type}")
            self.logger.info(f"  创建时间: {new_music_memory_concept.create.strftime('%Y-%m-%d %H:%M:%S')}")
            self.logger.info(f"  描述: {new_music_memory_concept.describe[:150]}...")
            self.logger.info(f"  重要性评分 (Poignancy): {new_music_memory_concept.poignancy}")
            self.logger.info(f"  事件主体: {new_music_memory_concept.event.subject}, 谓词: {new_music_memory_concept.event.predicate}, 宾语: {new_music_memory_concept.event.object}")
        else:
            self.logger.warning(f"{self.name} 尝试添加音乐创作思考到记忆，但 _add_concept 返回 None。")

    def _handle_quantum_computing_action(self):
        """处理量子计算活动。"""
        print(f"检测到 {self.name} 正在使用量子生命终端")
        
        # 获取计划中的结束时间
        planned_end_time = self.action.start + datetime.timedelta(minutes=self.action.duration)
        current_time_str = planned_end_time.strftime("%Y-%m-%d %H:%M:%S")

        if (self.last_quantum_computing_time is not None and
            planned_end_time - self.last_quantum_computing_time < datetime.timedelta(hours=self.quantum_computing_limit)):
            print(f"{self.name} 在过去一小时内已经使用过量子生命终端，需等待后才能再次使用。")
            return
        
        self.quantum_computing_count += 1
        self.last_quantum_computing_time = planned_end_time
        print(f"{self.name} 第 {self.quantum_computing_count} 次使用量子生命终端")

        # 注意：这里假设你会在 prompt.py 中定义 generate_game_life_rule
        quantum_computing_prompt = self.completion("generate_game_life_rule", self)

        quantum_records_path = "results/quantum_computing_records.json"
        quantum_records_dir = os.path.dirname(quantum_records_path)
        if not os.path.exists(quantum_records_dir):
            os.makedirs(quantum_records_dir, exist_ok=True)
        
        max_retries = 3
        retry_delay = 0.1
        for attempt in range(max_retries):
            try:
                if os.path.exists(quantum_records_path):
                    with open(quantum_records_path, "r", encoding="utf-8") as f:
                        try:
                            f.read(50)
                        except UnicodeDecodeError:
                            print(f"检测到 {quantum_records_path} 文件编码错误，尝试删除...")
                            os.remove(quantum_records_path)
                            print(f"已删除 {quantum_records_path} 文件。")
                            break 
            except PermissionError:
                print(f"删除 {quantum_records_path} 文件失败，尝试 {attempt + 1}/{max_retries}...")
                time.sleep(retry_delay)
        else:
            if os.path.exists(quantum_records_path):
                 print(f"重试 {max_retries} 次后仍然无法删除 {quantum_records_path} 文件。")

        try:
            with open(quantum_records_path, "r", encoding="utf-8", errors="replace") as f:
                data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError, PermissionError):
            print(f"读取 {quantum_records_path} 文件失败或文件为空/损坏，初始化新列表。")
            data = []

        similar_record_exists = any(
            record.get("时间") == current_time_str and
            record.get("智能体") == self.name and
            record.get("量子计算内容") == quantum_computing_prompt
            for record in data
        )

        if not similar_record_exists:
            data.append({
                "时间": current_time_str,
                "智能体": self.name,
                "量子计算内容": quantum_computing_prompt
            })
            with open(quantum_records_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
        else:
            print(f"已存在相同或类似的量子计算记录，跳过保存")

        quantum_event_description = f"{self.name} 在 {current_time_str} 使用了量子生命终端进行了一次计算，其核心内容是：{quantum_computing_prompt}"
        
        quantum_memory_event = memory.Event(
            subject=self.name,
            predicate="执行了", 
            object="一次量子计算",   
            describe=quantum_event_description, 
            address=self.get_tile().get_address(),
            emoji="⚛️"
        )
        
        new_quantum_memory_concept = self._add_concept("thought", quantum_memory_event)
        
        if new_quantum_memory_concept:
            self.logger.info(f"{self.name} 成功将量子计算思考加入记忆。")
            self.logger.info(f"  记忆ID: {new_quantum_memory_concept.node_id}")
            self.logger.info(f"  类型: {new_quantum_memory_concept.node_type}")
            self.logger.info(f"  创建时间: {new_quantum_memory_concept.create.strftime('%Y-%m-%d %H:%M:%S')}")
            self.logger.info(f"  描述: {new_quantum_memory_concept.describe[:150]}...")
            self.logger.info(f"  重要性评分 (Poignancy): {new_quantum_memory_concept.poignancy}")
            self.logger.info(f"  事件主体: {new_quantum_memory_concept.event.subject}, 谓词: {new_quantum_memory_concept.event.predicate}, 宾语: {new_quantum_memory_concept.event.object}")
        else:
            self.logger.warning(f"{self.name} 尝试添加量子计算思考到记忆，但 _add_concept 返回 None。")

    def move(self, coord, path=None):
        """处理智能体的移动和位置更新
        Args:
            coord: 目标坐标
            path: 移动路径,默认为None
        Returns:
            dict: 移动过程中涉及的事件字典
        """
        events = {}  # 初始化事件字典

        def _update_tile(coord):
            """新指地块事件
            Args:
                coord: 要更新的地块坐标
            Returns:
                dict: 地块上的事件字典
            """
            tile = self.maze.tile_at(coord)  # 获取指定坐标的地块
            if not self.action:  # 如果没有当前动作
                return {}
            if not tile.update_events(self.get_event()):  # 如果更新事件失败
                tile.add_event(self.get_event())  # 添加新事件
            obj_event = self.get_event(False)  # 获取对象事件
            if obj_event:  # 如果存在对象事件
                self.maze.update_obj(coord, obj_event)  # 更新地块对象
            return {e: coord for e in tile.get_events()}  # 返回地块上的所有事件

        # 处理位置变化
        if self.coord and self.coord != coord:  # 如果当前位置存在且不等于目标位置
            tile = self.get_tile()  # 获取当前地块
            tile.remove_events(subject=self.name)  # 移除与智能体相关的事件
            if tile.has_address("game_object"):  # 如果地块有游戏对象
                addr = tile.get_address("game_object")  # 获取游戏对象地址
                self.maze.update_obj(
                    self.coord, memory.Event(addr[-1], address=addr)
                )  # 更新游戏对象状态
            events.update({e: self.coord for e in tile.get_events()})  # 更新事件字典
        
        # 更新新位置的事件
        if not path:  # 如果没有指定路径
            events.update(_update_tile(coord))  # 更新目标位置的事件
        
        # 更新智能体位置信息
        self.coord = coord  # 更新当前坐标
        self.path = path or []  # 更新移动路径

        return events  # 返回所有相关事件

    def make_schedule(self):
        """制定或获取智能体的日程安排
        Returns:
            tuple: (当前计划, 分解后的计划)
        """
        if not self.schedule.scheduled():  # 如果还没有制定计划
            self.logger.info("{} is making schedule...".format(self.name))  # 记录日志
            
            # 更新当前状态描述
            if self.associate.index.nodes_num > 0:  # 如果有关联记忆
                self.associate.cleanup_index()  # 清理索引
                focus = [  # 设置关注点
                    f"{self.name} 在 {utils.get_timer().daily_format_cn()} 的计划。",
                    f"在 {self.name} 的生活中，重要的近期事件。",
                ]
                retrieved = self.associate.retrieve_focus(focus)  # 索相关忆
                self.logger.info(
                    "{} retrieved {} concepts".format(self.name, len(retrieved))
                )  # 记录检索结果
                if retrieved:  # 如果检索到相关概念
                    plan = self.completion("retrieve_plan", retrieved)  # 生成计划
                    thought = self.completion("retrieve_thought", retrieved)  # 生成想法
                    self.scratch.currently = self.completion(
                        "retrieve_currently", plan, thought
                    )  # 更新当前状态描述

            # 创建初始日程
            self.schedule.create = utils.get_timer().get_date()  # 设置日创建时间为当前时间
            wake_up = self.completion("wake_up")  # 生成起床时间
            init_schedule = self.completion("schedule_init", wake_up)  # 根据起床时间生成初始日程安排

            # 创建每日详细日程
            hours = [f"{i}:00" for i in range(24)]  # 生成24小时的时间点列表
            seed = [(h, "睡觉") for h in hours[:wake_up]]  # 在起床前的时间安排睡觉
            seed += [(h, "") for h in hours[wake_up:]]  # 在起床后的时间暂时留空

            schedule = {}  # 初始化日程字典
            for _ in range(self.schedule.max_try):  # 尝试多次成合适的日程
                schedule = {h: s for h, s in seed[:wake_up]}  # 复睡眠时间的安排
                schedule.update(
                    self.completion("schedule_daily", wake_up, init_schedule)
                )  # 生成每日具体日程
                if len(set(schedule.values())) >= self.schedule.diversity:  # 如果日程活动足够多样
                    break  # 结束尝试

            def _to_duration(date_str):
                """将时间字符串转换为从午夜开始的分钟数
                Args:
                    date_str: 时间字符串(HH:MM格式)
                Returns:
                    int: 从午夜开始的分钟数
                """
                # 兼容 LLM 偶尔生成的越界时间（如 "24:00"、"25:30"），统一按分钟数处理并截断到一天内
                try:
                    hour, minute = date_str.strip().split(":")
                    minutes = int(hour) * 60 + int(minute)
                except Exception:
                    return utils.daily_duration(utils.to_date(date_str, "%H:%M"))
                return min(minutes, 24 * 60 - 1)

            # 将时间转换为分钟并添加到日程中
            schedule = {_to_duration(k): v for k, v in schedule.items()}  # 转换时间格式
            starts = list(sorted(schedule.keys()))  # 获取排序后的时间点列表
            for idx, start in enumerate(starts):  # 遍历每个时间点
                end = starts[idx + 1] if idx + 1 < len(starts) else 24 * 60  # 计算结束时间
                self.schedule.add_plan(schedule[start], end - start)  # 添加计划到日程中

            # 记录日程安排的考过程
            schedule_time = utils.get_timer().time_format_cn(self.schedule.create)  # 获取日程创建时间
            thought = "这是 {} 在 {} 的计划：{}".format(
                self.name, schedule_time, "；".join(init_schedule)
            )  # 生成思考内容
            event = memory.Event(
                self.name,
                "计划",
                schedule_time,
                describe=thought,
                address=self.get_tile().get_address(),
            )  # 创建计划事件
            self._add_concept(
                "thought",
                event,
                expire=self.schedule.create + datetime.timedelta(days=30),
            )  # 添加计划概念，设置30天后过期

            # 分解当前计划
            plan, _ = self.schedule.current_plan()  # 获取当前计划
            if self.schedule.decompose(plan):  # 如果需要分解计划
                decompose_schedule = self.completion(
                    "schedule_decompose", plan, self.schedule
                )  # 生成计划的分解步骤
                decompose, start = [], plan["start"]  # 初始化分解列表和开始时间
                for describe, duration in decompose_schedule:  # 遍历每个分解步骤
                    decompose.append(
                        {
                            "idx": len(decompose),  # 步骤引
                            "describe": describe,  # 步骤描述
                            "start": start,  # 开始时间
                            "duration": duration,  # 持续时间
                        }
                    )  # 添加分解步骤
                    start += duration  # 更新下一步骤的开始时间
                plan["decompose"] = decompose  # 将分解步骤添加到计划中
        
        # 确保在所有情况下都返回当前计划
        return self.schedule.current_plan()  # 返回当前计划和分解后的计划

    def revise_schedule(self, event, start, duration):
        """修改当前计划
        Args:
            event: 要添加的事件
            start: 开始时间
            duration: 持续时间
        """
        self.action = memory.Action(event, start=start, duration=duration)  # 创建新的动作
        plan, _ = self.schedule.current_plan()  # 获取当前计划
        if len(plan["decompose"]) > 0:  # 如果计划已经被分解
            plan["decompose"] = self.completion(
                "schedule_revise", self.action, self.schedule
            )  # 根据新动作修改分解计划

    def percept(self):
        """感环境并更新记忆
        处理智能体对周围环境的感知，包括空间记忆和件记忆的更新
        """
        # 获取感知范围内的地块
        scope = self.maze.get_scope(self.coord, self.percept_config)  # 获取感知范围内的地块
        
        # 更新空间记忆
        for tile in scope:  # 遍历每个地块
            if tile.has_address("game_object"):  # 如果地块包含游戏对象
                self.spatial.add_leaf(tile.address)  # 将对象地址添加到空间记忆中
                
        events, arena = {}, self.get_tile().get_address("arena")  # 初始化事件字典和当前域
        
        # 收集范围的事件
        for tile in scope:  # 遍历感知范围内的地块
            if not tile.events or tile.get_address("arena") != arena:  # 如果地块没有事件或不在同一区域
                continue
            dist = math.dist(tile.coord, self.coord)  # 计算与地块的距离
            for event in tile.get_events():  # 遍历地块上的事件
                if dist < events.get(event, float("inf")):  # 如果这是最近的相同事件
                    events[event] = dist  # 更新事件距离

        # 对事件距离排序
        events = list(sorted(events.keys(), key=lambda k: events[k]))  # 将事件按距离排序
        
        # 处理概念生成
        self.concepts, valid_num = [], 0  # 初始化概念列表和有效概念计数
        for idx, event in enumerate(events[: self.percept_config["att_bandwidth"]]):  # 在注意力带宽范围内遍历事件
            # 获取最近的记忆节点
            recent_nodes = (
                self.associate.retrieve_events() + self.associate.retrieve_chats()
            )  # 获取最近的事件和对话记忆
            recent_nodes = set(n.describe for n in recent_nodes)  # 提取记忆描述集合
            
            # 检查事件是否已经存在于最近记忆中
            if event.get_describe() not in recent_nodes:  # 如果是新事件
                if event.object == "idle" or event.object == "空闲":  # 如果是空闲状态
                    node = Concept.from_event(
                        "idle_" + str(idx), "event", event, poignancy=1
                    )  # 创建低显著性的空闲概念
                    # 将空闲事件也加入概念，以便触发社交反应
                    self.concepts.append(node)
                else:  # 如果是其他事件
                    valid_num += 1  # 增加有效概念计数
                    node_type = "chat" if event.fit(self.name, "对话") else "event"  # 确定概念类型
                    node = self._add_concept(node_type, event)  # 添加新概念
                    if node is not None:
                        self.status["poignancy"] += node.poignancy  # 更新显著状态
                        self.concepts.append(node)  # 将概念添加到列表
                    else:
                        # 索引写入失败或被跳过,不影响主流程
                        self.logger.warning(f"{self.name} _add_concept returned None; skipping poignancy update for event: {event}")
                        continue
                
        # 过滤掉与自身相关的概念
        self.concepts = [c for c in self.concepts if c.event.subject != self.name]  # 移除自身相关的概念
        
        # 记录感知结果
        self.logger.info(
            "{} percept {}/{} concepts".format(self.name, valid_num, len(self.concepts))
        )  # 记录感知到的概念数量

    def make_plan(self, agents):
        """制定智能体的行动计划
        Args:
            agents: 其他智能体的字典
        """
        if self._reaction(agents):  # 如果对其他智能体有反应
            return  # 束计划制定
        if self.path:  # 如果已有移动路径
            return  # 保持当前路径
        if self.action.finished():  # 如果当前动作已完成
            self.action = self._determine_action()  # 确定下一个动作

    def make_event(self, subject, describe, address):
        """创建新的事件对象
        Args:
            subject: 事件主体
            describe: 事件描述
            address: 事件地址
        Returns:
            Event: 创建的事件对象
        """
        # 清理事件描述中的特殊字符
        e_describe = describe.replace("(", "").replace(")", "").replace("<", "").replace(">", "")
        
        # 移重复的主体描述
        if e_describe.startswith(subject + "此时"):
            e_describe = e_describe[len(subject + "此时"):]
        if e_describe.startswith(subject):
            e_describe = e_describe[len(subject):]
            
        # 创建并返回事件对象
        event = memory.Event(
            subject,  # 事件主体
            "此时",  # 事件状态
            e_describe,  # 处理后的描述
            describe=describe,  # 原始描述
            address=address  # 事件地址
        )
        return event

    def reflect(self):
        """反思和总结经验
        处理智能体的反思过程，包括思考总结和对话记忆的处理
        """
        def _add_thought(thought, evidence=None):
            """添加思考记忆并记录到文件

            Args:
                thought: 思考内容
                evidence: 支持证据
            Returns:
                Concept: 创建的思考概念
            """
            # --- 新增：记录反思内容到文件 ---
            # 从 storage_root 动态提取模拟名称
            simulation_name = None
            try:
                path_parts = os.path.normpath(self._storage_root).split(os.sep)
                if 'checkpoints' in path_parts:
                    chk_index = path_parts.index('checkpoints')
                    if chk_index + 1 < len(path_parts):
                        simulation_name = path_parts[chk_index + 1]
            except Exception as e:
                self.logger.error(f"无法从 self._storage_root ('{self._storage_root}') 提取 simulation_name: {e}")

            if simulation_name:
                reflection_records_dir = os.path.join("results", "reflection-records")
                if not os.path.exists(reflection_records_dir):
                    os.makedirs(reflection_records_dir, exist_ok=True)
                reflection_records_path = os.path.join(reflection_records_dir, f"{simulation_name}.json")
            else:
                # 如果无法获取模拟名称，则回退到旧的单一文件逻辑
                reflection_records_path = "results/reflection_records.json"
                reflection_records_dir = os.path.dirname(reflection_records_path)
                if not os.path.exists(reflection_records_dir):
                    os.makedirs(reflection_records_dir, exist_ok=True)


            current_time_str = utils.get_timer().get_date().strftime("%Y-%m-%d %H:%M:%S")

            max_retries = 3
            retry_delay = 0.1
            for attempt in range(max_retries):
                try:
                    if os.path.exists(reflection_records_path):
                        with open(reflection_records_path, "r", encoding="utf-8") as f:
                            try:
                                f.read(50)
                            except UnicodeDecodeError:
                                print(f"检测到 {reflection_records_path} 文件编码错误，尝试删除...")
                                os.remove(reflection_records_path)
                                print(f"已删除 {reflection_records_path} 文件。")
                                break
                except PermissionError:
                    print(f"删除 {reflection_records_path} 文件失败，尝试 {attempt + 1}/{max_retries}...")
                    time.sleep(retry_delay)
            else:
                if os.path.exists(reflection_records_path):
                    print(f"重试 {max_retries} 次后仍然无法删除 {reflection_records_path} 文件。")

            try:
                with open(reflection_records_path, "r", encoding="utf-8", errors="replace") as f:
                    data = json.load(f)
            except (FileNotFoundError, json.JSONDecodeError, PermissionError):
                print(f"读取 {reflection_records_path} 文件失败或文件为空/损坏，初始化新列表。")
                data = []

            similar_record_exists = any(
                record.get("时间") == current_time_str
                and record.get("智能体") == self.name
                and record.get("反思内容") == thought
                for record in data
            )

            if not similar_record_exists:
                new_record = {
                    "时间": current_time_str,
                    "智能体": self.name,
                    "反思内容": thought,
                }
                if evidence:
                    new_record["证据"] = evidence # 将证据也记录下来
                data.append(new_record)

                with open(reflection_records_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=4)
            else:
                print("已存在相同或类似的反思记录，跳过保存")

            # --- 原有逻辑 ---
            event = self.make_event(
                self.name, thought, self.get_tile().get_address()
            )  # 创建思考事件
            return self._add_concept(
                "thought", event, filling=evidence
            )  # 添加思考概念

        # 检查是否要进行反应
        if self.status["poignancy"] < self.think_config["poignancy_max"]:  # 如果显著性未达到阈
            return  # 不进行反思
            
        # 获取相关记忆节点
        nodes = (
            self.associate.retrieve_events() + self.associate.retrieve_thoughts()
        )  # 获取事件和思考记忆
        if not nodes:  # 如果没有相关记忆
            return  # 不进行反思
            
        # 记录反思开始
        self.logger.info(
            "{} reflect(P{}/{}) with {} concepts...".format(
                self.name,
                self.status["poignancy"],
                self.think_config["poignancy_max"],
                len(nodes),
            )
        )  # 记录反思状态
        
        # 选择重要的记忆节点
        nodes = sorted(nodes, key=lambda n: n.access, reverse=True)[
            : self.associate.max_importance
        ]  # 按访问频率排序并选择最重要的节点
        
        # 生成思考焦点
        focus = self.completion("reflect_focus", nodes, 3)  # 生成反思焦点
        retrieved = self.associate.retrieve_focus(focus, reduce_all=False)  # 检索相关记忆
        
        # 基于检索到的记忆生成见解
        for r_nodes in retrieved.values():  # 遍历组相关记忆
            thoughts = self.completion("reflect_insights", r_nodes, 5)  # 生成见解
            for thought, evidence_insight in thoughts:  # 遍历每个见解 # 重命名 evidence 以避免冲突
                _add_thought(thought, evidence_insight)  # 添加思考记忆
                
        # 生成对话相关的思考
        thought_chat_plan = self.completion("reflect_chat_planing", self.chats)  # 基于对话生成计划相关的思考
        _add_thought(f"对于 {self.name} 的计划：{thought_chat_plan}", None)  # 传递 None 作为 evidence
        
        thought_chat_memory = self.completion("reflect_chat_memory", self.chats)  # 基于对话生成记忆相关的思考
        _add_thought(f"{self.name} {thought_chat_memory}", None)  # 传递 None 作为 evidence
        
        # 重置状态
        self.status["poignancy"] = 0  # 重置显著性状态

    def find_path(self, agents):
        """寻找到目标位置的路径
        Args:
            agents: 其他智能体的字典
        Returns:
            list: 移动路径的坐标列表
        """
        address = self.get_event().address  # 获取目标事件的地址
        self.logger.info(f"{self.name} finding path to address: {address}. Current path: {self.path}. Current coord: {self.coord}")

        if self.path:  # 如果已有路径
            self.logger.info(f"{self.name} already has a path: {self.path}")
            return self.path  # 返回当前路径
        if address == self.get_tile().get_address():  # 如果已在目标位置
            self.logger.info(f"{self.name} is already at the target address: {address}")
            return []  # 返回空路径
        if address[0] == "<waiting>":  # 果是等待状态
            self.logger.info(f"{self.name} is in <waiting> state, no path needed.")
            return []  # 返回空路径
            
        # 取目标地块
        if address[0] == "<persona>":  # 如果目标是其他智能体
            target_agent_name = address[1]
            if target_agent_name in agents:
                target_agent_coord = agents[target_agent_name].coord
                target_tiles = self.maze.get_around(target_agent_coord)
                self.logger.info(f"{self.name} target is persona {target_agent_name} at {target_agent_coord}. Target tiles around: {target_tiles}")
            else:
                self.logger.warning(f"{self.name} target persona {target_agent_name} not found in agents. Cannot find path.")
                return []
        else:  # 如果是普通目标
            target_tiles = self.maze.get_address_tiles(address)
            self.logger.info(f"{self.name} target is a location. Target tiles for address {address}: {target_tiles}")

        if not target_tiles: # 确保 target_tiles 不是 None 或空
            self.logger.warning(f"{self.name} found no target_tiles for address: {address}. Cannot find path.")
            return []

        if tuple(self.coord) in target_tiles:  # 如果已在目标地块
            self.logger.info(f"{self.name} is already in one of the target_tiles {self.coord}.")
            return []  # 返回空路径

        # 过滤掉不可用的目标地块
        def _ignore_target(t_coord):
            """检查目标地块是否可用
            Args:
                t_coord: 目标坐标
            Returns:
                bool: 是否应该忽略该地块
            """
            if list(t_coord) == list(self.coord):  # 如果是当前位置
                return True
            events_on_tile = self.maze.tile_at(t_coord).get_events()  # 获取地块上的事件
            if any(e.subject in agents for e in events_on_tile):  # 如果地块被其他智能体占用
                return True
            return False

        # 过滤并选择目标地块
        original_target_tiles_count = len(target_tiles)
        target_tiles = [t for t in target_tiles if not _ignore_target(t)]  # 过滤掉不可用的地块
        self.logger.info(f"{self.name} filtered target_tiles. Original count: {original_target_tiles_count}, New count: {len(target_tiles)}. Filtered list: {target_tiles}")

        if not target_tiles:  # 如果没有可用的目标地块
            self.logger.warning(f"{self.name} 找不到合适的目标地块 after filtering for address: {address}")
            return []  # 返回空路径
        if len(target_tiles) >= 4:  # 如果可用地块超过4个
            sampled_tiles = random.sample(target_tiles, 4)  # 随机选择4个地块
            self.logger.info(f"{self.name} sampled 4 target_tiles: {sampled_tiles} from {len(target_tiles)}")
            target_tiles = sampled_tiles
            
        pathes = {}  # 初始化路径字典
        for idx, t_coord in enumerate(target_tiles):
            self.logger.info(f"{self.name} trying to find path to target_tile {idx+1}/{len(target_tiles)}: {t_coord} from {self.coord}")
            try:
                # --- 核心寻路调用 ---
                path_to_t = self.maze.find_path(self.coord, t_coord)
                # --- 核心寻路调用结束 ---
                pathes[t_coord] = path_to_t
                self.logger.info(f"{self.name} found path to {t_coord}: {'Yes, length ' + str(len(path_to_t)) if path_to_t else 'No'}. Path: {path_to_t}")
            except Exception as e:
                self.logger.error(f"{self.name} error during self.maze.find_path({self.coord}, {t_coord}): {e}", exc_info=True)
                pathes[t_coord] = [] # 记录为空路径以避免后续错误

        if not pathes: # 如果因为某种原因 (例如所有目标地块都无法到达或出错) 导致 pathes 为空
            self.logger.warning(f"{self.name} no paths were calculated for target_tiles: {target_tiles}. Cannot determine shortest path.")
            return []

        # 选择最短的路径
        # 需要处理 pathes[p] 可能为 None 或空列表的情况
        valid_pathes = {t: p for t, p in pathes.items() if p} # 只考虑非空路径
        if not valid_pathes:
            self.logger.warning(f"{self.name} no valid (non-empty) paths found among {pathes}. Cannot find path.")
            return []
            
        target = min(valid_pathes, key=lambda p: len(valid_pathes[p]))  # 选择最短的路径
        final_path = valid_pathes[target][1:] # 返回除起点外的路径坐标
        self.logger.info(f"{self.name} selected shortest path to {target}. Final path (excluding start): {final_path}")
        return final_path

    def _determine_action(self):
        """确定下一个动作
        Returns:
            Action: 确定的下一个动作对象
        """
        self.logger.info("{} is determining action...".format(self.name))  # 录动作确定开始
        plan, de_plan = self.schedule.current_plan()  # 获取当前计划和分解计划
        describes = [plan["describe"], de_plan["describe"]]  # 获取计划描述列表
        
        # 查找目标地址
        address = self.spatial.find_address(describes[0], as_list=True)  # 尝试直接查找地址
        if not address:  # 如果没有找到直接匹配的地址
            tile = self.get_tile()  # 获当前地块
            kwargs = {  # 准备参数
                "describes": describes,  # 计划描述
                "spatial": self.spatial,  # 空间记忆
                "address": tile.get_address("world", as_list=True),  # 世界地址
            }
            # 确定域
            kwargs["address"].append(
                self.completion("determine_sector", **kwargs, tile=tile)
            )  # 确定区域
            
            # 确定场景
            arenas = self.spatial.get_leaves(kwargs["address"])  # 获取可用场景
            if len(arenas) == 1:  # 如果只有一个场景
                kwargs["address"].append(arenas[0])  # 直接使用该场景
            else:  # 如有多场景
                kwargs["address"].append(self.completion("determine_arena", **kwargs))  # 选择合适的场景
                
            # 确定对象
            objs = self.spatial.get_leaves(kwargs["address"])  # 获取可用对象
            if len(objs) == 1:  # 如果只有一个对象
                kwargs["address"].append(objs[0])  # 直接使用该对象
            elif len(objs) > 1:  # 如果有多个对象
                kwargs["address"].append(self.completion("determine_object", **kwargs))  # 选择合适的对象
            address = kwargs["address"]  # 使用构建的地址

        # 创建事件对象
        event = self.make_event(self.name, describes[-1], address)  # 创建智能体事件
        obj_describe = self.completion("describe_object", address[-1], describes[-1])  # 生成对象描述
        obj_event = self.make_event(address[-1], obj_describe, address)  # 创建对象事件

        # 设置事件表情
        event.emoji = f"{de_plan['describe']}"  # 设置事件表情为计划描述

        # --- 调试代码开始 ---
        self.logger.info(f"[DEBUG_DE_PLAN] For {self.name}, current de_plan in _determine_action: {de_plan}")
        
        duration_minutes = de_plan["duration"]
        if not isinstance(duration_minutes, (int, float)) or duration_minutes <= 0:
            self.logger.warning(
                f"{self.name}'s determined action '{de_plan.get('describe', 'Unknown Action')}' "
                f"had a duration of {duration_minutes} minutes. Forcing to 5 minutes."
            )
            duration_minutes = 5  # 强制设置为5分钟
        # --- 调试代码结束 ---

        # 创建并返回动作对象
        return memory.Action(
            event,  # 智能体事件
            obj_event,  # 对象事件
            duration=duration_minutes,  # 使用可能修正后的 duration
            start=utils.get_timer().daily_time(de_plan["start"]),  # 置开始时间
        )

    def _reaction(self, agents=None, ignore_words=None):
        """处理对其他智能体的反应
        Args:
            agents: 其他智能体的字典，默认为None
            ignore_words: 要忽略的关键词列表，默认None
        Returns:
            bool: 是否产生了反应
        """
        focus = None  # 初始化关注点
        ignore_words = ignore_words or ["空闲"]  # 设置默认忽略词

        def _focus(concept):
            """检查概念是否与其他智能体相关
            Args:
                concept: 要检查的概念
            Returns:
                bool: 是否他智能体相关
            """
            return concept.event.subject in agents  # 检查事件主体是否是其他智能体

        def _ignore(concept):
            """检查概念是否应该被忽略
            Args:
                concept: 要检查的概念
            Returns:
                bool: 是否应该忽略
            """
            return any(i in concept.describe for i in ignore_words)  # 检查描述中是否包含忽略词

        # 选择关注的概念
        if agents:  # 如果有其他智能体
            priority = [i for i in self.concepts if _focus(i)]  # 选与其他智能体相关的概念
            if priority:  # 如果有相关概念
                focus = random.choice(priority)  # 随机选择一个关注点

        # 如果没有找到优先关注的概念，从其他概念中选择
        if not focus:  # 如果没有找到优先关注点
            priority = [i for i in self.concepts if not _ignore(i)]  # 筛选不需要忽略的概念
            if priority:  # 如果有可用概念
                focus = random.choice(priority)  # 随机选择一个关注点

        # 兜底：若仍无焦点，尝试选择同场景且在视野内的最近代理，构造一个低显著性概念作为焦点
        if not focus and agents and isinstance(agents, dict) and len(agents) > 1:
            try:
                current_arena = self.get_tile().get_address("arena")
                vision_r = self.percept_config.get("vision_r", 3)
                candidates = []
                for other_name, other_agent in agents.items():
                    if other_name == self.name:
                        continue
                    try:
                        if other_agent.get_tile().get_address("arena") != current_arena:
                            continue
                        dist = math.dist(other_agent.coord, self.coord)
                        if dist <= vision_r:
                            candidates.append((dist, other_agent))
                    except Exception:
                        continue
                if candidates:
                    candidates.sort(key=lambda x: x[0])
                    nearest_other = candidates[0][1]
                    other_event = nearest_other.get_event()
                    if other_event:
                        tmp_id = f"nearby_{int(time.time()*1000)}"
                        focus = Concept.from_event(tmp_id, "event", other_event, poignancy=1)
                        self.logger.info(f"{self.name} 使用邻近兜底策略选择 {nearest_other.name} 作为对话焦点")
            except Exception as e:
                self.logger.warning(f"{self.name} 邻近代理兜底策略失败: {e}")
                
        # 检查是否需要进行反应
        if not focus or focus.event.subject not in agents:  # 如果没有关注点或关注点不是其他智能体
            return False  # 不进行反应
            
        # 获取相关智能体和关联记忆
        other, focus = agents[focus.event.subject], self.associate.get_relation(focus)  # 获取目标智能体和关联记忆

        # 尝试行对话或等待
        if self._chat_with(other, focus):  # 尝试与其他智能体对话
            return True  # 反应成功
        if self._wait_other(other, focus):  # 尝试等待其他智能体
            return True  # 反应成功
        return False  # 没有产生反应

    def _skip_react(self, other):
        """检查是否应该跳过反应
        Args:
            other: 其他智能体对象
        Returns:
            bool: 是否应该跳过反应
        """
        def _skip(event):
            """检查件是否应该跳过
            Args:
                event: 要检查的事件
            Returns:
                bool: 是否应该跳过
            """
            if not event.address or "sleeping" in event.get_describe(False) or "睡觉" in event.get_describe(False):  # 如果没有地址或正在睡觉
                return True  # 跳过反应
            if event.predicate == "待开始":  # 如果事件还未开始
                return True  # 跳过反应
            return False  # 不过应

        # 检查时间状态
        if utils.get_timer().daily_duration(mode="hour") >= 23:  # 如果是深夜
            return True  # 跳过反应
        if _skip(self.get_event()) or _skip(other.get_event()):  # 如果自己或对方的事件需要跳过
            return True  # 跳过反应
        return False  # 不跳过反应

    def _chat_with(self, other, focus):
        """与其他智能体进行对话
        Args:
            other: 目标智能体对象
            focus: 对话的关注点
        Returns:
            bool: 是否成功进行对话
        """
        # 检查是否可以进行对话
        if len(self.schedule.daily_schedule) < 1 or len(other.schedule.daily_schedule) < 1:  # 如果任一方没有日安排
            return False  # 无法进行话
        if self._skip_react(other):  # 如果需要跳过反应
            return False  # 不进行对话
        if other.path:  # 如果目标智能体正在移动
            return False  # 不进行对话
        if self.get_event().fit(predicate="对话") or other.get_event().fit(predicate="对话"):  # 如果任一方正在对话
            return False  # 不进行新的对话

        # 检查最近的对话记录
        chats = self.associate.retrieve_chats(other.name)  # 获取与智能体的对话记录
        if chats:  # 如果对话记录
            delta = utils.get_timer().get_delta(chats[0].create)  # 计算距离上次对话的时间
            self.logger.info(
                "retrieved chat between {} and {}({} min):\n{}".format(
                    self.name, other.name, delta, chats[0]
                )
            )  # 记录对话信息
            if delta < 60:  # 如果距离上次对话不足60分钟
                return False  # 不进行新的对话

        # 决定是否开始对话
        if not self.completion("decide_chat", self, other, focus, chats):  # 如果决定不进行对话
            return False  # 不开始对话

        # 开始对话流程
        self.logger.info("{} decides chat with {}".format(self.name, other.name))  # 记录对话开始
        start, chats = utils.get_timer().get_date(), []  # 初始化开始时间和对话记录
        relations = [  # 获取双方关系描述
            self.completion("summarize_relation", self, other.name),  # 获取自己对对方的关系描述
            other.completion("summarize_relation", other, self.name),  # 获取对方对自己的关系描述
        ]

        # 进行对话交互
        for i in range(self.chat_iter):  # 设定的对话轮次内
            # 生成自己的对话容
            text = self.completion(
                "generate_chat", self, other, relations[0], chats
            )  # 生成对话内容

            if i > 0:  # 从第二轮对话开始
                # 检查是否出现重复对话
                end = self.completion(
                    "generate_chat_check_repeat", self, chats, text
                )  # 检查对话重复
                if end:  # 如果检测到重复
                    break  # 结束对话

                # 检查对话是否应该结束
                chats.append((self.name, text))  # 添加自己的对话
                end = self.completion(
                    "decide_chat_terminate", self, other, chats
                )  # 检查是否应该束对话
                if end:  # 如果应该结束
                    break  # 结束对话
            else:  # 第一轮对话
                chats.append((self.name, text))  # 直接添加对话内容

            # 生成对方的对话内容
            text = other.completion(
                "generate_chat", other, self, relations[1], chats
            )  # 生成对方的对话内容
            if i > 0:  # 从第二轮对话开始
                # 检查对方的对话是否重复
                end = self.completion(
                    "generate_chat_check_repeat", other, chats, text
                )  # 检查对话重复
                if end:  # 如果检测到重复
                    break  # 结束对话

            chats.append((other.name, text))  # 添加对方的对话内容

            # 检查对方是否想结束对话
            end = other.completion(
                "decide_chat_terminate", other, self, chats
            )  # 检查对方是否想结束对话
            if end:  # 如果对方想结束
                break  # 结束对话

        # 记录对话历史
        key = utils.get_timer().get_date("%Y%m%d-%H:%M")  # 生成时间戳键
        if key not in self.conversation.keys():  # 如果时间戳不存在
            self.conversation[key] = []  # 创建新对话列表
            
        # 清理名称中可能存在的空格问题
        clean_self_name = self.name.replace(" ", "")
        clean_other_name = other.name.replace(" ", "")
        
        # 使用清理后的名称保存对话记录
        self.conversation[key].append({f"{clean_self_name} -> {clean_other_name} @ {'，'.join(self.get_event().address)}": chats})  # 添加对话记录

        # 记录对话日志
        self.logger.info(
            "{} and {} has chats\n  {}".format(
                clean_self_name,
                clean_other_name,
                "\n  ".join(["{}: {}".format(n.replace(" ", ""), c) for n, c in chats]),
            ) )   # 记录详细对话内容

        # 总结对话并更新日程
        chat_summary = self.completion("summarize_chats", chats)  # 生成对话总结
        duration = int(sum([len(c[1]) for c in chats]) / 240)  # 计算对话持续时间
        self.schedule_chat(
            chats, chat_summary, start, duration, other
        )  # 更新自己的日程
        other.schedule_chat(chats, chat_summary, start, duration, self)  # 更新对方的日程
        return True  # 对话成功完成

    def _wait_other(self, other, focus):
        """等待其他智能体
        Args:
            other: 目标智能体对象
            focus: 等待的关注点
        Returns:
            bool: 是否成功开始等待
        """
        if self._skip_react(other):  # 如果需要跳过反应
            return False  # 不进行等待
        if not self.path:  # 如果没有移动路径
            return False  # 不进行等待
        if self.get_event().address != other.get_tile().get_address():  # 如果不在同一地点
            return False  # 不进行等待
        if not self.completion("decide_wait", self, other, focus):  # 如果决定不等待
            return False  # 不开始等待
        
        self.logger.info("{} decides wait to {}".format(self.name, other.name))  # 记录等待决定
        start = utils.get_timer().get_date()  # 获取当前时间
        t = other.action.end - start  # 计算等待时间
        duration = int(t.total_seconds() / 60)  # 转换为分钟
        
        # 创建等待事件
        event = memory.Event(
            self.name,
            "waiting to start",
            self.get_event().get_describe(False),
            address=self.get_event().address,
            emoji=f"⌛",
        )  # 创建等待事件
        self.revise_schedule(event, start, duration)  # 修改日程安排

    def schedule_chat(self, chats, chats_summary, start, duration, other, address=None):
        """安排对话日程
        Args:
            chats: 对话记录列表
            chats_summary: 对话总结
            start: 开始时间
            duration: 持续时间
            other: 对话对象
            address: 地点地址，默认为None
        """
        self.chats.extend(chats)  # 添加对话记录
        event = memory.Event(
            self.name,
            "对话",
            other.name,
            describe=chats_summary,
            address=address or self.get_tile().get_address(),
            emoji=f"",
        )  # 创建对话事件
        self.revise_schedule(event, start, duration)  # 更新日程安排
        chat_summary = self.completion("summarize_chats", chats)  # 生成对话总结

    def get_tile(self):
        """获取当前所在地
        Returns:
            Tile: 当前位置的地块对象
        """
        return self.maze.tile_at(self.coord)  # 返回当前坐标对应的地块对象

    def get_event(self, as_act=True):
        """获取当前事件
        Args:
            as_act: 是否获取动作事件，默认为True
        Returns:
            Event: 事件对象
        """
        return self.action.event if as_act else self.action.obj_event  # 根据参数返回动作事件或对象事件

    def is_awake(self):
        """检查智能体是否醒着
        Returns:
            bool: 是否处于清醒状态
        """
        if not self.action:  # 如果没有当前动作
            return True  # 视为清醒状态
        if self.get_event().fit(self.name, "is", "sleeping"):  # 如正在睡觉(英文)
            return False  # 处于睡眠状态
        if self.get_event().fit(self.name, "正在", "睡觉"):  # 如果正在睡觉(中文)
            return False  # 处于睡眠状态
        return True  # 处于清醒状态

    def llm_available(self):
        """检查语言模型是否可用
        Returns:
            bool: 语言模型是否可用
        """
        if not self._llm:  # 如果语言模型未初始化
            return False  # 不可用
        return self._llm.is_available()  # 返回语言模型的可用状态

    def to_dict(self, with_action=True):
        """将智能体信息转换为字典格式
        Args:
            with_action: 是否包含动作信息，默认为True
        Returns:
            dict: 包含智能体信息的字典
        """
        info = {
            "status": self.status,  # 状态息
            "schedule": self.schedule.to_dict(),  # 日程信息
            "associate": self.associate.to_dict(),  # 关联记忆信息
            "chats": self.chats,  # 对话记录
            "currently": self.scratch.currently,  # 当前状态描述
        }
        if with_action:  # 如果需要包含动作信息
            info.update({"action": self.action.to_dict()})  # 添加动作信息
        return info  # 返回信息字典

    def _add_concept(
        self,
        e_type,
        event,
        create=None,
        expire=None,
        filling=None,
    ):
        """添加新的概念到关联记忆中
        Args:
            e_type: 概念类型 ('event', 'chat', 'thought')
            event: 事件对象
            create: 创建时间，默认为None
            expire: 过期时间，认为None
            filling: 填充信息，默认None
        Returns:
            Concept: 创建的概念对象
        """
        if event.fit(None, "is", "idle"):
            poignancy = 1
        elif event.fit(None, "此时", "空闲"):
            poignancy = 1
        elif e_type == "chat":
            poignancy = self.completion("poignancy_chat", event)
        else:
            poignancy = self.completion("poignancy_event", event)
        self.logger.debug("{} add associate {}".format(self.name, event))
        concept = self.associate.add_node(
            e_type,
            event,
            poignancy,
            create=create,
            expire=expire,
            filling=filling,
        )
        if concept is None:
            # 退化策略: 索引写入失败时,返回一个不入索引的临时概念,避免上层逻辑崩溃
            try:
                from modules.memory.associate import Concept as _Concept
                tmp_id = f"tmp_{int(time.time()*1000)}"
                return _Concept.from_event(tmp_id, e_type, event, poignancy)
            except Exception:
                return None

    def add_chat(self, chats, chats_summary, start, duration, other, address=None):
        """添加对话记录
        Args:
            chats: 对话记录列表
            chats_summary: 对话总结
            start: 开始时间
            duration: 持续时间
            other: 对话对象
            address: 地点地址，默认为None
        """
        self.chats.extend(chats)  # 添加对话记录
        # 创建对话事件
        event = memory.Event(
            self.name,
            "对话",
            other.name,
            describe=chats_summary,
            address=address or self.get_tile().get_address(),
            emoji=f" ",
        )
        self.revise_schedule(event, start, duration)  # 更新日程安排
        chat_summary = self.completion("summarize_chats", chats)  # 生成对话总结
