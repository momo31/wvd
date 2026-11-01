"""Configuration and display translations shared by headless and web entrypoints."""
from script import *
from utils import *

KO_CATEGORY_TRANSLATIONS = {
    'FFXI联动': 'FFXI 콜라보',
    '最新任务': '새 작업',
    "主线前三章": "메인 시나리오 1~3장",
    "主线第四章": "메인 시나리오 4장",
    "任务洞窟": "퀘스트 동굴",
    "矿石": "광석 파밍",
    "月常": "일일/주간/콘텐츠",
    "最新洞窟": "최신 던전",
    "其他": "기타"
}

KO_TARGET_TRANSLATIONS = {
    '[刷怪]要塞10层刷巨人': '[몬스터] 요새 10층 거인',
    '[妖精]水路船一(前导任务)': '[요정] 수로 선실 1층 (선행 작업)',
    '[妖精]水路船一(后续任务)': '[요정] 수로 선실 1층 (후속 작업)',
    '[妖精]要塞八层门口(前导任务)': '[요정] 요새 8층 입구 (선행 작업)',
    '[妖精]要塞八层陷阱(后续任务)': '[요정] 요새 8층 함정 (후속 작업)',
    '钓鱼(测试)-近端': '낚시 (시험 기능) - 가까운 지점',
    '[刷怪]FFXI 1F 精英': '[몬스터] FFXI 1층 엘리트',
    '[宝箱]FFXI 4F': '[상자] FFXI 4층',
    '[恶名]FFXI 5F 最高难度 4精英': '[악명] FFXI 5층 최고 난도 엘리트 4마리',
    '[恶名]FFXI 5F 高难度 中部2精英': '[악명] FFXI 5층 높은 난도 중부 엘리트 2마리',
    '[恶名]FFXI 5F 中等难度 底部2精英': '[악명] FFXI 5층 보통 난도 하단 엘리트 2마리',
    '[恶名]FFXI 5F 低难度 单恶魔': '[악명] FFXI 5층 낮은 난도 악마 1마리',
    '[委托]钢试炼': '[의뢰] 강철의 시련',
    '[药]华蜜': '[포션] 꽃꿀',
    '测试任务': '테스트 작업',
    "[矿石]FFXI挖矿": "[광석] FFXI 광석 무한 채굴",
    "[宝箱]FFXI联动2F": "[보물상자] 파판11 콜라보 2F",
    "[宝箱]FFXI联动2F带精英": "[보물상자] 파판11 콜라보 2F (엘리트 포함)",
    "[宝箱]FFXI 2F 自动宝箱": "[상자] FFXI 2F 자동 상자",
    "[刷怪]FFXI 2F 精英": "[몬스터] FFXI 2F 엘리트",
    "[恶名]FFXI 5F 4精英": "[악명] FFXI 5F 엘리트 4마리",
    "[恶名]FFXI 5F 2精英": "[악명] FFXI 5F 엘리트 2마리",
    "[恶名]FFXI 5F 中部2精英": "[악명] FFXI 5F 중부 엘리트 2마리",
    "[恶名]FFXI 5F 底部2精英": "[악명] FFXI 5F 하단 엘리트 2마리",
    "[恶名]FFXI 5F 左侧2精英": "[악명] FFXI 5F 좌측 엘리트 2마리",
    "[恶名]FFXI 5F 单恶魔": "[악명] FFXI 5F 엘리트 1마리",
    "无限刷怪": "[몬스터] 무한 사냥 (제자리)",
    "[宝箱]水路一号街": "[상자] 무역수로 1번가",
    "[宝箱]水路船二lounge": "[상자] 무역수로 선실 2층 (라운지)",
    "[宝箱]要塞一层": "[상자] 요새 1층",
    "[妖精]要塞八层门口": "[요정] 요새 8층 입구",
    "[妖精]要塞八层陷阱": "[요정] 요새 8층 함정",
    "[灯怪]要塞10层": "[등불] 요새 10층",
    "[刷怪]要塞7f刷巨人": "[몬스터] 요새 7층 거인 파밍",
    "[刷怪]深雪R4": "[몬스터] 대설지대 R4",
    "[宝箱+刷怪]深雪R6": "[상자+몬스터] 대설지대 R6",
    "[宝箱+刷怪]深雪R7矿洞右": "[상자+몬스터] 대설지대 R7 광산 우측",
    "[宝箱+刷怪]深雪R7自动箱": "[상자+몬스터] 대설지대 R7 자동 상자",
    "[宝箱+刷怪]深雪R10": "[상자+몬스터] 대설지대 R10",
    "[刷怪]深雪R10巨人": "[몬스터] 대설지대 R10 거인",
    "[宝箱]教会-自动宝箱上半": "[상자] 교회 - 자동 상자 상반",
    "[宝箱]教会-全范围找箱": "[상자] 교회 - 전체 구역 상자 찾기",
    "[刷怪]教会白巨人 byXX": "[몬스터] 교회 백색 거인 (byXX)",
    "[宝箱]药师洞1f宝箱": "[상자] 치유사의 마을 유적 1F",
    "[宝箱]鬼洞1f 水路出发": "[상자] 귀곡도 1F (수로 출발)",
    "[宝箱]鬼洞2F": "[상자] 귀곡도 2F",
    "[刷怪]怨嗟洞窟三层": "[몬스터] 원한의 동굴 3층",
    "[宝箱]弗德莱戈的迷宫三层": "[상자] 포드레이그의 미궁 3층 (fordraig B3F)",
    "[宝箱]忍洞一层": "[상자] 모래 그림자의 동굴 1층",
    "[宝箱]卢比肯宝箱": "[상자] 루비콘의 상자",
    "[宝箱]狼洞2f": "[상자] 백아의 동굴 2F",
    "[宝箱]狼洞1f": "[상자] 백아의 동굴 1F (고르곤 없음)",
    "[宝箱]百花之庭固定怪": "[상자] 백화의 정원 고정 몬스터",
    "[宝箱]离别洞窟": "[상자] 영별의 동굴",
    "[宝箱]离别洞窟(只刷2f)": "[상자] 영별의 동굴 (2F 전용)",
    "[任务]卢比肯 三牛": "[퀘스트] 루비콘 삼우 (세 마리 황소)",
    "[任务]忍洞一层 金箱": "[퀘스트] 모래 그림자의 동굴 1층 금색 상자",
    "[矿石]土洞(中/次)": "[광석] 땅의 마굴 (중급/하급)",
    "[矿石]火洞(特/中/次)": "[광석] 불의 마굴 (특급/중급/하급)",
    "[矿石]火洞plus-地图全开": "[광석] 불의 마굴 Plus (지도 전체 개방)",
    "[矿石]风洞(特/上/中)": "[광석] 바람의 마굴 (특급/상급/중급)",
    "[矿石]风洞plus-地图全开": "[광석] 바람의 마굴 Plus (지도 전체 개방)",
    "[矿石]光洞(特/上/中)": "[광석] 빛의 마굴 (특급/상급/중급)",
    "[矿石]光洞plus-地图全开": "[광석] 빛의 마굴 Plus (지도 전체 개방)",
    "[矿石]水洞(银/特/上)": "[광석] 수류의 구멍 (은/특급/상급)",
    "[骨头]炉壶灵庙(王都出发)": "[뼈] 용광로의 영묘 (왕도 출발)",
    "[骨头]炉壶灵庙(战士骨)": "[뼈] 용광로의 영묘 (전사의 뼈)",
    "[骨头]战士灵庙": "[뼈] 전사 영묘",
    "[骨头]盗贼灵庙": "[뼈] 도적 영묘",
    "[骨头]僧侣灵庙": "[뼈] 승려 영묘",
    "[骨头]法师灵庙": "[뼈] 마법사 영묘",
    "[骨头]骑士灵庙": "[뼈] 기사 영묘",
    "[骨头]稀有灵庙": "[뼈] Rarities 영묘",
    "[悬赏]吉尔": "[현상수배] 질",
    "[悬赏]蝎女": "[현상수배] 스코피온 (전갈 여인)",
    "[悬赏]蝎女+风暴六手": "[현상수배] 스코피온 + 폭풍의 식스암즈",
    "[金币]7000G": "[골드] 황녀에게 7000G 받기",
    "[装备]半自动大恶魔": "[장비] 대악마 반자동 파밍",
    "[装备]暗灯": "[장비] 사신의 어둠 등불",
    "[刷药]喜欢睡觉": "[포션] 잠꾸러기 퀘스트",
    "[缘]沙人": "[인연] 샌드맨",
    "mergeBlastNumber": "Tapjoy 연동 (mergeBlastNumber)"
}

REVERSE_CATEGORY_MAP = {v: k for k, v in KO_CATEGORY_TRANSLATIONS.items()}
REVERSE_TARGET_MAP = {v: k for k, v in KO_TARGET_TRANSLATIONS.items()}

def trans_cat(cat):
    if LANGUAGE == 'ko_KR':
        return KO_CATEGORY_TRANSLATIONS.get(cat, cat)
    return cat

def trans_tgt(tgt):
    if LANGUAGE == 'ko_KR':
        return KO_TARGET_TRANSLATIONS.get(tgt, tgt)
    return tgt


def _is_known_emulator_executable(path):
    executable = os.path.basename(str(path or "").replace("\\", "/")).casefold()
    return executable in {
        "hd-player.exe",
        "mumuplayer.exe",
        "mumunxdevice.exe",
    }


def _category_keys_for_display(category_display):
    """Return all internal categories represented by one visible label."""

    return [
        category
        for category in DUNGEON_TARGETS
        if trans_cat(category) == category_display
    ]


def _targets_for_category_display(category_display):
    targets = []
    for category in _category_keys_for_display(category_display):
        targets.extend(DUNGEON_TARGETS[category].keys())
    return targets


def _target_matches_display(target, target_display):
    return target_display in {
        target,
        trans_tgt(target),
        REVERSE_TARGET_MAP.get(target, target),
    }


def _category_for_target_display(target_display):
    for category, targets in DUNGEON_TARGETS.items():
        if any(_target_matches_display(target, target_display) for target in targets):
            return category
    return ""


def _quest_code_for_target_display(target_display):
    for targets in DUNGEON_TARGETS.values():
        for target, quest_code in targets.items():
            if _target_matches_display(target, target_display):
                return quest_code
    return None


def _legacy_strategy_reload_defaults(reload_mode):
    """Map the pre-2.6 global reload mode to per-strategy defaults."""

    dungeon_modes = {
        "每次副本开始",
        "每次副本开始(自动)",
        _("每次副本开始"),
        _("每次副本开始(自动)"),
    }
    combat_modes = {"每场战斗前", _("每场战斗前")}
    return reload_mode in dungeon_modes, reload_mode in combat_modes


def task_button_text(busy):
    """Return one canonical, localized label for the task toggle button."""

    return _("停止") if busy else _("脚本, 启动!")


ORIG_SKILLS = ["左上技能", "右上技能", "左下技能", "右下技能", "防御", "双击自动"]
ORIG_TARGETS = ["左上角色", "中上角色", "右上角色", "左下角色", "右下角色", "中下角色", "不可用", "低生命值"]
ORIG_FREQS = ["每场战斗仅一次", "每次副本仅一次", "每次启动仅一次", "重复"]
ORIG_GROUPS = ["全自动战斗", "柚子", "自定义任务点策略"]

REVERSE_SKILL_MAP = {_(opt): opt for opt in ORIG_SKILLS}
REVERSE_TARGET_MAP_STRAT = {_(opt): opt for opt in ORIG_TARGETS}
REVERSE_FREQ_MAP = {_(opt): opt for opt in ORIG_FREQS}
REVERSE_GROUP_MAP = {_(opt): opt for opt in ORIG_GROUPS}

REVERSE_ROLE_MAP = {_(char): char for char in CHAR_LIST}

def translate_single_strategy(config):
    if not isinstance(config, dict):
        return config
    translated = config.copy()
    if 'group_name' in config:
        translated['group_name'] = _(config['group_name'])
    if 'skill_settings' in config:
        new_settings = []
        for setting in config['skill_settings']:
            new_setting = setting.copy()
            if 'role_var' in setting and setting['role_var']:
                new_setting['role_var'] = _(setting['role_var'])
            if 'skill_var' in setting and setting['skill_var']:
                new_setting['skill_var'] = _(setting['skill_var'])
            if 'target_var' in setting and setting['target_var']:
                new_setting['target_var'] = _(setting['target_var'])
            if 'freq_var' in setting and setting['freq_var']:
                new_setting['freq_var'] = _(setting['freq_var'])
            new_settings.append(new_setting)
        translated['skill_settings'] = new_settings
    return translated

def untranslate_single_strategy(config):
    if not isinstance(config, dict):
        return config
    untranslated = config.copy()
    if 'group_name' in config:
        untranslated['group_name'] = REVERSE_GROUP_MAP.get(config['group_name'], config['group_name'])
    if 'skill_settings' in config:
        new_settings = []
        for setting in config['skill_settings']:
            new_setting = setting.copy()
            if 'role_var' in setting:
                new_setting['role_var'] = REVERSE_ROLE_MAP.get(setting['role_var'], setting['role_var'])
            if 'skill_var' in setting:
                new_setting['skill_var'] = REVERSE_SKILL_MAP.get(setting['skill_var'], setting['skill_var'])
            if 'target_var' in setting:
                new_setting['target_var'] = REVERSE_TARGET_MAP_STRAT.get(setting['target_var'], setting['target_var'])
            if 'freq_var' in setting:
                new_setting['freq_var'] = REVERSE_FREQ_MAP.get(setting['freq_var'], setting['freq_var'])
            new_settings.append(new_setting)
        untranslated['skill_settings'] = new_settings
    return untranslated

def translate_task_point_strategy(strategy_dict):
    if not isinstance(strategy_dict, dict):
        return strategy_dict
    new_dict = {}
    if 'overall_strategy' in strategy_dict:
        new_dict['overall_strategy'] = _(strategy_dict['overall_strategy'])
    if 'task_point' in strategy_dict:
        tp = strategy_dict['task_point']
        new_tp = {}
        if isinstance(tp, dict):
            for k, v in tp.items():
                new_tp[k] = _(v)
        new_dict['task_point'] = new_tp
    return new_dict

def untranslate_task_point_strategy(strategy_dict):
    if not isinstance(strategy_dict, dict):
        return strategy_dict
    new_dict = {}
    if 'overall_strategy' in strategy_dict:
        val = strategy_dict['overall_strategy']
        new_dict['overall_strategy'] = REVERSE_GROUP_MAP.get(val, val)
    if 'task_point' in strategy_dict:
        tp = strategy_dict['task_point']
        new_tp = {}
        if isinstance(tp, dict):
            for k, v in tp.items():
                new_tp[k] = REVERSE_GROUP_MAP.get(v, v)
        new_dict['task_point'] = new_tp
    return new_dict
############################################

def LoadSettingFromDict(input_dict):
    setting = FarmConfig()

    for category, attr_name, var_type, default_value in CONFIG_VAR_LIST:
        if attr_name not in input_dict:
            setattr(setting, attr_name, default_value)
        else:
            setattr(setting, attr_name, input_dict[attr_name])

    legacy_dungeon_reload, legacy_combat_reload = _legacy_strategy_reload_defaults(
        input_dict.get("RELOAD_STRATEGY_WHEN", "不需要")
    )
    setting.STRATEGY = normalize_strategy_options(
        setting.STRATEGY,
        legacy_dungeon_reload=legacy_dungeon_reload,
        legacy_combat_reload=legacy_combat_reload,
    )

    if hasattr(setting, 'STRATEGY') and isinstance(setting.STRATEGY, list):
        setting.STRATEGY = [translate_single_strategy(g) for g in setting.STRATEGY]

    if hasattr(setting, 'DEFAULT_OVERALL_STRATEGY') and isinstance(setting.DEFAULT_OVERALL_STRATEGY, str):
        setting.DEFAULT_OVERALL_STRATEGY = _(setting.DEFAULT_OVERALL_STRATEGY)

    if hasattr(setting, 'RELOAD_STRATEGY_WHEN') and isinstance(setting.RELOAD_STRATEGY_WHEN, str):
        setting.RELOAD_STRATEGY_WHEN = _(setting.RELOAD_STRATEGY_WHEN)

    if hasattr(setting, 'TASK_POINT_STRATEGY') and isinstance(setting.TASK_POINT_STRATEGY, dict):
        setting.TASK_POINT_STRATEGY = translate_task_point_strategy(setting.TASK_POINT_STRATEGY)

    if LANGUAGE == 'ko_KR' and hasattr(setting, 'FARM_TARGET_TEXT') and setting.FARM_TARGET_TEXT:
        setting.FARM_TARGET_TEXT = KO_TARGET_TRANSLATIONS.get(setting.FARM_TARGET_TEXT, setting.FARM_TARGET_TEXT)

    return setting

def LoadConfig(specific='ALL', config_path=None):
    raw_config = LoadRawConfigFromFile(config_path) or {}
    general_config = raw_config.get("GENERAL", {})

    task_specific = general_config.get("TASK_SPECIFIC_CONFIG", False)
    farm_target = general_config.get("FARM_TARGET")

    if task_specific and farm_target and farm_target in raw_config:
        # 任务特定模式：从对应任务字典加载
        task_config = raw_config.get(farm_target, {})
    else:
        # 非任务特定模式或目标无效：从 DEFAULT 加载
        task_config = raw_config.get("DEFAULT", {})

    if specific == "ALL":
        result_config = {}
        result_config.update(task_config)
        result_config.update(general_config)
    elif specific == "general":
        result_config = general_config
    elif specific == "specific":
        result_config = raw_config.get(farm_target, {})
    elif specific == "default":
        result_config = raw_config.get("DEFAULT", {})

    return result_config
