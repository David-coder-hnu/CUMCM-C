# -*- coding: utf-8 -*-
"""
问题2 —— 三种"替代算法"对比（均带 SOC 跟踪执行）：
  §3 完美预见（下界）          : 确定性 LP 用实际净负荷, 无场景
  §4 两阶段随机规划            : 直接最小化期望费用(场景集=同组/同星期几)
  §5 报童分位数(newsvendor)    : 净负荷预测取第 q 分位 → 确定性 LP(场景集=同组/同星期几)

场景集对比: 同组(周末/工作日,近2周) vs 同星期几(近4周)。
所有结算用 SOC 跟踪执行(proper_rollout), 修正简化结算"不可实现"的问题。
"""

import sys
import numpy as np
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import problem2_stochastic_group as PG


def make_net_forecast(peers, q):
    """报童分位数: 净负荷预测 N̂[d] = quantile_q(load[peers]-pv[peers], axis=0)。"""
    N_hat = np.empty((PG.NDAYS, PG.N))
    for d in range(PG.NDAYS):
        if peers[d]:
            net_peer = PG.load[peers[d]] - PG.pv[peers[d]]
            N_hat[d] = np.quantile(net_peer, q, axis=0)
        else:
            N_hat[d] = PG.mean_load - PG.mean_pv
    return N_hat.ravel()


def run_quantile(peers, q, tag):
    g, c, d, _ = PG.solve_full_year(make_net_forecast(peers, q))
    cost, em, d_act, c_act, e_act = PG.proper_rollout(g, d, c)
    print(f"  [{tag}] 报童分位数 q={q}: 正确执行 {cost:,.0f} 元, 紧急 {em:,.0f} kWh")
    return cost, em


if __name__ == "__main__":
    print("=" * 90)
    print("问题2 三种替代算法对比（SOC 跟踪执行）")
    print("=" * 90)

    # §3 完美预见（下界）
    g_pf, c_pf, d_pf, _ = PG.solve_full_year(PG.load.ravel() - PG.pv.ravel())
    cost_pf, em_pf, *_ = PG.proper_rollout(g_pf, d_pf, c_pf)
    print(f"  §3 完美预见(下界): {cost_pf:,.0f} 元, 紧急 {em_pf:,.0f} kWh\n")

    peers_wd = PG.build_peers_weekday()
    peers_grp = PG.build_peers_group()

    # §4 两阶段随机规划
    print("  §4 两阶段随机规划:")
    r_wd = PG.solve_stochastic(peers_wd, "同星期几")
    cost_sp_wd, em_sp_wd, *_ = PG.proper_rollout(r_wd[0], r_wd[1], r_wd[2])
    r_grp = PG.solve_stochastic(peers_grp, "同组")
    cost_sp_grp, em_sp_grp, *_ = PG.proper_rollout(r_grp[0], r_grp[1], r_grp[2])
    print(f"    同星期几: {cost_sp_wd:,.0f} 元 (紧急 {em_sp_wd:,.0f})")
    print(f"    同组    : {cost_sp_grp:,.0f} 元 (紧急 {em_sp_grp:,.0f})\n")

    # §5 报童分位数
    print("  §5 报童分位数(newsvendor):")
    qs = [0.5, 0.833, 0.9, 1.0]
    q_res = {}
    for q in qs:
        q_res[("同星期几", q)] = run_quantile(peers_wd, q, "同星期几")
        q_res[("同组", q)] = run_quantile(peers_grp, q, "同组")

    # 汇总
    print("\n" + "=" * 90)
    print(f"{'算法':<22}{'同星期几(元)':>16}{'同组(元)':>16}{'同组节省(元)':>16}")
    print("-" * 90)
    print(f"{'§4 两阶段随机规划':<22}{cost_sp_wd:>16,.0f}{cost_sp_grp:>16,.0f}"
          f"{cost_sp_wd - cost_sp_grp:>16,.0f}")
    for q in qs:
        cwd = q_res[("同星期几", q)][0]
        cgrp = q_res[("同组", q)][0]
        print(f"{'§5 报童分位数 q='+str(q):<22}{cwd:>16,.0f}{cgrp:>16,.0f}"
              f"{cwd - cgrp:>16,.0f}")
    print("-" * 90)
    print(f"{'§3 完美预见(下界)':<22}{cost_pf:>16,.0f}")

    # 每种算法内找最优分位
    print("\n  报童分位数·各场景集最优分位:")
    for tag in ["同星期几", "同组"]:
        best_q = min(qs, key=lambda q: q_res[(tag, q)][0])
        print(f"    {tag}: 最优 q={best_q}, 费用 {q_res[(tag, best_q)][0]:,.0f} 元")
