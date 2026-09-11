# -*- coding: utf-8 -*-
"""诊断：γ=1 可交付计划对「周末组包含哪几天」的敏感性。

2025-01-01 是周三 ⇒ d%7: 0=Wed 1=Thu 2=Fri 3=Sat 4=Sun 5=Mon 6=Tue。
PR#1 取 周末 = {Fri, Sat}（d%7 in (2,3)），于是 **周日被划进工作日组**。
本脚本扫描各种周末定义，看结论是否稳健。
"""
import os
import sys
import numpy as np
import pandas as pd
from scipy.optimize import linprog
from scipy import sparse

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DT, ETA, P_MAX = 1.0 / 6.0, 0.9, 5000.0
SOC_MIN, SOC_MAX, SOC0 = 1200.0, 10800.0, 6000.0
N, NDAYS, REPORT = 144, 365, 31
T = N * NDAYS
DOW = ["Wed", "Thu", "Fri", "Sat", "Sun", "Mon", "Tue"]

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
price_day = pd.read_excel(os.path.join(BASE, "附件", "附件1.xlsx")).iloc[:, 1].to_numpy(float)
load = pd.read_excel(os.path.join(BASE, "附件", "附件2.xlsx"), sheet_name="小区负载").iloc[:, 1:1 + N].to_numpy(float)
pv = pd.read_excel(os.path.join(BASE, "附件", "附件2.xlsx"), sheet_name="光伏发电实际功率").iloc[:, 1:1 + N].to_numpy(float)
price = np.tile(price_day, NDAYS)
win = np.zeros(T, bool); win[REPORT * N:] = True
L = load.ravel(); P = pv.ravel()


def group_peers(weekend_dows, span=14):
    g_all = np.array([(d % 7) in weekend_dows for d in range(NDAYS)])
    return [[t for t in range(max(0, d - span), d) if g_all[t] == g_all[d]] for d in range(NDAYS)]


def weekday_peers(k):
    return [[d - 7 * j for j in range(1, k + 1) if d - 7 * j >= 0] for d in range(NDAYS)]


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
    res = linprog(c_obj, A_eq=A_eq, b_eq=np.zeros(T), A_ub=A_ub, b_ub=np.concatenate(ub),
                  bounds=bounds, method="highs")
    assert res.success, res.message
    x = res.x
    return x[G0:G0 + T], x[D0:D0 + T], q


def exec_causal(g):
    c = np.zeros(T); d = np.zeros(T); e = np.zeros(T); soc = SOC0
    for t in range(T):
        deficit = max(0.0, L[t] - P[t] - g[t])
        d[t] = min(deficit, P_MAX, max(0.0, (soc - SOC_MIN) * ETA / DT))
        c[t] = min(P_MAX, max(0.0, P[t] + g[t] + d[t] - L[t]), max(0.0, (SOC_MAX - soc) / (ETA * DT)))
        e[t] = max(0.0, L[t] - P[t] - g[t] - d[t])
        soc += (ETA * c[t] - d[t] / ETA) * DT
    return e


cfgs = [
    ("A same_weekday K=4 (baseline)", weekday_peers(4)),
    ("  weekend = {Fri,Sat}  [PR#1]", group_peers((2, 3))),
    ("  weekend = {Sat,Sun}  [fixed]", group_peers((3, 4))),
    ("  weekend = {Sun}", group_peers((4,))),
    ("  weekend = {Sat}", group_peers((3,))),
    ("  weekend = {Fri,Sun}", group_peers((2, 4))),
    ("  weekend = {Fri,Sat,Sun}", group_peers((2, 3, 4))),
    ("  weekend = {} (all one group)", group_peers(())),
    ("D same_weekday K=2", weekday_peers(2)),
]

print("=" * 112)
print("γ=1 可交付计划对「周末组定义」的敏感性  (2025-01-01 = 周三)")
print("=" * 112)
print(f"{'配置':<32}{'计划费':>15}{'紧急费(闭式)':>15}{'闭式合计':>15}{'因果执行':>15}{'min q (kW)':>13}")
print("-" * 112)
base = None
for tag, peers in cfgs:
    g, d, q = solve_deliver(peers, 1.0)
    planned = (price * g * DT)[win].sum()
    e_cl = np.maximum(0.0, L - g - P - d)
    emerg = (5 * price * e_cl * DT)[win].sum()
    causal = planned + (5 * price * exec_causal(g) * DT)[win].sum()
    if base is None:
        base = causal
    print(f"{tag:<32}{planned:>15,.0f}{emerg:>15,.0f}{planned+emerg:>15,.0f}{causal:>15,.0f}{q.min():>13,.1f}")
print("-" * 112)
print("DOW 映射 d%7:", ", ".join(f"{i}={n}" for i, n in enumerate(DOW)))
