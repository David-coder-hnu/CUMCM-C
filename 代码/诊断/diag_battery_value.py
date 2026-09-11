# -*- coding: utf-8 -*-
"""诊断：问题 2 里电池到底值多少钱？

背景：扫描发现 Q_ALL=0.80 是执行成本的最小值点，而 0.80 恰好是「完全不用电池」时
报童逻辑给出的最优分位（临界比 p/(5p) = 0.2 → 0.80 分位）。这个巧合必须查清：
如果"不用电池"的报童最优成本 ≈ 带电池的 LP+执行成本，那么电池在本问题里近乎空转，
整个执行层/滚动 MPC 的复杂度就是白加的。

本脚本只读附件与导出的计划，独立重算三件事：
  1. 纯报童（不用电池）：ĝ_q(t) = 0:00 预报 + 残差 q 分位，成本 = Σp·ĝ + 5Σp·max(0,N−ĝ)
     → 扫 q 找最小值，这是「不用电池」的最优。
  2. 给定 SP 的 ĝ、但完全不调度电池（d=c=0）的成本。
  3. 用同一 ĝ 的完美预见电池下界（对照）。

用法：python 代码/诊断/diag_battery_value.py [p2.npz 路径]
"""
import os
import sys

import numpy as np
import pandas as pd

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

DT, N, NDAYS, REPORT, K_PEERS = 1.0 / 6.0, 144, 365, 31, 4
T = N * NDAYS
BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # 代码/诊断/ → 项目根

price_day = pd.read_excel(os.path.join(BASE, "附件", "附件1.xlsx")).iloc[:, 1].to_numpy(float)
load = pd.read_excel(os.path.join(BASE, "附件", "附件2.xlsx"), sheet_name="小区负载") \
         .iloc[:, 1:1 + N].to_numpy(float)
pv = pd.read_excel(os.path.join(BASE, "附件", "附件2.xlsx"), sheet_name="光伏发电实际功率") \
       .iloc[:, 1:1 + N].to_numpy(float)
fc3 = pd.read_excel(os.path.join(BASE, "附件", "附件3.xlsx"), header=None) \
        .iloc[1:, 2:].to_numpy(float).reshape(NDAYS, 4, 24)

price = np.tile(price_day, NDAYS)
win = np.zeros(T, bool); win[REPORT * N:] = True
win2 = win.reshape(NDAYS, N)

mean_load = load.mean(axis=0)
L_base = np.empty_like(load)
for d in range(NDAYS):
    idx = [d - 7 * k for k in range(1, K_PEERS + 1) if d - 7 * k >= 0]
    L_base[d] = load[idx].mean(axis=0) if idx else mean_load

W = np.zeros((N, 25))
for k in range(N):
    t = (k + 1) / 6.0
    lo = int(np.floor(t)); hi = min(int(np.ceil(t)), 24)
    if lo == hi:
        W[k, lo] = 1.0
    else:
        W[k, lo] = 1.0 - (t - lo); W[k, hi] = t - lo


def pv_fc(d, s_idx, s_hour):
    H = np.zeros(25)
    if s_hour > 0:
        H[s_hour] = pv[d, 6 * s_hour]
    for h in range(s_hour + 1, 25):
        H[h] = fc3[d, s_idx, h - s_hour - 1]
    return H @ W.T


P_hat = np.stack([[pv_fc(d, s, [0, 6, 12, 18][s]) for s in range(4)] for d in range(NDAYS)])
F_hat = L_base[:, None, :] - P_hat
actual_net = load - pv
resid = actual_net[:, None, :] - F_hat

Ntot = actual_net.ravel()                       # 实际净需求
pw = price.ravel()


def no_batt_cost(ghat_flat):
    """ĝ 定死、完全不调度电池：成本 = Σp·ĝ + 5Σp·max(0, N−ĝ)"""
    e = np.maximum(0.0, Ntot - ghat_flat)
    return ((pw * ghat_flat * DT)[win].sum() + (5 * pw * e * DT)[win].sum(),
            (e * DT)[win].sum())


print("=" * 78)
print("问题 2：电池价值诊断（统计窗口 2/1–12/31）")
print("=" * 78)
print(f"窗口内实际净需求 ΣN = {(Ntot*DT)[win].sum():,.0f} kWh")

print("\n--- 1. 纯报童（不用电池），ĝ = 0:00 预报 + 残差 q 分位 ---")
print(f"    {'q':>6}{'Σĝ (kWh)':>16}{'紧急 (kWh)':>15}{'总费 (元)':>18}")
best = (None, 1e18)
for q in [0.50, 0.60, 0.70, 0.74, 0.78, 0.80, 0.82, 0.86, 0.90, 0.95, 0.99]:
    HEDGE = np.quantile(resid[:, 0, :], q, axis=0)
    ghat = np.maximum(0.0, F_hat[:, 0, :] + HEDGE[None, :]).ravel()
    c, e = no_batt_cost(ghat)
    if c < best[1]:
        best = (q, c)
    print(f"    {q:>6.2f}{(ghat*DT)[win].sum():>16,.0f}{e:>15,.0f}{c:>18,.2f}")
print(f"    → 不用电池的最优：q={best[0]:.2f}，总费 {best[1]:,.2f} 元")

if len(sys.argv) > 1 and os.path.exists(sys.argv[1]):
    d_ = np.load(sys.argv[1])
    g_sp = d_["g"]
    c2, e2 = no_batt_cost(g_sp)
    print(f"\n--- 2. 用 SP 自己的 ĝ，但完全不调度电池（c=d=0）---")
    print(f"    Σĝ = {(g_sp*DT)[win].sum():,.0f} kWh，紧急 {e2:,.0f} kWh，"
          f"总费 {c2:,.2f} 元")
    print(f"\n--- 3. 对照 ---")
    print(f"    SP 计划 + MPC 执行（带电池）        17,149,812.00 元")
    print(f"    → 电池的净贡献 = {c2 - 17_149_812:+,.0f} 元"
          f"（正=电池在帮忙；越小说明电池越没用）")
