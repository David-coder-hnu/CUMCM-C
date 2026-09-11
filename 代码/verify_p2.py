# -*- coding: utf-8 -*-
"""独立核验问题 2 的 13,832,465 元。

**刻意不 import 任何自己的求解代码**，只读 附件1/附件2 与 problem2_stochastic.py
导出的计划 (g, c, d)，从零重算三件事：

  (A) 复现：按 problem2_stochastic.rollout_cost 的口径重算 → 应恰好等于 13,832,465
  (B) 诚实执行：给储能加 SOC 递推，d̂ 放不出来时按实际能力削减、缺口按 5 倍价买电
  (C) 完美预见上界：ĝ 定死，储能给全窗口 LP（事后最优）→ 任何执行策略的下界

用法：DUMP_NPZ=/tmp/p2.npz python 代码/problem2_stochastic.py
      P2_NPZ=/tmp/p2.npz python 代码/verify_p2.py
"""
import os

import numpy as np
import pandas as pd
from scipy.optimize import linprog
from scipy import sparse

DT, ETA, P_MAX = 1.0 / 6.0, 0.9, 5000.0
SOC_MIN, SOC_MAX, SOC0 = 1200.0, 10800.0, 6000.0
N, NDAYS, REPORT = 144, 365, 31
T = N * NDAYS
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

price_day = pd.read_excel(os.path.join(BASE, "附件", "附件1.xlsx")).iloc[:, 1].to_numpy(float)
load = pd.read_excel(os.path.join(BASE, "附件", "附件2.xlsx"), sheet_name="小区负载") \
         .iloc[:, 1:1 + N].to_numpy(float)
pv = pd.read_excel(os.path.join(BASE, "附件", "附件2.xlsx"), sheet_name="光伏发电实际功率") \
       .iloc[:, 1:1 + N].to_numpy(float)
price = np.tile(price_day, NDAYS)
win = np.zeros(T, bool); win[REPORT * N:] = True
L = load.ravel(); P = pv.ravel()

d_ = np.load(os.environ.get("P2_NPZ", "p2.npz"))
g, c, d = d_["g"], d_["c"], d_["d"]
print(f"载入问题 2 自己的计划：ĝ 窗口内 {(g*DT)[win].sum():,.0f} kWh，"
      f"ĉ {(c*DT)[win].sum():,.0f}，d̂ {(d*DT)[win].sum():,.0f}")

# ---------- 守恒自检：SP 计划本身必须逐槽平衡 ----------
soc_chk = SOC0 + np.cumsum(ETA * c * DT - d * DT / ETA)
soc_ref = d_["soc"]
print(f"[自检1] 用 ĝ/ĉ/d̂ 重放 SOC，与 SP 的 SOC 轨迹最大偏差 "
      f"{np.abs(soc_chk - soc_ref[1:]).max():.3e} kWh  → {'一致' if np.abs(soc_chk-soc_ref[1:]).max() < 1 else '不一致'}")
bal = (g + P + d - L - c)                      # 逐槽：供 − (负载+充电)
print(f"[自检2] 逐槽能量余量 min {bal.min():,.0f} kW（负数=计划本身不可行）；"
      f"SOC 轨迹范围 [{soc_ref.min():.0f}, {soc_ref.max():.0f}]")


def cost_of(e):
    return (price * g * DT)[win].sum() + (5 * price * e * DT)[win].sum()


# ---------- (A) 复现 problem2_stochastic 的 rollout ----------
e_A = np.maximum(0.0, L - g - P - d)
print(f"\n(A) 复现 rollout（照抄 d̂，不追 SOC）        "
      f"紧急 {(e_A*DT)[win].sum():>10,.0f} kWh   总费 {cost_of(e_A):>14,.2f} 元")

# ---------- (B) 诚实执行：SOC 递推 + 双向限幅 ----------
def simulate(deficit_rule):
    soc, e_o, c_o, d_o, curt_d = SOC0, np.zeros(T), np.zeros(T), np.zeros(T), 0.0
    for t in range(T):
        dmax = max(0.0, (soc - SOC_MIN) * ETA / DT)
        dt_ = d[t]
        if deficit_rule:                       # BMS：有电就先顶住缺口
            dt_ = max(dt_, max(0.0, L[t] - P[t] - g[t]))
        if dt_ > dmax:
            curt_d += dt_ - dmax
            dt_ = dmax
        cmax = max(0.0, (SOC_MAX - soc) / (ETA * DT))
        ct_ = min(c[t], max(0.0, P[t] + g[t] + dt_ - L[t]), cmax)
        e_o[t] = max(0.0, L[t] - g[t] - P[t] - dt_)
        c_o[t], d_o[t] = ct_, dt_
        soc += (ETA * ct_ - dt_ / ETA) * DT
    return e_o, c_o, d_o, curt_d


for rule, tag in [(False, "(B1) 诚实执行：照抄 d̂（只加 SOC 限幅）"),
                  (True, "(B2) 诚实执行：+ 有电就先顶缺口")]:
    e_B, c_B, d_B, curt = simulate(rule)
    print(f"{tag}  紧急 {(e_B*DT)[win].sum():>10,.0f} kWh   "
          f"总费 {cost_of(e_B):>14,.2f} 元   (放电被限 {curt*DT:,.0f} kWh)")

# ---------- (C) 完美预见上界：ĝ 定死，储能给全窗口 LP ----------
t = np.arange(T)
C0, D0, S0, E0 = T, 2 * T, 3 * T, 4 * T + 1
n_vars = 5 * T + 1
c_obj = np.zeros(n_vars); c_obj[E0:E0 + T] = 5.0 * price * DT
A_eq = sparse.coo_matrix(
    (np.concatenate([np.ones(T), -np.ones(T), -ETA * DT * np.ones(T), (DT / ETA) * np.ones(T)]),
     (np.concatenate([t, t, t, t]),
      np.concatenate([S0 + t + 1, S0 + t, C0 + t, D0 + t]))), shape=(T, n_vars)).tocsr()
A_ub = sparse.coo_matrix(
    (np.concatenate([np.ones(T), -np.ones(T), -np.ones(T)]),
     (np.concatenate([t, t, t]), np.concatenate([C0 + t, D0 + t, E0 + t]))),
    shape=(T, n_vars)).tocsr()
res = linprog(c_obj, A_eq=A_eq, b_eq=np.zeros(T), A_ub=A_ub, b_ub=P + g - L,
              bounds=(list(zip(g, g)) + [(0, P_MAX)] * T + [(0, P_MAX)] * T
                      + [(SOC0, SOC0)] + [(SOC_MIN, SOC_MAX)] * (T - 1) + [(SOC0, SOC0)]
                      + [(0, None)] * T), method="highs")
assert res.success, res.message
e_C = res.x[E0:E0 + T]
print(f"(C) 完美预见储能（理论下界，不可实现）      紧急 {(e_C*DT)[win].sum():>10,.0f} kWh   "
      f"总费 {cost_of(e_C):>14,.2f} 元")

print(f"\n参照：纯实时按净需求购电（无储能、无紧急）                    "
      f"{((price*np.maximum(0,L-P))[win]*DT).sum():>14,.2f} 元")
print(f"参照：完美预见全年 LP（含储能套利）                          "
      f"{12_229_461:>14,.2f} 元")
