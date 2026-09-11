# -*- coding: utf-8 -*-
"""
问题 1：每天电价与小区负载相同、光伏功率预测已知的确定性计划购电策略。

模型：线性规划（LP），最小化全天购电费。
决策变量（每 10 分钟区间 t = 0..143）：
    g_t >= 0        外网购电功率（kW）
    c_t in [0,5000] 储能充电功率（kW）
    d_t in [0,5000] 储能放电功率（kW）
    s_t >= 0        弃光功率（kW）
    SOC_t           区间 t 起始时刻储电量（kWh）
目标：min  sum_t  price_t * g_t * DT
约束：
    功率平衡   g_t + P_t + d_t = L_t + c_t + s_t
    SOC 递推   SOC_{t+1} = SOC_t + ETA*c_t*DT - d_t*DT/ETA   (充放电各 9 折)
    SOC 上下限 1200 <= SOC_t <= 10800
    首尾相等   SOC_0 = SOC_144 = 6000
    功率上限   0 <= c_t, d_t <= 5000
"""
import os
import numpy as np
import pandas as pd
from scipy.optimize import linprog
import openpyxl

# Windows 下 stdout 重定向到文件/管道时默认走 GBK，打印 ĝ(U+011D) 等字符会抛
# UnicodeEncodeError 并打断脚本（前面的求解其实已算完）。统一改 UTF-8。
import sys as _sys
for _s in (_sys.stdout, _sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

# ---------------- 参数 ----------------
DT = 1.0 / 6.0        # 10 分钟 = 1/6 小时
ETA = 0.9              # 充放电效率（各 9 折）
P_MAX = 5000.0         # 最大充放电功率 kW
SOC_MIN = 1200.0       # 储电量下限 kWh
SOC_MAX = 10800.0      # 储电量上限 kWh
SOC0 = 6000.0          # 0:00 与 24:00 储电量 kWh
N = 144                # 一天 10 分钟区间数

# ---------------- 读附件 1 ----------------
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # 项目根目录
df = pd.read_excel(os.path.join(BASE, "附件", "附件1.xlsx"))
price = df.iloc[:, 1].to_numpy(float)   # 电价 元/kWh
load = df.iloc[:, 2].to_numpy(float)    # 小区负载 kW
pv = df.iloc[:, 3].to_numpy(float)      # 光伏预测功率 kW
assert len(price) == N, f"附件1 应有 {N} 行，实际 {len(price)} 行"

# ---------------- 变量索引 ----------------
# 0..N-1       -> g
# N..2N-1      -> c
# 2N..3N-1     -> d
# 3N..4N-1     -> s
# 4N..4N+N     -> SOC (共 N+1 个，SOC[t] 为区间 t 起始储电量)
G0, C0, D0, S0, SOC0_idx = 0, N, 2 * N, 3 * N, 4 * N
n_vars = 4 * N + (N + 1)

# 目标系数：只对购电功率 g_t 计费（价格元/kWh）
c_obj = np.zeros(n_vars)
c_obj[G0:G0 + N] = price

# ---------------- 等式约束 ----------------
# 288 条：前 144 条功率平衡，后 144 条 SOC 递推
A_eq = np.zeros((2 * N, n_vars))
b_eq = np.zeros(2 * N)

for t in range(N):
    # (1) 功率平衡： g_t - c_t + d_t - s_t = L_t - P_t
    A_eq[t, G0 + t] = 1.0
    A_eq[t, C0 + t] = -1.0
    A_eq[t, D0 + t] = 1.0
    A_eq[t, S0 + t] = -1.0
    b_eq[t] = load[t] - pv[t]

    # (2) SOC 递推： SOC_{t+1} - SOC_t - ETA*DT*c_t + (DT/ETA)*d_t = 0
    row = N + t
    A_eq[row, SOC0_idx + t + 1] = 1.0
    A_eq[row, SOC0_idx + t] = -1.0
    A_eq[row, C0 + t] = -ETA * DT
    A_eq[row, D0 + t] = DT / ETA
    b_eq[row] = 0.0

# ---------------- 变量上下界 ----------------
# 注意：bounds 顺序必须与变量顺序一致
#   x[0..N-1]    = g  (购电功率)
#   x[N..2N-1]   = c  (充电功率)
#   x[2N..3N-1]  = d  (放电功率)
#   x[3N..4N-1]  = s  (弃光功率)
#   x[4N..4N+N]  = SOC (储电量)
bounds = []
for t in range(N):
    bounds.append((0.0, None))        # g_t >= 0
for t in range(N):
    bounds.append((0.0, P_MAX))       # 0 <= c_t <= 5000
for t in range(N):
    bounds.append((0.0, P_MAX))       # 0 <= d_t <= 5000
for t in range(N):
    bounds.append((0.0, None))        # s_t >= 0
bounds.append((SOC0, SOC0))                       # SOC_0 = 6000
for t in range(1, N):
    bounds.append((SOC_MIN, SOC_MAX))             # 1200 <= SOC_t <= 10800
bounds.append((SOC0, SOC0))                       # SOC_144 = 6000

# ---------------- 求解 ----------------
res = linprog(c_obj, A_eq=A_eq, b_eq=b_eq, bounds=bounds, method="highs")
assert res.success, f"LP 求解失败: {res.message}"

x = res.x
g = x[G0:G0 + N]          # 购电功率 kW
c = x[C0:C0 + N]          # 充电功率 kW
d = x[D0:D0 + N]          # 放电功率 kW
s = x[S0:S0 + N]          # 弃光功率 kW
soc = x[SOC0_idx:SOC0_idx + N + 1]  # 储电量 kWh

# ---------------- 能量（kWh） ----------------
purchase_kwh = g * DT            # 每区间购电量 kWh
charge_kwh = c * DT              # 每区间充电量 kWh
discharge_kwh = d * DT           # 每区间放电量 kWh
total_purchase = purchase_kwh.sum()
total_cost = (price * g * DT).sum()

# ---------------- 自检 ----------------
balance_resid = np.abs(g + pv + d - load - c - s).max()   # 功率平衡残差
print("=" * 60)
print("问题 1 求解结果自检")
print("=" * 60)
print(f"LP 状态            : {res.message}")
print(f"目标值 Σprice*g*Δt : {res.fun * DT:.2f} 元")
print(f"功率平衡最大残差    : {balance_resid:.2e} kW  (应≈0)")
print(f"SOC 范围           : [{soc.min():.4f}, {soc.max():.4f}] kWh  (应∈[1200,10800])")
print(f"SOC_0 / SOC_144    : {soc[0]:.4f} / {soc[-1]:.4f} kWh  (应=6000)")
print(f"全天购电量         : {total_purchase:.4f} kWh")
print(f"全天购电费         : {total_cost:.4f} 元")
print(f"全天充电量         : {charge_kwh.sum():.4f} kWh")
print(f"全天放电量         : {discharge_kwh.sum():.4f} kWh")
print(f"全天弃光量         : {(s * DT).sum():.4f} kWh")
net_load = (load - pv).sum() * DT
print(f"全天净负荷(负载-光伏): {net_load:.4f} kWh")
print(f"效率损耗(=购电-净负荷+弃光): {total_purchase - net_load:.4f} kWh")

# ---------------- 表 1（论文）指定时间段购电量 ----------------
# 窗口起始分钟/10 即区间索引：10:00-10:10 -> 60，依此类推
win_idx = {"10:00-10:10": 60, "12:00-12:10": 72, "14:00-14:10": 84,
           "16:00-16:10": 96, "18:00-18:10": 108, "20:00-20:10": 120}
print("\n表 1  指定时间段购电量(kWh) 与 全天汇总")
for name, i in win_idx.items():
    print(f"  {name}: {purchase_kwh[i]:.4f}")
print(f"  全天购电量: {total_purchase:.4f} kWh")
print(f"  全天购电费: {total_cost:.2f} 元")

# ---------------- 表 2（论文）4 小时块充放电 ----------------
blocks = [("0:00-4:00", 0, 24), ("4:00-8:00", 24, 48), ("8:00-12:00", 48, 72),
          ("12:00-16:00", 72, 96), ("16:00-20:00", 96, 120), ("20:00-24:00", 120, 144)]
print("\n表 2  储能充放电量(kWh)")
for name, a, b in blocks:
    print(f"  {name}: 充电 {charge_kwh[a:b].sum():.4f}  放电 {discharge_kwh[a:b].sum():.4f}")
print(f"  0:00 储电量: {soc[0]:.4f} kWh   24:00 储电量: {soc[-1]:.4f} kWh")

# ---------------- 写入 result1.xlsx（复制模板并填值） ----------------
template = os.path.join(BASE, "附件", "附件5", "result1.xlsx")
out_dir = os.path.join(BASE, "结果")
os.makedirs(out_dir, exist_ok=True)
out_path = os.path.join(out_dir, "result1.xlsx")

wb = openpyxl.load_workbook(template)

# 「计划购电量」：result1[k] = p[(k+1) % 144]（模板 0:10-0:20 起步，整体循环左移 10 分钟）
ws_p = wb["计划购电量"]
for k in range(N):
    ws_p.cell(row=k + 2, column=2).value = round(float(purchase_kwh[(k + 1) % N]), 4)

# 「充放电量」：6 个 4 小时块 + 0:00/24:00 储电量
ws_c = wb["充放电量"]
for j, (name, a, b) in enumerate(blocks):
    r = j + 2
    ws_c.cell(row=r, column=2).value = round(float(charge_kwh[a:b].sum()), 4)
    ws_c.cell(row=r, column=3).value = round(float(discharge_kwh[a:b].sum()), 4)
ws_c.cell(row=2, column=5).value = round(float(soc[0]), 4)    # 0:00 储电量
ws_c.cell(row=3, column=5).value = round(float(soc[-1]), 4)   # 24:00 储电量

wb.save(out_path)
print(f"\n结果已写入: {out_path}")
