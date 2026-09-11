# -*- coding: utf-8 -*-
"""面板 B（修正版）：报童分位 ĝ = τ 分位(净需求 L−P) —— 不经过 LP，直接检验场景集质量。

注意分位方向：ĝ 要覆盖的是【净需求 D = L−P】，所以取 D 的 τ 分位。
上一版误写成 (P−L)，等价于取 (1−τ) 分位，系统性少买，故数值全废。
"""
import os
import sys
import numpy as np
import pandas as pd

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
RDAYS = np.arange(REPORT, NDAYS)


def peers_same_weekday(k):
    return [[d - 7 * j for j in range(1, k + 1) if d - 7 * j >= 0] for d in range(NDAYS)]


def peers_group(dows, span=14):
    m = np.array([(d % 7) in dows for d in range(NDAYS)])
    return [[t for t in range(max(0, d - span), d) if m[t] == m[d]] for d in range(NDAYS)]


def peers_all(span=14):
    return [[t for t in range(max(0, d - span), d)] for d in range(NDAYS)]


def exec_causal(g):
    c = np.zeros(T); d = np.zeros(T); e = np.zeros(T); soc = SOC0
    for t in range(T):
        deficit = max(0.0, L[t] - P[t] - g[t])
        d[t] = min(deficit, P_MAX, max(0.0, (soc - SOC_MIN) * ETA / DT))
        c[t] = min(P_MAX, max(0.0, P[t] + g[t] + d[t] - L[t]), max(0.0, (SOC_MAX - soc) / (ETA * DT)))
        e[t] = max(0.0, L[t] - P[t] - g[t] - d[t])
        soc += (ETA * c[t] - d[t] / ETA) * DT
    return e


CFG = [
    ("A1 同星期几 K=4  [main基线]", peers_same_weekday(4)),
    ("A2 同星期几 K=2", peers_same_weekday(2)),
    ("A3 低需求日/其余 (Fri+Sat)", peers_group((2, 3))),
    ("A4 日历周末/工作日 (Sat+Sun)", peers_group((3, 4))),
    ("A5 不分组 近14天", peers_all(14)),
]
taus = [0.70, 0.75, 0.80, 0.85, 0.90, 0.95, 1.0]

print("=" * 118)
print("面板 B（修正）：ĝ = τ 分位(净需求 L−P)，因果追索执行，334 个报告日")
print("=" * 118)
print(f"{'配置':<30}" + "".join(f"{'τ='+format(t,'.3g'):>12}" for t in taus) + f"{'最优τ':>8}{'最优成本':>14}{'vs基线':>13}")
print("-" * 118)
res = {}
for tag, peers in CFG:
    row = []
    for tau in taus:
        g = np.empty(T)
        for dd in range(NDAYS):
            p = peers[dd] if peers[dd] else [dd]
            vals = load[p] - pv[p]                       # 净需求 D = L − P
            g[dd * N:(dd + 1) * N] = np.quantile(vals, tau, axis=0) if len(p) > 1 else vals[0]
        g = np.maximum(g, 0.0)                           # 不允许向电网卖电
        e = exec_causal(g)
        per = (price * g * DT + 5 * price * e * DT).reshape(NDAYS, N).sum(axis=1)
        row.append(per[RDAYS].sum())
    j = int(np.argmin(row))
    res[tag] = (taus[j], row[j], row)
    print(f"{tag:<30}" + "".join(f"{v:>12,.0f}" for v in row) + f"{taus[j]:>8.3g}{row[j]:>14,.0f}")
print("-" * 118)
b_tau, b_cost, b_row = res["A1 同星期几 K=4  [main基线]"]
for tag in list(res)[1:]:
    tau, cost, _ = res[tag]
    print(f"  {tag:<28} 最优 τ={tau:.3g}  成本 {cost:,.0f}  相对基线 {cost-b_cost:+,.0f} "
          f"({(cost-b_cost)/b_cost*100:+.2f}%)")
print()
print("固定 τ=0.8（无储能时的报童临界比）下各场景集对比：")
print("-" * 118)
for tag in res:
    tau, cost, row = res[tag]
    v = row[taus.index(0.8)]
    print(f"  {tag:<30} {v:>14,.0f}   相对基线 {v-b_row[taus.index(0.8)]:+,.0f}")
print()
print("对照：γ=1 可交付 LP 在同一执行器下的最优成本 —— 基线 15,134,192 / Fri+Sat 14,341,723")
