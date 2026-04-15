"""
爆炒江湖 厨神计算器 贪心最优组合求解器（浏览器自动化版）
=============================================================
依赖：pip install playwright
首次运行：playwright install chromium

使用方法：
  python3 bcjh_greedy.py --code 你的校验码

  或直接修改下方 USER_CODE 变量后运行：
  python3 bcjh_greedy.py

算法说明：
  - 利用 https://h5.baochaojianghu.com/ 的计算器页面获取真实得分（含每周规则加成）
  - 贪心策略：先选菜谱再配厨师，利用网页 getRecommendChef 获取最优厨师排序
  - 每步对比"新增厨师位+最优菜谱" vs "现有厨师空位+最优菜谱"，选得分更高的
  - 目标：3位厨师 × 3道菜谱 = 9个格子，最大化总得分
"""

import argparse
import os
import re
import sys
import time

# ── 在这里填写你的校验码（也可以通过命令行参数 --code 传入）──
USER_CODE = "" #MK8UGM
# ─────────────────────────────────────────────────────────────

URL = "https://h5.baochaojianghu.com/"
MAX_CHEFS = 3
MAX_REPS_PER_CHEF = 3

# 浏览器持久化缓存目录（localStorage 数据存在这里，下次启动无需重新导入校验码）
BROWSER_PROFILE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".bcjh_browser_profile")


# ══════════════════════════════════════════════
#  浏览器操作工具函数
# ══════════════════════════════════════════════

def get_vm(page):
    """获取 Vue 实例"""
    return page.evaluate("document.querySelector('#main').__vue__")


def js_eval(page, script: str):
    return page.evaluate(f"(function(){{ var vm = document.querySelector('#main').__vue__; {script} }})()")


def wait_page_ready(page, timeout=30000):
    """等待 Vue 数据加载完成（calLoad 变为 false 表示已加载）"""
    page.wait_for_function(
        "() => { try { var vm = document.querySelector('#main').__vue__; return vm && !vm.calLoad; } catch(e){ return false; } }",
        timeout=timeout
    )


def ensure_cal_loaded(page):
    """
    确保计算器数据已加载。
    calLoad=true 时数据为空，需调用 initCal() 触发加载，然后等待 calLoad 变为 false。
    """
    cal_load = js_eval(page, "return vm.calLoad;")
    if cal_load:
        print("  计算器数据未加载，调用 initCal()...")
        js_eval(page, "vm.initCal();")
        time.sleep(1)
        wait_page_ready(page, timeout=30000)
        print("  计算器数据加载完成。")


def nav_to_calculator(page):
    """导航到计算器页面"""
    js_eval(page, "vm.checkNav(7);")
    time.sleep(0.5)


def nav_to_personal(page):
    """导航到个人页"""
    js_eval(page, "vm.checkNav(8);")
    time.sleep(0.5)


def import_user_data(page, code: str) -> bool:
    """通过校验码导入官方数据"""
    print(f"正在导入校验码数据...")
    nav_to_personal(page)
    time.sleep(1)

    # 填入校验码
    js_eval(page, f"vm.userDataCode = '{code}';")
    # 触发导入
    js_eval(page, "vm.syncUserData();")
    time.sleep(3)

    # 回到计算器
    nav_to_calculator(page)
    time.sleep(1)
    return True


def enable_got_only(page):
    """开启「只展示已有厨师菜谱」"""
    js_eval(page, "vm.calShowGot = true;")
    time.sleep(0.3)


def set_chef(page, slot: int, chef_id):
    """设置指定槽位的厨师"""
    page.evaluate(f"""
    (function(){{
        var vm = document.querySelector('#main').__vue__;
        var chefList = (vm.calChefs && vm.calChefs[{slot}]) ? vm.calChefs[{slot}] : [];
        var target = chefList.find(function(c){{ return (c.id || c.chefId) == {chef_id}; }});
        if (!target) {{ console.warn('Chef not found in slot {slot}: {chef_id}'); return; }}
        var selected = {{ id: [target.id || target.chefId], row: [target], name: [target.name] }};
        vm.$set(vm.calChef, {slot}, selected);
        // setDiskList 需要 calAmberList 已初始化，用 try-catch 保护
        try {{ vm.setDiskList({slot}); }} catch(e) {{ console.warn('setDiskList skipped:', e.message); }}
    }})()
    """)
    time.sleep(0.2)


def set_recipe(page, slot: int, rep_num: int, recipe_id):
    """设置指定槽位厨师的指定菜谱位"""
    page.evaluate(f"""
    (function(){{
        var vm = document.querySelector('#main').__vue__;
        var key = '{slot}-{rep_num}';
        // calRepsAll 是完整菜谱数组
        var allReps = vm.calRepsAll || [];
        var target = allReps.find(function(r){{ return (r.recipeId || r.id) == {recipe_id}; }});
        if (!target) {{
            // 备用：从当前 slot 的 calReps_list 找
            var listReps = (vm.calReps_list && vm.calReps_list[{slot}]) ? vm.calReps_list[{slot}] : [];
            target = listReps.find(function(r){{ return (r.recipeId || r.id) == {recipe_id}; }});
        }}
        if (!target) {{ console.warn('Recipe not found: {recipe_id}'); return; }}
        var selected = {{ id: [target.recipeId || target.id], row: [target], name: [target.name_show || target.name] }};
        vm.$set(vm.calRep, key, selected);
        vm.handleCalRepChange(selected.row, key);
    }})()
    """)
    time.sleep(0.2)


def clear_recipe(page, slot: int, rep_num: int):
    """清除指定菜谱位（模拟网页原生清除行为）"""
    page.evaluate(f"""
    (function(){{
        var vm = document.querySelector('#main').__vue__;
        var key = '{slot}-{rep_num}';
        vm.$set(vm.calRep, key, {{ id: [], row: [], name: [] }});
        vm.handleCalRepChange([], key);
    }})()
    """)
    time.sleep(0.1)


def clear_chef(page, slot: int):
    """清除指定厨师槽位（及其所有菜谱，模拟网页原生清除行为）"""
    page.evaluate(f"""
    (function(){{
        var vm = document.querySelector('#main').__vue__;
        for (var r = 1; r <= 3; r++) {{
            var key = '{slot}-' + r;
            vm.$set(vm.calRep, key, {{ id: [], row: [], name: [] }});
            vm.handleCalRepChange([], key);
        }}
        vm.$set(vm.calChef, {slot}, {{ id: [], row: [], name: [] }});
    }})()
    """)
    time.sleep(0.1)


def get_calculator_name(page) -> str:
    """读取当前计算器名称（如 '26/03/26远洋餐社（10/10）-爆炒花甲'）"""
    raw = js_eval(page, """
        var rule = vm.calType && vm.calType.row && vm.calType.row[0];
        if (!rule) return '';
        return rule.Title || ((rule.name || '') + (rule.subName ? ' - ' + rule.subName : ''));
    """)
    return str(raw).strip() if raw else ""


def get_total_score(page) -> int:
    """读取当前计算器总得分"""
    raw = js_eval(page, "vm.getCalRepShow(); return vm.calResultTotal || '';")
    # 格式："原售价：1234 总得分：5678"
    match = re.search(r'总得分[：:]\s*(\d+)', str(raw))
    if match:
        return int(match.group(1))
    # 备用：直接找数字（最后一个数字通常是总分）
    nums = re.findall(r'\d+', str(raw))
    if nums:
        return int(nums[-1])
    return 0


def reset_calculator(page):
    """重置所有选择"""
    for slot in range(1, MAX_CHEFS + 1):
        clear_chef(page, slot)
    time.sleep(0.3)


# ══════════════════════════════════════════════
#  数据读取辅助函数
# ══════════════════════════════════════════════

def read_recipe_list(page, slot: int, exclude_ids: set) -> list:
    """
    读取 calReps_list[slot]，保持网页原始排序，排除 exclude_ids。
    - 无厨师时：网页按 price_total（基础分）降序排列
    - 有厨师时：网页按 price_chef_{slot}（含厨师加成得分）降序排列
    """
    exclude_list = list(exclude_ids)
    result = page.evaluate(f"""
    (function(){{
        var vm = document.querySelector('#main').__vue__;
        var list = vm.calReps_list && vm.calReps_list[{slot}];
        if (!list) return [];
        var exclude = new Set({exclude_list});
        var out = [];
        for (var i = 0; i < list.length; i++) {{
            var r = list[i];
            var rid = r.recipeId || r.id;
            if (exclude.has(rid)) continue;
            if (r.isf) continue;
            out.push({{ id: rid, name: r.name_show || r.name }});
        }}
        return out;
    }})()
    """)
    return result or []


def trigger_chef_recommend(page, slot: int):
    """
    触发网页的厨师推荐排序。
    前提：该 slot 已设置了至少一个菜谱（hasRep 为 true）。
    调用后 calChefs[slot] 按与当前菜谱的兼容得分降序排列。
    """
    page.evaluate(f"""
    (function(){{
        var vm = document.querySelector('#main').__vue__;
        vm.getRecommend('chef', {slot});
    }})()
    """)
    time.sleep(0.3)


def read_sorted_chefs(page, slot: int, exclude_ids: set, limit: int = 3) -> list:
    """
    读取 calChefs[slot]（已由 getRecommendChef 按得分排好序），
    排除 exclude_ids，跳过 price_total <= 0 的厨师，返回前 limit 个。
    """
    exclude_list = list(exclude_ids)
    result = page.evaluate(f"""
    (function(){{
        var vm = document.querySelector('#main').__vue__;
        var list = vm.calChefs[{slot}] || [];
        var exclude = new Set({exclude_list});
        var out = [];
        for (var i = 0; i < list.length && out.length < {limit}; i++) {{
            var c = list[i];
            var cid = c.id || c.chefId;
            if (exclude.has(cid)) continue;
            if ((c.price_total || 0) <= 0) continue;
            if (c.isf) continue;
            out.push({{ id: cid, name: c.name, price_total: c.price_total || 0 }});
        }}
        return out;
    }})()
    """)
    return result or []


def wait_for_price_chef(page, slot: int):
    """等待 handlerChef 完成（calReps_list[slot] 出现 price_chef 字段）"""
    try:
        page.wait_for_function(
            f"""() => {{
                try {{
                    var vm = document.querySelector('#main').__vue__;
                    var list = vm.calReps_list && vm.calReps_list[{slot}];
                    if (!list || !list.length) return false;
                    var key = 'price_chef_{slot}';
                    return list[0][key] > 0;
                }} catch(e) {{ return false; }}
            }}""",
            timeout=5000
        )
    except Exception:
        time.sleep(1.0)


# ══════════════════════════════════════════════
#  贪心主算法
# ══════════════════════════════════════════════

class GreedySolver:
    """
    贪心策略（先选菜谱再配厨师）：

    每步面临两个选项：
      选项A（新厨师位）：
        取 calReps_list 前 TOP_K 个未用菜谱（网页已按得分降序排列），
        对每个菜谱：设菜谱 → 触发 getRecommendChef 获取按兼容性排序的厨师列表 →
        取排名第一的厨师探测 calResultTotal → 选得分最高的 (菜谱, 厨师) 组合。
        （厨师推荐已精确反映菜谱兼容性，且不影响材料消耗，无需多试。）
      选项B（现有厨师加菜谱）：
        对每个有空位的已有 slot，取 calReps_list[slot] 前 TOP_K 个未用菜谱，
        逐个探测 calResultTotal，选得分最高的。
        （因材料总数有限且跨菜谱共享，price_chef 高不等于全局总分高，需多试。）

    两个选项都使用 calResultTotal 作为比较基准，选更高的执行。
    """
    TOP_K = 2

    def __init__(self, page, verbose: bool = True):
        self.page = page
        self.verbose = verbose

        self.plan: dict = {}
        self.used_chefs: set = set()
        self.used_recipes: set = set()
        self.current_total: int = 0
        self.calculator_name: str = ""

    def log(self, msg: str):
        if self.verbose:
            print(msg)

    def find_best_new_slot(self) -> tuple:
        """
        选项A：新开一个厨师位。

        1. 读 calReps_list[new_slot]（无厨师时按基础分降序），取前 TOP_K 个未用菜谱
        2. 对每个菜谱：设菜谱 → getRecommendChef → 读排名第一的推荐厨师
        3. 对每个 (菜谱, 厨师) 对：设厨师+菜谱 → 读 calResultTotal → 清除现场
        4. 返回得分最高的 (calResultTotal, recipe, chef)
        """
        if len(self.plan) >= MAX_CHEFS:
            return (0, None, None)

        new_slot = len(self.plan) + 1

        # 阶段1：取前 TOP_K 个菜谱（无厨师时按基础分排序）
        recipe_list = read_recipe_list(self.page, new_slot, self.used_recipes)
        top_recipes = recipe_list[:self.TOP_K]
        if not top_recipes:
            return (0, None, None)

        # 阶段2：对每个菜谱，获取推荐厨师列表
        candidates = []  # [(recipe, [chef1, chef2, ...]), ...]
        for recipe in top_recipes:
            # 设菜谱（无厨师），触发 hasRep = true
            set_recipe(self.page, new_slot, 1, recipe["id"])
            time.sleep(0.3)
            # 触发厨师推荐排序
            trigger_chef_recommend(self.page, new_slot)
            # 读取排好序的厨师列表
            chefs = read_sorted_chefs(self.page, new_slot, self.used_chefs, limit=1)
            # 清除菜谱，恢复空 slot
            clear_recipe(self.page, new_slot, 1)
            time.sleep(0.2)
            if chefs:
                candidates.append((recipe, chefs))
                self.log(f"    菜谱[{recipe['name']}] 推荐厨师: {', '.join(c['name'] for c in chefs)}")
            else:
                self.log(f"    菜谱[{recipe['name']}] 无可用厨师")

        if not candidates:
            return (0, None, None)

        # 阶段3：逐个探测 (菜谱, 厨师) 对，读 calResultTotal
        best_score = 0
        best_recipe = None
        best_chef = None

        for recipe, chefs in candidates:
            for chef in chefs:
                # 设厨师
                set_chef(self.page, new_slot, chef["id"])
                time.sleep(0.3)
                wait_for_price_chef(self.page, new_slot)
                # 设菜谱
                set_recipe(self.page, new_slot, 1, recipe["id"])
                time.sleep(0.3)
                # 读总得分
                score = get_total_score(self.page)
                self.log(f"    菜谱[{recipe['name']}] x 厨师[{chef['name']}] -> 总分={score}")
                # 清除现场（clear_chef 同时清除所有菜谱）
                clear_chef(self.page, new_slot)
                time.sleep(0.2)

                if score > best_score:
                    best_score = score
                    best_recipe = recipe
                    best_chef = chef

        return (best_score, best_recipe, best_chef)

    def find_best_existing_slot(self) -> tuple:
        """
        选项B：现有厨师的空位添加菜谱。

        对每个有空位的 slot，取 calReps_list[slot] 前 TOP_K 个未用菜谱
        （已按 price_chef 降序排列），逐个探测 calResultTotal。
        因为材料总数有限，不同菜谱消耗不同材料，price_chef 高的菜谱
        可能大量消耗稀缺材料导致其他菜谱份数减少，所以需要多试。

        返回 (calResultTotal, recipe, slot, rep_num) 或 (0, None, None, None)
        """
        best_score = 0
        best_recipe = None
        best_slot = None
        best_rep_num = None

        for slot, slot_data in self.plan.items():
            if len(slot_data["recipes"]) >= MAX_REPS_PER_CHEF:
                continue
            rep_num = len(slot_data["recipes"]) + 1

            # 读 calReps_list[slot]（已按 price_chef 排序），取前 TOP_K 个未用菜谱
            recipe_list = read_recipe_list(self.page, slot, self.used_recipes)
            if not recipe_list:
                continue
            top_recipes = recipe_list[:self.TOP_K]

            for top_recipe in top_recipes:
                # 实际设菜谱，读 calResultTotal
                set_recipe(self.page, slot, rep_num, top_recipe["id"])
                time.sleep(0.3)
                score = get_total_score(self.page)
                self.log(f"    slot{slot} [{slot_data['chef']['name']}] + {top_recipe['name']} -> 总分={score}")
                # 清除探测的菜谱，恢复现场
                clear_recipe(self.page, slot, rep_num)
                time.sleep(0.2)

                if score > best_score:
                    best_score = score
                    best_recipe = top_recipe
                    best_slot = slot
                    best_rep_num = rep_num

        return (best_score, best_recipe, best_slot, best_rep_num)

    def commit_new_slot(self, chef: dict, recipe: dict):
        """提交新厨师+菜谱到下一个空 slot"""
        slot = len(self.plan) + 1
        set_chef(self.page, slot, chef["id"])
        time.sleep(0.3)
        wait_for_price_chef(self.page, slot)
        set_recipe(self.page, slot, 1, recipe["id"])
        time.sleep(0.3)
        self.plan[slot] = {"chef": chef, "recipes": [(1, recipe)]}
        self.used_chefs.add(chef["id"])
        self.used_recipes.add(recipe["id"])
        self.current_total = get_total_score(self.page)

    def commit_existing_slot(self, slot: int, rep_num: int, recipe: dict):
        """给现有厨师的空位添加菜谱"""
        set_recipe(self.page, slot, rep_num, recipe["id"])
        time.sleep(0.3)
        self.plan[slot]["recipes"].append((rep_num, recipe))
        self.used_recipes.add(recipe["id"])
        self.current_total = get_total_score(self.page)

    def run(self) -> dict:
        reset_calculator(self.page)
        self.plan = {}
        self.used_chefs = set()
        self.used_recipes = set()
        self.current_total = 0
        self.calculator_name = get_calculator_name(self.page)

        self.log("\n" + "=" * 60)
        if self.calculator_name:
            self.log(f"本期计算器: {self.calculator_name}")
        self.log("开始贪心求解...")
        self.log("=" * 60)

        # ── 第一个组合 ──
        self.log("\n[初始化] 寻找得分最高的第一道菜+厨师...")
        s1, r1, c1 = self.find_best_new_slot()
        if r1 is None:
            self.log("无法找到任何可行组合，请检查已有厨师/菜谱数据。")
            return {}

        self.commit_new_slot(c1, r1)
        self.log(f"  => 厨师[{c1['name']}] + 菜谱[{r1['name']}]  总分={self.current_total}")

        # ── 后续组合 ──
        iteration = 0
        while True:
            iteration += 1
            total_filled = sum(len(v["recipes"]) for v in self.plan.values())
            if total_filled >= MAX_CHEFS * MAX_REPS_PER_CHEF:
                self.log("\n所有格子已填满，结束。")
                break

            self.log(f"\n[轮次{iteration}] 总分={self.current_total}，已用{total_filled}格")

            # 选项A：新厨师位（如果还有空位）
            sA, rA, cA = self.find_best_new_slot()
            # 选项B：现有厨师加菜谱
            sB, rB, slotB, rnB = self.find_best_existing_slot()

            self.log(f"  选项A(新厨师): score={sA}  {rA['name'] if rA else 'N/A'} / {cA['name'] if cA else 'N/A'}")
            self.log(f"  选项B(现有厨师): score={sB}  {rB['name'] if rB else 'N/A'}")

            if len(self.plan) >= MAX_CHEFS:
                # 厨师位已满，只能选B
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

        return self._build_result()

    def _build_result(self) -> dict:
        result = {"plan": [], "total_score": self.current_total, "calculator_name": self.calculator_name}
        print("\n" + "=" * 60)
        if self.calculator_name:
            print(f"本期计算器: {self.calculator_name}")
        print(f"最终方案  总得分: {self.current_total}")
        print("=" * 60)
        for slot in sorted(self.plan.keys()):
            slot_data = self.plan[slot]
            chef = slot_data["chef"]
            recipes = slot_data["recipes"]
            chef_entry = {"chef": chef["name"], "chef_id": chef["id"], "recipes": []}
            print(f"\n厨师 {slot}: [{chef['name']}]")
            for rep_num, recipe in recipes:
                print(f"  菜谱{rep_num}: [{recipe['name']}]")
                chef_entry["recipes"].append({"name": recipe["name"], "id": recipe["id"]})
            empty = MAX_REPS_PER_CHEF - len(recipes)
            if empty > 0:
                print(f"  {'--'*10} ({empty} 个空位)")
            result["plan"].append(chef_entry)
        print(f"\n本期计算器: {self.calculator_name}")
        print(f"计算器真实总得分: {self.current_total}")
        print("=" * 60)
        return result


# ══════════════════════════════════════════════
#  主入口
# ══════════════════════════════════════════════

def has_cached_data(page) -> bool:
    """
    检测 localStorage 中是否已存有个人数据（厨师/菜谱已有标记）。
    网站把数据存在 localStorage 的 repGot / chefGot 键中。
    """
    result = page.evaluate("""
    (function(){
        try {
            // 网站把所有数据存在 localStorage.data 这个大 JSON 对象里
            var raw = localStorage.getItem('data');
            if (!raw) return false;
            var data = JSON.parse(raw);
            var repGot = data.repGot;
            var chefGot = data.chefGot;
            // repGot/chefGot 是对象（键为菜谱/厨师id），有任意一条数据即视为有缓存
            if (repGot && typeof repGot === 'object' && Object.keys(repGot).length > 0) return true;
            if (chefGot && typeof chefGot === 'object' && Object.keys(chefGot).length > 0) return true;
            return false;
        } catch(e) { return false; }
    })()
    """)
    return bool(result)


def main():
    parser = argparse.ArgumentParser(description="爆炒江湖 厨神贪心求解器")
    parser.add_argument("--code", type=str, default=USER_CODE, help="官方校验码（首次使用必填，之后自动缓存）")
    parser.add_argument("--no-headless", action="store_true", help="显示浏览器窗口（调试用）")
    parser.add_argument("--force-import", action="store_true", help="强制重新导入校验码，忽略缓存")
    args = parser.parse_args()

    code = args.code.strip()
    headless = not args.no_headless

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("请先安装 playwright：pip install playwright")
        print("然后安装浏览器：playwright install chromium")
        sys.exit(1)

    os.makedirs(BROWSER_PROFILE_DIR, exist_ok=True)
    print(f"浏览器数据目录: {BROWSER_PROFILE_DIR}")

    with sync_playwright() as pw:
        print(f"启动浏览器（headless={headless}）...")

        # 使用持久化 Context，localStorage 等数据会自动保存到 BROWSER_PROFILE_DIR
        context = pw.chromium.launch_persistent_context(
            user_data_dir=BROWSER_PROFILE_DIR,
            headless=headless,
            viewport={"width": 1280, "height": 900},
            user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15"
        )
        page = context.new_page()

        print(f"正在加载 {URL} ...")
        page.goto(URL, wait_until="networkidle", timeout=30000)

        # 关闭可能出现的提示弹窗
        try:
            page.locator(".el-dialog__headerbtn, .modal-close, button:has-text('关闭'), button:has-text('确定')").first.click(timeout=2000)
        except Exception:
            pass

        # 等待 Vue 应用加载
        page.wait_for_selector("#main", timeout=15000)
        time.sleep(2)

        # 导航到计算器
        nav_to_calculator(page)
        time.sleep(1)

        # 开启「只展示已有厨师菜谱」
        enable_got_only(page)

        # ── 判断是否需要（重新）导入校验码 ──
        cached = has_cached_data(page)
        if args.force_import or (code and not cached):
            if not code:
                print("本地无缓存数据，且未提供校验码，请通过 --code 参数传入校验码。")
                context.close()
                return
            print(f"{'强制重新' if args.force_import else '首次'}导入校验码数据...")
            import_user_data(page, code)
            nav_to_calculator(page)
            time.sleep(1)
            enable_got_only(page)
            time.sleep(0.5)
        elif cached:
            print("检测到本地缓存数据，跳过校验码导入，直接使用已有数据。")
            print("  如需强制重新导入，请加 --force-import 参数。")
        else:
            print("未提供校验码且无缓存数据，将使用计算器全量数据（不限于已有）。")

        # 确保计算器数据已加载
        print("正在加载计算器数据...")
        ensure_cal_loaded(page)

        # 运行贪心算法
        solver = GreedySolver(page, verbose=True)
        result = solver.run()

        if not args.no_headless:
            context.close()
        else:
            print("\n浏览器保持打开，可以手动查看最终结果。按 Enter 关闭...")
            input()
            context.close()


if __name__ == "__main__":
    main()

