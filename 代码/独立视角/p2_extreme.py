# -*- coding: utf-8 -*-
"""问题 2 —— 推到极致：ĝ 对着【可执行策略】标定，储能用影子价格跨日管理。

本脚本是"把一阶段决策放进仿真回路标定"这条务实路线的实证。**结论：失败** ——
在同一个诚实账本下，可执行策略最好只有 19,443,989 元，比开环 γ=1 可交付计划
（15,187,755 元）贵 28%。瓶颈不在 ĝ 规则，在执行器的跨时段 SOC 管理
（标量末端影子价格 λ 呈 bang-bang，无法同时表达"留住电量"与"用掉电量"）。
详见 文档/问题2_求解归档.md §5。保留本脚本作为该负结果的证据。

────────────────────────────────────────────────────────────────────────
一、病根（本脚本前一版踩到的，与队伍的问题是同一类，只高一层）
    执行器把时域末端 SOC 钉回【当日起点】。这个约束是自指的：
    它让每一天都围绕"当天起点"做能量中性 —— 而当天起点本身已经被前一天拉低了。
    于是 SOC 只能单向棘轮下滑，掉到下限 1200 后再也回不来（实测：第 2 天到底，
    之后 363 天电池全程瘫痪，所有缺口靠紧急购电）。实测第 2 天"充电 2,898、
    放电 2,347，净 SOC 变化恰好 0" —— 电池在下限上原地空转。

    正确做法：末端 SOC 用**影子价格** λ（元/kWh）进目标函数，而不是硬约束。
    λ>0 时 LP 会主动为明天留电，低缺口日充、高缺口日放。实测 λ 从 0 提到 1，
    电池立刻恢复循环（SOC 1200↔10746），高缺口日紧急购电 3,826→3,516 kWh。

二、为什么 τ 不能直接取报童的 0.8
    经典报童：多买 1 kWh 损失 p，少买 1 kWh 多付 4p ⟹ 临界比 0.8。
    但**有储能时两侧代价都被储能削平了**：
        多买 → 存进电池，净代价 p − 0.9λ（λ 可取到使该项为负）
        少买 → 电池放电顶，净代价 5p − (放掉的那份 SOC 的价值)
    有效临界比 = Cn/(Cn+Co) 与 0.8 无关，且随 λ 移动。
    再叠加 §3(3) 的 K=4 陷阱（0.8 分位就是最大值），**τ 必须扫，不能推**。

三、本脚本扫描的两个旋钮
    λ  末端 SOC 影子价格（元/kWh）—— 储能的跨日管理强度
    τ  ĝ = Q_τ(D) 的分位 —— D = L + c − P − d，"要完全免紧急购电需买到多少"
    恒等式（自检）：在执行层限幅下  e_{ω,t} > 0  ⟺  D_{ω,t} > ĝ_t
    所以"实测紧急频率"必须等于 1−τ，否则标定没收敛。

四、情景集
    hist_days(d) = 该日之前的历史同星期几日（上限 KCAP）。队伍的做法是固定取 4 个，
    且第 0–6 天回退到**全年均值**（用了未来信息）。这里回退到**全部历史日**（因果）。

用法：
    python 代码/独立视角/p2_extreme.py
    P2_DAYS=60 P2_LAMS=1 P2_TAUS=0.8 python 代码/独立视角/p2_extreme.py   # 计时
"""
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import p2_recourse as R                      # noqa: E402
R.TERM = "lam"                               # 末端 SOC 走影子价格，不硬钉
from p2_recourse import (day_lp, price_day, load, pv,          # noqa: E402
                         DT, ETA, P_MAX, SOC_MIN, SOC_MAX, SOC0, N, NDAYS, REPORT)

STEP = int(os.environ.get("P2_STEP", 48))     # 滚动 MPC 重解周期（槽）
ITER = int(os.environ.get("P2_ITER", 1))      # 报童不动点迭代次数
KCAP = int(os.environ.get("P2_KCAP", 8))      # 情景集上限
NDAYS_RUN = int(os.environ.get("P2_DAYS", NDAYS))
LAMS = [float(x) for x in os.environ.get("P2_LAMS", "0,0.5,1,2,4").split(",")]
TAUS = [float(x) for x in os.environ.get("P2_TAUS", "0.6,0.7,0.8,0.9").split(",")]
WIN0 = min(REPORT, NDAYS_RUN)
GN_FILE = os.environ.get("P2_GN")            # 外部 ĝ 计划（npz），用于同执行器对比
GEXT = np.load(GN_FILE)["g"] if GN_FILE else None


def hist_days(d):
    """0:00 可得的情景集：历史同星期几日；不足则回退到全部历史日（因果，非全年均值）。"""
    same = [d - 7 * k for k in range(1, 60) if d - 7 * k >= 0]
    if same:
        return same[:KCAP]
    past = list(range(d))
    return past[-KCAP:] if past else [d]


def rollout(gd, Ld, Pd, S, fc, lam, step=STEP):
    """因果滚动 MPC 执行一天，返回 (c, d, e, soc_end, 计划放电量)。"""
    c_all = np.zeros(N); d_all = np.zeros(N); e_all = np.zeros(N)
    plan_c = np.zeros(N); plan_d = np.zeros(N)
    soc = S
    for t in range(N):
        if t % step == 0:
            n = N - t
            Lf = np.concatenate([Ld[t:t + 1], fc[0][t + 1:N]])
            Pf = np.concatenate([Pd[t:t + 1], fc[1][t + 1:N]])
            o = day_lp(Lf[None, :], Pf[None, :], soc, lam, nslots=n,
                       g_fix=gd[t:t + n], pseq=price_day[t:t + n])
            if o is None:
                Lf, Pf = Ld[t:t + 1], Pd[t:t + 1]      # 兜底：退化为只用实测
                o = day_lp(Lf[None, :], Pf[None, :], soc, lam, nslots=n,
                           g_fix=gd[t:t + n], pseq=price_day[t:t + n])
            if o is not None:
                plan_c[t:t + n] = o[1][0][0]
                plan_d[t:t + n] = o[1][0][1]
        ct, dt_ = plan_c[t], plan_d[t]
        dt_ = min(dt_, max(0.0, (soc - SOC_MIN) * ETA / DT))          # 放电受 SOC 下限限幅
        ct = min(ct, max(0.0, Pd[t] + gd[t] + dt_ - Ld[t]),           # 充电受实际富余限幅
                 max(0.0, (SOC_MAX - soc) / (ETA * DT)))
        et = max(0.0, Ld[t] - gd[t] - Pd[t] - dt_)
        c_all[t], d_all[t], e_all[t] = ct, dt_, et
        soc += (ETA * ct - dt_ / ETA) * DT
    return c_all, d_all, e_all, soc, float(plan_d.sum())


def run(lam, tau, rule="quant"):
    """(λ, τ) 下一次全年因果执行。返回汇总 dict。

    rule="quant"：ĝ_t = Q_τ(D)，D 由执行器在历史情景上跑出来（报童不动点）
    rule="sp"   ：ĝ 由【日前两阶段 SP】给出（储能作追索，日内 SOC 中性），再交执行器
    """
    S = SOC0
    plan = emerg = em_kwh = curtail = 0.0
    freqs, socs = [], []
    g_saved = np.zeros(NDAYS_RUN * N)
    for d in range(NDAYS_RUN):
        hd = hist_days(d)
        fc = (load[hd].mean(0), pv[hd].mean(0))       # 0:00 可得预报
        if rule == "file":
            if GEXT is None:
                sys.exit("P2_GN 未设置")
            gd = GEXT[d * N:(d + 1) * N].copy()
        elif rule == "sp":
            o = day_lp(load[hd], pv[hd], S, 0.0)
            if o is None:
                return None
            gd = o[0]
        else:
            gd = np.maximum(0.0, fc[0] - fc[1])
            for _ in range(ITER):                      # 报童不动点
                D = np.empty((len(hd), N))
                for w, wd in enumerate(hd):
                    c_w, d_w, _, _, _ = rollout(gd, load[wd], pv[wd], S, fc, lam)
                    D[w] = load[wd] + c_w - pv[wd] - d_w
                gd = np.clip(np.quantile(D, tau, axis=0), 0.0, P_MAX)
        c, dd, e, S, pd_sum = rollout(gd, load[d], pv[d], S, fc, lam)
        freqs.append(float((e > 1e-9).mean()))
        curtail += max(0.0, pd_sum - dd.sum())
        socs.append(S)
        if d >= WIN0:
            plan += (price_day * gd * DT).sum()
            emerg += (5.0 * price_day * e * DT).sum()
            em_kwh += (e * DT).sum()
        g_saved[d * N:(d + 1) * N] = gd
    return dict(total=plan + emerg, plan=plan, emerg=emerg, em_kwh=em_kwh,
                curtail=curtail, S_end=S, S_min=float(np.min(socs)),
                S_max=float(np.max(socs)), freq=float(np.mean(freqs)), g=g_saved)


if __name__ == "__main__":
    for _s in (sys.stdout, sys.stderr):
        if hasattr(_s, "reconfigure"):
            _s.reconfigure(encoding="utf-8", errors="replace")
    print("=" * 108)
    print("问题 2 推到极致：ĝ 对可执行 MPC 标定 + 储能跨日影子价格 λ")
    print(f"  KCAP={KCAP} 情景  不动点迭代 {ITER} 次  MPC 步长 {STEP} 槽  "
          f"{NDAYS_RUN} 天  费用窗口第 {WIN0 + 1}–{NDAYS_RUN} 天")
    print("=" * 108)
    t0 = time.time()
    grid = {}

    def show(tag, lam, tau, r):
        if r is None:
            print(f"  {tag:16s} λ={lam:>5.2f} τ={tau:>4.2f}   —— LP 不可行")
            return
        print(f"  {tag:16s} λ={lam:>5.2f} τ={tau:>4.2f}  "
              f"总 {r['total']:>13,.0f}  计划 {r['plan']:>13,.0f}  "
              f"紧急 {r['emerg']:>11,.0f} ({r['em_kwh']:>8,.0f} kWh)  "
              f"SOC止 {r['S_end']:>7,.0f} 最低 {r['S_min']:>7,.0f}  "
              f"弃放 {r['curtail']:>8,.0f}  [{time.time() - t0:.0f}s]")

    ONLY = os.environ.get("P2_RULES", "sp,quant,file").split(",")

    if "sp" in ONLY:
        print("【规则 A】ĝ 由日前两阶段 SP 给出（储能作追索），再交因果 MPC 执行")
        print("-" * 108)
        for lam in LAMS:
            r = run(lam, 0.0, rule="sp")
            grid[(lam, "sp")] = r
            show("日前SP ĝ", lam, 0.0, r)

    print("-" * 108)
    print("【规则 B】ĝ = Q_τ(D)（报童不动点，D 由执行器在历史情景上跑出）")
    print("-" * 108)
    if "quant" in ONLY:
        for lam in LAMS:
            for tau in TAUS:
                r = run(lam, tau, rule="quant")
                grid[(lam, tau)] = r
                show("Q_τ(D)", lam, tau, r)

    if GEXT is not None and "file" in ONLY:
        print("-" * 108)
        print(f"【规则 C】ĝ 取自外部计划 {GN_FILE}（同执行器、同窗口，检验执行器本身）")
        print("-" * 108)
        for lam in LAMS:
            r = run(lam, 0.0, rule="file")
            grid[(lam, "file")] = r
            show("外部 ĝ", lam, 0.0, r)

    print("-" * 108)
    live = {k: v for k, v in grid.items() if v is not None}
    best = min(live.values(), key=lambda r: r["total"])
    bk = min(live, key=lambda k: live[k]["total"])
    print(f"  最优配置 {bk}  →  可执行年费 {best['total']:,.0f} 元")
    print(f"    计划 {best['plan']:,.0f}  紧急 {best['emerg']:,.0f} "
          f"({best['em_kwh']:,.0f} kWh)  实测紧急频率 {best['freq']:.3f}")
    print(f"    年末 SOC {best['S_end']:,.0f}  全年 SOC 区间 "
          f"[{best['S_min']:,.0f}, {best['S_max']:,.0f}]  弃放电 {best['curtail']:,.0f} kWh")
    print("-" * 108)
    print("  哨兵：完美预见下界 12,229,461 元 —— 任何低于它的结果都是 bug")
    print("  参照：γ=1 可交付(诚实执行) 15,389,997–16,017,281 ｜ 追索+oracle 14,613,824")
    print("        追索+旧MPC(棘轮) 18,194,055 ｜ 点预测 17,062,165")
    print("        现交付 result2 13,832,465（低于自身计划下界，任何策略都做不到）")
    print(f"  [计时] {(time.time() - t0) / 60:.1f} min")
