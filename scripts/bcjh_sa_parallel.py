"""
爆炒江湖 并行模拟退火求解器
=============================================================
多进程调度包装，内部复用 bcjh_sa.py 的 SimulatedAnnealingSolver。
每个进程独立跑：贪心初始解 → 模拟退火（含精确校验 + 轻量爬山），取全局最优。

使用方法：
  python3 bcjh_sa_parallel.py --code 你的校验码
  python3 bcjh_sa_parallel.py                    # 使用缓存数据，自动按CPU核心数并行
  python3 bcjh_sa_parallel.py --workers 4        # 指定 4 个并行进程
  python3 bcjh_sa_parallel.py --sa-reheats 48    # 总48次重加热分配给各进程

参数与 bcjh_sa.py 保持一致（--sa-reheats, --sa-temp）。
仅增加 --workers 控制并行度，--sa-reheats 为总次数自动分配。

依赖：仅标准库（无第三方依赖）
"""

import argparse
import os
import random
import sys
import time as _time
from dataclasses import dataclass
from multiprocessing import Process, Queue
from typing import Optional

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from bcjh_calculator import Calculator
from bcjh_sa import (
    load_game_data, fetch_rules, fetch_user_data_from_api,
    save_user_cache, load_user_cache, USER_CODE,
    GameData, UserData,
    SimulatedAnnealingSolver,
)


@dataclass(slots=True)
class WorkerResult:
    """并行 SA 工作进程的返回结果"""
    worker_id: int
    score: int = 0
    compact: Optional[dict] = None  # {slot: SlotData}
    error: Optional[str] = None


# ══════════════════════════════════════════════
#  多进程 SA Worker
# ══════════════════════════════════════════════

def _sa_worker(worker_id, raw_data, food_god_rules, user_cache_dict,
               show_got, sa_params, seed, result_queue):
    """SA 工作进程：创建独立 Calculator，运行完整 SA"""
    try:
        random.seed(seed)

        gd = GameData(raw_data, food_god_rules)
        ud = UserData()
        if user_cache_dict:
            ud.import_from_cache(user_cache_dict, gd)

        calc = Calculator(gd, ud, show_got=show_got)

        solver = SimulatedAnnealingSolver(calc, verbose=False)
        solver.run(
            initial_temp=sa_params.get('initial_temp', 800),
            max_reheats=sa_params.get('max_reheats', 6),
        )

        best_compact = solver._plan_to_compact(solver.best_plan)
        result_queue.put(WorkerResult(
            worker_id=worker_id,
            score=solver.best_score,
            compact=best_compact,
        ))
    except Exception as e:
        import traceback
        result_queue.put(WorkerResult(
            worker_id=worker_id,
            error=traceback.format_exc(),
        ))


# ══════════════════════════════════════════════
#  主入口
# ══════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="爆炒江湖 并行模拟退火求解器（SA + 全面爬山，多进程并行）")
    parser.add_argument("--user-id", type=str, default="",
                        help="用户ID（隔离缓存）")
    parser.add_argument("--code", type=str, default=USER_CODE,
                        help="校验码")
    parser.add_argument("--force-import", action="store_true",
                        help="强制重新导入")
    parser.add_argument("--workers", type=int, default=0,
                        help="并行工作进程数（0=自动按CPU核心数，默认0）")
    parser.add_argument("--sa-reheats", type=int, default=0,
                        help="SA 总重加热次数（自动分配给各进程，0=每进程12次，默认0）")
    parser.add_argument("--sa-temp", type=float, default=800,
                        help="SA 初始温度（默认 800）")
    parser.add_argument("--time", type=str, default=None,
                        help="指定时间获取历史规则，格式 'YYYY-MM-DD' 或 'YYYY-MM-DD HH:MM:SS'")
    parser.add_argument("--rule-id", type=int, default=None,
                        help="指定规则ID")
    args = parser.parse_args()

    code = args.code.strip() if args.code else ""
    user_id = args.user_id.strip() if args.user_id else ""

    n_workers = args.workers if args.workers > 0 else (os.cpu_count() or 4)
    if args.sa_reheats > 0:
        reheats_per_worker = max(2, args.sa_reheats // n_workers)
    else:
        reheats_per_worker = 12  # 与 bcjh_sa.py 默认值一致

    print("=" * 60)
    print("  爆炒江湖 并行模拟退火求解器")
    print("  每进程: 贪心 → SA + 轻量爬山")
    print(f"  {n_workers} 进程并行，每进程 {reheats_per_worker} 次重加热")
    if user_id:
        print(f"  用户ID: {user_id}")
    print("=" * 60)

    # ── 1. 加载游戏数据 ──
    print("\n[1/4] 加载游戏数据...")
    raw_data = load_game_data()
    print(f"  菜谱: {len(raw_data['recipes'])}  厨师: {len(raw_data['chefs'])}  "
          f"厨具: {len(raw_data['equips'])}  遗玉: {len(raw_data['ambers'])}")

    # ── 2. 获取规则 ──
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
                print(f"  时间格式错误: {args.time}")
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
                print(f"  未找到 ID={args.rule_id}，使用第一条")
        print(f"  当前规则: {food_god_rules[0].get('Title', '未知')}")
    else:
        print("  未获取到厨神规则，使用正常营业模式")

    # ── 3. 处理数据 + 加载个人数据 ──
    print("\n[3/4] 处理数据 + 加载个人数据...")
    gd = GameData(raw_data, food_god_rules)
    print(f"  处理完成: {len(gd.recipes)} 菜谱, {len(gd.chefs)} 厨师, {len(gd.rules)} 规则")

    ud = UserData()
    cached = load_user_cache(user_id)
    has_user_data = False
    user_cache_dict = None

    if args.force_import or code:
        if not code:
            print("  无缓存且未提供校验码，请通过 --code 传入")
            sys.exit(1)
        print(f"  {'强制重新' if args.force_import else '首次'}导入校验码数据...")
        try:
            api_data = fetch_user_data_from_api(code)
            ud.import_from_api(api_data, gd)
            save_user_cache(ud.to_cache(), user_id)
            has_user_data = True
            user_cache_dict = ud.to_cache()
            print("  导入成功！")
        except Exception as e:
            print(f"  导入失败: {e}")
            sys.exit(1)
    elif cached:
        has_user_data = True
        user_cache_dict = cached
        ud.import_from_cache(cached, gd)
        print("  使用本地缓存数据")
    else:
        print("  未提供校验码且无缓存，将使用全量数据")

    has_got = sum(1 for v in ud.rep_got.values() if v)
    chef_got = sum(1 for v in ud.chef_got.values() if v)
    print(f"  已有菜谱: {has_got}, 已有厨师: {chef_got}")

    # ── 4. 初始化计算器 + 并行 SA ──
    print("\n[4/4] 初始化计算器...")
    calc = Calculator(gd, ud, show_got=has_user_data)
    print(f"  规则: {calc.get_calculator_name()}")
    print(f"  可用厨师: {len(calc.cal_chefs_list)}, 可用菜谱: {len(calc.cal_reps_all)}")

    # ══════════════════════════════════════════════
    #  并行 SA + 全面爬山
    # ══════════════════════════════════════════════
    sa_params = {
        'initial_temp': args.sa_temp,
        'max_reheats': reheats_per_worker,
    }

    print(f"\n{'=' * 60}")
    print(f"[并行SA] 启动 {n_workers} 个工作进程...")
    print(f"  每进程: SA {reheats_per_worker} 次重加热 (T={args.sa_temp})")
    print("=" * 60)

    start = _time.time()

    if n_workers == 1:
        # 单进程模式：直接运行，保留详细日志
        solver = SimulatedAnnealingSolver(calc, verbose=True)
        solver.run(
            initial_temp=sa_params['initial_temp'],
            max_reheats=sa_params['max_reheats'],
        )
        best_compact = solver._plan_to_compact(solver.best_plan)
        results = [WorkerResult(worker_id=0, score=solver.best_score,
                    compact=best_compact)]
    else:
        # 多进程模式
        result_queue = Queue()
        processes = []
        for i in range(n_workers):
            seed = random.randint(0, 2 ** 32 - 1)
            p = Process(target=_sa_worker, args=(
                i, raw_data, food_god_rules, user_cache_dict,
                has_user_data, sa_params, seed, result_queue
            ))
            processes.append(p)
            p.start()
            print(f"  启动工作进程 #{i} (seed={seed})")

        # 收集结果
        results = []
        timeout = max(300, reheats_per_worker * 60)
        for _ in range(n_workers):
            try:
                r = result_queue.get(timeout=timeout)
                results.append(r)
                if r.error:
                    print(f"  工作进程 #{r.worker_id} 出错:\n{r.error}")
                else:
                    print(f"  工作进程 #{r.worker_id} 完成: 得分={r.score}")
            except Exception as e:
                print(f"  等待超时: {e}")

        for p in processes:
            p.join(timeout=30)

    elapsed = _time.time() - start

    # ══════════════════════════════════════════════
    #  取最优结果
    # ══════════════════════════════════════════════
    valid_results = [r for r in results if r.compact is not None]
    if not valid_results:
        print("\n错误：所有工作进程均失败")
        sys.exit(1)

    best = max(valid_results, key=lambda x: x.score)
    best_compact = best.compact
    best_score = calc.apply_plan(best_compact, fast=False)

    print(f"\n{'=' * 60}")
    print(f"[汇总] {n_workers} 个 SA 进程完成，总耗时 {elapsed:.1f}s")
    if len(valid_results) > 1:
        scores = sorted([(r.worker_id, r.score) for r in valid_results])
        print(f"  各进程得分: {', '.join(f'#{w}={s}' for w, s in scores)}")
    print(f"  最终得分: {best_score}")
    print("=" * 60)

    # 打印最终方案
    solver_for_print = SimulatedAnnealingSolver(calc, verbose=True)
    plan = solver_for_print._compact_to_plan(best_compact)
    solver_for_print._print_plan(plan, "最终最优方案", best_score)


if __name__ == "__main__":
    main()
