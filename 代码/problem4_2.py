# -*- coding: utf-8 -*-
"""问题 4（对应问题 2）—— 波动电价下微网的日前计划购电量 ĝ 与储能调度。

============================================================================
一、与问题 2 的唯一差别：价格不再是常数
    问题 2 的题面说「每天的电价相同」，所以全程共用附件1 的一条 144 槽剖面。
    问题 4 的题面说「实际上，外网的电价也是实时波动的」，结算改用附件4 的
    365×144 逐日逐槽实际电价。**其余假设一字不改**（口径 A、γ=1 可交付储能计划、
    334 天计费窗口、SOC ∈ [1200, 10800]、日末回 6000、不售电、时间标签左移）。

二、两个价格向量（本文件的核心分工，不可混用）
    price_base = tile(附件1, 365)   附件1 是外网**公布**的分时电价（典型日剖面）
    price_real = 附件4.ravel()      附件4 是**实际结算**电价（逐日逐槽波动）

        计划层 LP 目标   → price_base（读法 B）/ price_real（读法 A）
        紧急购电系数     → 场景日的 price_real（读法 B）/ 今日的 price_real（读法 A）
        结算与写盘       → price_real  ← 唯一花钱的地方，永远是实际价

    实测依据（代码/诊断/_p4_price_diag.txt）：
      附件4 的逐槽跨日均值剖面与附件1 基准剖面最大绝对差 5.151e-05 元，
      即附件1 就是「典型日分时电价」形状，附件4 = 该形状 + 波动。
      方差分解：日内形状 84.6% / 日水平因子 9.2% / 日内残差 6.2%。

三、两种读法（本问的核心建模选择，两者都做）
    读法 B（主模型，P4_READING=B，缺省）：0:00 **不知道**当天电价，只有公布的
        分时电价剖面可依据；价格不确定性由**场景**承载。
    读法 A（下界 + 敏感性，P4_READING=A）：0:00 **已知**全天实际电价。
    两者之差 = 价格信息的价值。实测该差值很小（见四），所以「两种都做」成本很低，
    本身就是一条稳健性论据。

四、本问真正的机理：价格与缺口的**联合分布**，而非预报精度
    日水平因子 a_d 与日均净负荷 corr = 0.982（逐槽跨天 median 0.933）——
    「缺电的时候电价系统性更高」。这抬高盲窗里的有效紧急边际成本，
    理论上应把最优承诺分位从 c_u/(c_u+c_o) = 4p/5p = 0.80 推到 ≈0.836。
    ⚠ 但在问题 3 的三层模型里实测**没有出现这个上移**（τ 重扫最优点仍是 0.80，
      0.75–0.86 区间只差 0.05%）—— 原因见 problem4_3.py §Q4-3。本文件没有 τ 旋钮，
      该相关性由场景紧急系数 5·PR[pd_ω]/Kd 直接承载，故两处的实现方式不同。

    实现方式：场景 ω 同时携带**该历史日的净负荷与价格**——
        e_ω 的系数 = 5·PR[pd_ω] / Kd       （而不是常数 5·p_base / Kd）
    这一项就是读法 B 的全部经济内容。

    反面证据（为什么不去造更好的价格预报器）：单日储能套利 LP 实测，
    完美价格信息相对任何预报只值 1.04%；把价格 MAE 从 0.0968 砍到 0.0475
    只买回 0.02%；水平校正甚至略微有害（1.05%）。原因是日水平因子是**全天
    均匀平移**，而口径 A 的四项（p·ĝ、0.5p、1.5p、5p）都是同一个 p 的倍数，
    均匀平移不改变任何边际权衡 ⇒ 不改变最优策略，只改变账单。

五、购电功率上界（自加假设，必须声明）
    题面（附录1）只给了储能「最大充放电功率 5000 kW」，**没有给微网与外网的
    联络线容量**。缺省 G_MAX = 5000 kW 是自加的保守假设（与储能同量级），
    旋钮 P4_GMAX；按字面读法放开：P4_GMAX=inf。
    问题 2 的交付方案没有这个上界，实测峰值 10,325.3 kW、
    7,313/48,096 个槽越限、334 天无一幸免（分组 span6 口径，见问题 2 归档 §9）。

六、交付表的购电量里有 **16.39%** 既未供负载、也未进电池（必须声明）
    实测（口径同 diag_p4_audit.py）：年购电 22,444,159 kWh，而净需求 (L−P)Δt 仅
    17,939,189 kWh；扣掉充 5,435,306 / 放 4,402,435 / 紧急 206,893 之后仍差
    −3,678,992 kWh，即 16.39% 的购电量无处安放（买了但用不上）。
    **g 有 36.61% 的槽贴在 G_MAX=5,000 kW 上** —— 上界是紧的，它同时是防止过度购电的
    唯一闸门。这是 problem2.py 继承下来的口径性质（result2.xlsx 同源），不是问题 4 引入的。
    口径含义：口径 A 是照付不议（take-or-pay），承诺量全额付费、与实收无关，所以账单
    自洽；但"购电量"列 ≠ 可交付电量，论文必须写明。
    ⚠ 与问题 3 的对照（这点很重要）：problem4_3 在读法 B 下策略与 result3.xlsx **逐槽
      完全相同**（只换价不改量），而本文件**不是** —— 因为 §四 的场景紧急系数
      5·PR[pd_ω]/Kd 与 problem2.py 的常数 5·price_day/Kd 不同，价格联合分布真的改变了
      承诺量。两问的机理层次不同，论文不要混为一谈。

七、用法
    python 代码/problem4_2.py                     # 读法 B（主模型）→ result4-2.xlsx
    P4_READING=A python 代码/problem4_2.py        # 读法 A（下界）
    P4_GMAX=inf python 代码/problem4_2.py         # 放开购电功率上界（对照）
    P4_KPEERS=8 python 代码/problem4_2.py         # 扩大情景集（敏感性）
    P4_NOWRITE=1 python 代码/problem4_2.py        # 只算不写盘（跑对照时用）
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
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

READING = os.environ.get("P4_READING", "B").strip().upper()
assert READING in ("A", "B"), f"P4_READING 只能是 A 或 B，实得 {READING!r}"
G_MAX = float(os.environ.get("P4_GMAX", P_MAX))          # 购电功率上界（自加假设，见 docstring 五）
K_PEERS = int(os.environ.get("P4_KPEERS", 4))            # 情景集：同星期几的历史日
NOWRITE = os.environ.get("P4_NOWRITE", "") not in ("", "0")

price_day = pd.read_excel(os.path.join(BASE, "附件", "附件1.xlsx")).iloc[:, 1].to_numpy(float)
load = pd.read_excel(os.path.join(BASE, "附件", "附件2.xlsx"), sheet_name="小区负载") \
         .iloc[:, 1:1 + N].to_numpy(float)
pv = pd.read_excel(os.path.join(BASE, "附件", "附件2.xlsx"), sheet_name="光伏发电实际功率") \
       .iloc[:, 1:1 + N].to_numpy(float)
PR = pd.read_excel(os.path.join(BASE, "附件", "附件4.xlsx")) \
       .iloc[:, 1:1 + N].to_numpy(float)
assert PR.shape == (NDAYS, N), f"附件4 形状应为 (365, 144)，实得 {PR.shape}"

# 回归自检旋钮：P4_PRICE_SRC=att1 把实际价退回附件1 的常数剖面。此时
# 本文件（配 P4_READING=A P4_GMAX=inf）必须**逐槽复现** 结果/result2.xlsx。
if os.environ.get("P4_PRICE_SRC", "att4").strip().lower() == "att1":
    PR = np.tile(price_day, (NDAYS, 1))
    print("[回归自检] P4_PRICE_SRC=att1：实际价已退回附件1 常数剖面")

# PSCALE 是价格整体缩放旋钮，用于论文敏感性一节（文献 3 规范：±30%、5% 步长）。
# 它加在**实际结算价向量 PR 上**，而不是只加在 price_real 上 —— 因为紧急系数走的是
# scen_price() → PR[...]，两条路必须同步缩放。只缩放 PR 而不缩放 price_base，是为了
# 让「读法 B 下 0:00 价格未知」这一结构在扰动中保持不变。
PSCALE = float(os.environ.get("P4_PSCALE", 1.0))
PR = PR * PSCALE

# 两个价格向量，分工见 docstring 二
price_base = np.tile(price_day, NDAYS)      # 公布的分时电价剖面（全天同一条）
price_real = PR.ravel()                      # 实际结算电价（逐日逐槽）

# 计划层目标用的价格：读法 B 用公布剖面，读法 A 用实际价（0:00 已知）
pr_plan = price_real if READING == "A" else price_base

win = np.zeros(T, bool); win[REPORT * N:] = True
L = load.ravel(); P = pv.ravel()

# 情景集口径 = problem2.py 定稿（低需求日分组 {Fri,Sat}，回看 6 天），
# 不是本文件早先的「同星期几 K=4」。理由见 文档/问题4_求解归档.md。
# ⚠ span=6 不是随手取的：它恰好是**不触发 sc_idx 退化分支的最短窗口**。
#   低需求日每周只有 2 天，回看 s 天只能捞到 ≈2s/7 个同组日；s=6 时周五/周六各捞到
#   1 个，s≤5 时窗口（周日…周四）里一个同组日都没有 ⟹ 退化成 [d] 自身、用当天实际
#   负荷冒充情景天，计费窗口内会有 47 天前视作弊。已核验：span=6 在计费窗口内
#   退化天数为 0。P2 实测在 s≥6 上总费单调递增，故可行最优即 6。
GRP_SPAN = int(os.environ.get("P42_GSPAN", 6))
GRP_TRAIN = int(os.environ.get("P42_GTRAIN", REPORT))


def low_demand_dows(train_days):
    """从 train_days 推断「低需求日」：日均净负荷最低的两个星期几。只喂暖机期，无前视。"""
    nl = (load - pv).sum(axis=1)
    dow = np.array([d % 7 for d in range(NDAYS)])
    means = [nl[train_days][dow[train_days] == k].mean() for k in range(7)]
    order = np.argsort(means)
    return (int(order[0]), int(order[1]))


GRP_DOWS = low_demand_dows(np.arange(0, GRP_TRAIN))
_gm = np.array([(d % 7) in GRP_DOWS for d in range(NDAYS)])
peers = [[t for t in range(max(0, d - GRP_SPAN), d) if _gm[t] == _gm[d]] for d in range(NDAYS)]
base_e = np.zeros(NDAYS, dtype=np.int64)
_c = 0
for d in range(NDAYS):
    base_e[d] = _c
    _c += max(1, len(peers[d])) * N          # 场景数下限取 1（前 4 周退化为当日点预报）
E_total = _c


def sc_idx(d):
    """day d 的情景天列表；无同组历史时退化为 [d] 本身（单情景）。

    注意退化分支 sc_idx(dd)=[dd] 会让该日的紧急系数用到当日实际价（轻微前视）。
    分组 span=6 下已核验：计费窗口（d ≥ REPORT=31）内退化天数为 **0**，
    退化只出现在热身期 d < 6，不影响 334 天结算。换更短的 span 会打破这个性质。
    """
    return peers[d] if peers[d] else [d]


def scen_price(dd, pd_):
    """场景紧急购电系数里用的价格向量。

    读法 B：用该情景历史日的实际价 —— 场景同时携带净负荷与价格，联合分布由此进入。
    读法 A：今日实际价在 0:00 已知，紧急价也就已知，与情景无关。
    """
    return PR[dd] if READING == "A" else PR[pd_]


def honor_cost(g, d):
    """闭式诚实费用（用**实际**结算价 price_real）：e 只依赖 (ĝ, d̂)，与 SOC 无关。
    返回 (总费, 计划费, 紧急费, 紧急 kWh)。"""
    e = np.maximum(0.0, L - g - P - d)
    planned = (price_real * g * DT)[win].sum()
    emerg = (5 * price_real * e * DT)[win].sum()
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


def execute_soc_causal(g):
    """严格满足 SOC 的因果实际执行策略（负荷缺口优先）。与问题 2 逐字相同。

    每个 10 分钟时刻只使用当前实际 L/P、计划购电量 g_t 和当前 SOC：
      1. 先用储能覆盖负载缺口，放电受 SOC 下限和 5000 kW 限制；
      2. 剩余富余用于充电，充电受 SOC 上限和 5000 kW 限制；
      3. 仍缺的电才紧急购电。
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


def solve_deliver(gamma):
    """γ 覆盖率下的可交付计划 LP。gamma=1 → q = min_ω(P_ω − L_ω)（全情景可交付）。

    与问题 2 的差别只有两处（其余逐字相同）：
      · g 的上界是 G_MAX（问题 2 无上界）
      · 紧急系数逐场景取 scen_price(dd, pd_)（问题 2 取常数 price_day）
    """
    G0, D0, S0_, CM0, E0 = 0, T, 2 * T, 3 * T + 1, 4 * T + 1
    n_vars = E0 + E_total
    q = np.empty(T)
    for dd in range(NDAYS):
        p = sc_idx(dd)
        vals = pv[p] - load[p]                      # 必须用裸 (P−L)，见 problem2.py docstring 三
        q[dd * N:(dd + 1) * N] = np.quantile(vals, 1.0 - gamma, axis=0) \
            if len(p) > 1 else vals[0]

    c_obj = np.zeros(n_vars)
    c_obj[G0:G0 + T] = pr_plan
    for dd in range(NDAYS):
        p = sc_idx(dd); Kd = len(p)
        for w, pd_ in enumerate(p):
            sl = base_e[dd] + w * N
            c_obj[E0 + sl:E0 + sl + N] = 5.0 * scen_price(dd, pd_) / Kd   # ← 读法 B 的全部经济内容

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

    bounds = ([(0, G_MAX)] * T + [(0, P_MAX)] * T
              + [(SOC0, SOC0)] + [(SOC_MIN, SOC_MAX)] * (T - 1) + [(SOC0, SOC0)]
              + [(0, P_MAX)] * T + [(0, None)] * E_total)
    t0 = time.time()
    res = linprog(c_obj, A_eq=A_eq, b_eq=np.zeros(T), A_ub=A_ub, b_ub=np.concatenate(ub),
                  bounds=bounds, method="highs")
    assert res.success, res.message
    x = res.x
    return x[G0:G0 + T], x[D0:D0 + T], x[CM0:CM0 + T], x[S0_:S0_ + T + 1], time.time() - t0


def solve_full_year(N_hat, pr):
    """确定性全年 LP（完美预见下界 / 点预测共用骨架），返回 (g, c, d)。

    pr 是目标函数用的价格：哨兵必须传 price_real（否则不是真下界）。
    """
    G0, C0, D0, S0_, S_idx = 0, T, 2 * T, 3 * T, 4 * T
    n_vars = 5 * T + 1
    c_obj = np.zeros(n_vars); c_obj[G0:G0 + T] = pr
    t = np.arange(T)
    A_eq = sparse.coo_matrix(
        (np.concatenate([np.ones(T), -np.ones(T), np.ones(T), -np.ones(T),
                         np.ones(T), -np.ones(T), -ETA * DT * np.ones(T), (DT / ETA) * np.ones(T)]),
         (np.concatenate([t, t, t, t, T + t, T + t, T + t, T + t]),
          np.concatenate([G0 + t, C0 + t, D0 + t, S0_ + t,
                          S_idx + t + 1, S_idx + t, C0 + t, D0 + t]))),
        shape=(2 * T, n_vars)).tocsr()
    b_eq = np.concatenate([N_hat, np.zeros(T)])
    bounds = ([(0, G_MAX)] * T + [(0, P_MAX)] * T + [(0, P_MAX)] * T + [(0, None)] * T
              + [(SOC0, SOC0)] + [(SOC_MIN, SOC_MAX)] * (T - 1) + [(SOC0, SOC0)])
    res = linprog(c_obj, A_eq=A_eq, b_eq=b_eq, bounds=bounds, method="highs")
    assert res.success, res.message
    x = res.x
    return x[G0:G0 + T], x[C0:C0 + T], x[D0:D0 + T]


# ============================ 主流程 ============================
print("=" * 100)
print(f"问题 4（对应问题 2）：波动电价下的可交付储能计划   读法 {READING}"
      f"  G_MAX={G_MAX:,.0f} kW  K_PEERS={K_PEERS}")
print("=" * 100)
print(f"  均价：公布剖面 {price_day.mean():.4f} 元/kWh ｜ 实际 {PR.mean():.4f} 元/kWh"
      f"（算数均值 {PR.mean() / price_day.mean() - 1:+.2%}）")
_w = (PR * (load - pv)).sum() / (load - pv).sum()
_wb = (price_day * (load - pv)).sum() / (load - pv).sum()
print(f"  净负荷加权均价：公布剖面 {_wb:.4f} ｜ 实际 {_w:.4f}（{_w / _wb - 1:+.2%}）"
      f"  ← 实际电价在用电多的时段更贵")

# ---- 哨兵：完美预见下界（任何低于它的结果都是 bug）----
# 必须用 price_real 最小化，否则不是真下界
g_pf, c_pf, d_pf = solve_full_year(L - P, price_real)
sent = honor_cost(g_pf, d_pf)
print("-" * 100)
print(f"{'完美预见下界(哨兵)':<24}{sent[1]:>14,.0f}{sent[2]:>14,.0f}"
      f"{sent[3]:>16,.0f}{sent[0]:>16,.0f}")
print(f"  哨兵购电功率峰值 {g_pf.max():,.1f} kW（上界 {G_MAX:,.0f}）")

# ---- 参照：点预测（负荷同星期几 + 光伏近 7 天）----
L_hat = np.empty_like(load)
for d in range(NDAYS):
    idx = peers[d]
    L_hat[d] = load[idx].mean(axis=0) if idx else load.mean(axis=0)
P_hat = np.empty_like(pv)
for d in range(NDAYS):
    lo = max(0, d - 7)
    P_hat[d] = pv[lo:d].mean(axis=0) if lo < d else pv.mean(axis=0)
g_pt, c_pt, d_pt = solve_full_year((L_hat - P_hat).ravel(), pr_plan)
c_pt_exec, d_pt_exec, e_pt_exec, soc_pt_exec = execute_soc_causal(g_pt)
pt = honor_cost(g_pt, d_pt_exec)

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
print(f"  点预测计划（同执行层）   {pt[1]:>14,.0f}{pt[2]:>14,.0f}{pt[3]:>16,.0f}{pt[0]:>16,.0f}")
print(f"{'  └ 实际SOC范围':<24}[{soc_pt_exec.min():,.1f}, {soc_pt_exec.max():,.1f}] kWh")
print(f"  哨兵：完美预见下界 {sent[0]:,.0f} 元 —— 任何低于它的结果都是 bug")
_r = honor_cost(best[2], best[3])[0]
assert _r >= sent[0] - 1e-6, \
    f"总费 {_r:,.0f} 低于完美预见下界 {sent[0]:,.0f} —— 模型被放松了，检查 bounds/约束"

# ---- 交付：γ=1（唯一可引用的一档）----
g1, d1, cm1, soc1 = solve_deliver(1.0)[:4]
c_exec, d_exec, e_exec, soc_exec = execute_soc_causal(g1)
r1 = honor_cost(g1, d_exec)
assert np.allclose(e_exec, np.maximum(0.0, L - g1 - P - d_exec), atol=1e-8)
assert c_exec.min() >= -1e-9 and c_exec.max() <= P_MAX + 1e-6
assert d_exec.min() >= -1e-9 and d_exec.max() <= P_MAX + 1e-6
assert soc_exec.min() >= SOC_MIN - 1e-6 and soc_exec.max() <= SOC_MAX + 1e-6
assert c_exec.max() <= P_MAX + 1e-6
# 口径 A 推论：违约费 ≡ 0 —— 实际购电 g 只在 g > ĝ 时有超额费，g < ĝ 时超购部分无退款
print()
print("=" * 100)
print(f"规划层 γ=1：计划购电 {r1[1]:,.0f} 元")
print(f"实际执行：紧急 {r1[2]:,.0f} 元 ({r1[3]:,.0f} kWh)  总 {r1[0]:,.0f} 元")
print(f"实际 SOC：首 {soc_exec[0]:,.1f}  末 {soc_exec[-1]:,.1f}  "
      f"范围 [{soc_exec.min():,.1f}, {soc_exec.max():,.1f}] kWh")
print(f"  哨兵下界 {sent[0]:,.0f} 元 ｜ 高出 {(r1[0] / sent[0] - 1) * 100:.1f}%")
print(f"  点预测   {pt[0]:,.0f} 元 ｜ γ=1 比它 {'省' if r1[0] < pt[0] else '贵'} "
      f"{abs(pt[0] - r1[0]):,.0f} 元")
_gpeak = np.maximum(g1, 0.0).max()
print(f"  购电功率峰值 {_gpeak:,.1f} kW ｜ 越限槽数 "
      f"{int((g1 > G_MAX + 1e-6).sum()):,} / {T:,}"
      f"（上界 {G_MAX:,.0f} kW）")
print("=" * 100)

# ---- 写 结果/result4-2.xlsx（沿用 附件5 模板）----
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


report_days = range(REPORT, NDAYS)          # 334 天计费窗口 = 2025-02-01 .. 2025-12-31
blocks = [("0:00-4:00", 0, 24), ("4:00-8:00", 24, 48), ("8:00-12:00", 48, 72),
          ("12:00-16:00", 72, 96), ("16:00-20:00", 96, 120), ("20:00-24:00", 120, 144)]

# 写盘自检：表内合计必须与 run 结算一致（沿用问题 3 的做法）
_tot = 0.0
for di in report_days:
    _tot += float((PR[di] * g_day[di]).sum() + (5 * PR[di] * e_day[di]).sum())
assert abs(_tot - r1[0]) < 1.0, f"写盘费用 {_tot:,.2f} 与结算 {r1[0]:,.2f} 不一致 —— 窗口/价格口径错位"

if NOWRITE:
    print("\nP4_NOWRITE=1：跳过写盘。")
else:
    template = os.path.join(BASE, "附件", "附件5", "result4-2.xlsx")
    # P4_OUT 可把交付文件写到别处：敏感性扫描时用它避免覆盖 result4-2.xlsx
    out_path = os.environ.get("P4_OUT") or os.path.join(BASE, "结果", "result4-2.xlsx")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    wb = openpyxl.load_workbook(template)

    # 「计划购电量」：144 个计划购电量（循环左移 10 分钟）+ 全天购电量 + 全天购电费
    ws_p = wb["计划购电量"]
    for j, di in enumerate(report_days):
        row = j + 2
        for k in range(N):
            ws_p.cell(row=row, column=2 + k).value = round(float(g_day[di][(k + 1) % N]), 4)
        ws_p.cell(row=row, column=2 + N).value = round(float(g_day[di].sum()), 4)
        # 口径 A 全额：p·ĝ + 5p·e，这里的 p 是**实际结算价** PR[di]
        ws_p.cell(row=row, column=3 + N).value = round(float((PR[di] * g_day[di]).sum()
                                                          + (5 * PR[di] * e_day[di]).sum()), 2)

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
