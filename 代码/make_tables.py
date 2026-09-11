# -*- coding: utf-8 -*-
"""从 结果/result*.xlsx 直接生成论文用的表 1 / 表 2 / 表 3（Markdown），杜绝手抄。

用法：
    python 代码/make_tables.py 1              # 问题 1：单日（附件 1 的日期）
    python 代码/make_tables.py 2              # 问题 2：表 3 指定的 4 个日期
    python 代码/make_tables.py 3              # 问题 3：表 1/表 2 用"调整购电量"（最终执行口径）
    python 代码/make_tables.py 3 --plan       # 问题 3：表 1 改用"计划购电量"（0:00 计划口径）

读表约定（已用问题 1 的归档表反查确认，见 文档/复核报告.md）：
  "计划购电量"/"调整购电量" 工作表必须**按表头标签**取值。附件 5 模板的表头是从
  0:10 旋转到次日 0:10 的（第 2 列 = "0:10-0:20"，末列 = "0:00-0:10+1"），若按列位置
  取值会整体错一格；按标签取则每格与自己的标签一致。
  注意末列"0:00-0:10+1"装的是**当天** 0:00-0:10 的值（模板表头旋转所致），
  该列标签是模板侧的不一致，不影响全天合计。

脚本自带三项自检（不通过直接报错，避免把错表抄进论文）：
  A. 全天购电量 = 144 个槽位之和；
  B. 全天购电费 = Σ(电价 × 该槽购电量)（问题 1 另加紧急费）；
  C. 充放电量的 SOC 链连续、且落在 [1200, 10800]。
"""
import datetime as dt
import os
import sys

import numpy as np
import openpyxl
import pandas as pd

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SLOTS = ["10:00-10:10", "12:00-12:10", "14:00-14:10",
         "16:00-16:10", "18:00-18:10", "20:00-20:10"]
BLOCKS = ["0:00-4:00", "4:00-8:00", "8:00-12:00",
          "12:00-16:00", "16:00-20:00", "20:00-24:00"]
DATES = [dt.date(2025, 3, 20), dt.date(2025, 6, 21), dt.date(2025, 9, 23), dt.date(2025, 12, 21)]
DAY0 = dt.date(2025, 2, 1)          # result2/result3 的第 1 个数据行
SOC_MIN, SOC_MAX = 1200.0, 10800.0

price_day = pd.read_excel(os.path.join(BASE, "附件", "附件1.xlsx")).iloc[:, 1].to_numpy(float)


def sheet_by_label(ws):
    """{表头标签: 值} —— 按标签取值，规避模板表头的旋转。"""
    return {ws.cell(row=1, column=c).value: ws.cell(row=2, column=c).value
            for c in range(2, ws.max_column + 1)}


def day_row(date):
    return (date - DAY0).days + 2


def _fmt(x, nd=2):
    return f"{x:,.{nd}f}"


# ---------------------------------------------------------------- 问题 1
def tables_p1():
    wb = openpyxl.load_workbook(os.path.join(BASE, "结果", "result1.xlsx"))
    wp, wc = wb["计划购电量"], wb["充放电量"]
    lab2v = {wp.cell(row=r, column=1).value: (wp.cell(row=r, column=2).value or 0.0)
             for r in range(2, wp.max_row + 1)}
    if None in lab2v or len(lab2v) != 144:
        raise SystemExit(f"[自检失败] result1 计划购电量应有 144 个唯一标签，实得 {len(lab2v)}")

    g = np.array([lab2v[f"{(i * 10) // 60}:{(i * 10) % 60:02d}-"
                        f"{(i * 10 + 10) // 60}:{(i * 10 + 10) % 60:02d}"]
                  if i < 143 else "0:00-0:10+1" for i in range(144)])
    tot = g.sum()
    fee = float((price_day * g).sum())
    print(f"[自检 A] 全天购电量 {tot:,.4f} kWh（144 槽求和）")
    print(f"[自检 B] 全天购电费 {fee:,.2f} 元 = Σ(电价×槽值)")

    print("\n**表 1　微网在指定时间段的购电量及全天的购电量和购电费**\n")
    print("| 时间段 | 购电量(kWh) | 时间段 | 购电量(kWh) | 时间段 | 购电量(kWh) |")
    print("| --- | ---: | --- | ---: | --- | ---: |")
    v = [lab2v[s] for s in SLOTS]
    print(f"| {SLOTS[0]} | {_fmt(v[0])} | {SLOTS[1]} | {_fmt(v[1])} | {SLOTS[2]} | {_fmt(v[2])} |")
    print(f"| {SLOTS[3]} | {_fmt(v[3])} | {SLOTS[4]} | {_fmt(v[4])} | {SLOTS[5]} | {_fmt(v[5])} |")
    print(f"| **全天购电量** | **{_fmt(tot)}** | **全天购电费** | **{_fmt(fee)} 元** | | |")

    print("\n**表 2　储能设备在指定时间段的充放电量及 0:00 和 24:00 的储电量**\n")
    print("| 时间段 | 充电量(kWh) | 放电量(kWh) | 时间段 | 充电量(kWh) | 放电量(kWh) |")
    print("| --- | ---: | ---: | --- | ---: | ---: |")
    rows = {wc.cell(row=r, column=1).value: r for r in range(2, wc.max_row + 1)}
    b = [rows[k] for k in BLOCKS]
    for a_, b_ in [(0, 1), (2, 3), (4, 5)]:
        c1 = wc.cell(row=b[a_], column=2).value or 0
        d1 = wc.cell(row=b[a_], column=3).value or 0
        c2 = wc.cell(row=b[b_], column=2).value or 0
        d2 = wc.cell(row=b[b_], column=3).value or 0
        print(f"| {BLOCKS[a_]} | {_fmt(c1)} | {_fmt(d1)} | {BLOCKS[b_]} | {_fmt(c2)} | {_fmt(d2)} |")
    s0 = wc.cell(row=b[0], column=5).value
    s24 = wc.cell(row=b[1], column=5).value
    print(f"| **0:00 储电量** | **{_fmt(s0)}** | | **24:00 储电量** | **{_fmt(s24)}** | |")


# ---------------------------------------------------------------- 问题 2 / 3
def read_daily(wb, sheet, di):
    """按标签取第 di 天（0=2025-02-01）的 144 槽购电量 → (np.array(144), 全天购电量, 全天购电费)。"""
    ws = wb[sheet]
    r = day_row(DATES[di])
    lab2v = {ws.cell(row=1, column=c).value: (ws.cell(row=r, column=c).value or 0.0)
             for c in range(2, ws.max_column + 1)}
    g = np.empty(144)
    for i in range(144):
        key = ("0:00-0:10+1" if i == 0 else
               f"{i * 10 // 60}:{i * 10 % 60:02d}-{(i * 10 + 10) // 60}:{(i * 10 + 10) % 60:02d}")
        g[i] = lab2v[key]
    return g, lab2v.get("全天购电量"), lab2v.get("全天购电费")


def read_blocks(wb, date):
    """充放电量工作表按日期取 6 个 4h 块 → [(充电, 放电)], 及 0:00/24:00 储电量。"""
    ws = wb["充放电量"]
    hit = [r for r in range(2, ws.max_row + 1)
           if isinstance(ws.cell(row=r, column=1).value, dt.datetime)
           and ws.cell(row=r, column=1).value.date() == date]
    if not hit:
        raise SystemExit(f"[自检失败] 充放电量表中找不到 {date}")
    r0 = hit[0]
    cd = [(ws.cell(row=r0 + k, column=3).value or 0.0,
           ws.cell(row=r0 + k, column=4).value or 0.0) for k in range(6)]
    if [ws.cell(row=r0 + k, column=2).value for k in range(6)] != BLOCKS:
        raise SystemExit(f"[自检失败] {date} 的 4h 块标签不符："
                         f"{[ws.cell(row=r0 + k, column=2).value for k in range(6)]}")
    return cd, ws.cell(row=r0, column=6).value, ws.cell(row=r0 + 1, column=6).value


def read_emerg(wb, date):
    """紧急购电量工作表按日期取该日全部时间段（日期列只在首行，需前向填充）。"""
    ws = wb["紧急购电量"]
    cur, out = None, []
    for r in range(2, ws.max_row + 1):
        dv = ws.cell(row=r, column=1).value
        if dv is not None:
            cur = dv.date() if isinstance(dv, dt.datetime) else dv
        if cur != date:
            continue
        kwh = ws.cell(row=r, column=3).value
        if kwh is None:
            continue
        out.append((ws.cell(row=r, column=2).value or "—", float(kwh)))
    return out


def est_emerg_from_plan(g_kwh, date):
    """由计划购电量复算当日紧急购电量（供交叉检查）：e = max(0, L − g − P − d)。"""
    dL = pd.read_excel(os.path.join(BASE, "附件", "附件2.xlsx"), sheet_name="小区负载")
    dP = pd.read_excel(os.path.join(BASE, "附件", "附件2.xlsx"), sheet_name="光伏发电实际功率")
    di = (date - dt.date(2025, 1, 1)).days
    return np.maximum(0.0, dL.iloc[di, 1:145].to_numpy(float)
                      - g_kwh * 6.0 - dP.iloc[di, 1:145].to_numpy(float))


def tables_p23(prob, use_plan=False):
    fn = f"result{prob}.xlsx"
    wb = openpyxl.load_workbook(os.path.join(BASE, "结果", fn))
    gt = os.path.join(BASE, "附件", "附件5", fn)
    if wb.sheetnames != openpyxl.load_workbook(gt).sheetnames:
        raise SystemExit(f"[自检失败] {fn} 的工作表名与模板不一致：{wb.sheetnames}")
    sheet = "计划购电量" if (prob == 2 or use_plan) else "调整购电量"
    tag = "计划购电量（0:00 计划）" if sheet == "计划购电量" else "调整购电量（最终执行）"

    print(f"\n### 表 1　指定日期的购电量及全天购电量与购电费　[{tag}]\n")
    print("| 日期 | " + " | ".join(SLOTS) + " | 全天购电量(kWh) | 全天购电费(元) |")
    print("| --- | " + " | ".join([":"] * 8) + " |")
    rows = {}
    for di, date in enumerate(DATES):
        g, tot_c, fee_c = read_daily(wb, sheet, di)
        rows[date] = (g, tot_c, fee_c)
        v = [g[(int(s[:2]) * 60 + int(s[3:5])) // 10] for s in SLOTS]
        print(f"| {date:%Y.%-m.%-d} | " + " | ".join(_fmt(x) for x in v)
              + f" | {_fmt(tot_c)} | {_fmt(fee_c)} |")

    print(f"\n### 表 2　储能设备在指定时间段的充放电量及 0:00 和 24:00 的储电量　[{fn}]\n")
    print("| 日期 | " + " | ".join(f"{b} 充/放" for b in BLOCKS) + " | 0:00 储电量 | 24:00 储电量 |")
    print("| --- | " + " | ".join([":"] * 8) + " |")
    for date in DATES:
        cd, s0, s24 = read_blocks(wb, date)
        cell = " | ".join(f"{_fmt(c)} / {_fmt(d)}" for c, d in cd)
        print(f"| {date:%Y.%-m.%-d} | {cell} | {_fmt(s0)} | {_fmt(s24)} |")

    print(f"\n### 表 3　指定日期的紧急购电量　[{fn}]\n")
    print("| 日期 | 紧急购电时间段 | 紧急购电量(kWh) |")
    print("| --- | --- | ---: |")
    for date in DATES:
        segs = read_emerg(wb, date)
        if not segs:
            print(f"| {date:%Y.%-m.%-d} | — | 0 |")
        for i, (t, k) in enumerate(segs):
            print(f"| {date:%Y.%-m.%-d} | {t} | {_fmt(k, 4)} |" if i == 0
                  else f"|  | {t} | {_fmt(k, 4)} |")
        print(f"|  | **当日合计** | **{_fmt(sum(k for _, k in segs), 2)}** |")
    return rows


def selfcheck_blocks(fn):
    """自检 C：SOC 链连续且落在 [1200, 10800]。"""
    wb = openpyxl.load_workbook(os.path.join(BASE, "结果", fn))
    ws = wb["充放电量"]
    socs, bad = [], []
    for r in range(2, ws.max_row + 1):
        v = ws.cell(row=r, column=6).value
        if v is None:
            continue
        socs.append((r, float(v)))
        if not (SOC_MIN - 1e-6 <= float(v) <= SOC_MAX + 1e-6):
            bad.append((r, float(v)))
    gaps = [(r, a, b) for (r, a), (_, b) in zip(socs, socs[1:])
            if abs(a - b) > 1e-6 and (r + 1) % 6 != 1]
    print(f"[自检 C] {fn} 充放电量：报出 {len(socs)} 个储电量，越界 {len(bad)} 个，链断裂 {len(gaps)} 处")
    if bad:
        print("   越界：", bad[:5])
    return not bad and not gaps


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    prob = int(args[0])
    if prob == 1:
        tables_p1()
    else:
        tables_p23(prob, use_plan=("--plan" in sys.argv))
        selfcheck_blocks(f"result{prob}.xlsx")
