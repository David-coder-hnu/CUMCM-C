# -*- coding: utf-8 -*-
"""问题 3 诊断：为什么信息更多、惩罚更低，却没有比问题 2 拉开优势？
本脚本只做【数据分析】，不跑大 LP。输出：
  ① 年度能量口径
  ② 负荷/光伏预测误差随预报时距的变化（10min 分辨率）
  ③ 调整后残余误差 → 紧急购电的理论下限
"""
import os
import numpy as np
import pandas as pd

DT = 1.0 / 6.0
N = 144
NDAYS = 365
REPORT = 31
K_PEERS = 4
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

df1 = pd.read_excel(os.path.join(BASE, "附件", "附件1.xlsx"))
price_day = df1.iloc[:, 1].to_numpy(float)
dfL = pd.read_excel(os.path.join(BASE, "附件", "附件2.xlsx"), sheet_name="小区负载")
dfP = pd.read_excel(os.path.join(BASE, "附件", "附件2.xlsx"), sheet_name="光伏发电实际功率")
load = dfL.iloc[:, 1:1 + N].to_numpy(float)
pv = dfP.iloc[:, 1:1 + N].to_numpy(float)
fc3 = pd.read_excel(os.path.join(BASE, "附件", "附件3.xlsx"), header=None) \
        .iloc[1:, 2:].to_numpy(float).reshape(NDAYS, 4, 24)

win = np.zeros(NDAYS, dtype=bool); win[REPORT:] = True
print("=" * 78)
print("① 年度能量口径（统计窗口 2/1–12/31）")
print("=" * 78)
L_e = (load[win] * DT).sum(); P_e = (pv[win] * DT).sum()
print(f"负荷总电量        : {L_e:,.0f} kWh")
print(f"光伏总电量        : {P_e:,.0f} kWh   (占负荷 {P_e/L_e*100:.1f}%)")
print(f"净负荷电量        : {L_e - P_e:,.0f} kWh")
print(f"电价 min/max/mean : {price_day.min():.4f} / {price_day.max():.4f} / {price_day.mean():.4f} 元/kWh")
print(f"净负荷若全按均价买 : {(L_e-P_e)*price_day.mean():,.0f} 元（粗估基准）")
print(f"负荷 kW  min/mean/max: {load[win].min():.0f} / {load[win].mean():.0f} / {load[win].max():.0f}")
print(f"光伏 kW  min/mean/max: {pv[win].min():.0f} / {pv[win].mean():.0f} / {pv[win].max():.0f}")

# ---------------- 负荷基础预测：同星期几最近 4 周 ----------------
L_base = np.empty_like(load)
for d in range(NDAYS):
    idx = [d - 7 * k for k in range(1, K_PEERS + 1) if d - 7 * k >= 0]
    L_base[d] = load[idx].mean(axis=0) if idx else load.mean(axis=0)

# ---------------- 光伏预报：逐小时 → 10min 线性插值 ----------------
W = np.zeros((N, 25))
for k in range(N):
    t = (k + 1) / 6.0
    lo = int(np.floor(t)); hi = min(int(np.ceil(t)), 24)
    if lo == hi:
        W[k, lo] = 1.0
    else:
        frac = t - lo
        W[k, lo] = 1.0 - frac
        W[k, hi] = frac


def pv_fc(d, s_idx, s_hour):
    H = np.zeros(25)
    if s_hour > 0:
        H[s_hour] = pv[d, 6 * s_hour]
    for h in range(s_hour + 1, 25):
        H[h] = fc3[d, s_idx, h - s_hour - 1]
    return H @ W.T


print()
print("=" * 78)
print("② 预测误差（10min 分辨率，窗口内 RMSE / 偏差，单位 kW）")
print("=" * 78)
print(f"{'预测对象 / 时距':<34}{'RMSE':>10}{'偏差':>10}{'MAE':>10}")
print("-" * 78)


def stat(name, err):
    e = err[win]
    print(f"{name:<34}{np.sqrt((e**2).mean()):>10.1f}{e.mean():>10.1f}{np.abs(e).mean():>10.1f}")


stat("光伏 0:00 预报(1-24h)", np.stack([pv_fc(d, 0, 0) for d in range(NDAYS)]) - pv)
stat("光伏 6:00 预报", np.stack([pv_fc(d, 1, 6) for d in range(NDAYS)]) - pv)
stat("光伏 12:00 预报", np.stack([pv_fc(d, 2, 12) for d in range(NDAYS)]) - pv)
stat("光伏 18:00 预报", np.stack([pv_fc(d, 3, 18) for d in range(NDAYS)]) - pv)
stat("负荷 同星期几4周(0:00)", L_base - load)
stat("光伏 历史近7天均值(问题2口径)",
     np.stack([pv[max(0, d - 7):d].mean(axis=0) if d else pv.mean(axis=0) for d in range(NDAYS)]) - pv)

print()
print("=" * 78)
print("③ 调整后的残余净负荷误差 → 紧急购电来源（逐 6 小时块）")
print("=" * 78)
# 问题3 的调整口径：块首用"已发生实际/预测比"修正 L_base，光伏用该时刻发布的预报
resid_blocks = []
for s_hour, s_idx in [(6, 1), (12, 2), (18, 3)]:
    si = s_hour * 6
    for d in range(NDAYS):
        if not win[d]:
            continue
        P_f = pv_fc(d, s_idx, s_hour)[si:]
        r = load[d, :si].sum() / L_base[d, :si].sum()
        L_f = r * L_base[d, si:]
        err = (load[d, si:] - L_f) - (pv[d, si:] - P_f)   # 正=预测偏低=紧急购电
        resid_blocks.append(err)
resid_blocks = np.concatenate(resid_blocks)
pos = np.maximum(0.0, resid_blocks)
print(f"残余净负荷误差 RMSE : {np.sqrt((resid_blocks**2).mean()):,.0f} kW")
print(f"残余误差 偏差(均值) : {resid_blocks.mean():,.0f} kW  (负=系统性多买)")
print(f"单侧(>0)均值        : {pos.mean():,.0f} kW")
print(f"按 1/6 小时折算     : 全年正偏差电量 ≈ {pos.sum()*DT:,.0f} kWh")
# 若不做任何"正偏置"，紧急购电下限
for q in [0.0, 0.5, 0.8, 1.0]:
    thr = np.quantile(resid_blocks, q)
    short = np.maximum(0.0, resid_blocks - thr)
    print(f"  正偏置到 {q:.0%} 分位 → 残余紧急购电 ≈ {short.sum()*DT:,.0f} kWh")

print()
print("=" * 78)
print("④ 两个口径下的“信息价值”上界")
print("=" * 78)
print("问题 2 信息集 = 只用历史（无附件3）；问题 3 信息集 = 附件3 光伏预报 + 日内修正")
print(f"PV 预报相对“历史近7天均值”的 RMSE 改善：")
e2 = np.stack([pv[max(0, d - 7):d].mean(axis=0) if d else pv.mean(axis=0) for d in range(NDAYS)]) - pv
e3 = np.stack([pv_fc(d, 0, 0) for d in range(NDAYS)]) - pv
print(f"   问题2 口径(PV统计预测) RMSE = {np.sqrt(((e2[win])**2).mean()):.1f} kW")
print(f"   问题3 口径(附件3 0:00) RMSE = {np.sqrt(((e3[win])**2).mean()):.1f} kW")
print(f"   负荷预测(两问题相同)   RMSE = {np.sqrt((((L_base-load)[win])**2).mean()):.1f} kW  ← 主导项")
