# -*- coding: utf-8 -*-
"""问题 2 换基线（GROUP_SPAN=6）后需要的几个补充数字，供归档引用。

导入 problem2 会顺带重跑全流程并重写 结果/result2.xlsx —— 内容与既有交付表逐格相同
（已用 pandas .equals 验证），只是 xlsx 压缩包时间戳不同。

输出：
  (1) γ=1 闭式计划费的分项与总额
  (2) 交付口径（因果执行）的分项
  (3) d̂ 中「缺口为零时放电」的 kWh 与占比（分组口径 / 同星期几 K=4 口径）
  (4) 严格执行 d̂（min(d̂, SOC 限)，不减缺口）的总费
  (5) 交付表 result2.xlsx 的「全天购电费」列合计、以及左移约定还原的 Σp·ĝ
"""
import os
import sys

import numpy as np
import pandas as pd

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

import problem2 as p  # noqa: E402  （导入即运行，得到 g1/d1/cm1/peers/peers_wd）

DT, N, NDAYS, REPORT = p.DT, p.N, p.NDAYS, p.REPORT

# ---- (1)(2) γ=1 闭式 vs 因果执行 ----
r_closed = p.honor_cost(p.g1, p.d1)
c_ex, d_ex, e_ex, soc_ex = p.execute_soc_causal(p.g1)
r_exec = p.honor_cost(p.g1, d_ex)
print("=" * 90)
print(f"γ=1 闭式计划费   计划 {r_closed[1]:>14,.0f}  紧急 {r_closed[2]:>12,.0f}"
      f" ({r_closed[3]:>10,.0f} kWh)  总 {r_closed[0]:>14,.0f}")
print(f"γ=1 因果执行     计划 {r_exec[1]:>14,.0f}  紧急 {r_exec[2]:>12,.0f}"
      f" ({r_exec[3]:>10,.0f} kWh)  总 {r_exec[0]:>14,.0f}")
print(f"  紧急均价 {r_exec[2] / r_exec[3]:.3f} 元/kWh ｜ 实际 SOC 首 {soc_ex[0]:,.1f} "
      f"末 {soc_ex[-1]:,.1f} 范围 [{soc_ex.min():,.1f}, {soc_ex.max():,.1f}]")


# ---- (3) d̂ 的「缺口为零时放电」占比 ----
def gap_zero_share(g_hat, d_hat, sc):
    """逐情景判定 ĝ+d̂+q 是否已覆盖缺口；q 用全情景最小可得富余（与 soc_trace 同口径）。

    ⚠ 必须传入**该臂自己的** `g_hat`：早期版本这里闭包引用了模块级的 `p.g1`（= 分组 span6 的
    计划），于是「同星期几 K=4」那一行拿的是别臂的 ĝ，算出的 169,652 kWh 是错的
    （正确值 135,880 kWh）。见 `_p2_dhat_edge.py`。
    """
    q = np.empty(p.T)
    for dd in range(NDAYS):
        pp = p.sc_of(sc, dd)
        q[dd * N:(dd + 1) * N] = (p.pv[pp] - p.load[pp]).min(axis=0)
    covered = g_hat + d_hat + q >= p.L - p.P - 1e-9     # 不放电也能覆盖缺口
    kwh = (d_hat * DT)[covered & (d_hat > 1e-9)].sum()
    return kwh, kwh / (d_hat * DT).sum() * 100


for tag, sc in (("分组 span6（本版交付）", p.peers), ("同星期几 K=4（旧口径）", p.peers_wd)):
    g_, d_, cm_ = p.solve_deliver(1.0, sc)[:3]
    kwh, pct = gap_zero_share(g_, d_, sc)
    print(f"d̂ 缺口为零时放电  {tag:<22} {kwh:>12,.0f} kWh  ({pct:>5.1f}%)")


# ---- (4) 严格执行 d̂（min(d̂, SOC 限)，不减缺口）----
def exec_strict(d_hat):
    """把 d̂ 当成必须执行的放电计划：只受 SOC 下限与功率上限截断，不按实际缺口削减。"""
    c = np.zeros(p.T); d = np.zeros(p.T); soc = np.empty(p.T + 1); soc[0] = p.SOC0
    for t in range(p.T):
        d[t] = min(d_hat[t], p.P_MAX, max(0.0, (soc[t] - p.SOC_MIN) * p.ETA / DT))
        surplus = max(0.0, p.P[t] + p.g1[t] + d[t] - p.L[t])
        c[t] = min(p.P_MAX, surplus, max(0.0, (p.SOC_MAX - soc[t]) / (p.ETA * DT)))
        soc[t + 1] = soc[t] + (p.ETA * c[t] - d[t] / p.ETA) * DT
    return c, d


_, d_strict = exec_strict(p.d1)
r_strict = p.honor_cost(p.g1, d_strict)
_, d_strict_wd = exec_strict(p.solve_deliver(1.0, p.peers_wd)[1])
r_strict_wd = p.honor_cost(p.solve_deliver(1.0, p.peers_wd)[0], d_strict_wd)
print(f"严格执行 d̂（分组 span6）      总 {r_strict[0]:>14,.0f}  "
      f"（比交付贵 {r_strict[0] - r_exec[0]:,.0f}）")
print(f"严格执行 d̂（同星期几 K=4）    总 {r_strict_wd[0]:>14,.0f}")

# ---- (5) 交付表核对 ----
# ⚠ BASE 是 `代码/`（供 import problem2 用），交付表在仓库根下，须再上一级。
ROOT = os.path.dirname(BASE)
f = os.path.join(ROOT, "结果", "result2.xlsx")
raw = pd.read_excel(f, sheet_name="计划购电量", header=None).iloc[1:]
num = raw.apply(pd.to_numeric, errors="coerce").to_numpy(float)
# ⚠ 列序（沿用附件 5 模板）：第 0 列是「日期」，第 1..144 列才是 144 个时间槽，
#    第 145 列 = 全天购电量，第 146 列 = 全天购电费。
fee_col = num[:, 2 + N]
core = num[:, 1:1 + N]
gd = num[:, 1 + N]
# ⚠ 表内槽列有 10 分钟循环错位 ⟹ 必须左移一位配对（等价 np.roll(core, 1, axis=1)）。
restored = (p.price_day[None, :] * core[:, (np.arange(N) - 1) % N]).sum(axis=1)
naive = (p.price_day[None, :] * core).sum(axis=1)
print("=" * 90)
print(f"全天购电费列合计        {np.nansum(fee_col):,.2f} 元")
print(f"左移约定还原 Σp·ĝ        {restored.sum():,.2f} 元  （求解器 {r_exec[1]:,.0f}）")
print(f"不左移（错读）           {naive.sum():,.2f} 元")
print(f"左移还原的紧急费         {np.nansum(fee_col) - restored.sum():,.2f} 元")
print(f"全天购电量列合计         {np.nansum(gd):,.2f} kWh")
