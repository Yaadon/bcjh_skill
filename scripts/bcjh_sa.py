"""
爆炒江湖 厨神计算器 模拟退火求解器（纯 Python 版）
=============================================================
纯 Python 复现网站 calculator.js 的全部计分逻辑，
支持贪心初始解 + 模拟退火优化 + 局部爬山精修。

无需浏览器，仅依赖标准库，内存占用 < 50MB。

使用方法：
  python3 bcjh_sa.py --code 你的校验码    # 首次使用
  python3 bcjh_sa.py                         # 后续自动读取缓存
  python3 bcjh_sa.py --sa-reheats 16         # 调整重加热次数
"""

import argparse
import copy
import json
import math
import os
import random
import re
import sys
import urllib.parse
import urllib.request

# ── 在这里填写你的校验码（也可以通过命令行参数 --code 传入）──
USER_CODE = ""
# ─────────────────────────────────────────────────────────────

# 路径
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from bcjh_calculator import (
    MAX_CHEFS, MAX_REPS_PER_CHEF,
    GRADE_BUFF, SKILL_TYPES, SKILL_KEYS, SKILL_TYPES_SET,
    MATERIAL_TYPES_SET, CONDIMENT_TYPES_SET, LIMIT_BASE,
    SKILL_MAP, SKILL_BY_COND_VALUE,
    judge_eff, check_tag, dc,
    Calculator, SlotData, CacheItem,
)
CACHE_DIR = os.path.join(SCRIPT_DIR, '.bcjh_user_caches')
# 兼容旧版单文件缓存
LEGACY_CACHE_FILE = os.path.join(SCRIPT_DIR, '.bcjh_user_cache.json')


def _get_cache_file(user_id=None):
    """根据 user_id 返回对应的缓存文件路径；无 user_id 时使用旧版单文件"""
    if not user_id:
        return LEGACY_CACHE_FILE
    os.makedirs(CACHE_DIR, exist_ok=True)
    return os.path.join(CACHE_DIR, f'{user_id}.json')


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


def fetch_rules(time_str=None):
    """从 API 获取规则，可选指定时间获取历史规则"""
    url = 'https://i.baochaojianghu.com/api/get_rule'
    if time_str:
        params = urllib.parse.urlencode({'time': time_str})
        url = f'{url}?{params}'
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


# Calculator 类已移至 bcjh_calculator.py


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
            slot: SlotData(
                chef_id=data['chef'].id,
                recipe_ids=[r.id for _, r in data['recipes']]
            )
            for slot, data in plan.items()
        }

    def _compact_to_plan(self, compact):
        """将 compact 格式转回完整 plan"""
        chef_map = {c.id: c for c in self.calc._all_chefs_list}
        rep_map = {r.id: r for r in self.calc.cal_reps_all}
        result = {}
        for slot, data in compact.items():
            chef = chef_map.get(data.chef_id)
            recipes = []
            for rn, rid in enumerate(data.recipe_ids, 1):
                r = rep_map.get(rid)
                rname = (r.name_show or r.name) if r else ''
                recipes.append((rn, CacheItem(id=rid, name=rname)))
            result[slot] = {'chef': CacheItem(id=chef.id if chef else 0, name=chef.name if chef else '?'), 'recipes': recipes}
        return result

    @staticmethod
    def _copy_compact(c):
        return {s: SlotData(chef_id=d.chef_id, recipe_ids=list(d.recipe_ids))
                for s, d in c.items()}

    @staticmethod
    def _get_used_recipes(compact):
        used = set()
        for d in compact.values():
            used.update(d.recipe_ids)
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
            entry = {'chef': chef.name, 'chef_id': chef.id, 'recipes': []}
            for rn, recipe in recipes:
                cnt = self.calc.cal_rep_cnt.get(f'{slot}-{rn}', 0)
                entry['recipes'].append({'name': recipe.name, 'id': recipe.id, 'count': cnt})
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
            print(f"\n厨师 {slot}: [{sd['chef'].name}]")
            for rn, recipe in sd['recipes']:
                cnt = self.calc.cal_rep_cnt.get(f'{slot}-{rn}', '?')
                print(f"  菜谱{rn}: [{recipe.name}]  份数: {cnt}")
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
            self.calc.set_recipe(new_slot, 1, recipe.id)
            chefs = self.calc.get_recommended_chefs(new_slot, self.used_chefs, limit=1)
            self.calc.clear_recipe(new_slot, 1)
            if chefs:
                candidates.append((recipe, chefs))
                self.log(f"    菜谱[{recipe.name}] 推荐厨师: {', '.join(c.name for c in chefs)}")
            else:
                self.log(f"    菜谱[{recipe.name}] 无可用厨师")

        if not candidates:
            return (0, None, None)

        best_score, best_recipe, best_chef = 0, None, None
        for recipe, chefs in candidates:
            for chef in chefs:
                self.calc.set_chef(new_slot, chef.id)
                self.calc.set_recipe(new_slot, 1, recipe.id)
                score = self.calc.get_total_score()
                self.log(f"    菜谱[{recipe.name}] x 厨师[{chef.name}] -> 总分={score}")
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
                self.calc.set_recipe(slot, rep_num, recipe.id)
                score = self.calc.get_total_score()
                self.log(f"    slot{slot} [{slot_data['chef'].name}] + {recipe.name} -> 总分={score}")
                self.calc.clear_recipe(slot, rep_num)
                if score > best_score:
                    best_score, best_recipe, best_slot, best_rep_num = score, recipe, slot, rep_num
        return (best_score, best_recipe, best_slot, best_rep_num)

    def commit_new_slot(self, chef, recipe):
        slot = len(self.plan) + 1
        self.calc.set_chef(slot, chef.id)
        self.calc.set_recipe(slot, 1, recipe.id)
        self.calc._sync_rep_cnt()  # 永久变更后同步份数
        self.plan[slot] = {'chef': chef, 'recipes': [(1, recipe)]}
        self.used_chefs.add(chef.id)
        self.used_recipes.add(recipe.id)
        self.current_total = self.calc.get_total_score()

    def commit_existing_slot(self, slot, rep_num, recipe):
        self.calc.set_recipe(slot, rep_num, recipe.id)
        self.calc._sync_rep_cnt()  # 永久变更后同步份数
        self.plan[slot]['recipes'].append((rep_num, recipe))
        self.used_recipes.add(recipe.id)
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
        self.log(f"  => 厨师[{c1.name}] + 菜谱[{r1.name}]  总分={self.current_total}")

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

            self.log(f"  选项A(新厨师): score={sA}  {rA.name if rA else 'N/A'} / {cA.name if cA else 'N/A'}")
            self.log(f"  选项B(现有厨师): score={sB}  {rB.name if rB else 'N/A'}")

            if len(self.plan) >= MAX_CHEFS:
                if sB <= 0:
                    self.log("  => 现有厨师无剩余可行菜谱，结束。")
                    break
                self.commit_existing_slot(slotB, rnB, rB)
                self.log(f"  => [选项B] {self.plan[slotB]['chef'].name} + {rB.name}  总分={self.current_total}")
            elif sA >= sB and sA > 0:
                self.commit_new_slot(cA, rA)
                self.log(f"  => [选项A] 新厨师[{cA.name}] + {rA.name}  总分={self.current_total}")
            elif sB > 0:
                self.commit_existing_slot(slotB, rnB, rB)
                self.log(f"  => [选项B] {self.plan[slotB]['chef'].name} + {rB.name}  总分={self.current_total}")
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
                rids = best_compact[slot].recipe_ids
                for r_idx in range(len(rids)):
                    if improved:
                        break
                    for new_rec in candidates:
                        cand = self._copy_compact(best_compact)
                        cand[slot].recipe_ids[r_idx] = new_rec.id
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
                rids1 = best_compact[s1].recipe_ids
                for r1_idx in range(len(rids1)):
                    if found_two_step:
                        break
                    for c1 in slot_candidates[s1]:
                        if found_two_step:
                            break
                        # 构造第一步替换后的方案
                        step1 = self._copy_compact(best_compact)
                        step1[s1].recipe_ids[r1_idx] = c1.id

                        # 第一步替换后，获取新的可用菜谱
                        used_after_step1 = self._get_used_recipes(step1)

                        # 尝试所有 (pos2, cand2) 作为第二步
                        for s2 in slots:
                            if found_two_step:
                                break
                            rids2 = step1[s2].recipe_ids
                            for r2_idx in range(len(rids2)):
                                if found_two_step:
                                    break
                                if s1 == s2 and r1_idx == r2_idx:
                                    continue  # 跳过同一位置
                                # 第二步候选：用原始 slot 候选 + 排除第一步已用的
                                for c2 in slot_candidates[s2]:
                                    if c2.id in used_after_step1:
                                        continue
                                    step2 = self._copy_compact(step1)
                                    step2[s2].recipe_ids[r2_idx] = c2.id
                                    score = _eval(step2)
                                    eval_count += 1
                                    if score > best_score:
                                        old1 = self._get_rep_name(rids1[r1_idx])
                                        old2 = self._get_rep_name(best_compact[s2].recipe_ids[r2_idx])
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
            self.used_chefs.add(d.chef_id)
            self.used_recipes.update(d.recipe_ids)
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
            # 操作: 替换厨师（优先用 _chef_list_cache 排序选取）
            slot = random.choice(slots)
            used_chefs = {d.chef_id for d in compact.values()}
            candidates = self.calc.get_chef_list(slot, used_chefs, limit=cand_range)
            if candidates:
                pick = random.choice(candidates)
                neighbor[slot].chef_id = pick.id
                return neighbor, True, self.OP_CHEF_REPLACE
            # fallback: 无缓存或缓存为空时用原始列表
            avail = [c for c in self.calc._all_chefs_list
                     if c.id not in used_chefs
                     and self.calc.ud.chef_got.get(c.id, not self.calc.show_got)]
            if avail:
                pick = random.choice(avail[:max(10, int(30 * t_ratio))])
                neighbor[slot].chef_id = pick.id
                return neighbor, True, self.OP_CHEF_REPLACE
            # 无可用厨师时 fallthrough 到单菜替换
            op = p_chef_swap + 0.01

        if op < p_chef_swap:
            # 操作: 厨师位置交换（从 JS _climbChefSwap 借鉴，仅高温时触发）
            if len(slots) >= 2 and t_ratio > 0.3:
                s1, s2 = random.sample(slots, 2)
                neighbor[s1].chef_id, neighbor[s2].chef_id = \
                    neighbor[s2].chef_id, neighbor[s1].chef_id
                return neighbor, True, self.OP_CHEF_SWAP

        if op < p_recipe_replace:
            # 操作: 随机替换一道菜（最常用的邻域）
            slot = random.choice(slots)
            rids = neighbor[slot].recipe_ids
            if rids:
                idx = random.randint(0, len(rids) - 1)
                old_id = rids[idx]
                exclude = used - {old_id}
                candidates = self.calc.get_recipe_list(slot, exclude, limit=cand_range)
                if candidates:
                    pick = random.choice(candidates)
                    rids[idx] = pick.id
            return neighbor, False, self.OP_RECIPE_REPLACE

        elif op < p_two_step:
            # 操作: 同时替换两道不同位置的菜（概率已降低）
            all_positions = [(s, i) for s in slots for i in range(len(neighbor[s].recipe_ids))]
            if len(all_positions) >= 2:
                p1, p2 = random.sample(all_positions, 2)
                old1 = neighbor[p1[0]].recipe_ids[p1[1]]
                exclude1 = used - {old1}
                cands1 = self.calc.get_recipe_list(p1[0], exclude1, limit=cand_range)
                if cands1:
                    pick1 = random.choice(cands1)
                    neighbor[p1[0]].recipe_ids[p1[1]] = pick1.id
                    new_used = self._get_used_recipes(neighbor)
                    old2 = neighbor[p2[0]].recipe_ids[p2[1]]
                    exclude2 = new_used - {old2}
                    cands2 = self.calc.get_recipe_list(p2[0], exclude2, limit=cand_range)
                    if cands2:
                        pick2 = random.choice(cands2)
                        neighbor[p2[0]].recipe_ids[p2[1]] = pick2.id
            return neighbor, False, self.OP_TWO_STEP

        elif op < p_recipe_swap:
            # 操作: 交换两个不同slot的菜谱位置（最高效操作，保证跨slot）
            if len(slots) >= 2:
                s1, s2 = random.sample(slots, 2)
                i1 = random.randint(0, len(neighbor[s1].recipe_ids) - 1)
                i2 = random.randint(0, len(neighbor[s2].recipe_ids) - 1)
                neighbor[s1].recipe_ids[i1], neighbor[s2].recipe_ids[i2] = \
                    neighbor[s2].recipe_ids[i2], neighbor[s1].recipe_ids[i1]
            return neighbor, False, self.OP_RECIPE_SWAP

        else:
            # 操作: 远端替换——从排名靠后的候选中选（跳出局部最优）
            slot = random.choice(slots)
            rids = neighbor[slot].recipe_ids
            if rids:
                idx = random.randint(0, len(rids) - 1)
                old_id = rids[idx]
                exclude = used - {old_id}
                candidates = self.calc.get_recipe_list(slot, exclude, limit=50)
                far_start = min(10, len(candidates))
                far_end = len(candidates)
                if far_start < far_end:
                    pick = candidates[random.randint(far_start, far_end - 1)]
                    rids[idx] = pick.id
            return neighbor, False, self.OP_FAR_REPLACE

    def run(self, initial_temp=800, final_temp=5, alpha=0.92,
            max_reheats=8, max_iter_per_temp=15):
        """运行模拟退火（轮次控制，确保跨平台结果一致）

        参数:
            initial_temp: 初始温度（控制初期接受差解的概率）
            final_temp: 终止温度
            alpha: 降温系数（0.92 → 更快降温更多轮加热+交叉）
            max_reheats: 最大重加热次数（控制搜索深度），默认8
            max_iter_per_temp: 每个温度下的迭代次数（15次更充分探索）
        """
        import time as _time

        self.log("\n" + "=" * 60)
        self.log("开始模拟退火求解...")
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
        # 初始化：setup_chefs 建 _recipe_list_cache，eval_plan_quick 评估，build_chef_list_cache 建厨师缓存
        self.calc.setup_chefs(current_compact)
        current_score = self.calc.eval_plan_quick(current_compact)
        self.calc.build_chef_list_cache(current_compact)
        self.log(f"  快速评估基准分: {current_score}（精确分: {initial_score}）")

        # 快速模式做基准，SA 内部比较全部基于快速模式
        global_best_compact = self._copy_compact(current_compact)
        global_best_score = current_score
        # 精确验证：追踪真实最优（避免快速评估虚高）
        precise_best_compact = self._copy_compact(initial_compact)
        precise_best_score = initial_score
        # 记录当前厨师配置（用于检测厨师变更）
        current_chef_ids = {s: d.chef_id for s, d in current_compact.items()}

        # 操作统计
        op_stats = self._new_op_stats()

        temperature = initial_temp
        total_iterations = 0
        accept_count = 0
        improve_count = 0
        precise_improve_count = 0
        reheat_count = 0
        chef_change_count = 0

        while reheat_count < max_reheats:

            for iteration in range(max_iter_per_temp):
                total_iterations += 1

                neighbor, chefs_changed, op_type = self._get_neighbor(
                    current_compact, temperature, initial_temp)
                op_stats[op_type]['triggered'] += 1

                # 统一用 eval_plan_quick 评估（~18次cal_score，含厨师变更）
                neighbor_score = self.calc.eval_plan_quick(neighbor)
                if chefs_changed:
                    chef_change_count += 1

                delta = neighbor_score - current_score
                accepted = False

                if delta > 0:
                    # 更好的解：直接接受
                    current_compact = self._copy_compact(neighbor)
                    current_score = neighbor_score
                    accept_count += 1
                    accepted = True

                    if chefs_changed:
                        # 厨师变更被接受：重建 _recipe_list_cache
                        self.calc.setup_chefs(current_compact)
                        current_chef_ids = {s: d.chef_id for s, d in current_compact.items()}

                    if current_score > global_best_score:
                        global_best_compact = self._copy_compact(current_compact)
                        global_best_score = current_score
                        improve_count += 1
                        op_stats[op_type]['improved'] += 1

                        # 精确验证（保存/恢复缓存，避免 apply_plan 清空）
                        saved_caches = self.calc._save_caches()
                        precise_score = self.calc.apply_plan(current_compact, fast=False)
                        if precise_score > precise_best_score:
                            precise_best_compact = self._copy_compact(current_compact)
                            precise_best_score = precise_score
                            precise_improve_count += 1

                            # ★ 轻量爬山：在新精确最优上做快速局部搜索
                            if reheat_count < int(max_reheats * 0.85):
                                self.log(f"    → 触发轻量爬山 (精确={precise_score})...")
                                hc_compact, hc_score = self._hill_climb_light(
                                    self._copy_compact(current_compact), precise_score)
                                if hc_score > precise_best_score:
                                    precise_best_compact = self._copy_compact(hc_compact)
                                    precise_best_score = hc_score
                                    self.log(f"    → 轻量爬山提升: {precise_score} → {hc_score} (+{hc_score - precise_score})")

                        # 恢复缓存（替代原来的 setup_chefs 调用）
                        self.calc._restore_caches(saved_caches)

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
                            current_chef_ids = {s: d.chef_id for s, d in current_compact.items()}

                # eval_plan_quick 不修改持久缓存状态，拒绝时无需恢复

            # 降温
            temperature *= alpha

            # 温度过低时重新加热
            if temperature <= final_temp:
                reheat_count += 1
                temperature = initial_temp

                # 从精确最优重新出发
                current_compact = self._copy_compact(precise_best_compact)
                self.calc.setup_chefs(current_compact)  # 重建 _recipe_list_cache
                current_score = self.calc.eval_plan_quick(current_compact)
                self.calc.build_chef_list_cache(current_compact)  # 重建 _chef_list_cache
                current_chef_ids = {s: d.chef_id for s, d in current_compact.items()}
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

        self.best_plan = self._compact_to_plan(precise_best_compact)
        self.best_score = precise_best_score

        self.log(f"\n[模拟退火] 完成，共 {total_iterations} 次迭代，{accept_count} 次接受，"
                f"{improve_count} 次快速改进，{precise_improve_count} 次精确改进，"
                f"{reheat_count} 轮加热，{chef_change_count} 次换厨师，耗时 {elapsed:.1f}秒")

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

        self.best_plan = self._compact_to_plan(precise_best_compact)
        self.best_score = precise_best_score

        return self._build_result()

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
            rids = compact[slot].recipe_ids
            for idx in range(len(rids)):
                old_rid = rids[idx]
                used = self._get_used_recipes(compact) - {old_rid}
                candidates = self.calc.get_recipe_list(slot, used)[:3]
                for cand in candidates:
                    if cand.id == old_rid:
                        continue
                    compact[slot].recipe_ids[idx] = cand.id
                    ns = _eval(compact)
                    if ns > fast_score:
                        fast_score = ns
                        old_rid = cand.id
                    else:
                        compact[slot].recipe_ids[idx] = old_rid

        # 2) 快速菜谱交换
        slots = sorted(compact.keys())
        for i in range(len(slots)):
            for j in range(i + 1, len(slots)):
                s1, s2 = slots[i], slots[j]
                for idx1 in range(len(compact[s1].recipe_ids)):
                    for idx2 in range(len(compact[s2].recipe_ids)):
                        rid1 = compact[s1].recipe_ids[idx1]
                        rid2 = compact[s2].recipe_ids[idx2]
                        if rid1 == rid2:
                            continue
                        compact[s1].recipe_ids[idx1] = rid2
                        compact[s2].recipe_ids[idx2] = rid1
                        ns = _eval(compact)
                        if ns > fast_score:
                            fast_score = ns
                        else:
                            compact[s1].recipe_ids[idx1] = rid1
                            compact[s2].recipe_ids[idx2] = rid2

        # 精确校准
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
    parser.add_argument("--optimizer", type=str, default="simulated_annealing",
                        choices=["simulated_annealing", "local_search"],
                        help="优化策略：simulated_annealing=模拟退火（默认），local_search=贪心+局部搜索")
    parser.add_argument("--sa-reheats", type=int, default=12,
                        help="SA重加热次数（控制搜索深度），默认12")
    parser.add_argument("--sa-temp", type=float, default=800,
                        help="模拟退火初始温度，默认800")
    parser.add_argument("--time", type=str, default=None,
                        help="指定时间获取历史规则，格式如 '2026-04-17 14:00:00'")
    parser.add_argument("--rule-id", type=int, default=None,
                        help="指定使用的规则ID（从API返回的多个规则中选择）")
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
    time_str = None
    if args.time:
        from datetime import datetime
        try:
            dt = datetime.strptime(args.time, '%Y-%m-%d %H:%M:%S')
        except ValueError:
            try:
                dt = datetime.strptime(args.time, '%Y-%m-%d')
                dt = dt.replace(hour=14)
            except ValueError:
                print(f"  时间格式错误: {args.time}，请使用 'YYYY-MM-DD' 或 'YYYY-MM-DD HH:MM:SS'")
                sys.exit(1)
        time_str = dt.strftime('%Y-%m-%dT%H:%M:%S.000Z')
        print(f"  指定时间: {args.time}")
    food_god_rules = fetch_rules(time_str)
    if food_god_rules:
        if len(food_god_rules) > 1:
            print(f"  获取到 {len(food_god_rules)} 条规则:")
            for r in food_god_rules:
                print(f"    ID={r.get('Id')}  {r.get('Title', '未知')}")
        if args.rule_id is not None:
            matched = [r for r in food_god_rules if r.get('Id') == args.rule_id]
            if matched:
                food_god_rules = matched
                print(f"  选择规则: ID={args.rule_id} {matched[0].get('Title', '')}")
            else:
                print(f"  未找到 ID={args.rule_id} 的规则，使用第一条")
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
    if args.optimizer == "simulated_annealing":
        sa_solver = SimulatedAnnealingSolver(calc, verbose=True)
        sa_solver.run(initial_temp=args.sa_temp, max_reheats=args.sa_reheats)
    else:
        solver = GreedySolver(calc, verbose=True)
        solver.run()


if __name__ == "__main__":
    main()
