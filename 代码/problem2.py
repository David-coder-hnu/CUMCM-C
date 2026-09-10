# -*- coding: utf-8 -*-
"""
问题 2：每天电价相同、负荷与光伏随时间（逐日）变化；0:00 制定当天计划；紧急购电 5 倍价。

方案（已与团队确认，方案 B——预测式计划 + 紧急购电）：
  * 0:00 用"预测"负荷/光伏制定计划，实际（附件2）偏离预测的缺口 → 5 倍价紧急购电。
  * 最优预测（见 problem2_forecast_compare.py 对比）：
        负荷 = 同星期几（近 4 周同星期几平均）
        光伏 = 近 7 天平均
  * 储能跨日连续：初始 6000（2025-1-1 0:00）、年末回 6000（全年能量中性），SOC 自由漂移；
    问题 2 原文没有"0:00 与 24:00 储电量相同"约束（那是问题 1 的）。

模型：
  计划阶段：全年 365×144 区间连续 LP（用预测负荷/光伏），得计划购电 ĝ、充放电 ĉ/d̂、SOC。
  紧急购电：e_t = max(0, L_t^act + ĉ_t − ĝ_t − P_t^act − d̂_t)，费用 5×price_t。
  总购电费 = Σ price·ĝ + Σ 5·price·e。
"""
import os
import datetime as dt
import numpy as np
import pandas as pd
from scipy.optimize import linprog
from scipy import sparse
import openpyxl

# ---------------- 参数 ----------------
DT = 1.0 / 6.0
ETA = 0.9
P_MAX = 5000.0
SOC_MIN = 1200.0
SOC_MAX = 10800.0
SOC0 = 6000.0
N = 144
NDAYS = 365
T = N * NDAYS

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ---------------- 读数据 ----------------
df1 = pd.read_excel(os.path.join(BASE, "附件", "附件1.xlsx"))
price_day = df1.iloc[:, 1].to_numpy(float)                     # (144,) 每天相同电价
dfL = pd.read_excel(os.path.join(BASE, "附件", "附件2.xlsx"), sheet_name="小区负载")
dfP = pd.read_excel(os.path.join(BASE, "附件", "附件2.xlsx"), sheet_name="光伏发电实际功率")
load = dfL.iloc[:, 1:1 + N].to_numpy(float)                    # (365,144) 实际负荷
pv = dfP.iloc[:, 1:1 + N].to_numpy(float)                      # (365,144) 实际光伏

price = np.tile(price_day, NDAYS)                              # (T,) 电价（按天周期）
mean_load, mean_pv = load.mean(axis=0), pv.mean(axis=0)

# ---------------- 预测（0:00 之前的信息） ----------------
# 负荷：近 4 周同星期几平均
L_hat = np.empty_like(load)
for d in range(NDAYS):
    idx = [d - 7 * k for k in range(1, 5) if d - 7 * k >= 0]
    L_hat[d] = load[idx].mean(axis=0) if idx else mean_load
# 光伏：近 7 天平均
P_hat = np.empty_like(pv)
for d in range(NDAYS):
    lo = max(0, d - 7)
    P_hat[d] = pv[lo:d].mean(axis=0) if lo < d else mean_pv

# ---------------- 全年连续 LP（计划阶段） ----------------
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
b_eq = np.concatenate([L_hat.ravel() - P_hat.ravel(), np.zeros(T)])
bounds = ([(0, None)] * T + [(0, P_MAX)] * T + [(0, P_MAX)] * T + [(0, None)] * T
          + [(SOC0, SOC0)] + [(SOC_MIN, SOC_MAX)] * (T - 1) + [(SOC0, SOC0)])

res = linprog(c_obj, A_eq=A_eq, b_eq=b_eq, bounds=bounds, method="highs")
assert res.success, res.message
x = res.x
g = x[G0:G0 + T]           # 计划购电功率 kW
c = x[C0:C0 + T]           # 计划充电功率 kW
d = x[D0:D0 + T]           # 计划放电功率 kW
soc = x[S_idx:S_idx + T + 1]   # 储电量 kWh
s = x[S0:S0 + T]               # 弃光功率 kW

# ---------------- 紧急购电（实际 vs 计划） ----------------
e = np.maximum(0.0, load.ravel() + c - g - pv.ravel() - d)     # 紧急购电功率 kW

# ---------------- 能量（kWh） ----------------
purchase = g * DT
charge = c * DT
discharge = d * DT
emergency = e * DT

# ---------------- 自检 ----------------
# 计划阶段功率平衡残差（用预测值验证 g + P̂ + d = L̂ + c + s）
bal = np.abs(g + P_hat.ravel() + d - L_hat.ravel() - c - s).max()

REPORT = 31
win = np.zeros(T, dtype=bool); win[REPORT * N:] = True
rep_planned = (purchase)[win].sum()
rep_emerg = (emergency)[win].sum()
rep_cost_planned = (price * purchase)[win].sum()
rep_cost_emerg = (5 * price * emergency)[win].sum()
print("=" * 64)
print("问题 2 求解结果自检（统计窗口 2/1–12/31）")
print("=" * 64)
print(f"LP 状态              : {res.message}")
print(f"计划阶段功率平衡残差  : {bal:.2e} kW (应≈0)")
print(f"SOC 范围             : [{soc.min():.4f}, {soc.max():.4f}] kWh (应∈[1200,10800])")
print(f"SOC_0 / SOC_T        : {soc[0]:.4f} / {soc[-1]:.4f} kWh (应=6000)")
print(f"效率自检 放电/充电    : {discharge.sum() / charge.sum():.6f} (应=0.81)")
print(f"计划购电量(全年)     : {purchase.sum():,.0f} kWh")
print(f"紧急购电量(全年)     : {emergency.sum():,.0f} kWh")
print(f"  报告窗口 计划购电量 : {rep_planned:,.0f} kWh")
print(f"  报告窗口 紧急购电量 : {rep_emerg:,.0f} kWh")
print(f"  报告窗口 计划购电费 : {rep_cost_planned:,.0f} 元")
print(f"  报告窗口 紧急购电费 : {rep_cost_emerg:,.0f} 元")
print(f"  报告窗口 总购电费   : {rep_cost_planned + rep_cost_emerg:,.0f} 元")

# ---------------- 按天重塑 ----------------
g_day = g.reshape(NDAYS, N) * DT
c_day = c.reshape(NDAYS, N) * DT
d_day = d.reshape(NDAYS, N) * DT
e_day = e.reshape(NDAYS, N) * DT
soc_midnight = soc[::N]                                       # 每天 0:00 储电量

# ---------------- 表1/表2/表3 指定日期 ----------------
special_dates = [dt.date(2025, 3, 20), dt.date(2025, 6, 21),
                 dt.date(2025, 9, 23), dt.date(2025, 12, 21)]
date0 = dt.date(2025, 1, 1)
special_idx = [(d - date0).days for d in special_dates]
win_idx = {"10:00-10:10": 60, "12:00-12:10": 72, "14:00-14:10": 84,
           "16:00-16:10": 96, "18:00-18:10": 108, "20:00-20:10": 120}
blocks = [("0:00-4:00", 0, 24), ("4:00-8:00", 24, 48), ("8:00-12:00", 48, 72),
          ("12:00-16:00", 72, 96), ("16:00-20:00", 96, 120), ("20:00-24:00", 120, 144)]

print("\n" + "=" * 64)
print("表1/表2/表3 指定日期结果")
print("=" * 64)
for di in special_idx:
    dstr = (date0 + dt.timedelta(days=di)).strftime("%Y.%m.%d")
    pl = g_day[di].sum(); em = e_day[di].sum()
    cp = (price_day * g_day[di]).sum(); ce = (5 * price_day * e_day[di]).sum()
    print(f"\n【{dstr}】 计划购电量 {pl:.2f}  紧急购电量 {em:.2f}  全天购电费 {cp + ce:.2f} 元")
    print("  表1 购电量(kWh):", "  ".join(f"{w}={g_day[di][i]:.2f}" for w, i in win_idx.items()))
    for name, a, b in blocks:
        print(f"  表2 {name}: 充电 {c_day[di][a:b].sum():.2f}  放电 {d_day[di][a:b].sum():.2f}")
    print(f"  表2 0:00储电量 {soc_midnight[di]:.2f}  24:00储电量 {soc_midnight[di + 1]:.2f} kWh")
    print(f"  表3 紧急购电量 {em:.2f} kWh")

# ---------------- 写 result2.xlsx ----------------
def fmt_time(m):
    m = int(m)
    if m >= 1440: return "24:00"
    return f"{m // 60:02d}:{m % 60:02d}"

def emergency_segments(e_kwh):
    """把一天 144 个区间的紧急购电量(kWh)聚成连续时间段。返回 [(时间串, kWh), ...]"""
    segs = []
    i = 0
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

template = os.path.join(BASE, "附件", "附件5", "result2.xlsx")
out_path = os.path.join(BASE, "结果", "result2.xlsx")
os.makedirs(os.path.dirname(out_path), exist_ok=True)
wb = openpyxl.load_workbook(template)

report_days = range(REPORT, NDAYS)
n_report = NDAYS - REPORT

# 「计划购电量」：填 144 个计划购电量（循环左移10分钟）+ 全天购电量 + 全天购电费
ws_p = wb["计划购电量"]
for j, di in enumerate(report_days):
    row = j + 2
    for k in range(N):
        ws_p.cell(row=row, column=2 + k).value = round(float(g_day[di][(k + 1) % N]), 4)
    ws_p.cell(row=row, column=2 + N).value = round(float(g_day[di].sum()), 4)                    # 全天购电量(计划)
    ws_p.cell(row=row, column=3 + N).value = round(float((price_day * g_day[di]).sum()
                                                        + (5 * price_day * e_day[di]).sum()), 2)  # 全天购电费(含紧急)

# 「充放电量」：重建为 334 天 × 6 块 + 0:00/24:00 储电量
ws_c = wb["充放电量"]
ws_c.delete_rows(2, ws_c.max_row - 1)
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

# 「紧急购电量」：每天若干连续时间段（表4格式）
ws_e = wb["紧急购电量"]
ws_e.delete_rows(2, ws_e.max_row - 1)
r = 2
for j, di in enumerate(report_days):
    segs = emergency_segments(e_day[di])
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
