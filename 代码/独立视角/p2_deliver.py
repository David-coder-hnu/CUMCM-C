# -*- coding: utf-8 -*-
"""问题 2 独立复算：把"计划层"与"执行层"严格分开，并给出一条【可交付】的储能计划。

诊断（由 verify_p2.py 已证实，本脚本独立复现）：
    现交付 result2.xlsx 报 13,832,465 元，低于"同一 ĝ 下储能完美预见"的 15,347,211 元
    —— 任何因果执行都做不到，说明计划本身违反物理。

根因（本脚本的论点）：
    两阶段 SP 里 d̂ 是【一阶段】变量（日前承诺的放电功率），但 SOC 递推用的是
    【情景平均充电】E[c̄]。实际充电在缺电情景里被削到 0，所以实际 SOC 永远低于计划
    SOC ⇒ d̂ 里的电根本不存在的部分被"凭空放掉"。

本脚本给出的新模型 —— 【可交付储能计划 / deliverable schedule】：
    把 SOC 递推里的 E[c̄] 换成"对目标覆盖率 γ 的可得充电下确界"：
        c_t^min ≤ g_t + d_t + q_{γ,t},   q_{γ,t} = 情景集合 {P_ω,t − L_ω,t} 的 γ 分位
    γ=1 ⇒ 逐情景全部可交付（严格可行，计划层=执行层，无模拟歧义）；
    γ=0 ⇒ 最悲观情景，最保守。
    目标函数仍是 E[e] 的精确值（e 只依赖 (g,d)，不依赖 SOC），所以
    给定 (g,d) 的总费是【闭式】的，无需任何执行层模拟 —— 这消除了当前口径的歧义。

输出：γ 扫描 + 三个参照（完美预见 / 点预测 / 现 SP 计划）的诚实费用对照。

用法：python 代码/独立视角/p2_deliver.py
"""
import os
import sys
import time

import numpy as np
import pandas as pd
from scipy.optimize import linprog
from scipy import sparse

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

DT, ETA, P_MAX = 1.0 / 6.0, 0.9, 5000.0
SOC_MIN, SOC_MAX, SOC0 = 1200.0, 10800.0, 6000.0
N, NDAYS, REPORT = 144, 365, 31
T = N * NDAYS
K_PEERS = 4
BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

price_day = pd.read_excel(os.path.join(BASE, "附件", "附件1.xlsx")).iloc[:, 1].to_numpy(float)
load = pd.read_excel(os.path.join(BASE, "附件", "附件2.xlsx"), sheet_name="小区负载") \
         .iloc[:, 1:1 + N].to_numpy(float)
pv = pd.read_excel(os.path.join(BASE, "附件", "附件2.xlsx"), sheet_name="光伏发电实际功率") \
       .iloc[:, 1:1 + N].to_numpy(float)
price = np.tile(price_day, NDAYS)
win = np.zeros(T, bool); win[REPORT * N:] = True
L = load.ravel(); P = pv.ravel()

peers = [[d - 7 * k for k in range(1, K_PEERS + 1) if d - 7 * k >= 0] for d in range(NDAYS)]
base_e = np.zeros(NDAYS, dtype=np.int64)
_c = 0
for d in range(NDAYS):
    base_e[d] = _c
    _c += max(1, len(peers[d])) * N          # 场景数下限取 1（前 4 周退化为当日点预报）
E_total = _c


def sc_idx(d):
    """day d 的场景天列表；前 4 周无同星期几历史时退化为 [d] 本身（单情景）。"""
    return peers[d] if peers[d] else [d]


def honor_cost(g, d):
    """闭式诚实费用：e 只依赖 (g,d)，与 SOC 无关。返回 (总费, 计划费, 紧急费, 紧急kWh)。"""
    e = np.maximum(0.0, L - g - P - d)
    planned = (price * g * DT)[win].sum()
    emerg = (5 * price * e * DT)[win].sum()
    return planned + emerg, planned, emerg, (e * DT)[win].sum()


def soc_gap(g, d, cm):
    """实际 SOC 轨迹（充电按"最坏情景可交付"以外的部分会掉队）：
    这里用【全部情景里最小的可得充电】= min_ω surplus_ω 来保守重放，
    得到的是真实 SOC 的下界；用它检查 d̂ 是否可交付。
    返回 (最小 SOC, 不可交付的放电量 kWh)。"""
    surp_min = np.empty(T)
    for dd in range(NDAYS):
        p = sc_idx(dd)
        surp_min[dd * N:(dd + 1) * N] = (pv[p] - load[p]).min(axis=0)
    c_real = np.minimum(cm, np.maximum(0.0, g + d + surp_min))
    soc = SOC0 + np.cumsum(ETA * c_real * DT - d * DT / ETA)
    return soc.min(), np.nan


def solve_deliver(gamma):
    """γ 覆盖率下的可交付计划 LP。gamma=1 → q = min(情景 p−l)（全情景可交付）。"""
    G0, D0, S0_, CM0, E0 = 0, T, 2 * T, 3 * T + 1, 4 * T + 1
    n_vars = E0 + E_total
    q = np.empty(T)
    for dd in range(NDAYS):
        p = sc_idx(dd)
        # 必须用【裸】(P−L)，不能用 max(0, P−L)：后者在缺电时段给出 q=0，于是
        # cmin ≤ g+d 与 e ≥ L−P−g−d 同时成立 —— 同一份 g+d 既顶负载缺口又给电池充电，
        # 凭空造电（实测全年总费掉到 3,061,112 元，远低于完美预见下界 12,229,461 元）。
        vals = (pv[p] - load[p])                       # (nscen, 144)
        q[dd * N:(dd + 1) * N] = np.quantile(vals, 1.0 - gamma, axis=0) \
            if len(p) > 1 else vals[0]

    c_obj = np.zeros(n_vars)
    c_obj[G0:G0 + T] = price
    for dd in range(NDAYS):
        p = sc_idx(dd); Kd = len(p)
        for w in range(Kd):
            sl = slice(base_e[dd] + w * N, base_e[dd] + (w + 1) * N)
            c_obj[E0 + sl.start:E0 + sl.stop] = 5.0 * price_day / Kd

    t = np.arange(T)
    # SOC 递推：S_{t+1} − S_t − ηΔt·cmin_t + (Δt/η)·d_t = 0
    A_eq = sparse.coo_matrix(
        (np.concatenate([np.ones(T), -np.ones(T), -ETA * DT * np.ones(T), (DT / ETA) * np.ones(T)]),
         (np.concatenate([t, t, t, t]),
          np.concatenate([S0_ + t + 1, S0_ + t, CM0 + t, D0 + t]))),
        shape=(T, n_vars)).tocsr()

    # 不等式 (1) cmin − g − d ≤ q      (2) −g − d − e ≤ p − l
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


def solve_full_year(N_hat):
    """确定性全年 LP（完美预见 / 点预测共用骨架）。"""
    G0, C0, D0, S0_, S_idx = 0, T, 2 * T, 3 * T, 4 * T
    n_vars = 5 * T + 1
    c_obj = np.zeros(n_vars); c_obj[G0:G0 + T] = price
    t = np.arange(T)
    A_eq = sparse.coo_matrix(
        (np.concatenate([np.ones(T), -np.ones(T), np.ones(T), -np.ones(T),
                         np.ones(T), -np.ones(T), -ETA * DT * np.ones(T), (DT / ETA) * np.ones(T)]),
         (np.concatenate([t, t, t, t, T + t, T + t, T + t, T + t]),
          np.concatenate([G0 + t, C0 + t, D0 + t, S0_ + t,
                          S_idx + t + 1, S_idx + t, C0 + t, D0 + t]))),
        shape=(2 * T, n_vars)).tocsr()
    b_eq = np.concatenate([N_hat, np.zeros(T)])
    bounds = ([(0, None)] * T + [(0, P_MAX)] * T + [(0, P_MAX)] * T + [(0, None)] * T
              + [(SOC0, SOC0)] + [(SOC_MIN, SOC_MAX)] * (T - 1) + [(SOC0, SOC0)])
    res = linprog(c_obj, A_eq=A_eq, b_eq=b_eq, bounds=bounds, method="highs")
    assert res.success, res.message
    x = res.x
    return x[G0:G0 + T], x[C0:C0 + T], x[D0:D0 + T]


print("=" * 104)
print("问题 2 独立复算：可交付储能计划（deliverable schedule）")
print("=" * 104)

# ---- 参照 1：完美预见 ----
g_pf, c_pf, d_pf = solve_full_year(L - P)
r = honor_cost(g_pf, d_pf)
print(f"{'完美预见(下界)':<26}{r[1]:>14,.0f}{r[2]:>14,.0f}{r[3]:>16,.0f}{r[0]:>16,.0f}")

# ---- 参照 2：点预测（同星期几4周负荷 + 近7天光伏） ----
L_hat = np.empty_like(load)
for d in range(NDAYS):
    idx = peers[d]
    L_hat[d] = load[idx].mean(axis=0) if idx else load.mean(axis=0)
P_hat = np.empty_like(pv)
for d in range(NDAYS):
    lo = max(0, d - 7)
    P_hat[d] = pv[lo:d].mean(axis=0) if lo < d else pv.mean(axis=0)
g_pt, c_pt, d_pt = solve_full_year((L_hat - P_hat).ravel())
r = honor_cost(g_pt, d_pt)
print(f"{'点预测(负荷周几+光伏7天)':<26}{r[1]:>14,.0f}{r[2]:>14,.0f}{r[3]:>16,.0f}{r[0]:>16,.0f}")
pt_cost = r[0]

# ---- 参照 3：现交付的 SP 计划 ----
npz = os.environ.get("P2_NPZ", os.path.join(BASE, "p2_sp.npz"))
if os.path.exists(npz):
    z = np.load(npz)
    r = honor_cost(z["g"], z["d"])
    print(f"{'[现交付] SP 计划 (照抄 d̂)':<26}{r[1]:>14,.0f}{r[2]:>14,.0f}{r[3]:>16,.0f}{r[0]:>16,.0f}")

# ---- 新模型：γ 覆盖率扫描 ----
print("-" * 104)
print(f"{'γ 可交付覆盖率':<26}{'计划费(元)':>14}{'紧急费(元)':>14}{'紧急kWh':>16}{'总费(元)':>16}")
print("-" * 104)
best = None
for gamma in [float(x) for x in os.environ.get("GAMMAS", "0,0.25,0.5,0.75,1.0").split(",")]:
    g, d, cm, soc, el = solve_deliver(gamma)
    r = honor_cost(g, d)
    tag = f"γ={gamma:.2f}  ({el:.0f}s)"
    print(f"{tag:<26}{r[1]:>14,.0f}{r[2]:>14,.0f}{r[3]:>16,.0f}{r[0]:>16,.0f}")
    # 真实 SOC 下界检查：放电是否可交付
    if gamma >= 1.0 - 1e-9:
        smin, _ = soc_gap(g, d, cm)
        print(f"{'  └ 真实SOC下界':<26}{smin:>14,.1f} kWh  （应 ≥ 1200，否则计划仍不可交付）")
    if best is None or r[0] < best[0]:
        best = (r[0], gamma, g, d, cm, soc)

print("-" * 104)
print(f"最优 γ = {best[1]:.2f}，总费 {best[0]:,.0f} 元；点预测基线 {pt_cost:,.0f} 元，"
      f"相差 {pt_cost - best[0]:,.0f} 元 ({(pt_cost - best[0]) / pt_cost * 100:+.2f}%)")

if os.environ.get("SAVE_NPZ"):
    np.savez(os.environ["SAVE_NPZ"], g=best[2], d=best[3], cm=best[4], soc=best[5],
             gamma=best[1])
    print(f"[dump] γ*={best[1]} 的 (g,d,cmin,soc) 已写入 {os.environ['SAVE_NPZ']}")
