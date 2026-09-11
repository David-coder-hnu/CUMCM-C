# -*- coding: utf-8 -*-
"""问题 2 归档 §7.6 需要的精确数：d̂ 的「缺口为零时放电」两种口径 + 严格执行 d̂ 的分项。

导入 problem2 会重跑并重写 结果/result2.xlsx（内容逐格相同，见 _p2_fresh_stats.py 说明）。
"""
import os, sys
import numpy as np
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
import problem2 as p

DT, N, NDAYS = p.DT, p.N, p.NDAYS
c_ex, d_ex, e_ex, soc_ex = p.execute_soc_causal(p.g1)
r_exec = p.honor_cost(p.g1, d_ex)


def exec_strict(d_hat):
    c = np.zeros(p.T); d = np.zeros(p.T); soc = np.empty(p.T + 1); soc[0] = p.SOC0
    for t in range(p.T):
        d[t] = min(d_hat[t], p.P_MAX, max(0.0, (soc[t] - p.SOC_MIN) * p.ETA / DT))
        surplus = max(0.0, p.P[t] + p.g1[t] + d[t] - p.L[t])
        c[t] = min(p.P_MAX, surplus, max(0.0, (p.SOC_MAX - soc[t]) / (p.ETA * DT)))
        soc[t + 1] = soc[t] + (p.ETA * c[t] - d[t] / p.ETA) * DT
    return c, d


print("=" * 92)
print(f"{'口径':<26}{'计划Σp·ĝ':>15}{'紧急费':>13}{'紧急kWh':>12}{'总费':>15}")
print("-" * 92)
for tag, sc in (("A1 同星期几 K=4", p.peers_wd), ("A3 分组 span6（交付）", p.peers)):
    g_, d_, cm_ = p.solve_deliver(1.0, sc)[:3]
    cX, dX, eX, socX = p.execute_soc_causal(g_)
    rC = p.honor_cost(g_, d_)          # 闭式（假设 d̂ 兑现）
    rX = p.honor_cost(g_, dX)          # 因果执行
    _, dS = exec_strict(d_)
    rS = p.honor_cost(g_, dS)          # 严格执行 d̂
    # 口径一：实际轨迹上「缺口为零时仍放电」
    act = np.maximum(0.0, d_ - np.maximum(0.0, p.L - p.P - g_))
    # 口径二：情景最坏下「不放电也能覆盖缺口」（q = min_ω(P−L)，与 soc_trace 同口径）
    q = np.empty(p.T)
    for dd in range(NDAYS):
        pp = p.sc_of(sc, dd)
        q[dd * N:(dd + 1) * N] = (p.pv[pp] - p.load[pp]).min(axis=0)
    cov = g_ + d_ + q >= p.L - p.P - 1e-9
    for nm, r in (("　闭式计划费(假设 d̂ 兑现)", rC), ("　→ 因果执行（交付口径）", rX),
                  ("　→ 严格执行 d̂", rS)):
        print(f"{tag+' '+nm:<26}{r[1]:>15,.0f}{r[2]:>13,.0f}{r[3]:>12,.0f}{r[0]:>15,.0f}")
    print(f"　'缺口为零时放电' 实际轨迹口径  {(act*DT).sum():>12,.0f} kWh ({(act*DT).sum()/(d_*DT).sum()*100:>4.1f}%)")
    kz = (d_ * DT)[cov & (d_ > 1e-9)].sum()
    print(f"　'缺口为零时放电' 情景最坏口径  {kz:>12,.0f} kWh ({kz/(d_*DT).sum()*100:>4.1f}%)")
    print(f"　严格执行 vs 因果执行  Δ总费 = {rS[0]-rX[0]:>+12,.0f} 元；"
          f"紧急 {rX[3]:,.0f} → {rS[3]:,.0f} kWh（{rS[3]-rX[3]:+,.0f}）")
print("=" * 92)
