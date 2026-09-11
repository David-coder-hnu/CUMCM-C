# -*- coding: utf-8 -*-
"""诊断二：预报质量逐时距对比（只比较各发布时刻真正可用的窗口）。"""
import os
import numpy as np
import pandas as pd

N, NDAYS, REPORT = 144, 365, 31
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
dfP = pd.read_excel(os.path.join(BASE, "附件", "附件2.xlsx"), sheet_name="光伏发电实际功率")
pv = dfP.iloc[:, 1:1 + N].to_numpy(float)
load = pd.read_excel(os.path.join(BASE, "附件", "附件2.xlsx"), sheet_name="小区负载") \
         .iloc[:, 1:1 + N].to_numpy(float)
fc3 = pd.read_excel(os.path.join(BASE, "附件", "附件3.xlsx"), header=None) \
        .iloc[1:, 2:].to_numpy(float).reshape(NDAYS, 4, 24)
win = np.zeros(NDAYS, bool); win[REPORT:] = True

# 逐小时角度对比：附件3 的 k 小时前预报 vs 同期"历史近7天均值"persistence
print("=" * 84)
print("附件3 光伏预报 vs 问题2 的统计预测（历史近7天均值）—— 逐小时，窗口 2/1-12/31")
print("=" * 84)
print(f"{'预报时距':<12}{'附件3 RMSE':>14}{'persistence RMSE':>20}{'附件3 MAE':>12}{'persistence MAE':>18}")
print("-" * 84)
for lead in [1, 2, 3, 4, 5, 6, 12, 18, 24]:
    errs_f, errs_p = [], []
    for d in range(NDAYS):
        if not win[d]:
            continue
        # 该 lead 对应哪个发布块？取当日能给出该时距的最小发布索引
        for s_idx, s_hour in [(0, 0), (1, 6), (2, 12), (3, 18)]:
            h = s_hour + lead
            if h <= 24:
                f = fc3[d, s_idx, lead - 1]
                a = pv[d, min(6 * h, N - 1)]
                errs_f.append(f - a)
                break
        lo = max(0, d - 7)
        p = pv[lo:d].mean(axis=0) if lo < d else pv.mean(axis=0)
        a2 = pv[d, min(6 * (0 + lead) if lead <= 24 else N - 1, N - 1)]
        errs_p.append(p[min(6 * lead, N - 1)] - a2)
    ef, ep = np.array(errs_f), np.array(errs_p)
    print(f"{lead:>2} 小时后   {np.sqrt((ef**2).mean()):>14.1f}{np.sqrt((ep**2).mean()):>20.1f}"
          f"{np.abs(ef).mean():>12.1f}{np.abs(ep).mean():>18.1f}")

print()
print("=" * 84)
print("负荷预测 vs 光伏预测 的误差量级对比（窗口内，10min）")
print("=" * 84)
L_base = np.empty_like(load)
for d in range(NDAYS):
    idx = [d - 7 * k for k in range(1, 5) if d - 7 * k >= 0]
    L_base[d] = load[idx].mean(axis=0) if idx else load.mean(axis=0)
eL = (L_base - load)[win]
W = np.zeros((N, 25))
for k in range(N):
    t = (k + 1) / 6.0; lo = int(np.floor(t)); hi = min(int(np.ceil(t)), 24)
    if lo == hi: W[k, lo] = 1.0
    else: W[k, lo] = 1 - (t - lo); W[k, hi] = t - lo


def pv_fc(d, s_idx, s_hour):
    H = np.zeros(25)
    if s_hour > 0: H[s_hour] = pv[d, 6 * s_hour]
    for h in range(s_hour + 1, 25): H[h] = fc3[d, s_idx, h - s_hour - 1]
    return H @ W.T


P3_hat = np.stack([pv_fc(d, 0, 0) for d in range(NDAYS)])
P2_hat = np.stack([pv[max(0, d - 7):d].mean(axis=0) if d else pv.mean(axis=0) for d in range(NDAYS)])
for nm, e in [("负荷(同星期几4周)", eL), ("光伏·附件3 0:00", (P3_hat - pv)[win]),
              ("光伏·历史近7天(问题2)", (P2_hat - pv)[win])]:
    print(f"  {nm:<24} RMSE={np.sqrt((e**2).mean()):>8.1f} kW   偏差={e.mean():>8.1f}   "
          f"相对量级={np.sqrt((e**2).mean())/load[win].mean()*100:>5.1f}%(以负荷均值计)")
print()
print(f"  负荷均值 {load[win].mean():.0f} kW；净负荷(L-P)标准差 {((load-pv)[win]).std():.0f} kW")
