"""pywebview 版图形界面.

界面直接使用同目录下的 ``ui.html``. 本模块负责:

* 读取 / 保存配置 (沿用 config.json 的原有结构)
* 启动 / 停止脚本任务
* 把日志与后台事件放进一个线程安全队列, 由前端定时 ``poll`` 取走
* 暴露给 JavaScript 的 API (``WebBridge``)

窗口本身由 pywebview 创建, 因此不再依赖 tkinter 的主循环.
"""

import copy
import ctypes
import os
import queue
import threading
import webbrowser
from datetime import date, datetime

import tkinter as tk
import sys
import gettext
import logging
import uuid
from pathlib import Path

from script import *
from config_model import *
from config_model import (_legacy_strategy_reload_defaults, _is_known_emulator_executable,
    _category_keys_for_display, _targets_for_category_display, _target_matches_display,
    _category_for_target_display, _quest_code_for_target_display)
from mod.telegram_remote_control.config import validate_telegram_settings, TelegramConfigError
from mod.telegram_remote_control.models import TelegramSettings, ConnectionTestRequest, ConnectionTestResult
from mod.telegram_remote_control.constants import GUI_CONNECTION_TEST_TIMEOUT_SECONDS
from mod.telegram_remote_control.recent_logs import redact_log_text
from mod.telegram_remote_control.i18n import get_translator
from utils import *


# ============================================================
# 与原 Tk 版本保持一致的配置读写函数
# ============================================================




# ============================================================
# 工具函数
# ============================================================
def _is_bool_var(var_type):
    return var_type is tk.BooleanVar


def _is_int_var(var_type):
    return var_type is tk.IntVar


def _to_bool(value):
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return bool(value)


def _to_int(value, default=0):
    try:
        if value is None or value == "":
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _display_of(value, canon):
    """把规范中文值转成当前语言下的显示文本.

    无法识别的旧值原样保留, 避免保存时悄悄改掉用户的配置.
    """
    if value in canon:
        return _(value)
    displayed = [_(c) for c in canon]
    if value in displayed:
        return value
    return value if value else _(canon[0])


def _canonical_of(value, canon):
    """把当前语言下的显示文本转回规范中文值."""
    if value in canon:
        return value
    for c in canon:
        if value == _(c):
            return c
    return value if value else canon[0]




# ============================================================
# 前端可调用的 API
# ============================================================

def ResolveUiPath():
    return ResourcePath('ui.html') if hasattr(sys, '_MEIPASS') else str(Path(__file__).with_name('ui.html'))


def CanonicalLabel(value, canon):
    if value in canon or not value:
        return value or ''
    for language in ('ko_KR', 'en_US', 'zh_CN'):
        trans = gettext.translation('messages', localedir, languages=[language], fallback=True)
        for name in canon:
            if trans.gettext(name) == value:
                return name
    return value


def RedactPayload(value, secrets):
    if isinstance(value, str):
        return redact_log_text(value, secrets)
    if isinstance(value, dict):
        return {key: RedactPayload(item, secrets) for key, item in value.items()}
    if isinstance(value, list):
        return [RedactPayload(item, secrets) for item in value]
    return value


class WebLogHandler(logging.Handler):
    def __init__(self, app):
        super().__init__(logging.INFO)
        self.app = app

    def emit(self, record):
        # Do not take the model lock from inside logging's handler lock.
        if self.app._closing:
            return
        try:
            event = {'type': 'log', 'level': record.levelname,
                     'time': datetime.fromtimestamp(record.created).strftime('%H:%M:%S'),
                     'message': record.getMessage()}
            self.app._enqueue_event(RedactPayload(event, self.app._secrets.copy()))
            if getattr(record, 'summary_data', None) is not None:
                self.app._enqueue_event(RedactPayload({'type': 'summary', 'data': record.summary_data,
                    'events': getattr(record, 'summary_events', {})}, self.app._secrets.copy()))
        except Exception:
            self.handleError(record)


UI_TEXT_KEYS = LoadJson(ResourcePath('resources/ui-strings.json')) or []
CHAR_DISPLAY_TO_ID = {_(name): name for name in CHAR_LIST}


WEB_ACTIONS = frozenset(['minimize_window', 'toggle_maximize', 'close_window', 'set_compact', 'save', 'set_language', 'choose_emu_path', 'select_target', 'set_task_specific', 'clear_task_specific', 'set_overall_strategy', 'set_task_point_strategy', 'save_plans', 'claim_gem', 'switch_monthly', 'open_url', 'download_update', 'start_quest', 'stop_quest', 'set_stop_after', 'save_telegram', 'test_connection', 'cancel_update'])


class WebBridge:
    """Read snapshots directly; send every mutation to the controller owner."""
    def __init__(self, app):
        self._app = app

    def bootstrap(self):
        return self._app.bootstrap()

    def poll(self):
        return self._app.poll()

    def _request(self, method, args):
        return self._app.controller.call_on_owner('web_action', {'method': method, 'args': args})

    def minimize_window(self):
        return self._request('minimize_window', [])

    def toggle_maximize(self):
        return self._request('toggle_maximize', [])

    def close_window(self):
        return self._request('close_window', [])

    def set_compact(self, enabled, height=None):
        return self._request('set_compact', [enabled, height])

    def save(self, patch):
        return self._request('save', [patch])

    def set_language(self, kind, value):
        return self._request('set_language', [kind, value])

    def choose_emu_path(self):
        return self._request('choose_emu_path', [])

    def select_target(self, text):
        return self._request('select_target', [text])

    def set_task_specific(self, enabled):
        return self._request('set_task_specific', [enabled])

    def clear_task_specific(self):
        return self._request('clear_task_specific', [])

    def set_overall_strategy(self, value, enable_custom=False):
        return self._request('set_overall_strategy', [value, enable_custom])

    def set_task_point_strategy(self, index, value):
        return self._request('set_task_point_strategy', [index, value])

    def save_plans(self, plans):
        return self._request('save_plans', [plans])

    def claim_gem(self, url):
        return self._request('claim_gem', [url])

    def switch_monthly(self):
        return self._request('switch_monthly', [])

    def open_url(self, url):
        return self._request('open_url', [url])

    def download_update(self):
        return self._request('download_update', [])

    def start_quest(self):
        return self._request('start_quest', [])

    def stop_quest(self):
        return self._request('stop_quest', [])

    def set_stop_after(self, enabled):
        return self._request('set_stop_after', [enabled])

    def save_telegram(self, patch):
        return self._request('save_telegram', [patch])

    def test_connection(self, patch=None):
        return self._request('test_connection', [patch])

    def cancel_update(self):
        return self._request('cancel_update', [])


# ============================================================
# 主窗口控制器
# ============================================================
class ConfigPanelApp:
    SKILL_CANON = ORIG_SKILLS
    TARGET_CANON = ORIG_TARGETS
    SKILL_LEVELS = [1, 2, 3, 4, 5, 6, 7]
    LANGUAGES = [("ko_KR", "한국어"), ("en_US", "English"), ("zh_CN", "简体中文")]
    CUSTOM_STRATEGY = "自定义任务点策略"
    FULL_AUTO = "全自动战斗"
    CONFIG_KEYS = {row[1] for row in CONFIG_VAR_LIST}

    def __init__(self, master_controller, version, msg_queue):
        self.controller = master_controller
        self.config_path = master_controller.config_path
        self.URL = 'https://github.com/momo31/wvd'
        self.version = version
        self.TITLE = 'wvdas v' + version
        self.msg_queue = msg_queue
        self._lock = threading.RLock()
        self._events = queue.Queue(maxsize=2000)
        self._closing = False
        self._window = None
        self._allow_close = False
        self._maximized = False
        self._compact = False
        self._compact_saved_size = None
        self._compact_was_maximized = False
        self._quest_active = False
        self._running_target = None
        self._run_started = None
        self._latest_version = ''
        self._remote_state = 'idle'
        self._active_test_request_id = None
        self._test_message = ''
        self._summary_text = ''
        self._secrets = set()
        self.values = {}
        self._load_values()
        self._apply_language()
        self._install_log_sinks()

    # ------------------------------------------------------------------
    # 运行
    # ------------------------------------------------------------------
    def run(self):
        import webview
        self._window = webview.create_window(
            self.TITLE, html=Path(ResolveUiPath()).read_text(encoding='utf-8'), js_api=WebBridge(self),
            width=1158, height=820, min_size=(700, 160), resizable=True, frameless=True,
            easy_drag=True, hidden=True, background_color='#ffffff',
        )
        self._window.events.closing += self._on_window_closing
        self._window.events.closed += self._on_window_closed
        self._window.events.loaded += self._window.show
        webview.settings['DRAG_REGION_DIRECT_TARGET_ONLY'] = True
        webview.start(debug=False)

    def shutdown(self):
        self.controller.request_shutdown()

    def _on_window_closed(self):
        self._remove_log_sinks()
        self.controller.request_shutdown()

    def close_window(self):
        return self.controller._dispatch('close_window', None)

    def minimize_window(self):
        try:
            self._window.minimize()
        except Exception:
            pass
        return {"ok": True}

    def set_compact(self, enabled, height=None):
        if enabled:
            if not self._compact:
                self._compact_saved_size = (self._window.width, self._window.height)
                self._compact_was_maximized = self._maximized
                self._compact = True
                if self._compact_was_maximized:
                    self._window.restore()
                    self._maximized = False
            self._window.resize(711, max(160, int(height or 180)))
        elif self._compact:
            width, height = self._compact_saved_size
            self._window.resize(width, height)
            if self._compact_was_maximized:
                self._window.maximize()
                self._maximized = True
            self._compact = False
        return {"ok": True}

    def toggle_maximize(self):
        try:
            if self._maximized:
                self._window.restore()
                self._maximized = False
            else:
                self._window.maximize()
                self._maximized = True
        except Exception:
            pass
        return {"ok": True, "maximized": self._maximized}

    # ------------------------------------------------------------------
    # 配置
    # ------------------------------------------------------------------
    def _load_values(self):
        config = LoadConfig(config_path=self.config_path)
        self.values = {name: self._coerce(kind, copy.deepcopy(config.get(name, default)), default)
                       for category, name, kind, default in CONFIG_VAR_LIST}
        self.values['STRATEGY'] = normalize_strategy_options(self.values.get('STRATEGY') or [],
            legacy_dungeon_reload=_legacy_strategy_reload_defaults(self.values.get('RELOAD_STRATEGY_WHEN'))[0],
            legacy_combat_reload=_legacy_strategy_reload_defaults(self.values.get('RELOAD_STRATEGY_WHEN'))[1])
        self.values['TASK_POINT_STRATEGY'] = self._normalize_task_point_strategy(self.values.get('TASK_POINT_STRATEGY'))
        self._secrets.add(self.values.get('TELEGRAM_BOT_TOKEN') or '')

    @staticmethod
    def _coerce(var_type, value, default):
        if _is_bool_var(var_type):
            return _to_bool(value)
        if _is_int_var(var_type):
            return _to_int(value, _to_int(default, 0))
        if var_type is list:
            return copy.deepcopy(value if isinstance(value, list) else default)
        if var_type is dict:
            return copy.deepcopy(value if isinstance(value, dict) else default)
        if value is None:
            return None
        return str(value) if not isinstance(value, str) else value

    @classmethod
    def _normalize_task_point_strategy(cls, value):
        if not isinstance(value, dict):
            return {"overall_strategy": _(cls.FULL_AUTO), "task_point": {}}
        result = dict(value)
        result.setdefault("overall_strategy", _(cls.FULL_AUTO))
        if not isinstance(result.get("task_point"), dict):
            result["task_point"] = {}
        return result

    def _coerce_key(self, key, value):
        for category, attr_name, var_type, default_value in CONFIG_VAR_LIST:
            if attr_name == key:
                return self._coerce(var_type, value, default_value)
        return value

    def save(self, patch):
        if not isinstance(patch, dict):
            return {'ok': False, 'error': 'invalid_patch'}
        with self._lock:
            for key, value in patch.items():
                if key not in self.CONFIG_KEYS or key.startswith('TELEGRAM_') or key in ('FARM_TARGET', 'FARM_TARGET_TEXT', 'TASK_SPECIFIC_CONFIG', 'LANGUAGE_SCRIPT', 'LANGUAGE_GAME'):
                    continue
                if self._quest_active and key != 'DARK_THEME':
                    continue
                self.values[key] = self._coerce_key(key, value)
            self._normalize_values()
            self._save_internal()
        return self._snapshot_with_ok()

    def save_config(self):
        with self._lock:
            self._normalize_values()
            self._save_internal()

    def _normalize_values(self):
        karma = str(self.values.get('KARMA_ADJUST') or '+0').strip()
        self.values['KARMA_ADJUST'] = '+' + karma if karma.isdecimal() else karma
        adb = str(self.values.get('ADB_ADRESS') or '').strip()
        if adb.isdecimal():
            adb = '127.0.0.1:' + adb
        self.values['ADB_ADRESS'] = adb
        for name, minimum in [('EMU_INDEX', 0), ('REST_INTERVEL', 0), ('RE_ASSEMBLE_PARTY_INTERVAL', 1), ('MAX_TRY_LIMIT', 1), ('MAX_CRASH_LIMIT', 1)]:
            self.values[name] = max(minimum, _to_int(self.values.get(name), minimum))
        target = self.values.get('FARM_TARGET')
        if target in QUEST_DATA:
            self.values['FARM_TARGET_TEXT'] = self._target_text(target)

    def _save_internal(self):
        raw = LoadRawConfigFromFile(self.config_path) or {}
        general = dict(raw.get('GENERAL') or {})
        target = self.values.get('FARM_TARGET')
        section = target if self.values.get('TASK_SPECIFIC_CONFIG') and target else 'DEFAULT'
        task = dict(raw.get(section) or {})
        for category, name, kind, default in CONFIG_VAR_LIST:
            value = copy.deepcopy(self.values.get(name, default))
            if name == 'STRATEGY':
                value = self._plans_to_store(value)
            elif name == 'TASK_POINT_STRATEGY':
                value = copy.deepcopy(value)
                if isinstance(value, dict):
                    value['overall_strategy'] = CanonicalLabel(value.get('overall_strategy'), ORIG_GROUPS)
                    value['task_point'] = {str(k): CanonicalLabel(v, ORIG_GROUPS) for k, v in (value.get('task_point') or {}).items()}
            elif name in ('DEFAULT_OVERALL_STRATEGY', 'RELOAD_STRATEGY_WHEN'):
                value = CanonicalLabel(value, ORIG_GROUPS + ['不需要', '每次副本开始(自动)', '每场战斗前'])
            (general if category == 'GENERAL' else task)[name] = value
        raw['GENERAL'] = general
        raw[section] = task
        if not SaveConfigToFile(raw, self.config_path):
            raise OSError('configuration_save_failed')

    def set_language(self, kind, value):
        if self._quest_active:
            return {'ok': False, 'error': _('Stop the task before changing these settings.')}
        key = 'LANGUAGE_SCRIPT' if kind in ('script', 'gui') else 'LANGUAGE_GAME'
        allowed = ('ko_KR', 'en_US', 'zh_CN') if key == 'LANGUAGE_SCRIPT' else ('en_US', 'zh_CN')
        if value not in allowed:
            return {'ok': False, 'error': 'unsupported_language'}
        with self._lock:
            self.values[key] = value
            self._save_internal()
            self._apply_language()
        return self.bootstrap()

    def choose_emu_path(self):
        import webview
        try:
            result = self._window.create_file_dialog(
                webview.FileDialog.OPEN,
                allow_multiple=False,
                file_types=(_("可执行文件 (*.exe)"), _("所有文件 (*.*)")),
            )
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

        if not result:
            return {"ok": True, "cancelled": True}

        path = result[0] if isinstance(result, (list, tuple)) else result
        with self._lock:
            self.values["EMU_PATH"] = str(path)
            self._normalize_values()
            self._save_internal()

        warning = None
        if not _is_known_emulator_executable(path):
            warning = _("设置的模拟器路径可能不正确。\n如果你遇到无法启动模拟器，请尝试重新设置路径。")
        return self._snapshot_with_ok(warning=warning)

    # ------------------------------------------------------------------
    # 快照
    # ------------------------------------------------------------------
    def _snapshot_with_ok(self, **extra):
        snap = self._snapshot()
        snap["ok"] = True
        snap.update(extra)
        return snap

    def _snapshot(self):
        with self._lock:
            values = copy.deepcopy(self.values)
            values.pop('TELEGRAM_BOT_TOKEN', None)
            values.pop('TELEGRAM_ALLOWED_CHAT_ID', None)
            target = values.get('FARM_TARGET')
            target_text = self._target_text(target)
            values['FARM_TARGET_TEXT'] = target_text
            runtime = self.controller._active_runtime
            return {
                'version': self.version, 'url': self.URL, 'values': values,
                'targetText': target_text, 'targetId': target, 'category': self._find_category(target_text),
                'taskSpecific': bool(values.get('TASK_SPECIFIC_CONFIG')),
                'taskPoints': self._task_points_state(values), 'plans': self._plans_for_js(values.get('STRATEGY') or []),
                'options': self._options(), 'daily': self._daily_state(values),
                'update': {'latest': self._latest_version} if self._latest_version else None,
                'running': self._quest_active, 'runningTargetId': self._running_target,
                'runningTargetText': self._target_text(self._running_target) if self._running_target else '',
                'startedAt': self._run_started.timestamp() if self._run_started else None,
                'stopAfter': bool(runtime and runtime.stop_after_run_event.is_set()),
                'remoteState': self._remote_state,
                'telegram': {'enabled': bool(self.values.get('TELEGRAM_ENABLED')),
                             'chatId': self.values.get('TELEGRAM_ALLOWED_CHAT_ID', ''),
                             'tokenConfigured': bool(self.values.get('TELEGRAM_BOT_TOKEN')),
                             'testing': self._active_test_request_id is not None,
                             'testEnabled': not self._quest_active and self._active_test_request_id is None,
                             'message': self._test_message},
            }

    def bootstrap(self):
        with self._lock:
            snap = self._snapshot()
            game = self.values.get('LANGUAGE_GAME', 'en_US')
            resolved = {}
            snap.update({
                'categories': [{'name': category, 'targets': [
                    {'text': text, 'id': target, 'missing': ValidateQuestResources(target, game, resolved)}
                    for text, target in items.items()]} for category, items in DUNGEON_TARGETS.items()],
                'uiLanguages': [{'value': lang, 'label': name} for lang, name in self.LANGUAGES],
                'gameLanguages': [{'value': lang, 'label': name} for lang, name in self.LANGUAGES if lang != 'ko_KR'],
                'autoGroupName': _(self.FULL_AUTO), 'customStrategy': _(self.CUSTOM_STRATEGY),
                'canonSkills': [_(name) for name in self.SKILL_CANON],
                'canonTargets': [_(name) for name in self.TARGET_CANON], 'levels': list(self.SKILL_LEVELS),
                'i18n': {text: _(text) for text in UI_TEXT_KEYS}, 'ok': True,
            })
            return snap

    @staticmethod
    def _find_category(target_text):
        if not target_text:
            return ""
        for category, items in DUNGEON_TARGETS.items():
            if target_text in items:
                return category
        return ""

    def _options(self):
        return {
            "roles": list(CHAR_DISPLAY_TO_ID.keys()),
            "skills": [_(_c) for _c in self.SKILL_CANON],
            "targets": [_(_c) for _c in self.TARGET_CANON],
            "frequencies": [_(name) for name in ORIG_FREQS],
            "unavailableTarget": _('不可用'),
            "levels": list(self.SKILL_LEVELS),
            "lockSkills": [_("防御"), _("双击自动")],
        }

    # ------------------------------------------------------------------
    # 战斗方案
    # ------------------------------------------------------------------
    @classmethod
    def _normalize_group_name(cls, name):
        if name in (cls.FULL_AUTO, _(cls.FULL_AUTO)):
            return _(cls.FULL_AUTO)
        return name or _(cls.FULL_AUTO)

    def _plans_for_js(self, plans):
        result = copy.deepcopy(plans)
        for plan in result:
            plan['group_name'] = _(CanonicalLabel(plan.get('group_name'), ORIG_GROUPS))
            for setting in plan.get('skill_settings', []):
                for field, canon in [('role_var', CHAR_LIST), ('skill_var', ORIG_SKILLS), ('target_var', ORIG_TARGETS), ('freq_var', ORIG_FREQS)]:
                    setting[field] = _(CanonicalLabel(setting.get(field), canon))
        return result

    def _plans_to_store(self, plans):
        result = copy.deepcopy(plans)
        for plan in result:
            plan['group_name'] = CanonicalLabel(plan.get('group_name'), ORIG_GROUPS)
            for setting in plan.get('skill_settings', []):
                for field, canon in [('role_var', CHAR_LIST), ('skill_var', ORIG_SKILLS), ('target_var', ORIG_TARGETS), ('freq_var', ORIG_FREQS)]:
                    setting[field] = CanonicalLabel(setting.get(field), canon)
        return result

    def save_plans(self, plans):
        if not isinstance(plans, list):
            return {"ok": False, "error": "invalid plans"}

        names = [self._normalize_group_name(p.get("group_name")) for p in plans
                 if isinstance(p, dict)]
        duplicates = [name for name in names if names.count(name) > 1]
        if duplicates:
            return {"ok": False,
                    "error": _("名称 '%s' 已存在，请使用其他名称") % duplicates[0]}

        with self._lock:
            self.values["STRATEGY"] = self._plans_to_store(plans)
            self._save_internal()
        return self._snapshot_with_ok()

    # ------------------------------------------------------------------
    # 任务点 / 战斗策略
    # ------------------------------------------------------------------
    def _strategy_names(self, values=None):
        values = values or self.values
        return [self._normalize_group_name(p.get("group_name"))
                for p in values.get("STRATEGY", []) if isinstance(p, dict)]

    def _task_points_state(self, values):
        values = copy.deepcopy(values)
        values["TASK_POINT_STRATEGY"] = translate_task_point_strategy(values.get("TASK_POINT_STRATEGY") or {})
        values["DEFAULT_OVERALL_STRATEGY"] = _(CanonicalLabel(values.get("DEFAULT_OVERALL_STRATEGY"), ORIG_GROUPS))
        target_id = values.get("FARM_TARGET")
        quest = None
        if target_id:
            try:
                quest = LoadQuest(target_id)
            except Exception:
                quest = None

        is_dungeon = bool(quest and getattr(quest, "_TYPE", None) == "dungeon")
        strategies = self._strategy_names(values)
        custom_label = _(self.CUSTOM_STRATEGY)
        full_auto_label = _(self.FULL_AUTO)

        tps = self._normalize_task_point_strategy(values.get("TASK_POINT_STRATEGY"))
        if values.get("TASK_SPECIFIC_CONFIG"):
            overall = tps.get("overall_strategy") or full_auto_label
        else:
            overall = values.get("DEFAULT_OVERALL_STRATEGY") or full_auto_label

        if is_dungeon:
            overall_values = (strategies + [custom_label]) if strategies else [custom_label]
        else:
            overall_values = strategies if strategies else [full_auto_label]
        if overall not in overall_values:
            overall = full_auto_label if full_auto_label in overall_values else overall_values[0]

        points = []
        if is_dungeon and quest and getattr(quest, "_TARGETINFOLIST", None):
            saved_points = tps.get("task_point", {})
            if not isinstance(saved_points, dict):
                saved_points = {}
            for idx, point in enumerate(quest._TARGETINFOLIST):
                label = "%s · %s" % (idx + 1, point.target)
                if point.target == "position":
                    label += " " + str(point.roi)
                saved = saved_points.get(str(idx))
                if saved is None:
                    saved = saved_points.get(idx)
                if saved not in strategies:
                    saved = full_auto_label if full_auto_label in strategies else (
                        strategies[0] if strategies else full_auto_label)
                points.append({"index": idx, "label": label, "strategy": saved})

        return {
            "isDungeon": is_dungeon,
            "points": points,
            "strategies": strategies,
            "overall": overall,
            "overallValues": overall_values,
            "customMode": overall == custom_label,
            "customLabel": custom_label,
            "fullAutoLabel": full_auto_label,
        }

    def _save_task_point_strategy(self):
        tps = self._normalize_task_point_strategy(self.values.get("TASK_POINT_STRATEGY"))
        self.values["TASK_POINT_STRATEGY"] = tps
        if not self.values.get("TASK_SPECIFIC_CONFIG"):
            self.values["DEFAULT_OVERALL_STRATEGY"] = tps.get(
                "overall_strategy", _(self.FULL_AUTO))
        self._save_internal()

    def set_overall_strategy(self, value, enable_custom=False):
        with self._lock:
            if value == _(self.CUSTOM_STRATEGY) and not self.values.get("TASK_SPECIFIC_CONFIG"):
                if not enable_custom:
                    return {"ok": False, "cancelled": True}
                self._save_internal()
                self._switch_task_specific(True, save_at_end=False)

            tps = self._normalize_task_point_strategy(self.values.get("TASK_POINT_STRATEGY"))
            tps["overall_strategy"] = value
            self.values["TASK_POINT_STRATEGY"] = tps
            self._save_task_point_strategy()
        return self._snapshot_with_ok()

    def set_task_point_strategy(self, index, value):
        with self._lock:
            tps = self._normalize_task_point_strategy(self.values.get("TASK_POINT_STRATEGY"))
            tps.setdefault("task_point", {})[str(index)] = value
            self.values["TASK_POINT_STRATEGY"] = tps
            self._save_task_point_strategy()
        return self._snapshot_with_ok()

    # ------------------------------------------------------------------
    # 任务定制配置
    # ------------------------------------------------------------------
    def set_task_specific(self, enabled):
        with self._lock:
            self._save_internal()
            self._switch_task_specific(bool(enabled))
        return self._snapshot_with_ok()

    def _switch_task_specific(self, enabled, save_at_end=True):
        self._save_internal()
        raw = LoadRawConfigFromFile(self.config_path) or {}
        target = self.values.get('FARM_TARGET')
        section = target if enabled and target in raw else 'DEFAULT'
        selected = raw.get(section) or {}
        for category, name, kind, default in CONFIG_VAR_LIST:
            if category != 'GENERAL':
                self.values[name] = self._coerce(kind, copy.deepcopy(selected.get(name, default)), default)
        self.values['TASK_SPECIFIC_CONFIG'] = bool(enabled)
        if save_at_end:
            self._save_internal()

    def clear_task_specific(self):
        with self._lock:
            target = self.values.get('FARM_TARGET')
            self._switch_task_specific(False)
            raw = LoadRawConfigFromFile(self.config_path) or {}
            if target not in ('GENERAL', 'DEFAULT'):
                raw.pop(target, None)
            if not SaveConfigToFile(raw, self.config_path):
                raise OSError('configuration_save_failed')
        return self._snapshot_with_ok()

    def select_target(self, text):
        if self._quest_active:
            return {'ok': False, 'error': 'task_running'}
        target = text if text in QUEST_DATA else next((qid for items in DUNGEON_TARGETS.values() for name, qid in items.items() if name == text), None)
        if target is None:
            return {'ok': False, 'error': 'unknown_target'}
        with self._lock:
            self._save_internal()
            self.values['FARM_TARGET'] = target
            self.values['FARM_TARGET_TEXT'] = self._target_text(target)
            self.values['TASK_SPECIFIC_CONFIG'] = False
            # Load the default section without overwriting a saved target section.
            selected = LoadConfig('default', config_path=self.config_path)
            for category, name, kind, default in CONFIG_VAR_LIST:
                if category != 'GENERAL':
                    self.values[name] = self._coerce(kind, copy.deepcopy(selected.get(name, default)), default)
            self._save_internal()
        snap = self._snapshot_with_ok()
        info = QUEST_DATA[target]
        snap['tip'] = info.get('_TIPS_' + LANGUAGE, info.get('_TIPS', ''))
        return snap

    # ------------------------------------------------------------------
    # 日常 / 周常
    # ------------------------------------------------------------------
    DATE_FORMAT = "%Y-%m-%d"

    def _is_same_week(self, date_str):
        try:
            input_date = datetime.strptime(date_str, self.DATE_FORMAT).date()
        except (ValueError, TypeError):
            return False
        current_date = datetime.now().date()
        iy, iw, _ = input_date.isocalendar()
        cy, cw, _ = current_date.isocalendar()
        return iy == cy and iw == cw

    def _is_same_fortnight(self, date_str):
        first_double_saturday = date(1970, 1, 11)
        try:
            input_date = datetime.strptime(date_str, self.DATE_FORMAT).date()
        except (ValueError, TypeError):
            return False
        current_date = datetime.now().date()
        input_period = (input_date - first_double_saturday).days // 14
        current_period = (current_date - first_double_saturday).days // 14
        return input_period == current_period

    def _daily_state(self, values):
        last_new = values.get("WEBSITE_ORG_TIME") or ""
        new_done = bool(last_new) and self._is_same_week(last_new)
        last_old = values.get("WEBSITE_ORG_TIME_OLD") or ""
        old_done = bool(last_old) and self._is_same_week(last_old)
        all_done = new_done and old_done

        last_am = values.get("AM_REFRESH_TIME") or ""
        am_done = bool(last_am) and self._is_same_fortnight(last_am)
        return {
            # 新/旧官网分开记录, 点击一个只会消除对应的提醒.
            "gemNewDone": new_done,
            "gemOldDone": old_done,
            "gemDone": all_done,
            "gemStatus": _("本周已领取") if all_done else _("本周待领取"),
            "gemTone": "green" if all_done else "amber",
            "gemRecord": last_new or "—",
            "gemRecordNew": last_new or "—",
            "gemRecordOld": last_old or "—",
            "gemDesc": (_("本周宝石已领取 · 点击可再次打开官网") if all_done
                        else _("本周 50 钻待领取 · 点击直接打开官网")),
            "amDone": am_done,
            "amStatus": _("本期已切换") if am_done else _("本期待切换"),
            "amTone": "green" if am_done else "amber",
            "amRecord": last_am or "—",
        }

    def claim_gem(self, url):
        if url:
            webbrowser.open(str(url))
        url_text = str(url or "")
        if "webstore.wizardry.info" in url_text:
            key = "WEBSITE_ORG_TIME"
        elif "store.wizardry.info" in url_text:
            key = "WEBSITE_ORG_TIME_OLD"
        else:
            key = "WEBSITE_ORG_TIME"
        with self._lock:
            self.values[key] = datetime.now().strftime(self.DATE_FORMAT)
            self._save_internal()
        return self._snapshot_with_ok()

    def switch_monthly(self):
        found_text = None
        for category, items in DUNGEON_TARGETS.items():
            for text, target_id in items.items():
                if target_id == "LMG-GT":
                    found_text = text
                    break
            if found_text:
                break
        if not found_text:
            found_text = "[骨头]炉壶灵庙(王都出发)"

        with self._lock:
            self.values["AM_REFRESH_TIME"] = datetime.now().strftime(self.DATE_FORMAT)
            self._save_internal()

        snap = self.select_target(found_text)
        snap["message"] = _("已切换到月常任务：%s") % found_text
        return snap

    # ------------------------------------------------------------------
    # 其他
    # ------------------------------------------------------------------
    def open_url(self, url):
        from urllib.parse import urlsplit
        if urlsplit(str(url)).scheme not in ('https', 'http'):
            return {'ok': False, 'error': 'invalid_url'}
        webbrowser.open(str(url))
        return {'ok': True}

    def download_update(self):
        return self.controller._dispatch('download_update', None)

    # ------------------------------------------------------------------
    # 任务运行
    # ------------------------------------------------------------------
    def start_quest(self):
        if self._quest_active:
            return {'ok': False, 'error': 'already_running'}
        self._normalize_values()
        self._save_internal()
        result = self.controller._dispatch('start_quest', None)
        snap = self._snapshot()
        snap['ok'] = bool(result.get('ok'))
        return snap

    def stop_quest(self):
        return self.controller._dispatch('stop_quest', None)

    def set_stop_after(self, enabled):
        result = self.controller._dispatch('set_stop_after', bool(enabled))
        return dict(result, armed=bool(result['ok'] and enabled))

    def finishingcallback(self):
        # Completion is owned by the controller's generation-checked latch.
        return None

    # ------------------------------------------------------------------
    # 后台事件 / 日志
    # ------------------------------------------------------------------
    def push_event(self, event):
        with self._lock:
            if self._closing:
                return
            event = copy.deepcopy(event)
            kind = event.get('type')
            if kind == 'task_started':
                self._quest_active = True
                self._running_target = event.get('target')
                if self._run_started is None:
                    self._run_started = datetime.now()
                event['startedAt'] = self._run_started.timestamp()
                event['text'] = self._target_text(self._running_target)
            elif kind == 'task_finished':
                self._quest_active = False
                self._run_started = None
                self._running_target = None
            elif kind == 'update_available':
                self._latest_version = str((event.get('data') or {}).get('version') or '')
            event = RedactPayload(event, self._secrets)
            self._enqueue_event(event)

    def _enqueue_event(self, event):
        """Keep recent events without waiting for WebView or taking the model lock."""
        try:
            self._events.put_nowait(event)
        except queue.Full:
            try:
                self._events.get_nowait()
            except queue.Empty:
                pass
            try:
                self._events.put_nowait(event)
            except queue.Full:
                # Another producer won the slot. Model snapshots keep state.
                pass

    def poll(self):
        events = []
        for underscore in range(200):
            try:
                events.append(self._events.get_nowait())
            except queue.Empty:
                break
        return events

    def _install_log_sinks(self):
        self._log_handler = WebLogHandler(self)
        logger.addHandler(self._log_handler)

    def _remove_log_sinks(self):
        handler = getattr(self, '_log_handler', None)
        if handler is not None:
            logger.removeHandler(handler)
            handler.close()
            self._log_handler = None

    # ------------------------------------------------------------------
    # 控制器回调
    # ------------------------------------------------------------------
    def show_update_notice(self, version, download_cb=None):
        if self._closing:
            return
        with self._lock:
            self.values["LATEST_VERSION"] = version
            self._latest_version = str(version)
            self._download_cb = download_cb
            self._save_internal()
        self.push_event({
            "type": "update_available",
            "version": str(version),
            "current": self.version,
        })

    def turn_to_quest(self, target):
        self.push_event({'type': 'task_started', 'target': target})

    def _apply_language(self):
        import utils, script, config_model
        language = self.values.get('LANGUAGE_SCRIPT', 'ko_KR')
        game = self.values.get('LANGUAGE_GAME', 'en_US')
        trans = gettext.translation('messages', utils.localedir, languages=[language], fallback=True)
        trans.install()
        utils.trans = trans
        feature = getattr(self.controller, 'remote_feature', None)
        if feature is not None:
            feature.translate = get_translator(language)
        utils.LANGUAGE = utils.LANGUAGE_SCRIPT = language
        utils.LANGUAGE_GAME = game
        utils.DIALOG_OPTION_IMAGE_LIST = utils.reflectImage('dialogueChoices', game)
        script.DIALOG_OPTION_IMAGE_LIST = utils.DIALOG_OPTION_IMAGE_LIST
        targets = utils.BuildQuestReflection()
        controller_module = sys.modules.get(type(self.controller).__module__)
        for module in (utils, script, config_model, sys.modules[__name__], controller_module):
            if module is not None:
                module.LANGUAGE = module.LANGUAGE_SCRIPT = language
                module.LANGUAGE_GAME = game
                module.DUNGEON_TARGETS = targets
        globals()['CHAR_DISPLAY_TO_ID'] = {_(name): name for name in CHAR_LIST}

    def _on_window_closing(self):
        if self._allow_close:
            return True
        self.controller.request_shutdown()
        return False

    def destroy(self):
        if self._allow_close:
            return
        self._allow_close = True
        self._closing = True
        self._remove_log_sinks()
        if self._window is not None:
            self._window.destroy()

    def handle_request(self, command, value):
        if command == 'web_action':
            method = value.get('method')
            args = value.get('args') or []
            if method not in WEB_ACTIONS:
                return {'ok': False, 'error': 'unsupported_action'}
            allowed_while_running = {'stop_quest', 'set_stop_after', 'close_window', 'cancel_update',
                                     'minimize_window', 'toggle_maximize', 'set_compact', 'open_url', 'save'}
            if self._quest_active and method not in allowed_while_running:
                return {'ok': False, 'error': _('Stop the task before changing these settings.')}
            return getattr(self, method)(*args)
        methods = {'save_settings': self.save, 'save_telegram': self.save_telegram,
                   'set_language': lambda data: self.set_language(data['kind'], data['value']),
                   'test_connection': self.test_connection, 'select_target': self.select_target}
        return methods[command](value)

    def _target_text(self, target):
        info = QUEST_DATA.get(target) or {}
        return info.get('questName_' + LANGUAGE, info.get('questName', str(target or '')))

    def select_farm_target_from_remote(self, category_display, target_display):
        return bool(self.select_target(target_display).get('ok'))

    def cancel_update(self):
        return self.controller._dispatch('cancel_update', None)

    def save_telegram(self, patch):
        if not isinstance(patch, dict) or self._quest_active:
            return {'ok': False, 'error': 'settings_locked'}
        token = self.values.get('TELEGRAM_BOT_TOKEN', '')
        if patch.get('clear_token'):
            token = ''
        elif str(patch.get('bot_token', '')).strip():
            token = str(patch['bot_token']).strip()
        try:
            settings = validate_telegram_settings(TelegramSettings(
                bool(patch.get('enabled', self.values.get('TELEGRAM_ENABLED'))), token,
                str(patch.get('chat_id', self.values.get('TELEGRAM_ALLOWED_CHAT_ID', ''))).strip()))
        except TelegramConfigError as exc:
            return {'ok': False, 'error': get_translator(LANGUAGE)(str(exc))}
        with self._lock:
            self._secrets.add(token)
            self.values.update(TELEGRAM_ENABLED=settings.enabled, TELEGRAM_BOT_TOKEN=settings.bot_token,
                               TELEGRAM_ALLOWED_CHAT_ID=settings.allowed_chat_id)
            self._save_internal()
        self.msg_queue.put(('telegram_reconfigure', None))
        return self._snapshot_with_ok()

    def test_connection(self, patch=None):
        if self._quest_active or self._active_test_request_id is not None:
            return {'ok': False, 'error': 'connection_test_busy'}
        patch = patch or {}
        token = str(patch.get('bot_token') or self.values.get('TELEGRAM_BOT_TOKEN') or '').strip()
        chat_id = str(patch.get('chat_id') or self.values.get('TELEGRAM_ALLOWED_CHAT_ID') or '').strip()
        try:
            settings = validate_telegram_settings(TelegramSettings(True, token, chat_id))
        except TelegramConfigError as exc:
            return {'ok': False, 'error': get_translator(LANGUAGE)(str(exc))}
        request_id = uuid.uuid4().hex
        self._secrets.add(token)
        self._active_test_request_id = request_id
        self._test_message = _('Checking connection...')
        self.msg_queue.put(('telegram_test_connection', ConnectionTestRequest(request_id, settings)))
        self.controller.schedule_after(GUI_CONNECTION_TEST_TIMEOUT_SECONDS * 1000,
            lambda: self.show_connection_test_result(ConnectionTestResult(request_id, False, _('Connection test timed out.'))))
        return self._snapshot_with_ok()

    def show_connection_test_result(self, result):
        with self._lock:
            if result.request_id != self._active_test_request_id:
                return
            self._active_test_request_id = None
            self._test_message = redact_log_text(get_translator(LANGUAGE)(result.public_message), self._secrets)
            self.push_event({'type': 'connection_test', 'ok': result.succeeded, 'message': self._test_message})

    def apply_remote_control_state(self, state):
        with self._lock:
            self._remote_state = getattr(state, 'value', str(state))
            busy = self._remote_state in ('starting', 'running', 'stop_requested', 'returning_to_town', 'returning_to_title', 'force_stopping')
            if busy:
                self._quest_active = True
            self.push_event({'type': 'remote_state', 'state': self._remote_state, 'busy': busy})
