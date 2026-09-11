# -*- coding: utf-8 -*-
"""问题2 场景集分组实验：把「低需求日」单独分一组，是否有显著收益。

口径（全程统一，见前序讨论）：
  0:00 只承诺计划购电量 ĝ；充放电与紧急购电都是实时追索。
  执行器固定为 execute_soc_causal（缺口驱动、逐槽因果、SOC/功率严格受限）。
  ⇒ 配置之间唯一的差别就是 ĝ，而 ĝ 的唯一差别就是场景集。

面板 A：各种场景集 → γ=1 可交付 LP → ĝ → 因果执行 → 逐日成本配对检验
面板 B：报童分位 ĝ = τ 分位(净负荷) → 扫 τ（不依赖 LP，隔离「场景集质量」本身）
面板 C：样本外——分组规则只用 1-6 月数据推导，成本只在 7-12 月评估
"""
import os
import sys
import numpy as np
import pandas as pd
from scipy.optimize import linprog
from scipy import sparse

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DT, ETA, P_MAX = 1.0 / 6.0, 0.9, 5000.0
SOC_MIN, SOC_MAX, SOC0 = 1200.0, 10800.0, 6000.0
N, NDAYS, REPORT = 144, 365, 31
T = N * NDAYS

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
price_day = pd.read_excel(os.path.join(BASE, "附件", "附件1.xlsx")).iloc[:, 1].to_numpy(float)
load = pd.read_excel(os.path.join(BASE, "附件", "附件2.xlsx"), sheet_name="小区负载").iloc[:, 1:1 + N].to_numpy(float)
pv = pd.read_excel(os.path.join(BASE, "附件", "附件2.xlsx"), sheet_name="光伏发电实际功率").iloc[:, 1:1 + N].to_numpy(float)
price = np.tile(price_day, NDAYS)
L = load.ravel(); P = pv.ravel()
RDAYS = np.arange(REPORT, NDAYS)          # 334 个报告日
net = (load - pv).sum(axis=1)             # 各日净负荷

# ---------- 场景集构造 ----------
def peers_same_weekday(k):
    return [[d - 7 * j for j in range(1, k + 1) if d - 7 * j >= 0] for d in range(NDAYS)]


def peers_group(dows, span=14):
    m = np.array([(d % 7) in dows for d in range(NDAYS)])
    return [[t for t in range(max(0, d - span), d) if m[t] == m[d]] for d in range(NDAYS)]


def peers_all(span=14):
    return [[t for t in range(max(0, d - span), d)] for d in range(NDAYS)]


def low_demand_dows(train_days):
    """从训练日推断『低需求日』：日均净负荷最低的两个星期几。"""
    m = np.array([d % 7 for d in range(NDAYS)])
    means = [(m[train_days] == k).sum() and net[train_days][m[train_days] == k].mean() for k in range(7)]
    order = np.argsort(means)
    return (int(order[0]), int(order[1])), means


# ---------- γ=1 可交付 LP（与项目求解器同源）----------
def solve_deliver(peers, gamma=1.0):
    base_e = np.zeros(NDAYS, dtype=np.int64)
    _c = 0
    for d in range(NDAYS):
        base_e[d] = _c; _c += max(1, len(peers[d])) * N
    E_total = _c

    def sc_idx(d):
        return peers[d] if peers[d] else [d]

    G0, D0, S0_, CM0, E0 = 0, T, 2 * T, 3 * T + 1, 4 * T + 1
    n_vars = E0 + E_total
    q = np.empty(T)
    for dd in range(NDAYS):
        p = sc_idx(dd)
        vals = pv[p] - load[p]
        q[dd * N:(dd + 1) * N] = np.quantile(vals, 1.0 - gamma, axis=0) if len(p) > 1 else vals[0]

    c_obj = np.zeros(n_vars); c_obj[G0:G0 + T] = price
    for dd in range(NDAYS):
        p = sc_idx(dd); Kd = len(p)
        for w in range(Kd):
            sl = slice(base_e[dd] + w * N, base_e[dd] + (w + 1) * N)
            c_obj[E0 + sl.start:E0 + sl.stop] = 5.0 * price_day / Kd

    t = np.arange(T)
    A_eq = sparse.coo_matrix(
        (np.concatenate([np.ones(T), -np.ones(T), -ETA * DT * np.ones(T), (DT / ETA) * np.ones(T)]),
         (np.concatenate([t, t, t, t]),
          np.concatenate([S0_ + t + 1, S0_ + t, CM0 + t, D0 + t]))),
        shape=(T, n_vars)).tocsr()

    n1, n2 = T, E_total
    ur, uc, ud, ub = [], [], [], []
    ur += [t, t, t]; uc += [CM0 + t, G0 + t, D0 + t]
    ud += [np.ones(T), -np.ones(T), -np.ones(T)]; ub.append(q)
    for dd in range(NDAYS):
        for w, pd_ in enumerate(sc_idx(dd)):
            r = base_e[dd] + w * N
            rr = n1 + np.arange(r, r + N); tt = dd * N + np.arange(N)
            ur += [rr, rr, rr]; uc += [G0 + tt, D0 + tt, E0 + np.arange(r, r + N)]
            ud += [-np.ones(N), -np.ones(N), -np.ones(N)]
            ub.append(pv[pd_] - load[pd_])
    A_ub = sparse.coo_matrix((np.concatenate(ud), (np.concatenate(ur), np.concatenate(uc))),
                             shape=(n1 + n2, n_vars)).tocsr()

    bounds = ([(0, None)] * T + [(0, P_MAX)] * T
              + [(SOC0, SOC0)] + [(SOC_MIN, SOC_MAX)] * (T - 1) + [(SOC0, SOC0)]
              + [(0, P_MAX)] * T + [(0, None)] * E_total)
    res = linprog(c_obj, A_eq=A_eq, b_eq=np.zeros(T), A_ub=A_ub, b_ub=np.concatenate(ub),
                  bounds=bounds, method="highs")
    assert res.success, res.message
    return res.x[G0:G0 + T]


# ---------- 追索执行层（唯一口径）----------
def exec_causal(g):
    c = np.zeros(T); d = np.zeros(T); e = np.zeros(T); soc = SOC0
    for t in range(T):
        deficit = L[t] - P[t] - g[t]
        if deficit < 0: deficit = 0.0
        d[t] = min(deficit, P_MAX, max(0.0, (soc - SOC_MIN) * ETA / DT))
        c[t] = min(P_MAX, max(0.0, P[t] + g[t] + d[t] - L[t]), max(0.0, (SOC_MAX - soc) / (ETA * DT)))
        e[t] = max(0.0, L[t] - P[t] - g[t] - d[t])
        soc += (ETA * c[t] - d[t] / ETA) * DT
    return e


def daily_cost(g):
    """逐日成本数组（334 天）。"""
    e = exec_causal(g)
    per = (price * g * DT + 5 * price * e * DT).reshape(NDAYS, N).sum(axis=1)
    return per[RDAYS], e


def block_bootstrap(diff, block=14, n_boot=4000, seed=0):
    """移动块自助：电池跨日耦合⇒日序列自相关，普通 t 检验会高估显著性。"""
    rng = np.random.default_rng(seed)
    n = len(diff); nb = int(np.ceil(n / block))
    starts = np.arange(n - block + 1)
    means = np.empty(n_boot)
    for i in range(n_boot):
        s = rng.choice(starts, nb, replace=True)
        idx = np.concatenate([np.arange(j, j + block) for j in s])[:n]
        means[i] = diff[idx].mean()
    return np.percentile(means, [2.5, 97.5])


# ============================ 面板 A ============================
LOW_DOWS, DOW_MEANS = low_demand_dows(np.arange(0, 182))
print("=" * 100)
print("面板 A：γ=1 可交付计划 + 因果追索执行（334 个报告日，全程同一执行器）")
print("=" * 100)
print("按日净负荷 (kWh/日) 的星期均值：", "  ".join(
    f"{['Wed','Thu','Fri','Sat','Sun','Mon','Tue'][k]}={DOW_MEANS[k]:,.0f}" for k in range(7)))
print(f"⇒ 数据推断的低需求日 = {{{', '.join(['Wed','Thu','Fri','Sat','Sun','Mon','Tue'][k] for k in LOW_DOWS)}}}"
      f"   （PR#1 手工取的就是这一对）")
print()

CFG = [
    ("A1 同星期几 K=4  [main基线]", peers_same_weekday(4)),
    ("A2 同星期几 K=2", peers_same_weekday(2)),
    ("A3 低需求日/其余 (Fri+Sat)", peers_group(LOW_DOWS)),
    ("A4 日历周末/工作日 (Sat+Sun)", peers_group((3, 4))),
    ("A5 不分组 近14天", peers_all(14)),
]

resA = {}
print(f"{'配置':<30}{'总成本(元)':>15}{'计划费':>14}{'紧急kWh':>12}{'前半':>14}{'后半':>14}")
print("-" * 100)
for tag, peers in CFG:
    g = solve_deliver(peers, 1.0)
    dc, e = daily_cost(g)
    planned = (price * g * DT)[REPORT * N:].sum()
    ekwh = (e * DT)[REPORT * N:].sum()
    h1, h2 = dc[:167].sum(), dc[167:].sum()
    resA[tag] = dict(dc=dc, tot=dc.sum(), planned=planned, ekwh=ekwh, h1=h1, h2=h2)
    print(f"{tag:<30}{dc.sum():>15,.0f}{planned:>14,.0f}{ekwh:>12,.0f}{h1:>14,.0f}{h2:>14,.0f}")
print("-" * 100)
base = resA["A1 同星期几 K=4  [main基线]"]["dc"]
print(f"\n{'对比（配对到日，正=更贵）':<30}{'Δ总成本':>14}{'Δ日均':>12}{'95% 块自助CI':>26}{'显著':>8}")
print("-" * 100)
for tag in list(resA)[1:]:
    diff = resA[tag]["dc"] - base
    lo, hi = block_bootstrap(diff)
    sig = "是" if (lo > 0) == (hi > 0) else "否"
    print(f"{tag:<30}{diff.sum():>+14,.0f}{diff.mean():>+12,.0f}"
          f"{f'[{lo:+,.0f}, {hi:+,.0f}]':>26}{sig:>8}")
print("（CI 用 14 天移动块自助 4000 次，已考虑电池跨日耦合带来的自相关）")

# ============================ 面板 B ============================
print()
print("=" * 100)
print("面板 B：报童分位 ĝ = τ 分位(净负荷) —— 不经过 LP，直接检验「场景集质量」")
print("=" * 100)
taus = [0.75, 0.80, 0.85, 0.90, 0.95, 0.975, 1.0]
print(f"{'配置':<30}" + "".join(f"{'τ='+format(t,'.3g'):>13}" for t in taus) + f"{'最优τ':>8}{'最优成本':>14}")
print("-" * 100)
resB = {}
for tag, peers in CFG:
    row = []
    for tau in taus:
        g = np.empty(T)
        for dd in range(NDAYS):
            p = peers[dd] if peers[dd] else [dd]
            vals = pv[p] - load[p]
            g[dd * N:(dd + 1) * N] = np.quantile(vals, tau, axis=0) if len(p) > 1 else vals[0]
        dc, _ = daily_cost(g)
        row.append(dc.sum())
    j = int(np.argmin(row))
    resB[tag] = (taus[j], row[j], row)
    print(f"{tag:<30}" + "".join(f"{v:>13,.0f}" for v in row) + f"{taus[j]:>8.3g}{row[j]:>14,.0f}")
print("-" * 100)
b_tau, b_cost, _ = resB["A1 同星期几 K=4  [main基线]"]
for tag in list(resB)[1:]:
    tau, cost, _ = resB[tag]
    print(f"  {tag:<28} 最优 τ={tau:.3g}  成本 {cost:,.0f}  相对基线 {cost-b_cost:+,.0f} "
          f"({(cost-b_cost)/b_cost*100:+.2f}%)")

# ============================ 面板 C ============================
print()
print("=" * 100)
print("面板 C：样本外 —— 分组规则只用 1-6 月推导，成本只在 7-12 月评估")
print("=" * 100)
train = np.arange(0, 182)
oos = np.arange(182, NDAYS)
oos_in_rpt = oos[oos >= REPORT]
LOW_TRAIN, _ = low_demand_dows(train)
print(f"  仅用 1-6 月推出的低需求日 = "
      f"{{{', '.join(['Wed','Thu','Fri','Sat','Sun','Mon','Tue'][k] for k in LOW_TRAIN)}}}")
print(f"  评估窗口 = {len(oos_in_rpt)} 天（2025-07-01 起）\n")
print(f"{'配置':<30}{'评估窗口成本':>16}{'相对基线':>14}")
print("-" * 100)
base_oos = None
for tag, peers in [("C1 同星期几 K=4  [main基线]", peers_same_weekday(4)),
                   ("C2 低需求日/其余 (样本外分组)", peers_group(LOW_TRAIN)),
                   ("C3 日历周末/工作日 (Sat+Sun)", peers_group((3, 4))),
                   ("C4 同星期几 K=2", peers_same_weekday(2))]:
    g = solve_deliver(peers, 1.0)
    dc, _ = daily_cost(g)
    m = np.isin(RDAYS, oos_in_rpt)
    v = dc[m].sum()
    if base_oos is None: base_oos = v
    print(f"{tag:<30}{v:>16,.0f}{v-base_oos:>+14,.0f}")
print("-" * 100)
