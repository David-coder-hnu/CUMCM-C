# -*- coding: utf-8 -*-
"""问题 3（problem3_v2）的消融实验 + 预报质量矩阵。

用途：为 文档/问题3_求解归档.md 提供可复现的支撑数据。
- 消融：分别关掉"计划对冲"(NO_HEDGE)、"日内调整通道"(NO_ADJ)、换用"只按 0:00 档残差对冲"(PLAN_R0)，
  看总额变化，证明每一块各自的贡献。
- 预报质量矩阵：净需求（负荷−光伏）在每个发布档、每个 6h 时窗上的 RMSE。

用法：python 代码/p3v2_ablation.py
"""
import os
import re
import subprocess
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.dirname(HERE)
SCRIPT = os.path.join(HERE, "problem3_v2.py")

N, NDAYS, K_PEERS, REPORT = 144, 365, 4, 31   # REPORT=31：统计窗口从 2/1 起
COVER = [(0, 36), (36, 72), (72, 108), (108, 144)]
WIN_NAME = ["0-6h", "6-12h", "12-18h", "18-24h"]


# ---------------------------------------------------------------- 消融
def run(env_extra):
    """跑一次 problem3_v2，返回 (总费, 紧急kWh, 计划kWh)。NO_SAVE=1 不写 result3.xlsx。"""
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["NO_SAVE"] = "1"
    env.update({k: str(v) for k, v in env_extra.items() if v is not None})
    r = subprocess.run([sys.executable, SCRIPT], env=env, capture_output=True, text=True,
                       encoding="utf-8", cwd=BASE)
    if r.returncode != 0:
        print(r.stdout[-1500:], r.stderr[-1500:])
        raise SystemExit(f"变体失败：{env_extra}")
    out = r.stdout
    tot = float(re.search(r"合计\s+([\d,]+)\s*元", out).group(1).replace(",", ""))
    em = float(re.search(r"\(([\d,]+) kWh\)", out).group(1).replace(",", ""))
    plan = float(re.search(r"计划量 ([\d,]+) kWh", out).group(1).replace(",", ""))
    return tot, em, plan


K_DEF = 20          # 留出法定出的场景数；K 只影响日内 LP，计划层不受影响
FLOOR = {"MEAN_FLOOR": 1}   # 定稿启用的均值覆盖下限

VARIANTS = [
    ("完整模型 K=20 + 下限（Q_BLIND=0.80 / Q_ADJ=0.74）", {"K_SCEN": K_DEF, **FLOOR}),
    ("关掉计划对冲（NO_HEDGE）", {"NO_HEDGE": 1, "K_SCEN": K_DEF, **FLOOR}),
    ("关掉日内调整通道（NO_ADJ，扫到最优 Q_ALL=0.80）", {"NO_ADJ": 1, "Q_ALL": 0.80}),
    ("计划只按 0:00 档残差对冲（PLAN_R0，最优 Q_ADJ=0.70）", {"PLAN_R0": 1, "Q_ADJ": 0.70, "K_SCEN": K_DEF, **FLOOR}),
    ("分位未调优（Q_BLIND=0.889 报童理论值 / Q_ADJ=0.70）", {"Q_BLIND": 0.889, "Q_ADJ": 0.70, "K_SCEN": K_DEF, **FLOOR}),
    ("K 退回 4 + 下限（仍带对冲）", {"K_SCEN": 4, **FLOOR}),
    ("K 退回 4 且无下限（= 上一版定稿）", {"K_SCEN": 4}),
]

# ② K 曲线（场景数；K 只影响日内 LP）
SWEEP_K = [4, 8, 12, 20, 32, 48]
# ③ 分位扫描（K=20 + 下限下，检验曲面平坦度）
SWEEP_BLIND = [0.50, 0.70, 0.80, 0.90]
SWEEP_ADJ = [0.64, 0.70, 0.74, 0.80]

def main():
    print("=" * 78)
    print("① 消融实验")
    print("=" * 78)
    print(f"{'变体':<50}{'总费(元)':>13}{'紧急(kWh)':>12}")
    print("-" * 78)
    base = None
    for name, ev in VARIANTS:
        tot, em, _ = run(ev)
        if base is None:
            base = tot
        delta = "" if tot == base else f"  (Δ{tot - base:+,.0f})"
        print(f"{name:<50}{tot:>13,.0f}{em:>12,.0f}{delta}", flush=True)

    print()
    print("=" * 78)
    print("② K 曲线（场景数；K 只影响日内 LP，计划层不受影响）")
    print("=" * 78)
    print(f"{'K':>6}{'总费(元)':>15}{'紧急(kWh)':>13}")
    for k in SWEEP_K:
        tot, em, _ = run({"K_SCEN": k, **FLOOR})
        print(f"{k:>6}{tot:>15,.0f}{em:>13,.0f}", flush=True)

    print()
    print("=" * 78)
    print("③ 分位扫描（K=20 + 下限，检验曲面平坦度）")
    print("=" * 78)
    print(f"-- 固定 Q_ADJ=0.70，扫 Q_BLIND --")
    print(f"{'Q_BLIND':>8}{'总费(元)':>15}")
    for qb in SWEEP_BLIND:
        tot, _, _ = run({"Q_BLIND": qb, "Q_ADJ": 0.70, "K_SCEN": K_DEF, **FLOOR})
        print(f"{qb:>8.3f}{tot:>15,.0f}", flush=True)
    print(f"-- 固定 Q_BLIND=0.80，扫 Q_ADJ --")
    print(f"{'Q_ADJ':>8}{'总费(元)':>15}")
    for qa in SWEEP_ADJ:
        tot, _, _ = run({"Q_BLIND": 0.80, "Q_ADJ": qa, "K_SCEN": K_DEF, **FLOOR})
        print(f"{qa:>8.2f}{tot:>15,.0f}", flush=True)

    # ------------------------------------------------------------ 预报质量矩阵
    print()
    print("=" * 78)
    print("③ 净需求（负荷−光伏）预报 RMSE，kW —— 各发布档 × 各 6h 时窗")
    print("=" * 78)
    dfL = pd.read_excel(os.path.join(BASE, "附件", "附件2.xlsx"), sheet_name="小区负载")
    dfP = pd.read_excel(os.path.join(BASE, "附件", "附件2.xlsx"), sheet_name="光伏发电实际功率")
    load = dfL.iloc[:, 1:1 + N].to_numpy(float)
    pv = dfP.iloc[:, 1:1 + N].to_numpy(float)
    fc3 = pd.read_excel(os.path.join(BASE, "附件", "附件3.xlsx"), header=None) \
            .iloc[1:, 2:].to_numpy(float).reshape(NDAYS, 4, 24)

    mean_load = load.mean(axis=0)
    L_base = np.empty_like(load)
    for d in range(NDAYS):
        idx = [d - 7 * k for k in range(1, K_PEERS + 1) if d - 7 * k >= 0]
        L_base[d] = load[idx].mean(axis=0) if idx else mean_load

    W = np.zeros((N, 25))
    for k in range(N):
        t = (k + 1) / 6.0
        lo = int(np.floor(t)); hi = min(int(np.ceil(t)), 24)
        if lo == hi:
            W[k, lo] = 1.0
        else:
            W[k, lo] = 1.0 - (t - lo); W[k, hi] = t - lo

    def pv_fc(d, s_idx, s_hour):
        H = np.zeros(25)
        if s_hour > 0:
            H[s_hour] = pv[d, 6 * s_hour]
        for h in range(s_hour + 1, 25):
            H[h] = fc3[d, s_idx, h - s_hour - 1]
        return H @ W.T

    S_HOUR = [0, 6, 12, 18]
    P_hat = np.stack([[pv_fc(d, s, S_HOUR[s]) for s in range(4)] for d in range(NDAYS)])
    F_hat = L_base[:, None, :] - P_hat
    actual_net = load - pv
    resid = (actual_net[:, None, :] - F_hat)[REPORT:]   # 与结果口径一致：2/1–12/31

    # 只统计"发布档 s 真正覆盖的时窗"——早于发布时刻的时窗对挡 s 无意义
    hdr = f"{'发布档':>8}" + "".join(f"{w:>10}" for w in WIN_NAME)
    print(hdr)
    print("-" * len(hdr))
    for s in range(4):
        row = f"{S_HOUR[s]:>6}:00"
        for wi, (a, b) in enumerate(COVER):
            if wi >= s:                       # 档 s 覆盖时窗 s..3
                row += f"{np.sqrt((resid[:, s, a:b] ** 2).mean()):>10.1f}"
            else:
                row += f"{'—':>10}"
        print(row)

    # 18:00 档对 18-24h 的增量：与 12:00 档、与 0:00 档对比
    print()
    print("增量检验（18-24h 时窗，净需求 RMSE kW）：")
    for s, lab in [(0, "0:00 档"), (1, "6:00 档"), (2, "12:00 档"), (3, "18:00 档")]:
        rmse = np.sqrt((resid[:, s, 108:144] ** 2).mean())
        print(f"  {lab}: {rmse:.1f}")


if __name__ == "__main__":
    main()
