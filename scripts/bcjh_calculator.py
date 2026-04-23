"""
爆炒江湖 计算器引擎（纯 Python 版）
=============================================================
纯 Python 复现网站 calculator.js 的全部计分逻辑。
独立模块，供 bcjh_sa.py 等求解器调用。
"""

import copy
import math
from dataclasses import dataclass, field
from typing import Optional


# ── Dataclass 定义 ──

@dataclass(slots=True)
class CalChef:
    """计算器内部厨师对象"""
    id: int
    rarity: int
    name: str
    subName_origin: Optional[str]
    isf: bool
    skills: dict                           # {sk: value}
    skill_effect: list
    ultimate_effect: list
    disk: dict                             # {maxLevel, info}
    tags: list
    # show_chef 填充的属性
    skills_last: dict = field(default_factory=dict)
    time_buff: float = 0
    partial_flag: bool = False
    effect_condition: list = field(default_factory=list)
    equip_effect: list = field(default_factory=list)
    condiment_effect: list = field(default_factory=list)
    sum_skill_effect: list = field(default_factory=list)
    amber_effect: list = field(default_factory=list)
    MutiEquipmentSkill: int = 0


@dataclass(slots=True)
class ChefScoreResult:
    """cal_score 输出的厨师计分结果"""
    materialReduce: list = field(default_factory=list)
    limitBuff: int = 0
    buff_rule: int = 0
    buff: int = 100
    basicPrice: int = 0
    basicPriceAbs: int = 0
    grade: int = 5
    buff_grade: int = 0
    limit: int = 1
    buff_equip: int = 0
    buff_skill: int = 0
    buff_condiment: int = 0
    price_buff: int = 0
    price_total: int = 0
    inf: dict = field(default_factory=dict)


@dataclass(slots=True)
class CalRecipe:
    """计算器内部菜谱对象"""
    id: int
    name: str
    name_show: str
    rarity: int
    price: int
    exPrice: int
    skills: dict
    time: int
    tags: list
    condiment: str
    materials: list
    materials_id: list
    materials_type: list
    materials_type_set: frozenset
    materials_search: str
    isCombo: bool
    # 技法值
    stirfry: int = 0
    boil: int = 0
    knife: int = 0
    fry: int = 0
    bake: int = 0
    steam: int = 0
    # 计算字段
    buff_ulti: int = 0
    buff_rule: int = 0
    buff_muti: int = 100
    buff: int = 100
    basicPrice: int = 0
    price_wipe_rule: int = 0
    price_buff: int = 0
    price_total: int = 0
    limit_origin: int = 1
    limit: int = 1
    limit_mater: int = 500
    # 显示字段
    rarity_show: str = ''
    time_last: int = 0
    time_show: str = ''
    gold_eff: int = 0
    condiment_show: str = ''
    # 可选字段
    buff_deco: int = 0
    unknowBuff: bool = False
    NotSure: bool = False
    # cal_score 动态写入（3个槽位的厨师结果）
    chef_1: Optional[ChefScoreResult] = None
    chef_2: Optional[ChefScoreResult] = None
    chef_3: Optional[ChefScoreResult] = None
    price_chef_1: int = 0
    price_chef_2: int = 0
    price_chef_3: int = 0
    # cal_score 临时 pos (如 'chf')
    chef_chf: Optional[ChefScoreResult] = None
    price_chef_chf: int = 0


@dataclass(slots=True)
class CacheItem:
    """菜谱/厨师缓存列表项"""
    id: int
    name: str
    score: int = 0   # 仅厨师缓存使用


@dataclass(slots=True)
class SlotData:
    """compact 方案中单个槽位数据"""
    chef_id: int
    recipe_ids: list


# ── 常量 ──
MAX_CHEFS = 3
MAX_REPS_PER_CHEF = 3

GRADE_BUFF = {1: 0, 2: 10, 3: 30, 4: 50, 5: 100}
SKILL_TYPES = ['Stirfry', 'Boil', 'Knife', 'Fry', 'Bake', 'Steam']
SKILL_KEYS = ['stirfry', 'boil', 'knife', 'fry', 'bake', 'steam']
MATERIAL_TYPES = ['Meat', 'Vegetable', 'Creation', 'Fish']
CONDIMENT_TYPES = ['Sweet', 'Sour', 'Spicy', 'Salty', 'Bitter', 'Tasty']
# 集合版本（O(1) 查找）
SKILL_TYPES_SET = frozenset(SKILL_TYPES)
MATERIAL_TYPES_SET = frozenset(MATERIAL_TYPES)
CONDIMENT_TYPES_SET = frozenset(CONDIMENT_TYPES)
# 预计算 lower 映射（避免热路径中反复 .lower()）
_LOWER_MAP = {s: s.lower() for s in SKILL_TYPES + MATERIAL_TYPES + CONDIMENT_TYPES}
LIMIT_BASE = {1: 40, 2: 30, 3: 25, 4: 20, 5: 15}
SKILL_MAP = {'stirfry': '炒', 'boil': '煮', 'knife': '切', 'fry': '炸', 'bake': '烤', 'steam': '蒸'}
# conditionValue 1-6 到技法名的映射（用于 _get_per_skill_cnt）
SKILL_BY_COND_VALUE = ['stirfry', 'fry', 'bake', 'steam', 'boil', 'knife']


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
        self._disable_cookbook_rank = bool(self.rule.get('DisableCookbookRank'))
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

        # 材料限制标志缓存
        self._has_material_limit = bool(rule.get('MaterialsLimit'))

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

            chefs_list.append(CalChef(
                id=item['chefId'],
                rarity=item.get('rarity', 1),
                name=item['name'],
                subName_origin=sub_name_origin,
                isf=chef_buff < 0 if rule.get('ChefTagEffect') else False,
                skills={sk: item.get(sk, 0) or 0 for sk in SKILL_KEYS},
                skill_effect=item['skill_obj'].get('effect', []),
                ultimate_effect=ult_eff_list,
                disk=self.gd.disk_map.get(item.get('disk', 0), {'maxLevel': 1, 'info': []}),
                tags=tags,
            ))

        chefs_list.sort(key=lambda x: (-x.rarity, -x.id))

        if self.show_got:
            self.cal_chefs_list = [c for c in chefs_list if self.ud.chef_got.get(c.id, False)]
        else:
            self.cal_chefs_list = chefs_list
        self._all_chefs_list = chefs_list
        # 构建 chef_id -> chef 快速查找字典
        self._chef_map = {c.id: c for c in chefs_list}

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
            rid = item['recipeId']
            materials = [dict(m, name=next((mat['name'] for mat in self.gd.materials
                                           if mat['materialId'] == m['material']), ''))
                         for m in item.get('materials', [])]
            materials_id = item.get('materials_id', [])
            materials_type = item.get('materials_type', [])

            buff = 100
            ex = item.get('exPrice', 0) if self.default_ex else 0
            buff_ulti = self.ulti.get(f"PriceBuff_{item['rarity']}", 0)
            buff += buff_ulti

            buff_rule = 0
            buff_muti = 100
            buff_deco = 0
            unknowBuff = False
            notSure = False
            r_id = self.rule.get('Id', self.rule.get('id', 0))
            if r_id == 0:
                buff_deco = self.ulti.get('decoBuff', 0)
                buff += buff_deco
            else:
                if rule.get('RecipeEffect'):
                    re_val = rule['RecipeEffect'].get(str(rid), rule['RecipeEffect'].get(rid))
                    if re_val is not None:
                        buff_rule += int(re_val * 100)
                    else:
                        unknowBuff = True
                    if rule.get('NotSure') and rid in rule['NotSure']:
                        notSure = True
                buff_rule += self._sum_buff_rule(rule, item)
                buff_muti += self._sum_buff_rule(muti_effect, item)

            price_wipe_rule = math.ceil((item['price'] + ex) * buff / 100)
            buff += buff_rule
            price_buff = math.ceil((item['price'] + ex) * buff * buff_muti / 10000)

            limit = item.get('limit', LIMIT_BASE.get(item['rarity'], 40)) + self.ulti.get(f"MaxLimit_{item['rarity']}", 0)
            if self.custom_rule and self.custom_rule.get('skill', {}).get('MaxLimit'):
                limit += int(self.custom_rule['skill']['MaxLimit'].get(str(item['rarity']), 0) or 0)
            limit_origin = limit
            if rule.get('DisableMultiCookbook'):
                limit_origin = 1

            r = CalRecipe(
                id=rid,
                name=item['name'],
                name_show=item['name'],
                rarity=item['rarity'],
                price=item['price'],
                exPrice=item.get('exPrice', 0),
                skills=item.get('skills', {}),
                time=item['time'],
                tags=item.get('tags', []),
                condiment=item.get('condiment', ''),
                materials=materials,
                materials_id=materials_id,
                materials_type=materials_type,
                materials_type_set=frozenset(materials_type),
                materials_search=item.get('materials_search', ''),
                isCombo=bool(self.gd.combo_map['combo'].get(rid)),
                stirfry=item.get('stirfry', 0) or 0,
                boil=item.get('boil', 0) or 0,
                knife=item.get('knife', 0) or 0,
                fry=item.get('fry', 0) or 0,
                bake=item.get('bake', 0) or 0,
                steam=item.get('steam', 0) or 0,
                buff_ulti=buff_ulti,
                buff_rule=buff_rule,
                buff_muti=buff_muti,
                buff=buff,
                price_wipe_rule=price_wipe_rule,
                price_buff=price_buff,
                price_total=price_buff * limit_origin,
                limit_origin=limit_origin,
                limit=limit_origin,
                rarity_show='★' * item['rarity'],
                time_last=item['time'],
                time_show=item.get('time_show', ''),
                gold_eff=item.get('gold_eff', 0),
                condiment_show=item.get('condiment_show', ''),
                buff_deco=buff_deco,
                unknowBuff=unknowBuff,
                NotSure=notSure,
            )

            rarity_limit = rule.get('CookbookRarityLimit', 6)
            if item['rarity'] <= rarity_limit:
                reps.append(r)

        self.cal_reps_all = reps
        # 构建 recipe_id -> recipe 快速查找字典
        self._rep_map = {r.id: r for r in reps}
        self._rep_name_map = {r.id: (r.name_show or r.name) for r in reps}

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
        self.cal_chef_show = {1: None, 2: None, 3: None}
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
        chef = copy.copy(c)  # 浅拷贝足够：show_chef只修改标量属性不修改原嵌套结构
        self.cal_chef[slot] = chef
        self.on_site_chef = [self.cal_chef[i].id for i in range(1, 4) if self.cal_chef[i]]

        # 加载用户遗玉/厨具配置
        ambers = self._load_chef_ambers(chef, slot)
        eqp = self._load_chef_equip(chef.id)

        self.cal_chef_show[slot] = self.show_chef(chef, slot, eqp=eqp, ambers=ambers)
        if not self._batch_mode:
            self._handler_all_chefs()

    def _load_chef_ambers(self, chef, slot):
        """加载厨师的遗玉配置"""
        ambers = []
        cid = chef.id
        disk_info = chef.disk.get('info', [])
        disk_max = chef.disk.get('maxLevel', 1)
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
        chef_result = getattr(rep, f'chef_{slot}', None)
        if self.cal_chef[slot] and chef_result:
            self.cal_rep_cnt[key] = chef_result.limit or rep.limit
        else:
            self.cal_rep_cnt[key] = rep.limit

        # 重算所有在场厨师
        if self.cal_chef[slot] and not self._batch_mode:
            self._handler_all_chefs()

    def clear_recipe(self, slot, rep_num):
        key = f'{slot}-{rep_num}'
        old_rep = self.cal_rep.get(key)
        if old_rep and old_rep.id in self.rep_cnt_map:
            del self.rep_cnt_map[old_rep.id]
        self.cal_rep[key] = None
        self.cal_rep_cnt[key] = None
        if self.cal_chef[slot]:
            self._handler_chef(slot)

    def clear_chef(self, slot):
        for rn in range(1, 4):
            self.clear_recipe(slot, rn)
        self.cal_chef[slot] = None
        self.cal_chef_show[slot] = None
        self.on_site_chef = [self.cal_chef[i].id for i in range(1, 4) if self.cal_chef[i]]
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
        for eff in chef.skill_effect:
            if eff.get('type') == 'OpenTime':
                time_buff += eff['value']
            if eff.get('condition') != 'Next' and judge_eff(eff):
                sum_skill_effect.append(eff)
                effect_condition.append(eff.get('conditionType', -1))
                if eff.get('condition') == 'Partial':
                    partial_flag = True

        # 上一位厨师的 Next 效果
        if last_chef:
            for eff in last_chef.skill_effect:
                if eff.get('condition') == 'Next' and judge_eff(eff):
                    sum_skill_effect.append(eff)
            for ue in last_chef.ultimate_effect:
                if ue['uid'] in self.ulti['Partial']['id'] or ue['uid'] in self.ulti['Self']['id']:
                    for eff in ue.get('ultimate_effect', []):
                        if eff.get('condition') == 'Next' and judge_eff(eff):
                            sum_skill_effect.append(eff)

        chef_on_site = self._get_chef_onsite(chef.id)
        chef.MutiEquipmentSkill = 0

        # 修炼技能效果
        for ue in chef.ultimate_effect:
            if ue['uid'] in self.ulti['Self']['id'] or ue['uid'] in self.ulti['Partial']['id']:
                for eff in ue.get('ultimate_effect', []):
                    if eff.get('condition') == 'Next':
                        continue
                    if eff.get('type') == 'OpenTime':
                        time_buff += eff['value']
                    if eff.get('type') == 'MutiEquipmentSkill' and eff.get('cal') == 'Percent':
                        chef.MutiEquipmentSkill += eff['value']
                    if judge_eff(eff):
                        sum_skill_effect.append(eff)
                        effect_condition.append(eff.get('conditionType', -1))
                        if eff.get('condition') == 'Partial':
                            partial_flag = True

        chef.partial_flag = partial_flag
        chef.effect_condition = list(set(effect_condition))
        chef.equip_effect = equip_effect
        chef.condiment_effect = condiment_effect
        chef.sum_skill_effect = sum_skill_effect
        chef.amber_effect = amber_effect

        # 计算最终技法值 —— 预分组 effect 按 type，避免 6×N 重复遍历
        # 1) skill_effect 按 type 分组
        _se_by_type = {}  # type -> [(cal, value)]
        for eff in chef.skill_effect:
            et = eff.get('type')
            if et in SKILL_TYPES_SET:
                _se_by_type.setdefault(et, []).append((eff.get('cal'), eff.get('value', 0)))

        # 2) 修炼技能按 (condition, type) 分组
        ulti_self_ids = self.ulti['Self']['id']
        ulti_partial_ids = self.ulti['Partial']['id']
        _ult_self_by_type = {}  # type -> [(cal, value)]
        _ult_partial_by_type = {}  # type -> [(cal, value, eff)]
        _ult_next_by_type = {}  # type -> [(cal, value)]
        for ue in chef.ultimate_effect:
            if ue['uid'] in ulti_self_ids or ue['uid'] in ulti_partial_ids:
                for eff in ue.get('ultimate_effect', []):
                    et = eff.get('type')
                    if et not in SKILL_TYPES_SET:
                        continue
                    cond = eff.get('condition')
                    cal = eff.get('cal')
                    val = eff.get('value', 0)
                    if cond == 'Self':
                        _ult_self_by_type.setdefault(et, []).append((cal, val))
                    elif cond == 'Partial':
                        _ult_partial_by_type.setdefault(et, []).append((cal, val, eff))
                    elif cond == 'Next':
                        _ult_next_by_type.setdefault(et, []).append((cal, val))

        # 3) 在场厨师 Partial 按 type 分组
        _onsite_partial_by_type = {}  # type -> [(cal, value, eff)]
        for i in range(1, 4):
            cur = self.cal_chef[i]
            if cur:
                for ue in cur.ultimate_effect:
                    if ue['uid'] in ulti_partial_ids or ue['uid'] in ulti_self_ids:
                        for eff in ue.get('ultimate_effect', []):
                            et = eff.get('type')
                            if et in SKILL_TYPES_SET and eff.get('condition') == 'Partial':
                                _onsite_partial_by_type.setdefault(et, []).append(
                                    (eff.get('cal'), eff.get('value', 0), eff))

        # 4) 上一位 Next 按 type 分组
        _last_next_by_type = {}
        if last_chef:
            for ue in last_chef.ultimate_effect:
                if ue['uid'] in ulti_partial_ids or ue['uid'] in ulti_self_ids:
                    for eff in ue.get('ultimate_effect', []):
                        et = eff.get('type')
                        if et in SKILL_TYPES_SET and eff.get('condition') == 'Next':
                            _last_next_by_type.setdefault(et, []).append(
                                (eff.get('cal'), eff.get('value', 0)))

        # 5) 厨具 effect 按 type 分组
        _eqp_by_type = {}
        if eqp and not rule.get('DisableEquipSkillEffect'):
            for eff in eqp.get('effect', []):
                et = eff.get('type')
                if et in SKILL_TYPES_SET:
                    _eqp_by_type.setdefault(et, []).append(
                        (eff.get('cal'), eff.get('value', 0)))

        # 6) 遗玉 effect 按 type 分组
        _amber_by_type = {}
        for eff in ambers_effect_all:
            et = eff.get('type')
            if et in SKILL_TYPES_SET:
                _amber_by_type.setdefault(et, []).append(
                    (eff.get('cal'), eff.get('value', 0)))

        # 预计算不变量
        ulti_all = self.ulti.get('All', 0)
        ulti_male = self.ulti.get('Male', 0)
        ulti_female = self.ulti.get('Female', 0)
        chef_tags = chef.tags
        has_male = 1 in chef_tags
        has_female = 2 in chef_tags
        muti_equip = (100 + chef.MutiEquipmentSkill) / 100
        custom_skill = None
        if self.custom_rule and self.custom_rule.get('skill', {}).get('Skill'):
            custom_skill = self.custom_rule['skill']['Skill']

        for key in SKILL_TYPES:
            low_key = key.lower()
            value = ulti_all + self.ulti.get(key, 0)
            percent_value = 0
            if has_male:
                value += ulti_male
            if has_female:
                value += ulti_female

            # skill_effect（已分组）
            for cal, val in _se_by_type.get(key, ()):
                if cal == 'Abs':
                    value += val
                elif cal == 'Percent':
                    percent_value += val

            # 七侠 tag 加成
            for tag in chef_tags:
                qt = self.ud.qixia_skill_obj_tag.get(tag)
                if qt:
                    value += qt.get(key, 0)

            # 修炼技能 Self（已分组）
            for cal, val in _ult_self_by_type.get(key, ()):
                if cal == 'Abs':
                    value += val
                elif cal == 'Percent':
                    percent_value += val

            # 在场厨师 Partial（已分组）
            for cal, val, eff in _onsite_partial_by_type.get(key, ()):
                ev = self._get_eff_value_by_cond_type(chef, eff)
                if cal == 'Abs':
                    value += ev
                elif cal == 'Percent':
                    percent_value += ev

            # 上一位 Next（已分组）
            for cal, val in _last_next_by_type.get(key, ()):
                if cal == 'Abs':
                    value += val
                elif cal == 'Percent':
                    percent_value += val

            # 不在场时自身 Partial
            if chef_on_site == 0:
                for cal, val, eff in _ult_partial_by_type.get(key, ()):
                    if cal == 'Abs':
                        value += val
                    elif cal == 'Percent':
                        percent_value += val

            # 厨具技法加成（已分组）
            for cal, val in _eqp_by_type.get(key, ()):
                if cal == 'Abs':
                    value += val * muti_equip
                elif cal == 'Percent':
                    percent_value += val * muti_equip

            # 遗玉技法加成（已分组）
            for cal, val in _amber_by_type.get(key, ()):
                if cal == 'Abs':
                    value += val
                elif cal == 'Percent':
                    percent_value += val

            # 百分比加成
            value += math.ceil(((chef.skills.get(low_key, 0) or 0) + value) * percent_value / 100)
            # 自定义规则额外加成
            if custom_skill:
                value += int(custom_skill.get(low_key, 0) or 0)

            skills_last[low_key] = (chef.skills.get(low_key, 0) or 0) + value

        time_buff += equip_time_buff * (100 + chef.MutiEquipmentSkill) / 100
        chef.skills_last = skills_last
        chef.time_buff = time_buff
        return chef

    def get_grade(self, chf, rep):
        """计算品级"""
        min_grade = 5
        inf_detail = {}
        if self._disable_cookbook_rank:
            min_grade = 1
        skills_last = chf.skills_last
        if not skills_last:
            return min_grade, inf_detail
        rep_skills = rep.skills
        if not rep_skills:
            return min_grade, inf_detail
        for sk, req in rep_skills.items():
            if req <= 0:
                continue
            val = skills_last.get(sk, 0)
            multi = int(val // req)
            if val < req:
                inf_detail[sk] = min(inf_detail.get(sk, 0), val - req)
            if multi < min_grade:
                min_grade = multi
        return min_grade, inf_detail

    def cal_score(self, chf, rep, pos, position, remain=None):
        """计算厨师做某个菜的结果（对应 JS calScore）"""
        rule = self.rule
        chef = ChefScoreResult()
        buff_rule = rep.buff_rule
        self.on_site_effect[position] = []

        buff_skill = 0
        buff_equip = 0
        buff_condiment = 0
        buff = rep.buff
        rep.basicPrice = 0
        chef_basicPrice = 0
        chef_basicPriceAbs = 0

        # 预提取 chf 常用属性（减少属性查找）
        chf_tags = chf.tags
        chf_amber_effect = chf.amber_effect
        chf_sum_skill_effect = chf.sum_skill_effect
        chf_equip_effect = chf.equip_effect
        chf_condiment_effect = chf.condiment_effect
        chf_id = chf.id

        chef_tag_eff = self._chef_tag_effect
        if chef_tag_eff:
            tag_buff = 0
            for tag in chf_tags:
                tag_buff += (chef_tag_eff.get(tag, chef_tag_eff.get(str(tag), 0)) or 0) * 100
            buff_rule += tag_buff
            buff += tag_buff

        grade, inf_detail = self.get_grade(chf, rep)
        buff_grade = GRADE_BUFF.get(grade, 0)
        buff += buff_grade

        rep_rarity = rep.rarity
        limit_buff = 0
        for eff in chf_amber_effect:
            if eff.get('type') == 'MaxEquipLimit' and eff.get('rarity') == rep_rarity:
                limit_buff += eff.get('value', 0)

        materialReduce = []
        for eff in chf_sum_skill_effect:
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
                for ue in i_chef.ultimate_effect:
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

        chef.materialReduce = materialReduce
        chef.limitBuff = limit_buff
        limit_rule = 1 if self._disable_multi_cookbook else 500
        rep.limit = min(rep.limit_origin, rep.limit_mater, limit_rule)

        rep_key = f'chef_{pos}'
        chef.buff_rule = buff_rule
        chef.buff = buff
        chef.basicPrice = chef_basicPrice
        chef.basicPriceAbs = chef_basicPriceAbs
        chef.grade = grade
        chef.buff_grade = buff_grade
        setattr(rep, rep_key, chef)
        limit_mater = self._cal_mater_limit(remain, rep, rep_key)
        limit_chef = min(rep.limit_origin + limit_buff, limit_mater, limit_rule)
        chef.limit = limit_chef

        rep_cnt = limit_chef
        if str(pos) in ('1', '2', '3') and rep.id in self.rep_cnt_map:
            cnt_key = self.rep_cnt_map[rep.id]
            if self.cal_rep_cnt.get(cnt_key) is not None:
                rep_cnt = self.cal_rep_cnt[cnt_key]

        # 心法效果
        for eff in chf_amber_effect:
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
            for eff in chf_sum_skill_effect:
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
            for eff in chf_equip_effect:
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
            for eff in chf_condiment_effect:
                buff_condiment += self._get_effect_buff(eff, rep, chf, rep_cnt, grade, position)

        # 在场技能（避免列表拼接，直接链式迭代）
        _ose = self.on_site_effect
        for _os_list in (_ose[1], _ose[2], _ose[3]):
            for eff in _os_list:
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
        chef.buff_equip = buff_equip
        chef.buff_skill = buff_skill
        chef.buff_condiment = buff_condiment
        chef.buff = buff
        chef.basicPrice = chef_basicPrice
        chef.basicPriceAbs = chef_basicPriceAbs

        ex = rep.exPrice if self.default_ex else 0
        basic_buff = rep.basicPrice + chef_basicPrice
        price = math.floor((rep.price + ex + chef_basicPriceAbs) * (100 + basic_buff) / 100)
        chef.price_buff = math.ceil(price * buff * rep.buff_muti / 10000)
        chef.price_total = chef.price_buff * limit_chef

        chef.inf = inf_detail if grade < 1 else {}
        setattr(rep, rep_key, copy.copy(chef))  # 浅拷贝：chef局部变量之后不再修改
        setattr(rep, f'price_chef_{pos}', chef.price_total)
        return rep

    def _get_effect_buff(self, eff, rep, chf, rep_cnt, grade, position, eqp_flag=0, basic_flag=0):
        buff = 0
        ct = eff.get('conditionType')
        eff_cond = eff.get('condition')
        if not ct:
            if eff_cond == 'Partial':
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
            if eff_cond == 'Partial':
                e = dict(eff)
                e.pop('conditionType', None)
                e.pop('condition', None)
                e['value'] = eff.get('value', 0) * self._get_per_rank_cnt(eff, chf, position)
                self.on_site_effect[position].append(e)
            else:
                buff += self._get_eff_wo_cond(eff, rep, chf, eqp_flag, basic_flag) * self._get_per_rank_cnt(eff, chf, position)
        elif ct == 'Rank':
            if eff_cond == 'Partial':
                e = dict(eff)
                e.pop('condition', None)
                self.on_site_effect[position].append(e)
            elif grade >= eff.get('conditionValue', 0):
                buff += self._get_eff_wo_cond(eff, rep, chf, eqp_flag, basic_flag)
        elif ct == 'SameSkill':
            cnt = self._get_same_skill_flag(position)
            if cnt > 0:
                if eff_cond == 'Partial':
                    e = dict(eff)
                    e.pop('conditionType', None)
                    e.pop('condition', None)
                    e['value'] = eff.get('value', 0) * cnt
                    self.on_site_effect[position].append(e)
                else:
                    buff += eff.get('value', 0) * cnt
        elif ct == 'CookbookRarity':
            if eff_cond == 'Partial':
                e = dict(eff)  # 浅拷贝
                e.pop('condition', None)
                self.on_site_effect[position].append(e)
            elif rep.rarity in (eff.get('conditionValueList') or []):
                buff += self._get_eff_wo_cond(eff, rep, chf, eqp_flag, basic_flag)
        elif ct == 'ChefTag':
            if eff_cond == 'Partial':
                e = dict(eff)  # 浅拷贝
                e.pop('condition', None)
                self.on_site_effect[position].append(e)
            elif check_tag(eff.get('conditionValueList', []), chf.tags):
                buff += self._get_eff_wo_cond(eff, rep, chf, eqp_flag, basic_flag)
        elif ct == 'CookbookTag':
            if eff_cond == 'Partial':
                e = dict(eff)  # 浅拷贝
                e.pop('condition', None)
                self.on_site_effect[position].append(e)
            elif check_tag(eff.get('conditionValueList', []), rep.tags):
                buff += self._get_eff_wo_cond(eff, rep, chf, eqp_flag, basic_flag)
        elif ct == 'PerSkill':
            if eff_cond == 'Partial':
                e = dict(eff)
                e.pop('conditionType', None)
                e.pop('condition', None)
                e['value'] = eff.get('value', 0) * self._get_per_skill_cnt(eff)
                self.on_site_effect[position].append(e)
            else:
                buff += self._get_eff_wo_cond(eff, rep, chf, eqp_flag, basic_flag) * self._get_per_skill_cnt(eff, position)
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
                if rep.skills.get(_LOWER_MAP[suffix]):
                    buff += self._get_sp_buff(eff, chf, eqp_flag)
            elif suffix in MATERIAL_TYPES_SET:
                if _LOWER_MAP[suffix] in rep.materials_type_set:
                    buff += self._get_sp_buff(eff, chf, eqp_flag)
            elif suffix in CONDIMENT_TYPES_SET:
                if rep.condiment == suffix:
                    buff += self._get_sp_buff(eff, chf, eqp_flag)
            # 注意：UseAll 不在此处理，已在 _compute_ultimate 通过 PriceBuff_{rarity} 全局处理
        elif t == 'CookbookPrice':
            buff += self._get_sp_buff(eff, chf, eqp_flag)
        elif t == 'BasicPrice':
            if eff.get('conditionType') == 'PerRank':
                if rep.id not in self.rep_cnt_map:
                    rep.basicPrice = rep.basicPrice + self._get_sp_buff(eff, chf, eqp_flag)
            elif basic_flag == 1:
                buff += self._get_sp_buff(eff, chf, eqp_flag)
        return buff

    def _get_sp_buff(self, eff, chf, eqp_flag=0):
        """getSelfPartialBuff — 内联优化版"""
        if eff.get('condition') == 'Partial' and chf.id in self.on_site_chef:
            return 0
        if eqp_flag:
            return eff.get('value', 0) * ((100 + chf.MutiEquipmentSkill) / 100)
        return eff.get('value', 0)

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
        if not chef or not chef.skills_last:
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
            limit_origin = rep.limit_origin
            chef_result = getattr(rep, chef_key, None)
            limit_buff = chef_result.limitBuff if chef_result else 0
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
                for m in rep.materials:
                    qty = m['quantity']
                    chef_r = getattr(rep, chef_key, None)
                    mr_list = chef_r.materialReduce if chef_r else []
                    for mr in mr_list:
                        if m['material'] in mr.get('list', []):
                            qty = max(qty - mr['value'], 1)
                    remain[m['material']] = remain.get(m['material'], 0) - qty * self.cal_rep_cnt[k]
        return remain

    def _cal_mater_limit(self, remain, rep, chef_key=None):
        if not self.rule.get('MaterialsLimit') or remain is None:
            return 500
        limit = 500
        for m in rep.materials:
            qty = m['quantity']
            chef_r = getattr(rep, chef_key, None) if chef_key else None
            if chef_r and chef_r.materialReduce:
                for mr in chef_r.materialReduce:
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

    def _get_per_skill_cnt(self, eff, position=None):
        """按 conditionValue 计算指定技法的菜谱数
        position=None 时计算全部位置，否则仅计算该位置
        """
        idx = eff.get('conditionValue', 1) - 1
        need = SKILL_BY_COND_VALUE[idx] if 0 <= idx < len(SKILL_BY_COND_VALUE) else 'stirfry'
        cnt = 0
        slots = range(1, 4) if position is None else (position,)
        for s in slots:
            for n in range(1, 4):
                rep = self.cal_rep.get(f'{s}-{n}')
                if rep and rep.skills.get(need):
                    cnt += 1
        return cnt

    def _get_same_skill_flag(self, position):
        result = 0
        for sk in SKILL_KEYS:
            cnt = sum(1 for n in range(1, 4) if self.cal_rep.get(f'{position}-{n}') and getattr(self.cal_rep[f'{position}-{n}'], sk, 0))
            if cnt == 3:
                result += 1
        return result

    def _get_eff_value_by_cond_type(self, chef, eff):
        if eff.get('conditionType') == 'ChefTag':
            return eff.get('value', 0) if check_tag(eff.get('conditionValueList', []), chef.tags) else 0
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
        has_mat_limit = self._has_material_limit
        for i in range(6):
            old_cnts = dict(self.cal_rep_cnt) if has_mat_limit else None
            self._handler_all_chefs()
            if has_mat_limit:
                self._sync_rep_cnt()
                if i >= 1 and self.cal_rep_cnt == old_cnts:
                    break  # cal_rep_cnt 已收敛且 on_site 已传播
            else:
                if i >= 1:
                    break  # 无材料限制时2轮即够（on_site 传播）

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
                self.set_chef(slot, plan[slot].chef_id)
            # 2. 菜谱批量设置（不触发 handler）
            self._batch_mode = True
            for slot in sorted(plan.keys()):
                for rn, rid in enumerate(plan[slot].recipe_ids, 1):
                    self.set_recipe(slot, rn, rid)
            self._batch_mode = False
            # 3. 仅对已放置菜谱做 handler 迭代收敛（最少2轮让 on_site_effect 传播）
            has_mat_limit = self._has_material_limit
            for i in range(6):
                old_cnts = dict(self.cal_rep_cnt) if has_mat_limit else None
                self._handler_all_chefs(placed_only=True)
                if has_mat_limit:
                    self._sync_rep_cnt()
                    if i >= 1 and self.cal_rep_cnt == old_cnts:
                        break
                else:
                    if i >= 1:
                        break
        else:
            for slot in sorted(plan.keys()):
                self.set_chef(slot, plan[slot].chef_id)
                for rn, rid in enumerate(plan[slot].recipe_ids, 1):
                    self.set_recipe(slot, rn, rid)
            self._sync_rep_cnt()  # 精确模式最终同步份数
        return self.get_total_score()

    def setup_chefs(self, plan):
        """设置厨师（增量触发 handler），用于 SA 初始化
        之后可反复调用 eval_recipes_fast 只换菜谱
        """
        self.reset()
        for slot in sorted(plan.keys()):
            self.set_chef(slot, plan[slot].chef_id)
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
            for rn, rid in enumerate(plan[slot].recipe_ids, 1):
                self.set_recipe(slot, rn, rid)
        self._batch_mode = False
        # placed_only handler 迭代收敛（最少2轮让 on_site_effect 跨位置传播）
        has_mat_limit = self._has_material_limit
        for i in range(6):
            old_cnts = dict(self.cal_rep_cnt) if has_mat_limit else None
            self._handler_all_chefs(placed_only=True)
            if has_mat_limit:
                self._sync_rep_cnt()
                if i >= 1 and self.cal_rep_cnt == old_cnts:
                    break
            else:
                if i >= 1:
                    break  # 无材料限制时2轮即够
        return self.get_total_score()

    def eval_plan_quick(self, compact):
        """极速评估：batch设置厨师+菜谱，仅placed_only handler收敛。
        不触发 full handler，不重建 _recipe_list_cache。~18次cal_score。
        用于SA内循环高频评估（含厨师变更的邻域）。
        
        关键：cal_rep 中的菜谱用深拷贝，避免 cal_score 污染 _rep_map 原始对象。
        这保证函数幂等性（相同输入→相同输出）。
        """
        # 清除评估状态，但保留 _recipe_list_cache 和 _chef_list_cache
        saved_caches = self._save_caches()
        self.reset()
        self._restore_caches(saved_caches)
        # batch 设置厨师 + 菜谱（不触发 handler）
        self._batch_mode = True
        for slot in sorted(compact.keys()):
            self.set_chef(slot, compact[slot].chef_id)
        for slot in sorted(compact.keys()):
            for rn, rid in enumerate(compact[slot].recipe_ids, 1):
                self.set_recipe(slot, rn, rid)
        self._batch_mode = False
        # ★ 浅拷贝 cal_rep 中的菜谱，防止 cal_score 污染 _rep_map 原始对象
        # cal_score 只写顶层键(basicPrice/limit/chef_{slot}/price_chef_{slot})，浅拷贝即可
        for key in self.cal_rep:
            if self.cal_rep[key]:
                self.cal_rep[key] = copy.copy(self.cal_rep[key])
        # placed_only handler 收敛（最少2轮让 on_site_effect 传播）
        has_mat_limit = self._has_material_limit
        for i in range(6):
            old_cnts = dict(self.cal_rep_cnt) if has_mat_limit else None
            self._handler_all_chefs(placed_only=True)
            if has_mat_limit:
                self._sync_rep_cnt()
                if i >= 1 and self.cal_rep_cnt == old_cnts:
                    break
            else:
                if i >= 1:
                    break
        return self.get_total_score()

    # ── 公共 API（供贪心求解器调用）──

    def _save_caches(self):
        """保存三类缓存（recipe_list / chef_list / chef_slot_scores），供 reset 前暂存"""
        return (self._recipe_list_cache,
                getattr(self, '_chef_list_cache', {}),
                getattr(self, '_chef_slot_scores', {}))

    def _restore_caches(self, saved):
        """恢复三类缓存"""
        self._recipe_list_cache, self._chef_list_cache, self._chef_slot_scores = saved

    @staticmethod
    def _filter_cached_list(cached, exclude_ids, limit=0):
        """从已排序缓存列表中过滤排除项并截断，供 get_recipe_list/get_chef_list 共用"""
        if exclude_ids:
            ex = exclude_ids if isinstance(exclude_ids, set) else set(exclude_ids)
            if limit > 0:
                result = []
                for item in cached:
                    if item.id not in ex:
                        result.append(item)
                        if len(result) >= limit:
                            break
                return result
            return [item for item in cached if item.id not in ex]
        if limit > 0:
            return cached[:limit]
        return list(cached)

    def get_recipe_list(self, slot, exclude_ids, limit=0):
        """获取排好序的菜谱列表（带缓存，厨师不变时排序结果可复用）
        limit>0 时提前截断，避免遍历完整列表（SA 高频调用场景）
        """
        if not hasattr(self, '_recipe_list_cache'):
            self._recipe_list_cache = {}

        if slot not in self._recipe_list_cache:
            reps = []
            for r in self.cal_reps_all:
                if self.show_got and not self.ud.rep_got.get(r.id, False):
                    continue
                reps.append(r)

            if self.cal_chef[slot]:
                key = f'price_chef_{slot}'
                reps.sort(key=lambda x: -(getattr(x, key, x.price_total) or 0))
            else:
                reps.sort(key=lambda x: -(x.price_total or 0))
            self._recipe_list_cache[slot] = [CacheItem(id=r.id, name=r.name_show or r.name) for r in reps]

        return self._filter_cached_list(self._recipe_list_cache[slot], exclude_ids, limit)

    def build_chef_list_cache(self, compact):
        """构建厨师排序缓存：对每个slot，按候选厨师对当前3道菜的得分降序排列。
        用于SA邻域生成时指导厨师替换候选选择。
        成本：~281厨师 x 3菜 x 3slot = ~2529次cal_score。
        """
        self._chef_list_cache = {}
        self._chef_slot_scores = {}
        # 保存 on_site_effect（cal_score 会修改它）
        saved_ose = {k: list(v) for k, v in self.on_site_effect.items()}
        for slot in sorted(compact.keys()):
            slot_scores = {}
            rids = compact[slot].recipe_ids
            # 收集该 slot 已放置的菜谱及份数
            slot_reps = []
            for n in range(1, 4):
                r = self.cal_rep.get(f'{slot}-{n}')
                if r:
                    cnt = self.cal_rep_cnt.get(f'{slot}-{n}') or r.limit
                    slot_reps.append((r, cnt))
            if not slot_reps:
                continue
            # 遍历所有候选厨师
            for c in self.cal_chefs_list:
                if self.show_got and not self.ud.chef_got.get(c.id, False):
                    continue
                # 构建 chef_show（参考 get_recommended_chefs 模式）
                chef_show = self.show_chef(
                    copy.copy(c), slot,
                    eqp=self._load_chef_equip(c.id),
                    ambers=self._load_chef_ambers(c, slot))
                # 恢复 on_site_effect（避免跨候选污染）
                self.on_site_effect = {k: list(v) for k, v in saved_ose.items()}
                price = 0
                for r, cnt in slot_reps:
                    result = self.cal_score(chef_show, copy.copy(r), 'chf', slot)
                    chef_data = result.chef_chf
                    price += (chef_data.price_buff if chef_data else 0) * cnt
                slot_scores[c.id] = price
            # 恢复 on_site_effect
            self.on_site_effect = {k: list(v) for k, v in saved_ose.items()}
            # 按得分降序排列
            sorted_list = sorted(slot_scores.items(), key=lambda x: -x[1])
            self._chef_list_cache[slot] = [
                CacheItem(id=cid, name=next((c.name for c in self.cal_chefs_list if c.id == cid), '?'), score=sc)
                for cid, sc in sorted_list if sc > 0
            ]
            self._chef_slot_scores[slot] = slot_scores

    def get_chef_list(self, slot, exclude_ids, limit=0):
        """获取排好序的厨师列表（从 _chef_list_cache），支持排除和截断"""
        if not hasattr(self, '_chef_list_cache') or slot not in self._chef_list_cache:
            return []
        return self._filter_cached_list(self._chef_list_cache[slot], exclude_ids, limit)

    def get_recommended_chefs(self, slot, exclude_ids, limit=3):
        """获取推荐厨师列表（对应 getRecommendChef）"""
        results = []
        for c in self.cal_chefs_list:
            if c.id in exclude_ids:
                continue
            # 临时设为当前 chef 以计算
            chef = self.show_chef(copy.copy(c), slot,
                                  eqp=self._load_chef_equip(c.id),
                                  ambers=self._load_chef_ambers(c, slot))
            price = 0
            inf_sum = 0
            for i in range(1, 4):
                rep = self.cal_rep.get(f'{slot}-{i}')
                if rep:
                    cnt = self.cal_rep_cnt.get(f'{slot}-{i}') or rep.limit
                    result = self.cal_score(chef, copy.copy(rep), 'chf', slot)
                    chef_data = result.chef_chf
                    price += (chef_data.price_buff if chef_data else 0) * cnt
                    for sk, v in (chef_data.inf if chef_data else {}).items():
                        if v < 0:
                            inf_sum -= v

            if price <= 0:
                continue
            results.append(CacheItem(id=c.id, name=c.name, score=price))

        results.sort(key=lambda x: -x.score)
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
                cd = getattr(rep, f'chef_{s}', None)
                if self.cal_chef[s] and cd:
                    if cd.grade < 1:
                        continue
                    p_buff = cd.price_buff
                else:
                    p_buff = rep.price_buff

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
