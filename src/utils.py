import tkinter as tk
from tkinter import ttk, scrolledtext
import json
import os
import logging
import logging.handlers
import copy
import sys
import cv2
import time
import queue
import numpy as np
import glob
import gettext
from datetime import datetime

# 基础模块包括:
# LOGGER. 将输入写入到logger.txt文件中.
# CONFIG. 保存和写入设置.
# CHANGES LOG. 弹窗展示更新文档.
# TOOLTIP. 鼠标悬停时的提示.

############################################
THREE_DAYS_AGO = time.time() - 3 * 24 * 60 * 60
LOGS_FOLDER_NAME = "logs"
os.makedirs(LOGS_FOLDER_NAME, exist_ok=True)
for filename in os.listdir(LOGS_FOLDER_NAME):
    file_path = os.path.join(LOGS_FOLDER_NAME, filename)
    
    # 获取最后修改时间
    creation_time = os.path.getmtime(file_path)
    
    # 如果文件创建时间早于3天前，则删除
    if creation_time < THREE_DAYS_AGO:
        os.remove(file_path)
############################################
LOG_FILE_PREFIX = LOGS_FOLDER_NAME + "/log"
logger = logging.getLogger('WvDASLogger')
#===========================================
def SetupFileHandle():
    """设置文件处理器"""
    os.makedirs(LOGS_FOLDER_NAME, exist_ok=True)
    current_time = time.strftime("%y%m%d-%H%M%S")
    log_file_path = f"{LOG_FILE_PREFIX}_{current_time}.txt"
    
    file_handler = logging.FileHandler(log_file_path, mode='a', encoding='utf-8')
    file_handler.setLevel(logging.DEBUG)
    file_formatter = logging.Formatter(
        '%(asctime)s - %(levelname)s - [%(module)s:%(funcName)s:%(lineno)d] - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    file_handler.setFormatter(file_formatter)
    return file_handler

log_queue = queue.Queue(-1)

class LogListenerManager:
    def __init__(self):
        self.listener = None
        self.started = False

    def start(self):
        if self.started:
            return
        self.listener = logging.handlers.QueueListener(log_queue, SetupFileHandle())
        self.listener.start()
        self.started = True

    def stop(self):
        if not self.started:
            return
        self.listener.stop()
        for handler in self.listener.handlers:
            handler.close()
        self.listener = None
        self.started = False

# 
LOG_LISTENER_MGR = LogListenerManager()
#===========================================
class LoggerStream:
    """自定义流，将输出重定向到logger"""
    def __init__(self, logger, log_level):
        self.logger = logger
        self.log_level = log_level
        self.buffer = ''  # 用于累积不完整的行
    
    def write(self, message):
        # 累积消息直到遇到换行符
        self.buffer += message
        while '\n' in self.buffer:
            line, self.buffer = self.buffer.split('\n', 1)
            if line:  # 跳过空行
                self.logger.log(self.log_level, line)
    
    def flush(self):
        # 处理缓冲区中剩余的内容
        if self.buffer:
            self.logger.log(self.log_level, self.buffer)
            self.buffer = ''

def RegisterQueueHandler():
    """配置QueueHandler，将日志发送到队列"""
    # 保持原有的stdout/stderr重定向
    sys.stdout = LoggerStream(logger, logging.DEBUG)
    sys.stderr = LoggerStream(logger, logging.ERROR)
    
    for handler in logger.handlers:
        if isinstance(handler, logging.handlers.QueueHandler) and handler.queue is log_queue:
            return

    # 创建QueueHandler并连接到全局队列
    queue_handler = logging.handlers.QueueHandler(log_queue)
    queue_handler.setLevel(logging.DEBUG)
    
    logger.setLevel(logging.DEBUG)
    logger.addHandler(queue_handler)
    logger.propagate = False

def RegisterConsoleHandler():
    sys.stdout = sys.__stdout__
    sys.stderr = sys.__stderr__

    logger.setLevel(logging.DEBUG)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

class ScrolledTextHandler(logging.Handler):
    def __init__(self, text_widget, clear_on_emit=False):
        super().__init__()
        self.text_widget = text_widget
        self.text_widget.config(state=tk.DISABLED)
        self.msg_queue = queue.Queue()
        self.clear_on_emit = clear_on_emit
        self._update_loop()

    def emit(self, record):
        msg = self.format(record)
        action = 'clear_and_insert' if self.clear_on_emit else 'insert'
        self.msg_queue.put((action, msg))

    def _update_loop(self):
        try:
            messages = []
            while True:
                try:
                    messages.append(self.msg_queue.get_nowait())
                except queue.Empty:
                    break
            
            if messages:
                self.text_widget.config(state=tk.NORMAL)
                for action, msg in messages:
                    if action == 'clear_and_insert':
                        self.text_widget.delete(1.0, tk.END)
                    self.text_widget.insert(tk.END, msg + '\n')
                self.text_widget.see(tk.END)
                self.text_widget.config(state=tk.DISABLED)
        except Exception:
            pass
        finally:
            try:
                self.text_widget.after(50, self._update_loop)
            except Exception:
                pass
class SummaryLogFilter(logging.Filter):
    def filter(self, record):
        if hasattr(record, 'summary') and record.summary:
            return True
            
        return False
############################################
def ResourcePath(relative_path):
    """ 获取资源的绝对路径，适用于开发环境和 PyInstaller 打包环境 """
    try:
        # PyInstaller 创建一个临时文件夹并将路径存储在 _MEIPASS 中
        base_path = sys._MEIPASS
    except Exception:
        # 未打包状态 (开发环境)
        # 假设 script.py 位于 C:\Users\Arnold\Desktop\andsimscripts\src\
        # 并且 resources 位于 C:\Users\Arnold\Desktop\andsimscripts\resources\
        # 我们需要从 script.py 的目录 (src) 回到上一级 (andsimscripts)
        base_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        # 如果你的 script.py 和 resources 文件夹都在项目根目录，则 base_path = os.path.abspath(".")

    return os.path.join(base_path, relative_path)
def LoadJson(path):
    try:
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as f:
                loaded_config = json.load(f)
                return loaded_config
        else:
            return {}   
    except json.JSONDecodeError:
        logger.error(f"错误: 无法解析 {path}。将使用默认配置。")
        return {}
    except Exception as e:
        logger.error(f"错误: 加载配置时发生错误: {e}。将使用默认配置。")
        return {}
def LoadImage(path):
    try:
        # 尝试读取图片
        img = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)
        if img is None:
        # 手动抛出异常
            raise ValueError(f"[OpenCV 错误] 图片加载失败，路径可能不存在或图片损坏: {path}")
    except Exception as e:
        logger.error(f"加载图片失败: {str(e)}")
        return None
    return img


def SaveImage(scn, name=None):
    """Save a diagnostic screenshot below the configured runtime log directory."""
    if scn is None:
        return None

    os.makedirs(LOGS_FOLDER_NAME, exist_ok=True)
    if name is None:
        name = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    name = os.path.basename(str(name))
    if not name.lower().endswith(".png"):
        name += ".png"

    file_path = os.path.join(LOGS_FOLDER_NAME, name)
    if not cv2.imwrite(file_path, scn):
        raise IOError(f"failed to save diagnostic screenshot: {file_path}")
    return file_path

############################################
def _config_file_path():
    """Return the persistent config path used by the application.

    A PyInstaller ``dist`` directory is replaceable build output. Keeping the
    only copy of the user's settings beside ``wvd.exe`` therefore loses the
    Telegram Chat ID whenever a clean build replaces that directory. Frozen
    builds use a per-user path instead, while still allowing an explicit path
    for portable/test deployments. The old executable-side file is read as a
    migration fallback by :func:`LoadRawConfigFromFile`.
    """
    if getattr(sys, "frozen", False):
        configured_path = os.environ.get("WVDAS_CONFIG_PATH")
        if configured_path:
            return os.path.abspath(os.path.expandvars(os.path.expanduser(configured_path)))

        user_data_directory = (
            os.environ.get("LOCALAPPDATA")
            or os.environ.get("APPDATA")
        )
        if user_data_directory:
            return os.path.join(user_data_directory, "WvDAS", "config.json")

        # Keep a useful fallback for portable environments without the normal
        # Windows per-user environment variables.
        return os.path.join(os.path.dirname(os.path.abspath(sys.executable)), "config.json")
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "config.json"))


def _config_has_runtime_settings(config_data):
    """Return whether a config contains user-selected runtime settings."""
    general = config_data.get("GENERAL", {}) if isinstance(config_data, dict) else {}
    if not isinstance(general, dict):
        return False

    emu_path = general.get("EMU_PATH")
    if isinstance(emu_path, str) and emu_path.strip():
        return True

    emu_index = general.get("EMU_INDEX")
    if emu_index not in (None, "", 0, "0"):
        return True

    adb_address = general.get("ADB_ADRESS")
    if adb_address not in (None, "", "127.0.0.1:16384"):
        return True

    farm_target = general.get("FARM_TARGET")
    if farm_target not in (None, "", "None"):
        return True

    # Telegram-only settings are still user data. Treating them as an empty
    # first-run config made the fallback select another config and dropped the
    # saved Chat ID after a rebuild.
    if general.get("TELEGRAM_ENABLED") is True:
        return True
    return any(
        isinstance(general.get(name), str) and general.get(name).strip()
        for name in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_ALLOWED_CHAT_ID")
    )


def _config_has_telegram_keys(config_data):
    """Return whether the config has been initialized with Telegram fields."""
    general = config_data.get("GENERAL", {}) if isinstance(config_data, dict) else {}
    return isinstance(general, dict) and any(
        name in general
        for name in (
            "TELEGRAM_ENABLED",
            "TELEGRAM_BOT_TOKEN",
            "TELEGRAM_ALLOWED_CHAT_ID",
        )
    )


def _config_candidate_score(config_data):
    """Rank fallback configs, preferring the one with Telegram credentials."""
    general = config_data.get("GENERAL", {}) if isinstance(config_data, dict) else {}
    if not isinstance(general, dict):
        return -1

    score = 0
    if _config_has_runtime_settings(config_data):
        score += 1
    if isinstance(general.get("EMU_PATH"), str) and general["EMU_PATH"].strip():
        score += 2
    if general.get("FARM_TARGET") not in (None, "", "None"):
        score += 1
    if isinstance(general.get("TELEGRAM_BOT_TOKEN"), str) and general["TELEGRAM_BOT_TOKEN"].strip():
        score += 4
    if isinstance(general.get("TELEGRAM_ALLOWED_CHAT_ID"), str) and general["TELEGRAM_ALLOWED_CHAT_ID"].strip():
        score += 6
    if general.get("TELEGRAM_ENABLED") is True:
        score += 1
    return score


def _config_fallback_candidates():
    """Yield nearby config files that can seed a frozen executable."""
    if not getattr(sys, "frozen", False):
        return []

    candidates = []
    seen = set()

    def add_candidate(directory):
        candidate = os.path.abspath(os.path.join(directory, "config.json"))
        if candidate not in seen:
            seen.add(candidate)
            candidates.append(candidate)

    add_candidate(os.getcwd())
    directory = os.path.dirname(os.path.abspath(sys.executable))
    # A repository build is commonly laid out as <repo>\\dist\\wvd\\wvd.exe.
    # Walking a few parents also supports an extracted distribution with a
    # config file placed beside its top-level folder.
    for _ in range(4):
        add_candidate(directory)
        parent = os.path.dirname(directory)
        if os.path.basename(parent).lower() == "dist":
            # Local rebuilds are often staged as <repo>\dist\<new-build>\wvd.
            # Also inspect the conventional <repo>\dist\wvd installation so
            # the first staged run can migrate its previous Chat ID.
            add_candidate(os.path.join(parent, "wvd"))
        if parent == directory:
            break
        directory = parent

    return candidates


def _find_config_fallback():
    """Find the best nearby config to migrate into a frozen build."""
    best_path = None
    best_score = -1
    for candidate in _config_fallback_candidates():
        if os.path.abspath(candidate) == os.path.abspath(CONFIG_FILE):
            continue
        data = LoadJson(candidate)
        score = _config_candidate_score(data)
        if score > best_score:
            best_path = candidate
            best_score = score
    return best_path if best_score >= 1 else None


def _merge_telegram_settings(config_data, fallback_data):
    """Fill missing Telegram values without overwriting newer user changes."""
    if not isinstance(config_data, dict):
        return copy.deepcopy(fallback_data) if isinstance(fallback_data, dict) else {}
    if not isinstance(fallback_data, dict):
        return copy.deepcopy(config_data)

    merged = copy.deepcopy(config_data)
    general = merged.setdefault("GENERAL", {})
    fallback_general = fallback_data.get("GENERAL", {})
    if not isinstance(general, dict) or not isinstance(fallback_general, dict):
        return merged

    telegram_names = (
        "TELEGRAM_ENABLED",
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_ALLOWED_CHAT_ID",
    )
    current_has_telegram = bool(general.get("TELEGRAM_ENABLED")) or any(
        isinstance(general.get(name), str) and general.get(name).strip()
        for name in telegram_names[1:]
    )

    # A newly generated config contains False/empty defaults for all three
    # fields. In that case migrate the complete legacy Telegram section.
    if not current_has_telegram:
        for name in telegram_names:
            if name in fallback_general:
                general[name] = copy.deepcopy(fallback_general[name])
        return merged

    # If the user has already changed any Telegram value in the new location,
    # retain it and only fill fields that are genuinely absent/empty.
    for name in telegram_names[1:]:
        current_value = general.get(name)
        fallback_value = fallback_general.get(name)
        if (
            isinstance(fallback_value, str)
            and fallback_value.strip()
            and (name not in general or not isinstance(current_value, str) or not current_value.strip())
        ):
            general[name] = fallback_value
    if "TELEGRAM_ENABLED" not in general and "TELEGRAM_ENABLED" in fallback_general:
        general["TELEGRAM_ENABLED"] = copy.deepcopy(fallback_general["TELEGRAM_ENABLED"])
    return merged


_RECOVERY_SETTING_MIGRATIONS = (
    ("SKIP_COMBAT_RECOVER", "DO_COMBAT_RECOVER"),
    ("SKIP_CHEST_RECOVER", "DO_CHEST_RECOVER"),
)


def _migrate_recovery_settings(config_data):
    """Convert legacy skip flags without changing effective behavior."""

    if not isinstance(config_data, dict):
        return config_data, False

    migrated = copy.deepcopy(config_data)
    changed = False
    for section in migrated.values():
        if not isinstance(section, dict):
            continue
        for legacy_name, current_name in _RECOVERY_SETTING_MIGRATIONS:
            if current_name not in section and legacy_name in section:
                section[current_name] = not bool(section[legacy_name])
                changed = True
            if legacy_name in section:
                del section[legacy_name]
                changed = True
    return migrated, changed


def _write_config_file(config_path, config_data):
    """Write a config atomically, creating the per-user directory if needed."""
    absolute_path = os.path.abspath(config_path)
    directory = os.path.dirname(absolute_path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    temporary_path = f"{absolute_path}.tmp-{os.getpid()}"
    try:
        with open(temporary_path, 'w', encoding='utf-8') as f:
            json.dump(config_data, f, ensure_ascii=False, indent=4)
        os.replace(temporary_path, absolute_path)
    finally:
        if os.path.exists(temporary_path):
            try:
                os.remove(temporary_path)
            except OSError:
                pass


CONFIG_FILE = _config_file_path()
def SaveConfigToFile(config_data, config_file_path=CONFIG_FILE):
    try:
        _write_config_file(config_file_path or CONFIG_FILE, config_data)
        logger.info(_("配置已保存。"))
        return True
    except Exception as e:
        logger.error(f"保存配置时发生错误: {e}")
        return False
def LoadRawConfigFromFile(config_file_path = CONFIG_FILE, migrate_recovery = True):
    if config_file_path == None:
        config_file_path = CONFIG_FILE
    config_data = LoadJson(config_file_path)
    should_persist = False

    # A clean build can leave either a first-run config or an older config that
    # predates the Telegram fields beside the executable. Recover and migrate
    # the best legacy file into the stable per-user location in both cases.
    if (
        getattr(sys, "frozen", False)
        and os.path.abspath(config_file_path) == os.path.abspath(CONFIG_FILE)
        and (
            not _config_has_runtime_settings(config_data)
            or not _config_has_telegram_keys(config_data)
        )
    ):
        fallback_path = _find_config_fallback()
        if fallback_path:
            fallback_data = LoadJson(fallback_path)
            if fallback_data:
                if _config_has_runtime_settings(config_data):
                    migrated_data = _merge_telegram_settings(config_data, fallback_data)
                else:
                    migrated_data = fallback_data
                if migrated_data != config_data:
                    config_data = migrated_data
                    should_persist = True

    if migrate_recovery:
        config_data, recovery_settings_changed = _migrate_recovery_settings(config_data)
        should_persist = should_persist or recovery_settings_changed
    if should_persist:
        try:
            _write_config_file(config_file_path, config_data)
        except Exception as exc:
            logger.warning("Config migration failed: %s", exc)

    return config_data
def SetOneVarInGeneralConfig(var, value):
    data = LoadRawConfigFromFile()
    data['GENERAL'][var] = value
    SaveConfigToFile(data)
def GetOneVarInGeneralConfig(var, default_value):
    # Locale setup runs while this module is imported. Defer recovery-key
    # persistence until the application explicitly loads its farm settings so
    # imports and test discovery never rewrite the user's config by themselves.
    data = LoadRawConfigFromFile(migrate_recovery=False)
    if 'GENERAL' in data:
        if var in data['GENERAL']:
            return data['GENERAL'][var]

    return default_value
############################################
localedir = ResourcePath("locale")
LANGUAGE = GetOneVarInGeneralConfig('LANGUAGE', "ko_KR")
trans = gettext.translation('messages', localedir, languages=[LANGUAGE], fallback=True)
trans.install()
###########################################
CHANGES_LOG = "CHANGES_LOG.md"


def LocalizeChangesLog(markdown_content, translator=None):
    """Translate changelog lines while preserving the Markdown layout."""

    translate = translator or _
    localized_lines = []
    for line in markdown_content.splitlines(keepends=True):
        body = line.rstrip("\r\n")
        ending = line[len(body):]
        if body:
            localized_lines.append(f"{translate(body)}{ending}")
        else:
            localized_lines.append(line)
    return "".join(localized_lines)


def ShowChangesLogWindow():
    log_window = tk.Toplevel()
    log_window.title(_("更新日志"))
    log_window.geometry("700x500")

    log_window.lift()  # 提升到最上层
    log_window.attributes('-topmost', True)  # 强制置顶
    log_window.after(100, lambda: log_window.attributes('-topmost', False))
    
    # 创建滚动文本框
    text_area = scrolledtext.ScrolledText(
        log_window, 
        wrap=tk.WORD,
        font=("Segoe UI", 10),
        padx=10,
        pady=10
    )
    text_area.pack(fill=tk.BOTH, expand=True)
    
    # 禁用文本编辑功能
    text_area.configure(state='disabled')
    
    # 尝试读取并显示Markdown文件
    try:
        # 替换为你的Markdown文件路径
        with open(CHANGES_LOG, "r", encoding="utf-8") as file:
            markdown_content = LocalizeChangesLog(file.read())
        
        # 临时启用文本框以插入内容
        text_area.configure(state='normal')
        text_area.delete(1.0, tk.END)
        text_area.insert(tk.INSERT, markdown_content)
        text_area.configure(state='disabled')
    
    except FileNotFoundError:
        text_area.configure(state='normal')
        text_area.insert(tk.INSERT, f"错误：未找到{CHANGES_LOG}文件")
        text_area.configure(state='disabled')
    
    except Exception as e:
        text_area.configure(state='normal')
        text_area.insert(tk.INSERT, f"读取文件时出错: {str(e)}")
        text_area.configure(state='disabled')
###########################################
QUEST_FILE_BASE = 'resources/quest/quest.json'
QUEST_FILE_MOD = 'mod/quest.json'
def _build_quest_data():
    """加载基础任务文件并合并 mod/quest.json，返回合并后的任务字典"""
    try:
        base_data = LoadJson(ResourcePath(QUEST_FILE_BASE))
    except (FileNotFoundError, json.JSONDecodeError) as e:
        logger.error(f"无法读取通用任务列表: {e}")
        raise

    # 深拷贝一份作为结果，避免修改原始数据影响后续
    merged = copy.deepcopy(base_data)

    # 如果 mod 文件存在，进行校验与合并
    if os.path.exists(QUEST_FILE_MOD):
        try:
            mod_data = LoadJson(QUEST_FILE_MOD)
        except (FileNotFoundError, json.JSONDecodeError) as e:
            logger.warning(f"无法读取自定义任务列表: {e}, 跳过合并.")
            mod_data = {}

        for mod_key, mod_info in mod_data.items():
            # === 校验1: _TYPE 必须存在且为 dungeon 或 quest ===
            if "_TYPE" not in mod_info or mod_info["_TYPE"] not in ("dungeon", "quest"):
                logger.error(f"自定义任务 '{mod_key}' 具有不合法的_TYPE值, 跳过.")
                continue

            # === 校验2: 必须有 questName 或 questName_en_US ===
            has_local_name = "questName" in mod_info
            has_en_name = "questName_en_US" in mod_info
            if not has_local_name and not has_en_name:
                logger.error(f"自定义任务 '{mod_key}' 缺少任务名或者英文任务名, 跳过.")
                continue

            # 补齐本地化名称（只提供一种时，另一种保持一致）
            if has_local_name and not has_en_name:
                mod_info["questName_en_US"] = mod_info["questName"]
            elif has_en_name and not has_local_name:
                mod_info["questName"] = mod_info["questName_en_US"]

            # 强制锁定分类
            mod_info["questCategory"] = "自定义"
            mod_info["questCategory_en_US"] = "Custom Requests"

            # 处理索引冲突
            final_key = mod_key
            while final_key in merged:
                final_key += "_mod"
                mod_info["questName"] += "_自定义"
                mod_info["questName_en_US"] += "_mod"
            merged[final_key] = mod_info
            if final_key != mod_key:
                logger.info(f"自定义任务的内部代号 '{mod_key}' 和现有任务冲突, 修改为 '{final_key}'.")

    return merged
QUEST_DATA = _build_quest_data()

def BuildQuestReflection():
    try:
        data = QUEST_DATA
        
        quest_reflect_map = {}
        seen_names = set()

        # questCategory is the stable category identity. A localized category
        # field is only its display label; treating it as a separate key splits
        # one category when only some quests have been localized.
        localized_category_key = f"questCategory_{LANGUAGE}"
        category_labels = {}
        for quest_info in data.values():
            raw_category = quest_info["questCategory"]
            localized_category = quest_info.get(localized_category_key)
            if raw_category not in category_labels:
                category_labels[raw_category] = localized_category or None
            elif category_labels[raw_category] is None and localized_category:
                category_labels[raw_category] = localized_category

        for raw_category, category_label in category_labels.items():
            if not category_label:
                category_labels[raw_category] = raw_category
        
        # 遍历所有任务代号
        for quest_code, quest_info in data.items():
            # 获取本地化任务名称
            quest_name = quest_info.get(f"questName_{LANGUAGE}", quest_info["questName"])

            # 检查名称是否重复
            if quest_name in seen_names:
                raise ValueError(f"Duplicate questName found: '{quest_name}'")
            seen_names.add(quest_name)
            
            # 添加到映射表和已见集合
            category = category_labels[quest_info["questCategory"]]
            quest_reflect_map.setdefault(category, {})[quest_name] = quest_code
            
        
        return quest_reflect_map
    
    except KeyError as e:
        raise KeyError(f"不存在'questName'属性: {e}.")
    except json.JSONDecodeError as e:
        logger.info(f"Error at line {e.lineno}, column {e.colno}: {e.msg}")
        logger.info(f"Problematic text: {e.doc[e.pos-30:e.pos+30]}")  # 显示错误上下文
        exit()
    except FileNotFoundError as e:
        raise FileNotFoundError(f"{e}")
###########################################
IMAGE_FOLDER = fr'resources/images/'
_TEMPLATE_CACHE = {}
def LoadTemplateImage(shortPathOfTarget):
    # 매 호출마다 디스크에서 PNG 를 다시 읽던 것을 캐싱. 호출부는 모두 matchTemplate
    # 입력(읽기 전용)으로만 사용하므로 안전하며, CheckIf 가 도는 모든 루프가 빨라진다.
    # (v2.4.0 병합: 캐시 미스 경로에 업스트림의 mod 디렉터리 폴백을 유지한다.
    #  단 LoadImage 는 예외를 던지지 않고 None 을 반환하므로 — 업스트림의 try/except
    #  폴백은 도달 불가한 죽은 코드였다 — None 판정으로 폴백을 실제 동작하게 한다.)
    img = _TEMPLATE_CACHE.get(shortPathOfTarget)
    if img is not None:
        return img
    logger.debug(f"加载图片: {shortPathOfTarget}")
    image_filename = f"{shortPathOfTarget}.png"

    # 1. 优先从 ResourcePath 加载
    img = LoadImage(ResourcePath(os.path.join(IMAGE_FOLDER, image_filename)))
    # 2. 资源路径失败，尝试 mod 目录
    if img is None:
        logger.debug(f"资源路径未找到 {image_filename}，尝试 mod 目录")
        mod_path = os.path.join('mod', image_filename)
        if os.path.isfile(mod_path):
            img = LoadImage(mod_path)
    # 3. 两处都未找到
    if img is None:
        raise FileNotFoundError(f"图片 {shortPathOfTarget} 不可用")
    _TEMPLATE_CACHE[shortPathOfTarget] = img
    return img
def reflectImage(folder):
    # 构建dialogueChoices文件夹的模式匹配路径
    pattern = os.path.join(IMAGE_FOLDER, folder, '*.png')
    full_pattern = ResourcePath(pattern)
    
    # 使用glob获取所有匹配的文件
    png_files = glob.glob(full_pattern)
    
    # 提取不带扩展名的文件名
    img = sorted([os.path.splitext(os.path.basename(f))[0] for f in png_files])
    
    return img

DIALOG_OPTION_IMAGE_LIST = reflectImage('dialogueChoices')

CHAR_LIST = sorted(list({img.split('_')[0] for img in reflectImage(os.path.join('spellskill', 'char'))}))

###########################################
class Tooltip:
    def __init__(self, widget, text):
        self.widget = widget
        self.text = text
        self.tooltip_window = None
        self.widget.bind("<Enter>", self.show_tooltip)
        self.widget.bind("<Leave>", self.hide_tooltip)

    def show_tooltip(self, event=None):
        if self.tooltip_window:
            return
            
        # 获取widget的位置和尺寸
        widget_x = self.widget.winfo_rootx()
        widget_y = self.widget.winfo_rooty()
        widget_width = self.widget.winfo_width()
        widget_height = self.widget.winfo_height()
        
        self.tooltip_window = tk.Toplevel(self.widget)
        self.tooltip_window.wm_overrideredirect(True)  # 移除窗口装饰
        self.tooltip_window.attributes("-alpha", 0.95)  # 设置透明度
        
        # 创建标签显示文本
        label = ttk.Label(
            self.tooltip_window, 
            text=self.text, 
            background="#ffffe0", 
            relief="solid", 
            borderwidth=1,
            padding=(8, 4),
            font=("Arial", 10),
            justify="left",
            wraplength=300  # 自动换行宽度
        )
        label.pack()
        
        # 计算最佳显示位置（默认在widget下方）
        x = widget_x + widget_width + 2
        y = widget_y + widget_height//2
        
        # 设置最终位置并显示
        self.tooltip_window.wm_geometry(f"+{int(x)}+{int(y)}")
        self.tooltip_window.deiconify()

    def hide_tooltip(self, event=None):
        if self.tooltip_window:
            self.tooltip_window.destroy()
            self.tooltip_window = None

def _dummy_character_names_for_translation():
    # This function is never called; it exists solely to allow pybabel extract to find and extract the character name strings.
    _("0 面具")
    _("F 伊亚玛斯")
    _("F 凛音")
    _("F 普修利")
    _("F 赛德")
    _("F 吉拉德")
    _("F 基利昂")
    _("F 夏莉莉妮雅")
    _("F 奥尔德里科")
    _("F 尤尔萨")
    _("F 影狼")
    _("F 柚奈壬姬")
    _("F 狮樱")
    _("F 艾妮琪")
    _("F 艾尔文")
    _("F 莉娜莉亚")
    _("F 莉瓦娜")
    _("F 萨维亚")
    _("F 贝卡南")
    _("F 迦鲁巴多斯")
    _("F 银莲")
    _("F 阿尔博里斯")
    _("F 雅蓓妮斯")
    _("G 亚沙")
    _("G 克拉丽莎")
    _("G 克洛艾")
    _("G 切羽")
    _("G 加斯顿")
    _("G 奥利芙")
    _("G 奥菲莉亚")
    _("G 本杰明")
    _("G 海因里科")
    _("G 玛丽安娜")
    _("G 甘道夫")
    _("G 米拉娜")
    _("G 巴克什")
    _("G 艾莉赛")
    _("G 芙尔特")
    _("G 阿米莉娅")
    _("N 无名人类女僧侣")
    _("N 无名兽人女盗贼")
    _("N 无名妖精女法师")
    _("P 亚当")
    _("P 叶卡捷琳娜")
    _("P 哲鲁夫")
    _("P 拉纳维尔")
    _("P 爱丽丝")
    _("P 黛波拉")

def _dummy_strategy_option_names_for_translation():
    # 该函数从不被调用; 它的存在是为了让 pybabel extract 能够提取策略选项的规范字符串.
    # gui.py 的 ORIG_SKILLS / ORIG_TARGETS / ORIG_FREQS / ORIG_GROUPS 仅通过 _(opt) 动态翻译,
    # 提取器无法从列表字面量中发现它们, 缺少此处会导致翻译在重新提取时被标记为过时.
    _("左上技能")
    _("右上技能")
    _("左下技能")
    _("右下技能")
    _("防御")
    _("双击自动")
    _("左上角色")
    _("中上角色")
    _("右上角色")
    _("左下角色")
    _("右下角色")
    _("中下角色")
    _("不可用")
    _("低生命值")
    _("每场战斗仅一次")
    _("每次副本仅一次")
    _("每次启动仅一次")
    _("重复")
    _("全自动战斗")
    _("柚子")
    _("自定义任务点策略")
