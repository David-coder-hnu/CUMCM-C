# -*- coding: utf-8 -*-
"""问题 3 诊断实验：把"确定性等价"的日内调整 LP 换成【两阶段随机 LP】。

差异只有一处：
  现行 problem3.py 的 solve_stage 里没有紧急购电变量 —— 它把预报当真，
  计划恰好覆盖预报净负荷，于是残差 100% 暴露在 5 倍紧急购电下。
  本脚本在每一阶段引入场景 ω 的紧急购电 e_{t,ω}（5 倍价），
  目标改为对残差经验分布求期望 —— 即真正"风险感知"的调整。

同时扫描 0:00 计划的正偏置 H（kW），找到联合最优。
"""
import os, sys, time
import numpy as np
import pandas as pd
from scipy.optimize import linprog
from scipy import sparse

DT, ETA, P_MAX = 1.0 / 6.0, 0.9, 5000.0
SOC_MIN, SOC_MAX, SOC0 = 1200.0, 10800.0, 6000.0
N, NDAYS, REPORT = 144, 365, 31
T = N * NDAYS
K_PEERS = 4
K_SCEN = int(os.environ.get("K_SCEN", 8))     # 残差场景数
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

df1 = pd.read_excel(os.path.join(BASE, "附件", "附件1.xlsx"))
price_day = df1.iloc[:, 1].to_numpy(float)
load = pd.read_excel(os.path.join(BASE, "附件", "附件2.xlsx"), sheet_name="小区负载") \
         .iloc[:, 1:1 + N].to_numpy(float)
pv = pd.read_excel(os.path.join(BASE, "附件", "附件2.xlsx"), sheet_name="光伏发电实际功率") \
       .iloc[:, 1:1 + N].to_numpy(float)
fc3 = pd.read_excel(os.path.join(BASE, "附件", "附件3.xlsx"), header=None) \
        .iloc[1:, 2:].to_numpy(float).reshape(NDAYS, 4, 24)
price = np.tile(price_day, NDAYS)

W = np.zeros((N, 25))
for k in range(N):
    t = (k + 1) / 6.0; lo = int(np.floor(t)); hi = min(int(np.ceil(t)), 24)
    if lo == hi: W[k, lo] = 1.0
    else: W[k, lo] = 1 - (t - lo); W[k, hi] = t - lo


def pv_fc(d, s_idx, s_hour):
    H = np.zeros(25)
    if s_hour > 0: H[s_hour] = pv[d, 6 * s_hour]
    for h in range(s_hour + 1, 25): H[h] = fc3[d, s_idx, h - s_hour - 1]
    return H @ W.T


P_hat = np.stack([pv_fc(d, 0, 0) for d in range(NDAYS)])
L_base = np.empty_like(load)
for d in range(NDAYS):
    idx = [d - 7 * k for k in range(1, K_PEERS + 1) if d - 7 * k >= 0]
    L_base[d] = load[idx].mean(axis=0) if idx else load.mean(axis=0)


def solve_annual(N_hat):
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
    b_eq = np.concatenate([N_hat, np.zeros(T)])
    bounds = ([(0, None)] * T + [(0, P_MAX)] * T + [(0, P_MAX)] * T + [(0, None)] * T
              + [(SOC0, SOC0)] + [(SOC_MIN, SOC_MAX)] * (T - 1) + [(SOC0, SOC0)])
    res = linprog(c_obj, A_eq=A_eq, b_eq=b_eq, bounds=bounds, method="highs")
    assert res.success, res.message
    x = res.x
    return x[G0:G0 + T], x[C0:C0 + T], x[D0:D0 + T], x[S_idx:S_idx + T + 1]


def solve_stage_sp(s_idx, soc_start, soc_end, P_rem, L_rem, ghat_rem, price_rem, resid):
    """两阶段随机调整 LP。resid: (K,n) 净负荷残差场景（预报−实际 的反号：实际−预报）。"""
    K, n = resid.shape
    G0, C0, D0, SL = 0, n, 2 * n, 3 * n
    S_idx = 4 * n
    AP, AN = 5 * n + 1, 6 * n + 1
    E0 = 7 * n + 1
    n_vars = E0 + K * n

    c_obj = np.zeros(n_vars)
    c_obj[G0:G0 + n] = price_rem * DT
    c_obj[AP:AP + n] = 0.5 * price_rem * DT
    c_obj[AN:AN + n] = 0.5 * price_rem * DT
    for w in range(K):
        c_obj[E0 + w * n: E0 + (w + 1) * n] = 5.0 * price_rem * DT / K

    i = np.arange(n)
    r1 = np.concatenate([i, i, i, i]); c1 = np.concatenate([G0 + i, D0 + i, C0 + i, SL + i])
    d1 = np.concatenate([np.ones(n), np.ones(n), -np.ones(n), -np.ones(n)])
    r2 = np.concatenate([n + i] * 4); c2 = np.concatenate([S_idx + i + 1, S_idx + i, C0 + i, D0 + i])
    d2 = np.concatenate([np.ones(n), -np.ones(n), -ETA * DT * np.ones(n), (DT / ETA) * np.ones(n)])
    r3 = np.concatenate([2 * n + i] * 3); c3 = np.concatenate([G0 + i, AP + i, AN + i])
    d3 = np.concatenate([np.ones(n), -np.ones(n), np.ones(n)])
    A_eq = sparse.coo_matrix((np.concatenate([d1, d2, d3]),
                              (np.concatenate([r1, r2, r3]), np.concatenate([c1, c2, c3]))),
                             shape=(3 * n, n_vars)).tocsr()
    b_eq = np.concatenate([L_rem - P_rem, np.zeros(n), ghat_rem])

    # A_ub x ≤ b_ub：  −e − g − d + c ≤ −(F + resid)   ⇔   e ≥ F + resid + c − g − d
    F = L_rem - P_rem
    rl, cl, dl = [], [], []
    for w in range(K):
        rl.append(np.tile(w * n + i, 4))
        cl.append(np.concatenate([E0 + w * n + i, G0 + i, D0 + i, C0 + i]))
        dl.append(np.concatenate([-np.ones(n), -np.ones(n), -np.ones(n), np.ones(n)]))
    A_ub = sparse.coo_matrix((np.concatenate(dl), (np.concatenate(rl), np.concatenate(cl))),
                             shape=(K * n, n_vars)).tocsr()
    b_ub = np.concatenate([-(F + resid[w]) for w in range(K)])

    lo = ([0.0] * n * 4 + [soc_start, SOC_MIN] + [SOC_MIN] * (n - 2) + [soc_end]
          + [0.0] * n + [0.0] * n + [0.0] * (K * n))
    hi = ([None] * n + [P_MAX] * n + [P_MAX] * n + [None] * n
          + [soc_start, SOC_MAX] + [SOC_MAX] * (n - 2) + [soc_end]
          + [None] * n + [None] * n + [None] * (K * n))
    res = linprog(c_obj, A_eq=A_eq, b_eq=b_eq, A_ub=A_ub, b_ub=b_ub,
                  bounds=list(zip(lo, hi)), method="highs")
    assert res.success, res.message
    x = res.x
    return x[G0:G0 + n], x[C0:C0 + n], x[D0:D0 + n], x[S_idx:S_idx + n + 1]


STAGES = [(6, 1), (12, 2), (18, 3)]


def build_resid(d, s_idx, s_hour):
    """当天该阶段、剩余时段的净负荷残差场景（实际−预报），取同星期几最近 K_SCEN 周。"""
    si = s_hour * 6
    peers = [d - 7 * k for k in range(1, K_SCEN + 1) if d - 7 * k >= 0]
    if not peers:
        return np.zeros((1, N - si))
    out = []
    for p in peers:
        P_f = PVFC[p, _SIDX[s_idx]][si:]
        denom = L_base[p, :si].sum()
        r = load[p, :si].sum() / denom if denom > 1e-6 else 1.0
        out.append((load[p, si:] - r * L_base[p, si:]) - (pv[p, si:] - P_f))
    return np.stack(out)


_SIDX = {1: 0, 2: 1, 3: 2}
PVFC = np.stack([np.stack([pv_fc(d, s_idx, s_hour) for s_hour, s_idx in STAGES])
                 for d in range(NDAYS)])                       # (365,3,144)
RESID = [[build_resid(d, s_idx, s_hour) for s_hour, s_idx in STAGES]
         for d in range(NDAYS)]                                # [365][3] -> (K,144-si)


def run(H, annual_cache={}):
    if H not in annual_cache:
        N_hat = (L_base - P_hat + H).ravel()
        annual_cache[H] = solve_annual(N_hat)
    g_plan, c_plan, d_plan, soc_plan = annual_cache[H]
    g_plan = g_plan.reshape(NDAYS, N); c_plan = c_plan.reshape(NDAYS, N)
    d_plan = d_plan.reshape(NDAYS, N); soc_mid = soc_plan[::N]

    g_final, c_final, d_final = g_plan.copy(), c_plan.copy(), d_plan.copy()
    for d in range(NDAYS):
        soc_end = soc_mid[d + 1] if d + 1 < NDAYS else SOC0
        for (s_hour, s_idx), Pfull, resid in zip(STAGES, PVFC[d], RESID[d]):
            si = s_hour * 6
            # SOC 起点用实际执行值
            s = soc_mid[d]
            for t in range(si):
                s += ETA * c_final[d, t] * DT - d_final[d, t] * DT / ETA
            den = L_base[d, :si].sum()
            r = load[d, :si].sum() / den if den > 1e-6 else 1.0
            g, c, dd, _ = solve_stage_sp(
                si, s, soc_end, Pfull[si:], r * L_base[d, si:],
                g_plan[d, si:], price_day[si:], resid)
            nx = si + 36
            g_final[d, si:nx] = g[:36]; c_final[d, si:nx] = c[:36]; d_final[d, si:nx] = dd[:36]

    # 题面口径：e 只补"微网提供的电能(购电+光伏+放电)低于小区负载"的缺口，不含充电量
    e = np.maximum(0.0, load - g_final - pv - d_final)
    win = np.zeros(NDAYS, bool); win[REPORT:] = True
    plan_fee = (price_day * g_final * DT)[win].sum()
    adj_fee = (0.5 * price_day * np.abs(g_final - g_plan) * DT)[win].sum()
    em_fee = (5 * price_day * e * DT)[win].sum()
    em_kwh = (e * DT)[win].sum()
    return plan_fee, adj_fee, em_fee, em_kwh


if __name__ == "__main__":
    print(f"K_SCEN={K_SCEN}  统计窗口 2/1–12/31")
    print(f"{'0:00对冲H(kW)':>14}{'计划费':>14}{'调整费':>12}{'紧急费':>13}{'紧急kWh':>13}{'总费':>14}")
    print("-" * 80)
    for H in [float(x) for x in (sys.argv[1:] or ["0", "100", "200", "300", "400", "600"])]:
        t0 = time.time()
        pf, af, ef, ek = run(H)
        print(f"{H:>14.0f}{pf:>14,.0f}{af:>12,.0f}{ef:>13,.0f}{ek:>13,.0f}{pf+af+ef:>14,.0f}"
              f"   ({time.time()-t0:.0f}s)")
