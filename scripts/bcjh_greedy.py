"""
爆炒江湖 厨神计算器 贪心最优组合求解器（纯 Python 版）
=============================================================
无需浏览器，内存占用 < 50MB，适合 2核2G 低配机器。

依赖：仅标准库（无第三方依赖）

使用方法：
  # 首次使用（需要校验码导入个人数据）：
  python3 bcjh_greedy_pure.py --code 你的校验码

  # 后续使用（自动读取缓存）：
  python3 bcjh_greedy_pure.py

算法说明：
  - 纯 Python 复现网站 calculator.js 的全部计分逻辑
  - 贪心策略与 bcjh_greedy.py 完全一致
  - 数据源：本地 data.min.json + 在线 API 获取规则和个人数据
"""

import argparse
import copy
import json
import math
import os
import random
import re
import sys
import urllib.request

# ── 在这里填写你的校验码（也可以通过命令行参数 --code 传入）──
USER_CODE = ""
# ─────────────────────────────────────────────────────────────

MAX_CHEFS = 3
MAX_REPS_PER_CHEF = 3

# 路径
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.join(SCRIPT_DIR, '.bcjh_user_caches')
# 兼容旧版单文件缓存
LEGACY_CACHE_FILE = os.path.join(SCRIPT_DIR, '.bcjh_user_cache.json')


def _get_cache_file(user_id=None):
    """根据 user_id 返回对应的缓存文件路径；无 user_id 时使用旧版单文件"""
    if not user_id:
        return LEGACY_CACHE_FILE
    os.makedirs(CACHE_DIR, exist_ok=True)
    return os.path.join(CACHE_DIR, f'{user_id}.json')

# ── 常量 ──
GRADE_BUFF = {1: 0, 2: 10, 3: 30, 4: 50, 5: 100}
SKILL_TYPES = ['Stirfry', 'Boil', 'Knife', 'Fry', 'Bake', 'Steam']
SKILL_KEYS = ['stirfry', 'boil', 'knife', 'fry', 'bake', 'steam']
MATERIAL_TYPES = ['Meat', 'Vegetable', 'Creation', 'Fish']
CONDIMENT_TYPES = ['Sweet', 'Sour', 'Spicy', 'Salty', 'Bitter', 'Tasty']
# 集合版本（O(1) 查找）
SKILL_TYPES_SET = frozenset(SKILL_TYPES)
MATERIAL_TYPES_SET = frozenset(MATERIAL_TYPES)
CONDIMENT_TYPES_SET = frozenset(CONDIMENT_TYPES)
LIMIT_BASE = {1: 40, 2: 30, 3: 25, 4: 20, 5: 15}
SKILL_MAP = {'stirfry': '炒', 'boil': '煮', 'knife': '切', 'fry': '炸', 'bake': '烤', 'steam': '蒸'}


# ══════════════════════════════════════════════
#  工具函数
# ══════════════════════════════════════════════

def judge_eff(eff):
    """判断效果是否影响售价/份数"""
    t = eff.get('type', '')
    return (t[:3] == 'Use' or t == 'Gold_Gain' or t[-5:] == 'Price' or
            t[-5:] == 'Limit' or t[:10] == 'BasicPrice' or t == 'MaterialReduce')


def check_tag(cond_list, tags):
    """检查 tag 交集（无临时 set 创建，适合小列表高频调用）"""
    if not cond_list or not tags:
        return False
    for t in cond_list:
        if t in tags:
            return True
    return False


def dc(obj):
    """深拷贝"""
    return copy.deepcopy(obj)


# ══════════════════════════════════════════════
#  数据加载
# ══════════════════════════════════════════════

def _fetch_url(url, timeout=15, retries=3):
    """带重试的 URL 请求"""
    import time as _time
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    last_err = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read().decode('utf-8')
        except Exception as e:
            last_err = e
            if attempt < retries - 1:
                wait = 2 ** attempt  # 1s, 2s
                print(f"  请求失败({e})，{wait}秒后重试...")
                _time.sleep(wait)
    raise last_err

GAME_DATA_URL = 'https://h5.baochaojianghu.com/data/data.min.json'
GAME_DATA_CACHE = os.path.join(SCRIPT_DIR, '.bcjh_game_data.json')
# 备用本地路径（兼容旧目录结构）
GAME_DATA_LEGACY = os.path.join(SCRIPT_DIR, '..', 'h5.baochaojianghu.com',
                                'h5.baochaojianghu.com', 'data', 'data.min.json')


def load_game_data():
    """加载游戏数据：优先在线下载，失败则用本地缓存"""
    # 1. 尝试在线下载
    try:
        print(f"  从在线获取游戏数据...")
        raw = _fetch_url(GAME_DATA_URL, timeout=30)
        data = json.loads(raw)
        # 缓存到本地
        with open(GAME_DATA_CACHE, 'w', encoding='utf-8') as f:
            f.write(raw)
        print(f"  在线获取成功，已缓存到本地")
        return data
    except Exception as e:
        print(f"  在线获取失败: {e}，尝试本地缓存...")

    # 2. 尝试本地缓存
    for path in [GAME_DATA_CACHE, GAME_DATA_LEGACY]:
        if os.path.exists(path):
            print(f"  使用本地缓存: {path}")
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)

    print("错误：无法获取游戏数据（在线下载失败且无本地缓存）")
    sys.exit(1)


def fetch_rules():
    """从 API 获取当前规则"""
    url = 'https://i.baochaojianghu.com/api/get_rule'
    try:
        raw = _fetch_url(url)
        data = json.loads(raw)
        return data.get('rules', [])
    except Exception as e:
        print(f"  获取在线规则失败: {e}，尝试本地缓存...")
        cached = os.path.join(SCRIPT_DIR, '..', 'h5.baochaojianghu.com',
                              'i.baochaojianghu.com', 'api', 'get_rule.html')
        if os.path.exists(cached):
            with open(cached, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return data.get('rules', [])
        return []


def fetch_user_data_from_api(code):
    """通过校验码从 API 获取个人数据"""
    url = f'https://yx518.com/api/archive.do?token={code}'
    raw = _fetch_url(url)
    result = json.loads(raw)
    if result.get('ret') != 'S':
        raise ValueError(f"导入失败：{result.get('msg', '未知错误')}")
    return result['msg']


def save_user_cache(user_data, user_id=None):
    """缓存个人数据到本地"""
    cache_file = _get_cache_file(user_id)
    with open(cache_file, 'w', encoding='utf-8') as f:
        json.dump(user_data, f, ensure_ascii=False)
    print(f"  个人数据已缓存到: {cache_file}")


def load_user_cache(user_id=None):
    """读取本地缓存"""
    cache_file = _get_cache_file(user_id)
    if os.path.exists(cache_file):
        with open(cache_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    # 有 user_id 但无对应缓存时，尝试迁移旧版单文件缓存
    if user_id and os.path.exists(LEGACY_CACHE_FILE):
        print(f"  未找到用户 {user_id} 的缓存，发现旧版缓存，跳过（旧缓存可能属于其他用户）。")
    return None


# ══════════════════════════════════════════════
#  数据处理
# ══════════════════════════════════════════════

class GameData:
    """处理后的游戏数据"""

    def __init__(self, raw_data, food_god_rules):
        self.raw = raw_data
        self.skill_map = {}  # skillId -> skill obj
        self.disk_map = {}   # diskId -> {maxLevel, info}
        self.recipes = []
        self.chefs = []
        self.equips = []
        self.ambers = []
        self.condiments = []
        self.materials = []
        self.rules = []
        self.combo_map = {'combo': {}, 'split': {}}
        self._process(food_god_rules)

    def _process(self, food_god_rules):
        # 技能 map
        for s in self.raw['skills']:
            self.skill_map[s['skillId']] = s

        # 心法盘 map
        for d in self.raw['disks']:
            self.disk_map[d['diskId']] = {'maxLevel': d['maxLevel'], 'info': d['info']}

        # 合成 map
        for c in self.raw.get('combos', []):
            self.combo_map['combo'][c['recipeId']] = c['recipes']
            for rid in c['recipes']:
                self.combo_map['split'].setdefault(rid, []).append(c['recipeId'])

        # 材料
        self.materials = self.raw['materials']

        # 菜谱处理
        mat_map = {m['materialId']: m for m in self.materials}
        for item in self.raw['recipes']:
            r = dict(item)
            r['id'] = r['recipeId']
            skills = {}
            for sk in SKILL_KEYS:
                if r.get(sk):
                    skills[sk] = r[sk]
            r['skills'] = skills
            r['materials_type'] = list(set(
                self._get_material_type(mat_map.get(m['material'], {}).get('origin', ''))
                for m in r.get('materials', [])
            ))
            r['materials_search'] = ' '.join(
                mat_map.get(m['material'], {}).get('name', '') for m in r.get('materials', [])
            )
            r['materials_id'] = [m['material'] for m in r.get('materials', [])]
            r['condiment_show'] = {'Sweet': '甜', 'Sour': '酸', 'Spicy': '辣',
                                   'Salty': '咸', 'Bitter': '苦', 'Tasty': '鲜'}.get(r.get('condiment', ''), '')
            r['tags'] = r.get('tags', [])
            r['gold_eff'] = round(3600 / r['time'] * r['price']) if r['time'] > 0 else 0
            r['time_show'] = self._format_time(r['time'])
            r['exPrice'] = r.get('exPrice', 0)
            self.recipes.append(r)

        # 厨师处理
        for item in self.raw['chefs']:
            c = dict(item)
            c['id'] = c['chefId']
            # 解析常驻技能
            skill_id = c.get('skill')
            if isinstance(skill_id, int):
                skill_obj = self.skill_map.get(skill_id, {'effect': [], 'desc': ''})
                c['skill_desc'] = skill_obj.get('desc', '')
                c['skill_obj'] = skill_obj
            else:
                c['skill_obj'] = {'effect': [], 'desc': str(skill_id)}
            # 解析修炼技能列表
            ult_ids = c.get('ultimateSkillList', [])
            if ult_ids and isinstance(ult_ids[0], int):
                c['ultimateSkillList'] = [self.skill_map[sid] for sid in ult_ids if sid in self.skill_map]
            c['tags'] = c.get('tags', [])
            c['baseChefId'] = c.get('baseChefId', 0)
            self.chefs.append(c)

        # 厨具处理
        for item in self.raw['equips']:
            e = dict(item)
            e['id'] = e['equipId']
            skill_ids = e.get('skill', [])
            if isinstance(skill_ids, list):
                effects = []
                for sid in skill_ids:
                    s = self.skill_map.get(sid)
                    if s:
                        effects.extend(s.get('effect', []))
                e['effect'] = effects
            e['rarity_show'] = '★' * e.get('rarity', 0)
            self.equips.append(e)

        # 遗玉处理
        self.amber_by_type = {1: [], 2: [], 3: []}
        for item in self.raw['ambers']:
            a = dict(item)
            a['id'] = a['amberId']
            skill_ids = a.get('skill', [])
            skill_list = []
            effects = []
            for sid in (skill_ids if isinstance(skill_ids, list) else [skill_ids]):
                s = self.skill_map.get(sid)
                if s:
                    skill_list.append(s)
                    effects.extend(s.get('effect', []))
            a['effect'] = effects
            a['skill_list'] = skill_list
            a['amplification'] = a.get('amplification', 0)
            a_type = a.get('type', 1)
            self.amber_by_type.setdefault(a_type, []).append(a)
            self.ambers.append(a)

        # 调料处理
        for item in self.raw['condiments']:
            c = dict(item)
            c['id'] = c['condimentId']
            skill_ids = c.get('skill', [])
            effects = []
            for sid in (skill_ids if isinstance(skill_ids, list) else [skill_ids]):
                s = self.skill_map.get(sid)
                if s:
                    effects.extend(s.get('effect', []))
            c['effect'] = effects
            self.condiments.append(c)

        # 规则处理
        default_rule = 0
        rules = [r for r in self.raw.get('rules', []) if r.get('Id', 0) < 620000]
        if food_god_rules:
            default_rule = food_god_rules[0].get('Id', 0)
            rules = food_god_rules + rules
        self.rules = rules
        self.default_rule_id = default_rule

    @staticmethod
    def _get_material_type(origin):
        for origins, mtype in [
            (['菜棚', '菜地', '森林'], 'vegetable'),
            (['鸡舍', '猪圈', '牧场'], 'meat'),
            (['作坊'], 'creation'),
            (['池塘'], 'fish'),
        ]:
            for o in origins:
                if o in str(origin):
                    return mtype
        return 'vegetable'

    @staticmethod
    def _format_time(seconds):
        if seconds < 60:
            return f"{seconds}秒"
        if seconds < 3600:
            m, s = divmod(seconds, 60)
            return f"{m}分{s}秒" if s else f"{m}分"
        h, rem = divmod(seconds, 3600)
        m = rem // 60
        return f"{h}时{m}分" if m else f"{h}时"


class UserData:
    """个人数据"""

    def __init__(self):
        self.rep_got = {}       # recipeId -> bool
        self.chef_got = {}      # chefId -> bool
        self.chef_ult = {}      # chefId -> bool (是否已修炼)
        self.chef_amber = {}    # chefId -> [amberId, ...]
        self.chef_equip = {}    # chefId -> equipId
        self.chef_disk_lv = {}  # chefId -> level
        self.deco_buff = 0      # 装修加成
        self.qixia_skill_obj_tag = {}  # 七侠技法加成
        self.user_ultimate = {
            'Partial': {'id': [], 'row': []},
            'Self': {'id': [], 'row': []},
            'Stirfry': 0, 'Boil': 0, 'Knife': 0, 'Fry': 0, 'Bake': 0, 'Steam': 0,
            'Male': 0, 'Female': 0, 'All': 0,
            'PriceBuff_1': 0, 'PriceBuff_2': 0, 'PriceBuff_3': 0, 'PriceBuff_4': 0, 'PriceBuff_5': 0,
            'MaxLimit_1': 0, 'MaxLimit_2': 0, 'MaxLimit_3': 0, 'MaxLimit_4': 0, 'MaxLimit_5': 0,
            'decoBuff': 0,
        }

    def import_from_api(self, api_data, game_data):
        """从 API 数据导入"""
        # api_data 结构: {recipes: [{id, got}], chefs: [{id, got, ult, ambers, equip, dlv}], decorationEffect}
        for r in api_data.get('recipes', []):
            self.rep_got[r['id']] = (r.get('got') == '是')
        for c in api_data.get('chefs', []):
            cid = c['id']
            self.chef_got[cid] = (c.get('got') == '是')
            self.chef_ult[cid] = (c.get('ult') == '是')
            if c.get('ambers'):
                self.chef_amber[cid] = c['ambers']
            if c.get('equip'):
                self.chef_equip[cid] = c['equip']
            if c.get('dlv'):
                self.chef_disk_lv[cid] = c['dlv']
        self.deco_buff = api_data.get('decorationEffect', 0) or 0
        self._compute_ultimate(game_data)

    def import_from_cache(self, cache_data, game_data):
        """从缓存数据导入"""
        self.rep_got = {int(k): v for k, v in cache_data.get('rep_got', {}).items()}
        self.chef_got = {int(k): v for k, v in cache_data.get('chef_got', {}).items()}
        self.chef_ult = {int(k): v for k, v in cache_data.get('chef_ult', {}).items()}
        self.chef_amber = {int(k): v for k, v in cache_data.get('chef_amber', {}).items()}
        self.chef_equip = {int(k): v for k, v in cache_data.get('chef_equip', {}).items()}
        self.chef_disk_lv = {int(k): v for k, v in cache_data.get('chef_disk_lv', {}).items()}
        self.deco_buff = cache_data.get('deco_buff', 0)
        self._compute_ultimate(game_data)

    def to_cache(self):
        """导出为可缓存的字典"""
        return {
            'rep_got': {str(k): v for k, v in self.rep_got.items()},
            'chef_got': {str(k): v for k, v in self.chef_got.items()},
            'chef_ult': {str(k): v for k, v in self.chef_ult.items()},
            'chef_amber': {str(k): v for k, v in self.chef_amber.items()},
            'chef_equip': {str(k): v for k, v in self.chef_equip.items()},
            'chef_disk_lv': {str(k): v for k, v in self.chef_disk_lv.items()},
            'deco_buff': self.deco_buff,
        }

    def _compute_ultimate(self, gd):
        """计算修炼加成（对应 JS setUlti）"""
        ulti = {
            'Partial': {'id': [], 'row': []},
            'Self': {'id': [], 'row': []},
            'Stirfry': 0, 'Boil': 0, 'Knife': 0, 'Fry': 0, 'Bake': 0, 'Steam': 0,
            'Male': 0, 'Female': 0, 'All': 0,
            'PriceBuff_1': 0, 'PriceBuff_2': 0, 'PriceBuff_3': 0, 'PriceBuff_4': 0, 'PriceBuff_5': 0,
            'MaxLimit_1': 0, 'MaxLimit_2': 0, 'MaxLimit_3': 0, 'MaxLimit_4': 0, 'MaxLimit_5': 0,
            'decoBuff': self.deco_buff or 0,
        }
        qixia_tag = {}  # tag -> {Stirfry:0, ...}

        for chef in gd.chefs:
            cid = chef['chefId']
            if not self.chef_ult.get(cid, False):
                continue
            for skill in chef.get('ultimateSkillList', []):
                if not skill:
                    continue
                uid = f"{cid},{skill['skillId']}"
                sc = skill.get('skillCondition', '')
                if sc in ('Partial', 'Next'):
                    ulti['Partial']['id'].append(uid)
                    ulti['Partial']['row'].append({
                        'id': uid, 'name': chef['name'],
                        'subName': skill.get('desc', ''), 'effect': skill.get('effect', [])
                    })
                if sc == 'Self':
                    eff = [e for e in skill.get('effect', [])
                           if e.get('type') not in ('Material_Gain', 'GuestDropCount')]
                    if eff:
                        ulti['Self']['id'].append(uid)
                        ulti['Self']['row'].append({
                            'id': uid, 'name': chef['name'],
                            'subName': skill.get('desc', ''), 'effect': eff
                        })
                if not skill.get('isGlobalQuanJiFa') and not skill.get('isQiXiaJiFa'):
                    for eff in skill.get('effect', []):
                        if eff.get('condition') == 'Global' and not eff.get('tag'):
                            if eff['type'] in ulti and isinstance(ulti[eff['type']], (int, float)):
                                ulti[eff['type']] += eff.get('value', 0)
                        for i in range(1, 6):
                            if eff.get('type') == 'UseAll' and eff.get('rarity') == i:
                                ulti[f'PriceBuff_{i}'] += eff.get('value', 0)
                            if (eff.get('type') == 'MaxEquipLimit' and
                                    eff.get('rarity') == i and eff.get('condition') == 'Global'):
                                ulti[f'MaxLimit_{i}'] += eff.get('value', 0)
                if skill.get('isGlobalQuanJiFa'):
                    eff = skill['effect'][0] if skill.get('effect') else None
                    if eff:
                        tag = eff.get('tag')
                        if tag == 1:
                            ulti['Male'] += eff.get('value', 0)
                        elif tag == 2:
                            ulti['Female'] += eff.get('value', 0)
                        else:
                            ulti['All'] += eff.get('value', 0)
                if skill.get('isQiXiaJiFa') and skill.get('effect'):
                    eff0 = skill['effect'][0]
                    match_count = 0
                    for cv in eff0.get('conditionValueList', []):
                        for ch in gd.chefs:
                            if self.chef_got.get(ch['chefId']) and ch.get('baseChefId') == cv:
                                match_count += 1
                    if match_count >= len(eff0.get('conditionValueList', [])):
                        tag = eff0.get('tag')
                        if tag not in qixia_tag:
                            qixia_tag[tag] = {st: 0 for st in SKILL_TYPES}
                        for ef in skill['effect']:
                            if ef.get('type') in qixia_tag.get(ef.get('tag'), {}):
                                qixia_tag[ef['tag']][ef['type']] += ef.get('value', 0)

        self.user_ultimate = ulti
        self.qixia_skill_obj_tag = qixia_tag


# ══════════════════════════════════════════════
#  计算器引擎
# ══════════════════════════════════════════════

class Calculator:
    """纯 Python 计算器引擎（对应 calculator.js）"""

    def __init__(self, gd, ud, rule_id=None, show_got=True):
        self.gd = gd
        self.ud = ud
        self.rule = None
        self.custom_rule = None

        # 计算器状态
        self._batch_mode = False  # 批量模式：延迟 _handler_all_chefs
        self.cal_chef = {1: None, 2: None, 3: None}      # slot -> chef_list_item
        self.cal_chef_show = {1: {}, 2: {}, 3: {}}        # slot -> showChef result
        self.cal_rep = {}        # "slot-num" -> recipe obj or None
        self.cal_rep_cnt = {}    # "slot-num" -> count
        self.rep_cnt_map = {}    # recipe_id -> "slot-num"
        self.on_site_chef = []
        self.on_site_effect = {1: [], 2: [], 3: []}
        self.cal_reps_all = []   # 所有菜谱（含基础分）
        self.cal_chefs_list = [] # 厨师列表
        self.cal_equips_map = {} # equipId -> equip obj
        self.materials_all = {}  # materialId -> limit
        self.ulti = {}           # 当前使用的修炼加成
        self.default_ex = False
        self.default_disk_max = False
        self.show_got = show_got

        self._select_rule(rule_id)
        self._init()

    def _select_rule(self, rule_id):
        if rule_id is None:
            rule_id = self.gd.default_rule_id
        for r in self.gd.rules:
            if r.get('Id') == rule_id or r.get('id') == rule_id:
                self.rule = r
                break
        if self.rule is None and self.gd.rules:
            self.rule = self.gd.rules[0]
        if self.rule is None:
            self.rule = {'Id': 0, 'id': 0, 'Title': '正常营业'}
        self.custom_rule = self.rule.get('CustomRule')
        # 预计算常用标志（避免每次 cal_score 都查询）
        self._rule_id = self.rule.get('Id', self.rule.get('id', 0))
        self._disable_chef_skill = bool(self.rule.get('DisableChefSkillEffect'))
        self._disable_equip_skill = bool(self.rule.get('DisableEquipSkillEffect'))
        self._disable_condiment_skill = bool(self.rule.get('DisableCondimentSkillEffect'))
        self._disable_multi_cookbook = bool(self.rule.get('DisableMultiCookbook'))
        self._chef_tag_effect = self.rule.get('ChefTagEffect')

    def _init(self):
        """初始化计算器（对应 initCal）"""
        self._chef_map = {}  # chef_id -> chef obj (快速查找)
        self._rep_map = {}   # recipe_id -> recipe obj (快速查找)
        self._rep_name_map = {}  # recipe_id -> name (快速查找)
        self.ulti = dc(self.ud.user_ultimate)
        # 确保数值类型
        for k in ['Stirfry', 'Boil', 'Knife', 'Fry', 'Bake', 'Steam',
                   'Male', 'Female', 'All', 'decoBuff'] + \
                  [f'PriceBuff_{i}' for i in range(1, 6)] + \
                  [f'MaxLimit_{i}' for i in range(1, 6)]:
            self.ulti[k] = int(self.ulti.get(k, 0) or 0)

        # 材料限制
        rule = self.rule
        if rule.get('MaterialsLimit'):
            ml = rule['MaterialsLimit']
            if isinstance(ml, dict):
                self.materials_all = {m['materialId']: ml.get(str(m['materialId']), ml.get(m['materialId'], 0))
                                      for m in self.gd.materials}
            elif isinstance(ml, (int, float)):
                self.materials_all = {m['materialId']: ml for m in self.gd.materials}

        # 厨具 map
        self.cal_equips_map = {e['equipId']: e for e in self.gd.equips}

        self._init_cal_chef()
        self._init_cal_rep()
        self.reset()

    def _init_cal_chef(self):
        """构建厨师列表（对应 initCalChef）"""
        rule = self.rule
        chefs_list = []
        for item in self.gd.chefs:
            tags = item.get('tags', [])
            show_tags = [t for t in tags if t in (1, 2)]
            chef_buff = 0
            sub_name_origin = None
            if rule.get('ChefTagEffect'):
                for tag in show_tags:
                    chef_buff += rule['ChefTagEffect'].get(tag, rule['ChefTagEffect'].get(str(tag), 0))
                sub_name_origin = f'{chef_buff}倍' if chef_buff else ''

            # EnableChefTags 检查
            enable = True
            if rule.get('EnableChefTags'):
                enable = any(t in rule['EnableChefTags'] for t in tags) if tags else False
            if not enable:
                continue

            ult_eff_list = []
            for sk in item.get('ultimateSkillList', []):
                if sk:
                    ult_eff_list.append({
                        'uid': f"{item['chefId']},{sk['skillId']}",
                        'ultimate_effect': sk.get('effect', [])
                    })

            chefs_list.append({
                'id': item['chefId'],
                'rarity': item.get('rarity', 1),
                'name': item['name'],
                'subName_origin': sub_name_origin,
                'isf': chef_buff < 0 if rule.get('ChefTagEffect') else False,
                'skills': {sk: item.get(sk, 0) or 0 for sk in SKILL_KEYS},
                'skill_effect': item['skill_obj'].get('effect', []),
                'ultimate_effect': ult_eff_list,
                'disk': self.gd.disk_map.get(item.get('disk', 0), {'maxLevel': 1, 'info': []}),
                'tags': tags,
            })

        chefs_list.sort(key=lambda x: (-x['rarity'], -x['id']))

        if self.show_got:
            self.cal_chefs_list = [c for c in chefs_list if self.ud.chef_got.get(c['id'], False)]
        else:
            self.cal_chefs_list = chefs_list
        self._all_chefs_list = chefs_list
        # 构建 chef_id -> chef 快速查找字典
        self._chef_map = {c['id']: c for c in chefs_list}

    def _init_cal_rep(self):
        """构建菜谱列表（对应 initCalRep）"""
        rule = self.rule
        reps = []
        muti_effect = {}
        if self.custom_rule and self.custom_rule.get('effect'):
            effect = self.custom_rule['effect']
            if not rule.get('CustomMuti'):
                self._set_custom_rule(effect, rule)
            else:
                self._set_custom_rule(effect, muti_effect)

        for item in self.gd.recipes:
            r = {}
            r['id'] = item['recipeId']
            r['materials'] = [dict(m, name=next((mat['name'] for mat in self.gd.materials
                                                  if mat['materialId'] == m['material']), ''))
                              for m in item.get('materials', [])]
            r['materials_id'] = item.get('materials_id', [])
            r['materials_type'] = item.get('materials_type', [])
            r['materials_search'] = item.get('materials_search', '')

            buff = 100
            ex = item.get('exPrice', 0) if self.default_ex else 0
            r['buff_ulti'] = self.ulti.get(f"PriceBuff_{item['rarity']}", 0)
            buff += r['buff_ulti']

            buff_rule = 0
            buff_muti = 100
            r_id = self.rule.get('Id', self.rule.get('id', 0))
            if r_id == 0:
                r['buff_deco'] = self.ulti.get('decoBuff', 0)
                buff += r['buff_deco']
            else:
                if rule.get('RecipeEffect'):
                    re_val = rule['RecipeEffect'].get(str(r['id']), rule['RecipeEffect'].get(r['id']))
                    if re_val is not None:
                        buff_rule += int(re_val * 100)
                    else:
                        r['unknowBuff'] = True
                    if rule.get('NotSure') and r['id'] in rule['NotSure']:
                        r['NotSure'] = True
                buff_rule += self._sum_buff_rule(rule, item)
                buff_muti += self._sum_buff_rule(muti_effect, item)

            r['buff_rule'] = buff_rule
            r['buff_muti'] = buff_muti
            r['price_wipe_rule'] = math.ceil((item['price'] + ex) * buff / 100)
            buff += buff_rule
            r['price_buff'] = math.ceil((item['price'] + ex) * buff * buff_muti / 10000)

            limit = item.get('limit', LIMIT_BASE.get(item['rarity'], 40)) + self.ulti.get(f"MaxLimit_{item['rarity']}", 0)
            if self.custom_rule and self.custom_rule.get('skill', {}).get('MaxLimit'):
                limit += int(self.custom_rule['skill']['MaxLimit'].get(str(item['rarity']), 0) or 0)
            r['limit_origin'] = limit
            if rule.get('DisableMultiCookbook'):
                r['limit_origin'] = 1
            r['limit'] = r['limit_origin']
            r['limit_mater'] = 500
            r['price_total'] = r['price_buff'] * r['limit']
            r['buff'] = buff
            r['basicPrice'] = 0

            # 附加属性
            r['name_show'] = item['name']
            r['name'] = item['name']
            r['rarity'] = item['rarity']
            r['rarity_show'] = '★' * item['rarity']
            r['price'] = item['price']
            r['exPrice'] = item.get('exPrice', 0)
            r['skills'] = item.get('skills', {})
            r['time'] = item['time']
            r['time_last'] = item['time']
            r['time_show'] = item.get('time_show', '')
            r['gold_eff'] = item.get('gold_eff', 0)
            r['condiment'] = item.get('condiment', '')
            r['condiment_show'] = item.get('condiment_show', '')
            r['tags'] = item.get('tags', [])
            r['isCombo'] = bool(self.gd.combo_map['combo'].get(item['recipeId']))
            for sk in SKILL_KEYS:
                r[sk] = item.get(sk, 0) or 0

            rarity_limit = rule.get('CookbookRarityLimit', 6)
            if item['rarity'] <= rarity_limit:
                reps.append(r)

        self.cal_reps_all = reps
        # 构建 recipe_id -> recipe 快速查找字典
        self._rep_map = {r['id']: r for r in reps}
        self._rep_name_map = {r['id']: r.get('name_show', r.get('name', '')) for r in reps}

    def _set_custom_rule(self, custom, rule_target):
        for p in ['SkillEffect', 'CondimentEffect', 'MaterialTypeEffect']:
            if custom.get(p):
                rule_target[p] = {k: round(float(v or 0) / 100, 3) for k, v in custom[p].items()}
        rule_target['TotalEffect'] = int(custom.get('TotalEffect', 0) or 0)

    def _sum_buff_rule(self, rule, recipe):
        buff = 0
        if rule.get('MaterialsEffect'):
            for m in rule['MaterialsEffect']:
                if m.get('MaterialID') in recipe.get('materials_id', []):
                    buff += int(m.get('Effect', 0) * 100)
        if rule.get('SkillEffect'):
            for sk_code, val in rule['SkillEffect'].items():
                if recipe.get(sk_code) or recipe.get(sk_code.lower()):
                    buff += round((val or 0) * 100)
        if rule.get('RarityEffect'):
            buff += round((rule['RarityEffect'].get(str(recipe['rarity']),
                           rule['RarityEffect'].get(recipe['rarity'], 0)) or 0) * 100)
        if rule.get('CondimentEffect'):
            buff += round((rule['CondimentEffect'].get(recipe.get('condiment', ''), 0) or 0) * 100)
        if rule.get('MaterialTypeEffect'):
            mat_types_lower = [m.lower() for m in recipe.get('materials_type', [])]
            for mtype, val in rule['MaterialTypeEffect'].items():
                if mtype.lower() in mat_types_lower:
                    buff += round(val * 100)
        if rule.get('TotalEffect'):
            buff += rule['TotalEffect']
        return buff

    # ── 状态管理 ──

    def reset(self):
        self.cal_chef = {1: None, 2: None, 3: None}
        self.cal_chef_show = {1: {}, 2: {}, 3: {}}
        self.on_site_chef = []
        self.on_site_effect = {1: [], 2: [], 3: []}
        self.cal_rep = {}
        self.cal_rep_cnt = {}
        self.rep_cnt_map = {}
        self._recipe_list_cache = {}
        for s in range(1, 4):
            for n in range(1, 4):
                self.cal_rep[f'{s}-{n}'] = None
                self.cal_rep_cnt[f'{s}-{n}'] = None

    def set_chef(self, slot, chef_id):
        """设置厨师到指定槽位"""
        c = self._chef_map.get(chef_id)
        if not c:
            return
        chef = dict(c)  # 浅拷贝足够：show_chef只添加新key不修改原嵌套结构
        self.cal_chef[slot] = chef
        self.on_site_chef = [self.cal_chef[i]['id'] for i in range(1, 4) if self.cal_chef[i]]

        # 加载用户遗玉/厨具配置
        ambers = self._load_chef_ambers(chef, slot)
        eqp = self._load_chef_equip(chef['id'])

        self.cal_chef_show[slot] = self.show_chef(chef, slot, eqp=eqp, ambers=ambers)
        if not self._batch_mode:
            self._handler_all_chefs()

    def _load_chef_ambers(self, chef, slot):
        """加载厨师的遗玉配置"""
        ambers = []
        cid = chef['id']
        disk_info = chef.get('disk', {}).get('info', [])
        disk_max = chef.get('disk', {}).get('maxLevel', 1)
        level = self.ud.chef_disk_lv.get(cid, 1)
        if self.default_disk_max:
            level = disk_max
        self._current_disk_level = level

        user_ambers = self.ud.chef_amber.get(cid, [])
        for i, atype in enumerate(disk_info):
            amber_id = user_ambers[i] if i < len(user_ambers) else 0
            if amber_id:
                for a in self.gd.amber_by_type.get(atype, []):
                    if a['amberId'] == amber_id:
                        ambers.append(a)
                        break
                else:
                    ambers.append(None)
            else:
                ambers.append(None)
        return ambers

    def _load_chef_equip(self, chef_id):
        """加载厨师的厨具配置"""
        equip_id = self.ud.chef_equip.get(chef_id, 0)
        if equip_id:
            return self.cal_equips_map.get(equip_id)
        return None

    def set_recipe(self, slot, rep_num, recipe_id):
        """设置菜谱"""
        key = f'{slot}-{rep_num}'
        rep = self._rep_map.get(recipe_id)
        if not rep:
            return
        self.cal_rep[key] = rep
        self.rep_cnt_map[recipe_id] = key

        # 设置份数
        if self.cal_chef[slot] and rep.get(f'chef_{slot}'):
            self.cal_rep_cnt[key] = rep[f'chef_{slot}'].get('limit', rep.get('limit', 1))
        else:
            self.cal_rep_cnt[key] = rep.get('limit', 1)

        # 重算所有在场厨师
        if self.cal_chef[slot] and not self._batch_mode:
            self._handler_all_chefs()

    def clear_recipe(self, slot, rep_num):
        key = f'{slot}-{rep_num}'
        old_rep = self.cal_rep.get(key)
        if old_rep and old_rep['id'] in self.rep_cnt_map:
            del self.rep_cnt_map[old_rep['id']]
        self.cal_rep[key] = None
        self.cal_rep_cnt[key] = None
        if self.cal_chef[slot]:
            self._handler_chef(slot)

    def clear_chef(self, slot):
        for rn in range(1, 4):
            self.clear_recipe(slot, rn)
        self.cal_chef[slot] = None
        self.cal_chef_show[slot] = {}
        self.on_site_chef = [self.cal_chef[i]['id'] for i in range(1, 4) if self.cal_chef[i]]
        self.on_site_effect[slot] = []

    # ── 核心计算 ──

    def show_chef(self, chef, position, eqp=None, condi=None, ambers=None):
        """计算厨师最终属性（对应 JS showChef）"""
        rule = self.rule
        skills_last = {}
        equip_effect = []
        condiment_effect = []
        sum_skill_effect = []
        amber_effect = []
        effect_condition = []
        time_buff = 0
        equip_time_buff = 0
        disk_level = getattr(self, '_current_disk_level', 1)
        last_chef = self._get_last_chef(position)

        if eqp and not rule.get('DisableEquipSkillEffect'):
            for eff in eqp.get('effect', []):
                if eff.get('type') == 'OpenTime':
                    equip_time_buff = eff['value']
                if judge_eff(eff):
                    equip_effect.append(eff)
        if condi:
            condiment_effect = list(condi.get('effect', []))

        ambers_effect_all = []
        if ambers:
            for amber in ambers:
                if not amber:
                    continue
                for skill in amber.get('skill_list', []):
                    for eff in skill.get('effect', []):
                        e = dict(eff)  # 浅拷贝：只修改value数值
                        e['value'] = eff.get('value', 0) + (disk_level - 1) * amber.get('amplification', 0)
                        ambers_effect_all.append(e)
                        if judge_eff(e):
                            amber_effect.append(e)
                            effect_condition.append(e.get('conditionType', -1))

        partial_flag = False
        for eff in chef.get('skill_effect', []):
            if eff.get('type') == 'OpenTime':
                time_buff += eff['value']
            if eff.get('condition') != 'Next' and judge_eff(eff):
                sum_skill_effect.append(eff)
                effect_condition.append(eff.get('conditionType', -1))
                if eff.get('condition') == 'Partial':
                    partial_flag = True

        # 上一位厨师的 Next 效果
        if last_chef:
            for eff in last_chef.get('skill_effect', []):
                if eff.get('condition') == 'Next' and judge_eff(eff):
                    sum_skill_effect.append(eff)
            for ue in last_chef.get('ultimate_effect', []):
                if ue['uid'] in self.ulti['Partial']['id'] or ue['uid'] in self.ulti['Self']['id']:
                    for eff in ue.get('ultimate_effect', []):
                        if eff.get('condition') == 'Next' and judge_eff(eff):
                            sum_skill_effect.append(eff)

        chef_on_site = self._get_chef_onsite(chef['id'])
        chef['MutiEquipmentSkill'] = 0

        # 修炼技能效果
        for ue in chef.get('ultimate_effect', []):
            if ue['uid'] in self.ulti['Self']['id'] or ue['uid'] in self.ulti['Partial']['id']:
                for eff in ue.get('ultimate_effect', []):
                    if eff.get('condition') == 'Next':
                        continue
                    if eff.get('type') == 'OpenTime':
                        time_buff += eff['value']
                    if eff.get('type') == 'MutiEquipmentSkill' and eff.get('cal') == 'Percent':
                        chef['MutiEquipmentSkill'] += eff['value']
                    if judge_eff(eff):
                        sum_skill_effect.append(eff)
                        effect_condition.append(eff.get('conditionType', -1))
                        if eff.get('condition') == 'Partial':
                            partial_flag = True

        chef['partial_flag'] = partial_flag
        chef['effect_condition'] = list(set(effect_condition))
        chef['equip_effect'] = equip_effect
        chef['condiment_effect'] = condiment_effect
        chef['sum_skill_effect'] = sum_skill_effect
        chef['amber_effect'] = amber_effect

        # 计算最终技法值
        for key in SKILL_TYPES:
            low_key = key.lower()
            value = self.ulti.get('All', 0)
            percent_value = 0
            value += self.ulti.get(key, 0)
            if 1 in chef.get('tags', []):
                value += self.ulti.get('Male', 0)
            if 2 in chef.get('tags', []):
                value += self.ulti.get('Female', 0)

            for eff in chef.get('skill_effect', []):
                if eff.get('type') == key:
                    if eff.get('cal') == 'Abs':
                        value += eff.get('value', 0)
                    elif eff.get('cal') == 'Percent':
                        percent_value += eff.get('value', 0)

            # 七侠 tag 加成
            for tag in chef.get('tags', []):
                qt = self.ud.qixia_skill_obj_tag.get(tag, {})
                value += qt.get(key, 0)

            # 修炼技能（Self, Partial）
            for ue in chef.get('ultimate_effect', []):
                if ue['uid'] in self.ulti['Self']['id'] or ue['uid'] in self.ulti['Partial']['id']:
                    for eff in ue.get('ultimate_effect', []):
                        if eff.get('type') == key and eff.get('condition') == 'Self':
                            if eff.get('cal') == 'Abs':
                                value += eff['value']
                            elif eff.get('cal') == 'Percent':
                                percent_value += eff['value']

            # 在场厨师的 Partial 技法加成
            for i in range(1, 4):
                cur = self.cal_chef[i]
                if cur:
                    for ue in cur.get('ultimate_effect', []):
                        if ue['uid'] in self.ulti['Partial']['id'] or ue['uid'] in self.ulti['Self']['id']:
                            for eff in ue.get('ultimate_effect', []):
                                if eff.get('type') == key and eff.get('condition') == 'Partial':
                                    ev = self._get_eff_value_by_cond_type(chef, eff)
                                    if eff.get('cal') == 'Abs':
                                        value += ev
                                    elif eff.get('cal') == 'Percent':
                                        percent_value += ev

            # 上一位的 Next 加成
            if last_chef:
                for ue in last_chef.get('ultimate_effect', []):
                    if ue['uid'] in self.ulti['Partial']['id'] or ue['uid'] in self.ulti['Self']['id']:
                        for eff in ue.get('ultimate_effect', []):
                            if eff.get('type') == key and eff.get('condition') == 'Next':
                                if eff.get('cal') == 'Abs':
                                    value += eff['value']
                                elif eff.get('cal') == 'Percent':
                                    percent_value += eff['value']

            # 不在场时自身 Partial 加成
            if chef_on_site == 0:
                for ue in chef.get('ultimate_effect', []):
                    if ue['uid'] in self.ulti['Partial']['id'] or ue['uid'] in self.ulti['Self']['id']:
                        for eff in ue.get('ultimate_effect', []):
                            if eff.get('type') == key and eff.get('condition') == 'Partial':
                                if eff.get('cal') == 'Abs':
                                    value += eff['value']
                                elif eff.get('cal') == 'Percent':
                                    percent_value += eff['value']

            # 厨具技法加成
            if eqp and not rule.get('DisableEquipSkillEffect'):
                for eff in eqp.get('effect', []):
                    if eff.get('type') == key:
                        muti = (100 + chef.get('MutiEquipmentSkill', 0)) / 100
                        if eff.get('cal') == 'Abs':
                            value += eff['value'] * muti
                        elif eff.get('cal') == 'Percent':
                            percent_value += eff['value'] * muti

            # 遗玉技法加成
            for eff in ambers_effect_all:
                if eff.get('type') == key:
                    if eff.get('cal') == 'Abs':
                        value += eff['value']
                    elif eff.get('cal') == 'Percent':
                        percent_value += eff['value']

            # 百分比加成
            value += math.ceil(((chef['skills'].get(low_key, 0) or 0) + value) * percent_value / 100)
            # 自定义规则额外加成
            if self.custom_rule and self.custom_rule.get('skill', {}).get('Skill'):
                value += int(self.custom_rule['skill']['Skill'].get(low_key, 0) or 0)

            skills_last[low_key] = (chef['skills'].get(low_key, 0) or 0) + value

        time_buff += equip_time_buff * (100 + chef.get('MutiEquipmentSkill', 0)) / 100
        chef['skills_last'] = skills_last
        chef['time_buff'] = time_buff
        return chef

    def get_grade(self, chf, rep):
        """计算品级"""
        min_grade = 5
        inf_detail = {}
        if self.rule.get('DisableCookbookRank'):
            min_grade = 1
        skills_last = chf.get('skills_last')
        if not skills_last:
            skills_last = {}
        for sk, req in rep.get('skills', {}).items():
            if req <= 0:
                continue
            val = skills_last.get(sk, 0)
            multi = int(val // req)
            if val < req:
                inf_detail[sk] = min(inf_detail.get(sk, 0), val - req)
            min_grade = min(multi, min_grade)
        return min_grade, inf_detail

    def cal_score(self, chf, rep, pos, position, remain=None):
        """计算厨师做某个菜的结果（对应 JS calScore）"""
        rule = self.rule
        chef = {}
        buff_rule = rep.get('buff_rule', 0)
        self.on_site_effect[position] = []

        buff_skill = 0
        buff_equip = 0
        buff_condiment = 0
        buff = rep.get('buff', 100)
        rep['basicPrice'] = 0
        chef_basicPrice = 0
        chef_basicPriceAbs = 0

        chef_tag_eff = self._chef_tag_effect
        if chef_tag_eff:
            tag_buff = 0
            for tag in chf.get('tags', []):
                tag_buff += (chef_tag_eff.get(tag, chef_tag_eff.get(str(tag), 0)) or 0) * 100
            buff_rule += tag_buff
            buff += tag_buff

        grade, inf_detail = self.get_grade(chf, rep)
        buff_grade = GRADE_BUFF.get(grade, 0)
        buff += buff_grade

        rep_rarity = rep.get('rarity')
        limit_buff = 0
        for eff in chf.get('amber_effect', []):
            if eff.get('type') == 'MaxEquipLimit' and eff.get('rarity') == rep_rarity:
                limit_buff += eff.get('value', 0)

        materialReduce = []
        chf_tags = chf.get('tags', [])
        for eff in chf.get('sum_skill_effect', []):
            eff_type = eff.get('type')
            if eff_type == 'MaterialReduce' and eff.get('condition') == 'Self':
                materialReduce.append({'list': eff.get('conditionValueList', []), 'value': eff.get('value', 0)})
            if eff_type == 'MaxEquipLimit' and eff.get('rarity') == rep_rarity and eff.get('condition') == 'Self':
                limit_buff += eff.get('value', 0)

        # 光环类食材消耗/份数加成
        ulti_self_id = self.ulti['Self']['id']
        ulti_partial_id = self.ulti['Partial']['id']
        for k in range(1, 4):
            i_chef = self.cal_chef[k]
            if i_chef:
                for ue in i_chef.get('ultimate_effect', []):
                    if ue['uid'] in ulti_self_id or ue['uid'] in ulti_partial_id:
                        for eff in ue.get('ultimate_effect', []):
                            eff_type = eff.get('type')
                            eff_cond = eff.get('condition')
                            if eff_type == 'MaterialReduce' and eff_cond == 'Partial':
                                materialReduce.append({'list': eff.get('conditionValueList', []), 'value': eff.get('value', 0)})
                            if (eff_type == 'MaxEquipLimit' and eff_cond == 'Partial'
                                    and check_tag(eff.get('conditionValueList', []), chf_tags)
                                    and eff.get('rarity') == rep_rarity):
                                limit_buff += eff.get('value', 0)

        chef['materialReduce'] = materialReduce
        chef['limitBuff'] = limit_buff
        limit_rule = 1 if self._disable_multi_cookbook else 500
        rep['limit'] = min(rep.get('limit_origin', 1), rep.get('limit_mater', 500), limit_rule)

        rep_key = f'chef_{pos}'
        chef['buff_rule'] = buff_rule
        chef['buff'] = buff
        chef['basicPrice'] = chef_basicPrice
        chef['basicPriceAbs'] = chef_basicPriceAbs
        chef['grade'] = grade
        chef['buff_grade'] = buff_grade
        rep[rep_key] = chef
        limit_mater = self._cal_mater_limit(remain, rep, rep_key)
        limit_chef = min(rep.get('limit_origin', 1) + limit_buff, limit_mater, limit_rule)
        chef['limit'] = limit_chef

        rep_cnt = limit_chef
        if str(pos) in ('1', '2', '3') and rep['id'] in self.rep_cnt_map:
            cnt_key = self.rep_cnt_map[rep['id']]
            if self.cal_rep_cnt.get(cnt_key) is not None:
                rep_cnt = self.cal_rep_cnt[cnt_key]

        # 心法效果
        for eff in chf.get('amber_effect', []):
            buff_skill += self._get_effect_buff(eff, rep, chf, rep_cnt, grade, position)
            eff_type = eff.get('type')
            value = 0
            if eff_type == 'BasicPrice':
                if not eff.get('conditionType'):
                    value = eff.get('value', 0)
                elif eff.get('conditionType') == 'PerRank':
                    value = self._get_basic_buff_by_rank(eff, chf, position)
            if eff.get('cal') == 'Percent':
                chef_basicPrice += value
            else:
                chef_basicPriceAbs += value

        # 厨师技能
        if not self._disable_chef_skill:
            for eff in chf.get('sum_skill_effect', []):
                eff_type = eff.get('type', '')
                if eff_type == 'BasicPrice':
                    value = 0
                    eff_ct = eff.get('conditionType')
                    if not eff_ct:
                        value = eff.get('value', 0)
                    elif eff_ct == 'PerRank':
                        value = self._get_basic_buff_by_rank(eff, chf, position)
                    else:
                        value = self._get_effect_buff(eff, rep, chf, rep_cnt, grade, position, 0, 1)
                    if eff.get('cal') == 'Percent':
                        chef_basicPrice += value
                    else:
                        chef_basicPriceAbs += value
                elif eff_type[:10] == 'BasicPrice' and eff.get('condition') == 'Self':
                    eff_new = dict(eff)
                    eff_new['type'] = eff_type[10:]
                    value = self._get_effect_buff(eff_new, rep, chf, rep_cnt, grade, position, 0)
                    if eff.get('cal') == 'Percent':
                        chef_basicPrice += value
                    else:
                        chef_basicPriceAbs += value
                else:
                    buff_skill += self._get_effect_buff(eff, rep, chf, rep_cnt, grade, position)

        # 厨具技能
        if not self._disable_equip_skill:
            for eff in chf.get('equip_effect', []):
                eff_type = eff.get('type', '')
                if eff_type == 'BasicPrice':
                    value = 0
                    eff_ct = eff.get('conditionType')
                    if not eff_ct:
                        value = eff.get('value', 0)
                    elif eff_ct == 'PerRank':
                        value = self._get_basic_buff_by_rank(eff, chf, position)
                    else:
                        value = self._get_effect_buff(eff, rep, chf, rep_cnt, grade, position, 1, 1)
                    if eff.get('cal') == 'Percent':
                        chef_basicPrice += value
                    else:
                        chef_basicPriceAbs += value
                elif eff_type[:10] == 'BasicPrice':
                    eff_new = dict(eff)
                    eff_new['type'] = eff_type[10:]
                    value = self._get_effect_buff(eff_new, rep, chf, rep_cnt, grade, position, 1)
                    if eff.get('cal') == 'Percent':
                        chef_basicPrice += value
                    else:
                        chef_basicPriceAbs += value
                else:
                    buff_equip += self._get_effect_buff(eff, rep, chf, rep_cnt, grade, position, 1)

        # 调料技能
        if not self._disable_condiment_skill:
            for eff in chf.get('condiment_effect', []):
                buff_condiment += self._get_effect_buff(eff, rep, chf, rep_cnt, grade, position)

        # 在场技能
        on_site = self.on_site_effect[1] + self.on_site_effect[2] + self.on_site_effect[3]
        for eff in on_site:
            eff_type = eff.get('type', '')
            if eff_type == 'BasicPrice':
                value = self._get_effect_buff(eff, rep, chf, rep_cnt, grade, position, 0, 1)
                if eff.get('cal') == 'Percent':
                    chef_basicPrice += value
                else:
                    chef_basicPriceAbs += value
            elif eff_type[:10] == 'BasicPrice':
                eff_new = dict(eff)
                eff_new['type'] = eff_type[10:]
                value = self._get_effect_buff(eff_new, rep, chf, rep_cnt, grade, position)
                if eff.get('cal') == 'Percent':
                    chef_basicPrice += value
                else:
                    chef_basicPriceAbs += value
            else:
                buff_skill += self._get_effect_buff(eff, rep, chf, rep_cnt, grade, position)

        buff += buff_equip + buff_skill + buff_condiment
        chef['buff_equip'] = buff_equip
        chef['buff_skill'] = buff_skill
        chef['buff_condiment'] = buff_condiment
        chef['buff'] = buff
        chef['basicPrice'] = chef_basicPrice
        chef['basicPriceAbs'] = chef_basicPriceAbs

        ex = rep.get('exPrice', 0) if self.default_ex else 0
        basic_buff = rep.get('basicPrice', 0) + chef_basicPrice
        price = math.floor((rep['price'] + ex + chef_basicPriceAbs) * (100 + basic_buff) / 100)
        chef['price_buff'] = math.ceil(price * buff * rep.get('buff_muti', 100) / 10000)
        chef['price_total'] = chef['price_buff'] * limit_chef

        chef['inf'] = inf_detail if grade < 1 else {}
        rep[rep_key] = dict(chef)  # 浅拷贝：chef局部变量之后不再修改
        rep[f'price_chef_{pos}'] = chef['price_total']
        return rep

    def _get_effect_buff(self, eff, rep, chf, rep_cnt, grade, position, eqp_flag=0, basic_flag=0):
        buff = 0
        ct = eff.get('conditionType')
        if not ct:
            if eff.get('condition') == 'Partial':
                e = dict(eff)  # 浅拷贝
                e.pop('condition', None)
                self.on_site_effect[position].append(e)
            else:
                buff += self._get_eff_wo_cond(eff, rep, chf, eqp_flag, basic_flag)
        elif ct == 'ExcessCookbookNum':
            if rep_cnt >= eff.get('conditionValue', 0):
                buff += self._get_eff_wo_cond(eff, rep, chf, eqp_flag, basic_flag)
        elif ct == 'FewerCookbookNum':
            if rep_cnt <= eff.get('conditionValue', 0):
                buff += self._get_eff_wo_cond(eff, rep, chf, eqp_flag, basic_flag)
        elif ct == 'PerRank':
            if eff.get('condition') == 'Partial':
                e = dict(eff)
                e.pop('conditionType', None)
                e.pop('condition', None)
                e['value'] = eff.get('value', 0) * self._get_per_rank_cnt(eff, chf, position)
                self.on_site_effect[position].append(e)
            else:
                buff += self._get_eff_wo_cond(eff, rep, chf, eqp_flag, basic_flag) * self._get_per_rank_cnt(eff, chf, position)
        elif ct == 'Rank':
            if eff.get('condition') == 'Partial':
                e = dict(eff)
                e.pop('condition', None)
                self.on_site_effect[position].append(e)
            elif grade >= eff.get('conditionValue', 0):
                buff += self._get_eff_wo_cond(eff, rep, chf, eqp_flag, basic_flag)
        elif ct == 'SameSkill':
            cnt = self._get_same_skill_flag(position)
            if cnt > 0:
                if eff.get('condition') == 'Partial':
                    e = dict(eff)
                    e.pop('conditionType', None)
                    e.pop('condition', None)
                    e['value'] = eff.get('value', 0) * cnt
                    self.on_site_effect[position].append(e)
                else:
                    buff += eff.get('value', 0) * cnt
        elif ct == 'CookbookRarity':
            if eff.get('condition') == 'Partial':
                e = dict(eff)  # 浅拷贝
                e.pop('condition', None)
                self.on_site_effect[position].append(e)
            elif rep.get('rarity') in (eff.get('conditionValueList') or []):
                buff += self._get_eff_wo_cond(eff, rep, chf, eqp_flag, basic_flag)
        elif ct == 'ChefTag':
            if eff.get('condition') == 'Partial':
                e = dict(eff)  # 浅拷贝
                e.pop('condition', None)
                self.on_site_effect[position].append(e)
            elif check_tag(eff.get('conditionValueList', []), chf.get('tags', [])):
                buff += self._get_eff_wo_cond(eff, rep, chf, eqp_flag, basic_flag)
        elif ct == 'CookbookTag':
            if eff.get('condition') == 'Partial':
                e = dict(eff)  # 浅拷贝
                e.pop('condition', None)
                self.on_site_effect[position].append(e)
            elif check_tag(eff.get('conditionValueList', []), rep.get('tags', [])):
                buff += self._get_eff_wo_cond(eff, rep, chf, eqp_flag, basic_flag)
        elif ct == 'PerSkill':
            if eff.get('condition') == 'Partial':
                e = dict(eff)
                e.pop('conditionType', None)
                e.pop('condition', None)
                e['value'] = eff.get('value', 0) * self._get_per_skill_cnt(eff)
                self.on_site_effect[position].append(e)
            else:
                buff += self._get_eff_wo_cond(eff, rep, chf, eqp_flag, basic_flag) * self._get_per_skill_cnt2(eff, position)
        return buff

    def _get_eff_wo_cond(self, eff, rep, chf, eqp_flag=0, basic_flag=0):
        """无前置条件时计算 buff（对应 getEffectBuffWithOutCondition）"""
        buff = 0
        t = eff.get('type', '')
        if t == 'Gold_Gain' and self._rule_id == 0:
            buff += self._get_sp_buff(eff, chf, eqp_flag)
        elif t[:3] == 'Use':
            suffix = t[3:]
            if suffix in SKILL_TYPES_SET:
                if rep.get('skills', {}).get(suffix.lower()):
                    buff += self._get_sp_buff(eff, chf, eqp_flag)
            elif suffix in MATERIAL_TYPES_SET:
                if suffix.lower() in rep.get('materials_type', []):
                    buff += self._get_sp_buff(eff, chf, eqp_flag)
            elif suffix in CONDIMENT_TYPES_SET:
                if rep.get('condiment') == suffix:
                    buff += self._get_sp_buff(eff, chf, eqp_flag)
            # 注意：UseAll 不在此处理，已在 _compute_ultimate 通过 PriceBuff_{rarity} 全局处理
        elif t == 'CookbookPrice':
            buff += self._get_sp_buff(eff, chf, eqp_flag)
        elif t == 'BasicPrice':
            if eff.get('conditionType') == 'PerRank':
                if rep['id'] not in self.rep_cnt_map:
                    rep['basicPrice'] = rep.get('basicPrice', 0) + self._get_sp_buff(eff, chf, eqp_flag)
            elif basic_flag == 1:
                buff += self._get_sp_buff(eff, chf, eqp_flag)
        return buff

    def _get_sp_buff(self, eff, chf, eqp_flag=0):
        """getSelfPartialBuff"""
        muti = (100 + (chf.get('MutiEquipmentSkill', 0) or 0)) / 100 if eqp_flag else 1
        b = eff.get('value', 0) * muti
        if eff.get('condition') == 'Partial' and chf.get('id') in self.on_site_chef:
            return 0
        return b

    def _handler_all_chefs(self, placed_only=False):
        """重算所有在场厨师的菜谱加成（对应 JS 中 partial_flag 时三个都重算）
        placed_only=True 时仅处理已放置的菜谱（用于快速评估）
        注意：不在此处调用 _sync_rep_cnt，避免贪心临时评估（set/clear）时
        污染其他菜谱的 cal_rep_cnt。调用方在永久变更后显式调用 _sync_rep_cnt。
        """
        if not placed_only:
            self._recipe_list_cache = {}
        for k in range(1, 4):
            if self.cal_chef[k]:
                self._handler_chef(k, placed_only=placed_only)

    def _handler_chef(self, slot, placed_only=False):
        """重算厨师对菜谱的加成
        placed_only=True 时仅处理已放置的菜谱（9道），大幅加速评估
        """
        chef = self.cal_chef_show.get(slot)
        if not chef or not chef.get('skills_last'):
            return
        remain = self._get_remain()
        if placed_only:
            for n in range(1, 4):
                r = self.cal_rep.get(f'{slot}-{n}')
                if r:
                    self.cal_score(chef, r, slot, slot, remain)
        else:
            for r in self.cal_reps_all:
                self.cal_score(chef, r, slot, slot, remain)

    def _sync_rep_cnt(self):
        """同步 cal_rep_cnt 份数上限（对应 JS getCalRepLimit）"""
        limit_rule = 1 if self._disable_multi_cookbook else 500
        has_mat_limit = bool(self.rule.get('MaterialsLimit'))
        for key, rep in self.cal_rep.items():
            if not rep:
                continue
            slot = int(key[0])
            chef_key = f'chef_{slot}'
            if not self.cal_chef[slot]:
                continue
            # 计算正确的份数上限
            limit_mater = 500
            if has_mat_limit:
                remain = self._get_remain(exclude_key=key)
                limit_mater = self._cal_mater_limit(remain, rep, chef_key)
            limit_origin = rep.get('limit_origin', LIMIT_BASE.get(rep.get('rarity', 1), 40))
            limit_buff = (rep.get(chef_key, {}) or {}).get('limitBuff', 0) or 0
            limit = min(limit_origin + limit_buff, limit_mater, limit_rule)
            # 仅向下修正（与 JS getCalRepLimit 行为一致）
            if self.cal_rep_cnt.get(key) is not None and self.cal_rep_cnt[key] > limit:
                self.cal_rep_cnt[key] = limit

    def _get_remain(self, exclude_key=None):
        if not self.rule.get('MaterialsLimit'):
            return None
        remain = dict(self.materials_all)  # 浅拷贝：flat dict {materialId: int}
        for k, rep in self.cal_rep.items():
            if rep and k != exclude_key and (self.cal_rep_cnt.get(k) or 0) > 0:
                chef_key = f'chef_{k[0]}'
                for m in rep.get('materials', []):
                    qty = m['quantity']
                    mr_list = rep.get(chef_key, {}).get('materialReduce', [])
                    for mr in mr_list:
                        if m['material'] in mr.get('list', []):
                            qty = max(qty - mr['value'], 1)
                    remain[m['material']] = remain.get(m['material'], 0) - qty * self.cal_rep_cnt[k]
        return remain

    def _cal_mater_limit(self, remain, rep, chef_key=None):
        if not self.rule.get('MaterialsLimit') or remain is None:
            return 500
        limit = 500
        for m in rep.get('materials', []):
            qty = m['quantity']
            if chef_key and rep.get(chef_key) and rep[chef_key].get('materialReduce'):
                for mr in rep[chef_key]['materialReduce']:
                    if m['material'] in mr.get('list', []):
                        qty = max(qty - mr['value'], 1)
            avail = remain.get(m['material'], 0)
            l = avail // qty if qty > 0 else 500
            limit = min(limit, l)
        return limit

    def _get_basic_buff_by_rank(self, eff, chf, position):
        buff = 0
        for key in range(1, 4):
            rep = self.cal_rep.get(f'{position}-{key}')
            if rep:
                g, _ = self.get_grade(chf, rep)
                if g >= eff.get('conditionValue', 0):
                    buff += eff.get('value', 0)
        return buff

    def _get_per_rank_cnt(self, eff, chf, position):
        cnt = 0
        for key in range(1, 4):
            rep = self.cal_rep.get(f'{position}-{key}')
            if rep:
                g, _ = self.get_grade(chf, rep)
                if g >= eff.get('conditionValue', 0):
                    cnt += 1
        return cnt

    def _get_per_skill_cnt(self, eff):
        sk_map = ['stirfry', 'fry', 'bake', 'steam', 'boil', 'knife']
        idx = eff.get('conditionValue', 1) - 1
        need = sk_map[idx] if 0 <= idx < len(sk_map) else 'stirfry'
        cnt = 0
        for s in range(1, 4):
            for n in range(1, 4):
                rep = self.cal_rep.get(f'{s}-{n}')
                if rep and rep.get('skills', {}).get(need):
                    cnt += 1
        return cnt

    def _get_per_skill_cnt2(self, eff, position):
        sk_map = ['stirfry', 'fry', 'bake', 'steam', 'boil', 'knife']
        idx = eff.get('conditionValue', 1) - 1
        need = sk_map[idx] if 0 <= idx < len(sk_map) else 'stirfry'
        cnt = 0
        for n in range(1, 4):
            rep = self.cal_rep.get(f'{position}-{n}')
            if rep and rep.get('skills', {}).get(need):
                cnt += 1
        return cnt

    def _get_same_skill_flag(self, position):
        result = 0
        for sk in SKILL_KEYS:
            cnt = sum(1 for n in range(1, 4) if self.cal_rep.get(f'{position}-{n}') and self.cal_rep[f'{position}-{n}'].get(sk))
            if cnt == 3:
                result += 1
        return result

    def _get_eff_value_by_cond_type(self, chef, eff):
        if eff.get('conditionType') == 'ChefTag':
            return eff.get('value', 0) if check_tag(eff.get('conditionValueList', []), chef.get('tags', [])) else 0
        return eff.get('value', 0)

    def _get_chef_onsite(self, chef_id):
        return 1 if chef_id in self.on_site_chef else 0

    def _get_last_chef(self, position):
        if position == 1:
            return None
        elif position == 2:
            return self.cal_chef[1]
        else:
            return self.cal_chef[2] or self.cal_chef[1]

    def begin_batch(self):
        """进入批量模式，延迟 _handler_all_chefs 直到 end_batch"""
        self._batch_mode = True

    def end_batch(self):
        """结束批量模式，统一执行 _handler_all_chefs 并修正份数
        需要迭代多轮：份数影响材料剩余 → 影响限制 → 又影响份数
        以及份数影响 ExcessCookbookNum/FewerCookbookNum 等条件效果 → 影响 buff → 影响分数
        最少 2 轮：on_site_effect 需要跨位置传播（chef 1→2→3→1）
        """
        self._batch_mode = False
        for i in range(6):
            old_cnts = dict(self.cal_rep_cnt)
            self._handler_all_chefs()
            self._sync_rep_cnt()
            if i >= 1 and self.cal_rep_cnt == old_cnts:
                break  # cal_rep_cnt 已收敛且 on_site 已传播

    def apply_plan(self, plan, fast=False):
        """一次性应用完整方案并返回总分
        plan: {slot: {'chef_id': id, 'recipe_ids': [id, id, id]}}
        fast=True: 厨师增量+菜谱批量+仅评估已放置菜谱（用于SA迭代）
        fast=False: 完整增量评估（精确，用于最终验证和贪心排序）
        """
        self.reset()
        if fast:
            # 1. 厨师增量设置（触发 handler，预计算 rep['chef_{slot}'] 排序数据）
            for slot in sorted(plan.keys()):
                self.set_chef(slot, plan[slot]['chef_id'])
            # 2. 菜谱批量设置（不触发 handler）
            self._batch_mode = True
            for slot in sorted(plan.keys()):
                for rn, rid in enumerate(plan[slot]['recipe_ids'], 1):
                    self.set_recipe(slot, rn, rid)
            self._batch_mode = False
            # 3. 仅对已放置菜谱做 handler 迭代收敛（最少2轮让 on_site_effect 传播）
            for i in range(6):
                old_cnts = dict(self.cal_rep_cnt)
                self._handler_all_chefs(placed_only=True)
                self._sync_rep_cnt()
                if i >= 1 and self.cal_rep_cnt == old_cnts:
                    break
        else:
            for slot in sorted(plan.keys()):
                self.set_chef(slot, plan[slot]['chef_id'])
                for rn, rid in enumerate(plan[slot]['recipe_ids'], 1):
                    self.set_recipe(slot, rn, rid)
            self._sync_rep_cnt()  # 精确模式最终同步份数
        return self.get_total_score()

    def setup_chefs(self, plan):
        """设置厨师（增量触发 handler），用于 SA 初始化
        之后可反复调用 eval_recipes_fast 只换菜谱
        """
        self.reset()
        for slot in sorted(plan.keys()):
            self.set_chef(slot, plan[slot]['chef_id'])
        # 保存厨师设置后的 on_site_effect 状态（full handler 的结果）
        self._saved_on_site_effect = {k: list(v) for k, v in self.on_site_effect.items()}

    def eval_recipes_fast(self, plan):
        """仅替换菜谱并快速评估（厨师已通过 setup_chefs 设置）
        只做 placed_only handler，不重跑全量 handler
        """
        if not hasattr(self, '_saved_on_site_effect'):
            raise RuntimeError("必须先调用 setup_chefs() 再调用 eval_recipes_fast()")
        # 恢复厨师设置后的 on_site_effect 状态
        self.on_site_effect = {k: list(v) for k, v in self._saved_on_site_effect.items()}
        self.rep_cnt_map = {}
        for s in range(1, 4):
            for n in range(1, 4):
                self.cal_rep[f'{s}-{n}'] = None
                self.cal_rep_cnt[f'{s}-{n}'] = None
        # 批量设置菜谱
        self._batch_mode = True
        for slot in sorted(plan.keys()):
            for rn, rid in enumerate(plan[slot]['recipe_ids'], 1):
                self.set_recipe(slot, rn, rid)
        self._batch_mode = False
        # placed_only handler 迭代收敛（最少2轮让 on_site_effect 跨位置传播）
        for i in range(6):
            old_cnts = dict(self.cal_rep_cnt)
            self._handler_all_chefs(placed_only=True)
            self._sync_rep_cnt()
            if i >= 1 and self.cal_rep_cnt == old_cnts:
                break
        return self.get_total_score()

    # ── 公共 API（供贪心求解器调用）──

    def get_recipe_list(self, slot, exclude_ids):
        """获取排好序的菜谱列表（带缓存，厨师不变时排序结果可复用）"""
        if not hasattr(self, '_recipe_list_cache'):
            self._recipe_list_cache = {}

        if slot not in self._recipe_list_cache:
            reps = []
            for r in self.cal_reps_all:
                if r.get('isf'):
                    continue
                if self.show_got and not self.ud.rep_got.get(r['id'], False):
                    continue
                reps.append(r)

            if self.cal_chef[slot]:
                key = f'price_chef_{slot}'
                reps.sort(key=lambda x: -(x.get(key, x.get('price_total', 0)) or 0))
            else:
                reps.sort(key=lambda x: -(x.get('price_total', 0) or 0))
            self._recipe_list_cache[slot] = [{'id': r['id'], 'name': r.get('name_show', r.get('name', ''))} for r in reps]

        cached = self._recipe_list_cache[slot]
        if exclude_ids:
            ex = exclude_ids if isinstance(exclude_ids, set) else set(exclude_ids)
            return [r for r in cached if r['id'] not in ex]
        return list(cached)

    def invalidate_recipe_cache(self):
        """清除菜谱排序缓存（厨师变更时需调用）"""
        self._recipe_list_cache = {}

    def get_recommended_chefs(self, slot, exclude_ids, limit=3):
        """获取推荐厨师列表（对应 getRecommendChef）"""
        results = []
        for c in self.cal_chefs_list:
            if c['id'] in exclude_ids:
                continue
            # 临时设为当前 chef 以计算
            chef = self.show_chef(dc(c), slot,
                                  eqp=self._load_chef_equip(c['id']),
                                  ambers=self._load_chef_ambers(c, slot))
            price = 0
            inf_sum = 0
            for i in range(1, 4):
                rep = self.cal_rep.get(f'{slot}-{i}')
                if rep:
                    cnt = self.cal_rep_cnt.get(f'{slot}-{i}') or rep.get('limit', 1)
                    result = self.cal_score(chef, dc(rep), 'chf', slot)
                    chef_data = result.get('chef_chf', {})
                    price += chef_data.get('price_buff', 0) * cnt
                    for sk, v in chef_data.get('inf', {}).items():
                        if v < 0:
                            inf_sum -= v

            if price <= 0:
                continue
            results.append({
                'id': c['id'], 'name': c['name'],
                'price_total': price, 'inf_sum': inf_sum,
                'isf': inf_sum > 0
            })

        results.sort(key=lambda x: (-x['price_total'], x['inf_sum']))
        return results[:limit]

    def get_total_score(self):
        """计算总得分（对应 calResultTotal）"""
        rule = self.rule
        price = 0
        for s in range(1, 4):
            for n in range(1, 4):
                key = f'{s}-{n}'
                rep = self.cal_rep.get(key)
                if not rep:
                    continue
                cnt = self.cal_rep_cnt.get(key) or 0
                if cnt <= 0:
                    continue

                chef_id = s
                if self.cal_chef[s] and rep.get(f'chef_{s}'):
                    cd = rep[f'chef_{s}']
                    if cd.get('grade', 0) < 1:
                        continue
                    p_buff = cd.get('price_buff', 0)
                else:
                    p_buff = rep.get('price_buff', 0)

                item_total = p_buff * cnt
                if rule.get('ScoreCoef') and isinstance(rule['ScoreCoef'], dict) and rule['ScoreCoef'].get('each'):
                    expr = rule['ScoreCoef']['each'].replace('this', str(item_total))
                    try:
                        item_total = eval(expr)
                    except:
                        pass
                price += item_total

        if rule.get('ScoreCoef') and isinstance(rule['ScoreCoef'], (int, float)):
            if price >= 0:
                price = math.floor(price / rule['ScoreCoef'])
            else:
                price = math.ceil(price / rule['ScoreCoef'])
        if rule.get('ScoreCoef') and isinstance(rule['ScoreCoef'], dict) and rule['ScoreCoef'].get('total'):
            expr = rule['ScoreCoef']['total'].replace('this', str(price))
            try:
                price = eval(expr)
            except:
                pass
        return int(price)

    def get_calculator_name(self):
        return self.rule.get('Title', '')


# ══════════════════════════════════════════════
#  求解器基类
# ══════════════════════════════════════════════

class BaseSolver:
    """求解器公共方法基类"""

    def __init__(self, calc, verbose=True):
        self.calc = calc
        self.verbose = verbose

    def log(self, msg):
        if self.verbose:
            print(msg)

    @staticmethod
    def _plan_to_compact(plan):
        """将 plan 转换为 apply_plan 的 compact 格式"""
        return {
            slot: {
                'chef_id': data['chef']['id'],
                'recipe_ids': [r['id'] for _, r in data['recipes']]
            }
            for slot, data in plan.items()
        }

    def _compact_to_plan(self, compact):
        """将 compact 格式转回完整 plan"""
        chef_map = {c['id']: c for c in self.calc._all_chefs_list}
        rep_map = {r['id']: r for r in self.calc.cal_reps_all}
        result = {}
        for slot, data in compact.items():
            chef = chef_map.get(data['chef_id'], {})
            recipes = []
            for rn, rid in enumerate(data['recipe_ids'], 1):
                r = rep_map.get(rid, {})
                recipes.append((rn, {'id': rid, 'name': r.get('name_show', r.get('name', ''))}))
            result[slot] = {'chef': {'id': chef.get('id'), 'name': chef.get('name', '?')}, 'recipes': recipes}
        return result

    @staticmethod
    def _copy_compact(c):
        return {s: {'chef_id': d['chef_id'], 'recipe_ids': list(d['recipe_ids'])}
                for s, d in c.items()}

    @staticmethod
    def _get_used_recipes(compact):
        used = set()
        for d in compact.values():
            used.update(d['recipe_ids'])
        return used

    def _get_rep_name(self, rid):
        return self.calc._rep_name_map.get(rid, str(rid))

    def _build_result_dict(self, plan, score):
        """构建结果字典（含每道菜谱的份数）"""
        result = {'plan': [], 'total_score': score,
                  'calculator_name': self.calc.get_calculator_name()}
        for slot in sorted(plan.keys()):
            sd = plan[slot]
            chef = sd['chef']
            recipes = sd['recipes']
            entry = {'chef': chef['name'], 'chef_id': chef['id'], 'recipes': []}
            for rn, recipe in recipes:
                cnt = self.calc.cal_rep_cnt.get(f'{slot}-{rn}', 0)
                entry['recipes'].append({'name': recipe['name'], 'id': recipe['id'], 'count': cnt})
            result['plan'].append(entry)
        return result

    def _print_plan(self, plan, title, score):
        """打印方案详情（含每道菜谱的份数）"""
        calculator_name = self.calc.get_calculator_name()
        print("\n" + "=" * 60)
        if calculator_name:
            print(f"本期计算器: {calculator_name}")
        print(f"{title}  总得分: {score}")
        print("=" * 60)
        for slot in sorted(plan.keys()):
            sd = plan[slot]
            print(f"\n厨师 {slot}: [{sd['chef']['name']}]")
            for rn, recipe in sd['recipes']:
                cnt = self.calc.cal_rep_cnt.get(f'{slot}-{rn}', '?')
                print(f"  菜谱{rn}: [{recipe['name']}]  份数: {cnt}")
            empty = MAX_REPS_PER_CHEF - len(sd['recipes'])
            if empty > 0:
                print(f"  {'--' * 10} ({empty} 个空位)")
        print(f"\n本期计算器: {calculator_name}")
        print(f"计算器真实总得分: {score}")
        print("=" * 60)


# ══════════════════════════════════════════════
#  贪心求解器
# ══════════════════════════════════════════════

class GreedySolver(BaseSolver):
    """贪心策略 + 局部搜索优化"""
    TOP_K = 8

    def __init__(self, calc, verbose=True):
        super().__init__(calc, verbose)
        self.plan = {}
        self.used_chefs = set()
        self.used_recipes = set()
        self.current_total = 0

    def find_best_new_slot(self):
        if len(self.plan) >= MAX_CHEFS:
            return (0, None, None)
        new_slot = len(self.plan) + 1
        recipe_list = self.calc.get_recipe_list(new_slot, self.used_recipes)[:self.TOP_K]
        if not recipe_list:
            return (0, None, None)

        candidates = []
        for recipe in recipe_list:
            self.calc.set_recipe(new_slot, 1, recipe['id'])
            chefs = self.calc.get_recommended_chefs(new_slot, self.used_chefs, limit=1)
            self.calc.clear_recipe(new_slot, 1)
            if chefs:
                candidates.append((recipe, chefs))
                self.log(f"    菜谱[{recipe['name']}] 推荐厨师: {', '.join(c['name'] for c in chefs)}")
            else:
                self.log(f"    菜谱[{recipe['name']}] 无可用厨师")

        if not candidates:
            return (0, None, None)

        best_score, best_recipe, best_chef = 0, None, None
        for recipe, chefs in candidates:
            for chef in chefs:
                self.calc.set_chef(new_slot, chef['id'])
                self.calc.set_recipe(new_slot, 1, recipe['id'])
                score = self.calc.get_total_score()
                self.log(f"    菜谱[{recipe['name']}] x 厨师[{chef['name']}] -> 总分={score}")
                self.calc.clear_chef(new_slot)
                if score > best_score:
                    best_score, best_recipe, best_chef = score, recipe, chef
        return (best_score, best_recipe, best_chef)

    def find_best_existing_slot(self):
        best_score, best_recipe, best_slot, best_rep_num = 0, None, None, None
        for slot, slot_data in self.plan.items():
            if len(slot_data['recipes']) >= MAX_REPS_PER_CHEF:
                continue
            rep_num = len(slot_data['recipes']) + 1
            recipe_list = self.calc.get_recipe_list(slot, self.used_recipes)[:self.TOP_K]
            for recipe in recipe_list:
                self.calc.set_recipe(slot, rep_num, recipe['id'])
                score = self.calc.get_total_score()
                self.log(f"    slot{slot} [{slot_data['chef']['name']}] + {recipe['name']} -> 总分={score}")
                self.calc.clear_recipe(slot, rep_num)
                if score > best_score:
                    best_score, best_recipe, best_slot, best_rep_num = score, recipe, slot, rep_num
        return (best_score, best_recipe, best_slot, best_rep_num)

    def commit_new_slot(self, chef, recipe):
        slot = len(self.plan) + 1
        self.calc.set_chef(slot, chef['id'])
        self.calc.set_recipe(slot, 1, recipe['id'])
        self.calc._sync_rep_cnt()  # 永久变更后同步份数
        self.plan[slot] = {'chef': chef, 'recipes': [(1, recipe)]}
        self.used_chefs.add(chef['id'])
        self.used_recipes.add(recipe['id'])
        self.current_total = self.calc.get_total_score()

    def commit_existing_slot(self, slot, rep_num, recipe):
        self.calc.set_recipe(slot, rep_num, recipe['id'])
        self.calc._sync_rep_cnt()  # 永久变更后同步份数
        self.plan[slot]['recipes'].append((rep_num, recipe))
        self.used_recipes.add(recipe['id'])
        self.current_total = self.calc.get_total_score()

    def run(self):
        self.calc.reset()
        self.plan = {}
        self.used_chefs = set()
        self.used_recipes = set()
        self.current_total = 0

        name = self.calc.get_calculator_name()
        self.log("\n" + "=" * 60)
        if name:
            self.log(f"本期计算器: {name}")
        self.log("开始贪心求解...")
        self.log("=" * 60)

        self.log("\n[初始化] 寻找得分最高的第一道菜+厨师...")
        s1, r1, c1 = self.find_best_new_slot()
        if r1 is None:
            self.log("无法找到任何可行组合，请检查已有厨师/菜谱数据。")
            return {}

        self.commit_new_slot(c1, r1)
        self.log(f"  => 厨师[{c1['name']}] + 菜谱[{r1['name']}]  总分={self.current_total}")

        iteration = 0
        while True:
            iteration += 1
            total_filled = sum(len(v['recipes']) for v in self.plan.values())
            if total_filled >= MAX_CHEFS * MAX_REPS_PER_CHEF:
                self.log("\n所有格子已填满，结束。")
                break

            self.log(f"\n[轮次{iteration}] 总分={self.current_total}，已用{total_filled}格")

            sA, rA, cA = self.find_best_new_slot()
            sB, rB, slotB, rnB = self.find_best_existing_slot()

            self.log(f"  选项A(新厨师): score={sA}  {rA['name'] if rA else 'N/A'} / {cA['name'] if cA else 'N/A'}")
            self.log(f"  选项B(现有厨师): score={sB}  {rB['name'] if rB else 'N/A'}")

            if len(self.plan) >= MAX_CHEFS:
                if sB <= 0:
                    self.log("  => 现有厨师无剩余可行菜谱，结束。")
                    break
                self.commit_existing_slot(slotB, rnB, rB)
                self.log(f"  => [选项B] {self.plan[slotB]['chef']['name']} + {rB['name']}  总分={self.current_total}")
            elif sA >= sB and sA > 0:
                self.commit_new_slot(cA, rA)
                self.log(f"  => [选项A] 新厨师[{cA['name']}] + {rA['name']}  总分={self.current_total}")
            elif sB > 0:
                self.commit_existing_slot(slotB, rnB, rB)
                self.log(f"  => [选项B] {self.plan[slotB]['chef']['name']} + {rB['name']}  总分={self.current_total}")
            else:
                self.log("  => 两个选项均无可行菜谱，结束。")
                break

        # 局部搜索优化（仅在有材料限制时启用）
        self._build_result(name, silent=True)  # 记录贪心结果
        self.local_search()
        return self._build_result(name)

    # ── 局部搜索优化 ──

    def local_search(self, max_rounds=100, replace_k=10):
        """局部搜索优化（轮次控制，确保跨平台结果一致）
        Phase 1: 单步替换 —— 用未使用的菜谱替换某个位置的菜谱（始终执行）
        Phase 2: 两步替换 —— 先替换一个菜谱释放材料，再替换另一个利用多出的材料
                  （仅在有材料限制时执行，解决单步看似亏损、两步组合收益的问题）
        使用 setup_chefs + eval_recipes_fast 加速评估（厨师不变，仅换菜谱）
        """
        import time as _time

        has_material_limit = bool(self.calc.rule.get('MaterialsLimit'))

        self.log(f"\n[局部搜索] 开始优化（上限 {max_rounds}轮，材料限制={'有' if has_material_limit else '无'}）...")
        start = _time.time()
        best_compact = self._plan_to_compact(self.plan)
        best_score = self.current_total
        greedy_score = best_score
        round_num = 0
        eval_count = 0

        # 厨师只设置一次（局部搜索不换厨师）
        self.calc.setup_chefs(best_compact)
        _eval = self.calc.eval_recipes_fast

        while round_num < max_rounds:
            round_num += 1
            improved = False
            slots = sorted(best_compact.keys())

            # ---- Phase 1: 单步替换 ----
            all_used = self._get_used_recipes(best_compact)
            _eval(best_compact)  # 应用当前方案以获取正确排序
            eval_count += 1

            for slot in slots:
                if improved:
                    break
                candidates = self.calc.get_recipe_list(slot, all_used)[:replace_k]
                rids = best_compact[slot]['recipe_ids']
                for r_idx in range(len(rids)):
                    if improved:
                        break
                    for new_rec in candidates:
                        cand = self._copy_compact(best_compact)
                        cand[slot]['recipe_ids'][r_idx] = new_rec['id']
                        score = _eval(cand)
                        eval_count += 1
                        if score > best_score:
                            old_name = self._get_rep_name(rids[r_idx])
                            self.log(f"  [轮{round_num}] 单步替换 slot{slot}[{old_name}] -> [{new_rec['name']}] -> {score} (+{score - best_score})")
                            best_score = score
                            best_compact = cand
                            improved = True
                            break

            if improved:
                continue  # 单步找到改进，继续下一轮

            if not has_material_limit:
                break  # 无材料限制时只做单步替换

            # ---- Phase 2: 两步替换 ----
            # 思路：替换菜谱A释放材料 -> 替换菜谱B利用释放的材料获得更多份数
            self.log(f"  [轮{round_num}] 单步无改进，尝试两步替换...")

            # 先收集每个 slot 的候选菜谱
            slot_candidates = {}
            _eval(best_compact)
            eval_count += 1
            for slot in slots:
                slot_candidates[slot] = self.calc.get_recipe_list(slot, all_used)[:replace_k]

            # 遍历所有 (pos1, cand1) 作为第一步替换
            found_two_step = False
            for s1 in slots:
                if found_two_step:
                    break
                rids1 = best_compact[s1]['recipe_ids']
                for r1_idx in range(len(rids1)):
                    if found_two_step:
                        break
                    for c1 in slot_candidates[s1]:
                        if found_two_step:
                            break
                        # 构造第一步替换后的方案
                        step1 = self._copy_compact(best_compact)
                        step1[s1]['recipe_ids'][r1_idx] = c1['id']

                        # 第一步替换后，获取新的可用菜谱
                        used_after_step1 = self._get_used_recipes(step1)

                        # 尝试所有 (pos2, cand2) 作为第二步
                        for s2 in slots:
                            if found_two_step:
                                break
                            rids2 = step1[s2]['recipe_ids']
                            for r2_idx in range(len(rids2)):
                                if found_two_step:
                                    break
                                if s1 == s2 and r1_idx == r2_idx:
                                    continue  # 跳过同一位置
                                # 第二步候选：用原始 slot 候选 + 排除第一步已用的
                                for c2 in slot_candidates[s2]:
                                    if c2['id'] in used_after_step1:
                                        continue
                                    step2 = self._copy_compact(step1)
                                    step2[s2]['recipe_ids'][r2_idx] = c2['id']
                                    score = _eval(step2)
                                    eval_count += 1
                                    if score > best_score:
                                        old1 = self._get_rep_name(rids1[r1_idx])
                                        old2 = self._get_rep_name(best_compact[s2]['recipe_ids'][r2_idx])
                                        self.log(f"  [轮{round_num}] 两步替换: slot{s1}[{old1}]->[{c1['name']}] + slot{s2}[{old2}]->[{c2['name']}] -> {score} (+{score - best_score})")
                                        best_score = score
                                        best_compact = step2
                                        found_two_step = True
                                        improved = True
                                        break

            if not improved:
                break

        elapsed = _time.time() - start
        # 应用最终最优方案（精确模式）
        self.calc.apply_plan(best_compact, fast=False)
        self.plan = self._compact_to_plan(best_compact)
        self.used_recipes = set()
        self.used_chefs = set()
        for d in best_compact.values():
            self.used_chefs.add(d['chef_id'])
            self.used_recipes.update(d['recipe_ids'])
        self.current_total = best_score

        delta = best_score - greedy_score
        self.log(f"  [局部搜索] 完成，{round_num}轮，{eval_count}次评估，耗时 {elapsed:.1f}秒")
        if delta > 0:
            self.log(f"  [局部搜索] 得分提升: {greedy_score} -> {best_score} (+{delta})")
        else:
            self.log(f"  [局部搜索] 贪心解已是局部最优")

    def _build_result(self, calculator_name, silent=False):
        result = self._build_result_dict(self.plan, self.current_total)
        if not silent:
            self._print_plan(self.plan, "最终方案", self.current_total)
        return result


# ══════════════════════════════════════════════
#  模拟退火求解器
# ══════════════════════════════════════════════

class SimulatedAnnealingSolver(BaseSolver):
    """模拟退火 + 贪心初始解"""

    def __init__(self, calc, verbose=True):
        super().__init__(calc, verbose)
        self.best_plan = None
        self.best_score = 0

    # ── 邻域操作类型常量 ──
    OP_CHEF_REPLACE = 'chef_replace'       # 替换厨师
    OP_CHEF_SWAP = 'chef_swap'             # 交换两个厨师位置
    OP_RECIPE_REPLACE = 'recipe_replace'   # 单菜替换
    OP_TWO_STEP = 'two_step'               # 双菜替换
    OP_RECIPE_SWAP = 'recipe_swap'         # 菜谱交换
    OP_FAR_REPLACE = 'far_replace'         # 远端替换

    @staticmethod
    def _new_op_stats():
        """创建操作统计字典"""
        return {op: {'triggered': 0, 'improved': 0}
                for op in ['chef_replace', 'chef_swap', 'recipe_replace',
                           'two_step', 'recipe_swap', 'far_replace']}

    @staticmethod
    def _compact_signature(compact):
        """生成方案签名（用于精英种群去重）"""
        parts = []
        for s in sorted(compact.keys()):
            d = compact[s]
            parts.append(f"{s}:{d['chef_id']}:{'|'.join(str(r) for r in d['recipe_ids'])}")
        return ';'.join(parts)

    def _greedy_fill_slot(self, compact, slot):
        """对指定 slot 贪心重填菜谱（不变更厨师）"""
        used = set()
        for s, d in compact.items():
            if s != slot:
                used.update(d['recipe_ids'])
        new_rids = []
        for _ in range(len(compact[slot]['recipe_ids'])):
            cands = self.calc.get_recipe_list(slot, used | set(new_rids))
            if cands:
                new_rids.append(cands[0]['id'])
            else:
                # 没有可用菜谱，保留原来的
                orig = compact[slot]['recipe_ids']
                new_rids.append(orig[len(new_rids)] if len(new_rids) < len(orig) else 0)
        compact[slot]['recipe_ids'] = new_rids

    def _get_neighbor(self, compact, temperature, initial_temp):
        """生成邻域解：随机扰动当前方案
        温度越高，扰动幅度越大（候选范围更广）
        返回 (neighbor, chefs_changed, op_type) 三元组

        概率分布（基于5组实验数据优化）：
          chef_replace  3%~10%  (改进率1.5%，单次贡献最大)
          chef_swap     3%~7%   (改进率0.2%，曾贡献+62k)
          recipe_replace 45%    (基础操作，靠量取胜)
          two_step       8%     (改进率0.03%，从20%大幅降低)
          recipe_swap   20%     (改进率0.7%，最稳定有效)
          far_replace   ~7-14%  (改进率0.2%，偶有跳出局部最优)
        已移除 greedy_reselect(0%改进率) 和 multi_rebuild(0%改进率)
        """
        neighbor = self._copy_compact(compact)
        slots = sorted(neighbor.keys())
        if not slots:
            return neighbor, False, self.OP_RECIPE_REPLACE

        used = self._get_used_recipes(compact)
        # 温度比例 0~1，控制探索广度
        t_ratio = min(temperature / initial_temp, 1.0)
        # 候选范围：高温时扩大到 top 30，低温时缩到 top 5
        cand_range = max(5, int(30 * t_ratio))

        op = random.random()

        # ---- 概率分布（基于实验数据优化）----
        # 厨师替换: 3%~10% (单次贡献最大)
        p_chef_replace = 0.03 + 0.07 * t_ratio
        # 厨师位置交换: 1%~2% (改进率极低，大幅降低)
        p_chef_swap = p_chef_replace + 0.01 + 0.01 * t_ratio
        # 单菜替换: 50% (核心操作，从45%提到50%)
        p_recipe_replace = p_chef_swap + 0.50
        # 双菜替换: 5% (从8%降到5%，改进率极低)
        p_two_step = p_recipe_replace + 0.05
        # 菜谱交换: 25% (从20%提到25%，改进率最高且稳定)
        p_recipe_swap = p_two_step + 0.25
        # 远端替换: 剩余 ~4-6% (兜底)
        # p_far_replace = 1.0

        if op < p_chef_replace:
            # 操作: 替换厨师
            slot = random.choice(slots)
            used_chefs = {d['chef_id'] for d in compact.values()}
            avail = [c for c in self.calc._all_chefs_list
                     if c['id'] not in used_chefs
                     and self.calc.ud.chef_got.get(c['id'], not self.calc.show_got)]
            if avail:
                pick = random.choice(avail[:max(10, int(30 * t_ratio))])
                neighbor[slot]['chef_id'] = pick['id']
                return neighbor, True, self.OP_CHEF_REPLACE
            # 无可用厨师时 fallthrough 到单菜替换
            op = p_chef_swap + 0.01

        if op < p_chef_swap:
            # 操作: 厨师位置交换（从 JS _climbChefSwap 借鉴，仅高温时触发）
            if len(slots) >= 2 and t_ratio > 0.3:
                s1, s2 = random.sample(slots, 2)
                neighbor[s1]['chef_id'], neighbor[s2]['chef_id'] = \
                    neighbor[s2]['chef_id'], neighbor[s1]['chef_id']
                return neighbor, True, self.OP_CHEF_SWAP

        if op < p_recipe_replace:
            # 操作: 随机替换一道菜（最常用的邻域）
            slot = random.choice(slots)
            rids = neighbor[slot]['recipe_ids']
            if rids:
                idx = random.randint(0, len(rids) - 1)
                old_id = rids[idx]
                exclude = used - {old_id}
                candidates = self.calc.get_recipe_list(slot, exclude)[:cand_range]
                if candidates:
                    pick = random.choice(candidates)
                    rids[idx] = pick['id']
            return neighbor, False, self.OP_RECIPE_REPLACE

        elif op < p_two_step:
            # 操作: 同时替换两道不同位置的菜（概率已降低）
            all_positions = [(s, i) for s in slots for i in range(len(neighbor[s]['recipe_ids']))]
            if len(all_positions) >= 2:
                p1, p2 = random.sample(all_positions, 2)
                old1 = neighbor[p1[0]]['recipe_ids'][p1[1]]
                exclude1 = used - {old1}
                cands1 = self.calc.get_recipe_list(p1[0], exclude1)[:cand_range]
                if cands1:
                    pick1 = random.choice(cands1)
                    neighbor[p1[0]]['recipe_ids'][p1[1]] = pick1['id']
                    new_used = self._get_used_recipes(neighbor)
                    old2 = neighbor[p2[0]]['recipe_ids'][p2[1]]
                    exclude2 = new_used - {old2}
                    cands2 = self.calc.get_recipe_list(p2[0], exclude2)[:cand_range]
                    if cands2:
                        pick2 = random.choice(cands2)
                        neighbor[p2[0]]['recipe_ids'][p2[1]] = pick2['id']
            return neighbor, False, self.OP_TWO_STEP

        elif op < p_recipe_swap:
            # 操作: 交换两个不同slot的菜谱位置（最高效操作，保证跨slot）
            if len(slots) >= 2:
                s1, s2 = random.sample(slots, 2)
                i1 = random.randint(0, len(neighbor[s1]['recipe_ids']) - 1)
                i2 = random.randint(0, len(neighbor[s2]['recipe_ids']) - 1)
                neighbor[s1]['recipe_ids'][i1], neighbor[s2]['recipe_ids'][i2] = \
                    neighbor[s2]['recipe_ids'][i2], neighbor[s1]['recipe_ids'][i1]
            return neighbor, False, self.OP_RECIPE_SWAP

        else:
            # 操作: 远端替换——从排名靠后的候选中选（跳出局部最优）
            slot = random.choice(slots)
            rids = neighbor[slot]['recipe_ids']
            if rids:
                idx = random.randint(0, len(rids) - 1)
                old_id = rids[idx]
                exclude = used - {old_id}
                candidates = self.calc.get_recipe_list(slot, exclude)
                far_start = min(10, len(candidates))
                far_end = min(50, len(candidates))
                if far_start < far_end:
                    pick = candidates[random.randint(far_start, far_end - 1)]
                    rids[idx] = pick['id']
            return neighbor, False, self.OP_FAR_REPLACE

    def run(self, initial_temp=800, final_temp=5, alpha=0.92,
            max_reheats=8, max_iter_per_temp=15, hill_climb_rounds=0):
        """运行模拟退火（轮次控制，确保跨平台结果一致）

        参数:
            initial_temp: 初始温度（控制初期接受差解的概率）
            final_temp: 终止温度
            alpha: 降温系数（0.92 → 更快降温更多轮加热+交叉）
            max_reheats: 最大重加热次数（控制搜索深度），默认8
            max_iter_per_temp: 每个温度下的迭代次数（15次更充分探索）
            hill_climb_rounds: 全面爬山精修轮数，0=不爬山，>0=SA后追加爬山
        """
        import time as _time

        self.log("\n" + "=" * 60)
        self.log("开始模拟退火求解（融合爬山+遗传算法增强版）...")
        self.log("=" * 60)

        # Step 1: 先用贪心算法获取初始解
        self.log("\n[步骤1] 贪心获取初始解...")
        greedy_solver = GreedySolver(self.calc, verbose=False)
        greedy_solver.run()
        initial_compact = greedy_solver._plan_to_compact(greedy_solver.plan)
        initial_score = greedy_solver.current_total
        greedy_score = initial_score
        self.log(f"  贪心初始解得分: {initial_score}")

        # Step 2: 模拟退火
        self.log(f"\n[步骤2] 模拟退火 (T={initial_temp}→{final_temp}, α={alpha}, 重加热={max_reheats})...")
        start = _time.time()

        current_compact = self._copy_compact(initial_compact)
        # 设置厨师一次（SA 只换菜谱不换厨师）
        self.calc.setup_chefs(current_compact)
        current_score = self.calc.eval_recipes_fast(current_compact)
        self.log(f"  快速评估基准分: {current_score}（精确分: {initial_score}）")

        # 快速模式做基准，SA 内部比较全部基于快速模式
        global_best_compact = self._copy_compact(current_compact)
        global_best_score = current_score
        # 精确验证：追踪真实最优（避免快速评估虚高）
        precise_best_compact = self._copy_compact(initial_compact)
        precise_best_score = initial_score
        # 记录当前厨师配置（用于检测厨师变更）
        current_chef_ids = {s: d['chef_id'] for s, d in current_compact.items()}

        # 操作统计
        op_stats = self._new_op_stats()

        # 精英种群（遗传算法元素）
        ELITE_POOL_SIZE = 5
        elite_pool = []  # [(score, compact, signature)]
        # 初始解加入精英种群
        init_sig = self._compact_signature(initial_compact)
        elite_pool.append((initial_score, self._copy_compact(initial_compact), init_sig))

        temperature = initial_temp
        total_iterations = 0
        accept_count = 0
        improve_count = 0
        precise_improve_count = 0
        reheat_count = 0
        chef_change_count = 0
        crossover_count = 0
        crossover_improve_count = 0

        def _try_insert_elite(score, compact):
            """尝试将解插入精英种群（去重）"""
            sig = self._compact_signature(compact)
            for _, _, s in elite_pool:
                if s == sig:
                    return  # 重复解
            elite_pool.append((score, self._copy_compact(compact), sig))
            elite_pool.sort(key=lambda x: -x[0])
            while len(elite_pool) > ELITE_POOL_SIZE:
                elite_pool.pop()

        def _crossover():
            """Slot级交叉：从两个精英解中各取部分slot组合成新解"""
            if len(elite_pool) < 2:
                return None
            # 锦标赛选择两个不同的父本
            idxs = random.sample(range(len(elite_pool)), 2)
            parentA = elite_pool[idxs[0]][1]
            parentB = elite_pool[idxs[1]][1]
            slotsA = sorted(parentA.keys())
            slotsB = sorted(parentB.keys())
            if slotsA != slotsB:
                return None
            # 随机选1-2个slot从A取，其余从B取
            n_from_a = random.randint(1, max(1, len(slotsA) - 1))
            slots_from_a = set(random.sample(slotsA, n_from_a))
            child = {}
            for s in slotsA:
                if s in slots_from_a:
                    child[s] = {'chef_id': parentA[s]['chef_id'],
                                'recipe_ids': list(parentA[s]['recipe_ids'])}
                else:
                    child[s] = {'chef_id': parentB[s]['chef_id'],
                                'recipe_ids': list(parentB[s]['recipe_ids'])}
            # 检查厨师冲突
            chef_ids = [d['chef_id'] for d in child.values()]
            if len(set(chef_ids)) < len(chef_ids):
                return None  # 冲突，放弃
            # 检查菜谱冲突（不同slot不应有相同菜谱）
            all_rids = []
            for d in child.values():
                all_rids.extend(d['recipe_ids'])
            if len(set(all_rids)) < len(all_rids):
                # 有菜谱冲突，尝试修复：对冲突的slot用贪心重填
                seen = set()
                conflict_slots = []
                for s in sorted(child.keys()):
                    for rid in child[s]['recipe_ids']:
                        if rid in seen:
                            conflict_slots.append(s)
                            break
                        seen.add(rid)
                for s in conflict_slots:
                    self._greedy_fill_slot(child, s)
            return child

        while reheat_count < max_reheats:

            for iteration in range(max_iter_per_temp):
                total_iterations += 1

                neighbor, chefs_changed, op_type = self._get_neighbor(
                    current_compact, temperature, initial_temp)
                op_stats[op_type]['triggered'] += 1

                if chefs_changed:
                    # 厨师变了，需要重新 setup_chefs（较慢）
                    self.calc.setup_chefs(neighbor)
                    neighbor_score = self.calc.eval_recipes_fast(neighbor)
                    chef_change_count += 1
                else:
                    neighbor_score = self.calc.eval_recipes_fast(neighbor)

                delta = neighbor_score - current_score
                accepted = False

                if delta > 0:
                    # 更好的解：直接接受
                    current_compact = self._copy_compact(neighbor)
                    current_score = neighbor_score
                    accept_count += 1
                    accepted = True

                    if chefs_changed:
                        current_chef_ids = {s: d['chef_id'] for s, d in current_compact.items()}

                    if current_score > global_best_score:
                        global_best_compact = self._copy_compact(current_compact)
                        global_best_score = current_score
                        improve_count += 1
                        op_stats[op_type]['improved'] += 1

                        # 精确验证每次快速评估改进（开销小，仅在改进时触发）
                        precise_score = self.calc.apply_plan(current_compact, fast=False)
                        if precise_score > precise_best_score:
                            precise_best_compact = self._copy_compact(current_compact)
                            precise_best_score = precise_score
                            precise_improve_count += 1
                            # 插入精英种群
                            _try_insert_elite(precise_score, current_compact)

                            # ★ 轻量爬山：在新精确最优上做快速局部搜索
                            if reheat_count < int(max_reheats * 0.85):
                                self.log(f"    → 触发轻量爬山 (精确={precise_score})...")
                                hc_compact, hc_score = self._hill_climb_light(
                                    self._copy_compact(current_compact), precise_score)
                                if hc_score > precise_best_score:
                                    precise_best_compact = self._copy_compact(hc_compact)
                                    precise_best_score = hc_score
                                    _try_insert_elite(hc_score, hc_compact)
                                    self.log(f"    → 轻量爬山提升: {precise_score} → {hc_score} (+{hc_score - precise_score})")

                        # 恢复快速评估状态
                        self.calc.setup_chefs(current_compact)

                        if self.verbose:
                            self.log(f"  [改进{improve_count}|{op_type}] 快速={global_best_score} 精确={precise_score} "
                                    f"(+{precise_score - greedy_score}), T={temperature:.1f}, 重加热={reheat_count}/{max_reheats}")
                else:
                    # 更差的解：以概率 exp(delta/T) 接受
                    acceptance_prob = math.exp(delta / temperature) if temperature > 0.01 else 0
                    if random.random() < acceptance_prob:
                        current_compact = self._copy_compact(neighbor)
                        current_score = neighbor_score
                        accept_count += 1
                        accepted = True
                        if chefs_changed:
                            current_chef_ids = {s: d['chef_id'] for s, d in current_compact.items()}

                # 如果厨师变了但被拒绝，恢复之前的厨师配置
                if chefs_changed and not accepted:
                    self.calc.setup_chefs(current_compact)

            # 降温
            temperature *= alpha

            # 温度过低时重新加热
            if temperature <= final_temp:
                reheat_count += 1
                temperature = initial_temp

                # 遗传算法交叉：50% 概率从精英种群交叉产生新起点
                use_crossover = len(elite_pool) >= 2 and random.random() < 0.5
                if use_crossover:
                    child = _crossover()
                    if child:
                        crossover_count += 1
                        self.calc.setup_chefs(child)
                        child_score = self.calc.eval_recipes_fast(child)
                        # 交叉解作为重启起点
                        current_compact = self._copy_compact(child)
                        current_score = child_score
                        current_chef_ids = {s: d['chef_id'] for s, d in current_compact.items()}
                        if current_score > global_best_score:
                            global_best_score = current_score
                            global_best_compact = self._copy_compact(current_compact)
                            crossover_improve_count += 1
                        # 也验证精确分
                        precise_score = self.calc.apply_plan(child, fast=False)
                        if precise_score > precise_best_score:
                            precise_best_compact = self._copy_compact(child)
                            precise_best_score = precise_score
                            _try_insert_elite(precise_score, child)
                            crossover_improve_count += 1
                        self.calc.setup_chefs(current_compact)
                        continue  # 跳过下面的普通重启

                # 普通重启：从精确最优重新出发
                current_compact = self._copy_compact(precise_best_compact)
                self.calc.setup_chefs(current_compact)
                current_score = self.calc.eval_recipes_fast(current_compact)
                current_chef_ids = {s: d['chef_id'] for s, d in current_compact.items()}
                # 同步快速最优
                if current_score > global_best_score:
                    global_best_score = current_score
                    global_best_compact = self._copy_compact(current_compact)

        # Step 3: 取精确最优解
        elapsed = _time.time() - start
        # 同时验证快速评估最优（可能碰巧精确分也高）
        fast_best_precise = self.calc.apply_plan(global_best_compact, fast=False)
        if fast_best_precise > precise_best_score:
            precise_best_compact = self._copy_compact(global_best_compact)
            precise_best_score = fast_best_precise

        # 验证精英种群中的所有解
        for pool_score, pool_compact, _ in elite_pool:
            pool_precise = self.calc.apply_plan(pool_compact, fast=False)
            if pool_precise > precise_best_score:
                precise_best_compact = self._copy_compact(pool_compact)
                precise_best_score = pool_precise

        self.best_plan = self._compact_to_plan(precise_best_compact)
        self.best_score = precise_best_score

        self.log(f"\n[模拟退火] 完成，共 {total_iterations} 次迭代，{accept_count} 次接受，"
                f"{improve_count} 次快速改进，{precise_improve_count} 次精确改进，"
                f"{reheat_count} 轮加热，{chef_change_count} 次换厨师，耗时 {elapsed:.1f}秒")
        self.log(f"[遗传算法] 精英种群 {len(elite_pool)} 个，交叉 {crossover_count} 次，"
                f"交叉改进 {crossover_improve_count} 次")

        # 打印各操作类型统计
        self.log("\n[邻域操作统计]")
        self.log(f"  {'操作类型':<20s} {'触发次数':>8s} {'改进次数':>8s} {'改进率':>8s}")
        self.log(f"  {'-' * 48}")
        for op_name in ['chef_replace', 'chef_swap', 'recipe_replace', 'two_step',
                        'recipe_swap', 'far_replace']:
            stats = op_stats[op_name]
            triggered = stats['triggered']
            improved = stats['improved']
            rate = f"{improved / triggered * 100:.1f}%" if triggered > 0 else "-"
            self.log(f"  {op_name:<20s} {triggered:>8d} {improved:>8d} {rate:>8s}")

        if precise_best_score > greedy_score:
            self.log(f"[模拟退火] 得分提升: {greedy_score} -> {precise_best_score} (+{precise_best_score - greedy_score})")
        elif precise_best_score == greedy_score:
            self.log(f"[模拟退火] 未找到更优解（精确得分: {precise_best_score}）")
        else:
            self.log(f"[模拟退火] 精确最优 {precise_best_score} 不如贪心 {greedy_score}，保留贪心解")
            precise_best_compact = self._copy_compact(initial_compact)
            precise_best_score = self.calc.apply_plan(initial_compact, fast=False)

        # Step 4: 全面爬山精修——系统性搜索局部最优（含厨师替换/交换）
        if hill_climb_rounds > 0:
            self.log(f"\n[步骤3] 全面爬山精修（上限 {hill_climb_rounds}轮）...")
            polished_compact, polished_score = self._hill_climb_full(
                precise_best_compact, precise_best_score, max_rounds=hill_climb_rounds)
        else:
            polished_compact = precise_best_compact
            polished_score = precise_best_score

        self.best_plan = self._compact_to_plan(polished_compact)
        self.best_score = polished_score

        return self._build_result()

    # ── 爬山法（替代局部打磨，全面系统性搜索） ──

    def _hc_recipe_replace(self, compact, score, top_k=15):
        """爬山-菜谱替换：先快速评估粗筛top5，再精确验证（加速3-5x）"""
        improved = False
        FAST_TOP = min(top_k, 30)  # 快速评估的候选范围
        PRECISE_TOP = 5            # 精确验证的候选数
        for slot in sorted(compact.keys()):
            for idx in range(len(compact[slot]['recipe_ids'])):
                rep_num = idx + 1
                current_rid = compact[slot]['recipe_ids'][idx]
                used = self._get_used_recipes(compact) - {current_rid}

                # Phase 1: 快速评估粗筛
                self.calc.setup_chefs(compact)
                candidates = self.calc.get_recipe_list(slot, used)[:FAST_TOP]
                fast_scores = []
                for cand in candidates:
                    if cand['id'] == current_rid:
                        continue
                    test = self._copy_compact(compact)
                    test[slot]['recipe_ids'][idx] = cand['id']
                    fs = self.calc.eval_recipes_fast(test)
                    fast_scores.append((fs, cand))
                # 取快速评估 top PRECISE_TOP 候选
                fast_scores.sort(key=lambda x: -x[0])
                top_cands = [c for _, c in fast_scores[:PRECISE_TOP]]

                # Phase 2: 精确验证 top 候选
                best_rid = current_rid
                best_score = score
                for cand in top_cands:
                    test = self._copy_compact(compact)
                    test[slot]['recipe_ids'][idx] = cand['id']
                    ns = self.calc.apply_plan(test, fast=False)
                    if ns > best_score:
                        best_score = ns
                        best_rid = cand['id']

                if best_rid != current_rid:
                    compact[slot]['recipe_ids'][idx] = best_rid
                    score = best_score
                    improved = True
                    self.log(f"    菜谱替换 slot{slot}-{rep_num}: "
                             f"[{self._get_rep_name(current_rid)}]→[{self._get_rep_name(best_rid)}] "
                             f"分={score}")
                    # 应用最优方案以保持计算器状态一致
                    self.calc.apply_plan(compact, fast=False)
        return compact, score, improved

    def _hc_recipe_swap(self, compact, score):
        """爬山-菜谱交换：跨slot交换菜谱（快速评估）"""
        improved = False
        self.calc.setup_chefs(compact)
        slots = sorted(compact.keys())
        for i in range(len(slots)):
            for j in range(i + 1, len(slots)):
                s1, s2 = slots[i], slots[j]
                for idx1 in range(len(compact[s1]['recipe_ids'])):
                    for idx2 in range(len(compact[s2]['recipe_ids'])):
                        rid1 = compact[s1]['recipe_ids'][idx1]
                        rid2 = compact[s2]['recipe_ids'][idx2]
                        if rid1 == rid2:
                            continue
                        compact[s1]['recipe_ids'][idx1] = rid2
                        compact[s2]['recipe_ids'][idx2] = rid1
                        ns = self.calc.eval_recipes_fast(compact)
                        if ns > score:
                            score = ns
                            improved = True
                            self.log(f"    菜谱交换 slot{s1}-{idx1+1}↔slot{s2}-{idx2+1} 分={score}")
                        else:
                            compact[s1]['recipe_ids'][idx1] = rid1
                            compact[s2]['recipe_ids'][idx2] = rid2
        return compact, score, improved

    def _hc_chef_replace(self, compact, score, top_k=15):
        """爬山-厨师替换：Plan A 保留菜谱 / Plan B 换厨师+重选菜谱"""
        improved = False
        used_chefs = {d['chef_id'] for d in compact.values()}
        for slot in sorted(compact.keys()):
            cur_id = compact[slot]['chef_id']
            avail = [c for c in self.calc.cal_chefs_list
                     if c['id'] not in used_chefs and c['id'] != cur_id]
            avail.sort(key=lambda x: -x.get('rarity', 1))
            avail = avail[:top_k]
            for cand in avail:
                # Plan A: 保留菜谱换厨师
                test_a = self._copy_compact(compact)
                test_a[slot]['chef_id'] = cand['id']
                score_a = self.calc.apply_plan(test_a, fast=False)
                # Plan B: 换厨师 + 重选该位置菜谱
                test_b = self._copy_compact(compact)
                test_b[slot]['chef_id'] = cand['id']
                test_b[slot]['recipe_ids'] = []
                other_rids = set()
                for s, d in test_b.items():
                    if s != slot:
                        other_rids.update(d['recipe_ids'])
                self.calc.reset()
                for s in sorted(test_b.keys()):
                    self.calc.set_chef(s, test_b[s]['chef_id'])
                    for rn, rid in enumerate(test_b[s]['recipe_ids'], 1):
                        self.calc.set_recipe(s, rn, rid)
                new_rids = []
                for rn in range(1, MAX_REPS_PER_CHEF + 1):
                    exclude = other_rids | set(new_rids)
                    cands_b = self.calc.get_recipe_list(slot, exclude)
                    if cands_b:
                        self.calc.set_recipe(slot, rn, cands_b[0]['id'])
                        self.calc._sync_rep_cnt()
                        new_rids.append(cands_b[0]['id'])
                test_b[slot]['recipe_ids'] = new_rids
                score_b = self.calc.apply_plan(test_b, fast=False)
                best_alt = max(score_a, score_b)
                if best_alt > score:
                    old_name = next((c['name'] for c in self.calc._all_chefs_list
                                     if c['id'] == cur_id), '?')
                    which = 'A(留菜)' if score_a >= score_b else 'B(重选菜)'
                    self.log(f"    厨师替换 slot{slot}: [{old_name}]→[{cand['name']}] "
                             f"方案{which} {score}→{best_alt} (+{best_alt-score})")
                    compact = self._copy_compact(test_a if score_a >= score_b else test_b)
                    score = best_alt
                    used_chefs = {d['chef_id'] for d in compact.values()}
                    improved = True
                    break  # 厨师变了，重新来过
        return compact, score, improved

    def _hc_chef_swap(self, compact, score):
        """爬山-厨师位置交换：交换两个slot的厨师（连同菜谱）"""
        improved = False
        slots = sorted(compact.keys())
        for i in range(len(slots)):
            for j in range(i + 1, len(slots)):
                s1, s2 = slots[i], slots[j]
                test = self._copy_compact(compact)
                test[s1], test[s2] = test[s2], test[s1]
                ns = self.calc.apply_plan(test, fast=False)
                if ns > score:
                    self.log(f"    厨师交换 slot{s1}↔slot{s2} {score}→{ns} (+{ns-score})")
                    compact = self._copy_compact(test)
                    score = ns
                    improved = True
        return compact, score, improved

    def _hc_recipe_reselect(self, compact, score):
        """爬山-菜谱重选：清空某位置全部菜谱重新贪心填充"""
        improved = False
        for slot in sorted(compact.keys()):
            test = self._copy_compact(compact)
            test[slot]['recipe_ids'] = []
            other_rids = set()
            for s, d in test.items():
                if s != slot:
                    other_rids.update(d['recipe_ids'])
            self.calc.reset()
            for s in sorted(test.keys()):
                self.calc.set_chef(s, test[s]['chef_id'])
                for rn, rid in enumerate(test[s]['recipe_ids'], 1):
                    self.calc.set_recipe(s, rn, rid)
            new_rids = []
            for rn in range(1, MAX_REPS_PER_CHEF + 1):
                exclude = other_rids | set(new_rids)
                cands = self.calc.get_recipe_list(slot, exclude)
                if cands:
                    self.calc.set_recipe(slot, rn, cands[0]['id'])
                    self.calc._sync_rep_cnt()
                    new_rids.append(cands[0]['id'])
            test[slot]['recipe_ids'] = new_rids
            ns = self.calc.apply_plan(test, fast=False)
            if ns > score:
                self.log(f"    菜谱重选 slot{slot}: {score}→{ns} (+{ns-score})")
                compact = self._copy_compact(test)
                score = ns
                improved = True
        return compact, score, improved

    def _hill_climb_light(self, compact, score):
        """轻量爬山：快速菜谱替换+交换（SA途中调用，开销极小）

        全程使用 setup_chefs + eval_recipes_fast 加速（约为精确评估的1/10耗时）。
        不换厨师，保持 SA 状态兼容。
        """
        self.calc.setup_chefs(compact)
        _eval = self.calc.eval_recipes_fast
        # 用快速分数作为爬山基准
        fast_score = _eval(compact)

        # 1) 快速菜谱替换（top_k=3，开销极小）
        for slot in sorted(compact.keys()):
            rids = compact[slot]['recipe_ids']
            for idx in range(len(rids)):
                old_rid = rids[idx]
                used = self._get_used_recipes(compact) - {old_rid}
                candidates = self.calc.get_recipe_list(slot, used)[:3]
                for cand in candidates:
                    if cand['id'] == old_rid:
                        continue
                    compact[slot]['recipe_ids'][idx] = cand['id']
                    ns = _eval(compact)
                    if ns > fast_score:
                        fast_score = ns
                        old_rid = cand['id']
                    else:
                        compact[slot]['recipe_ids'][idx] = old_rid

        # 2) 快速菜谱交换
        slots = sorted(compact.keys())
        for i in range(len(slots)):
            for j in range(i + 1, len(slots)):
                s1, s2 = slots[i], slots[j]
                for idx1 in range(len(compact[s1]['recipe_ids'])):
                    for idx2 in range(len(compact[s2]['recipe_ids'])):
                        rid1 = compact[s1]['recipe_ids'][idx1]
                        rid2 = compact[s2]['recipe_ids'][idx2]
                        if rid1 == rid2:
                            continue
                        compact[s1]['recipe_ids'][idx1] = rid2
                        compact[s2]['recipe_ids'][idx2] = rid1
                        ns = _eval(compact)
                        if ns > fast_score:
                            fast_score = ns
                        else:
                            compact[s1]['recipe_ids'][idx1] = rid1
                            compact[s2]['recipe_ids'][idx2] = rid2

        # 精确校准
        score = self.calc.apply_plan(compact, fast=False)
        return compact, score

    def _hill_climb_full(self, compact, score, max_rounds=8):
        """全面爬山：多策略多轮迭代直到收敛（SA结束后调用）

        策略顺序：菜谱替换→菜谱交换→厨师替换(PlanA/B)→厨师交换→菜谱重选
        每轮依次尝试所有策略，有任一改进则继续下一轮，全无改进则收敛停止。
        """
        import time as _time
        start = _time.time()
        score = self.calc.apply_plan(compact, fast=False)

        for round_idx in range(max_rounds):
            round_improved = False
            labels = []

            # 1) 菜谱替换
            compact, score, imp = self._hc_recipe_replace(compact, score)
            if imp:
                round_improved = True
                labels.append('菜谱替换')

            # 2) 菜谱交换
            compact, score, imp = self._hc_recipe_swap(compact, score)
            if imp:
                round_improved = True
                labels.append('菜谱交换')
                # 交换后精确校准
                score = self.calc.apply_plan(compact, fast=False)

            # 3) 厨师替换 (Plan A + Plan B)
            compact, score, imp = self._hc_chef_replace(compact, score)
            if imp:
                round_improved = True
                labels.append('厨师替换')

            # 4) 厨师位置交换
            compact, score, imp = self._hc_chef_swap(compact, score)
            if imp:
                round_improved = True
                labels.append('厨师交换')

            # 5) 菜谱重选
            compact, score, imp = self._hc_recipe_reselect(compact, score)
            if imp:
                round_improved = True
                labels.append('菜谱重选')

            elapsed = _time.time() - start
            self.log(f"  [爬山R{round_idx+1}] {'+'.join(labels) if labels else '无改进'} "
                     f"分={score} ({elapsed:.1f}s)")
            if not round_improved:
                break

        # 最终精确校准
        score = self.calc.apply_plan(compact, fast=False)
        return compact, score

    def _hill_climb_fast(self, compact, score, max_rounds=8):
        """快速爬山：仅菜谱操作（跳过耗时的厨师替换），用于每轮SA后快速精修

        策略顺序：菜谱替换→菜谱交换→菜谱重选
        比 _hill_climb_full 快 2-3 倍（省掉厨师遍历）。
        """
        import time as _time
        start = _time.time()
        score = self.calc.apply_plan(compact, fast=False)

        for round_idx in range(max_rounds):
            round_improved = False
            labels = []

            # 1) 菜谱替换
            compact, score, imp = self._hc_recipe_replace(compact, score)
            if imp:
                round_improved = True
                labels.append('菜谱替换')

            # 2) 菜谱交换
            compact, score, imp = self._hc_recipe_swap(compact, score)
            if imp:
                round_improved = True
                labels.append('菜谱交换')
                score = self.calc.apply_plan(compact, fast=False)

            # 3) 菜谱重选
            compact, score, imp = self._hc_recipe_reselect(compact, score)
            if imp:
                round_improved = True
                labels.append('菜谱重选')

            elapsed = _time.time() - start
            self.log(f"  [快速爬山R{round_idx+1}] {'+'.join(labels) if labels else '无改进'} "
                     f"分={score} ({elapsed:.1f}s)")
            if not round_improved:
                break

        score = self.calc.apply_plan(compact, fast=False)
        return compact, score

    def _build_result(self):
        result = self._build_result_dict(self.best_plan, self.best_score)
        self._print_plan(self.best_plan, "模拟退火最终方案", self.best_score)
        return result


# ══════════════════════════════════════════════
#  主入口
# ══════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="爆炒江湖 厨神贪心求解器（纯Python版，无需浏览器）")
    parser.add_argument("--user-id", type=str, default="",
                        help="用户ID，用于隔离不同用户的缓存数据（推荐由调用方自动传入）")
    parser.add_argument("--code", type=str, default=USER_CODE, help="官方校验码（首次使用必填，之后自动缓存）")
    parser.add_argument("--force-import", action="store_true", help="强制重新导入校验码，忽略缓存")
    parser.add_argument("--optimizer", type=str, default="hybrid",
                        choices=["hybrid", "simulated_annealing", "local_search"],
                        help="优化策略：hybrid=SA+爬山融合（默认推荐），"
                             "simulated_annealing=纯模拟退火，local_search=贪心+局部搜索")
    parser.add_argument("--sa-reheats", type=int, default=24,
                        help="SA重加热次数（控制搜索深度，跨平台确定性），默认12（hybrid模式自动分配）")
    parser.add_argument("--sa-temp", type=float, default=800,
                        help="模拟退火初始温度，默认800")
    args = parser.parse_args()

    code = args.code.strip() if args.code else ""
    user_id = args.user_id.strip() if args.user_id else ""

    print("=" * 60)
    print("  爆炒江湖 厨神贪心求解器（纯 Python 版）")
    print("  无需浏览器，内存占用 < 50MB")
    if user_id:
        print(f"  用户ID: {user_id}")
    print("=" * 60)

    # 1. 加载游戏数据
    print("\n[1/4] 加载游戏数据...")
    raw_data = load_game_data()
    print(f"  菜谱: {len(raw_data['recipes'])}  厨师: {len(raw_data['chefs'])}  "
          f"厨具: {len(raw_data['equips'])}  遗玉: {len(raw_data['ambers'])}")

    # 2. 获取规则
    print("\n[2/4] 获取厨神规则...")
    food_god_rules = fetch_rules()
    if food_god_rules:
        print(f"  当前规则: {food_god_rules[0].get('Title', '未知')}")
    else:
        print("  未获取到厨神规则，使用正常营业模式")

    # 3. 处理数据
    print("\n[3/4] 处理数据...")
    gd = GameData(raw_data, food_god_rules)
    print(f"  处理完成: {len(gd.recipes)} 菜谱, {len(gd.chefs)} 厨师, {len(gd.rules)} 规则")

    # 4. 加载个人数据
    print("\n[4/4] 加载个人数据...")
    ud = UserData()
    cached = load_user_cache(user_id)

    if args.force_import or code:
        if not code:
            print("  无缓存数据且未提供校验码，请通过 --code 参数传入。")
            sys.exit(1)
        print(f"  {'强制重新' if args.force_import else '首次'}导入校验码数据...")
        has_user_data = True
        try:
            api_data = fetch_user_data_from_api(code)
            ud.import_from_api(api_data, gd)
            save_user_cache(ud.to_cache(), user_id)
            print("  导入成功！")
        except Exception as e:
            print(f"  导入失败: {e}")
            sys.exit(1)
    elif cached:
        has_user_data = True
        print("  检测到本地缓存数据，直接使用。")
        print("  如需强制重新导入，请加 --force-import 参数。")
        ud.import_from_cache(cached, gd)
    else:
        print("  未提供校验码且无缓存数据，将使用全量数据（不限于已有）。")
        has_user_data = False

    has_got = sum(1 for v in ud.rep_got.values() if v)
    chef_got = sum(1 for v in ud.chef_got.values() if v)
    print(f"  已有菜谱: {has_got}, 已有厨师: {chef_got}")

    # 5. 初始化计算器
    print("\n初始化计算器...")
    calc = Calculator(gd, ud, show_got=has_user_data)
    print(f"  规则: {calc.get_calculator_name()}")
    print(f"  可用厨师: {len(calc.cal_chefs_list)}, 可用菜谱: {len(calc.cal_reps_all)}")

    # 6. 运行求解器
    if args.optimizer == "hybrid":
        _run_hybrid(calc, args)
    elif args.optimizer == "simulated_annealing":
        sa_solver = SimulatedAnnealingSolver(calc, verbose=True)
        sa_solver.run(initial_temp=args.sa_temp, max_reheats=args.sa_reheats)
    else:
        solver = GreedySolver(calc, verbose=True)
        solver.run()


def _run_hybrid(calc, args):
    """多轮重启 hybrid 策略：多轮独立 SA+全面爬山，取全局最优

    每轮独立跑 SA + 全面爬山，多轮独立随机路径确保稳定性。
    """
    import time as _time

    total_reheats = args.sa_reheats
    HC_ROUNDS = 5  # 每轮爬山轮数

    # 确定轮数和每轮重加热次数（每轮至少6次重加热）
    REHEATS_PER_ROUND = 6
    if total_reheats <= REHEATS_PER_ROUND + 1:
        n_rounds = 1
    else:
        n_rounds = max(1, total_reheats // REHEATS_PER_ROUND)
    reheats_per_round = total_reheats // n_rounds

    print(f"\n[Hybrid 多轮策略] 总重加热={total_reheats}, {n_rounds}轮, "
          f"每轮 SA×{reheats_per_round}次重加热 + 爬山{HC_ROUNDS}轮")

    global_best_score = 0
    global_best_solver = None
    start = _time.time()
    used_reheats = 0

    for rd in range(n_rounds):
        remain_reheats = total_reheats - used_reheats
        if remain_reheats < 2:
            print(f"\n[轮{rd+1}] 剩余重加热次数不足，跳过")
            break

        rd_reheats = remain_reheats if rd == n_rounds - 1 else reheats_per_round

        print(f"\n{'='*60}")
        print(f"[轮{rd+1}/{n_rounds}] 开始 (SA重加热={rd_reheats}, 爬山={HC_ROUNDS}轮)")
        print(f"{'='*60}")

        sa_solver = SimulatedAnnealingSolver(calc, verbose=True)
        sa_solver.run(initial_temp=args.sa_temp, max_reheats=rd_reheats,
                      hill_climb_rounds=HC_ROUNDS)
        used_reheats += rd_reheats

        if sa_solver.best_score > global_best_score:
            global_best_score = sa_solver.best_score
            global_best_solver = sa_solver
            print(f"\n[轮{rd+1}] ★ 新全局最优: {global_best_score}")
        else:
            print(f"\n[轮{rd+1}] 本轮得分 {sa_solver.best_score}，"
                  f"未超越全局最优 {global_best_score}")

    # 输出全局最优结果
    total_elapsed = _time.time() - start
    print(f"\n{'='*60}")
    print(f"[多轮汇总] {n_rounds}轮完成，总耗时 {total_elapsed:.1f}s")
    print(f"[多轮汇总] 全局最优得分: {global_best_score}")
    print(f"{'='*60}")

    if global_best_solver:
        best_compact = global_best_solver._plan_to_compact(global_best_solver.best_plan)
        calc.apply_plan(best_compact, fast=False)
        global_best_solver._print_plan(
            global_best_solver.best_plan,
            f"全局最优方案（{n_rounds}轮中最佳）",
            global_best_score)


if __name__ == "__main__":
    main()
