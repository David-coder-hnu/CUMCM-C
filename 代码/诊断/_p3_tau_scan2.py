# -*- coding: utf-8 -*-
"""换 L_base 口径后最优 τ 是否位移？在 C1(现状) 与 D1(分组span14) 上各扫一遍。"""
import os, sys, subprocess
import numpy as np
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
def run(envx):
    e = os.environ.copy(); e.update({"P3_WRITE":"0","P3_SENT":"0"}); e.update(envx)
    p = subprocess.run([sys.executable, os.path.join(BASE,"代码","problem3_v3.py")],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", env=e, cwd=BASE)
    if p.returncode != 0: return None
    for ln in p.stdout.splitlines():
        if "最优 λ" in ln:
            return float(ln.split("年费")[1].replace("元","").replace(",","").strip())
    return None
CONF = [("C1 现状 K=4", {}), ("D1 分组 span14", {"P3_GRP":"auto","P3_GSPAN":"14"}),
        ("D6 分组 span7", {"P3_GRP":"auto","P3_GSPAN":"7"})]
T0 = [0.70, 0.75, 0.80, 0.85, 0.90]
T1 = [0.45, 0.50, 0.55, 0.60]
print("="*94); print("τ 扫描：块0 τ × 后三块 τ'（单位：元）"); print("="*94)
for tag, envx in CONF:
    print(f"\n【{tag}】")
    print("块0\后三块".ljust(10) + "".join(f"{y:>13.2f}" for y in T1))
    best, bv = None, None
    for x in T0:
        row = []
        for y in T1:
            v = run({**envx, "P3_TAUB": f"{x},{y},{y},{y}"})
            row.append(v)
            if v is not None and (bv is None or v < bv): bv, best = v, (x, y)
        print(f"{x:<10.2f}" + "".join(f"{('—' if v is None else format(v, ',.0f')):>13}" for v in row), flush=True)
    print(f"  最优：块0 τ={best[0]}  后三块 τ'={best[1]}  → {bv:,.0f} 元")
