# -*- coding: utf-8 -*-
"""独立审计：把每一份"问题 2 计划"放在同一把尺子上量。

对每份计划 (ĝ, d̂, ĉ)：
  (A) 照抄口径   e = max(0, L − ĝ − P − d̂)                ← 忽略储能物理，乐观
  (B) 诚实执行   实际 SOC 递推 + 放电受 SOC 下限限制 + 充电受富余/上限限制
  (C) 完美预见   固定 ĝ，储能给全年 LP（不可实现，是【同 ĝ 下的下界】）

判据：若 (A) < (C)，则该计划在算术上不可能被任何因果执行实现 —— 计划本身违反物理。

用法：python 代码/独立视角/audit.py
"""
import os
import sys
import tempfile

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
T = N * NDAYS
K_PEERS = 4
BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

price_day = pd.read_excel(os.path.join(BASE, "附件", "附件1.xlsx")).iloc[:, 1].to_numpy(float)
load = pd.read_excel(os.path.join(BASE, "附件", "附件2.xlsx"), sheet_name="小区负载") \
         .iloc[:, 1:1 + N].to_numpy(float)
pv = pd.read_excel(os.path.join(BASE, "附件", "附件2.xlsx"), sheet_name="光伏发电实际功率") \
       .iloc[:, 1:1 + N].to_numpy(float)
price = np.tile(price_day, NDAYS)
win = np.zeros(T, bool); win[REPORT * N:] = True
L = load.ravel(); P = pv.ravel()


def cost_of(e, g):
    return (price * g * DT)[win].sum() + (5 * price * e * DT)[win].sum()


def honest_sim(g, c, d, deficit_first=False):
    """实际执行：SOC 逐槽递推，放电受 SOC 下限与功率限幅，充电受实际富余与 SOC 上限限幅。"""
    soc = SOC0
    e_o = np.zeros(T); c_o = np.zeros(T); d_o = np.zeros(T)
    curt = 0.0
    for t in range(T):
        dmax = max(0.0, (soc - SOC_MIN) * ETA / DT)
        dt_ = d[t]
        if deficit_first:
            dt_ = max(dt_, max(0.0, L[t] - P[t] - g[t]))
        if dt_ > dmax:
            curt += dt_ - dmax
            dt_ = dmax
        cmax_soc = max(0.0, (SOC_MAX - soc) / (ETA * DT))
        ct_ = min(c[t], max(0.0, P[t] + g[t] + dt_ - L[t]), cmax_soc)
        e_o[t] = max(0.0, L[t] - g[t] - P[t] - dt_)
        c_o[t], d_o[t] = ct_, dt_
        soc += (ETA * ct_ - dt_ / ETA) * DT
    return e_o, curt


def pf_bound(ghat):
    """(C) 固定 ĝ，储能完美预见 → 同 ĝ 下任何执行策略的下界。"""
    t = np.arange(T)
    C0, D0, S0_, E0 = T, 2 * T, 3 * T, 4 * T + 1
    nv = 5 * T + 1
    c_obj = np.zeros(nv); c_obj[E0:E0 + T] = 5.0 * price * DT
    A_eq = sparse.coo_matrix(
        (np.concatenate([np.ones(T), -np.ones(T), -ETA * DT * np.ones(T), (DT / ETA) * np.ones(T)]),
         (np.concatenate([t, t, t, t]),
          np.concatenate([S0_ + t + 1, S0_ + t, C0 + t, D0 + t]))),
        shape=(T, nv)).tocsr()
    A_ub = sparse.coo_matrix(
        (np.concatenate([np.ones(T), -np.ones(T), -np.ones(T)]),
         (np.concatenate([t, t, t]), np.concatenate([C0 + t, D0 + t, E0 + t]))),
        shape=(T, nv)).tocsr()
    res = linprog(c_obj, A_eq=A_eq, b_eq=np.zeros(T), A_ub=A_ub, b_ub=P + ghat - L,
                  bounds=(list(zip(ghat, ghat)) + [(0, P_MAX)] * T + [(0, P_MAX)] * T
                          + [(SOC0, SOC0)] + [(SOC_MIN, SOC_MAX)] * (T - 1) + [(SOC0, SOC0)]
                          + [(0, None)] * T), method="highs")
    assert res.success, res.message
    return res.x[E0:E0 + T]


def solve_full_year(N_hat):
    G0, C0, D0, S0_, S_idx = 0, T, 2 * T, 3 * T, 4 * T
    nv = 5 * T + 1
    c_obj = np.zeros(nv); c_obj[G0:G0 + T] = price
    t = np.arange(T)
    A_eq = sparse.coo_matrix(
        (np.concatenate([np.ones(T), -np.ones(T), np.ones(T), -np.ones(T),
                         np.ones(T), -np.ones(T), -ETA * DT * np.ones(T), (DT / ETA) * np.ones(T)]),
         (np.concatenate([t, t, t, t, T + t, T + t, T + t, T + t]),
          np.concatenate([G0 + t, C0 + t, D0 + t, S0_ + t,
                          S_idx + t + 1, S_idx + t, C0 + t, D0 + t]))),
        shape=(2 * T, nv)).tocsr()
    res = linprog(c_obj, A_eq=A_eq, b_eq=np.concatenate([N_hat, np.zeros(T)]),
                  bounds=([(0, None)] * T + [(0, P_MAX)] * T + [(0, P_MAX)] * T + [(0, None)] * T
                          + [(SOC0, SOC0)] + [(SOC_MIN, SOC_MAX)] * (T - 1) + [(SOC0, SOC0)]),
                  method="highs")
    assert res.success, res.message
    x = res.x
    return x[G0:G0 + T], x[C0:C0 + T], x[D0:D0 + T]


peers = [[d - 7 * k for k in range(1, K_PEERS + 1) if d - 7 * k >= 0] for d in range(NDAYS)]
L_hat = np.array([load[p].mean(0) if p else load.mean(0) for p in peers])
P_hat = np.array([pv[max(0, d - 7):d].mean(0) if d else pv.mean(0) for d in range(NDAYS)])

cands = {}

print("构造候选计划 ...")
g, c, d = solve_full_year(L - P);                      cands["完美预见(下界)"] = (g, c, d)
g, c, d = solve_full_year((L_hat - P_hat).ravel());    cands["点预测(周几4周+光伏7天)"] = (g, c, d)

TMP = os.environ.get("P2_TMP", tempfile.gettempdir())      # Python 端 /tmp ≠ MSYS 的 /tmp
for fn, label, key in [("p2_sp.npz", "现交付 result2 SP 计划", ("g", "c", "d")),
                       ("p2_robust.npz", "新模型 γ=1 可交付计划", ("g", "cm", "d")),
                       ("p2_rec.npz", "新模型 追索+oracle 执行", ("g", "c", "d"))]:
    fp = os.path.join(TMP, fn)
    if os.path.exists(fp):
        z = np.load(fp)
        cands[label] = tuple(z[k] for k in key)
    else:
        print(f"  [skip] 缺少 {fp}")

print()
print("=" * 108)
print("计划 × 执行口径 交叉表（统计窗口 2025.2.1–12.31，334 天）")
print("=" * 108)
print(f"{'计划':<26}{'(A)照抄口径':>15}{'(B)诚实执行':>15}{'(C)同ĝ完美预见':>17}{'放电被限kWh':>14}")
print("-" * 108)
rows = []
for name, (g, c, d) in cands.items():
    eA = np.maximum(0.0, L - g - P - d)
    costA = cost_of(eA, g)
    eB, curt = honest_sim(g, c, d)
    costB = cost_of(eB, g)
    eC = pf_bound(g)
    costC = cost_of(eC, g)
    rows.append((name, costA, costB, costC, curt * DT, (eA * DT)[win].sum()))
    print(f"{name:<26}{costA:>15,.0f}{costB:>15,.0f}{costC:>17,.0f}{curt * DT:>14,.0f}")

print("-" * 108)
print("判据：(A) 若 < (C) → 计划在算术上不可能被任何因果执行实现（放电量放不出来）。")
print()
for name, costA, costB, costC, curt, emA in rows:
    if name.startswith("完美预见"):
        continue
    flag = "❌ 不可能" if costA < costC - 1 else "✅ 可交付"
    print(f"  {name:<26} (A) {costA:>13,.0f}  vs  (C) {costC:>13,.0f}   {flag}"
          f"   差额 {costC - costA:>+11,.0f}")
