# -*- coding: utf-8 -*-
"""
问题 2：每天电价相同、负荷与光伏随时间变化，0:00 制定当天计划购电策略。

建模（已与团队确认）：
  * 完美预见：0:00 制定计划时已知当天实际负荷/光伏（附件2），故"供电 < 负载"永不发生，
    紧急购电恒为 0（购电功率 g_t 无上界，总能补足负荷）。
  * 储能跨日连续：初始 6000 kWh（2025-1-1 0:00），SOC 逐区间连续传递，年末回到 6000 kWh
    （全年能量中性，避免边界效应）。
  * 目标：最小化全年购电费 = Σ price_t · g_t · Δt。

线性规划（全年 365 天 × 144 区间 = 52560 个区间）：
  决策变量（每区间 t）：g_t≥0 购电、c_t∈[0,5000] 充电、d_t∈[0,5000] 放电、s_t≥0 弃光、SOC_t∈[1200,10800]
  目标：min Σ price_t·g_t·Δt
  约束：功率平衡 g_t + P_t + d_t = L_t + c_t + s_t
        SOC 递推  SOC_{t+1} = SOC_t + 0.9·c_t·Δt − d_t·Δt/0.9
        SOC 边界  SOC_0 = SOC_T = 6000，其余 ∈[1200,10800]
"""
import os
import datetime as dt
import numpy as np
import pandas as pd
from scipy.optimize import linprog
from scipy import sparse
import openpyxl

# ---------------- 参数 ----------------
DT = 1.0 / 6.0        # 10 分钟 = 1/6 小时
ETA = 0.9             # 充放电效率（各 9 折）
P_MAX = 5000.0        # 最大充放电功率 kW
SOC_MIN = 1200.0      # 储电量下限 kWh
SOC_MAX = 10800.0     # 储电量上限 kWh
SOC0 = 6000.0         # 初始 / 年末储电量 kWh
N = 144               # 每天 10 分钟区间数
NDAYS = 365           # 2025 年天数
T = N * NDAYS         # 全年区间总数

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # 项目根目录

# ---------------- 读数据 ----------------
# 附件1：单日 144 个电价（每天相同）
df1 = pd.read_excel(os.path.join(BASE, "附件", "附件1.xlsx"))
price_day = df1.iloc[:, 1].to_numpy(float)          # (144,) 元/kWh
assert len(price_day) == N

# 附件2：全年实际负荷 / 光伏 (365, 144)
dfL = pd.read_excel(os.path.join(BASE, "附件", "附件2.xlsx"), sheet_name="小区负载")
dfP = pd.read_excel(os.path.join(BASE, "附件", "附件2.xlsx"), sheet_name="光伏发电实际功率")
load = dfL.iloc[:, 1:1 + N].to_numpy(float)         # (365, 144)
pv = dfP.iloc[:, 1:1 + N].to_numpy(float)
assert load.shape == (NDAYS, N) and pv.shape == (NDAYS, N)

price = np.tile(price_day, NDAYS)                   # (T,) 电价，按天周期重复
load_flat = load.ravel()
pv_flat = pv.ravel()

# ---------------- 变量索引 ----------------
# 0..T-1     -> g
# T..2T-1    -> c
# 2T..3T-1   -> d
# 3T..4T-1   -> s
# 4T..4T+N   -> SOC（共 T+1 个，SOC[t] 为区间 t 起始储电量）
G0, C0, D0, S0, SOC0_idx = 0, T, 2 * T, 3 * T, 4 * T
n_vars = 5 * T + 1

# ---------------- 目标：只对购电功率计费 ----------------
c_obj = np.zeros(n_vars)
c_obj[G0:G0 + T] = price

# ---------------- 等式约束（稀疏） ----------------
# 前 T 行功率平衡，后 T 行 SOC 递推，共 2T 行
t = np.arange(T)
rows = np.concatenate([
    t,                # g（功率平衡）
    t,                # c（功率平衡）
    t,                # d（功率平衡）
    t,                # s（功率平衡）
    T + t,            # SOC_{t+1}（递推）
    T + t,            # SOC_t（递推）
    T + t,            # c（递推）
    T + t,            # d（递推）
])
cols = np.concatenate([
    G0 + t,           # g
    C0 + t,           # c
    D0 + t,           # d
    S0 + t,           # s
    SOC0_idx + t + 1, # SOC_{t+1}
    SOC0_idx + t,     # SOC_t
    C0 + t,           # c
    D0 + t,           # d
])
data = np.concatenate([
    np.ones(T),                 # g : +1
    -np.ones(T),                # c : -1（充电消耗电）
    np.ones(T),                 # d : +1（放电供给）
    -np.ones(T),                # s : -1（弃光）
    np.ones(T),                 # SOC_{t+1} : +1
    -np.ones(T),                # SOC_t : -1
    -ETA * DT * np.ones(T),     # c : -0.9Δt
    (DT / ETA) * np.ones(T),    # d : +Δt/0.9
])
A_eq = sparse.coo_matrix((data, (rows, cols)), shape=(2 * T, n_vars)).tocsr()

b_eq = np.concatenate([load_flat - pv_flat, np.zeros(T)])

# ---------------- 变量上下界 ----------------
bounds = []
bounds += [(0.0, None)] * T           # g ≥ 0
bounds += [(0.0, P_MAX)] * T          # 0 ≤ c ≤ 5000
bounds += [(0.0, P_MAX)] * T          # 0 ≤ d ≤ 5000
bounds += [(0.0, None)] * T           # s ≥ 0
bounds.append((SOC0, SOC0))           # SOC_0 = 6000
bounds += [(SOC_MIN, SOC_MAX)] * (T - 1)   # 1200 ≤ SOC_t ≤ 10800
bounds.append((SOC0, SOC0))           # SOC_T = 6000
assert len(bounds) == n_vars

# ---------------- 求解 ----------------
print("变量数:", n_vars, " 等式约束数:", 2 * T)
res = linprog(c_obj, A_eq=A_eq, b_eq=b_eq, bounds=bounds, method="highs")
assert res.success, f"LP 求解失败: {res.message}"

x = res.x
g = x[G0:G0 + T]
c = x[C0:C0 + T]
d = x[D0:D0 + T]
s = x[S0:S0 + T]
soc = x[SOC0_idx:SOC0_idx + T + 1]

# ---------------- 能量（kWh） ----------------
purchase = g * DT           # 每区间购电量 kWh
charge = c * DT
discharge = d * DT
spill = s * DT
total_cost = float((price * g * DT).sum())

# ---------------- 自检 ----------------
balance_resid = np.abs(g + pv_flat + d - load_flat - c - s).max()
total_purchase = purchase.sum()
total_charge = charge.sum()
total_discharge = discharge.sum()
total_spill = spill.sum()
total_load = (load_flat * DT).sum()
total_pv = (pv_flat * DT).sum()
print("=" * 62)
print("问题 2 求解结果自检")
print("=" * 62)
print(f"LP 状态              : {res.message}")
print(f"目标值(全年购电费)   : {total_cost:.2f} 元")
print(f"功率平衡最大残差      : {balance_resid:.2e} kW  (应≈0)")
print(f"SOC 范围             : [{soc.min():.4f}, {soc.max():.4f}] kWh  (应∈[1200,10800])")
print(f"SOC_0 / SOC_T        : {soc[0]:.4f} / {soc[-1]:.4f} kWh  (应=6000)")
print(f"全年购电量           : {total_purchase:.2f} kWh")
print(f"全年充电量           : {total_charge:.2f} kWh")
print(f"全年放电量           : {total_discharge:.2f} kWh")
print(f"全年弃光量           : {total_spill:.2f} kWh")
print(f"全年负载总能量       : {total_load:.2f} kWh")
print(f"全年光伏总能量       : {total_pv:.2f} kWh")
print(f"效率自检 放电/充电    : {total_discharge / total_charge:.6f} (应=0.81)")
# 紧急购电 = 0 的验证：功率平衡保证 g+pv+d = load+c+s ≥ load，故供电恒≥负载
print(f"紧急购电             : 0 kWh（供电恒≥负载，完美预见下无需紧急购电）")

# ---------------- 按天重塑 ----------------
purchase_day = purchase.reshape(NDAYS, N)      # (365, 144)
charge_day = charge.reshape(NDAYS, N)
discharge_day = discharge.reshape(NDAYS, N)
spill_day = spill.reshape(NDAYS, N)
soc_day = soc[:-1].reshape(NDAYS, N)           # 每天 0:00..23:50 起始 SOC（144个）
soc_day_end = soc[1:].reshape(NDAYS, N)        # 每天 0:10..24:00 起始 SOC
soc_at_midnight = soc[::N]                     # 每天 0:00 SOC（365个）

# 指定日期
special_dates = [dt.date(2025, 3, 20), dt.date(2025, 6, 21),
                 dt.date(2025, 9, 23), dt.date(2025, 12, 21)]
date0 = dt.date(2025, 1, 1)
special_idx = [(d - date0).days for d in special_dates]

# 表1 指定时间段索引（与问题1一致）
win_idx = {"10:00-10:10": 60, "12:00-12:10": 72, "14:00-14:10": 84,
           "16:00-16:10": 96, "18:00-18:10": 108, "20:00-20:10": 120}

blocks = [("0:00-4:00", 0, 24), ("4:00-8:00", 24, 48), ("8:00-12:00", 48, 72),
          ("12:00-16:00", 72, 96), ("16:00-20:00", 96, 120), ("20:00-24:00", 120, 144)]

print("\n" + "=" * 62)
print("表1/表2/表3 指定日期结果")
print("=" * 62)
for di in special_idx:
    d = (date0 + dt.timedelta(days=di)).strftime("%Y.%m.%d")
    daily_purchase = purchase_day[di].sum()
    daily_cost = float((price_day * purchase_day[di]).sum())
    print(f"\n【{d}】 全天购电量 {daily_purchase:.2f} kWh  全天购电费 {daily_cost:.2f} 元")
    print("  表1 指定时间段购电量(kWh):", "  ".join(
        f"{w}={purchase_day[di][i]:.2f}" for w, i in win_idx.items()))
    for name, a, b in blocks:
        print(f"  表2 {name}: 充电 {charge_day[di][a:b].sum():.2f}  放电 {discharge_day[di][a:b].sum():.2f}")
    print(f"  表2 0:00储电量 {soc_at_midnight[di]:.2f} kWh  24:00储电量 {soc_at_midnight[di + 1]:.2f} kWh")
    print(f"  表3 紧急购电量 0.00 kWh")

# ---------------- 写 result2.xlsx ----------------
template = os.path.join(BASE, "附件", "附件5", "result2.xlsx")
out_path = os.path.join(BASE, "结果", "result2.xlsx")
os.makedirs(os.path.dirname(out_path), exist_ok=True)
wb = openpyxl.load_workbook(template)

report_start = 31          # 2025-2-1 的 day index
report_days = range(report_start, NDAYS)   # 2/1 .. 12/31 共 334 天
n_report = NDAYS - report_start

# 「计划购电量」：模板已预置 335 行（表头 + 334 天日期），填值即可
ws_p = wb["计划购电量"]
for j, di in enumerate(report_days):
    row = j + 2
    # 144 个时间列：与问题1相同，循环左移10分钟 result[k] = p[(k+1)%144]
    for k in range(N):
        ws_p.cell(row=row, column=2 + k).value = round(float(purchase_day[di][(k + 1) % N]), 4)
    ws_p.cell(row=row, column=2 + N).value = round(float(purchase_day[di].sum()), 4)      # 全天购电量
    ws_p.cell(row=row, column=3 + N).value = round(float((price_day * purchase_day[di]).sum()), 4)  # 全天购电费

# 「充放电量」：重建为 334 天 × 6 块
ws_c = wb["充放电量"]
ws_c.delete_rows(2, ws_c.max_row - 1)
for j, di in enumerate(report_days):
    base = j * 6 + 2
    date_val = date0 + dt.timedelta(days=di)
    for bj, (name, a, b) in enumerate(blocks):
        r = base + bj
        ws_c.cell(row=r, column=1).value = date_val if bj == 0 else None
        ws_c.cell(row=r, column=2).value = name
        ws_c.cell(row=r, column=3).value = round(float(charge_day[di][a:b].sum()), 4)
        ws_c.cell(row=r, column=4).value = round(float(discharge_day[di][a:b].sum()), 4)
    # 0:00 / 24:00 储电量（时刻列=第5列，储电量列=第6列）
    ws_c.cell(row=base, column=5).value = "0:00"
    ws_c.cell(row=base, column=6).value = round(float(soc_at_midnight[di]), 4)
    ws_c.cell(row=base + 1, column=5).value = "24:00"
    ws_c.cell(row=base + 1, column=6).value = round(float(soc_at_midnight[di + 1]), 4)

# 「紧急购电量」：紧急购电恒为 0，每天一行（日期 + 购电量 0）
ws_e = wb["紧急购电量"]
ws_e.delete_rows(2, ws_e.max_row - 1)
for j, di in enumerate(report_days):
    r = j + 2
    ws_e.cell(row=r, column=1).value = date0 + dt.timedelta(days=di)
    ws_e.cell(row=r, column=3).value = 0.0

wb.save(out_path)
print(f"\n结果已写入: {out_path}")
