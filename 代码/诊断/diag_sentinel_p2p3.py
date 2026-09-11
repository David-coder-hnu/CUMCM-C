# -*- coding: utf-8 -*-
"""为什么问题 2 的哨兵 12,229,461 低于问题 3 的 12,406,053？

问题 3 的可行集**严格包含**问题 2 的（多了 1.5p 上调通道、紧急购电是软约束而非硬约束），
所以问题 3 的完美预见下界必须 ≤ 问题 2 的。报出更高值 = 至少一条口径不一致。

本脚本把 problem2.py:223-242 的哨兵 LP 原样复刻出来，在**同一份数据、同一窗口**下
与 problem3_v3.sentinel() 对比，并逐个变体定位差异来源。
"""
import os
import sys

import numpy as np
import pandas as pd
from scipy import sparse
from scipy.optimize import linprog

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
N, NDAYS, REPORT = 144, 365, 31
T = N * NDAYS
DT, ETA, P_MAX = 1.0 / 6.0, 0.9, 5000.0
SOC_MIN, SOC_MAX, SOC0 = 1200.0, 10800.0, 6000.0

price_day = pd.read_excel(os.path.join(BASE, "附件", "附件1.xlsx")).iloc[:, 1].to_numpy(float)
load = pd.read_excel(os.path.join(BASE, "附件", "附件2.xlsx"),
                     sheet_name="小区负载").iloc[:, 1:1 + N].to_numpy(float)
pv = pd.read_excel(os.path.join(BASE, "附件", "附件2.xlsx"),
                   sheet_name="光伏发电实际功率").iloc[:, 1:1 + N].to_numpy(float)
price = np.tile(price_day, NDAYS)
win = np.zeros(T, bool); win[REPORT * N:] = True
L = load.ravel(); P = pv.ravel()


def p2_sentinel(g_hi=None, x_hi=None):
    """复刻 problem2.py 的哨兵 LP。g_hi=None 保持原样 (0,None)；否则给上界。

    变量 G|C|D|X|S，方程 g − c + d − x = L−P（x=弃电，≥0 ⟹ 紧急购电被硬性置 0），
    SOC 递推 −ηΔt·c + (Δt/η)·d + S_{t+1} − S_t = 0，S_0 = S_T = SOC0。
    """
    G0, C0, D0, X0, S0_ = 0, T, 2 * T, 3 * T, 4 * T
    nv = 5 * T + 1
    obj = np.zeros(nv); obj[G0:G0 + T] = price
    t = np.arange(T)
    A_eq = sparse.coo_matrix(
        (np.concatenate([np.ones(T), -np.ones(T), np.ones(T), -np.ones(T),
                         np.ones(T), -np.ones(T), -ETA * DT * np.ones(T), (DT / ETA) * np.ones(T)]),
         (np.concatenate([t, t, t, t, T + t, T + t, T + t, T + t]),
          np.concatenate([G0 + t, C0 + t, D0 + t, X0 + t,
                          S0_ + t + 1, S0_ + t, C0 + t, D0 + t]))),
        shape=(2 * T, nv)).tocsr()
    b_eq = np.concatenate([L - P, np.zeros(T)])
    gb = (0, None) if g_hi is None else (0, g_hi)
    xb = (0, None) if x_hi is None else (0, x_hi)
    bounds = ([gb] * T + [(0, P_MAX)] * T + [(0, P_MAX)] * T + [xb] * T
              + [(SOC0, SOC0)] + [(SOC_MIN, SOC_MAX)] * (T - 1) + [(SOC0, SOC0)])
    r = linprog(obj, A_eq=A_eq, b_eq=b_eq, bounds=bounds, method="highs")
    if not r.success:
        return None
    x = r.x
    g, c, d = x[G0:G0 + T], x[C0:C0 + T], x[D0:D0 + T]
    e = np.maximum(0.0, L - g - P - d)
    soc = x[S0_:S0_ + T + 1]
    return dict(fee_p2=(price * g * DT)[win].sum() + (5 * price * e * DT)[win].sum(),
                plan=(price * g * DT)[win].sum(),
                em_kwh=(e * DT)[win].sum(),
                g_kwh=(g * DT)[win].sum(),
                soc_min=soc.min(), soc_max=soc.max(),
                g_max=g.max(), p_max=max(g.max(), d.max(), c.max()))


print("=" * 96)
print("A. 复刻 problem2.py 的哨兵 LP（G 无上界，与其源码一致）")
a = p2_sentinel()
print(f"   报出费用 {a['fee_p2']:>13,.2f} 元 ｜ 购电 {a['g_kwh']:>12,.0f} kWh ｜ "
      f"紧急 {a['em_kwh']:.2f} kWh ｜ SOC [{a['soc_min']:,.0f},{a['soc_max']:,.0f}]")
print(f"   规划层最大功率 g_max = {a['g_max']:,.2f} kW（物理上限 {P_MAX:,.0f}）")

print("\nB. 同一 LP，只把 G 加上界 P_MAX=5000")
b = p2_sentinel(g_hi=P_MAX)
print(f"   报出费用 {b['fee_p2']:>13,.2f} 元 ｜ 购电 {b['g_kwh']:>12,.0f} kWh ｜ "
      f"紧急 {b['em_kwh']:.2f} kWh ｜ g_max = {b['g_max']:,.2f} kW")

print("\nC. 同一 LP，只把弃电 X 加上界 5000")
c = p2_sentinel(x_hi=P_MAX)
print(f"   报出费用 {c['fee_p2']:>13,.2f} 元 ｜ 购电 {c['g_kwh']:>12,.0f} kWh ｜ "
      f"g_max = {c['g_max']:,.2f} kW")

print("\nD. 两个上界都加")
d_ = p2_sentinel(g_hi=P_MAX, x_hi=P_MAX)
print(f"   报出费用 {d_['fee_p2']:>13,.2f} 元 ｜ 购电 {d_['g_kwh']:>12,.0f} kWh ｜ "
      f"g_max = {d_['g_max']:,.2f} kW")

sys.path.insert(0, os.path.join(BASE, "代码"))
import problem3_v3 as M                                              # noqa: E402
print("\n" + "=" * 96)
print("E. problem3_v3.sentinel()（口径 A，含 1.5p 上调通道与 5p 紧急软约束）")
s = M.sentinel()
print(f"   报出费用 {s['total']:>13,.2f} 元 ｜ 购电 {s['kwh_g']:>12,.0f} kWh ｜ "
      f"紧急 {s['kwh_em']:.2f} kWh ｜ 超额 {s['excess']:,.2f} ｜ 违约 {s['breach']:,.2f}")

print("\n" + "=" * 96)
print(f"结论：问题 2 口径 {a['fee_p2']:,.0f} ｜ 加功率上界后 {d_['fee_p2']:,.0f} ｜ "
      f"问题 3 口径 {s['total']:,.0f}")
gap = s["total"] - d_["fee_p2"]
print(f"      两口径差 {gap:+,.0f} 元")
