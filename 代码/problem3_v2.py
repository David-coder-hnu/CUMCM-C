# -*- coding: utf-8 -*-
"""
问题 3 —— 严格按题面场景重解（problem3_v2）

题面口径（逐句对应）：
  计划购电量 ĝ、调整购电量 g（0:00 计划，6/12/18 各调整一次；0:00-6:00 无预报发布、不可调整）
  总购电费用 = 计划购电费用 + 紧急购电费用 + 调整购电量的相关费用
     计划购电费用   : p · min(g, ĝ)          （按计划价结算的那部分电量）
     违约费         : 0.5p · (ĝ − g)⁺        （计划高于调整的部分，违约电价 50%）
     超额费         : 1.5p · (g − ĝ)⁺        （调整高于计划的部分，电价 150%）
     紧急购电费     : 5p · e                 （微网供电低于负载，5 倍价）
  ⇒ 合计 = p·g + 0.5p·|g − ĝ| + 5p·e

紧急购电口径（严格按题面「微网提供的电能不可低于小区负载，如果低于负载，
需向外网紧急购电」）：微网提供的电能 = 购电量 + 光伏 + 储能放电，故
      e = max(0, L − g − P − d)
注意 e 中**不含充电量 c** —— 充电是微网内部的负荷，不属于"向小区提供的电能"。
但充电必须有能源，于是储能只能吃"提供完负载之后的富余"：
      c ≤ max(0, P + g + d − L)   ⇔   c − g − d ≤ P − L
⚠ 这两条必须成对出现：若只把 e 换成上式而仍让充电"凭空进行"（不占能源），
LP 会发现"免费充电"漏洞——充电不花能源、放电却能省购电费，费用会跌破完美预见下界。

与旧版 problem3.py 的差别（旧版的问题）：
  1) 0:00 计划直接用均值预报，**没有任何对冲**；
  2) solve_stage 里没有紧急购电变量（等式 g+d-c-slack = L-P），LP 认为预报精确，
     残差 100% 裸露在 5 倍价上 —— 这是紧急购电量反而比问题 2 高的根因。

本版（两阶段随机规划 + 滚动时域 MPC 执行）：
  §计划层（求解阶段）——与问题 2 共用同一套流程，差别只在问题 3 多 6/12/18 三个调整点：
    · 一阶段决策：0:00 承诺的购电量 ĝ 与计划 SOC 路径 S（S 是"取平"式的软路径变量）；
    · 二阶段追索：逐情景 ω 的 c_ω / d_ω / s_ω / e_ω，情景集 = 同星期几前 K_PEERS 周的实际净需求残差；
    · 目标 = 计划购电费 + 违约/超额费 + 期望紧急购电费，e_ω 严格按题面口径 max(0, L−g−P−d)。
    · 前 7 天没有"同星期几"历史可抽 ⇒ build_scenarios 退化为【当日 0:00 点预报】单情景，
      否则这 7 天没有二阶段约束、ĝ 会被设为 0，SOC 被凭空抽干。
  §执行层（仿真阶段）——滚动时域 MPC（solve_mpc），问题 2/3 共用：
    每 MPC_RES 槽重解一个长度 MPC_H 的 LP，末端 SOC 软约束对齐计划路径 soc_hat，
    只执行当前槽并按实际富余/实际 SOC 双向限幅。
  §消融开关（环境变量）：
    EXEC_NAIVE=1  退回"照抄计划 + 限幅"的朴素执行（不调用 solve_mpc）
    MPC_H / MPC_K / MPC_RES / MPC_LAM  控制时域、残差情景数、重解间隔、末端 SOC 罚
    NO_ADJ=1      关闭 6/12/18 调整 ⇒ 本脚本退化为问题 2 的模型
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

# Windows 下 stdout 被重定向到文件/管道时默认走 GBK，打印 ĝ(U+011D) 这类字符会抛
# UnicodeEncodeError 并把整个脚本打断在最后一段汇总里（前面的求解其实已经算完）。
# 统一改 UTF-8，保证 `python 代码/problem3_v2.py > log.txt` 也能跑到底。
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

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

# 报童临界分位（可用环境变量扫描）
Q_BLIND = float(os.environ.get("Q_BLIND", 0.80))        # 0:00-6:00：缺电只能吃 5 倍紧急
Q_ADJ = float(os.environ.get("Q_ADJ", 0.74))            # 有调整通道（数值扫描最优）
K_SCEN = int(os.environ.get("K_SCEN", 20))  # 日内调整 LP 的残差场景数（同星期几最近 K 周）
                                            # 定稿用留出法选定 K=20；旧默认 4 已被弃用
                                            # （K=4 时结果 15,212,547 元，作废）

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ---------------- 数据 ----------------
df1 = pd.read_excel(os.path.join(BASE, "附件", "附件1.xlsx"))
price_day = df1.iloc[:, 1].to_numpy(float)
dfL = pd.read_excel(os.path.join(BASE, "附件", "附件2.xlsx"), sheet_name="小区负载")
dfP = pd.read_excel(os.path.join(BASE, "附件", "附件2.xlsx"), sheet_name="光伏发电实际功率")
load = dfL.iloc[:, 1:1 + N].to_numpy(float)
pv = dfP.iloc[:, 1:1 + N].to_numpy(float)
fc3 = pd.read_excel(os.path.join(BASE, "附件", "附件3.xlsx"), header=None) \
        .iloc[1:, 2:].to_numpy(float).reshape(NDAYS, 4, 24)

price = np.tile(price_day, NDAYS)
# 统计窗口 [WIN0, WIN1)（天）。默认 2/1–12/31；留出法验证时用 WIN0/WIN1 切分。
WIN0 = int(os.environ.get("WIN0", REPORT))
WIN1 = int(os.environ.get("WIN1", NDAYS))
win = np.zeros(T, dtype=bool); win[WIN0 * N:WIN1 * N] = True

mean_load = load.mean(axis=0)
L_base = np.empty_like(load)
for d in range(NDAYS):
    idx = [d - 7 * k for k in range(1, K_PEERS + 1) if d - 7 * k >= 0]
    L_base[d] = load[idx].mean(axis=0) if idx else mean_load

# 附件3 逐小时 → 10min 线性插值
W = np.zeros((N, 25))
for k in range(N):
    t = (k + 1) / 6.0
    lo = int(np.floor(t)); hi = min(int(np.ceil(t)), 24)
    if lo == hi:
        W[k, lo] = 1.0
    else:
        W[k, lo] = 1.0 - (t - lo); W[k, hi] = t - lo


def pv_fc(d, s_idx, s_hour):
    """day d、第 s_idx 档发布(s_hour=0/6/12/18) → 全天 144 个 10min 光伏预报"""
    H = np.zeros(25)
    if s_hour > 0:
        H[s_hour] = pv[d, 6 * s_hour]
    for h in range(s_hour + 1, 25):
        H[h] = fc3[d, s_idx, h - s_hour - 1]
    return H @ W.T


S_HOUR = [0, 6, 12, 18]
S_IDX = [0, 36, 72, 108]
P_hat = np.stack([[pv_fc(d, s, S_HOUR[s]) for s in range(4)] for d in range(NDAYS)])  # (365,4,144)
F_hat = L_base[:, None, :] - P_hat                                                    # 预报净需求

# ---------------- 残差经验分布：actual − 各自档位预报（净需求口径） ----------------
actual_net = load - pv
resid = actual_net[:, None, :] - F_hat            # (365,4,144)
# 每档只在其覆盖的时段有效
COVER = [(0, 36), (36, 72), (72, 108), (108, 144)]
Qtab = np.zeros((4, N))
for s, (a, b) in enumerate(COVER):
    Qtab[s, a:b] = np.quantile(resid[:, s, a:b], Q_ADJ, axis=0)
Qtab[0, 0:36] = np.quantile(resid[:, 0, 0:36], Q_BLIND, axis=0)   # 0:00-6:00 盲窗


# ---------------- 全年 0:00 计划 LP（带对冲的净需求） ----------------
def solve_annual(N_hat):
    G0, C0, D0, S0, S_idx = 0, T, 2 * T, 3 * T, 4 * T
    n_vars = 5 * T + 1
    c_obj = np.zeros(n_vars); c_obj[G0:G0 + T] = price
    t = np.arange(T)
    rows = np.concatenate([t, t, t, t, T + t, T + t, T + t, T + t])
    cols = np.concatenate([G0 + t, C0 + t, D0 + t, S0 + t,
                           S_idx + t + 1, S_idx + t, C0 + t, D0 + t])
    dat = np.concatenate([np.ones(T), -np.ones(T), np.ones(T), -np.ones(T),
                          np.ones(T), -np.ones(T), -ETA * DT * np.ones(T), (DT / ETA) * np.ones(T)])
    A_eq = sparse.coo_matrix((dat, (rows, cols)), shape=(2 * T, n_vars)).tocsr()
    b_eq = np.concatenate([N_hat, np.zeros(T)])
    bounds = ([(0, None)] * T + [(0, P_MAX)] * T + [(0, P_MAX)] * T + [(0, None)] * T
              + [(SOC0, SOC0)] + [(SOC_MIN, SOC_MAX)] * (T - 1) + [(SOC0, SOC0)])
    res = linprog(c_obj, A_eq=A_eq, b_eq=b_eq, bounds=bounds, method="highs")
    assert res.success, res.message
    x = res.x
    return x[G0:G0 + T], x[C0:C0 + T], x[D0:D0 + T], x[S_idx:S_idx + T + 1]


# ---------------- 0:00 计划：两阶段随机规划（与问题 2 同一框架） ----------------
# 一阶段（here-and-now，一天一份）：计划购电 ĝ、计划放电 d̂、SOC 递推；
# 二阶段（recourse，逐场景）：充电 c̄_ω 只能吃该场景的富余、紧急购电 e_ω 只补负载缺口。
#   (i)  c̄_ω − ĝ − d̂ ≤ P_ω − L_ω = −N_ω      (ii) −ĝ − d̂ − e_ω ≤ −N_ω
#   SOC 递推按场景平均：S_{t+1} − S_t − ηΔt·Σ_ω c̄_ω/K_d + (Δt/η)·d̂ = 0
# 场景集 Ω_d = 与当天同星期几的最近 K_PEERS 周历史。CENTER 决定"围绕谁展开"：
#   CENTER=hist → 直接用这些历史天的实际净需求（0:00 只有历史，= 问题 2 的信息集）
#   CENTER=fc3  → 围绕附件 3 的 0:00 档预报展开，残差取同一预报方法的历史误差
# 取 CENTER=hist 时本 SP 与问题 2 的 SP 同构同解，故 ĝ 与问题 2 完全一致；问题 3 的
# 增量全部来自 6/12/18 三次调整 ⇒ 结构上保证问题 3 不劣于问题 2。
def build_scenarios(center):
    nets = []
    for d in range(NDAYS):
        ps = [d - 7 * k for k in range(1, K_PEERS + 1) if d - 7 * k >= 0]
        if not ps:
            # 前 7 天没有"同星期几"的历史可抽。旧版这里让该天【不设场景】，结果 SP 在那
            # 7 天里没有任何二阶段约束，而目标里只有 p·ĝ —— 于是 ĝ 被设成 0，这 7 天全靠
            # 电池顶负载、SOC 从 6000 一路抽到 1200。第 8 天起 SP 仍按"S 起点=6000"排
            # 计划（S 在那 7 天被"取平"约束钉在 6000），执行层却从 1200 起跑，永远追不上，
            # 于是出现"用 5 倍紧急电充电"的假象。改为退化成【当日 0:00 点预报】单情景：
            # 该天有了二阶段约束，ĝ 就要覆盖当日净需求，SOC 不再凭空被抽干。
            nets.append(F_hat[d, 0, :][None, :])
        elif center == "fc3":
            nets.append(F_hat[d, 0, :][None, :] + resid[ps, 0, :])
        else:
            nets.append(actual_net[ps])
    base, cnt = [], 0                       # 由 nets 反推偏移/规模，避免与 nets 失配
    for d in range(NDAYS):
        base.append(cnt); cnt += len(nets[d]) * N
    return base, nets, cnt


def solve_annual_sp(center):
    """两阶段随机规划：一阶段定【计划购电 ĝ 与计划 SOC 路径 S】，二阶段逐情景定
    【充电 c_ω、放电 d_ω、情景 SOC s_ω、紧急购电 e_ω】。

    为什么 SOC 必须逐情景（而不是用"期望充电 E[c̄]"推一条 SOC 路径）：
      充电只能用【该情景真正的富余】。若 SOC 按 E[c̄] 递推，计划就会认为"平均意义上
      充得进去"，于是排出日后也放得出的放电计划；而实际执行时富余一旦偏小，充电被
      削减 → SOC 掉得比计划低 → 放电也放不出来 → 缺口的电只能 5 倍价紧急买。实测该
      口径下紧急购电 111 万 kWh（占计划充电 14%），费用被系统性低估约 490 万元。
      把 c、d、s 都放进二阶段，等于让"电池的实时操作"随真实富余自适应，这才是物理上
      站得住的模型；K 增大只会让期望更准，不会像"取最坏情景"那样越抽越紧。
    一阶段只留 ĝ 与 S：ĝ 是真正的承诺量（问题 2 按它付费），S 是给运行人员看的计划水位。

    约束：s_{t+1} = s_t + ηΔt·c_t − (Δt/η)·d_t          （逐情景）
          s_ω[0] = S_{d·N}，s_ω[N] = S_{(d+1)·N}         （情景首尾锚在一阶段水位上）
          c_t − ĝ_t − d_t ≤ P_ω − L_ω = −N_ω             （充电只能吃富余）
          −ĝ_t − d_t − e_t ≤ −N_ω                        （紧急只补负载缺口）
    目标：Σ p·ĝ + Σ_ω (5p/K_d)·e_ω
    """
    base, nets, E_total = build_scenarios(center)
    G0, S_idx = 0, T                       # 一阶段：ĝ (T)、S (T+1)
    BLK = 4 * N + 1                        # 情景块：c(N) d(N) s(N+1) e(N)
    scens, off = [], T + (T + 1)
    for d in range(NDAYS):
        for w in range(len(nets[d])):
            scens.append((d, w, off)); off += BLK
    n_vars = off
    n_eq = E_total + 2 * len(scens) + T
    print(f"[0:00 计划·SP] 情景 {len(scens):,}，变量 {n_vars:,}，"
          f"约束 {n_eq + 2 * E_total:,}（CENTER={center}）")

    c_obj = np.zeros(n_vars)
    c_obj[G0:G0 + T] = price
    for d, w, o in scens:
        c_obj[o + 3 * N:o + 4 * N] = 5.0 * price_day / len(nets[d])

    # ---- 等式：逐情景 SOC 递推（N 行）+ 情景首尾锚定（2 行） ----
    t = np.arange(N)
    er, ec, ed = [], [], []
    row = 0
    for d, w, o in scens:
        r = row + t
        er += [r, r, r, r]
        ec += [o + 2 * N + t + 1, o + 2 * N + t, o + t, o + N + t]
        ed += [np.ones(N), -np.ones(N), -ETA * DT * np.ones(N), (DT / ETA) * np.ones(N)]
        row += N
        er += [row, row, row + 1, row + 1]
        ec += [o + 2 * N, S_idx + d * N, o + 3 * N, S_idx + (d + 1) * N]
        ed += [1.0, -1.0, 1.0, -1.0]
        row += 2
    # ---- S = 各情景 SOC 的期望（消除简并）----
    # S 原本只出现在情景首尾两条锚定约束里，日内是纯自由变量、不进目标，
    # 求解器会把它钉在下界 1200 —— 于是"计划 SOC 路径"名不副实：用 ĝ/ĉ/d̂ 重放
    # SOC 递推与 S 对不上（实测差 4,800 kWh）。补上 S_t = (1/K_d)Σ_ω s_ω,t 之后
    # S 既是真正的期望轨迹，也才能给执行层当跟踪目标。
    # ⚠ 行号必须用顺序计数器 row，不能用 S_idx + td ——后者会落进情景 SOC 递推
    #   行的区间 [0, E_total)，把两组方程互相覆盖（scipy 的 COO→CSR 会就地累加）。
    for d in range(NDAYS):
        Kd = len(nets[d])
        td = d * N + t + 1                      # S 的 T 个内部点（S_0 由边界钉为 SOC0）
        rr = row + t
        if Kd == 0:                             # 无场景的历史日：S 取平，保证路径连续
            er += [rr, rr]; ec += [S_idx + td, S_idx + td - 1]
            ed += [np.ones(N), -np.ones(N)]
        else:
            er += [rr] * (Kd + 1)
            ec += [S_idx + td] + [o + 2 * N + t + 1 for dd, w, o in scens if dd == d]
            ed += [np.ones(N)] + [-np.ones(N) / Kd] * Kd
        row += N
    assert row == n_eq
    A_eq = sparse.coo_matrix((np.concatenate([np.atleast_1d(v) for v in ed]),
                              (np.concatenate([np.atleast_1d(v) for v in er]),
                               np.concatenate([np.atleast_1d(v) for v in ec]))),
                             shape=(row, n_vars)).tocsr()

    # ---- 不等式：(i) 充电只能吃富余  (ii) 紧急只补负载缺口 ----
    nz = 6 * E_total
    ub_row = np.empty(nz, dtype=np.int64); ub_col = np.empty(nz, dtype=np.int64)
    ub_dat = np.empty(nz); ub_b = np.empty(2 * E_total)
    p = urow = 0
    for d, w, o in scens:
        td = d * N + t
        rhs = -nets[d][w]                       # = P_ω − L_ω
        r1 = urow + t; r2 = urow + N + t; urow += 2 * N
        ub_row[p:p+N] = r1; ub_col[p:p+N] = o + t;          ub_dat[p:p+N] = +1.0; p += N
        ub_row[p:p+N] = r1; ub_col[p:p+N] = G0 + td;        ub_dat[p:p+N] = -1.0; p += N
        ub_row[p:p+N] = r1; ub_col[p:p+N] = o + N + t;      ub_dat[p:p+N] = -1.0; p += N
        ub_b[r1] = rhs
        ub_row[p:p+N] = r2; ub_col[p:p+N] = G0 + td;        ub_dat[p:p+N] = -1.0; p += N
        ub_row[p:p+N] = r2; ub_col[p:p+N] = o + N + t;      ub_dat[p:p+N] = -1.0; p += N
        ub_row[p:p+N] = r2; ub_col[p:p+N] = o + 3 * N + t;  ub_dat[p:p+N] = -1.0; p += N
        ub_b[r2] = rhs
    A_ub = sparse.coo_matrix((ub_dat, (ub_row, ub_col)),
                             shape=(2 * E_total, n_vars)).tocsr()

    lo = [0.0] * T + [SOC0] + [SOC_MIN] * (T - 1) + [SOC0]
    hi = [None] * T + [SOC0] + [SOC_MAX] * (T - 1) + [SOC0]
    for d, w, o in scens:
        lo += [0.0] * N + [0.0] * N + [SOC_MIN] * (N + 1) + [0.0] * N
        hi += [P_MAX] * N + [P_MAX] * N + [SOC_MAX] * (N + 1) + [None] * N

    res = linprog(c_obj, A_eq=A_eq, b_eq=np.zeros(row), A_ub=A_ub, b_ub=ub_b,
                  bounds=list(zip(lo, hi)), method="highs")
    assert res.success, res.message
    x = res.x
    g = x[G0:G0 + T]; soc = x[S_idx:S_idx + T + 1]
    c = np.zeros(T); d = np.zeros(T)        # 计划充/放 = 各情景的期望（交给执行层）
    for dd, w, o in scens:
        sl = dd * N + t
        c[sl] += x[o + t] / len(nets[dd])
        d[sl] += x[o + N + t] / len(nets[dd])
    return g, c, d, soc


# ---------------- 0:00 计划（净需求预报 + 对冲分位） ----------------
# 每个时段用"覆盖它的最后一次调整机会"那一档的残差分位数作为对冲量
HEDGE = np.concatenate([Qtab[0, 0:36], Qtab[1, 36:72], Qtab[2, 72:108], Qtab[3, 108:144]])
if os.environ.get("UNIF_H"):          # 诊断：改用统一正偏置 H(kW) 冲（对照 p3_stoch.py 的口径）
    HEDGE = np.full(N, float(os.environ["UNIF_H"]))
if os.environ.get("NO_HEDGE"):        # 诊断：关掉对冲，隔离其影响
    HEDGE = np.zeros(N)
NO_ADJ = bool(os.environ.get("NO_ADJ"))   # 诊断：关掉 6/12/18 调整通道（退化为"只用 0:00 预报")
if NO_ADJ:
    HEDGE = np.quantile(resid[:, 0, :], float(os.environ.get("Q_ALL", 0.89)), axis=0)
if os.environ.get("PLAN_R0"):             # 变体：计划只按 0:00 档残差对冲（更宽），靠日内下修回收
    HEDGE = np.quantile(resid[:, 0, :], Q_ADJ, axis=0)
if os.environ.get("HEDGE_NPY"):           # 逐时段最优对冲：由 diag_hedge_fixpoint.py 迭代产生
    # 依据报童一阶条件：min ĝ  ⇒  P(N_t − d_t > ĝ_t) = 1/5，故最优对冲是"电池放电后
    # 残余缺口"的 80 分位，而非净需求的 80 分位。该向量只能靠仿真做不动点迭代得到。
    HEDGE = np.load(os.environ["HEDGE_NPY"])
    assert HEDGE.shape == (N,), f"HEDGE 形状应为 ({N},)，实得 {HEDGE.shape}"
N_plan = F_hat[:, 0, :] + HEDGE[None, :]

PLAN = os.environ.get("PLAN", "sp")     # sp = 两阶段随机规划（定稿）；lp = 旧确定性 LP + 对冲
CENTER = os.environ.get("CENTER", "hist")
t0 = time.time()
if PLAN == "lp":
    g_hat, c_hat, d_hat, soc_hat = solve_annual(N_plan.ravel())
    print(f"[0:00 计划·LP] 带对冲确定性 LP 完成，{time.time() - t0:.1f}s")
else:
    g_hat, c_hat, d_hat, soc_hat = solve_annual_sp(CENTER)
    print(f"[0:00 计划·SP] 求解完成，{time.time() - t0:.1f}s")
soc_mid = soc_hat[::N]

# 诊断：把 0:00 计划 ĝ 换成别处已有的方案（用于分离"计划选得好不好"与"日内调整行不行"）。
# 已知关系：问题 3 相对问题 2 多了 6/12/18 三个调整机会，偏差罚则也更软
# （0.5p / 1.5p < 5p），故在同一 ⟨ĝ, 执行层⟩ 下，问题 3 的最优值必 ≤ 问题 2。
#   实测：问题 2 = 本脚本 NO_ADJ=1 → 18,300,549（朴素）/ 17,149,812（MPC）
#         问题 3 = 15,715,709（MPC）—— 方向一致，调整通道价值 1,434,103 元。
# ⚠ 旧注释在此写过一条"定理"：ĝ 取问题 2 的方案且不调整时总费应恰等于 13,832,465 元。
#   该"定理"是错的：13,832,465 低于同一 ĝ 下的完美预见储能下界（15,347,211 元），
#   不存在能实现它的因果执行策略；实测同 ĝ 不调整为 18,300,549 / 17,149,812。
if os.environ.get("GHAT_FROM"):
    _src = os.environ["GHAT_FROM"]
    _ws = openpyxl.load_workbook(os.path.join(BASE, "结果", _src))["计划购电量"]
    _g = np.empty(T)
    for _d in range(NDAYS - REPORT):        # 表内第 1 个数据行 = 第 REPORT 天（2/1）
        for _k in range(N):
            _g[(REPORT + _d) * N + (_k + 1) % N] = \
                _ws.cell(row=_d + 2, column=2 + _k).value or 0.0
    g_hat = _g * 6.0                      # 表内是每槽 kWh，LP 用 kW
    print(f"[诊断] 0:00 计划取自 {_src}：Σĝ = {g_hat[win].sum() * DT:,.0f} kWh")
print(f"[0:00 计划] 带对冲 LP 完成，{time.time() - t0:.1f}s，"
      f"计划购电量 {g_hat[win].sum() * DT:,.0f} kWh")
print(f"  诊断：窗口内负载 {load.ravel()[win].sum() * DT:,.0f} kWh，"
      f"光伏 {pv.ravel()[win].sum() * DT:,.0f} kWh，"
      f"净需求 {F_hat[:, 0, :].ravel()[win].sum() * DT:,.0f} kWh")
if PLAN == "lp":
    print(f"  诊断：对冲量合计 {HEDGE[None, :].repeat(NDAYS, 0).ravel()[win].sum() * DT:,.0f} kWh")
else:
    # ⚠ PLAN="sp" 时 HEDGE 根本不参与求解（它只喂给 PLAN="lp" 的 solve_annual），
    #   所以这里不能再叫"对冲量"——否则会被误读成"SP 计划里含了多少对冲"。
    #   改报 SP 自己的计划 SOC 路径统计，那才是该计划层真正产出的东西。
    print(f"  诊断：SP 计划 SOC 路径 [{soc_hat.min():.0f}, {soc_hat.max():.0f}] kWh，"
          f"日末锚点 soc_mid [{soc_mid.min():.0f}, {soc_mid.max():.0f}] kWh"
          f"（HEDGE 在本路径下未被使用）")


# ---------------- 日内调整 LP（含 5 倍紧急购电的场景对冲） ----------------
def solve_stage_v2(d, s_idx, s_hour, soc_start, soc_end, ghat_rem, price_rem, F_rem, R):
    """R: (K,n) 残差场景。目标 = p·g + 0.5p·(a+ + a-) + 5p/K·Σ_ω e_ω"""
    n = N - s_idx
    K = R.shape[0]
    G0, C0, D0 = 0, n, 2 * n
    AP, AN = 3 * n, 4 * n
    S_idx = 5 * n
    E0 = S_idx + n + 1
    n_vars = E0 + K * n

    c_obj = np.zeros(n_vars)
    c_obj[G0:G0 + n] = price_rem * DT
    _padj = 0.0 if os.environ.get("ADJ_FREE") else 0.5   # 诊断：关掉调整 LP 目标里的偏差罚
    c_obj[AP:AP + n] = _padj * price_rem * DT
    c_obj[AN:AN + n] = _padj * price_rem * DT
    for w in range(K):
        c_obj[E0 + w * n:E0 + (w + 1) * n] = 5.0 * price_rem * DT / K

    i = np.arange(n)
    # 功率平衡用不等式（e 只在缺电时为正，等式会强制 e 恒为正）：
    #   g + d - c >= F + resid_ω - e_ω   ⇔   -g - d + c - e <= -(F+resid)
    # (1) SOC 递推
    rows2 = np.concatenate([i, i, i, i])
    cols2 = np.concatenate([S_idx + i + 1, S_idx + i, C0 + i, D0 + i])
    dat2 = np.concatenate([np.ones(n), -np.ones(n), -ETA * DT * np.ones(n), (DT / ETA) * np.ones(n)])
    # (2) g - aP + aN = ĝ
    rows3 = np.concatenate([n + i, n + i, n + i])
    cols3 = np.concatenate([G0 + i, AP + i, AN + i])
    dat3 = np.concatenate([np.ones(n), -np.ones(n), np.ones(n)])

    rows = np.concatenate([rows2, rows3]); cols = np.concatenate([cols2, cols3])
    data = np.concatenate([dat2, dat3])
    A_eq = sparse.coo_matrix((data, (rows, cols)), shape=(2 * n, n_vars)).tocsr()
    b_eq = np.concatenate([np.zeros(n), ghat_rem])

    # 不等式（严格按题面口径；F_rem + R_ω = 情景 ω 的净需求 L_ω − P_ω）：
    #   (i)  充电只能用富余：c − g − d ≤ P̄ − L̄ = −(F_rem + mean_ω R_ω)
    #        充电是能量搬运，按"期望富余"做计划；执行期再按实际富余削减（见 execute()）。
    #        这里刻意不逐情景取 min —— 否则充电上限会随场景数 K 增大而收紧（K=20 时
    #        最差场景把充电卡死，总费反而比 K=4 高 160 万），充电上限不应依赖抽样数。
    #   (ii) 紧急只补负载缺口：−g − d − e_ω ≤ −(F_rem + R_ω)  ⇔  g + d + e_ω ≥ L_ω − P_ω
    #        e_ω 逐情景，防止 LP 利用抽样场景把 g 压低去赌残差为负、被 5 倍紧急购电反噬。
    #        （原 MEAN_FLOOR 行 g+d−c ≥ F_rem 与 (i) 同形，已被 (i) 包含，不再单列。）
    ur, uc, ud, ubb = [], [], [], []
    ones, neg1 = np.ones(n), -np.ones(n)
    ur += [i, i, i]                                          # (i)
    uc += [C0 + i, G0 + i, D0 + i]
    ud += [ones, neg1, neg1]
    ubb.append(-(F_rem + R.mean(axis=0)))
    for w in range(K):
        rhs_w = -(F_rem + R[w])
        r2 = n + w * n + i                                  # (ii)
        ur += [r2, r2, r2]
        uc += [G0 + i, D0 + i, E0 + w * n + i]
        ud += [neg1, neg1, neg1]
        ubb.append(rhs_w)
    nrows = (K + 1) * n
    A_ub = sparse.coo_matrix((np.concatenate(ud), (np.concatenate(ur), np.concatenate(uc))),
                             shape=(nrows, n_vars)).tocsr()
    ub = np.concatenate(ubb)

    lo = ([0.0] * n + [0.0] * n + [0.0] * n + [0.0] * n + [0.0] * n
          + [soc_start, SOC_MIN] + [SOC_MIN] * (n - 2) + [soc_end] + [0.0] * (K * n))
    hi = ([None] * n + [P_MAX] * n + [P_MAX] * n + [None] * n + [None] * n
          + [soc_start, SOC_MAX] + [SOC_MAX] * (n - 2) + [soc_end] + [None] * (K * n))
    res = linprog(c_obj, A_eq=A_eq, b_eq=b_eq, A_ub=A_ub, b_ub=ub,
                  bounds=list(zip(lo, hi)), method="highs")
    assert res.success, res.message
    x = res.x
    return x[G0:G0 + n], x[C0:C0 + n], x[D0:D0 + n], x[S_idx:S_idx + n + 1]


# ---------------- 执行层：滚动时域 MPC（问题 2/3 共用同一套） ----------------
# 计划层（0:00 随机规划 + 6/12/18 调整）给出的是"事前最优"，但它建立在预报/情景上；
# 实际负荷与光伏一旦揭晓，就必须允许储能按【已实现信息】重新调度——这就是执行层。
# 这里是标准的滚动时域优化（MPC）：每个 Δt 用"当日已实现的实测值 + 当前可用档位的预报"
# 重解一个小 LP，只执行当前槽的动作，下一槽再解一次（因此是因果的，不使用任何未来数据）。
EXEC_NAIVE = bool(os.environ.get("EXEC_NAIVE"))   # 消融：回到"照抄计划 + 限幅"的朴素执行
# EXEC_SMART：朴素执行 +「吃尽一切实际富余充电」。见 execute_naive 内的说明。
EXEC_SMART = int(os.environ.get("EXEC_SMART", 0))
MPC_H = int(os.environ.get("MPC_H", 36))          # 预测时域（槽）；36 槽 = 6 h
MPC_K = int(os.environ.get("MPC_K", 1))           # 执行层的残差场景数（见下：默认 1 = 点预报）
MPC_LAM = float(os.environ.get("MPC_LAM", 5.0))   # 末端 SOC 松弛罚（元/kWh，近硬约束）
MPC_RES = int(os.environ.get("MPC_RES", 1))       # 重解间隔（槽）；1 = 与 Δt 同步


def solve_mpc(day, t, soc, g_rem, level, r):
    """滚动时域执行 LP。返回当前槽的 (c, d) 建议。

    信息集 = 当日 0..t 的实测负荷/光伏 + 档位 level 的预报 + 同伴残差场景（全部是"此刻可得"的）。
    约束（def = 时点赤字，见下）：
      C1  def_t + d_t ≥ L̂_t − P̂_t − g_t                    （赤字定义，def ≥ 0）
      C2  c_t − d_t − def_t ≤ g_t + P̂_t − L̂_t              （充电只吃富余）
      C3  −d_t − e_ω,t ≤ P̂_t + R_ω,t − L̂_t − g_t           （负载必须被供上，逐情景）
      C4  s_n + sl ≥ soc_hat[τ0+n]                          （末端 SOC 目标，软约束）
    三处都是踩过坑才写对的，别再"化简"：
      · C2 若写成 c − d ≤ g + P̂ − L̂（去掉 def），取 c=0 就变成 d ≥ L̂ − P̂ − g ——
        【强制电池把每一个预期赤字都放出来】，36 槽连续 4398 kW 强制放电直接把 SOC 放穿，
        LP 不可行。物理上"充电只吃富余"是 c ≤ max(0, g+P+d−L)，max(0,·) 非线性；
        引入 def_t = max(0, L̂−P̂−g−d)（由 C1 线性刻画）后 C2 右端恒 ≥ 0，既不强制放电，
        又保证【紧急电不能拿来充电】（否则 LP 会买 5 倍电价电充进去凑 C4）。
      · C3 只约束【供电】，不出现 c：充电是耗能不是供能。
      · C4 的方向必须是 ≥（早先误写成 s_n − sl ≤ target，成了上界，等于没约束，
        电池一早就放光，紧急购电翻 4 倍）。把紧急充电堵死后 λ 才能取大，
        现在 MPC_LAM 默认 5.0 元/kWh，接近硬约束。
    为什么执行层默认 K=1（点预报）而不是像计划层那样带情景对冲：
      总线上 c ≤ g + P + d − L 允许"把放出来的电再充回去"，于是【放电腾空间去对冲
      坏情景、再充回来凑末端目标】在不罚 c/d 的目标下是免费的。6 h 时域看不到回收损失
      （损失表现为 g 被浪费，之后才变成紧急购电），实测这会让 0-6 点凭空充放电各几百万
      kWh、紧急购电从 0.97 百万 kWh 涨到 4.4 百万，总费 18.3 → 38.8 百万。
      对冲本来就是计划层（0:00 两阶段 SP + 6/12/18 情景调整）的职责，
      执行层用最新点预报做确定性滚动优化即可；MPC_K > 1 只作为消融保留。
    """
    n = min(MPC_H, N - t)
    K = MPC_K
    C0, D0, S0 = 0, n, 2 * n
    E0 = 3 * n + 1
    SL = E0 + K * n
    n_vars = SL + 1

    p = price_day[t:t + n]
    c_obj = np.zeros(n_vars)
    for w in range(K):
        c_obj[E0 + w * n:E0 + (w + 1) * n] = 5.0 * p * DT / K
    c_obj[SL] = MPC_LAM
    if K == 1:                       # 打破"充放同量"的简并（代价 1e-4 元/kWh，可忽略）
        c_obj[C0:C0 + n] += 1e-4 * p * DT
        c_obj[D0:D0 + n] += 1e-4 * p * DT

    i = np.arange(n)
    A_eq = sparse.coo_matrix(
        (np.concatenate([np.ones(n), -np.ones(n), -ETA * DT * np.ones(n), (DT / ETA) * np.ones(n)]),
         (np.concatenate([i, i, i, i]),
          np.concatenate([S0 + i + 1, S0 + i, C0 + i, D0 + i]))),
        shape=(n, n_vars)).tocsr()

    Lf = r * L_base[day, t:t + n]
    Pf = P_hat[day, level, t:t + n]
    peers = [day - 7 * k for k in range(1, K) if day - 7 * k >= 0]
    R = np.zeros((K, n))                                       # 情景 0 ≡ 点预报（R=0）
    for w, q in enumerate(peers, start=1):
        R[w] = actual_net[q, t:t + n] - (L_base[q, t:t + n] - P_hat[q, level, t:t + n])
    for w in range(len(peers) + 1, K):                         # 同伴不足时复制已有情景
        R[w] = R[max(1, len(peers))]
    # 情景 0 必须是点预报（R≡0）。早先版本在 K==1 时取"最近一个同伴"的残差，
    # 那不是一个情景而是一个【任意的坏情景】：C3 会以它为据强迫 e>0，LP 于是拼命放电
    # 去压这笔 5 倍费，再靠 C2 从富余里充回来——0-6 点凭空充放各数百万 kWh。

    ones, neg1 = np.ones(n), -np.ones(n)
    surp = Pf + g_rem[:n] - Lf                                 # 时点富余（可为负）
    ur, uc, ud, ub = [], [], [], []
    ur += [i, i, i]                                            # C2 充电只吃富余（行 0..n-1）
    uc += [C0 + i, D0 + i, E0 + i]
    ud += [ones, neg1, neg1]
    ub.append(surp)
    for w in range(K):                                         # C3 负载必须被供上（逐情景）
        r2 = (w + 1) * n + i                                   # d + e_ω ≥ (L̂+R_ω) − P̂ − g
        ur += [r2, r2]                                         #  ⇒ −d − e_ω ≤ surp + R_ω
        uc += [D0 + i, E0 + w * n + i]
        ud += [neg1, neg1]
        ub.append(surp + R[w])
    _r4 = (K + 1) * n                                          # C4 末端 SOC 目标（单行两元）
    ur.append(np.array([_r4, _r4]))
    uc.append(np.array([S0 + n, SL]))
    ud.append(np.array([-1.0, -1.0]))
    ub.append(np.array([-soc_hat[day * N + t + n]]))

    A_ub = sparse.coo_matrix((np.concatenate(ud), (np.concatenate(ur), np.concatenate(uc))),
                             shape=((K + 1) * n + 1, n_vars)).tocsr()
    lo = ([0.0] * n + [0.0] * n + [soc] + [SOC_MIN] * n
          + [0.0] * (K * n) + [0.0])
    hi = ([P_MAX] * n + [P_MAX] * n + [soc] + [SOC_MAX] * n
          + [None] * (K * n) + [None])
    res = linprog(c_obj, A_eq=A_eq, b_eq=np.zeros(n), A_ub=A_ub, b_ub=np.concatenate(ub),
                  bounds=list(zip(lo, hi)), method="highs")
    if os.environ.get("MPC_DBG"):
        _dd, _tt = int(os.environ["MPC_DBG"]), int(os.environ.get("MPC_DBG_T", 0))
        if day == _dd and t == _tt:
            x = res.x
            print(f"  [MPC {day}@{t}] n={n} soc={soc:.0f} 目标={soc_hat[day * N + t + n]:.0f} "
                  f"Σc={x[C0:C0 + n].sum() * DT:,.0f} Σd={x[D0:D0 + n].sum() * DT:,.0f} "
                  f"末SOC={x[S0 + n]:.0f} sl={x[SL]:.0f} obj={res.fun:,.1f} "
                  f"Σe={x[E0:E0 + n].sum() * DT:,.0f} kWh")
            _viol = (A_ub @ x - np.concatenate(ub)).max()
            print(f"      约束最大违反 {_viol:.3e}（应 ≤ 0）  "
                  f"surp 前 8 槽 {np.round(surp[:8], 1)}  c 前 8 槽 {np.round(x[C0:C0 + 8], 1)}  "
                  f"d 前 8 槽 {np.round(x[D0:D0 + 8], 1)}  "
                  f"e0 前 8 槽 {np.round(x[E0:E0 + 8], 1)}")
    if not res.success:
        print(f"[MPC 不可行] day={day} t={t} n={n} soc={soc:.1f} lev={level} r={r:.4f} "
              f"target={soc_hat[day * N + t + n]:.0f} "
              f"R=[{R.min():.1f},{R.max():.1f}] Lf=[{Lf.min():.1f},{Lf.max():.1f}] "
              f"Pf=[{Pf.min():.1f},{Pf.max():.1f}] g=[{g_rem[:n].min():.1f},{g_rem[:n].max():.1f}] "
              f"NaN={int(np.isnan(Lf).any() + np.isnan(Pf).any() + np.isnan(R).any())} "
              f"bub=[{np.concatenate(ub).min():.1f},{np.concatenate(ub).max():.1f}]")
        raise SystemExit(1)
    return res.x[C0], res.x[D0]


# ---------------- 全年滚动 ----------------
g_fin = np.empty_like(g_hat); c_fin = np.empty_like(c_hat); d_fin = np.empty_like(d_hat)
c_plan = c_hat.copy(); d_plan = d_hat.copy()   # 调整后、执行限幅前的计划（用于诊断兑现率）
soc_act = np.empty(NDAYS + 1); soc_act[0] = SOC0


def execute_naive(day, g_day, c_day, d_day, a, b, soc):
    """执行 [a,b)：按实际负荷/光伏推进 SOC，并对充放电双向限幅（等效 BMS）。

    计划（0:00 年计划 / 6/12/18 各次调整）是按预报或情景做的，实际富余可能更小：
      · 充电只能吃"提供完负载后的实际富余"（题面：微网供电不可低于负载）；
      · 放电不能击穿 SOC 下限 1200，充电不能顶穿上限 10800。
    限幅只可能让 SOC 落在 [SOC_MIN, SOC_MAX] 内，故 SOC 边界由构造保证；
    限幅量回写 c_day/d_day，使交付文件与执行轨迹自洽（少充/少放都会反映到
    紧急购电量上：少放 = 供电缺口变大 = 5 倍价紧急购电）。
    """
    kc = kd = 0.0
    for t in range(a, b):
        d_max = max(0.0, (soc - SOC_MIN) * ETA / DT)          # 放电受 SOC 下限约束
        # 备选 BMS 规则（默认关闭）：只要还有电就先顶住当前缺口。
        # ⚠ 实测【更差】，已由消融实验否定，勿默认开启：
        #   新计划 18,302,027 → 18,748,641 元；问题 2 计划 18,779,159 → 19,122,846 元。
        #   原因是该规则近视——把电提前放掉，晚高峰（电价最高、5 倍罚最重）反而没电，
        #   而缺口该由"放电 vs 紧急购电"按 5p·Δt 的机会成本全局排序，不是逐槽顶。
        if os.environ.get("BMS_DEFICIT"):
            d_need = max(0.0, load[day, t] - pv[day, t] - g_day[t])
            if d_need > d_day[t]:
                d_day[t] = d_need
        if d_day[t] > d_max:
            kd += d_day[t] - d_max
            d_day[t] = d_max
        if EXEC_SMART >= 3:
            # 变体 3：放电严格只放到【刚好盖住缺口】，不再照抄 d̂。
            # 为什么应当占优：g 已在 0:00 承诺死，放多放少都不改变 p·g；e = max(0, L−P−g−d)
            # 只要 d = need 就归零。故 d̂ > need 的那部分放电【零收益】，只会把电放掉、
            # 再靠富余充回来，白丢一个来回的 η²（储能往返效率 0.81）。
            # 反过来说，不把那部分电放掉，它就留在电池里等更贵的缺口 —— 这正是 (C) 完美
            # 预见下界比我们便宜 32.4 万的原因（它买的紧急电量更多、但都买在便宜时段）。
            need = max(0.0, load[day, t] - pv[day, t] - g_day[t])
            d_day[t] = min(need, d_max)
        c_max = max(0.0, (SOC_MAX - soc) / (ETA * DT))        # 充电受 SOC 上限约束
        surp = pv[day, t] + g_day[t] + d_day[t] - load[day, t]
        c_lim = min(max(0.0, surp), c_max)
        if EXEC_SMART:
            # 执行层应当【吃尽一切实际富余】，而不是只充计划里的 ĉ。
            # 理由：富余不能上网卖（题面），不充就是白白弃掉，边际成本 = 0；而任何一次
            # 放电削减最后都变成 5p 的紧急购电（5p 最高 6.98 元/kWh，是套利价差 ~0.98 的 7 倍）。
            # 计划 ĉ 是"预测富余"下的建议值，实际富余更大时多充的部分零成本，且直接减少
            # 后续 SOC 触底造成的放电削减（实测同一 ĝ 下削减 118,510 kWh）。
            # ⚠ 这条只能在【执行层】用：计划层的 ĉ 若也这么定，会让 LP 认为"想充多少都充得上"，
            #   从而排出日后放不出来的放电计划（这正是 solve_annual_sp 注释里记录的那个坑）。
            c_day[t] = c_lim
            if EXEC_SMART == 2 and d_day[t] < max(0.0, load[day, t] - pv[day, t] - g_day[t]):
                # 变体 2：缺口时用电池顶（d = max(d̂, need)），对照。
                d_day[t] = min(max(0.0, load[day, t] - pv[day, t] - g_day[t]), d_max)
                c_day[t] = min(max(0.0, pv[day, t] + g_day[t] + d_day[t] - load[day, t]), c_max)
        elif c_day[t] > c_lim:
            kc += c_day[t] - c_lim
            c_day[t] = c_lim
        soc += (ETA * c_day[t] - d_day[t] / ETA) * DT
    return soc, kc, kd


curt_c = curt_d = 0.0   # 占位：真正的限幅量在滚动结束后由 c_plan/d_plan 与 c_fin/d_fin 直接算
n_mpc = 0
t0 = time.time()
for d in range(NDAYS):
    Ld, Pd = load[d], pv[d]
    g_day = g_hat[d * N:(d + 1) * N].copy()   # 已承诺的购电量（问题 3 会在 6/12/18 改）
    c_day = c_hat[d * N:(d + 1) * N].copy()   # 计划层建议（朴素执行照抄；MPC 只用于诊断）
    d_day = d_hat[d * N:(d + 1) * N].copy()
    c_plan[d * N:(d + 1) * N] = c_day
    d_plan[d * N:(d + 1) * N] = d_day
    adv_c = c_day.copy(); adv_d = d_day.copy()   # 执行层手上的动作建议
    soc = soc_act[d]              # 实际 SOC（被限幅后会偏离计划值）
    lev = 0                       # 当前预报档位：问题 2 恒为 0 档（只有 0:00 预报）
    for t in range(N):
        # ---- 计划层：6:00 / 12:00 / 18:00 各用最新预报改一次购电量（问题 3）----
        at_adj = (not NO_ADJ) and t in S_IDX[1:]
        if at_adj:
            s_lvl = S_IDX.index(t)
            r = Ld[:t].sum() / max(L_base[d, :t].sum(), 1e-9)
            F_rem = r * L_base[d, t:] - P_hat[d, s_lvl, t:]
            peers = [d - 7 * k for k in range(1, K_SCEN + 1) if d - 7 * k >= 0]
            R = np.stack([actual_net[q, t:] - (L_base[q, t:] - P_hat[q, s_lvl, t:]) for q in peers]) \
                if peers else np.zeros((1, N - t))
            g_r, c_r, d_r, _ = solve_stage_v2(d, t, S_HOUR[s_lvl], soc, soc_mid[d + 1],
                                              g_hat[d * N + t:(d + 1) * N], price_day[t:],
                                              F_rem, R)
            g_day[t:] = g_r
            adv_c[t:] = c_r; adv_d[t:] = d_r      # 调整 LP 的储能建议，供朴素执行/诊断用
            # ⚠ 右边界必须是当天末 (d+1)*N：c_r/d_r 只有 N−t 长。少了它就会被广播进
            #   "从今天到年底"的 52,524 个位置而报错。此前所有执行层对比都带 NO_ADJ=1，
            #   这个分支根本没跑过，故一直没暴露。
            c_plan[d * N + t:(d + 1) * N] = c_r
            d_plan[d * N + t:(d + 1) * N] = d_r
            lev = s_lvl
        # ---- 执行层：每 MPC_RES 槽重解一次滚动时域 LP（调整点强制重解）----
        # ⚠ 必须带 (not EXEC_NAIVE)：消融模式下若仍调 solve_mpc，adv_c/adv_d 会被 MPC 覆写，
        #   "朴素执行"实际跑的还是 MPC —— 这正是早先 EXEC_NAIVE=1 与 MPC_RES=1 逐位相同的原因。
        if (not EXEC_NAIVE) and (t % MPC_RES == 0 or at_adj):
            r = Ld[:t].sum() / max(L_base[d, :t].sum(), 1e-9) if t > 0 else 1.0
            ca, da = solve_mpc(d, t, soc, g_day[t:], lev, r)
            n = min(MPC_H, N - t)
            adv_c[t:t + n] = ca; adv_d[t:t + n] = da
            n_mpc += 1
        if os.environ.get("MPC_DBG2") and d == int(os.environ["MPC_DBG2"]) and t < 5:
            print(f"  [执行 {d}@{t}] adv_c={adv_c[t]:>7.0f} 计划ĉ={c_hat[d * N + t]:>7.0f} | "
                  f"adv_d={adv_d[t]:>7.0f} 计划d̂={d_hat[d * N + t]:>7.0f} | "
                  f"soc={soc:>6.0f} 实际富余={Pd[t] + g_day[t] - Ld[t]:>7.0f}")
        # ---- 只执行当前槽，并按"实际富余 / 实际 SOC"双向限幅 ----
        if EXEC_NAIVE or EXEC_SMART:
            soc, kc_, kd_ = execute_naive(d, g_day, adv_c, adv_d, t, t + 1, soc)
            curt_c += kc_; curt_d += kd_
            c_fin[d * N + t] = adv_c[t]; d_fin[d * N + t] = adv_d[t]
        else:
            d_u = min(adv_d[t], max(0.0, (soc - SOC_MIN) * ETA / DT))
            c_u = min(adv_c[t], max(0.0, (SOC_MAX - soc) / (ETA * DT)),
                      max(0.0, Pd[t] + g_day[t] + d_u - Ld[t]))
            c_fin[d * N + t] = c_u; d_fin[d * N + t] = d_u
            soc += (ETA * c_u - d_u / ETA) * DT
        g_fin[d * N + t] = g_day[t]
    soc_act[d + 1] = soc

print(f"[滚动调整] 完成，{time.time() - t0:.1f}s"
      f"（执行层 {'朴素限幅' if EXEC_NAIVE else f'MPC 滚动，{n_mpc:,} 次 LP，时域 {MPC_H} 槽 × {MPC_K} 情景'}）")
# 执行限幅量 = 调整后计划 − 实际执行（分母用调整后计划，才是"兑现率"的正确基准）
curt_c = ((c_plan - c_fin) * DT)[win].sum()
curt_d = ((d_plan - d_fin) * DT)[win].sum()
_cp = (c_plan * DT)[win].sum(); _dp = (d_plan * DT)[win].sum()
print(f"  执行期 SOC 范围 [{soc_act.min():.0f}, {soc_act.max():.0f}] kWh")
print(f"  充电兑现 {(c_fin * DT)[win].sum():,.0f}/{_cp:,.0f} kWh"
      f"（削减 {curt_c:,.0f}，{curt_c / max(_cp, 1e-9) * 100:.2f}%）；"
      f"放电兑现 {(d_fin * DT)[win].sum():,.0f}/{_dp:,.0f} kWh"
      f"（削减 {curt_d:,.0f}，{curt_d / max(_dp, 1e-9) * 100:.2f}%）")
print(f"  实际日末 SOC 与年计划锚点 soc_mid 的最大偏差 "
      f"{np.abs(soc_act[1:] - soc_mid[1:]).max():,.0f} kWh")

if os.environ.get("DIAG_DAY"):          # 诊断：逐槽对比"计划轨迹"与"执行轨迹"
    _dd = int(os.environ["DIAG_DAY"])
    _sl = slice(_dd * N, (_dd + 1) * N)
    _em = np.maximum(0.0, load.ravel() - g_fin - pv.ravel() - d_fin)
    print(f"\n[DIAG] 第 {_dd} 天（{L_base[_dd].sum():,.0f} 负载）"
          f" 计划充 {(c_hat[_sl]*DT).sum():,.0f} 实际充 {(c_fin[_sl]*DT).sum():,.0f}"
          f" | 计划放 {(d_hat[_sl]*DT).sum():,.0f} 实际放 {(d_fin[_sl]*DT).sum():,.0f}"
          f" | 紧急 {(_em[_sl]*DT).sum():,.0f} kWh")
    print(f"  {'t':>4}{'电价':>8}{'负荷':>9}{'光伏':>9}{'计划g':>9}"
          f"{'计划c':>8}{'实c':>8}{'计划d':>8}{'实d':>8}{'计划S':>9}{'实S':>9}{'富余':>9}{'紧急':>8}")
    _soc_a = [soc_act[_dd]]
    for _t in range(N):
        _soc_a.append(_soc_a[-1] + (ETA * c_fin[_dd * N + _t] - d_fin[_dd * N + _t] / ETA) * DT)
    for _t in range(N):
        _surp = pv[_dd, _t] + g_fin[_dd * N + _t] + d_fin[_dd * N + _t] - load[_dd, _t]
        if _t % 6 == 0 or _em[_dd * N + _t] > 1e-6:
            print(f"  {_t:>4}{price_day[_t]:>8.2f}{load[_dd,_t]:>9.0f}{pv[_dd,_t]:>9.0f}"
                  f"{g_fin[_dd*N+_t]:>9.0f}{c_hat[_dd*N+_t]:>8.0f}{c_fin[_dd*N+_t]:>8.0f}"
                  f"{d_hat[_dd*N+_t]:>8.0f}{d_fin[_dd*N+_t]:>8.0f}"
                  f"{soc_hat[_dd*N+_t+1]:>9.0f}{_soc_a[_t]:>9.0f}{_surp:>9.0f}"
                  f"{_em[_dd*N+_t]:>8.0f}")

# 计划 vs 执行（分 6h 时窗）：区分"日内调整改了多少"与"执行限幅削了多少"
_tod = np.tile(np.arange(N), NDAYS)
print(f"  [诊断] 分时窗 计划→执行（窗口内合计，kWh）：")
print(f"    {'时窗':>8}{'年计划充':>12}{'调整后充':>12}{'实际充':>12}"
      f"{'年计划放':>12}{'调整后放':>12}{'实际放':>12}")
for _a, _b in [(0, 36), (36, 72), (72, 108), (108, 144)]:
    _m = win & (_tod >= _a) & (_tod < _b)
    print(f"    {_a//6:>3}-{_b//6:<4}"
          f"{(c_hat * DT)[_m].sum():>12,.0f}{(c_plan * DT)[_m].sum():>12,.0f}"
          f"{(c_fin * DT)[_m].sum():>12,.0f}"
          f"{(d_hat * DT)[_m].sum():>12,.0f}{(d_plan * DT)[_m].sum():>12,.0f}"
          f"{(d_fin * DT)[_m].sum():>12,.0f}")

# ---------------- 结算（题面口径） ----------------
L = load.ravel(); P = pv.ravel()
emerg = np.maximum(0.0, L - g_fin - P - d_fin)   # 题面口径：只补负载缺口，不含充电量
plan_fee = (price * np.minimum(g_fin, g_hat) * DT)[win].sum()
breach = (0.5 * price * np.maximum(g_hat - g_fin, 0) * DT)[win].sum()
excess = (1.5 * price * np.maximum(g_fin - g_hat, 0) * DT)[win].sum()
em_fee = (5 * price * emerg * DT)[win].sum()
em_kwh = (emerg * DT)[win].sum()
total = plan_fee + breach + excess + em_fee

print("\n" + "=" * 78)
print("问题 3（严格按题面场景重解）—— 统计窗口 2/1–12/31")
print("=" * 78)
print(f"  计划购电费 p·min(g,ĝ)      {plan_fee:>16,.0f} 元")
print(f"  违约费   0.5p·(ĝ−g)+       {breach:>16,.0f} 元")
print(f"  超额费   1.5p·(g−ĝ)+       {excess:>16,.0f} 元")
print(f"  紧急购电费 5p·e            {em_fee:>16,.0f} 元   ({em_kwh:,.0f} kWh)")
print(f"  ------------------------------------------------")
print(f"  合计                       {total:>16,.0f} 元")
# 对照基准：每一条都必须写明【口径 + 来源】，避免再出现"拿一个不可实现的数当基准"。
# ⚠ 这里曾硬编码 13,832,465 元作为问题 2 的基准。该数低于同一 ĝ 下的完美预见储能下界
#   （15,347,211 元），故不存在能实现它的因果执行策略 —— 它是个假数，已删除。
#   问题 2 的正确定义就是"本脚本 NO_ADJ=1 + 同一执行层"，故基准改为实测值。
#   同 ĝ 不调整的实测：18,300,549（朴素执行） / 17,149,812（MPC 执行，本版采用）。
P2_REF = float(os.environ.get("P2_REF", 17_149_812))
_v = P2_REF - total
print(f"  对照：问题 2（本脚本 NO_ADJ=1 + MPC 执行）{P2_REF:>13,.0f} 元 → 问题 3 "
      f"{'省' if _v >= 0 else '多花'} {abs(_v):,.0f} 元 ({_v / P2_REF * 100:+.2f}%)"
      f"    ← 这才是 6/12/18 调整通道的价值")
print(f"  对照：旧 result3（旧 e 口径 + myopic，非本模型）15,681,438 元")
print(f"  对照：完美预见全年 LP（ĝ 可自由选，松下界）     12,229,461 元")
print(f"  对照：ĝ 固定、储能完美预见（不可实现的紧下界）14,613,824 元"
      f"　见 文档/问题2_独立复核_可交付性与追索模型.md")
tod = np.tile(np.arange(N), NDAYS)
print("  按 6h 时窗拆分：")
print(f"    {'时窗':>8} {'计划(kWh)':>13} {'净调整(kWh)':>13} {'上调':>11} {'下调':>11} "
      f"{'紧急(kWh)':>12} {'偏差费(元)':>12}")
for a, b in [(0, 36), (36, 72), (72, 108), (108, 144)]:
    m = win & (tod >= a) & (tod < b)
    print(f"    {a//6:>3}-{b//6:<4} {(g_hat * DT)[m].sum():>13,.0f} "
          f"{((g_fin - g_hat) * DT)[m].sum():>13,.0f} "
          f"{((np.maximum(g_fin - g_hat, 0)) * DT)[m].sum():>11,.0f} "
          f"{((np.maximum(g_hat - g_fin, 0)) * DT)[m].sum():>11,.0f} "
          f"{(emerg * DT)[m].sum():>12,.0f} "
          f"{(0.5 * price * np.maximum(g_hat - g_fin, 0) + 1.5 * price * np.maximum(g_fin - g_hat, 0))[m].sum() * DT:>12,.0f}")
_alt = (price * g_hat * DT)[win].sum() + breach + excess + em_fee
print(f"  [口径敏感性] 若改成「计划费按全额 ĝ 计」（= p·ĝ + 偏差费 + 紧急费）"
      f"同一轨迹为 {_alt:,.0f} 元；该口径下最优分位会下移（盲窗≈0.73、可调段≈0.25）")
print(f"  SOC 范围（年计划）[{soc_hat.min():.0f}, {soc_hat.max():.0f}]，"
      f"SOC_0={soc_hat[0]:.0f}，SOC_T={soc_hat[-1]:.0f}")
print(f"  SOC 范围（实际执行，日末）[{soc_act.min():.0f}, {soc_act.max():.0f}]，"
      f"越界天数 {int(((soc_act < SOC_MIN - 1e-6) | (soc_act > SOC_MAX + 1e-6)).sum())}")
print(f"  净调整量 {((g_fin - g_hat) * DT)[win].sum():,.0f} kWh；"
      f"计划量 {g_hat[win].sum() * DT:,.0f} kWh；实际购电 {(g_fin * DT)[win].sum():,.0f} kWh")

if os.environ.get("NO_SAVE"):        # 扫描时用：只出数字，不写文件
    if os.environ.get("DUMP_NPZ"):   # 诊断：导出计划与执行轨迹
        # 除计划 (g,c,d,soc) 外，一并导出【实际执行轨迹】与【逐槽紧急购电】：
        #   · 诊断脚本用 g/c/d/soc 做独立核验；
        #   · diag_hedge_fixpoint.py 用 e_fin 逐时段统计"缺口发生频率"，做报童不动点迭代。
        _e_fin = np.maximum(0.0, load.ravel() - g_fin - pv.ravel() - d_fin)
        np.savez(os.environ["DUMP_NPZ"], g=g_hat, c=c_hat, d=d_hat, soc=soc_hat,
                 g_fin=g_fin, c_fin=c_fin, d_fin=d_fin, e_fin=_e_fin)
        print(f"  [dump] 计划(g,c,d,soc) 与执行(g_fin,c_fin,d_fin,e_fin) "
              f"已写入 {os.environ['DUMP_NPZ']}")
    sys.exit(0)

# ---------------- 写 result3.xlsx ----------------
def fmt_time(m):
    m = int(m)
    return "24:00" if m >= 1440 else f"{m // 60:02d}:{m % 60:02d}"


def segments(e_kwh):
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


g_day_kwh = (g_fin * DT).reshape(NDAYS, N)
gh_day_kwh = (g_hat * DT).reshape(NDAYS, N)
c_day_kwh = (c_fin * DT).reshape(NDAYS, N)
d_day_kwh = (d_fin * DT).reshape(NDAYS, N)
e_day_kwh = (emerg * DT).reshape(NDAYS, N)
pr_day = price_day.repeat(NDAYS).reshape(NDAYS, N)[:, 0]

template = os.path.join(BASE, "附件", "附件5", "result3.xlsx")
out_path = os.path.join(BASE, "结果", "result3.xlsx")
os.makedirs(os.path.dirname(out_path), exist_ok=True)
wb = openpyxl.load_workbook(template)
report_days = range(REPORT, NDAYS)
blocks = [("0:00-4:00", 0, 24), ("4:00-8:00", 24, 48), ("8:00-12:00", 48, 72),
          ("12:00-16:00", 72, 96), ("16:00-20:00", 96, 120), ("20:00-24:00", 120, 144)]

ws_p = wb["计划购电量"]
for j, di in enumerate(report_days):
    row = j + 2
    for k in range(N):
        ws_p.cell(row=row, column=2 + k).value = round(float(gh_day_kwh[di][(k + 1) % N]), 4)
    ws_p.cell(row=row, column=2 + N).value = round(float(gh_day_kwh[di].sum()), 4)
    ws_p.cell(row=row, column=3 + N).value = round(float(
        (price_day * np.minimum(g_day_kwh[di], gh_day_kwh[di])).sum()
        + 0.5 * (price_day * np.maximum(gh_day_kwh[di] - g_day_kwh[di], 0)).sum()
        + 1.5 * (price_day * np.maximum(g_day_kwh[di] - gh_day_kwh[di], 0)).sum()
        + (5 * price_day * e_day_kwh[di]).sum()), 2)

ws_a = wb["调整购电量"]
for j, di in enumerate(report_days):
    row = j + 2
    for k in range(N):
        ws_a.cell(row=row, column=2 + k).value = round(float(g_day_kwh[di][(k + 1) % N]), 4)
    ws_a.cell(row=row, column=2 + N).value = round(float(g_day_kwh[di].sum()), 4)

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
        ws_c.cell(row=r, column=3).value = round(float(c_day_kwh[di][a:b].sum()), 4)
        ws_c.cell(row=r, column=4).value = round(float(d_day_kwh[di][a:b].sum()), 4)
    ws_c.cell(row=base, column=5).value = "0:00"
    ws_c.cell(row=base, column=6).value = round(float(soc_act[di]), 4)
    ws_c.cell(row=base + 1, column=5).value = "24:00"
    ws_c.cell(row=base + 1, column=6).value = round(float(soc_act[di + 1]), 4)

ws_e = wb["紧急购电量"]
ws_e.delete_rows(2, ws_e.max_row - 1)
r = 2
for j, di in enumerate(report_days):
    segs = segments(e_day_kwh[di])
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
print(f"\n已写入 {out_path}")
