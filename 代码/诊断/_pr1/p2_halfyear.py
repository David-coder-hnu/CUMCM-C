# -*- coding: utf-8 -*-
"""诊断：把成本按半年度拆开，看 PR#1 的「同组更优」是全年均匀的，还是集中在个别区段。"""
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

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
price_day = pd.read_excel(os.path.join(BASE, "附件", "附件1.xlsx")).iloc[:, 1].to_numpy(float)
load = pd.read_excel(os.path.join(BASE, "附件", "附件2.xlsx"), sheet_name="小区负载").iloc[:, 1:1 + N].to_numpy(float)
pv = pd.read_excel(os.path.join(BASE, "附件", "附件2.xlsx"), sheet_name="光伏发电实际功率").iloc[:, 1:1 + N].to_numpy(float)
price = np.tile(price_day, NDAYS)
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
    return res.x[G0:G0 + T]


def exec_causal(g):
    c = np.zeros(T); d = np.zeros(T); e = np.zeros(T); soc = SOC0
    for t in range(T):
        deficit = max(0.0, L[t] - P[t] - g[t])
        d[t] = min(deficit, P_MAX, max(0.0, (soc - SOC_MIN) * ETA / DT))
        c[t] = min(P_MAX, max(0.0, P[t] + g[t] + d[t] - L[t]), max(0.0, (SOC_MAX - soc) / (ETA * DT)))
        e[t] = max(0.0, L[t] - P[t] - g[t] - d[t])
        soc += (ETA * c[t] - d[t] / ETA) * DT
    return e


# 报告窗口 334 天，按前后两半拆（各 167 天）
rng = np.arange(REPORT, NDAYS)
half1 = np.zeros(T, bool); half2 = np.zeros(T, bool)
for di in rng[:167]: half1[di * N:(di + 1) * N] = True
for di in rng[167:]: half2[di * N:(di + 1) * N] = True

cfgs = [
    ("A same_weekday K=4", weekday_peers(4)),
    ("B group {Fri,Sat} [PR#1]", group_peers((2, 3))),
    ("C group {Sat,Sun}", group_peers((3, 4))),
    ("D same_weekday K=2", weekday_peers(2)),
]

print("=" * 100)
print("因果执行成本按半年度拆分（报告窗口 334 天 = 前167 + 后167）")
print("=" * 100)
print(f"{'配置':<26}{'全年':>15}{'前半(2-7月)':>15}{'后半(8-12月)':>15}")
print("-" * 100)
res = {}
for tag, peers in cfgs:
    g = solve_deliver(peers, 1.0)
    e = exec_causal(g)
    per = 5 * price * e * DT
    planned = price * g * DT
    tot = planned.sum() + per.sum()
    h1 = planned[half1].sum() + per[half1].sum()
    h2 = planned[half2].sum() + per[half2].sum()
    res[tag] = (tot, h1, h2)
    print(f"{tag:<26}{tot:>15,.0f}{h1:>15,.0f}{h2:>15,.0f}")
print("-" * 100)
b = res["A same_weekday K=4"]
for tag in list(res)[1:]:
    t, h1, h2 = res[tag]
    print(f"  {tag:<24}{t-b[0]:>+15,.0f}{h1-b[1]:>+15,.0f}{h2-b[2]:>+15,.0f}")
print()
print("（相对 A 基线的差；若「同组更优」是真实结构，两半都应显著为负）")
