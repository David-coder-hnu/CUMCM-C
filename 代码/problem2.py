# -*- coding: utf-8 -*-
"""问题 2 —— 微网日前计划购电量 ĝ 与储能调度（可交付储能计划 / deliverable schedule）。

============================================================================
一、口径（题面原文抽取，三处必须同源）
    「除紧急购电费用外，其他时间段的购电费用均按计划购电量计算」
        ⟹ 按 ĝ 付费，用不掉也算钱；超购的代价是 p·Δt，没有退款。
    「每天的电价相同」
        ⟹ 全年共用同一条 144 槽电价剖面，跨日没有价差可套。
    问题 2 **没有终端约束**，题面只给 SOC ∈ [1200, 10800] 与 2025-01-01 0:00 = 6000。
        「年末回到 6000」是**建模假设**（否则最优解会把电池放到 1200 收尾、白赚一池电），
        本项目采纳该假设并在论文中声明。

    统一账本：
        计划购电费 = Σ_{t∈窗口} p_t · ĝ_t · Δt
        紧急购电费 = Σ 5 p_t · e_t · Δt ,   e_t = max(0, L_t − P_t − ĝ_t − d̂_t)
        SOC 递推用【实际可充入】c_t = min(ĉ_t, max(0, ĝ_t + d̂_t + q_t))，q_t = min_ω(P_ω,t − L_ω,t)
        哨兵        完美预见下界（每次报数都必须同时给出）

============================================================================
二、为什么不能把 d̂ 写成一阶段承诺量（本项目旧的错法）
    把 d̂_t（日前承诺放电）与【情景平均充电】E[c̄] 放进同一个 SOC 等式，而真实充电在
    缺电情景被削到 0 ⇒ 实际 SOC 恒低于计划 SOC，d̂ 承诺的电根本不存在。
    实测 914,735 kWh 放电被 SOC 下限卡掉，报出的总费低于"同一 ĝ 下储能完美预见"的
    下界 —— 任何策略（含完美预见）都做不到。

三、本模型：可交付储能计划
    把 SOC 递推里的 E[c̄] 换成"对覆盖率 γ 的可得充电下确界"：
        c_t^min ≤ ĝ_t + d̂_t + q_{γ,t},   q_{γ,t} = { P_ω,t − L_ω,t } 的 (1−γ) 分位
    γ = 1 ⟹ 逐情景全部可交付（计划层 = 执行层，无模拟歧义）。
    目标函数仍是 E[e] 的精确值 —— e 只依赖 (ĝ, d̂)，与 SOC 无关 ——
    所以给定 (ĝ, d̂) 的总费是**闭式**的，不需要任何执行层模拟。

    注意 q 必须用【裸】(P−L)，不能写成 max(0, P−L)：后者在缺电时段给出 q=0，
    于是 c^min ≤ ĝ+d 与 e ≥ L−P−ĝ−d 同时成立 —— 同一份 ĝ+d 既顶负载缺口又给电池充电，
    凭空造电（实测全年总费掉到 3,061,112 元，远低于完美预见下界 12,229,461 元）。

四、保留（必须写进论文）
    γ=1 的"可交付"是**对建模情景集**（同星期几的历史日）而言，不是分布无关的鲁棒保证。
    自检口径见 soc_trace：充电按【全情景中最小的可得富余】保守重放，得到真实 SOC 的下界；
    该下界 ≥ 1200 ⟺ 计划列出的放电量在任何情景里都放得出来。交付计划该下界 = 1200.0。

    对照：点预测计划（负荷同星期几均值 + 光伏近 7 天均值）账面比 γ=1 便宜，
    但用同一保守口径重放，真实 SOC 下界为 **−902,669 kWh**（52,409 个槽低于 1200）。
    由于该重放本身就是真实 SOC 的下界，点预测计划**确凿不可交付** ——
    它便宜是因为把电池放穿了，计划里承诺的放电量根本不存在。不能引用它的价格。

五、未竟事项（如实记录，勿在论文中夸大）
    "把一阶段决策放进仿真回路标定"（ĝ 对着可执行的滚动 MPC 标定）**已尝试且失败**：
    在同一个诚实账本下，可执行的因果 MPC 全年最好只有 19,958,082 元，
    比本模型的 15,187,755 元**贵 31%**。瓶颈不在 ĝ 规则，在执行器的跨时段 SOC 管理
    （标量末端影子价格 λ 无法同时表达"留住电量"与"用掉电量"）。
    所以本文件交付的是**开环可交付计划**，不是"在线最优策略"。
    详见 文档/问题2_求解归档.md §5。

用法：
    python 代码/problem2.py                # 求解 γ=1 并写 结果/result2.xlsx
    GAMMAS=0.5,0.75,1.0 python 代码/problem2.py   # γ 敏感性（仅 γ=1 可引用）
"""
import datetime as dt
import os
import sys
import time

import numpy as np
import pandas as pd
from scipy.optimize import linprog
from scipy import sparse

# Windows 下 stdout 重定向到文件/管道时默认走 GBK，打印 ĝ 等字符会抛 UnicodeEncodeError
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

import openpyxl

# ---------------- 参数 ----------------
DT, ETA, P_MAX = 1.0 / 6.0, 0.9, 5000.0
SOC_MIN, SOC_MAX, SOC0 = 1200.0, 10800.0, 6000.0
N, NDAYS, REPORT = 144, 365, 31
T = N * NDAYS
K_PEERS = 4                     # 情景集：同星期几的历史日
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

price_day = pd.read_excel(os.path.join(BASE, "附件", "附件1.xlsx")).iloc[:, 1].to_numpy(float)
load = pd.read_excel(os.path.join(BASE, "附件", "附件2.xlsx"), sheet_name="小区负载") \
         .iloc[:, 1:1 + N].to_numpy(float)
pv = pd.read_excel(os.path.join(BASE, "附件", "附件2.xlsx"), sheet_name="光伏发电实际功率") \
       .iloc[:, 1:1 + N].to_numpy(float)
price = np.tile(price_day, NDAYS)
win = np.zeros(T, bool); win[REPORT * N:] = True
L = load.ravel(); P = pv.ravel()

peers = [[d - 7 * k for k in range(1, K_PEERS + 1) if d - 7 * k >= 0] for d in range(NDAYS)]
base_e = np.zeros(NDAYS, dtype=np.int64)
_c = 0
for d in range(NDAYS):
    base_e[d] = _c
    _c += max(1, len(peers[d])) * N          # 场景数下限取 1（前 4 周退化为当日点预报）
E_total = _c

def sc_idx(d):
    """day d 的情景天列表；前 4 周无同星期几历史时退化为 [d] 本身（单情景）。"""
    return peers[d] if peers[d] else [d]


def honor_cost(g, d):
    """闭式诚实费用：e 只依赖 (ĝ, d̂)，与 SOC 无关。返回 (总费, 计划费, 紧急费, 紧急 kWh)。"""
    e = np.maximum(0.0, L - g - P - d)
    planned = (price * g * DT)[win].sum()
    emerg = (5 * price * e * DT)[win].sum()
    return planned + emerg, planned, emerg, (e * DT)[win].sum()


def soc_trace(g, d, cm):
    """真实 SOC 轨迹：充电按【全部情景里最小的可得富余】保守重放，得真实 SOC 的下界。
    计划可交付 ⟺ 该下界 ≥ SOC_MIN。"""
    surp_min = np.empty(T)
    for dd in range(NDAYS):
        p = sc_idx(dd)
        surp_min[dd * N:(dd + 1) * N] = (pv[p] - load[p]).min(axis=0)
    c_real = np.minimum(cm, np.maximum(0.0, g + d + surp_min))
    return SOC0 + np.concatenate([[0.0],
           np.cumsum(ETA * c_real * DT - d * DT / ETA)])


def solve_deliver(gamma):
    """γ 覆盖率下的可交付计划 LP。gamma=1 → q = min_ω(P_ω − L_ω)（全情景可交付）。"""
    G0, D0, S0_, CM0, E0 = 0, T, 2 * T, 3 * T + 1, 4 * T + 1
    n_vars = E0 + E_total
    q = np.empty(T)
    for dd in range(NDAYS):
        p = sc_idx(dd)
        vals = pv[p] - load[p]                      # 必须用裸 (P−L)，见模块 docstring 三
        q[dd * N:(dd + 1) * N] = np.quantile(vals, 1.0 - gamma, axis=0) \
            if len(p) > 1 else vals[0]

    c_obj = np.zeros(n_vars)
    c_obj[G0:G0 + T] = price
    for dd in range(NDAYS):
        p = sc_idx(dd); Kd = len(p)
        for w in range(Kd):
            sl = slice(base_e[dd] + w * N, base_e[dd] + (w + 1) * N)
            c_obj[E0 + sl.start:E0 + sl.stop] = 5.0 * price_day / Kd

    t = np.arange(T)
    # SOC 递推：S_{t+1} − S_t − ηΔt·cmin_t + (Δt/η)·d_t = 0
    A_eq = sparse.coo_matrix(
        (np.concatenate([np.ones(T), -np.ones(T), -ETA * DT * np.ones(T), (DT / ETA) * np.ones(T)]),
         (np.concatenate([t, t, t, t]),
          np.concatenate([S0_ + t + 1, S0_ + t, CM0 + t, D0 + t]))),
        shape=(T, n_vars)).tocsr()

    # 不等式 (1) cmin − g − d ≤ q        (2) −g − d − e ≤ p − l
    n1, n2 = T, E_total
    ur, uc, ud, ub = [], [], [], []
    ur += [t, t, t]
    uc += [CM0 + t, G0 + t, D0 + t]
    ud += [np.ones(T), -np.ones(T), -np.ones(T)]
    ub.append(q)
    for dd in range(NDAYS):
        for w, pd_ in enumerate(sc_idx(dd)):
            r = base_e[dd] + w * N
            rr = n1 + np.arange(r, r + N)
            tt = dd * N + np.arange(N)
            ur += [rr, rr, rr]
            uc += [G0 + tt, D0 + tt, E0 + np.arange(r, r + N)]
            ud += [-np.ones(N), -np.ones(N), -np.ones(N)]
            ub.append(pv[pd_] - load[pd_])
    A_ub = sparse.coo_matrix((np.concatenate(ud), (np.concatenate(ur), np.concatenate(uc))),
                             shape=(n1 + n2, n_vars)).tocsr()

    bounds = ([(0, None)] * T + [(0, P_MAX)] * T
              + [(SOC0, SOC0)] + [(SOC_MIN, SOC_MAX)] * (T - 1) + [(SOC0, SOC0)]
              + [(0, P_MAX)] * T + [(0, None)] * E_total)
    t0 = time.time()
    res = linprog(c_obj, A_eq=A_eq, b_eq=np.zeros(T), A_ub=A_ub, b_ub=np.concatenate(ub),
                  bounds=bounds, method="highs")
    assert res.success, res.message
    x = res.x
    return x[G0:G0 + T], x[D0:D0 + T], x[CM0:CM0 + T], x[S0_:S0_ + T + 1], time.time() - t0


def solve_full_year(N_hat):
    """确定性全年 LP（完美预见下界 / 点预测共用骨架），返回 (g, c, d)。"""
    G0, C0, D0, S0_, S_idx = 0, T, 2 * T, 3 * T, 4 * T
    n_vars = 5 * T + 1
    c_obj = np.zeros(n_vars); c_obj[G0:G0 + T] = price
    t = np.arange(T)
    A_eq = sparse.coo_matrix(
        (np.concatenate([np.ones(T), -np.ones(T), np.ones(T), -np.ones(T),
                         np.ones(T), -np.ones(T), -ETA * DT * np.ones(T), (DT / ETA) * np.ones(T)]),
         (np.concatenate([t, t, t, t, T + t, T + t, T + t, T + t]),
          np.concatenate([G0 + t, C0 + t, D0 + t, S0_ + t,
                          S_idx + t + 1, S_idx + t, C0 + t, D0 + t]))),
        shape=(2 * T, n_vars)).tocsr()
    b_eq = np.concatenate([N_hat, np.zeros(T)])
    bounds = ([(0, None)] * T + [(0, P_MAX)] * T + [(0, P_MAX)] * T + [(0, None)] * T
              + [(SOC0, SOC0)] + [(SOC_MIN, SOC_MAX)] * (T - 1) + [(SOC0, SOC0)])
    res = linprog(c_obj, A_eq=A_eq, b_eq=b_eq, bounds=bounds, method="highs")
    assert res.success, res.message
    x = res.x
    return x[G0:G0 + T], x[C0:C0 + T], x[D0:D0 + T]


# ============================ 主流程 ============================
print("=" * 100)
print("问题 2：可交付储能计划（deliverable schedule）")
print("=" * 100)

# ---- 哨兵：完美预见下界（任何低于它的结果都是 bug）----
g_pf, c_pf, d_pf = solve_full_year(L - P)
sent = honor_cost(g_pf, d_pf)
print(f"{'完美预见下界(哨兵)':<24}{sent[1]:>14,.0f}{sent[2]:>14,.0f}"
      f"{sent[3]:>16,.0f}{sent[0]:>16,.0f}")

# ---- 参照：点预测（负荷同星期几 + 光伏近 7 天）----
L_hat = np.empty_like(load)
for d in range(NDAYS):
    idx = peers[d]
    L_hat[d] = load[idx].mean(axis=0) if idx else load.mean(axis=0)
P_hat = np.empty_like(pv)
for d in range(NDAYS):
    lo = max(0, d - 7)
    P_hat[d] = pv[lo:d].mean(axis=0) if lo < d else pv.mean(axis=0)
g_pt, c_pt, d_pt = solve_full_year((L_hat - P_hat).ravel())
pt = honor_cost(g_pt, d_pt)

print("-" * 100)
print(f"{'γ 可交付覆盖率':<24}{'计划费(元)':>14}{'紧急费(元)':>14}{'紧急kWh':>16}{'总费(元)':>16}")
print("-" * 100)
best = None
for gamma in [float(x) for x in os.environ.get("GAMMAS", "0,0.25,0.5,0.75,1.0").split(",")]:
    g, d, cm, soc, el = solve_deliver(gamma)
    r = honor_cost(g, d)
    print(f"{f'γ={gamma:.2f}  ({el:.0f}s)':<24}{r[1]:>14,.0f}{r[2]:>14,.0f}{r[3]:>16,.0f}{r[0]:>16,.0f}")
    if gamma >= 1.0 - 1e-9:
        smin = soc_trace(g, d, cm).min()
        print(f"{'  └ 真实SOC下界':<24}{smin:>14,.1f} kWh   "
              f"（≥ {SOC_MIN:.0f} 才说明计划可交付）")
    if best is None or r[0] < best[0]:
        best = (r[0], gamma, g, d, cm, soc)

print("-" * 100)
print(f"  点预测计划（同账本）     {pt[1]:>14,.0f}{pt[2]:>14,.0f}{pt[3]:>16,.0f}{pt[0]:>16,.0f}")
sm_pt = soc_trace(g_pt, d_pt, c_pt).min()
print(f"{'  └ 真实SOC下界':<24}{sm_pt:>14,.1f} kWh   "
      f"（{'可交付' if sm_pt >= SOC_MIN - 1e-6 else '不可交付：账面便宜是因为把电池放穿了'}）")
print(f"  哨兵：完美预见下界 {sent[0]:,.0f} 元 —— 任何低于它的结果都是 bug")
# 自检：任何配置低于哨兵都说明模型被放松了（本项目已因此踩坑三次）
_r = honor_cost(best[2], best[3])[0]
assert _r >= sent[0] - 1e-6, \
    f"总费 {_r:,.0f} 低于完美预见下界 {sent[0]:,.0f} —— 模型被放松了，检查 bounds/约束"

# ---- 交付：γ=1（唯一可引用的一档）----
g1, d1, cm1, soc1 = solve_deliver(1.0)[:4]
r1 = honor_cost(g1, d1)
print()
print("=" * 100)
print(f"交付计划 γ=1：计划 {r1[1]:,.0f}  紧急 {r1[2]:,.0f} ({r1[3]:,.0f} kWh)  总 {r1[0]:,.0f} 元")
print(f"  哨兵下界 {sent[0]:,.0f} 元 ｜ 高出 {(r1[0] / sent[0] - 1) * 100:.1f}%")
print(f"  点预测   {pt[0]:,.0f} 元 ｜ γ=1 比它 {'省' if r1[0] < pt[0] else '贵'} "
      f"{abs(pt[0] - r1[0]):,.0f} 元")
print("=" * 100)

# ---- 写 结果/result2.xlsx（沿用 附件5 模板）----
e1 = np.maximum(0.0, L - g1 - P - d1)
g_day = (g1 * DT).reshape(NDAYS, N)
c_day = (cm1 * DT).reshape(NDAYS, N)
d_day = (d1 * DT).reshape(NDAYS, N)
e_day = (e1 * DT).reshape(NDAYS, N)
soc_midnight = soc1[::N]


def fmt_time(m):
    m = int(m)
    return "24:00" if m >= 1440 else f"{m // 60:02d}:{m % 60:02d}"


def emergency_segments(e_kwh):
    """把一天 144 个区间的紧急购电量(kWh)聚成连续时间段。"""
    segs, i = [], 0
    while i < N:
        if e_kwh[i] > 1e-6:
            j = i
            while j + 1 < N and e_kwh[j + 1] > 1e-6:
                j += 1
            segs.append((fmt_time(i * 10) + "-" + fmt_time((j + 1) * 10),
                         float(e_kwh[i:j + 1].sum())))
            i = j + 1
        else:
            i += 1
    return segs


template = os.path.join(BASE, "附件", "附件5", "result2.xlsx")
out_path = os.path.join(BASE, "结果", "result2.xlsx")
os.makedirs(os.path.dirname(out_path), exist_ok=True)
wb = openpyxl.load_workbook(template)

report_days = range(REPORT, NDAYS)
blocks = [("0:00-4:00", 0, 24), ("4:00-8:00", 24, 48), ("8:00-12:00", 48, 72),
          ("12:00-16:00", 72, 96), ("16:00-20:00", 96, 120), ("20:00-24:00", 120, 144)]

# 「计划购电量」：144 个计划购电量（循环左移 10 分钟）+ 全天购电量 + 全天购电费
ws_p = wb["计划购电量"]
for j, di in enumerate(report_days):
    row = j + 2
    for k in range(N):
        ws_p.cell(row=row, column=2 + k).value = round(float(g_day[di][(k + 1) % N]), 4)
    ws_p.cell(row=row, column=2 + N).value = round(float(g_day[di].sum()), 4)
    ws_p.cell(row=row, column=3 + N).value = round(float((price_day * g_day[di]).sum()
                                                        + (5 * price_day * e_day[di]).sum()), 2)

# 「充放电量」：334 天 × 6 块 + 0:00/24:00 储电量
ws_c = wb["充放电量"]
ws_c.delete_rows(2, ws_c.max_row - 1)
date0 = dt.date(2025, 1, 1)
for j, di in enumerate(report_days):
    base = j * 6 + 2
    date_val = date0 + dt.timedelta(days=di)
    for bj, (name, a, b) in enumerate(blocks):
        r = base + bj
        ws_c.cell(row=r, column=1).value = date_val if bj == 0 else None
        ws_c.cell(row=r, column=2).value = name
        ws_c.cell(row=r, column=3).value = round(float(c_day[di][a:b].sum()), 4)
        ws_c.cell(row=r, column=4).value = round(float(d_day[di][a:b].sum()), 4)
    ws_c.cell(row=base, column=5).value = "0:00"
    ws_c.cell(row=base, column=6).value = round(float(soc_midnight[di]), 4)
    ws_c.cell(row=base + 1, column=5).value = "24:00"
    ws_c.cell(row=base + 1, column=6).value = round(float(soc_midnight[di + 1]), 4)

# 「紧急购电量」：每天若干连续时间段
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
print(f"\n计划已写入: {out_path}")
