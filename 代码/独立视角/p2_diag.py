# -*- coding: utf-8 -*-
"""诊断：为什么"日能量中性"的执行器会让 SOC 一路漏到下限？

逐日打印：缺口、ĝ 总量、计划充/放、实际充/放、紧急购电、SOC 起止、
以及"末端钉回当日起点"这个 LP 目标是否可行（不可行时会静默回退）。
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from p2_recourse import (day_lp, price_day, load, pv,
                         DT, ETA, P_MAX, SOC_MIN, SOC_MAX, SOC0, N, REPORT)

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

ND = int(os.environ.get("P2_DAYS", 10))
STEP = int(os.environ.get("P2_STEP", 24))
LAM = float(os.environ.get("P2_LAM", 0.0))      # 末端 SOC 的影子价值（元/kWh）
TAU = float(os.environ.get("P2_TAU", 0.8))


def hist_days(d, cap=8):
    same = [d - 7 * k for k in range(1, 60) if d - 7 * k >= 0]
    return same[:cap] if same else (list(range(d))[-cap:] or [d])


def rollout_diag(gd, Ld, Pd, S, fc, step=STEP):
    c_all = np.zeros(N); d_all = np.zeros(N); e_all = np.zeros(N)
    plan_c = np.zeros(N); plan_d = np.zeros(N)
    nfail = 0
    soc = S
    for t in range(N):
        if t % step == 0:
            n = N - t
            Lf = np.concatenate([Ld[t:t + 1], fc[0][t + 1:N]])
            Pf = np.concatenate([Pd[t:t + 1], fc[1][t + 1:N]])
            o = day_lp(Lf[None, :], Pf[None, :], soc, LAM, nslots=n,
                       g_fix=gd[t:t + n], pseq=price_day[t:t + n])
            if o is None:
                nfail += 1
            if o is not None:
                plan_c[t:t + n] = o[1][0][0]
                plan_d[t:t + n] = o[1][0][1]
        ct, dt_ = plan_c[t], plan_d[t]
        dt_ = min(dt_, max(0.0, (soc - SOC_MIN) * ETA / DT))
        ct = min(ct, max(0.0, Pd[t] + gd[t] + dt_ - Ld[t]),
                 max(0.0, (SOC_MAX - soc) / (ETA * DT)))
        et = max(0.0, Ld[t] - gd[t] - Pd[t] - dt_)
        c_all[t], d_all[t], e_all[t] = ct, dt_, et
        soc += (ETA * ct - dt_ / ETA) * DT
    return c_all, d_all, e_all, soc, plan_c, plan_d, nfail


print(f"电价剖面：min {price_day.min():.0f}  均值 {price_day.mean():.0f}  "
      f"max {price_day.max():.0f}  峰谷比 {price_day.max() / max(price_day.min(), 1e-9):.3f}")
print(f"       （储能套利需要峰谷比 > 1/0.81 = {1 / 0.81:.3f} 才划算，"
      f"削紧急购电需要 > 1/(0.81*5) = {1 / (0.81 * 5):.3f}）")
print(f"逐时电价：{np.array2string(price_day, precision=2, max_line_width=200)}")
print("-" * 110)

S = SOC0
print(f"{'日':>3} {'缺口kWh':>9} {'ĝkWh':>9} {'计划充':>8} {'实际充':>8} "
      f"{'计划放':>8} {'实际放':>8} {'紧急kWh':>9} {'弃放':>7} {'SOC起':>8} {'SOC止':>8} {'回退':>4}")
for d in range(ND):
    hd = hist_days(d)
    fc = (load[hd].mean(0), pv[hd].mean(0))
    gd = np.maximum(0.0, fc[0] - fc[1])
    for _ in range(2):
        D = np.empty((len(hd), N))
        for w, wd in enumerate(hd):
            cw, dw, _, _, _, _, _ = rollout_diag(gd, load[wd], pv[wd], S, fc)
            D[w] = load[wd] + cw - pv[wd] - dw
        gd = np.clip(np.quantile(D, TAU, axis=0), 0.0, P_MAX)
    S0d = S
    c, dd, e, S, pc, pd_, nfail = rollout_diag(gd, load[d], pv[d], S, fc)
    gap = float((load[d] - pv[d]).sum()) * DT
    print(f"{d:>3} {gap:>9,.0f} {gd.sum() * DT:>9,.0f} {pc.sum() * DT:>8,.0f} "
          f"{c.sum() * DT:>8,.0f} {pd_.sum() * DT:>8,.0f} {dd.sum() * DT:>8,.0f} "
          f"{e.sum() * DT:>9,.0f} {max(0.0, pd_.sum() - dd.sum()) * DT:>7,.0f} "
          f"{S0d:>8,.0f} {S:>8,.0f} {nfail:>4}")
