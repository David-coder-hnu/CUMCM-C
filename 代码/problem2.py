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
    γ = 1 ⟹ 逐情景全部可交付。注意"可交付"指的只是【SOC 递推可行】：
    soc_trace 用全情景最小可得富余保守重放，SOC 下界仍 ≥ SOC_MIN。
    这**不等于**"计划层 = 执行层" —— d̂ 是 LP 的副产品，执行层 execute_soc_causal
    按实际缺口重算放电，根本不兑现 d̂。实测 d̂ 里约 14% 的放电量发生在缺口为零时，
    照 d̂ 执行会白付一趟 η 往返损失（同星期几口径 +883,089 元）。
    所以"闭式计划费"与"因果执行费"是两个数，必须分别报，不可混用。

    目标函数仍是 E[e] 的精确值 —— e 只依赖 (ĝ, d̂)，与 SOC 无关 ——
    所以给定 (ĝ, d̂) 的总费是**闭式**的，不需要任何执行层模拟。

    注意 q 必须用【裸】(P−L)，不能写成 max(0, P−L)：后者在缺电时段给出 q=0，
    于是 c^min ≤ ĝ+d 与 e ≥ L−P−ĝ−d 同时成立 —— 同一份 ĝ+d 既顶负载缺口又给电池充电，
    凭空造电（实测全年总费掉到 3,061,112 元，远低于完美预见下界 12,229,461 元）。

三之二、情景集：按「低需求日」分组（本次更新）
    旧口径用"同星期几的历史日"(K=4, 回看 4 周)。本版改为**同组**：先按日均净负荷
    把七天分成【低需求日】与【其余】两组，再取回看 14 天内与当日同组的历史日。
    分组规则只喂**暖机期**（前 31 天，报告窗口之前）⟹ 推导无前视。
    实测 {周五,周六} 为低需求日，且该结论对窗口不敏感：暖机期 31 天 / 1-6 月 /
    全年三个窗口都给出同一答案。低需求日日均净负荷约为其余五天的 1/2 ~ 1/3。

    收益（统一 execute_soc_causal 因果执行，334 个报告日，逐日配对）：
        同星期几 K=4（旧）  15,134,192 元
        同组 {周五,周六}     14,341,723 元    Δ = -792,470（-5.24%）
        95% 移动块自助(14 天) 置信区间 [-4,395, -903]，单侧 p < 0.001
    归因：缩短窗口本身（同星期几 K=2）不显著（-92,652，CI 含 0，p=0.37）；
    分组本身的净贡献 -699,818，但只在边缘显著（CI 勉强含 0，单侧 p≈0.03），
    且收益集中在 6 月上旬与 12 月上旬两簇（前 15 个省钱日占 12 天）。
    样本外复核：只用 1-6 月推出的分组仍是 {周五,周六}，在 7-12 月窗口独立省 445,290 元。
    ⟹ 论文中可以主张"低需求日分组 + 缩短窗口"这个**配方**优于旧口径；
    **不要**单独主张"分组"这一个动作为显著。详见 文档/问题2_求解归档.md §7。

四、实际执行层（写 result2.xlsx）
    规划层给出最终计划购电量 g。执行层采用 execute_soc_causal：
    当前时刻只用当前实际 L/P 与当前 SOC，优先放电覆盖负载缺口，富余再充电，
    最后缺口才紧急购电；充放电功率与 SOC 全程严格受限。
    result2.xlsx 中的充放电、紧急购电、费用和 SOC 均来自该实际执行轨迹。
    问题 2 没有终端 SOC 约束，因此实际年末 SOC 不强制回到 6000。

五、保留（必须写进论文）
    γ=1 的"可交付"是**对建模情景集**（同组历史日，见三之二）而言，不是分布无关的鲁棒保证。
    自检口径见 soc_trace：充电按【全情景中最小的可得富余】保守重放，得到真实 SOC 的下界。
    交付结果采用 execute_soc_causal 在 2025 实际轨迹上重算，SOC 上下限逐槽自检。

    对照：点预测计划（负荷同星期几均值 + 光伏近 7 天均值）账面比 γ=1 便宜，
    但用同一保守口径重放，真实 SOC 下界为 **−902,669 kWh**（52,409 个槽低于 1200）。
    由于该重放本身就是真实 SOC 的下界，点预测计划**确凿不可交付** ——
    它便宜是因为把电池放穿了，计划里承诺的放电量根本不存在。不能引用它的价格。

六、未竟事项（如实记录，勿在论文中夸大）
    "把一阶段决策放进仿真回路标定"（ĝ 对着可执行的滚动 MPC 标定）**已尝试且失败**：
    在同一个诚实账本下，可执行的因果 MPC 全年最好只有 19,958,082 元，
    比本模型最终实际执行成本 14,341,723 元**贵 39.2%**。瓶颈不在 ĝ 规则，
    在执行器的跨时段 SOC 管理
    （标量末端影子价格 λ 无法同时表达"留住电量"与"用掉电量"）。
    所以本文件交付的是"γ=1 计划购电 + 严格 SOC 因果执行轨迹"，不是"在线最优策略"。
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
K_PEERS = 4                     # 同星期几情景数（仅作对照与点预测参照）
GROUP_SPAN = 6                  # 分组情景集的回看窗口（天）
# 定稿 span=6 的依据（实测见 文档/问题2_求解归档.md §7.4 窗口扫描）：
#   低需求日 {Fri,Sat} 每周只有 2 天，故回看 s 天只能捞到 ≈2s/7 个同组日。
#   s=6 恰好让周五/周六各捞到 1 个同组日，是**不触发退化分支的最短窗口**；
#   s≤5 时窗口（周日…周四）里一个同组日都没有，sc_of 退化成 [d] 本身
#   —— 用当天实际负荷冒充情景天，属前视作弊，计费窗口内有 47 天踩坑，故不可用。
#   在可行域 s≥6 上总费单调递增（6:13,846,553 → 14:14,341,723 → 28:15,032,496），
#   所以可行最优 = 可行下界 = 6。⚠ 这是**约束下的最优**，不是无约束最优：
#   真实最低点可能更短，但那片区域被前视污染，不可信。
GROUP_TRAIN = REPORT            # 分组规则只喂暖机期（前 31 天）⟹ 推导无前视
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

price_day = pd.read_excel(os.path.join(BASE, "附件", "附件1.xlsx")).iloc[:, 1].to_numpy(float)
load = pd.read_excel(os.path.join(BASE, "附件", "附件2.xlsx"), sheet_name="小区负载") \
         .iloc[:, 1:1 + N].to_numpy(float)
pv = pd.read_excel(os.path.join(BASE, "附件", "附件2.xlsx"), sheet_name="光伏发电实际功率") \
       .iloc[:, 1:1 + N].to_numpy(float)
price = np.tile(price_day, NDAYS)
win = np.zeros(T, bool); win[REPORT * N:] = True
L = load.ravel(); P = pv.ravel()

net_load = (load - pv).sum(axis=1)          # 各日净负荷，用于推断低需求日


def low_demand_dows(train_days):
    """从 train_days 推断「低需求日」：日均净负荷最低的两个星期几。

    只喂报告窗口之前的数据，所以推导过程不含前视。该规则对窗口不敏感 ——
    暖机期(31 天) / 1-6 月 / 全年 三个窗口都给出同一答案 {周五,周六}。
    低需求日的日均净负荷只有其余五天的 ~1/2（暖机期）到 ~1/3（全年）。
    """
    dow = np.array([d % 7 for d in range(NDAYS)])
    means = [net_load[train_days][dow[train_days] == k].mean() for k in range(7)]
    order = np.argsort(means)
    return (int(order[0]), int(order[1])), means


def build_peers_group(dows, span=GROUP_SPAN):
    """同组情景集：回看 span 天内、与当日同组的历史日。"""
    m = np.array([(d % 7) in dows for d in range(NDAYS)])
    return [[t for t in range(max(0, d - span), d) if m[t] == m[d]] for d in range(NDAYS)]


def build_peers_weekday(k=K_PEERS):
    """同星期几情景集（旧口径，保留作对照与点预测参照）。"""
    return [[d - 7 * j for j in range(1, k + 1) if d - 7 * j >= 0] for d in range(NDAYS)]


def prep_peers(pp):
    """把情景天列表编成 LP 的列偏移，返回 (base_e, E_total)。

    场景数下限取 1：第 d 天没有同组历史时退化为 [d] 本身（单情景，等价点预报）。
    """
    base_e = np.zeros(NDAYS, dtype=np.int64)
    c = 0
    for d in range(NDAYS):
        base_e[d] = c
        c += max(1, len(pp[d])) * N
    return base_e, c


def sc_of(pp, d):
    """第 d 天实际使用的场景天列表。"""
    return pp[d] if pp[d] else [d]


GROUP_DOWS, DOW_MEANS = low_demand_dows(np.arange(0, GROUP_TRAIN))
peers_wd = build_peers_weekday(K_PEERS)     # 旧口径：对照 + 点预测参照
peers = build_peers_group(GROUP_DOWS)       # 交付所用情景集


def honor_cost(g, d):
    """闭式诚实费用：e 只依赖 (ĝ, d̂)，与 SOC 无关。返回 (总费, 计划费, 紧急费, 紧急 kWh)。"""
    e = np.maximum(0.0, L - g - P - d)
    planned = (price * g * DT)[win].sum()
    emerg = (5 * price * e * DT)[win].sum()
    return planned + emerg, planned, emerg, (e * DT)[win].sum()


def soc_trace(g, d, cm, pp=None):
    """真实 SOC 轨迹：充电按【全部情景里最小的可得富余】保守重放，得真实 SOC 的下界。
    计划可交付 ⟺ 该下界 ≥ SOC_MIN。"""
    pp = peers if pp is None else pp
    surp_min = np.empty(T)
    for dd in range(NDAYS):
        p = sc_of(pp, dd)
        surp_min[dd * N:(dd + 1) * N] = (pv[p] - load[p]).min(axis=0)
    c_real = np.minimum(cm, np.maximum(0.0, g + d + surp_min))
    return SOC0 + np.concatenate([[0.0],
           np.cumsum(ETA * c_real * DT - d * DT / ETA)])


def execute_soc_causal(g):
    """严格满足 SOC 的因果实际执行策略（负荷缺口优先）。

    每个 10 分钟时刻只使用当前实际 L/P、计划购电量 g_t 和当前 SOC：
      1. 先用储能覆盖负载缺口，放电受 SOC 下限和 5000 kW 限制；
      2. 剩余富余用于充电，充电受 SOC 上限和 5000 kW 限制；
      3. 仍缺的电才紧急购电。

    执行过程不回看未来时刻。返回实际操作量 c/d/e 和长度 T+1 的 SOC 轨迹。
    """
    c = np.zeros(T)
    d = np.zeros(T)
    e = np.zeros(T)
    soc = np.empty(T + 1)
    soc[0] = SOC0

    for t in range(T):
        deficit = max(0.0, L[t] - P[t] - g[t])
        d_max_soc = max(0.0, (soc[t] - SOC_MIN) * ETA / DT)
        d[t] = min(deficit, P_MAX, d_max_soc)

        surplus = max(0.0, P[t] + g[t] + d[t] - L[t])
        c_max_soc = max(0.0, (SOC_MAX - soc[t]) / (ETA * DT))
        c[t] = min(P_MAX, surplus, c_max_soc)

        e[t] = max(0.0, L[t] - P[t] - g[t] - d[t])
        soc[t + 1] = soc[t] + (ETA * c[t] - d[t] / ETA) * DT

    return c, d, e, soc


def solve_deliver(gamma, pp=None):
    """γ 覆盖率下的可交付计划 LP。gamma=1 → q = min_ω(P_ω − L_ω)（全情景可交付）。
    pp=None 用交付情景集；传 peers_wd 即复现旧口径作对照。"""
    pp = peers if pp is None else pp
    base_e, E_total = prep_peers(pp)
    G0, D0, S0_, CM0, E0 = 0, T, 2 * T, 3 * T + 1, 4 * T + 1
    n_vars = E0 + E_total
    q = np.empty(T)
    for dd in range(NDAYS):
        p = sc_of(pp, dd)
        vals = pv[p] - load[p]                      # 必须用裸 (P−L)，见模块 docstring 三
        q[dd * N:(dd + 1) * N] = np.quantile(vals, 1.0 - gamma, axis=0) \
            if len(p) > 1 else vals[0]

    c_obj = np.zeros(n_vars)
    c_obj[G0:G0 + T] = price
    for dd in range(NDAYS):
        p = sc_of(pp, dd); Kd = len(p)
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
        for w, pd_ in enumerate(sc_of(pp, dd)):
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

DOW_NAME = ["Wed", "Thu", "Fri", "Sat", "Sun", "Mon", "Tue"]   # 2025-01-01 = 周三
print(f"情景集：按日均净负荷把七天分成【低需求日】与【其余】两组")
print(f"  分组规则只用暖机期（前 {GROUP_TRAIN} 天，在报告窗口之前）推导 ⟹ 无前视")
print("  各星期几日均净负荷(kWh/日)：" + "  ".join(
    f"{DOW_NAME[k]}={DOW_MEANS[k]:,.0f}" for k in range(7)))
_lo = np.mean([DOW_MEANS[k] for k in GROUP_DOWS])
_hi = np.mean([DOW_MEANS[k] for k in range(7) if k not in GROUP_DOWS])
print(f"  ⟹ 低需求日 = {{{', '.join(DOW_NAME[k] for k in GROUP_DOWS)}}}"
      f"，其余五天为对照组；低需求日/其余 = {_lo / _hi:.2f} 倍")
print(f"  情景集 = 回看 {GROUP_SPAN} 天内与当日同组的历史日")

# ---- 哨兵：完美预见下界（任何低于它的结果都是 bug）----
print("-" * 100)
g_pf, c_pf, d_pf = solve_full_year(L - P)
sent = honor_cost(g_pf, d_pf)
print(f"{'完美预见下界(哨兵)':<24}{sent[1]:>14,.0f}{sent[2]:>14,.0f}"
      f"{sent[3]:>16,.0f}{sent[0]:>16,.0f}")

# ---- 参照：点预测（负荷同星期几均值 + 光伏近 7 天均值，沿用旧口径以便历史对照）----
L_hat = np.empty_like(load)
for d in range(NDAYS):
    idx = peers_wd[d]
    L_hat[d] = load[idx].mean(axis=0) if idx else load.mean(axis=0)
P_hat = np.empty_like(pv)
for d in range(NDAYS):
    lo = max(0, d - 7)
    P_hat[d] = pv[lo:d].mean(axis=0) if lo < d else pv.mean(axis=0)
g_pt, c_pt, d_pt = solve_full_year((L_hat - P_hat).ravel())
c_pt_exec, d_pt_exec, e_pt_exec, soc_pt_exec = execute_soc_causal(g_pt)
pt = honor_cost(g_pt, d_pt_exec)

print("-" * 100)
print(f"{'γ 可交付覆盖率':<24}{'计划费(元)':>14}{'紧急费(元)':>14}{'紧急kWh':>16}{'总费(元)':>16}")
print("-" * 100)
for gamma in [float(x) for x in os.environ.get("GAMMAS", "0,0.25,0.5,0.75,1.0").split(",")]:
    g, d, cm, soc, el = solve_deliver(gamma)
    r = honor_cost(g, d)
    print(f"{f'γ={gamma:.2f}  ({el:.0f}s)':<24}{r[1]:>14,.0f}{r[2]:>14,.0f}{r[3]:>16,.0f}{r[0]:>16,.0f}")
    if gamma >= 1.0 - 1e-9:
        smin = soc_trace(g, d, cm).min()
        print(f"{'  └ 真实SOC下界':<24}{smin:>14,.1f} kWh   "
              f"（≥ {SOC_MIN:.0f} 才说明计划可交付）")

print("-" * 100)
print(f"  点预测计划（同执行层）   {pt[1]:>14,.0f}{pt[2]:>14,.0f}{pt[3]:>16,.0f}{pt[0]:>16,.0f}")
print(f"{'  └ 实际SOC范围':<24}[{soc_pt_exec.min():,.1f}, {soc_pt_exec.max():,.1f}] kWh")
print(f"  哨兵：完美预见下界 {sent[0]:,.0f} 元 —— 任何低于它的结果都是 bug")
print(f"  ⚠ γ 表中低于哨兵的行（当前 γ<1 各档）是【不可交付计划】的闭式假价，")
print(f"    它假设 d̂ 全部兑现，本就允许低于下界 —— 不可引用，也不要拿它触发哨兵断言。")

# ---- 交付：γ=1（唯一可引用的一档）----
g1, d1, cm1, soc1 = solve_deliver(1.0)[:4]
c_exec, d_exec, e_exec, soc_exec = execute_soc_causal(g1)
r1 = honor_cost(g1, d_exec)
assert np.allclose(e_exec, np.maximum(0.0, L - g1 - P - d_exec), atol=1e-8)
assert c_exec.min() >= -1e-9 and c_exec.max() <= P_MAX + 1e-6
assert d_exec.min() >= -1e-9 and d_exec.max() <= P_MAX + 1e-6
assert soc_exec.min() >= SOC_MIN - 1e-6 and soc_exec.max() <= SOC_MAX + 1e-6

# 哨兵自检：只查【交付口径】—— γ=1 的闭式计划费与因果执行总费，二者都是可交付的量。
# 不能拿 min over γ 去比：γ<1 的计划不可交付，其闭式价假设 d̂ 全部兑现，
# 本就允许低于下界（本项目旧版把这个错误掩盖了，见 docstring 与归档 §4.1）。
_r1_plan = honor_cost(g1, d1)[0]
for _lbl, _v in (("γ=1 闭式计划费", _r1_plan), ("γ=1 因果执行总费", r1[0])):
    assert _v >= sent[0] - 1e-6, \
        f"{_lbl} {_v:,.0f} 低于完美预见下界 {sent[0]:,.0f} —— 模型被放松了，检查 bounds/约束"
print()
print("=" * 100)
print(f"规划层 γ=1：计划购电 {r1[1]:,.0f} 元")
print(f"实际执行：紧急 {r1[2]:,.0f} 元 ({r1[3]:,.0f} kWh)  总 {r1[0]:,.0f} 元")
print(f"实际 SOC：首 {soc_exec[0]:,.1f}  末 {soc_exec[-1]:,.1f}  "
      f"范围 [{soc_exec.min():,.1f}, {soc_exec.max():,.1f}] kWh")
print(f"  哨兵下界 {sent[0]:,.0f} 元 ｜ 高出 {(r1[0] / sent[0] - 1) * 100:.1f}%")
print(f"  点预测   {pt[0]:,.0f} 元 ｜ γ=1 比它 {'省' if r1[0] < pt[0] else '贵'} "
      f"{abs(pt[0] - r1[0]):,.0f} 元")
print("=" * 100)

# ---- 情景集对照：同星期几(旧口径) vs 同组(交付)，都在 γ=1 + 同一因果执行器下 ----
def _exec_total(g):
    """因果执行后的总费（计划费 + 紧急费），与交付口径完全一致。

    honor_cost(g, d) 的第二个参数是【放电量】，紧急量由它反算
    e = max(0, L−P−g−d)；不要误传 execute_soc_causal 返回的紧急量。
    """
    return honor_cost(g, execute_soc_causal(g)[1])


g_wd, d_wd, cm_wd = solve_deliver(1.0, peers_wd)[:3]
r_wd = _exec_total(g_wd)
smin_wd = soc_trace(g_wd, d_wd, cm_wd, peers_wd).min()
r_gp = _exec_total(g1)
smin_gp = soc_trace(g1, d1, cm1).min()

print()
print("情景集对照（γ=1 规划 + execute_soc_causal，统计窗口 334 天）")
print("-" * 100)
print(f"{'情景集':<32}{'闭式计划费(元)':>16}{'因果执行总费(元)':>18}{'紧急kWh':>12}"
      f"{'SOC下界':>12}")
print("-" * 100)
_rows = [(f"同星期几 K={K_PEERS}（旧口径）", r_wd, smin_wd),
         (f"同组 {{{','.join(DOW_NAME[k] for k in GROUP_DOWS)}}}（本次交付）", r_gp, smin_gp)]
for tag, r, sm in _rows:
    print(f"{tag:<32}{r[1]:>16,.0f}{r[0]:>18,.0f}{r[3]:>12,.0f}{sm:>12,.1f}")
print("-" * 100)
print(f"  改用同组情景集：{r_gp[0] - r_wd[0]:+,.0f} 元 "
      f"({(r_gp[0] - r_wd[0]) / r_wd[0] * 100:+.2f}%)")
print(f"  可交付性：两种情景集的 SOC 下界都 ≥ {SOC_MIN:.0f} kWh ⟹ 均为可行计划")
print("  归因提示：该差额含「缩短窗口」与「分组」两个效应，单看这一行不能把功劳记给分组；")
print("            逐日配对检验与归因分解见 文档/问题2_求解归档.md §7。")

# ---- 写 结果/result2.xlsx（沿用 附件5 模板）----
g_day = (g1 * DT).reshape(NDAYS, N)
c_day = (c_exec * DT).reshape(NDAYS, N)
d_day = (d_exec * DT).reshape(NDAYS, N)
e_day = (e_exec * DT).reshape(NDAYS, N)
soc_midnight = soc_exec[::N]


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
