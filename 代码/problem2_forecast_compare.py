# -*- coding: utf-8 -*-
"""
问题 2 —— 预测方式横向对比（储能跨日连续版）。

统一框架（所有预测方式共用）：
  1) 计划：用"预测"负荷/光伏解全年连续 LP（储能跨日连续、首尾 6000、SOC 自由漂移），得 ĝ/ĉ/d̂；
  2) 实际：附件 2 实际负荷/光伏对不上的部分 → 5 倍价紧急购电 e = max(0, L+ĉ−ĝ−P−d̂)；
  3) 总购电费 = Σ price·ĝ + Σ 5·price·e。

预测方式（除"完美预见/全年平均"两个基准外均只用当天 0:00 之前的信息）。
"""
import os
import numpy as np
import pandas as pd
from scipy.optimize import linprog
from scipy import sparse

DT = 1.0 / 6.0
ETA = 0.9
P_MAX = 5000.0
SOC_MIN = 1200.0
SOC_MAX = 10800.0
SOC0 = 6000.0
N = 144
NDAYS = 365
T = N * NDAYS

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

df1 = pd.read_excel(os.path.join(BASE, "附件", "附件1.xlsx"))
price_day = df1.iloc[:, 1].to_numpy(float)
dfL = pd.read_excel(os.path.join(BASE, "附件", "附件2.xlsx"), sheet_name="小区负载")
dfP = pd.read_excel(os.path.join(BASE, "附件", "附件2.xlsx"), sheet_name="光伏发电实际功率")
load = dfL.iloc[:, 1:1 + N].to_numpy(float)
pv = dfP.iloc[:, 1:1 + N].to_numpy(float)

price = np.tile(price_day, NDAYS)
mean_load, mean_pv = load.mean(axis=0), pv.mean(axis=0)

# ---- 全年连续 LP 骨架 ----
G0, C0, D0, S0, S_idx = 0, T, 2 * T, 3 * T, 4 * T
n_vars = 5 * T + 1
c_obj = np.zeros(n_vars); c_obj[G0:G0 + T] = price
t = np.arange(T)
rows = np.concatenate([t, t, t, t, T + t, T + t, T + t, T + t])
cols = np.concatenate([G0 + t, C0 + t, D0 + t, S0 + t,
                       S_idx + t + 1, S_idx + t, C0 + t, D0 + t])
data = np.concatenate([np.ones(T), -np.ones(T), np.ones(T), -np.ones(T),
                       np.ones(T), -np.ones(T), -ETA * DT * np.ones(T), (DT / ETA) * np.ones(T)])
A_eq = sparse.coo_matrix((data, (rows, cols)), shape=(2 * T, n_vars)).tocsr()
bounds = ([(0, None)] * T + [(0, P_MAX)] * T + [(0, P_MAX)] * T + [(0, None)] * T
          + [(SOC0, SOC0)] + [(SOC_MIN, SOC_MAX)] * (T - 1) + [(SOC0, SOC0)])

def solve_full_year(L_hat, P_hat):
    b_eq = np.concatenate([L_hat.ravel() - P_hat.ravel(), np.zeros(T)])
    res = linprog(c_obj, A_eq=A_eq, b_eq=b_eq, bounds=bounds, method="highs")
    assert res.success, res.message
    x = res.x
    return x[G0:G0 + T], x[C0:C0 + T], x[D0:D0 + T]

# ---- 预测方式：返回 (L_hat, P_hat)，形状 (365,144) ----
def f_climatology():    return np.tile(mean_load, (NDAYS, 1)), np.tile(mean_pv, (NDAYS, 1))
def f_persistence():
    L = np.empty_like(load); P = np.empty_like(pv)
    L[0], P[0] = mean_load, mean_pv
    L[1:], P[1:] = load[:-1], pv[:-1]
    return L, P
def f_same_weekday(n_weeks):
    L = np.empty_like(load); P = np.empty_like(pv)
    for d in range(NDAYS):
        idx = [d - 7 * k for k in range(1, n_weeks + 1) if d - 7 * k >= 0]
        if idx:
            L[d] = load[idx].mean(axis=0); P[d] = pv[idx].mean(axis=0)
        else:
            L[d], P[d] = mean_load, mean_pv
    return L, P
def make_ma(W):
    L = np.empty_like(load); P = np.empty_like(pv)
    for d in range(NDAYS):
        lo = max(0, d - W)
        if lo == d:
            L[d], P[d] = mean_load, mean_pv
        else:
            L[d] = load[lo:d].mean(axis=0); P[d] = pv[lo:d].mean(axis=0)
    return L, P

def f_ema(alpha):
    """指数加权平均：forecast_d = α·actual_{d-1} + (1-α)·forecast_{d-1}。α 越大越贴近前一天。"""
    L = np.empty_like(load); P = np.empty_like(pv)
    L[0], P[0] = mean_load, mean_pv
    for d in range(1, NDAYS):
        L[d] = alpha * load[d - 1] + (1 - alpha) * L[d - 1]
        P[d] = alpha * pv[d - 1] + (1 - alpha) * P[d - 1]
    return L, P

sw1 = f_same_weekday(1); sw2 = f_same_weekday(2)
sw4 = f_same_weekday(4); sw8 = f_same_weekday(8)
persist = f_persistence(); ma7 = make_ma(7)

methods = [
    ("完美预见(基准)", (load, pv)),
    ("全年平均(附件1)", f_climatology()),
    ("前一天(持续法)", persist),
    ("同星期几(1周)", sw1),
    ("同星期几(2周)", sw2),
    ("同星期几(4周)", sw4),
    ("同星期几(8周)", sw8),
    ("混:负荷周几+光伏昨", (sw4[0], persist[1])),
    ("混:负荷周几+光伏7天", (sw4[0], ma7[1])),
    ("混:负荷周几+光伏周几", (sw4[0], sw4[1])),
    ("指数加权α=0.5", f_ema(0.5)),
    ("指数加权α=0.3", f_ema(0.3)),
    ("指数加权α=0.1", f_ema(0.1)),
    ("近3天平均", make_ma(3)),
    ("近7天平均", ma7),
    ("近14天平均", make_ma(14)),
    ("近30天平均", make_ma(30)),
]

REPORT = 31
win = np.zeros(T, dtype=bool); win[REPORT * N:] = True

print("=" * 100)
print("问题 2 预测方式对比（储能跨日连续；统计窗口 2025.2.1–12.31，共 %d 天）" % (NDAYS - REPORT))
print("=" * 100)
print(f"{'预测方式':<20}{'计划购电量':>14}{'紧急购电量':>14}{'计划费(元)':>14}{'紧急费(元)':>14}{'总购电费(元)':>16}")
print("-" * 100)

results = []
for name, (L_hat, P_hat) in methods:
    g, c, d = solve_full_year(L_hat, P_hat)
    # 题面口径：e 只补"微网提供的电能(购电+光伏+放电)低于小区负载"的缺口，不含充电量
    e = np.maximum(0.0, load.ravel() - g - pv.ravel() - d)
    planned = (g * DT)[win].sum(); emerg = (e * DT)[win].sum()
    cost_planned = (price * g * DT)[win].sum(); cost_emerg = (5 * price * e * DT)[win].sum()
    total = cost_planned + cost_emerg
    results.append((name, planned, emerg, cost_planned, cost_emerg, total))
    print(f"{name:<20}{planned:>14,.0f}{emerg:>14,.0f}{cost_planned:>14,.0f}{cost_emerg:>14,.0f}{total:>16,.0f}")

print("-" * 100)
best = min(results[2:], key=lambda r: r[2])   # 排除"完美预见/全年平均"两个基准
print("排除基准后，紧急购电量最少:", best[0], f"({best[2]:,.0f} kWh)，总购电费 {best[5]:,.0f} 元")
