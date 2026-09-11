# -*- coding: utf-8 -*-
"""汇总问题 3 的 6 小时窗口数据。

读取 结果/result3.xlsx，按以下约定生成：
  · 计划购电量：计划购电量工作表 144 个槽列
  · 调整购电量：调整购电量工作表 144 个槽列
  · 净调整量：g - g_hat
  · 上调量：max(g - g_hat, 0)
  · 下调量：max(g_hat - g, 0)
  · 紧急购电量：解析 HH:MM-HH:MM，并按与四个 6 小时窗口的重叠时长比例归窗

窗口取自然槽序：
  0:00-6:00 -> [0, 36)
  6:00-12:00 -> [36, 72)
  12:00-18:00 -> [72, 108)
  18:00-24:00 -> [108, 144)

result3 写盘时执行了 arr[(k + 1) % 144]，因此读回时必须对每行做 np.roll(row, 1)。
"""
from pathlib import Path

import numpy as np
import pandas as pd


BASE = Path(__file__).resolve().parents[2]
SOURCE = BASE / "结果" / "result3.xlsx"
OUT_SUMMARY = BASE / "结果" / "problem3_block_summary.csv"
OUT_DAILY = BASE / "结果" / "problem3_block_daily.csv"

N = 144
NDAYS = 334
BLOCKS = [(0, 36), (36, 72), (72, 108), (108, 144)]
LABELS = ["0:00-6:00", "6:00-12:00", "12:00-18:00", "18:00-24:00"]


def minute_value(value):
    text = str(value).strip()
    if text in {"24:00", "0:00+1"}:
        return 24 * 60
    hour, minute = map(int, text.split(":"))
    return hour * 60 + minute


def read_slots(sheet):
    matrix = sheet.iloc[:NDAYS, 1 : 1 + N].to_numpy(float)
    if matrix.shape != (NDAYS, N):
        raise ValueError(f"工作表应为 {NDAYS}×{N}，实际为 {matrix.shape}")
    return np.roll(matrix, 1, axis=1)


def main():
    plan = read_slots(pd.read_excel(SOURCE, sheet_name="计划购电量"))
    adjusted = read_slots(pd.read_excel(SOURCE, sheet_name="调整购电量"))
    emergency_sheet = pd.read_excel(SOURCE, sheet_name="紧急购电量")

    net = adjusted - plan
    up = np.maximum(net, 0.0)
    down = np.maximum(-net, 0.0)

    dates = pd.date_range("2025-02-01", "2025-12-31", freq="D")
    if len(dates) != NDAYS:
        raise ValueError("日期范围应为 2025-02-01 至 2025-12-31")

    emergency = np.zeros((NDAYS, 4), dtype=float)
    date_col = pd.to_datetime(emergency_sheet.iloc[:, 0], errors="coerce").ffill()

    for row in range(len(emergency_sheet)):
        date = pd.Timestamp(date_col.iloc[row]).normalize()
        segment = emergency_sheet.iloc[row, 1]
        energy = emergency_sheet.iloc[row, 2]
        if pd.isna(date) or pd.isna(segment) or pd.isna(energy):
            continue
        if date < dates[0] or date > dates[-1]:
            continue

        start_text, end_text = str(segment).split("-")
        start = minute_value(start_text)
        end = minute_value(end_text)
        if end <= start:
            continue

        day_index = (date - dates[0]).days
        energy = float(energy)
        for block_index, (block_start, block_end) in enumerate(
            [(0, 360), (360, 720), (720, 1080), (1080, 1440)]
        ):
            overlap = max(0, min(end, block_end) - max(start, block_start))
            if overlap:
                emergency[day_index, block_index] += energy * overlap / (end - start)

    records = []
    for day_index, date in enumerate(dates):
        for block_index, label in enumerate(LABELS):
            start, end = BLOCKS[block_index]
            records.append(
                {
                    "日期": date.strftime("%Y-%m-%d"),
                    "窗口": label,
                    "计划购电量_kWh": plan[day_index, start:end].sum(),
                    "调整购电量_kWh": adjusted[day_index, start:end].sum(),
                    "净调整_kWh": net[day_index, start:end].sum(),
                    "上调_kWh": up[day_index, start:end].sum(),
                    "下调_kWh": down[day_index, start:end].sum(),
                    "紧急购电量_kWh": emergency[day_index, block_index],
                }
            )

    daily = pd.DataFrame(records)
    columns = [
        "计划购电量_kWh",
        "调整购电量_kWh",
        "净调整_kWh",
        "上调_kWh",
        "下调_kWh",
        "紧急购电量_kWh",
    ]
    summary = daily.groupby("窗口", sort=False)[columns].sum().reset_index()

    daily.to_csv(OUT_DAILY, index=False, encoding="utf-8-sig")
    summary.to_csv(OUT_SUMMARY, index=False, encoding="utf-8-sig")

    print(summary.to_string(index=False, float_format=lambda value: f"{value:,.4f}"))
    print(f"\n逐日明细: {OUT_DAILY}")
    print(f"窗口汇总: {OUT_SUMMARY}")


if __name__ == "__main__":
    main()
