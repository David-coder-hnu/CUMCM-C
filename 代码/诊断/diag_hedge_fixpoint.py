# -*- coding: utf-8 -*-
"""逐时段最优对冲 —— 报童不动点迭代。

理论依据
--------
问题 2 里 g ≡ ĝ（无调整通道），故总费 = Σp·ĝ·Δt + 5Σp·e·Δt，其中
    e_t = max(0, N_t − ĝ_t − d_t)，  N_t = 实际净需求，d_t = 电池放电。
对 ĝ_t 求一阶条件（其余时刻视为不变）：
    ∂/∂ĝ_t = p_t·Δt − 5·p_t·Δt·P(N_t − d_t > ĝ_t) = 0
  ⇒ P(N_t − d_t > ĝ_t) = 1/5  ⇔  ĝ_t = 80 分位( N_t − d_t )

**关键点：要对冲的是"电池放电后的残余缺口"，不是净需求本身。** 均匀分位数扫描
（Q_ALL）把同一个分位套到所有时段，等价于假设电池在所有时段削掉的缺口一样多，
这个假设不成立 —— 夜里有富余、傍晚缺口大，电池的削峰能力逐时段不同。

算法
----
直接解不动点而非次梯度爬山。记每槽 t 的"残余缺口"（负=富余）
    def_t = N_t − g_t − d_t        （g = 实际购电，d = 实际放电）
则 P(缺口) = P(def_t > 0)，一阶条件等价于 **Q_{0.8}(def_t) = 0**。
把 ĝ_t 抬高 δ 会让 g_t 大致同幅抬高、从而把 def_t 压低 δ，故迭代式取

    HEDGE_t ← HEDGE_t + λ · Q_{0.8}(def_{·,t})        （λ = 阻尼，默认 0.7）

这等价于让 ĝ 收敛到 Q_{0.8}(N_t − d_t)，即"电池放电后残余缺口"的 80 分位 ——
比对净需求直接取 80 分位要低（电池已经吃掉一部分缺口），差额正是"ĝ 的时域形状"
该做的修正。每轮都重跑完整执行层，故 d_t 随 ĝ 一起更新，是坐标下降。
只接受让【实际执行成本】下降的更新，故结果不会比出发点更差。

用法：python 代码/诊断/diag_hedge_fixpoint.py [迭代轮数，默认 10]
"""
import os
import re
import subprocess
import sys

import numpy as np
import pandas as pd

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DT, N, NDAYS, REPORT, K_PEERS = 1.0 / 6.0, 144, 365, 31, 4
T = N * NDAYS
ITERS = int(sys.argv[1]) if len(sys.argv) > 1 else 8
# ⚠ 阻尼不能取 1.0。更新式假设 d(ĝ) 对 def 是 1:1 的，但实际有负反馈：压低 ĝ 会让
#   执行层的 need = L−P−g 变大、电池被迫多放，于是 def 降得比 δ 少 —— 步长过大会过冲。
#   每轮都保留 best-so-far，故结果不会比出发点差，只会慢。
DAMP = float(os.environ.get("DAMP", 0.40))      # 阻尼系数
HEDGE_PATH = os.path.join(BASE, "代码", "诊断", "_hedge_iter.npy")
DUMP = os.path.join(BASE, "代码", "诊断", "_fixpoint_dump.npz")
SCRIPT = os.path.join(BASE, "代码", "problem3_v2.py")

# ---- 复算残差以给出初值 ----
load = pd.read_excel(os.path.join(BASE, "附件", "附件2.xlsx"), sheet_name="小区负载") \
         .iloc[:, 1:1 + N].to_numpy(float)
pv = pd.read_excel(os.path.join(BASE, "附件", "附件2.xlsx"), sheet_name="光伏发电实际功率") \
       .iloc[:, 1:1 + N].to_numpy(float)
fc3 = pd.read_excel(os.path.join(BASE, "附件", "附件3.xlsx"), header=None) \
        .iloc[1:, 2:].to_numpy(float).reshape(NDAYS, 4, 24)
mean_load = load.mean(axis=0)
L_base = np.empty_like(load)
for d in range(NDAYS):
    idx = [d - 7 * k for k in range(1, K_PEERS + 1) if d - 7 * k >= 0]
    L_base[d] = load[idx].mean(axis=0) if idx else mean_load
W = np.zeros((N, 25))
for k in range(N):
    t = (k + 1) / 6.0
    lo = int(np.floor(t)); hi = min(int(np.ceil(t)), 24)
    if lo == hi:
        W[k, lo] = 1.0
    else:
        W[k, lo] = 1.0 - (t - lo); W[k, hi] = t - lo


def pv_fc(d, s_idx, s_hour):
    H = np.zeros(25)
    if s_hour > 0:
        H[s_hour] = pv[d, 6 * s_hour]
    for h in range(s_hour + 1, 25):
        H[h] = fc3[d, s_idx, h - s_hour - 1]
    return H @ W.T


P_hat = np.stack([[pv_fc(d, s, [0, 6, 12, 18][s]) for s in range(4)] for d in range(NDAYS)])
F0 = L_base - P_hat[:, 0, :]
resid0 = (load - pv) - F0

COST_RE = re.compile(r"^\s+合计\s+([\d,]+)\s+元", re.M)


def run(hedge):
    np.save(HEDGE_PATH, hedge)
    env = dict(os.environ, NO_SAVE="1", NO_ADJ="1", PLAN="lp", EXEC_SMART="2",
               HEDGE_NPY=HEDGE_PATH, DUMP_NPZ=DUMP, PYTHONIOENCODING="utf-8")
    out = subprocess.run([sys.executable, SCRIPT], capture_output=True, text=True,
                         env=env, encoding="utf-8", errors="replace")
    if out.returncode != 0:
        print(out.stdout[-2000:]); print(out.stderr[-2000:])
        raise SystemExit(f"求解失败，returncode={out.returncode}")
    m = COST_RE.search(out.stdout)
    if not m:
        print(out.stdout[-2000:]); raise SystemExit("未能从输出中解析合计费用")
    cost = float(m.group(1).replace(",", ""))
    d_ = np.load(DUMP)
    return cost, d_["g_fin"], d_["d_fin"]


print("=" * 78)
print("逐时段最优对冲 —— 报童不动点迭代")
print("  口径：问题 2（NO_ADJ=1）+ PLAN=lp + EXEC_SMART=2 执行层")
print("=" * 78)
hedge = np.quantile(resid0, 0.80, axis=0)       # 初值：净需求的 80 分位（= Q_ALL 0.80）
best_cost, best_hedge = None, hedge.copy()
net = (load - pv).ravel()                       # 实际净需求 N

for it in range(ITERS):
    cost, g_fin, d_fin = run(hedge)
    dflt = (net - g_fin - d_fin).reshape(NDAYS, N)[REPORT:]   # 残余缺口，负=富余
    frac = (dflt > 0).mean(axis=0)              # 缺口发生频率，理论目标 0.20
    q80 = np.quantile(dflt, 0.80, axis=0)       # 残余缺口的 80 分位，理论目标 0
    tag = ""
    if best_cost is None or cost < best_cost - 1:
        best_cost, best_hedge, tag = cost, hedge.copy(), "  ← 新最优"
    print(f"  轮 {it:>2}  成本 {cost:>14,.2f} 元"
          f"  缺口频率 均值 {frac.mean():.3f} / 最大 {frac.max():.3f}"
          f"  max|Q80| {np.abs(q80).max():>7.1f} kW"
          f"  Σĝ {(g_fin * DT).sum():>12,.0f} kWh{tag}")
    if np.abs(q80).max() < 5.0 and it > 1:
        print("  收敛：各时段残余缺口的 80 分位已 < 5 kW")
        break
    hedge = np.maximum(0.0, hedge + DAMP * q80)

print(f"\n最优执行成本 {best_cost:,.2f} 元")
print("对照：SP 计划层 17,149,812 元；均匀分位 0.80 为 15,837,382 元")
np.save(HEDGE_PATH, best_hedge)
print(f"最优对冲向量已存 {HEDGE_PATH}")
