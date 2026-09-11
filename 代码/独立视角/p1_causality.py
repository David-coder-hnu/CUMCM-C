# -*- coding: utf-8 -*-
"""P1 吸收性核验：365 天联合 LP 的"非因果"到底值多少钱？

复核者 P1 的主张：problem2_stochastic.py 把全年 365 天放进同一个 LP，
跨日通过 SOC 与 SOC_T 耦合，因此不是逐日在线的因果策略。

本脚本量化这个耦合的经济价值：
  (a) 全年联合 LP（复刻 solve_full_year），S_0 = SOC_T = SOC0
  (b) 365 个互相独立的单日 LP，每天 S_0 = S_N = SOC0
(b) 的可行集是 (a) 的子集 ⇒ cost(b) ≥ cost(a)，差额 = 跨日调度自由度的价值。
关键前提：price = tile(price_day, 365)，各日电价剖面完全相同。

另外核验：预测构造里有多少天回退到了"全年均值"（= 未来信息）。
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

DT, ETA, P_MAX = 1.0 / 6.0, 0.9, 5000.0
SOC_MIN, SOC_MAX, SOC0 = 1200.0, 10800.0, 6000.0
N, NDAYS, REPORT = 144, 365, 31
BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

df1 = pd.read_excel(os.path.join(BASE, "附件", "附件1.xlsx"))
price_day = df1.iloc[:, 1].to_numpy(float)
dfL = pd.read_excel(os.path.join(BASE, "附件", "附件2.xlsx"), sheet_name="小区负载")
dfP = pd.read_excel(os.path.join(BASE, "附件", "附件2.xlsx"), sheet_name="光伏发电实际功率")
load = dfL.iloc[:, 1:1 + N].to_numpy(float)
pv = dfP.iloc[:, 1:1 + N].to_numpy(float)
mean_load, mean_pv = load.mean(axis=0), pv.mean(axis=0)

# ---------- 1) 未来信息泄漏的规模：多少天回退到全年均值 ----------
fb_L = [d for d in range(NDAYS)
        if not [d - 7 * k for k in range(1, 5) if d - 7 * k >= 0]]
fb_P = [d for d in range(NDAYS) if not (max(0, d - 7) < d)]
print("=" * 78)
print("1) 预测构造中的全年均值回退（= 使用了未来信息）")
print("=" * 78)
print(f"  负荷 L_hat 回退天数 : {len(fb_L)} 天 —— {fb_L}")
print(f"  光伏 P_hat 回退天数 : {len(fb_P)} 天 —— {fb_P}")
print(f"  报告窗口 win 从第 {REPORT} 天起 ⇒ 这些天{'全部在窗口外' if max(fb_L) < REPORT else '有落入窗口的'}")
print()

# 点预测（完全复刻 problem2_stochastic.py 的构造，含回退）
L_hat = np.empty_like(load)
for d in range(NDAYS):
    idx = [d - 7 * k for k in range(1, 5) if d - 7 * k >= 0]
    L_hat[d] = load[idx].mean(axis=0) if idx else mean_load
P_hat = np.empty_like(pv)
for d in range(NDAYS):
    lo = max(0, d - 7)
    P_hat[d] = pv[lo:d].mean(axis=0) if lo < d else mean_pv
NET = (L_hat - P_hat).ravel()
price = np.tile(price_day, NDAYS)


def year_lp(net):
    """全年联合 LP，复刻 solve_full_year：布局 g|c|d|s|SOC。"""
    T = net.size
    G0, C0, D0, S0, SI = 0, T, 2 * T, 3 * T, 4 * T
    nv = 5 * T + 1
    c = np.zeros(nv); c[G0:G0 + T] = price
    t = np.arange(T)
    rows = np.concatenate([t, t, t, t, T + t, T + t, T + t, T + t])
    cols = np.concatenate([G0 + t, C0 + t, D0 + t, S0 + t,
                           SI + t + 1, SI + t, C0 + t, D0 + t])
    dat = np.concatenate([np.ones(T), -np.ones(T), np.ones(T), -np.ones(T),
                          np.ones(T), -np.ones(T), -ETA * DT * np.ones(T), (DT / ETA) * np.ones(T)])
    A = sparse.coo_matrix((dat, (rows, cols)), shape=(2 * T, nv)).tocsr()
    b = np.concatenate([net, np.zeros(T)])
    bd = ([(0, None)] * T + [(0, P_MAX)] * T + [(0, P_MAX)] * T + [(0, None)] * T
          + [(SOC0, SOC0)] + [(SOC_MIN, SOC_MAX)] * (T - 1) + [(SOC0, SOC0)])
    r = linprog(c, A_eq=A, b_eq=b, bounds=bd, method="highs")
    assert r.success, r.message
    return r, r.x[G0:G0 + T], r.x[SI:SI + T + 1]


def day_lp(net_d, s_start, s_end):
    """单日 LP（独立），布局与全年版一致，长度 N。"""
    n = net_d.size
    G0, C0, D0, S0, SI = 0, n, 2 * n, 3 * n, 4 * n
    nv = 5 * n + 1
    c = np.zeros(nv); c[G0:G0 + n] = price_day
    t = np.arange(n)
    rows = np.concatenate([t, t, t, t, n + t, n + t, n + t, n + t])
    cols = np.concatenate([G0 + t, C0 + t, D0 + t, S0 + t,
                           SI + t + 1, SI + t, C0 + t, D0 + t])
    dat = np.concatenate([np.ones(n), -np.ones(n), np.ones(n), -np.ones(n),
                          np.ones(n), -np.ones(n), -ETA * DT * np.ones(n), (DT / ETA) * np.ones(n)])
    A = sparse.coo_matrix((dat, (rows, cols)), shape=(2 * n, nv)).tocsr()
    b = np.concatenate([net_d, np.zeros(n)])
    bd = ([(0, None)] * n + [(0, P_MAX)] * n + [(0, P_MAX)] * n + [(0, None)] * n
          + [(s_start, s_start)] + [(SOC_MIN, SOC_MAX)] * (n - 1) + [(s_end, s_end)])
    r = linprog(c, A_eq=A, b_eq=b, bounds=bd, method="highs")
    assert r.success, r.message
    return DT * r.fun          # 注意：与 year_lp 同样乘 DT，否则单位是 元/h


print("=" * 78)
print("2) 跨日耦合的经济价值：全年联合 LP  vs  365 个独立单日 LP")
print("=" * 78)
res_y, g_y, soc_y = year_lp(NET)
cost_a = DT * res_y.fun
midnight = soc_y[::N]
print(f"  (a) 全年联合 LP          : {cost_a:>16,.0f} 元")
print(f"      日界 SOC（午夜）分布 : min {midnight.min():,.1f} / max {midnight.max():,.1f} / "
      f"std {midnight.std():,.1f}  (SOC0 = {SOC0:,.0f})")
print(f"      偏离 SOC0 的天数     : {(np.abs(midnight - SOC0) > 1e-3).sum()} / {NDAYS}")

cost_b = 0.0
day_costs = []
for d in range(NDAYS):
    cd = day_lp(NET[d * N:(d + 1) * N], SOC0, SOC0)
    day_costs.append(cd)
    cost_b += cd
# 无储能基线：缺多少买多少（单日 LP 的可行解，故 cost_b 不可能超过它）
no_store = DT * (price * np.maximum(0.0, NET)).sum()
print(f"  (b) 365 个独立单日 LP    : {cost_b:>16,.0f} 元")
print(f"  (c) 无储能（买全部缺口） : {no_store:>16,.0f} 元   ← (b) 的可行解，故 cost_b ≤ cost_c")
print(f"      差额 (b) − (a)       : {cost_b - cost_a:>16,.0f} 元 "
      f"({(cost_b - cost_a) / cost_a * 100:.4f}%)")
print(f"  ▶ 跨日耦合的经济价值 = {cost_b - cost_a:,.0f} 元，占 {((cost_b - cost_a) / cost_a * 100):.3f}%")
print()

# ---------- 3) 若把回退改成"只用可得的历史"（严格因果），费用如何变 ----------
print("=" * 78)
print("3) 把全年均值回退换成严格因果的回退，对报告窗口的影响")
print("=" * 78)
L_hat2 = np.empty_like(load); P_hat2 = np.empty_like(pv)
for d in range(NDAYS):
    idx = [d - 7 * k for k in range(1, 5) if d - 7 * k >= 0]
    L_hat2[d] = load[idx].mean(axis=0) if idx else load[d]      # 无历史 → 退化为"昨天"
for d in range(NDAYS):
    lo = max(0, d - 7)
    P_hat2[d] = pv[lo:d].mean(axis=0) if lo < d else pv[d]
res_y2, g_y2, soc_y2 = year_lp((L_hat2 - P_hat2).ravel())
win = np.zeros(N * NDAYS, dtype=bool); win[REPORT * N:] = True
w1 = (price * g_y * DT)[win].sum(); w2 = (price * g_y2 * DT)[win].sum()
print(f"  含全年均值回退（原样）   窗口购电费: {w1:>14,.0f} 元")
print(f"  严格因果回退             窗口购电费: {w2:>14,.0f} 元")
print(f"  影响                     差额        : {w2 - w1:>14,.0f} 元")
