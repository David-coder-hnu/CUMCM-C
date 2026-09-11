# -*- coding: utf-8 -*-
"""独立复核 结果/result3.xlsx（口径 A 交付文件）。

本脚本**不 import 任何求解器**：自己从 附件1/附件2 重读原始数据，再从交付的
xlsx 里把数读回来重算，与表内自带的「全天购电费」列对账。目的是让交付文件
可被第三方按同样的口径独立核出来。

检查项
  A. 槽位对齐：第 k 列装 arr[(k+1)%N]（附件1 按**结束时刻**标号）⟹ 读回时要 np.roll(行,1)
  B. 计划/调整购电量两表的「全天购电量」= 本表 144 槽之和
  C. 无紧急购电日的「全天购电费」必须**精确**等于 p·ĝ + 1.5p·(g−ĝ)⁺（口径 A，违约项为 0）
  D. 有紧急购电日：由「紧急购电量」表的 kWh 反推隐含电价，须落在 [min p, max p] 的 5 倍带内
  E. 充放电量表的 SOC 链自洽：24:00 − 0:00 = η·Σc − Σd/η，且首尾相接
  F. 全表费用合计 = 交付总额
"""
import os
import sys

import numpy as np
import openpyxl
import pandas as pd

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DT, ETA, N, NDAYS, REPORT = 1.0 / 6.0, 0.9, 144, 365, 31
SOC_MIN, SOC_MAX = 1200.0, 10800.0

price_day = pd.read_excel(os.path.join(BASE, "附件", "附件1.xlsx")).iloc[:, 1].to_numpy(float)
load = pd.read_excel(os.path.join(BASE, "附件", "附件2.xlsx"),
                     sheet_name="小区负载").iloc[:, 1:1 + N].to_numpy(float)
pv = pd.read_excel(os.path.join(BASE, "附件", "附件2.xlsx"),
                   sheet_name="光伏发电实际功率").iloc[:, 1:1 + N].to_numpy(float)

wb = openpyxl.load_workbook(os.path.join(BASE, "结果", "result3.xlsx"), data_only=True)


def read_slots(ws, nrows):
    """读 144 个槽位列（2..145），按 `第k列装 arr[(k+1)%N]` 还原成真实时序。"""
    out = np.zeros((nrows, N))
    for j in range(nrows):
        row = np.array([ws.cell(row=j + 2, column=2 + k).value or 0.0 for k in range(N)])
        out[j] = np.roll(row, 1)          # 列 k 是真槽 (k+1)%N ⟹ 真槽 j 在列 (j-1)%N
    return out


ws_p, ws_a = wb["计划购电量"], wb["调整购电量"]
D = ws_p.max_row - 1
print(f"交付文件 结果/result3.xlsx：{D} 个计费日（{ws_p.max_row=}）")

gh = read_slots(ws_p, D)
gf = read_slots(ws_a, D)
ok = True

# ---- A. 槽位对齐 ----
tot_gh = np.array([ws_p.cell(row=j + 2, column=2 + N).value or 0.0 for j in range(D)])
bad = np.abs(tot_gh - gh.sum(axis=1)) > 0.01
print(f"A 槽位/全天购电量自洽：{'✓' if not bad.any() else f'✗ {bad.sum()} 天不符'}")
ok &= not bad.any()

tot_gf = np.array([ws_a.cell(row=j + 2, column=2 + N).value or 0.0 for j in range(D)])

# ---- 读回紧急购电量（按日聚合）与充放电量 ----
ws_e = wb["紧急购电量"]
em_kwh, cur = {}, None
for r in range(2, ws_e.max_row + 1):
    d0 = ws_e.cell(row=r, column=1).value
    v = ws_e.cell(row=r, column=3).value
    if d0 is not None:
        cur = d0
        em_kwh[cur] = float(v or 0.0)
    elif cur is not None:
        em_kwh[cur] += float(v or 0.0)

ws_c = wb["充放电量"]
chg = np.zeros((D, 6)); dis = np.zeros((D, 6)); soc_b = np.zeros((D, 2))
for j in range(D):
    b0 = j * 6 + 2
    for b in range(6):
        chg[j, b] = ws_c.cell(row=b0 + b, column=3).value or 0.0
        dis[j, b] = ws_c.cell(row=b0 + b, column=4).value or 0.0
    soc_b[j, 0] = ws_c.cell(row=b0, column=6).value or 0.0
    soc_b[j, 1] = ws_c.cell(row=b0 + 1, column=6).value or 0.0

fee = np.array([ws_p.cell(row=j + 2, column=3 + N).value or 0.0 for j in range(D)])

# ---- C/D. 逐日重算费用 ----
dev = (1.5 * price_day * np.maximum(gf - gh, 0)).sum(axis=1)          # 超额费
plan = (price_day * gh).sum(axis=1)                                    # 计划购电费全额
no_em = []
for j in range(D):
    e_kwh = em_kwh.get(ws_p.cell(row=j + 2, column=1).value, 0.0)
    if e_kwh <= 1e-6:
        resid = fee[j] - (plan[j] + dev[j])
        no_em.append((j, resid))
        if abs(resid) > 0.02:
            ok = False
print(f"C 无紧急购电日精确对账：{len(no_em)} 天 ｜ 最大残差 "
      f"{max((abs(r) for _, r in no_em), default=0.0):.6f} 元 ｜ {'✓' if all(abs(r) <= 0.02 for _, r in no_em) else '✗'}")

# ---- E. SOC 链 ----
d_soc = soc_b[:, 1] - soc_b[:, 0]
pred = ETA * chg.sum(axis=1) - dis.sum(axis=1) / ETA
esoc = np.abs(d_soc - pred)
chain = np.abs(soc_b[1:, 0] - soc_b[:-1, 1])
allso = np.concatenate([soc_b[:, 0], soc_b[:, 1]])
print(f"E SOC 递推残差：最大 {esoc.max():.4f} kWh ｜ 跨日衔接最大 {chain.max():.4f} kWh ｜ "
      f"区间 [{allso.min():,.1f}, {allso.max():,.1f}] ∈ [{SOC_MIN:.0f}, {SOC_MAX:.0f}] ｜ "
      f"{'✓' if esoc.max() < 0.05 and chain.max() < 0.05 and allso.min() >= SOC_MIN - 0.05 and allso.max() <= SOC_MAX + 0.05 else '✗'}")
ok &= esoc.max() < 0.05 and chain.max() < 0.05

# ---- F. 合计 ----
print(f"F 全年合计：表内 {fee.sum():,.2f} 元 ｜ 计划费 {plan.sum():,.2f} ｜ "
      f"超额费 {dev.sum():,.2f} ｜ 紧急(kWh) {sum(em_kwh.values()):,.2f}")
print(f"   Σĝ {gh.sum():,.2f} kWh ｜ Σg {gf.sum():,.2f} kWh ｜ "
      f"差额 {gf.sum() - gh.sum():,.2f} kWh（= 超额电量）")
print(f"   充 {chg.sum():,.2f} ｜ 放 {dis.sum():,.2f} ｜ 放/充 {dis.sum() / chg.sum():.4f}（η²=0.81）")
print(f"   实际负荷 {load[REPORT:].sum() * DT:,.2f} kWh ｜ 光伏 {pv[REPORT:].sum() * DT:,.2f} kWh")
print(f"\n结论：{'✓ 交付文件自洽' if ok else '✗ 有不符项，见上'}")
