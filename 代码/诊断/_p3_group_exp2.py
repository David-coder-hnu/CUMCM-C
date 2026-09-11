# -*- coding: utf-8 -*-
"""第二批：把残差取样那一路真正激活（MINR 放开），并做 C4−C2 的干净配对检验。"""
import os, sys, subprocess
import numpy as np
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(BASE, "代码", "诊断", "_p3arms"); os.makedirs(OUT, exist_ok=True)

ARMS = [
    ("D1 C4基准 span14 MINR14", {"P3_GRP": "auto", "P3_GSPAN": "14", "P3_GBASE": "1"}),
    ("D2 同上但 MINR4",          {"P3_GRP": "auto", "P3_GSPAN": "14", "P3_GBASE": "1", "P3_MINR": "4"}),
    # ⚠ 仅残差分组必须显式 `P3_HSRC=group`；缺省 "all" 会让这两臂静默退化成 C1（已实测 +0）。
    ("D3 分组扩张 仅残差 MINR4",  {"P3_GRP": "auto", "P3_GSPAN": "0", "P3_GBASE": "0",
                             "P3_HSRC": "group", "P3_MINR": "4"}),
    ("D4 分组span14 仅残差 MINR4",{"P3_GRP": "auto", "P3_GSPAN": "14", "P3_GBASE": "0",
                             "P3_HSRC": "group", "P3_MINR": "4"}),
    ("D5 分组 span28",           {"P3_GRP": "auto", "P3_GSPAN": "28", "P3_GBASE": "1"}),
    ("D6 分组 span7",            {"P3_GRP": "auto", "P3_GSPAN": "7",  "P3_GBASE": "1"}),
    ("D7 分组 span21",           {"P3_GRP": "auto", "P3_GSPAN": "21", "P3_GBASE": "1"}),
    ("D8 分组 span35",           {"P3_GRP": "auto", "P3_GSPAN": "35", "P3_GBASE": "1"}),
]
def run_arm(tag, envx):
    e = os.environ.copy()
    k = tag.split()[0]
    e.update({"P3_WRITE": "0", "P3_SENT": "0", "P3_DUMP": os.path.join(OUT, k + ".npz")})
    e.update(envx)
    p = subprocess.run([sys.executable, os.path.join(BASE, "代码", "problem3_v3.py")],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", env=e, cwd=BASE)
    if p.returncode != 0:
        print(f"[{tag}] 失败\n{p.stdout[-900:]}\n{p.stderr[-900:]}"); return None
    return np.load(e["P3_DUMP"])

res = {}
for tag, envx in ARMS:
    r = run_arm(tag, envx)
    if r is not None:
        res[tag] = r
        print(f"  {tag:26s} 总 {float(r['total']):>12,.0f} 元  紧急 {float(r['kwh_em']):>9,.0f} kWh", flush=True)

def block_ci(d, blk=14, B=4000, seed=7):
    rng = np.random.default_rng(seed); n = len(d); nb = int(np.ceil(n/blk))
    m = np.empty(B)
    for b in range(B):
        st = rng.integers(0, n, nb)
        m[b] = d[np.concatenate([(np.arange(s, s+blk) % n) for s in st])].mean()
    lo, hi = np.percentile(m, [2.5, 97.5])
    return lo, hi, 2*min((m <= 0).mean(), (m >= 0).mean())

b = np.load(os.path.join(OUT, "C1.npz")); c2 = np.load(os.path.join(OUT, "C2.npz"))
RD = np.arange(int(b["win0"]), int(b["nd"]))
c1d, c2d = b["cost_day"][RD], c2["cost_day"][RD]

print("\n" + "="*100)
print("★ 关键配对检验（照搬问题 2 的 A3−A2 结构）")
print("="*100)
for tag, r in res.items():
    if not tag.startswith(("D1", "D2")): continue
    d4 = r["cost_day"][RD]
    for nm, dd in [("(分组 span14) − (K=4)", d4 - c1d), ("(分组 span14) − (K=2)", d4 - c2d)]:
        lo, hi, p = block_ci(dd)
        s = np.sort(dd)
        print(f"  {tag.split()[0]} × {nm:<24} 总 {dd.sum():>+11,.0f} ｜ 中位 {np.median(dd):>+8,.0f} ｜ "
              f"更便宜 {int((dd<0).sum()):>3}/334 ｜ CI [{lo:+,.0f}, {hi:+,.0f}] ｜ p={p:.3f}")
        print(f"      剔10 {s[10:].sum():>+11,.0f} ｜ 剔20 {s[20:].sum():>+11,.0f} ｜ "
              f"剔50 {s[50:].sum():>+11,.0f}")

print("\n" + "="*100)
print("回看窗口敏感性（都启用分组，L_base 与残差同步）")
print("="*100)
print(f"{'回看':<10}{'总费':>13}{'Δ vs C1':>13}{'Δ vs C2':>13}{'紧急kWh':>12}")
for tag, r in res.items():
    if not tag.startswith("D"): continue
    lab = tag.split()[-1]
    print(f"{lab:<10}{float(r['total']):>13,.0f}{r['cost_day'][RD].sum()-c1d.sum():>+13,.0f}"
          f"{r['cost_day'][RD].sum()-c2d.sum():>+13,.0f}{float(r['kwh_em']):>12,.0f}")

print("\n" + "="*100)
print("残差取样那一路单独激活时（GBASE=0, MINR=4）与 C1/C4 的差")
print("="*100)
for tag, r in res.items():
    if not tag.startswith(("D3", "D4")): continue
    dd = r["cost_day"][RD]
    print(f"  {tag:<26} Δ vs C1 {dd.sum()-c1d.sum():>+11,.0f} ｜ Δ vs D1 {dd.sum()-res['D1 C4基准 span14 MINR14']['cost_day'][RD].sum():>+11,.0f}")
