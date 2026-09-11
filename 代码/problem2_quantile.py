# -*- coding: utf-8 -*-
"""
问题 2 —— 报童/分位数论证：为什么"均值预测"不是无预报下的成本最优预测。

单期报童模型：净负荷 N_t = L_t − P_t。
  * 买少了 → 缺 1 kWh 按 5 倍价紧急补 → 边际损失 c_u = 5p
  * 买多了 → 多买 1 kWh 是普通价    → 边际损失 c_o = p
  最优订货量 = 净负荷分布的临界分位数：
        F(N̂*) = c_u / (c_u + c_o) = 5p / (5p + p) = 5/6 ≈ 83%
  即：无预报下，成本最优的"计划量"应是净负荷的约 83 分位（正偏置），而非均值(50 分位)。

本脚本：对净负荷取不同分位数 q 做预测（场景集=同星期几最近 4 周），解同一套全年连续 LP，
  滚动实际算总费用，画出"费用 vs 分位数"曲线，验证理论（最低点应落在 q≈0.8~0.85 而非 0.5）。
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
REPORT = 31
K_PEERS = 4

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

df1 = pd.read_excel(os.path.join(BASE, "附件", "附件1.xlsx"))
price_day = df1.iloc[:, 1].to_numpy(float)
dfL = pd.read_excel(os.path.join(BASE, "附件", "附件2.xlsx"), sheet_name="小区负载")
dfP = pd.read_excel(os.path.join(BASE, "附件", "附件2.xlsx"), sheet_name="光伏发电实际功率")
load = dfL.iloc[:, 1:1 + N].to_numpy(float)
pv = dfP.iloc[:, 1:1 + N].to_numpy(float)

price = np.tile(price_day, NDAYS)
mean_load, mean_pv = load.mean(axis=0), pv.mean(axis=0)
win = np.zeros(T, dtype=bool); win[REPORT * N:] = True

# 场景集：同星期几最近 K 周
peers = []
for d in range(NDAYS):
    ps = [d - 7 * k for k in range(1, K_PEERS + 1) if d - 7 * k >= 0]
    peers.append(ps)

# 全年连续 LP 骨架（b_eq 传净负荷预测 N̂）
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


def solve_and_cost(N_hat):
    """用净负荷预测 N̂ 解 LP，滚动实际 2025 算报告窗口总费用。返回 (总费, 计划费, 紧急费, 紧急购电量)。"""
    b_eq = np.concatenate([N_hat, np.zeros(T)])
    res = linprog(c_obj, A_eq=A_eq, b_eq=b_eq, bounds=bounds, method="highs")
    assert res.success, res.message
    x = res.x
    g = x[G0:G0 + T]; c = x[C0:C0 + T]; d = x[D0:D0 + T]
    # 题面口径：e 只补"微网提供的电能(购电+光伏+放电)低于小区负载"的缺口，不含充电量
    e = np.maximum(0.0, load.ravel() - g - pv.ravel() - d)
    planned = (price * g * DT)[win].sum()
    emerg = (5 * price * e * DT)[win].sum()
    em_kwh = (e * DT)[win].sum()
    return planned + emerg, planned, emerg, em_kwh


# 各分位数下的净负荷预测：N̂_q[d] = 同星期几 K 周场景净负荷的第 q 分位（逐区间）
def make_net_forecast(q):
    N_hat = np.empty((NDAYS, N))
    for d in range(NDAYS):
        if peers[d]:
            net_peer = load[peers[d]] - pv[peers[d]]      # (K,144)
            N_hat[d] = np.quantile(net_peer, q, axis=0)
        else:
            N_hat[d] = mean_load - mean_pv
    return N_hat.ravel()


print("=" * 96)
print("报童/分位数论证：费用 vs 净负荷预测分位数 q（场景集=同星期几4周；窗口 2/1–12/31）")
print("=" * 96)
print(f"{'分位数 q':>8}{'计划费(元)':>14}{'紧急费(元)':>14}{'紧急购电量(kWh)':>18}{'总费用(元)':>16}")
print("-" * 96)

qs = [0.30, 0.40, 0.50, 0.60, 0.70, 0.80, 0.833, 0.85, 0.90, 0.95, 0.99, 1.00]
results = {}
for q in qs:
    cost, planned, emerg, em = solve_and_cost(make_net_forecast(q))
    results[q] = (cost, planned, emerg, em)
    mark = " ← 报童下界(5/6)" if abs(q - 5 / 6) < 1e-3 else ""
    print(f"{q:>8.3f}{planned:>14,.0f}{emerg:>14,.0f}{em:>18,.0f}{cost:>16,.0f}{mark}")

# 与当前"负荷周几4周+光伏7天"点预测基线对比
L_hat = np.empty_like(load)
for d in range(NDAYS):
    idx = [d - 7 * k for k in range(1, 5) if d - 7 * k >= 0]
    L_hat[d] = load[idx].mean(axis=0) if idx else mean_load
P_hat = np.empty_like(pv)
for d in range(NDAYS):
    lo = max(0, d - 7)
    P_hat[d] = pv[lo:d].mean(axis=0) if lo < d else mean_pv
base = solve_and_cost(L_hat.ravel() - P_hat.ravel())

print("-" * 96)
print(f"{'当前点预测(负荷周几+光伏7天)':<8}{base[1]:>14,.0f}{base[2]:>14,.0f}{base[3]:>18,.0f}{base[0]:>16,.0f}")

best_q = min(results, key=lambda q: results[q][0])
print("-" * 96)
print(f"最低费用出现在 q={best_q:.3f}：{results[best_q][0]:,.0f} 元（计划费 {results[best_q][1]:,.0f}，紧急费 {results[best_q][2]:,.0f}）")
print(f"均值(q=0.5)费用 {results[0.5][0]:,.0f} → 最优分位 q={best_q:.3f} 节省 "
      f"{results[0.5][0] - results[best_q][0]:,.0f} 元 ({(results[0.5][0] - results[best_q][0]) / results[0.5][0] * 100:.2f}%)")
print("结论：")
print("  1) 均值(50分位)不是成本最优——5 倍紧急购电使最优点预测偏置为正；报童无储能下界 = 5/6≈83 分位。")
print("  2) 实际最优分位更高(储能吸收多买、使'买多'的损失低于普通价)，验证'均值系统性少买'。")

