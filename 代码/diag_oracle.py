# -*- coding: utf-8 -*-
"""诊断：固定 0:00 计划 ĝ，给储能【完美预见】(全窗口一个 LP)，求紧急购电的理论下界。

用来判定"紧急购电到底是计划 ĝ 不好，还是执行层（BMS 规则）不好"：
  · 若完美预见下紧急购电≈0  → ĝ 与储能容量都够用，是执行策略的问题；
  · 若完美预见下仍有大量紧急 → ĝ 本身覆盖不住实际净需求，是预报/计划的问题。

用法：NO_SAVE=1 DUMP_GHAT=/tmp/ghat.npy python 代码/problem3_v2.py
      GHAT_NPY=/tmp/ghat.npy python 代码/diag_oracle.py
"""
import os
import sys
import time

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


def solve(ghat, tag):
    """固定 g=ĝ，储能完美预见：min Σ 5p·e·Δt"""
    C0, D0, S0, E0 = T, 2 * T, 3 * T, 4 * T + 1   # s 占 3T..4T（T+1 个），故 e 从 4T+1 起
    n_vars = 5 * T + 1
    c_obj = np.zeros(n_vars)
    c_obj[E0:E0 + T] = 5.0 * price * DT

    t = np.arange(T)
    A_eq = sparse.coo_matrix(
        (np.concatenate([np.ones(T), -np.ones(T), -ETA * DT * np.ones(T), (DT / ETA) * np.ones(T)]),
         (np.concatenate([t, t, t, t]),
          np.concatenate([S0 + t + 1, S0 + t, C0 + t, D0 + t]))),
        shape=(T, n_vars)).tocsr()

    # (i) c − d ≤ P + ĝ − L      (ii) −d − e ≤ L − P − ĝ
    # 能量平衡（唯一一条）：Ĝ + P + d + e ≥ L + c
    #   ⇒ c − d − e ≤ Ĝ + P − L。e 只在"供不应求"时为真，而"用 5 倍价紧急电去充电"
    #     永不划算，故最优解里 e 恰等于题面口径 max(0, L − Ĝ − P − d)。
    cols = np.concatenate([C0 + t, D0 + t, E0 + t])
    dat = np.concatenate([np.ones(T), -np.ones(T), -np.ones(T)])
    A_ub = sparse.coo_matrix((dat, (np.concatenate([t, t, t]), cols)),
                             shape=(T, n_vars)).tocsr()
    b_ub = P + ghat - L

    bounds = (list(zip(ghat, ghat))                       # g 固定为 ĝ
              + [(0, P_MAX)] * T + [(0, P_MAX)] * T
              + [(SOC0, SOC0)] + [(SOC_MIN, SOC_MAX)] * (T - 1) + [(SOC0, SOC0)]
              + [(0, None)] * T)
    r = linprog(c_obj, A_eq=A_eq, b_eq=np.zeros(T), A_ub=A_ub, b_ub=b_ub,
                bounds=bounds, method="highs")
    assert r.success, r.message
    x = r.x
    e = x[E0:E0 + T]
    print(f"[{tag}] 储能完美预见：紧急购电 {(e*DT)[win].sum():>12,.0f} kWh  "
          f"费用 {(5*price*e*DT)[win].sum():>13,.0f} 元   "
          f"充 {(x[C0:C0+T]*DT)[win].sum():,.0f} / 放 {(x[D0:D0+T]*DT)[win].sum():,.0f} kWh")


if __name__ == "__main__":
    src = os.environ.get("GHAT_NPY")
    if not src:
        raise SystemExit("需要 GHAT_NPY=<ğ 的 .npy>")
    g = np.load(src)
    print(f"ĝ: 窗口内 {g[win].sum()*DT:,.0f} kWh，全窗口 {g.sum()*DT:,.0f} kWh")
    # 参照：无储能、纯实时按净需求购电
    print(f"参照：无储能实时购电 {((price*np.maximum(0,L-P))[win]*DT).sum():,.0f} 元；"
          f"无储能+5倍紧急（=同一件事）")
    t0 = time.time()
    solve(g, os.path.basename(src))
    # 对照：ĝ 换成"实际净需求"（假设 0:00 预报完美）
    solve(np.maximum(0.0, L - P), "完美预报 ĝ")
    print(f"  ({time.time()-t0:.0f}s)")
