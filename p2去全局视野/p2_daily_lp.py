# -*- coding: utf-8 -*-
"""问题 2 —— 去掉「全年一次性联合求解」的单日 LP 对照（严格因果，无全局视野）。

背景
────
问题 2 的定稿代码（CUMCM-C/代码/problem2.py 的 solve_deliver）把 365 天一次性建成一个
联合 LP（T=52,560 个购电变量），并带年末锚 S_0 = S_T = 6000。这带来一个"全局视野"：
LP 知道全年长度、能把 365 天的 SOC 轨迹统筹在一起。它不是数据泄露（计划层只读过去
6 天同组历史日，不读未来负荷/光伏），但属于结构性前视。

本脚本把它改成严格在线：第 d 天 0:00，只用【过去 6 天同组历史日】作情景集 + 当日已知
起始 SOC，解一个 144 槽的单日 LP（SOC_0 = SOC_144 = 6000 单日能量中性，问题 1 条件②
口径），再用 execute_soc_causal 因果执行当天、SOC 传次日。据此量化"去掉全局视野"的代价。

口径与 problem2.py 逐字一致，唯一区别 = 单日 LP vs 全年联合 LP：
  · 低需求日分组：暖机期(前 31 天)日均净负荷最低的两天 = {周五, 周六}，回看 span=6
  · γ=1 可交付：q_t = min_ω(P_ω − L_ω)（裸 P−L，非 max(0,·)），约束 CM − G − D ≤ q
  · 目标：Σ p_t·ĝ_t + Σ (5p_t/K)·E_ω,t（应急期望 5 倍价）
  · 执行：逐槽贪婪 先放覆盖缺口→富余再充→仍缺才紧急，SOC 双向限幅 [1200,10800]
  · 结算口径 B：Σ p·ĝ + Σ 5p·e，统计窗口 2/1–12/31（前 31 天暖机）

用法
────
    python p2_daily_lp.py
输出：单日 LP 总费 vs 全年联合 LP 总费（REF_INF），及差额。
"""
import os
import sys

import numpy as np
import pandas as pd
from scipy.optimize import linprog
from scipy import sparse

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

# ── 参数（与 problem2.py 一致） ────────────────────────────────────────────
DT = 1.0 / 6.0
ETA = 0.9
P_MAX = 5000.0
SOC_MIN = 1200.0
SOC_MAX = 10800.0
SOC0 = 6000.0
N = 144
NDAYS = 365
REPORT = 31            # 计费窗口 2/1–12/31（1 月暖机）
ROBUST_SPAN = 6        # 情景回看窗口，与 problem2.GROUP_SPAN 对齐
T = N * NDAYS

# 参照值：全年联合 LP（problem2.py solve_deliver 定稿，本会话经 p2_gcap 自检复现 −0.01 元）
REF_INF = 13_846_553.26

# ── 数据（C题/附件，与 problem3_v3 同源） ─────────────────────────────────
BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
price_day = pd.read_excel(os.path.join(BASE, "附件", "附件1.xlsx")).iloc[:, 1].to_numpy(float)
load = pd.read_excel(os.path.join(BASE, "附件", "附件2.xlsx"),
                     sheet_name="小区负载").iloc[:, 1:1 + N].to_numpy(float)
pv = pd.read_excel(os.path.join(BASE, "附件", "附件2.xlsx"),
                   sheet_name="光伏发电实际功率").iloc[:, 1:1 + N].to_numpy(float)
price = np.tile(price_day, NDAYS)
L = load.ravel()
P = pv.ravel()
win = np.zeros(T, bool)
win[REPORT * N:] = True


# ── 低需求日分组 + 情景集（与 problem2.py 同规则，严格因果） ────────────────
def low_demand_dows(train_days):
    """按日均净负荷把七天分成{低需求日, 其余}，只喂暖机期(前 31 天)⟹ 无前视。"""
    nl = (load - pv).sum(axis=1)
    dw = np.array([d % 7 for d in range(NDAYS)])
    means = np.array([nl[train_days][dw[train_days] == k].mean() for k in range(7)])
    o = np.argsort(means)
    return int(o[0]), int(o[1])


def robust_peers():
    """第 d 天情景集 = 过去 ROBUST_SPAN 天内、与当日同组（低需求日）的历史日。"""
    dows = low_demand_dows(np.arange(0, REPORT))
    m = np.array([(d % 7) in dows for d in range(NDAYS)])
    return [[t for t in range(max(0, d - ROBUST_SPAN), d) if m[t] == m[d]]
            for d in range(NDAYS)]


# ── 因果执行器（= problem2.execute_soc_causal 的逐日版） ──────────────────
def exec_causal_day(d, g_day, soc):
    """按实测净需求贪婪充放电：先放覆盖缺口、富余再充、仍缺才紧急。返回 (c,d,e,soc_end)。"""
    c = np.zeros(N); d_ = np.zeros(N); e = np.zeros(N)
    for t in range(N):
        deficit = max(0.0, load[d, t] - pv[d, t] - g_day[t])
        d_max_soc = max(0.0, (soc - SOC_MIN) * ETA / DT)
        d_[t] = min(deficit, P_MAX, d_max_soc)
        surplus = max(0.0, pv[d, t] + g_day[t] + d_[t] - load[d, t])
        c_max_soc = max(0.0, (SOC_MAX - soc) / (ETA * DT))
        c[t] = min(P_MAX, surplus, c_max_soc)
        e[t] = max(0.0, load[d, t] - pv[d, t] - g_day[t] - d_[t])
        soc += (ETA * c[t] - d_[t] / ETA) * DT
    return c, d_, e, soc


# ── 单日 LP ────────────────────────────────────────────────────────────────
def solve_day_lp(d, soc_start, soc_end, pp):
    """第 d 天 144 槽单日 LP：只读历史同伴情景 + 当日已知起始 SOC，SOC_144 = soc_end。

    变量顺序（与 solve_deliver 一致）：G(N), D(N), S(N+1), CM(N), E(K*N)。
    返回当日计划购电功率 ĝ（N,）或 (None, 报错信息)。
    """
    p = pp[d] if pp[d] else [d]          # 与 solve_deliver 的 sc 一致（仅暖机第 1 天会自引用）
    K = len(p)

    G0, D0, S0_, CM0, E0 = 0, N, 2 * N, 3 * N + 1, 4 * N + 1
    n_vars = E0 + K * N

    vals = pv[p] - load[p]               # (K, N) 裸 (P−L)
    q = vals.min(axis=0)                 # γ=1 可交付下界

    c_obj = np.zeros(n_vars)
    c_obj[G0:G0 + N] = price_day
    for w in range(K):
        c_obj[E0 + w * N:E0 + (w + 1) * N] = 5.0 * price_day / K

    t = np.arange(N)
    # SOC 递推：S_{t+1} − S_t − ηΔt·CM_t + (Δt/η)·D_t = 0
    A_eq = sparse.coo_matrix(
        (np.concatenate([np.ones(N), -np.ones(N), -ETA * DT * np.ones(N), (DT / ETA) * np.ones(N)]),
         (np.concatenate([t, t, t, t]),
          np.concatenate([S0_ + t + 1, S0_ + t, CM0 + t, D0 + t]))),
        shape=(N, n_vars)).tocsr()

    # 可交付：CM − G − D ≤ q；应急（每情景 w）：−G − D − E_w ≤ P_w − L_w
    ur = [t, t, t]
    uc = [CM0 + t, G0 + t, D0 + t]
    ud = [np.ones(N), -np.ones(N), -np.ones(N)]
    ub = [q]
    for w in range(K):
        rr = N + np.arange(w * N, (w + 1) * N)
        ur += [rr, rr, rr]
        uc += [G0 + t, D0 + t, E0 + np.arange(w * N, (w + 1) * N)]
        ud += [-np.ones(N), -np.ones(N), -np.ones(N)]
        ub.append(vals[w])
    A_ub = sparse.coo_matrix((np.concatenate(ud), (np.concatenate(ur), np.concatenate(uc))),
                             shape=(N + K * N, n_vars)).tocsr()

    bounds = ([(0, None)] * N + [(0, P_MAX)] * N
              + [(soc_start, soc_start)] + [(SOC_MIN, SOC_MAX)] * (N - 1) + [(soc_end, soc_end)]
              + [(0, P_MAX)] * N + [(0, None)] * (K * N))

    res = linprog(c_obj, A_eq=A_eq, b_eq=np.zeros(N), A_ub=A_ub, b_ub=np.concatenate(ub),
                  bounds=bounds, method="highs")
    if not res.success:
        return None, res.message
    return res.x[G0:G0 + N], "ok"


def run_daily():
    """严格因果逐日：每天单日 LP 计划（SOC_0=SOC_144=6000）→ 因果执行 → SOC 传次日。"""
    pp = robust_peers()
    g_all = np.zeros((NDAYS, N))
    c_all = np.zeros((NDAYS, N)); d_all = np.zeros((NDAYS, N)); e_all = np.zeros((NDAYS, N))
    soc_tr = np.zeros(NDAYS + 1); soc_tr[0] = SOC0
    soc = SOC0
    for d in range(NDAYS):
        g_day, msg = solve_day_lp(d, SOC0, SOC0, pp)
        if g_day is None:
            return g_all, c_all, d_all, e_all, soc_tr, (d, msg)
        g_all[d] = g_day
        c, dd, e, soc = exec_causal_day(d, g_day, soc)
        c_all[d], d_all[d], e_all[d] = c, dd, e
        soc_tr[d + 1] = soc
    return g_all, c_all, d_all, e_all, soc_tr, None


def honor(g_f, d_f):
    """口径 B 结算：Σp·ĝ + Σ5p·e（e 由实际放电反算）。返回 (总, 计划, 紧急, 紧急kWh)。"""
    e = np.maximum(0.0, L - g_f - P - d_f)
    planned = (price * g_f * DT)[win].sum()
    emerg = (5 * price * e * DT)[win].sum()
    return planned + emerg, planned, emerg, (e * DT)[win].sum()


def report(tag, g_all, c_all, d_all, e_all, soc_tr):
    g_f = g_all.ravel(); d_f = d_all.ravel()
    r = honor(g_f, d_f)
    g_peak = g_f.max()
    n_over_win = int((g_f[win] > P_MAX + 1e-6).sum())
    s_g = (g_f * DT)[win].sum()
    em_kwh = (e_all.ravel() * DT)[win].sum()
    print("-" * 100)
    print(f"【{tag}】")
    print(f"  计划购电费 Σp·ĝ        {r[1]:>16,.2f} 元")
    print(f"  紧急购电费 Σ5p·e       {r[2]:>16,.2f} 元  ({em_kwh:,.0f} kWh)")
    print(f"  实际执行总费           {r[0]:>16,.2f} 元")
    print(f"  Σĝ 计划购电量          {s_g:>16,.0f} kWh")
    print(f"  计划 ĝ 峰值            {g_peak:>16,.2f} kW")
    print(f"  ĝ > 5000 槽数(报告窗)  {n_over_win:>15,} / {win.sum():,.0f}")
    print(f"  实际 SOC 范围          [{soc_tr.min():,.1f}, {soc_tr.max():,.1f}] kWh")
    print(f"  实际 SOC 首 / 末       {soc_tr[0]:,.1f} / {soc_tr[-1]:,.1f} kWh")
    return r


if __name__ == "__main__":
    print("=" * 100)
    print("问题 2 · 单日 LP（去掉全年联合求解） vs 全年联合 LP")
    print("=" * 100)

    print("▶ 单日 LP（每天独立锚定 6000）…")
    g_i, c_i, d_i, e_i, soc_i, bad = run_daily()
    if bad is None:
        r_daily = report("单日 LP（无全局视野）", g_i, c_i, d_i, e_i, soc_i)
    else:
        r_daily = None
        print(f"  ⚠ 不可行：day {bad[0]} → {bad[1]}")

    print()
    print("=" * 100)
    print("结论 · 去掉「全年联合 LP + 年末锚」前视的代价")
    print("-" * 100)
    if r_daily is not None:
        print(f"  单日 LP      {r_daily[0]:>14,.2f} 元")
        print(f"  全年联合 LP  {REF_INF:>14,.2f} 元")
        print(f"  差额         {r_daily[0] - REF_INF:>+14,.2f} 元 "
              f"({(r_daily[0] / REF_INF - 1) * 100:+.3f}%)")
    print("=" * 100)
