# -*- coding: utf-8 -*-
"""问题 2 —— 新模型：储能作【追索】变量 + 滚动执行（SDDP 的实用近似）。

重新划界：日前 0:00 承诺的**只有购电量 ĝ_t**；储能充放电 c,d 与紧急购电 e 都放进
二阶段追索 —— 它们本来就由当天实际负荷/光伏决定，把它们写成一阶段承诺量，正是现交付
文件"计划放不出的电"的病根。

日尺度子问题（起 SOC = 0:00 实测值 S）：
    min_{ĝ ≥ 0}  Σ_t p_t ĝ_t Δt  +  (1/K)Σ_ω [ Σ_t 5 p_t e_{t,ω} Δt − λ·SOC_{T,ω} ]
    s.t. 逐情景 ω：SOC 递推（起点 S）、1200 ≤ SOC ≤ 10800、0 ≤ c,d ≤ 5000
                   c_{t,ω} − ĝ_t − d_{t,ω} − e_{t,ω} ≤ P_{t,ω} − L_{t,ω}   槽级能量平衡
                   e_{t,ω} ≥ L_{t,ω} − P_{t,ω} − ĝ_t − d_{t,ω}      紧急只补负载缺口

λ = 储能的边际价值（元/kWh）。它就是 SDDP 里值函数 V(S) 的单割平面近似
（V(S) ≈ λ·S）。本脚本用一维打靶把 λ 标定到"年末 SOC 回到 6000"，
从而用一个有经济含义的终端条件取代团队自加的"全年能量中性"硬约束。

执行层两个口径：
    EXEC=oracle  日内完美预见（储能瞬时知道当天全部负荷/光伏）——乐观下界
    EXEC=mpc     因果滚动 MPC：已实测的用实测、未来用同伴情景均值预报 —— 可实现

用法：
    python 代码/独立视角/p2_recourse.py
    EXEC=mpc BISECT=8 python 代码/独立视角/p2_recourse.py
"""
import os
import sys
import time

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
K_PEERS = 4
EXEC = os.environ.get("EXEC", "oracle")
TERM = os.environ.get("P2_TERM", "neutral")     # neutral | lam
MPC_H = int(os.environ.get("MPC_H", 36))
BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

price_day = pd.read_excel(os.path.join(BASE, "附件", "附件1.xlsx")).iloc[:, 1].to_numpy(float)
load = pd.read_excel(os.path.join(BASE, "附件", "附件2.xlsx"), sheet_name="小区负载") \
         .iloc[:, 1:1 + N].to_numpy(float)
pv = pd.read_excel(os.path.join(BASE, "附件", "附件2.xlsx"), sheet_name="光伏发电实际功率") \
       .iloc[:, 1:1 + N].to_numpy(float)
peers = [[d - 7 * k for k in range(1, K_PEERS + 1) if d - 7 * k >= 0] for d in range(NDAYS)]


def day_lp(Ls, Ps, S, lam, nslots=N, g_fix=None, pseq=None, soc_end=None):
    """日尺度两阶段 LP。

    Ls, Ps : (K, nslots) 情景
    S      : 起 SOC（所有情景共用，实测）
    g_fix  : None → ĝ 是决策（计划层）；数组 → ĝ 固定（执行层）
    pseq   : 该窗口对应的电价切片；None 表示从 0:00 起算
    返回 (g, [(c,d,e,soc_end)]*K)
    """
    K, m = Ls.shape
    G0, CB0 = 0, m
    DB0 = CB0 + K * m
    SB0 = DB0 + K * m
    EB0 = SB0 + K * (m + 1)
    nv = EB0 + K * m
    p = price_day[:m] if pseq is None else np.asarray(pseq)[:m]

    c_obj = np.zeros(nv)
    c_obj[G0:G0 + m] = p * DT
    for w in range(K):
        c_obj[EB0 + w * m:EB0 + (w + 1) * m] = 5.0 * p * DT / K
        c_obj[SB0 + w * (m + 1) + m] = -lam / K          # 末端 SOC 价值

    i = np.arange(m)
    rows, cols, dat = [], [], []
    for w in range(K):
        base = w * (m + 1)
        rows += [base + i, base + i, base + i, base + i]
        cols += [SB0 + base + i + 1, SB0 + base + i,
                 CB0 + w * m + i, DB0 + w * m + i]
        dat += [np.ones(m), -np.ones(m), -ETA * DT * np.ones(m), (DT / ETA) * np.ones(m)]
    A_eq = sparse.coo_matrix((np.concatenate(dat), (np.concatenate(rows), np.concatenate(cols))),
                             shape=(K * (m + 1), nv)).tocsr()
    # 递推右端恒为 0；S_0 = S 由【下界】承担（写成 b_eq=S 会把 S_1 顶到 2S 而不可行）
    b_eq = np.zeros(K * (m + 1))

    # 槽级能量平衡（唯一必需的耦合约束）：
    #   P + ĝ + d + e ≥ L + c   ⇔   c − ĝ − d − e ≤ P − L
    # 它自动蕴含"紧急购电只补缺口"（c=0 时即 e ≥ L−P−ĝ−d）。
    # 反例（本脚本第一版就踩了）：写成"充电只吃富余" c ≤ ĝ + d + max(0, P−L)，
    # 在缺电时段该式退化为 c ≤ ĝ + d —— 于是同一份 ĝ + d 既去顶负载缺口、又去给电池充电，
    # 净凭空造电，全年总费会掉到完美预见下界以下（实测 2,773,754 元 ≪ 12,229,461 元）。
    ur, uc, ud = [], [], []
    surps = [Ps[w] - Ls[w] for w in range(K)]
    for w in range(K):
        r = w * m + i
        ur += [r, r, r, r]
        uc += [CB0 + w * m + i, G0 + i, DB0 + w * m + i, EB0 + w * m + i]
        ud += [np.ones(m), -np.ones(m), -np.ones(m), -np.ones(m)]
    A_ub = sparse.coo_matrix((np.concatenate(ud), (np.concatenate(ur), np.concatenate(uc))),
                             shape=(K * m, nv)).tocsr()
    b_ub = np.concatenate(surps)

    # 变量顺序必须与 G0/CB0/DB0/SB0/EB0 完全一致：g | c | d | SOC | e
    lo = [0.0] * m + [0.0] * (K * m) + [0.0] * (K * m)
    hi = [None] * m + [P_MAX] * (K * m) + [P_MAX] * (K * m)
    for _ in range(K):
        lo += [S] + [SOC_MIN] * m
        hi += [S] + [SOC_MAX] * m
    lo += [0.0] * (K * m)
    hi += [None] * (K * m)
    if TERM == "neutral":
        # 日末 SOC 回到当日起点：团队"全年能量中性"的按日版本，无需标定 λ。
        # （λ 割平面版 P2_TERM=lam 是退化的：只要 λ>0，日末恒灌满 10800，打靶无内点解。）
        for w in range(K):
            lo[SB0 + w * (m + 1) + m] = S
            hi[SB0 + w * (m + 1) + m] = S
    if soc_end is not None:          # 滚动执行的"跟踪目标"：末端 SOC 钉在日前计划轨迹上
        for w in range(K):
            lo[SB0 + w * (m + 1) + m] = soc_end
            hi[SB0 + w * (m + 1) + m] = soc_end
    if g_fix is not None:
        lo[G0:G0 + m] = g_fix
        hi[G0:G0 + m] = g_fix

    res = linprog(c_obj, A_eq=A_eq, b_eq=b_eq, A_ub=A_ub, b_ub=b_ub,
                  bounds=list(zip(lo, hi)), method="highs")
    if not res.success:
        if os.environ.get("LP_DEBUG"):
            print(f"    [LP] {res.status}: {res.message}  m={m} K={K} nv={nv} "
                  f"A_eq{ A_eq.shape} A_ub{A_ub.shape} nlo={len(lo)} nhi={len(hi)}")
        return None
    x = res.x
    per = []
    for w in range(K):
        per.append((x[CB0 + w * m:CB0 + (w + 1) * m],
                    x[DB0 + w * m:DB0 + (w + 1) * m],
                    x[EB0 + w * m:EB0 + (w + 1) * m],
                    x[SB0 + w * (m + 1) + m]))
    return x[G0:G0 + m], per


def exec_day(gd, Ld, Pd, S, lam, fc, splan=None):
    """执行一天。返回 (c, d, e, soc_end)。

    oracle：日内完美预见（用实测 (Ld,Pd) 解储能调度 LP）
    mpc   ：因果滚动 —— 每槽用 [0..t] 实测 + [t+1..] 预报 fc 解长度 MPC_H 的 LP，只执行当前槽；
            时域末端 SOC 跟踪日前计划轨迹 splan（不钉回"当前 SOC"，否则放电会被执行、
            而配套充电被实际富余削掉，电池单向漏空 —— 实测年末 SOC 掉到 1,212 kWh、总费 32.8M）。
    """
    if EXEC == "oracle":
        o = day_lp(Ld[None, :], Pd[None, :], S, lam, g_fix=gd)
        if o is None:
            raise RuntimeError(
                f"oracle 执行 LP 失败: S={S:.1f}  ΣĝΔt={(gd * DT).sum():.0f} kWh  "
                f"ĝmax={gd.max():.0f}  L−P max={(Ld - Pd).max():.0f}")
        c, d, e, send = o[1][0]
        return c, d, e, send
    # mpc：每 MPC_STEP 槽重解一次，槽间沿用上一次计划的对应项（因果滚动）
    step = max(1, int(os.environ.get("MPC_STEP", 6)))
    mode = os.environ.get("MPC_MODE", "track")
    c_all = np.zeros(N); d_all = np.zeros(N); e_all = np.zeros(N)
    plan_c = np.zeros(N); plan_d = np.zeros(N)
    soc = S
    for t in range(N):
        if t % step == 0:
            if mode == "remain":
                # 时域 = 当天剩余全部槽；末端 SOC 钉回【当日起点】S（日能量中性）。
                # 这是修正版：不跟踪日前计划轨迹（轨迹随 K 增大而偏离实际），
                # 也不钉回"当前 SOC"（会导致电池单向漏空）。
                n = N - t
                Lf = np.concatenate([Ld[t:t + 1], fc[0][t + 1:N]])
                Pf = np.concatenate([Pd[t:t + 1], fc[1][t + 1:N]])
                tgt = float(S)
            else:
                n = min(MPC_H, N - t)
                Lf = np.concatenate([Ld[t:t + 1], fc[0][t + 1:t + n]])
                Pf = np.concatenate([Pd[t:t + 1], fc[1][t + 1:t + n]])
                tgt = None if splan is None else float(splan[t + n])
            o = day_lp(Lf[None, :], Pf[None, :], soc, lam, nslots=n,
                       g_fix=gd[t:t + n], pseq=price_day[t:t + n], soc_end=tgt)
            if o is None:                       # 末端目标过紧 → 退回不跟踪
                o = day_lp(Lf[None, :], Pf[None, :], soc, lam, nslots=n,
                           g_fix=gd[t:t + n], pseq=price_day[t:t + n])
            if o is not None:
                plan_c[t:t + n] = o[1][0][0]
                plan_d[t:t + n] = o[1][0][1]
        ct, dt_ = plan_c[t], plan_d[t]
        dmax = max(0.0, (soc - SOC_MIN) * ETA / DT)
        dt_ = min(dt_, dmax)
        cmax = max(0.0, (SOC_MAX - soc) / (ETA * DT))
        ct = min(ct, max(0.0, Pd[t] + gd[t] + dt_ - Ld[t]), cmax)
        et = max(0.0, Ld[t] - gd[t] - Pd[t] - dt_)
        c_all[t], d_all[t], e_all[t] = ct, dt_, et
        soc += (ETA * ct - dt_ / ETA) * DT
    return c_all, d_all, e_all, soc


def roll_year(lam, verbose=False):
    S = SOC0
    tp = te = tk = 0.0
    g_all = np.zeros(NDAYS * N); d_all = np.zeros(NDAYS * N); c_all = np.zeros(NDAYS * N)
    for d in range(NDAYS):
        pidx = peers[d] if peers[d] else [d]
        o = day_lp(load[pidx], pv[pidx], S, lam)
        if o is None:
            return None
        gd, per = o
        # 日前计划 SOC 轨迹（情景均值，长度 m+1）—— 滚动执行的跟踪目标
        splan = np.mean([S + np.concatenate([[0.0], np.cumsum(
            ETA * pw[0] * DT - pw[1] * DT / ETA)]) for pw in per], axis=0)
        if EXEC == "oracle":
            fc = None
        else:                       # 因果预报 = 同伴情景均值
            fc = (load[pidx].mean(0), pv[pidx].mean(0))
        c, dd, e, S = exec_day(gd, load[d], pv[d], S, lam, fc, splan)
        if d >= REPORT:
            tp += (price_day * gd * DT).sum()
            te += (5 * price_day * e * DT).sum()
            tk += (e * DT).sum()
        g_all[d * N:(d + 1) * N] = gd
        d_all[d * N:(d + 1) * N] = dd
        c_all[d * N:(d + 1) * N] = c
    return dict(total=tp + te, plan=tp, emerg=te, em_kwh=tk, S_end=S,
                g=g_all, d=d_all, c=c_all)


if __name__ == "__main__":
    print("=" * 96)
    print(f"问题 2 新模型：日前只承诺 ĝ，储能降为二阶段追索"
          f"（执行 EXEC={EXEC}，终端 {TERM}）")
    print("=" * 96)
    t0 = time.time()
    if TERM == "neutral":
        r = roll_year(0.0)
        lam = None
        print(f"[计时] 全年滚动一趟 {(time.time() - t0) / 60:.1f} min")
    else:
        r = roll_year(0.0)
        print(f"[计时] 一趟 {(time.time() - t0) / 60:.1f} min  总费 {r['total']:,.0f}  "
              f"年末SOC {r['S_end']:,.0f}")
        lo, hi = 0.0, 6.0
        for _ in range(int(os.environ.get("BISECT", 12))):
            mid = 0.5 * (lo + hi)
            r = roll_year(mid)
            if r is None:
                print("  ! 打靶失败")
                break
            print(f"  λ={mid:6.3f}  总费 {r['total']:>13,.0f}  紧急 {r['em_kwh']:>9,.0f} kWh"
                  f"  年末SOC {r['S_end']:>9,.0f}")
            if r["S_end"] > SOC0:
                lo = mid
            else:
                hi = mid
        lam = 0.5 * (lo + hi)
        r = roll_year(lam)
        print(f"标定 λ* = {lam:.4f} 元/kWh")
    if r is None:
        sys.exit("全年滚动失败")
    print("-" * 96)
    print(f"  计划购电费 {r['plan']:>13,.0f} 元")
    print(f"  紧急购电费 {r['emerg']:>13,.0f} 元  ({r['em_kwh']:,.0f} kWh)")
    print(f"  总费       {r['total']:>13,.0f} 元      年末 SOC {r['S_end']:,.1f}")
    print("  参照：完美预见 12,229,461 ｜ 可交付开环 γ=1 ｜ 现交付 result2 照抄 13,832,465（不可能）")
    if os.environ.get("SAVE_NPZ"):
        np.savez(os.environ["SAVE_NPZ"], g=r["g"], d=r["d"], c=r["c"],
                 lam=(-1.0 if lam is None else lam))
        print(f"  [dump] → {os.environ['SAVE_NPZ']}")
