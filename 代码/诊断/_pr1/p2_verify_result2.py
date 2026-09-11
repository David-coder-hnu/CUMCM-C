# -*- coding: utf-8 -*-
"""独立复核 结果/result2.xlsx（分组版）：不复用 problem2.py 的任何中间量，只读表。"""
import os, sys
import numpy as np
import pandas as pd
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
N, NDAYS, REPORT = 144, 365, 31
DT = 1.0 / 6.0
price_day = pd.read_excel(os.path.join(BASE, "附件", "附件1.xlsx")).iloc[:, 1].to_numpy(float)
xl = pd.ExcelFile(os.path.join(BASE, "结果", "result2.xlsx"))
print("工作表:", xl.sheet_names)

# ---- 表1 计划购电量 ----
d = pd.read_excel(xl, "计划购电量", header=0)
print("表1 形状:", d.shape)
slots = d.iloc[:, 1:1 + N].apply(pd.to_numeric, errors="coerce")
day_tot = pd.to_numeric(d.iloc[:, 1 + N], errors="coerce")
day_fee = pd.to_numeric(d.iloc[:, 2 + N], errors="coerce")
print(f"  报告天数 {len(d)}  NaN(槽) {int(slots.isna().sum().sum())}  NaN(全天/费用) "
      f"{int(day_tot.isna().sum())}/{int(day_fee.isna().sum())}")
print(f"  槽列和 {slots.to_numpy().sum():,.4f}  vs 全天列和 {day_tot.sum():,.4f}  "
      f"差 {slots.to_numpy().sum() - day_tot.sum():,.6f}")
print(f"  全天购电费列合计 {day_fee.sum():,.2f} 元")

# 时间对齐：result2[k] = g[(k+1) % 144]  ⟹  Σp·ĝ = Σ_k p[(k+1)%144]·cell_k
sh = np.roll(price_day, -1)                      # 左移 1 位
G = slots.to_numpy()
planned = float((G * sh).sum())
print(f"  Σp·ĝ（应用循环左移约定）  {planned:,.2f} 元")
print(f"  Σp·ĝ（不应用左移，错读）  {float((G * price_day).sum()):,.2f} 元")
print(f"  紧急费 = 费用列 − Σp·ĝ    {day_fee.sum() - planned:,.2f} 元")

# ---- 5000 kW 功率越限 ----
kw = G / DT
over = kw > 5000.0 + 1e-6
print(f"\n  购电功率峰值 {kw.max():,.4f} kW")
print(f"  超 5000 kW 的槽 {int(over.sum()):,} / {G.size:,}   "
      f"涉及天数 {int((over.any(axis=1)).sum())} / {len(G)}")
print(f"  每槽功率 = 该槽 kWh / (1/6 h)")

# ---- 表2 充放电量 ----
c = pd.read_excel(xl, "充放电量", header=0)
print(f"\n表2 形状: {c.shape}")
chg = pd.to_numeric(c.iloc[:, 2], errors="coerce")
dis = pd.to_numeric(c.iloc[:, 3], errors="coerce")
tok = pd.to_numeric(c.iloc[:, 5], errors="coerce")
print(f"  充电合计 {np.nansum(chg):,.4f} kWh   放电合计 {np.nansum(dis):,.4f} kWh")
print(f"  充/放功率峰值 {np.nanmax(chg)/4.0:,.2f} / {np.nanmax(dis)/4.0:,.2f} kW"
      f"   （表2 每行是 4 小时块的 kWh 合计，阈值 5000kW×4h = 20,000 kWh）")
soc = tok.dropna().to_numpy()
print(f"  储电量读数 {len(soc)} 个  范围 [{soc.min():,.4f}, {soc.max():,.4f}]")
mid = []
for j in range(0, len(soc) - 1, 2):
    mid.append((soc[j], soc[j + 1]))
mid = np.array(mid)
print(f"  0:00 读数范围 [{mid[:,0].min():,.4f}, {mid[:,0].max():,.4f}]")
print(f"  24:00 与次日 0:00 的最大差 {np.abs(mid[:-1,1] - mid[1:,0]).max():.10f}")
print(f"  日内 0:00→24:00 首末: {mid[0,0]:,.4f} → {mid[-1,1]:,.4f}")

# ---- 表3 紧急购电量 ----
e = pd.read_excel(xl, "紧急购电量", header=0)
print(f"\n表3 形状: {e.shape}  （行=紧急时段，日期列有重复）")
ev = pd.to_numeric(e.iloc[:, 2], errors="coerce")
print(f"  紧急购电量合计 {np.nansum(ev):,.4f} kWh")
dt_col = pd.to_datetime(e.iloc[:, 0], errors="coerce").dropna()
print(f"  日期范围 {dt_col.min().date()} → {dt_col.max().date()}   不同日期 {dt_col.nunique()}")
nz = (ev.fillna(0) > 1e-9).sum()
print(f"  非零紧急时段 {nz} 段")

print("\n--- 与求解器输出对照 ---")
print(f"  求解器: 计划 14,089,579 / 实际总 14,341,723 / 紧急 42,589 kWh")
print(f"  表内  : 计划 {planned:,.0f} / 实际总 {day_fee.sum():,.0f} / 紧急 {np.nansum(ev):,.0f} kWh")
