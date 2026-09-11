# -*- coding: utf-8 -*-
"""诊断：把「诚实执行」相对「闭式」的差额分解开，看两套执行器到底差在哪。

同一份 γ=1 计划 (g, d̂, cmin)，依次施加越来越强的执行约束：
  V0 closed       d = d̂                        —— 闭式口径（假设 d̂ 足额兑现）
  V1 deficit_cap  d = min(d̂, 实际缺口)          —— 只加「不往富余里放电」
  V2 soc_cap      d = min(d̂, SOC下限允许)       —— 只加「放电受 SOC 下限限幅」
  V3 honest       d = min(d̂, SOC限)，c 受实际富余限幅  —— PR 的 honest_sim
  V4 causal       d = min(实际缺口, SOC限)，c 受富余限幅 —— main 的 execute_soc_causal
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
    return x[G0:G0 + T], x[D0:D0 + T], x[CM0:CM0 + T]


def variants(g, d_hat, cm):
    """逐槽递推，返回每个变体的 (紧急 kWh, 被削放电 kWh, 循环充电 kWh)。"""
    deficit = np.maximum(0.0, L - P - g)
    out = {}

    def run(mode):
        soc = SOC0; e = np.zeros(T); curt = 0.0; cyc = 0.0
        for t in range(T):
            room_d = max(0.0, (soc - SOC_MIN) * ETA / DT)
            if mode == "V0":
                d = d_hat[t]
            elif mode == "V1":
                d = min(d_hat[t], deficit[t])
            else:
                d = min(d_hat[t], room_d)
            if d < d_hat[t] - 1e-12 and mode in ("V1", "V2", "V3"):
                curt += d_hat[t] - d
            if mode in ("V3", "V4") and d < deficit[t] - 1e-9:
                pass
            if mode == "V4":
                d = min(deficit[t], P_MAX, room_d)
            # 若「不该放电时放电」，多出的量会进富余、随后被充回，记作循环损失
            if mode in ("V0", "V1", "V2"):
                cyc += max(0.0, d - deficit[t])
            surplus = max(0.0, P[t] + g[t] + d - L[t])
            room_c = max(0.0, (SOC_MAX - soc) / (ETA * DT))
            if mode == "V0":
                c = cm[t]
            elif mode == "V2":
                c = min(cm[t], room_c)
            else:
                c = min(cm[t], surplus, room_c) if mode == "V3" else min(P_MAX, surplus, room_c)
            e[t] = max(0.0, L[t] - P[t] - g[t] - d)
            soc += (ETA * c - d / ETA) * DT
        return e, curt, cyc

    for mode in ("V0", "V1", "V2", "V3", "V4"):
        e, curt, cyc = run(mode)
        out[mode] = dict(cost=(price * g * DT)[win].sum() + (5 * price * e * DT)[win].sum(),
                         ekwh=(e * DT)[win].sum(), curt=curt * DT, cyc=cyc * DT)
    return out


NAMES = {"V0": "V0 closed (d=d̂)", "V1": "V1 +不向富余放电", "V2": "V2 +放电受SOC限",
         "V3": "V3 +充电受富余限 (PR honest)", "V4": "V4 缺口驱动 (main causal)"}

for tag, peers in [("A 同星期几 K=4 (main 基线)", weekday_peers(4)),
                   ("B {Fri,Sat} (PR#1)", group_peers((2, 3)))]:
    g, d, cm = solve_deliver(peers, 1.0)
    r = variants(g, d, cm)
    print("=" * 96)
    print(tag)
    print("=" * 96)
    print(f"{'执行口径':<34}{'总费(元)':>16}{'紧急kWh':>14}{'被削放电kWh':>14}{'循环放kWh':>13}")
    print("-" * 96)
    base = None
    for m in ("V0", "V1", "V2", "V3", "V4"):
        v = r[m]
        if base is None: base = v["cost"]
        print(f"{NAMES[m]:<34}{v['cost']:>16,.0f}{v['ekwh']:>14,.0f}{v['curt']:>14,.0f}{v['cyc']:>13,.0f}")
    print("-" * 96)
    print(f"  V0→V4 总差 {r['V4']['cost']-r['V0']['cost']:+,.0f} 元 "
          f"｜ V0→V2(SOC泄漏) {r['V2']['cost']-r['V0']['cost']:+,.0f} "
          f"｜ V2→V4(执行器) {r['V4']['cost']-r['V2']['cost']:+,.0f}")
    print()
