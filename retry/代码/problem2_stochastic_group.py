# -*- coding: utf-8 -*-
"""
问题 2 —— 两阶段随机规划 + SOC 跟踪执行层（修正"不可实现"问题）

基于 CUMCM-C/代码/problem2_stochastic.py，改动两处：
  1) 场景集从"同星期几(近4周)"改为"同组(周末/工作日, 近2周)"，并保留"同星期几"作对比；
  2) 结算从"简化 rollout(不跟踪SOC)"改为"正确执行(逐时段校验 SOC 与充放电上下限)"，
     解决简化结算低估费用(放电被 SOC 下限削减、充电被实际富余削减)的"不可实现"问题。

分组: 周末组 = 周五+周六(d%7∈{2,3}); 工作日组 = 其余(d%7∈{0,1,4,5,6})。

两阶段随机规划不变：
  一阶段(here-and-now): 计划购电 ĝ、计划放电 d̂、SOC 递推；
  二阶段(recourse): 逐场景 充电 c̄_ω(只能吃富余)、紧急 e_ω(只补负载缺口, 5倍价)。
  目标 = Σ p·ĝ + Σ_ω (5p/K_d)·e_ω。

正确执行(逐时段)：
  d_act = min(d̂, (SOC−1200)·η/Δt)                        # 放电受 SOC 下限约束
  c_act = min(c̄, max(0, P+ĝ+d_act−L), (10800−SOC)/(η·Δt)) # 充电受实际富余+SOC上限约束
  e_act = max(0, L − ĝ − P − d_act)                       # 紧急只补负载缺口
  SOC  += (η·c_act − d_act/η)·Δt
"""

import os
import sys
import time
import datetime as dt
import numpy as np
import pandas as pd
from scipy.optimize import linprog
from scipy import sparse
import openpyxl

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

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

BASE = os.path.dirname(os.path.abspath(__file__))          # retry
DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(BASE))), "CUMCM-C", "附件")

df1 = pd.read_excel(os.path.join(DATA, "附件1.xlsx"))
price_day = df1.iloc[:, 1].to_numpy(float)
dfL = pd.read_excel(os.path.join(DATA, "附件2.xlsx"), sheet_name="小区负载")
dfP = pd.read_excel(os.path.join(DATA, "附件2.xlsx"), sheet_name="光伏发电实际功率")
load = dfL.iloc[:, 1:1 + N].to_numpy(float)
pv = dfP.iloc[:, 1:1 + N].to_numpy(float)

price = np.tile(price_day, NDAYS)
mean_load, mean_pv = load.mean(axis=0), pv.mean(axis=0)
win = np.zeros(T, dtype=bool); win[REPORT * N:] = True


def group_mask(d):
    """True=周末组(周五+周六), False=工作日组。d 为 day_index(0=2025-01-01周三)。"""
    return (d % 7) in (2, 3)


def build_peers_weekday():
    peers = []
    for d in range(NDAYS):
        ps = [d - 7 * k for k in range(1, K_PEERS + 1) if d - 7 * k >= 0]
        peers.append(ps)
    return peers


def build_peers_group():
    g_all = np.array([group_mask(d) for d in range(NDAYS)])
    peers = []
    for d in range(NDAYS):
        g = g_all[d]
        ps = [t for t in range(max(0, d - 14), d) if g_all[t] == g]
        peers.append(ps)
    return peers


def solve_full_year(b_eq_net):
    """完美预见(确定性 LP, 用实际净需求)。返回 g, c, d, fun。"""
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
    b_eq = np.concatenate([b_eq_net, np.zeros(T)])
    bounds = ([(0, None)] * T + [(0, P_MAX)] * T + [(0, P_MAX)] * T + [(0, None)] * T
              + [(SOC0, SOC0)] + [(SOC_MIN, SOC_MAX)] * (T - 1) + [(SOC0, SOC0)])
    res = linprog(c_obj, A_eq=A_eq, b_eq=b_eq, bounds=bounds, method="highs")
    assert res.success, res.message
    x = res.x
    return x[G0:G0 + T], x[C0:C0 + T], x[D0:D0 + T], res.fun


def solve_stochastic(peers, tag=""):
    """两阶段随机规划。返回 (ĝ, d̂, c̄, soc_plan, 简化费用, 简化紧急)。"""
    E_total = sum(len(ps) * N for ps in peers)
    G0, D0, S_idx = 0, T, 2 * T
    CB0 = 3 * T + 1
    E0 = CB0 + E_total
    n_vars = E0 + E_total

    base_e = np.zeros(NDAYS, dtype=np.int64)
    cnt = 0
    for d in range(NDAYS):
        base_e[d] = cnt; cnt += len(peers[d]) * N

    c_obj = np.zeros(n_vars)
    c_obj[G0:G0 + T] = price
    for d in range(NDAYS):
        Kd = len(peers[d])
        if Kd == 0:
            continue
        for w in range(Kd):
            sl = slice(base_e[d] + w * N, base_e[d] + (w + 1) * N)
            c_obj[E0 + sl.start:E0 + sl.stop] = 5.0 * price_day / Kd

    t = np.arange(T)
    eq_rows = [t, t, t]
    eq_cols = [S_idx + t + 1, S_idx + t, D0 + t]
    eq_data = [np.ones(T), -np.ones(T), (DT / ETA) * np.ones(T)]
    for d in range(NDAYS):
        Kd = len(peers[d])
        if Kd == 0:
            continue
        td = d * N + np.arange(N)
        for w in range(Kd):
            sl = slice(base_e[d] + w * N, base_e[d] + (w + 1) * N)
            eq_rows.append(td); eq_cols.append(CB0 + np.arange(sl.start, sl.stop))
            eq_data.append(-ETA * DT / Kd * np.ones(N))
    A_eq = sparse.coo_matrix((np.concatenate(eq_data),
                              (np.concatenate(eq_rows), np.concatenate(eq_cols))),
                             shape=(T, n_vars)).tocsr()
    b_eq = np.zeros(T)

    nz = 6 * E_total
    ub_row = np.empty(nz, dtype=np.int64); ub_col = np.empty(nz, dtype=np.int64)
    ub_dat = np.empty(nz); ub_b = np.empty(2 * E_total)
    p = 0
    for d in range(NDAYS):
        for w, pd_ in enumerate(peers[d]):
            sl = slice(base_e[d] + w * N, base_e[d] + (w + 1) * N)
            r = np.arange(sl.start, sl.stop)
            r1, r2 = r, E_total + r
            t = d * N + np.arange(N)
            ub_row[p:p + N] = r1; ub_col[p:p + N] = CB0 + r; ub_dat[p:p + N] = +1.0; p += N
            ub_row[p:p + N] = r1; ub_col[p:p + N] = G0 + t;  ub_dat[p:p + N] = -1.0; p += N
            ub_row[p:p + N] = r1; ub_col[p:p + N] = D0 + t;  ub_dat[p:p + N] = -1.0; p += N
            ub_b[r1] = pv[pd_] - load[pd_]
            ub_row[p:p + N] = r2; ub_col[p:p + N] = G0 + t;  ub_dat[p:p + N] = -1.0; p += N
            ub_row[p:p + N] = r2; ub_col[p:p + N] = D0 + t;  ub_dat[p:p + N] = -1.0; p += N
            ub_row[p:p + N] = r2; ub_col[p:p + N] = E0 + r;  ub_dat[p:p + N] = -1.0; p += N
            ub_b[r2] = pv[pd_] - load[pd_]
    A_ub = sparse.coo_matrix((ub_dat, (ub_row, ub_col)), shape=(2 * E_total, n_vars)).tocsr()

    bounds = ([(0, None)] * T + [(0, P_MAX)] * T
              + [(SOC0, SOC0)] + [(SOC_MIN, SOC_MAX)] * (T - 1) + [(SOC0, SOC0)]
              + [(0, P_MAX)] * E_total + [(0, None)] * E_total)

    t0 = time.time()
    res = linprog(c_obj, A_eq=A_eq, b_eq=b_eq, A_ub=A_ub, b_ub=ub_b, bounds=bounds, method="highs")
    assert res.success, res.message
    x = res.x
    g = x[G0:G0 + T]
    d_hat = x[D0:D0 + T]
    soc_plan = x[S_idx:S_idx + T + 1]
    c = np.zeros(T)
    for d in range(NDAYS):
        Kd = len(peers[d])
        if Kd == 0:
            continue
        sl = d * N + np.arange(N)
        for w in range(Kd):
            st = CB0 + base_e[d] + w * N
            c[sl] += x[st:st + N] / Kd
    # 简化结算(不跟踪SOC, 仅用于对照)
    e_simp = np.maximum(0.0, load.ravel() - g - pv.ravel() - d_hat)
    cost_simp = (price * g * DT)[win].sum() + (5 * price * e_simp * DT)[win].sum()
    em_simp = (e_simp * DT)[win].sum()
    print(f"  [{tag}] 场景 {E_total:,}, 变量 {n_vars:,}, 求解 {time.time()-t0:.1f}s, "
          f"简化费用 {cost_simp:,.0f} 元")
    return g, d_hat, c, soc_plan, cost_simp, em_simp


def proper_rollout(g, d, c):
    """正确执行：逐时段校验 SOC 与充放电上下限。返回 (费用, 紧急量, SOC轨迹, d_act, c_act, e_act)。"""
    L = load.ravel(); P = pv.ravel()
    soc = SOC0
    d_act = np.zeros(T); c_act = np.zeros(T); e_act = np.zeros(T)
    for t in range(T):
        d_max = max(0.0, (soc - SOC_MIN) * ETA / DT)
        dt_ = min(d[t], d_max)
        c_max = max(0.0, (SOC_MAX - soc) / (ETA * DT))
        surplus = P[t] + g[t] + dt_ - L[t]
        ct_ = min(c[t], max(0.0, surplus), c_max)
        soc += (ETA * ct_ - dt_ / ETA) * DT
        e_act[t] = max(0.0, L[t] - g[t] - P[t] - dt_)
        d_act[t] = dt_; c_act[t] = ct_
    planned = (price * g * DT)[win].sum()
    emerg = (5 * price * e_act * DT)[win].sum()
    return planned + emerg, (e_act * DT)[win].sum(), d_act, c_act, e_act


def fmt_time(m):
    m = int(m)
    return "24:00" if m >= 1440 else f"{m // 60:02d}:{m % 60:02d}"


def emergency_segments(e_kwh):
    segs = []; i = 0
    while i < N:
        if e_kwh[i] > 1e-6:
            j = i
            while j + 1 < N and e_kwh[j + 1] > 1e-6:
                j += 1
            segs.append((fmt_time(i * 10) + "-" + fmt_time((j + 1) * 10), float(e_kwh[i:j + 1].sum())))
            i = j + 1
        else:
            i += 1
    return segs


def write_result2(g, d_act, c_act, e_act, tag):
    """用正确执行的结果写 result2.xlsx。"""
    g_day = g.reshape(NDAYS, N) * DT
    c_day = c_act.reshape(NDAYS, N) * DT
    d_day = d_act.reshape(NDAYS, N) * DT
    e_day = e_act.reshape(NDAYS, N) * DT

    template = os.path.join(DATA, "附件5", "result2.xlsx")
    out_path = os.path.join(BASE, f"result2_{tag}.xlsx")
    wb = openpyxl.load_workbook(template)
    report_days = range(REPORT, NDAYS)
    blocks = [("0:00-4:00", 0, 24), ("4:00-8:00", 24, 48), ("8:00-12:00", 48, 72),
              ("12:00-16:00", 72, 96), ("16:00-20:00", 96, 120), ("20:00-24:00", 120, 144)]

    # 实际 SOC 轨迹(逐日 0:00)
    soc = np.zeros(T + 1); soc[0] = SOC0
    for t in range(T):
        soc[t + 1] = soc[t] + (ETA * c_act[t] - d_act[t] / ETA) * DT
    soc_midnight = soc[::N]

    ws_p = wb["计划购电量"]
    for j, di in enumerate(report_days):
        row = j + 2
        for k in range(N):
            ws_p.cell(row=row, column=2 + k).value = round(float(g_day[di][(k + 1) % N]), 4)
        ws_p.cell(row=row, column=2 + N).value = round(float(g_day[di].sum()), 4)
        ws_p.cell(row=row, column=3 + N).value = round(float((price_day * g_day[di]).sum()
                                                            + (5 * price_day * e_day[di]).sum()), 2)

    ws_c = wb["充放电量"]
    ws_c.delete_rows(2, ws_c.max_row - 1)
    date0 = dt.date(2025, 1, 1)
    for j, di in enumerate(report_days):
        base = j * 6 + 2
        dv = date0 + dt.timedelta(days=di)
        for bj, (name, a, b) in enumerate(blocks):
            r = base + bj
            ws_c.cell(row=r, column=1).value = dv if bj == 0 else None
            ws_c.cell(row=r, column=2).value = name
            ws_c.cell(row=r, column=3).value = round(float(c_day[di][a:b].sum()), 4)
            ws_c.cell(row=r, column=4).value = round(float(d_day[di][a:b].sum()), 4)
        ws_c.cell(row=base, column=5).value = "0:00"
        ws_c.cell(row=base, column=6).value = round(float(soc_midnight[di]), 4)
        ws_c.cell(row=base + 1, column=5).value = "24:00"
        ws_c.cell(row=base + 1, column=6).value = round(float(soc_midnight[di + 1]), 4)

    ws_e = wb["紧急购电量"]
    ws_e.delete_rows(2, ws_e.max_row - 1)
    r = 2
    for j, di in enumerate(report_days):
        segs = emergency_segments(e_day[di])
        ws_e.cell(row=r, column=1).value = date0 + dt.timedelta(days=di)
        if segs:
            for tstr, kwh in segs:
                ws_e.cell(row=r, column=2).value = tstr
                ws_e.cell(row=r, column=3).value = round(kwh, 4)
                r += 1
        else:
            ws_e.cell(row=r, column=3).value = 0.0
            r += 1
    wb.save(out_path)
    return out_path


if __name__ == "__main__":
    # 完美预见下界
    g_pf, c_pf, d_pf, fun_pf = solve_full_year(load.ravel() - pv.ravel())
    e_pf = np.maximum(0.0, load.ravel() - g_pf - pv.ravel() - d_pf)
    cost_pf = (price * g_pf * DT)[win].sum() + (5 * price * e_pf * DT)[win].sum()

    print("=" * 88)
    print("问题2 两阶段随机规划 + SOC 跟踪执行：同组 vs 同星期几")
    print("=" * 88)
    print(f"  完美预见下界 : {cost_pf:,.0f} 元\n")

    results = {}
    for tag, builder in [("同星期几", build_peers_weekday), ("同组", build_peers_group)]:
        g, d, c, soc_plan, cost_simp, em_simp = solve_stochastic(builder(), tag)
        cost_prop, em_prop, d_act, c_act, e_act = proper_rollout(g, d, c)
        results[tag] = dict(g=g, d_act=d_act, c_act=c_act, e_act=e_act,
                            cost_prop=cost_prop, em_prop=em_prop)
        print(f"    {tag}: 简化 {cost_simp:,.0f} → 正确执行 {cost_prop:,.0f} 元, "
              f"紧急 {em_prop:,.0f} kWh")

    print("\n" + "=" * 88)
    print(f"{'场景集':<12}{'正确执行费用(元)':>20}{'紧急购电量(kWh)':>20}")
    print("-" * 88)
    for tag in ["同星期几", "同组"]:
        print(f"{tag:<12}{results[tag]['cost_prop']:>20,.0f}{results[tag]['em_prop']:>20,.0f}")
    print("-" * 88)
    diff = results["同组"]["cost_prop"] - results["同星期几"]["cost_prop"]
    print(f"同组相对同星期几 节省 {abs(diff):,.0f} 元 ({diff/results['同星期几']['cost_prop']*100:+.2f}%)")

    # 用"同组"写结果(正确执行)
    r = results["同组"]
    out = write_result2(r["g"], r["d_act"], r["c_act"], r["e_act"], "group")
    print(f"\n同组结果已写入: {out}")
