# -*- coding: utf-8 -*-
"""
问题2 —— γ=1 可交付储能计划（独立复核 §4 的"最佳正确方案"）：
  同星期几(近4周) vs 同组(周末/工作日,近2周) 场景集对比。

算法(源自 CUMCM-C/代码/独立视角/p2_deliver.py)：
  把 SOC 递推里的"情景平均充电 E[c̄]"换成"对覆盖率 γ 的可得充电下确界 cmin"：
      cmin_t − g_t − d_t ≤ q_{γ,t},   q_{γ,t} = 情景集 {P−L} 的 (1−γ) 分位
  γ=1 ⇒ q = min_ω(P−L)，全情景可交付（计划层=执行层，无模拟歧义）。
  目标仍是 E[e] 的精确闭式值（e 只依赖 (g,d)，与 SOC 无关）。

对每个场景集输出：
  (1) 情景内闭式费用 honor_cost（γ=1 的可交付口径）；
  (2) 诚实执行费用 honest_sim（逐槽 SOC 递推 + 放电受 SOC 下限限幅，全年实测）。
"""

import os
import sys
import time
import numpy as np
import pandas as pd
from scipy.optimize import linprog
from scipy import sparse

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DT, ETA, P_MAX = 1.0 / 6.0, 0.9, 5000.0
SOC_MIN, SOC_MAX, SOC0 = 1200.0, 10800.0, 6000.0
N, NDAYS, REPORT = 144, 365, 31
T = N * NDAYS
K_PEERS = 4

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(BASE))), "CUMCM-C", "附件")

price_day = pd.read_excel(os.path.join(DATA, "附件1.xlsx")).iloc[:, 1].to_numpy(float)
load = pd.read_excel(os.path.join(DATA, "附件2.xlsx"), sheet_name="小区负载").iloc[:, 1:1 + N].to_numpy(float)
pv = pd.read_excel(os.path.join(DATA, "附件2.xlsx"), sheet_name="光伏发电实际功率").iloc[:, 1:1 + N].to_numpy(float)
price = np.tile(price_day, NDAYS)
win = np.zeros(T, bool); win[REPORT * N:] = True
L = load.ravel(); P = pv.ravel()


def group_mask(d):
    return (d % 7) in (2, 3)   # 周末组=周五+周六


def build_peers_weekday():
    return [[d - 7 * k for k in range(1, K_PEERS + 1) if d - 7 * k >= 0] for d in range(NDAYS)]


def build_peers_group():
    g_all = np.array([group_mask(d) for d in range(NDAYS)])
    return [[t for t in range(max(0, d - 14), d) if g_all[t] == group_mask(d)] for d in range(NDAYS)]


def honor_cost(g, d):
    """闭式诚实费用：e 只依赖 (g,d)。"""
    e = np.maximum(0.0, L - g - P - d)
    planned = (price * g * DT)[win].sum()
    emerg = (5 * price * e * DT)[win].sum()
    return planned + emerg, planned, emerg, (e * DT)[win].sum()


def honest_sim(g, c, d):
    """诚实执行：SOC 逐槽递推 + 放电受 SOC 下限限幅 + 充电受实际富余/上限限幅。"""
    soc = SOC0
    e_o = np.zeros(T); curt = 0.0
    for t in range(T):
        dmax = max(0.0, (soc - SOC_MIN) * ETA / DT)
        dt_ = d[t]
        if dt_ > dmax:
            curt += dt_ - dmax
            dt_ = dmax
        cmax_soc = max(0.0, (SOC_MAX - soc) / (ETA * DT))
        ct_ = min(c[t], max(0.0, P[t] + g[t] + dt_ - L[t]), cmax_soc)
        e_o[t] = max(0.0, L[t] - g[t] - P[t] - dt_)
        soc += (ETA * ct_ - dt_ / ETA) * DT
    return e_o, curt


def solve_deliver(peers, gamma):
    """γ 覆盖率下的可交付计划 LP（源自 p2_deliver.py）。"""
    base_e = np.zeros(NDAYS, dtype=np.int64)
    _c = 0
    for d in range(NDAYS):
        base_e[d] = _c
        _c += max(1, len(peers[d])) * N
    E_total = _c

    def sc_idx(d):
        return peers[d] if peers[d] else [d]

    G0, D0, S0_, CM0, E0 = 0, T, 2 * T, 3 * T + 1, 4 * T + 1
    n_vars = E0 + E_total

    q = np.empty(T)
    for dd in range(NDAYS):
        p = sc_idx(dd)
        vals = (pv[p] - load[p])
        q[dd * N:(dd + 1) * N] = np.quantile(vals, 1.0 - gamma, axis=0) if len(p) > 1 else vals[0]

    c_obj = np.zeros(n_vars)
    c_obj[G0:G0 + T] = price
    for dd in range(NDAYS):
        p = sc_idx(dd); Kd = len(p)
        for w in range(Kd):
            sl = slice(base_e[dd] + w * N, base_e[dd] + (w + 1) * N)
            c_obj[E0 + sl.start:E0 + sl.stop] = 5.0 * price_day / Kd

    t = np.arange(T)
    A_eq = sparse.coo_matrix(
        (np.concatenate([np.ones(T), -np.ones(T), -ETA * DT * np.ones(T), (DT / ETA) * np.ones(T)]),
         (np.concatenate([t, t, t, t]),
          np.concatenate([S0_ + t + 1, S0_ + t, CM0 + t, D0 + t]))),
        shape=(T, n_vars)).tocsr()

    n1 = T
    n2 = E_total
    ur, uc, ud, ub = [], [], [], []
    ur += [t, t, t]
    uc += [CM0 + t, G0 + t, D0 + t]
    ud += [np.ones(T), -np.ones(T), -np.ones(T)]
    ub.append(q)
    for dd in range(NDAYS):
        for w, pd_ in enumerate(sc_idx(dd)):
            r = base_e[dd] + w * N
            rr = n1 + np.arange(r, r + N)
            tt = dd * N + np.arange(N)
            ur += [rr, rr, rr]
            uc += [G0 + tt, D0 + tt, E0 + np.arange(r, r + N)]
            ud += [-np.ones(N), -np.ones(N), -np.ones(N)]
            ub.append(pv[pd_] - load[pd_])
    A_ub = sparse.coo_matrix((np.concatenate(ud), (np.concatenate(ur), np.concatenate(uc))),
                             shape=(n1 + n2, n_vars)).tocsr()

    bounds = ([(0, None)] * T + [(0, P_MAX)] * T
              + [(SOC0, SOC0)] + [(SOC_MIN, SOC_MAX)] * (T - 1) + [(SOC0, SOC0)]
              + [(0, P_MAX)] * T + [(0, None)] * E_total)
    t0 = time.time()
    res = linprog(c_obj, A_eq=A_eq, b_eq=np.zeros(T), A_ub=A_ub, b_ub=np.concatenate(ub),
                  bounds=bounds, method="highs")
    assert res.success, res.message
    x = res.x
    return x[G0:G0 + T], x[D0:D0 + T], x[CM0:CM0 + T], x[S0_:S0_ + T + 1], time.time() - t0


if __name__ == "__main__":
    print("=" * 96)
    print("问题2 γ=1 可交付储能计划：同星期几 vs 同组 场景集对比")
    print("=" * 96)

    results = {}
    for tag, builder in [("同星期几(近4周)", build_peers_weekday),
                         ("同组(周末/工作日,近2周)", build_peers_group)]:
        peers = builder()
        g, d, cm, soc, el = solve_deliver(peers, 1.0)   # γ=1 全情景可交付
        # (1) 情景内闭式费用
        tot, pl, em, emk = honor_cost(g, d)
        # (2) 诚实执行(全年实测)
        e_o, curt = honest_sim(g, cm, d)
        cost_honest = (price * g * DT)[win].sum() + (5 * price * e_o * DT)[win].sum()
        em_honest = (e_o * DT)[win].sum()
        results[tag] = dict(g=g, d=d, cm=cm, tot=tot, pl=pl, em=em, emk=emk,
                            cost_honest=cost_honest, em_honest=em_honest, curt=curt * DT)
        print(f"\n【{tag}】 求解 {el:.1f}s")
        print(f"  情景内闭式费用 : {tot:,.0f} 元 (计划费 {pl:,.0f} + 紧急费 {em:,.0f}, 紧急 {emk:,.0f} kWh)")
        print(f"  诚实执行(全年实测): {cost_honest:,.0f} 元 (紧急 {em_honest:,.0f} kWh, 放电被限 {curt*DT:,.0f} kWh)")

    print("\n" + "=" * 96)
    print(f"{'场景集':<22}{'情景内闭式费用(元)':>20}{'诚实执行费用(元)':>20}")
    print("-" * 96)
    for tag in ["同星期几(近4周)", "同组(周末/工作日,近2周)"]:
        print(f"{tag:<22}{results[tag]['tot']:>20,.0f}{results[tag]['cost_honest']:>20,.0f}")
    print("-" * 96)
    d_tot = results["同星期几(近4周)"]["tot"] - results["同组(周末/工作日,近2周)"]["tot"]
    d_hon = results["同星期几(近4周)"]["cost_honest"] - results["同组(周末/工作日,近2周)"]["cost_honest"]
    print(f"同组相对同星期几：情景内节省 {d_tot:,.0f} 元 ({d_tot/results['同星期几(近4周)']['tot']*100:+.2f}%)，"
          f"诚实执行节省 {d_hon:,.0f} 元 ({d_hon/results['同星期几(近4周)']['cost_honest']*100:+.2f}%)")
