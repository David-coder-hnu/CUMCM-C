# -*- coding: utf-8 -*-
"""临时诊断：检验 PR#1 的核心主张「周末/工作日分组场景集稳健优于同星期几」。

对照四组场景集：
  A same_weekday_K4  —— main 现基线（近 4 周同星期几）
  B group_pr         —— PR#1 原样（d%7 in (2,3) = 周五+周六 / 其余，近 2 周）
  C group_fix        —— 修正分组（周六+周日 / 其余，近 2 周）
  D same_weekday_K2  —— 近 2 周同星期几（**只换窗口不换分组**，用于隔离「更近」与「分组」）

两种执行层都算，避免用执行器差异冒充场景集差异：
  exec_causal —— main 的 execute_soc_causal（缺口驱动、逐槽因果）
  exec_honest —— PR 的 honest_sim（按计划 d̂ 放电，受 SOC 下限限幅）
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

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
price_day = pd.read_excel(os.path.join(BASE, "附件", "附件1.xlsx")).iloc[:, 1].to_numpy(float)
load = pd.read_excel(os.path.join(BASE, "附件", "附件2.xlsx"), sheet_name="小区负载").iloc[:, 1:1 + N].to_numpy(float)
pv = pd.read_excel(os.path.join(BASE, "附件", "附件2.xlsx"), sheet_name="光伏发电实际功率").iloc[:, 1:1 + N].to_numpy(float)
price = np.tile(price_day, NDAYS)
win = np.zeros(T, bool); win[REPORT * N:] = True
L = load.ravel(); P = pv.ravel()

# 2025-01-01 是周三 ⇒ d%7: 0=Wed 1=Thu 2=Fri 3=Sat 4=Sun 5=Mon 6=Tue
PEERS = {
    "A same_weekday_K4": lambda d: [d - 7 * k for k in range(1, 5) if d - 7 * k >= 0],
    "B group_pr(Fri+Sat/2wk)": None,
    "C group_fix(Sat+Sun/2wk)": None,
    "D same_weekday_K2": lambda d: [d - 7 * k for k in range(1, 3) if d - 7 * k >= 0],
}


def group_peers(weekend_dows, span=14):
    g_all = np.array([(d % 7) in weekend_dows for d in range(NDAYS)])
    return [[t for t in range(max(0, d - span), d) if g_all[t] == g_all[d]] for d in range(NDAYS)]


_B = group_peers((2, 3))
_C = group_peers((3, 4))
PEERS["B group_pr(Fri+Sat/2wk)"] = lambda d, gp=_B: gp[d]
PEERS["C group_fix(Sat+Sun/2wk)"] = lambda d, gp=_C: gp[d]


def solve_deliver(peers, gamma=1.0):
    base_e = np.zeros(NDAYS, dtype=np.int64)
    _c = 0
    for d in range(NDAYS):
        base_e[d] = _c; _c += max(1, len(peers[d])) * N
    E_total = _c

    def sc_idx(d):
        return peers[d] if peers[d] else [d]

    G0, D0, S0_, CM0, E0 = 0, T, 2 * T, 3 * T + 1, 4 * T + 1
    n_vars = E0 + E_total
    q = np.empty(T)
    for dd in range(NDAYS):
        p = sc_idx(dd)
        vals = pv[p] - load[p]
        q[dd * N:(dd + 1) * N] = np.quantile(vals, 1.0 - gamma, axis=0) if len(p) > 1 else vals[0]

    c_obj = np.zeros(n_vars); c_obj[G0:G0 + T] = price
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

    n1, n2 = T, E_total
    ur, uc, ud, ub = [], [], [], []
    ur += [t, t, t]; uc += [CM0 + t, G0 + t, D0 + t]
    ud += [np.ones(T), -np.ones(T), -np.ones(T)]; ub.append(q)
    for dd in range(NDAYS):
        for w, pd_ in enumerate(sc_idx(dd)):
            r = base_e[dd] + w * N
            rr = n1 + np.arange(r, r + N); tt = dd * N + np.arange(N)
            ur += [rr, rr, rr]; uc += [G0 + tt, D0 + tt, E0 + np.arange(r, r + N)]
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
    return x[G0:G0 + T], x[D0:D0 + T], x[CM0:CM0 + T], time.time() - t0


def exec_causal(g):
    """main/problem2.py 的 execute_soc_causal：缺口驱动。"""
    c = np.zeros(T); d = np.zeros(T); e = np.zeros(T)
    soc = SOC0
    for t in range(T):
        deficit = max(0.0, L[t] - P[t] - g[t])
        d[t] = min(deficit, P_MAX, max(0.0, (soc - SOC_MIN) * ETA / DT))
        surplus = max(0.0, P[t] + g[t] + d[t] - L[t])
        c[t] = min(P_MAX, surplus, max(0.0, (SOC_MAX - soc) / (ETA * DT)))
        e[t] = max(0.0, L[t] - P[t] - g[t] - d[t])
        soc += (ETA * c[t] - d[t] / ETA) * DT
    return c, d, e, soc


def exec_honest(g, cm, d_plan):
    """PR 的 honest_sim：按计划 d̂ 放电，受 SOC 下限限幅。"""
    soc = SOC0; e_o = np.zeros(T); curt = 0.0
    for t in range(T):
        dmax = max(0.0, (soc - SOC_MIN) * ETA / DT)
        dt_ = d_plan[t]
        if dt_ > dmax:
            curt += dt_ - dmax; dt_ = dmax
        ct_ = min(cm[t], max(0.0, P[t] + g[t] + dt_ - L[t]), max(0.0, (SOC_MAX - soc) / (ETA * DT)))
        e_o[t] = max(0.0, L[t] - P[t] - g[t] - dt_)
        soc += (ETA * ct_ - dt_ / ETA) * DT
    return e_o, curt * DT


def fee(g, e):
    return (price * g * DT)[win].sum() + (5 * price * e * DT)[win].sum()


print("=" * 108)
print("PR#1 场景集主张的对照检验（γ=1 可交付 LP，同一批代码，只换场景集）")
print("=" * 108)
rows = []
for tag, fn in PEERS.items():
    peers = [fn(d) for d in range(NDAYS)]
    g, d, cm, el = solve_deliver(peers, 1.0)
    e_closed = np.maximum(0.0, L - g - P - d)                 # 闭式（用 d̂）
    closed = fee(g, e_closed)
    _, _, e_c, soc_c = exec_causal(g)
    causal = fee(g, e_c)
    e_h, curt = exec_honest(g, cm, d)
    honest = fee(g, e_h)
    Pk = g * 6.0
    rows.append((tag, el, closed, causal, honest, Pk.max(), (Pk > 5000).sum(), e_h.sum() * DT, soc_c.min()))
    print(f"  {tag:<26} solve {el:>5.1f}s  n_scen/day ~{np.mean([len(fn(d)) for d in range(NDAYS)]):.1f}")

print()
print("%-26s %>20s".replace("%>20s", "") % "场景集", end="")
print(f"{'闭式(用d̂)':>16}{'因果执行':>16}{'PR诚实执行':>16}{'峰值kW':>12}{'>5000槽':>10}")
print("-" * 108)
base_c = rows[0][3]; base_h = rows[0][4]
for tag, el, closed, causal, honest, pk, ncap, ekwh, smin in rows:
    print(f"{tag:<26}{closed:>16,.0f}{causal:>16,.0f}{honest:>16,.0f}{pk:>12,.1f}{ncap:>10,}")
print("-" * 108)
print(f"{'（相对 A 基线）':<26}{'':>16}{'因果口径':>16}{'PR诚实口径':>16}")
for tag, el, closed, causal, honest, pk, ncap, ekwh, smin in rows[1:]:
    print(f"  {tag:<24}{'':>16}{causal-base_c:>+16,.0f}{honest-base_h:>+16,.0f}")
print()
print("执行层自检：main 因果执行器的 SOC 下界 = %.1f kWh（应 >= 1200）" % min(r[8] for r in rows))
