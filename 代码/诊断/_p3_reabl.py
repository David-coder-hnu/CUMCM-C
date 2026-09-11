# -*- coding: utf-8 -*-
"""新默认口径（分组 span7）下重测 §5.2 分位扫描 与 §5.3 消融，输出可直接贴进归档的行。"""
import os, sys, subprocess
import numpy as np
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
def run(envx):
    e = os.environ.copy(); e.update({"P3_WRITE":"0","P3_SENT":"0"}); e.update(envx)
    p = subprocess.run([sys.executable, os.path.join(BASE,"代码","problem3_v3.py")],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", env=e, cwd=BASE)
    if p.returncode != 0: print("失败", p.stderr[-500:]); return None
    o = {}
    for ln in p.stdout.splitlines():
        if "最优 λ" in ln:
            o["total"] = float(ln.split("年费")[1].replace("元","").replace(",","").strip())
        if "分项：计划" in ln:
            t = ln.replace("分项：","").replace("｜"," ").split()
            o["plan"] = float(t[1].replace(",",""))
            o["breach"] = float(t[3].replace(",",""))
            o["excess"] = float(t[5].replace(",",""))
            o["emerg"] = float(t[7].replace(",",""))
        if "电量：计划" in ln:
            t = ln.replace("电量：","").replace("｜"," ").split()
            o["kwh_gh"] = float(t[1].replace(",","")); o["kwh_em"] = float(t[7].replace(",",""))
    return o

print("="*96); print("§5.2 分位扫描（新默认 L_base=分组span7）"); print("="*96)
print("| 块 0 τ | 块 1–3 τ | τ' | 总费(元) | 计划 | 紧急费 | 紧急 kWh |")
print("|---:|---:|---:|---:|---:|---:|---:|")
ROWS = [(0.80,0.40,0.40),(0.80,0.45,0.45),(0.80,0.50,0.50),(0.80,0.55,0.55),
        (0.80,0.60,0.60),(0.90,0.50,0.50),(0.80,0.50,0.60),(0.80,0.60,0.50),(0.85,0.45,0.45)]
best=None
for x,y,yp in ROWS:
    o = run({"P3_TAUB": f"{x},{y},{y},{y}", "P3_TAUP": str(yp)})
    if o is None: continue
    if best is None or o["total"] < best[0]: best = (o["total"], x, y, yp)
    bold = (x,y,yp)==(0.80,0.55,0.55)
    print(f"| {'**' if bold else ''}{x:.2f}{'**' if bold else ''} | {'**' if bold else ''}{y:.2f}{'**' if bold else ''} "
          f"| {'**' if bold else ''}{yp:.2f}{'**' if bold else ''} "
          f"| {'**' if bold else ''}{o['total']:,.0f}{'**' if bold else ''} "
          f"| {o['plan']:,.0f} | {o['emerg']:,.0f} | {o['kwh_em']:,.0f} |", flush=True)
print(f"\n最优：块0 τ={best[1]}  块1-3 τ={best[2]}  τ'={best[3]}  → {best[0]:,.0f} 元")

print("\n"+"="*96); print("§5.3 消融（新默认）"); print("="*96)
print("| 配置 | 总费(元) | 相对定稿 |")
print("|---|---:|---:|")
base = None
for tag, envx in [("**定稿**", {}), ("关水平校正 LEVEL=0", {"P3_LEVEL":"0"}),
                  ("BANDS=1（只用 6:00 档）", {"P3_BANDS":"1"}),
                  ("BANDS=2（+12:00 档）", {"P3_BANDS":"2"}),
                  ("BANDS=0（不用调整通道）", {"P3_BANDS":"0"})]:
    o = run(envx)
    if o is None: continue
    if base is None: base = o["total"]
    d = o["total"] - base
    print(f"| {tag} | {o['total']:,.0f} | {'—' if d==0 else f'**+{d:,.0f}**' if d>0 else f'{d:,.0f}'} |", flush=True)
