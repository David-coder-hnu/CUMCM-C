# -*- coding: utf-8 -*-
"""扫 Q_ADJ / Q_BLIND 两个计划分位，找问题 3 严格口径下的最优 0:00 计划水位。
用子进程 + 环境变量调 problem3_v2.py，结果从 stdout 抓。NO_SAVE=1 时不写 result3.xlsx。
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "problem3_v2.py")
BASE = os.path.dirname(HERE)


def run(q_blind, q_adj, save=False):
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["Q_BLIND"] = str(q_blind)
    env["Q_ADJ"] = str(q_adj)
    if not save:
        env["NO_SAVE"] = "1"
    r = subprocess.run([sys.executable, SCRIPT], env=env, capture_output=True, text=True,
                       encoding="utf-8", cwd=BASE)
    if r.returncode != 0:
        print(r.stdout[-2000:], r.stderr[-2000:])
        raise SystemExit(1)
    out = r.stdout
    tot = float(re.search(r"合计\s+([\d,]+)\s*元", out).group(1).replace(",", ""))
    em = float(re.search(r"\(([\d,]+) kWh\)", out).group(1).replace(",", ""))
    plan = float(re.search(r"计划量 ([\d,]+) kWh", out).group(1).replace(",", ""))
    return tot, em, plan


if __name__ == "__main__":
    print(f"{'Q_BLIND':>8} {'Q_ADJ':>6} {'计划量(kWh)':>14} {'紧急(kWh)':>12} {'总费(元)':>14}")
    print("-" * 62)
    best = None
    for qb in [0.72, 0.76, 0.80, 0.84, 0.88]:
        for qa in [0.40, 0.50, 0.60, 0.70, 0.74]:
            tot, em, plan = run(qb, qa)
            print(f"{qb:>8.3f} {qa:>6.2f} {plan:>14,.0f} {em:>12,.0f} {tot:>14,.0f}", flush=True)
            if best is None or tot < best[0]:
                best = (tot, qb, qa)
    print("-" * 62)
    print(f"最优：Q_BLIND={best[1]:.3f}, Q_ADJ={best[2]:.2f}, 总费={best[0]:,.0f}")
