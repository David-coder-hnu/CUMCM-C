# -*- coding: utf-8 -*-
"""
问题 3（**旧版 / legacy**）：0:00 计划 + 6:00/12:00/18:00 调整 + 双向调整费 + 紧急购电(5 倍价)。

⚠⚠ **本文件不是问题 3 的定稿，不要用它出数。** ⚠⚠
  * 定稿求解器是 `代码/problem3_v3.py`（口径 A），交付 `结果/result3.xlsx`。
  * 本文件的**计划层是在口径 B 下优化的**（`Q_FARSIGHT=0.75` 取自 B 的对称临界分位
    `1.5/(1.5+0.5)`），只有**结算与写盘已对齐口径 A**。所以它报出的数**不是**定稿的数，
    只是一个历史基线，用于对照归档。
  * **写盘路径已改为 `代码/诊断/_p3_legacy.xlsx`**（可用 `P3_LEGACY_OUT` 覆盖）。
    此前它直接写 `结果/result3.xlsx`，跑一次就会用口径 B 的数**静默覆盖 v3 的交付物**。

计费口径（口径 A，与 problem3_v3.py 一致）：
    总费 = 计划购电费用 + 紧急购电费用 + 调整购电量的相关费用
         = Σ p·ĝ·Δt + 0.5·Σ p·(ĝ−g)⁺·Δt + 1.5·Σ p·(g−ĝ)⁺·Δt + 5·Σ p·e·Δt
  即计划量**全额付费**（题面：其他时间段的购电费用均按计划购电量计算）；
  下调按 0.5p（违约）、上调按 1.5p（超额）。
  （此前本文件报的是 `p·g + 0.5p·|Δ|`，与口径 A 的代数和差 `Σp·(ĝ−g)⁺`，已修正。）

约定（与团队确认）：
  * 0:00 用附件3 的 0:00 光伏预报(逐小时→线性插值到 10min) + 负荷"同星期几4周" 制定计划。
  * 6/12/18 点用"更新预报 + 已发生实际负荷的比值修正"重排剩余时段（电池自由充放电，SOC 不越界）。
  * 调整购电量 = 最终购电 − 0:00 计划（带符号净差）。
  * 紧急购电 = 最终策略 vs 实际负荷/光伏 的缺口，5 倍价。
  * 储能沿用"全年能量中性"：SOC_0=SOC_T=6000，日内调整以 0:00 计划的 24:00 SOC 为锚。

两档初设（MODE）：
  * myopic    ：0:00 计划用均值点预测（不预知未来可调整）。
  * farsighted：0:00 计划用报童最优分位预测（前瞻不对称调整费）。

输出：代码/诊断/_p3_legacy.xlsx（计划购电量/调整购电量/充放电量/紧急购电量 4 表）。
"""
import os
import datetime as dt
import numpy as np
import pandas as pd
from scipy.optimize import linprog
from scipy import sparse
import openpyxl

# Windows 下 stdout 重定向到文件/管道时默认走 GBK，打印 ĝ(U+011D) 等字符会抛
# UnicodeEncodeError 并打断脚本（前面的求解其实已算完）。统一改 UTF-8。
import sys as _sys
for _s in (_sys.stdout, _sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

MODE = os.environ.get("P3_MODE", "myopic")   # "myopic" | "farsighted"
Q_FARSIGHT = 0.75          # 前瞻分位（**口径 B** 的对称临界分位 1.5/(1.5+0.5)）
# ⚠ 这是 B 的分位，不是 A 的。口径 A 下 0:00–6:00 块不可调整、只能吃 5p 紧急，
#   其临界比是 4p/(4p+p)=0.80（见 problem3_v3.py 的 TAU_B）。本文件**不改**这个值，
#   因为改了就变成另一个模型；它只作为口径 B 的历史基线保留。

DT = 1.0 / 6.0
ETA = 0.9
P_MAX = 5000.0
SOC_MIN = 1200.0
SOC_MAX = 10800.0
SOC0 = 6000.0
N = 144
NDAYS = 365
T = N * NDAYS
REPORT = 31                # 统计窗口 2/1–12/31
K_PEERS = 4                # 同星期几取最近 4 周

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ---------------- 读数据 ----------------
df1 = pd.read_excel(os.path.join(BASE, "附件", "附件1.xlsx"))
price_day = df1.iloc[:, 1].to_numpy(float)                     # (144,)
dfL = pd.read_excel(os.path.join(BASE, "附件", "附件2.xlsx"), sheet_name="小区负载")
dfP = pd.read_excel(os.path.join(BASE, "附件", "附件2.xlsx"), sheet_name="光伏发电实际功率")
load = dfL.iloc[:, 1:1 + N].to_numpy(float)                    # (365,144) 实际负荷
pv = dfP.iloc[:, 1:1 + N].to_numpy(float)                      # (365,144) 实际光伏
fc3 = pd.read_excel(os.path.join(BASE, "附件", "附件3.xlsx"), header=None) \
        .iloc[1:, 2:].to_numpy(float).reshape(NDAYS, 4, 24)    # (365,4,24) 光伏预报

price = np.tile(price_day, NDAYS)
mean_load = load.mean(axis=0)


# ---------------- 负荷基础预测：同星期几最近 4 周平均 ----------------
L_base = np.empty_like(load)
for d in range(NDAYS):
    idx = [d - 7 * k for k in range(1, K_PEERS + 1) if d - 7 * k >= 0]
    L_base[d] = load[idx].mean(axis=0) if idx else mean_load


# ---------------- 光伏预报：逐小时 → 10min 线性插值 ----------------
# 权重矩阵 W：(144, 25)，把 25 个整点值(H[0..24])插到 144 个 10min 区间
W = np.zeros((N, 25))
for k in range(N):
    t = (k + 1) / 6.0                 # 区间右端点小时
    lo = int(np.floor(t)); hi = min(int(np.ceil(t)), 24)
    if lo == hi:
        W[k, lo] = 1.0
    else:
        frac = t - lo
        W[k, lo] = 1.0 - frac
        W[k, hi] = frac


def pv_forecast_10min(d, s_idx, s_hour):
    """day d、发布索引 s_idx、发布时刻 s_hour(0/6/12/18)；返回该发布下全天 144 个 10min 光伏预报。
    区间 [s_hour,24) 用插值预报（s_hour 瞬时用实际），[0,s_hour) 未用。"""
    H = np.zeros(25)
    if s_hour > 0:
        H[s_hour] = pv[d, 6 * s_hour]                    # 当前瞬时实际
    for h in range(s_hour + 1, 25):
        H[h] = fc3[d, s_idx, h - s_hour - 1]             # lead = h - s_hour
    return H @ W.T                                       # (144,)


P_hat = np.stack([pv_forecast_10min(d, 0, 0) for d in range(NDAYS)])   # (365,144) 全年 0:00 光伏预报


# ---------------- 全年 0:00 计划（确定性 LP） ----------------
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


# ---------------- 日内调整：重排 [s_idx,144) 的 LP ----------------
def solve_stage(s_idx, soc_start, soc_end, P_rem, L_rem, ghat_rem, price_rem):
    n = N - s_idx
    G0, C0, D0, S0 = 0, n, 2 * n, 3 * n
    S_idx = 4 * n
    AP, AN = 5 * n + 1, 6 * n + 1
    n_vars = 7 * n + 1

    c_obj = np.zeros(n_vars)
    c_obj[G0:G0 + n] = price_rem * DT
    c_obj[AP:AP + n] = 0.5 * price_rem * DT
    c_obj[AN:AN + n] = 0.5 * price_rem * DT

    i = np.arange(n)
    rows1 = np.concatenate([i, i, i, i])
    cols1 = np.concatenate([G0 + i, D0 + i, C0 + i, S0 + i])
    dat1 = np.concatenate([np.ones(n), np.ones(n), -np.ones(n), -np.ones(n)])
    rows2 = np.concatenate([n + i, n + i, n + i, n + i])
    cols2 = np.concatenate([S_idx + i + 1, S_idx + i, C0 + i, D0 + i])
    dat2 = np.concatenate([np.ones(n), -np.ones(n), -ETA * DT * np.ones(n), (DT / ETA) * np.ones(n)])
    rows3 = np.concatenate([2 * n + i, 2 * n + i, 2 * n + i])
    cols3 = np.concatenate([G0 + i, AP + i, AN + i])
    dat3 = np.concatenate([np.ones(n), -np.ones(n), np.ones(n)])

    rows = np.concatenate([rows1, rows2, rows3])
    cols = np.concatenate([cols1, cols2, cols3])
    data = np.concatenate([dat1, dat2, dat3])
    A_eq = sparse.coo_matrix((data, (rows, cols)), shape=(3 * n, n_vars)).tocsr()
    b_eq = np.concatenate([L_rem - P_rem, np.zeros(n), ghat_rem])

    lo = ([0.0] * n + [0.0] * n + [0.0] * n + [0.0] * n
          + [soc_start, SOC_MIN] + [SOC_MIN] * (n - 2) + [soc_end]
          + [0.0] * n + [0.0] * n)
    hi = ([None] * n + [P_MAX] * n + [P_MAX] * n + [None] * n
          + [soc_start, SOC_MAX] + [SOC_MAX] * (n - 2) + [soc_end]
          + [None] * n + [None] * n)
    res = linprog(c_obj, A_eq=A_eq, b_eq=b_eq, bounds=list(zip(lo, hi)), method="highs")
    assert res.success, res.message
    x = res.x
    return x[G0:G0 + n], x[C0:C0 + n], x[D0:D0 + n], x[S_idx:S_idx + n + 1]


# ================= 两阶段随机规划（0:00 计划） =================
def solve_stochastic_plan():
    """两阶段随机 LP：min E_ω[ price·g_ω + 0.5·price·|g_ω−ĝ| + 5·price·e_ω ]。
    第一阶段 here-and-now：ĝ, ĉ, d̂, SOC（跨场景唯一）；
    第二阶段 recourse：每场景 ω 的最终购电 g_ω（可自由调整，等效"完美日内调整"）。
    场景集 = 同星期几最近 K_PEERS 周（与问题 2 同一信息集）。"""
    peers = [[d - 7 * k for k in range(1, K_PEERS + 1) if d - 7 * k >= 0] for d in range(NDAYS)]
    E_total = sum(len(ps) * N for ps in peers)
    G0, C0, D0, S_idx = 0, T, 2 * T, 3 * T          # 第一阶段
    G2 = 4 * T + 1                                   # 第二阶段 g_ω 起点
    AP = G2 + E_total
    AN = AP + E_total
    n_vars = AN + E_total
    print(f"[随机规划] 场景区间 {E_total:,}，变量 {n_vars:,}")

    base_e = np.zeros(NDAYS, dtype=np.int64)
    cnt = 0
    for d in range(NDAYS):
        base_e[d] = cnt
        cnt += len(peers[d]) * N
    assert cnt == E_total

    # 目标：g_ω -> price/K_d，a⁺/a⁻ -> 0.5·price/K_d（对场景求期望）
    c_obj = np.zeros(n_vars)
    for d in range(NDAYS):
        Kd = len(peers[d])
        if Kd == 0:
            continue
        for w in range(Kd):
            sl = slice(base_e[d] + w * N, base_e[d] + (w + 1) * N)
            c_obj[G2 + sl.start:G2 + sl.stop] = price_day / Kd
            c_obj[AP + sl.start:AP + sl.stop] = 0.5 * price_day / Kd
            c_obj[AN + sl.start:AN + sl.stop] = 0.5 * price_day / Kd

    # --- 等式① SOC 递推（T 行，4 非零） ---
    t = np.arange(T)
    eq_rows = np.tile(t, 4)
    eq_cols = np.concatenate([S_idx + t + 1, S_idx + t, C0 + t, D0 + t])
    eq_dat = np.concatenate([np.ones(T), -np.ones(T), -ETA * DT * np.ones(T), (DT / ETA) * np.ones(T)])
    A_eq = sparse.coo_matrix((eq_dat, (eq_rows, eq_cols)), shape=(T + E_total, n_vars)).tocsr()
    b_eq = np.zeros(T + E_total)

    # --- 等式② 调整分解：g_ω − ĝ − a⁺ + a⁻ = 0（E_total 行，4 非零） ---
    nz = 4 * E_total
    r2 = np.empty(nz, dtype=np.int64); c2 = np.empty(nz, dtype=np.int64); d2 = np.empty(nz)
    p = 0
    for d in range(NDAYS):
        for w in range(len(peers[d])):
            sl = slice(base_e[d] + w * N, base_e[d] + (w + 1) * N)
            rr = T + np.arange(sl.start, sl.stop)
            t_ = d * N + np.arange(N)
            r2[p:p + N] = rr; c2[p:p + N] = G2 + np.arange(sl.start, sl.stop); d2[p:p + N] = 1.0; p += N
            r2[p:p + N] = rr; c2[p:p + N] = G0 + t_; d2[p:p + N] = -1.0; p += N
            r2[p:p + N] = rr; c2[p:p + N] = AP + np.arange(sl.start, sl.stop); d2[p:p + N] = -1.0; p += N
            r2[p:p + N] = rr; c2[p:p + N] = AN + np.arange(sl.start, sl.stop); d2[p:p + N] = 1.0; p += N
    A_eq += sparse.coo_matrix((d2, (r2, c2)), shape=(T + E_total, n_vars)).tocsr()

    # --- 不等式③ 功率平衡：g_ω − ĉ + d̂ ≥ N_ω → −g_ω + ĉ − d̂ ≤ −N_ω（E_total 行，3 非零） ---
    # 场景净负荷 = 当天 0:00 预报净负荷 + 历史同星期几的"预报误差"（用附件3预报，而非原始历史实际）
    F_hat = L_base - P_hat                                   # 0:00 预报净负荷 (365,144)
    resid_peer = (load - pv) - F_hat                         # 历史实际 vs 其当天预报 的误差 (365,144)
    nz = 3 * E_total
    ru = np.empty(nz, dtype=np.int64); cu = np.empty(nz, dtype=np.int64); du = np.empty(nz)
    b_ub = np.empty(E_total)
    p = 0
    for d in range(NDAYS):
        for w, pd_ in enumerate(peers[d]):
            sl = slice(base_e[d] + w * N, base_e[d] + (w + 1) * N)
            rr = np.arange(sl.start, sl.stop)
            t_ = d * N + np.arange(N)
            ru[p:p + N] = rr; cu[p:p + N] = G2 + rr; du[p:p + N] = -1.0; p += N
            ru[p:p + N] = rr; cu[p:p + N] = C0 + t_; du[p:p + N] = 1.0; p += N
            ru[p:p + N] = rr; cu[p:p + N] = D0 + t_; du[p:p + N] = -1.0; p += N
            b_ub[sl] = -(F_hat[d] + resid_peer[pd_])          # -N_ω = -(预报 + 历史误差)
    A_ub = sparse.coo_matrix((du, (ru, cu)), shape=(E_total, n_vars)).tocsr()

    bounds = ([(0, None)] * T + [(0, P_MAX)] * T + [(0, P_MAX)] * T          # ĝ, ĉ, d̂
              + [(SOC0, SOC0)] + [(SOC_MIN, SOC_MAX)] * (T - 1) + [(SOC0, SOC0)]  # SOC
              + [(0, None)] * (3 * E_total))                                  # g_ω, a⁺, a⁻
    res = linprog(c_obj, A_eq=A_eq, b_eq=b_eq, A_ub=A_ub, b_ub=b_ub, bounds=bounds, method="highs")
    assert res.success, res.message
    x = res.x
    return (x[G0:G0 + T].reshape(NDAYS, N), x[C0:C0 + T].reshape(NDAYS, N),
            x[D0:D0 + T].reshape(NDAYS, N), x[S_idx:S_idx + T + 1], res.fun)


# ================= 0:00 全年计划 =================
if MODE == "myopic":
    N_hat = (L_base - P_hat).ravel()
    g_plan, c_plan, d_plan, soc_plan = solve_annual(N_hat)
elif MODE == "farsighted":
    N_hat = np.empty_like(L_base)
    for d in range(NDAYS):
        base = L_base[d] - P_hat[d]
        peers = [d - 7 * k for k in range(1, K_PEERS + 1) if d - 7 * k >= 0]
        if peers:
            resid = np.stack([(load[p] - pv[p]) - (L_base[p] - P_hat[p]) for p in peers])
            N_hat[d] = base + np.quantile(resid, Q_FARSIGHT, axis=0)
        else:
            N_hat[d] = base
    N_hat = N_hat.ravel()
    g_plan, c_plan, d_plan, soc_plan = solve_annual(N_hat)
elif MODE == "stochastic":
    g_plan, c_plan, d_plan, soc_plan, _ = solve_stochastic_plan()
else:
    raise ValueError(MODE)
g_plan = g_plan.reshape(NDAYS, N)
c_plan = c_plan.reshape(NDAYS, N)
d_plan = d_plan.reshape(NDAYS, N)
soc_mid = soc_plan[::N]                      # 每天 0:00 SOC (366 个，含年末)


def soc_current(d, start_idx):
    """执行到 start_idx 后的 SOC（用已定的 g/c/d 与递推）。"""
    s = soc_mid[d]
    for t in range(start_idx):
        s += ETA * c_final[d, t] * DT - d_final[d, t] * DT / ETA
    return s


# ================= 日内滚动调整 + 紧急购电 =================
g_final = g_plan.copy()
c_final = c_plan.copy()
d_final = d_plan.copy()

stage_n = 0
for d in range(NDAYS):
    soc_end = soc_mid[d + 1] if d + 1 < NDAYS else SOC0   # 24:00 锚
    for s_hour, s_idx in [(6, 1), (12, 2), (18, 3)]:
        start_idx = s_hour * 6
        P_rem = pv_forecast_10min(d, s_idx, s_hour)[start_idx:]
        elapsed = slice(0, start_idx)
        r = load[d, elapsed].sum() / L_base[d, elapsed].sum() if L_base[d, elapsed].sum() > 1e-6 else 1.0
        L_rem = r * L_base[d, start_idx:]
        g, c, dd, _ = solve_stage(start_idx, soc_current(d, start_idx),
                                  soc_end, P_rem, L_rem, g_plan[d, start_idx:],
                                  price_day[start_idx:])
        nxt = start_idx + 36
        g_final[d, start_idx:nxt] = g[:36]
        c_final[d, start_idx:nxt] = c[:36]
        d_final[d, start_idx:nxt] = dd[:36]
        stage_n += 1


# ================= 紧急购电 + 能量 =================
# 题面口径：e 只补"微网提供的电能(购电+光伏+放电)低于小区负载"的缺口，不含充电量
e = np.maximum(0.0, load - g_final - pv - d_final)                # (365,144) kW
plan_kwh = g_plan * DT
adj_kwh = (g_final - g_plan) * DT
em_kwh = e * DT

win = np.zeros(NDAYS, dtype=bool); win[REPORT:] = True


def day_fee_A(di):
    """口径 A 的单日总费（与 problem3_v3.py 的 write_result3.day_fee 同式）。

        总费 = Σ p·ĝ·Δt  +  0.5·Σ p·(ĝ−g)⁺·Δt  +  1.5·Σ p·(g−ĝ)⁺·Δt  +  5·Σ p·e·Δt

    adj_kwh = (g − ĝ)·Δt（带符号净差），故 (ĝ−g)⁺ = max(−adj, 0)、(g−ĝ)⁺ = max(adj, 0)。
    ⚠ 两项的**系数不同**（0.5 对下调、1.5 对上调），不能合并成 `0.5·|Δ|`——
      那个对称写法与口径 A 相差 `Σp·(ĝ−g)⁺`。
    """
    a = adj_kwh[di]
    return float((price_day * plan_kwh[di]).sum()
                 + (0.5 * price_day * np.maximum(-a, 0.0)).sum()
                 + (1.5 * price_day * np.maximum(a, 0.0)).sum()
                 + (5.0 * price_day * em_kwh[di]).sum())


# 口径 A 分项（计费窗口）
plan_fee = (price_day * plan_kwh)[win].sum()
breach_fee = (0.5 * price_day * np.maximum(-adj_kwh, 0.0))[win].sum()
excess_fee = (1.5 * price_day * np.maximum(adj_kwh, 0.0))[win].sum()
em_fee = (5 * price_day * em_kwh)[win].sum()


def soc_final_check():
    s = np.empty((NDAYS, N + 1))
    for d in range(NDAYS):
        s[d, 0] = soc_mid[d]
        for t in range(N):
            s[d, t + 1] = s[d, t] + ETA * c_final[d, t] * DT - d_final[d, t] * DT / ETA
    return s


soc_fin = soc_final_check()

# ================= 自检 =================
print("=" * 72)
print(f"问题 3 求解自检（MODE={MODE}，窗口 2/1–12/31，共 {NDAYS - REPORT} 天）")
print("=" * 72)
print(f"0:00 计划 SOC 范围    : [{soc_plan.min():.1f}, {soc_plan.max():.1f}] kWh (应∈[1200,10800])")
print(f"SOC_0 / SOC_T         : {soc_plan[0]:.1f} / {soc_plan[-1]:.1f} kWh (应=6000)")
print(f"调整阶段求解次数      : {stage_n} (应={NDAYS * 3})")
print(f"调整后 SOC 范围       : [{soc_fin.min():.1f}, {soc_fin.max():.1f}] kWh (应∈[1200,10800])")
print(f"每日 24:00 SOC 锚偏差 : {np.abs(soc_fin[:, N] - soc_mid[1:]).max():.2f} kWh (应≈0)")
print("-" * 72)
print(f"计划购电费 Σp·ĝ       : {plan_fee:,.0f} 元")
print(f"　违约费 0.5p(ĝ−g)⁺   : {breach_fee:,.0f} 元")
print(f"　超额费 1.5p(g−ĝ)⁺   : {excess_fee:,.0f} 元")
print(f"紧急购电费 5p·e       : {em_fee:,.0f} 元")
print(f"总购电费（口径 A）    : {plan_fee + breach_fee + excess_fee + em_fee:,.0f} 元")
print(f"计划购电量(计划侧)    : {plan_kwh[win].sum():,.0f} kWh")
print(f"调整购电量(净带符号)  : {adj_kwh[win].sum():,.0f} kWh")
print(f"紧急购电量            : {em_kwh[win].sum():,.0f} kWh")


# ================= 写 result3.xlsx =================
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


template = os.path.join(BASE, "附件", "附件5", "result3.xlsx")
# ⚠ 故意**不写** 结果/result3.xlsx —— 那是 problem3_v3.py（口径 A 定稿）的交付物，
#   旧版这里是同一个路径，跑一次就会静默覆盖定稿。
#   也不写进 结果/ 目录：那里是交卷时整包提交的，混进一个"旧版非交付物"有被误交的风险。
#   落到 代码/诊断/_* （既有的「下划线前缀 = 可重跑中间产物」约定，已被 .gitignore 覆盖）。
out_path = (os.environ.get("P3_LEGACY_OUT")
            or os.path.join(BASE, "代码", "诊断", "_p3_legacy.xlsx"))
wb = openpyxl.load_workbook(template)
report_days = range(REPORT, NDAYS)
date0 = dt.date(2025, 1, 1)
blocks = [("0:00-4:00", 0, 24), ("4:00-8:00", 24, 48), ("8:00-12:00", 48, 72),
          ("12:00-16:00", 72, 96), ("16:00-20:00", 96, 120), ("20:00-24:00", 120, 144)]

ws_p = wb["计划购电量"]
for j, di in enumerate(report_days):
    row = j + 2
    for k in range(N):
        ws_p.cell(row=row, column=2 + k).value = round(float(plan_kwh[di][(k + 1) % N]), 4)
    ws_p.cell(row=row, column=2 + N).value = round(float(plan_kwh[di].sum()), 4)
    # 口径 A 全天总费。⚠ 两张购电量表写的是**同一个物理日**的全口径总费，
    #   与 problem3_v3.py 的写盘器一致；读表只能取其一，**不可相加**。
    ws_p.cell(row=row, column=3 + N).value = round(day_fee_A(di), 2)

ws_a = wb["调整购电量"]
for j, di in enumerate(report_days):
    row = j + 2
    for k in range(N):
        ws_a.cell(row=row, column=2 + k).value = round(float(adj_kwh[di][(k + 1) % N]), 4)
    ws_a.cell(row=row, column=2 + N).value = round(float(adj_kwh[di].sum()), 4)
    # 同上：与「计划购电量」表同值（同一物理日的全口径总费），不是"仅调整费"。
    ws_a.cell(row=row, column=3 + N).value = round(day_fee_A(di), 2)

ws_c = wb["充放电量"]
ws_c.delete_rows(2, ws_c.max_row - 1)
for j, di in enumerate(report_days):
    base = j * 6 + 2
    date_val = date0 + dt.timedelta(days=di)
    for bj, (name, a, b) in enumerate(blocks):
        r = base + bj
        ws_c.cell(row=r, column=1).value = date_val if bj == 0 else None
        ws_c.cell(row=r, column=2).value = name
        ws_c.cell(row=r, column=3).value = round(float((c_final[di][a:b] * DT).sum()), 4)
        ws_c.cell(row=r, column=4).value = round(float((d_final[di][a:b] * DT).sum()), 4)
    ws_c.cell(row=base, column=5).value = "0:00"
    ws_c.cell(row=base, column=6).value = round(float(soc_fin[di, 0]), 4)
    ws_c.cell(row=base + 1, column=5).value = "24:00"
    ws_c.cell(row=base + 1, column=6).value = round(float(soc_fin[di, N]), 4)

ws_e = wb["紧急购电量"]
ws_e.delete_rows(2, ws_e.max_row - 1)
r = 2
for j, di in enumerate(report_days):
    segs = emergency_segments(em_kwh[di])
    ws_e.cell(row=r, column=1).value = date0 + dt.timedelta(days=di)
    if segs:
        for si, (tstr, kwh) in enumerate(segs):
            ws_e.cell(row=r, column=2).value = tstr
            ws_e.cell(row=r, column=3).value = round(kwh, 4)
            r += 1
    else:
        ws_e.cell(row=r, column=3).value = 0.0
        r += 1

wb.save(out_path)
print(f"\n结果已写入: {out_path}")

# ================= 表1/2/3 指定日期 =================
special = [dt.date(2025, 3, 20), dt.date(2025, 6, 21), dt.date(2025, 9, 23), dt.date(2025, 12, 21)]
special_idx = [(d - date0).days for d in special]
win_idx = {"10:00-10:10": 60, "12:00-12:10": 72, "14:00-14:10": 84,
           "16:00-16:10": 96, "18:00-18:10": 108, "20:00-20:10": 120}
print("\n" + "=" * 72)
print("表1/表2/表3 指定日期")
print("=" * 72)
for di in special_idx:
    dstr = (date0 + dt.timedelta(days=di)).strftime("%Y.%m.%d")
    pl = plan_kwh[di].sum(); adj = adj_kwh[di].sum(); em = em_kwh[di].sum()
    total_fee = day_fee_A(di)
    print(f"\n【{dstr}】 计划 {pl:.2f}  调整 {adj:+.2f}  紧急 {em:.2f}  全天购电费 {total_fee:.2f} 元")
    print("  表1 计划购电量(kWh):", "  ".join(f"{w}={plan_kwh[di][i]:.2f}" for w, i in win_idx.items()))
    print("  表3 紧急购电量(kWh):", f"{em:.2f}")
