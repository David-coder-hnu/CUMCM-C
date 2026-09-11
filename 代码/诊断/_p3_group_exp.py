# -*- coding: utf-8 -*-
"""问题 3 吸纳问题 2 的低需求日分组：收益有多大？是否显著？

对照结构照搬问题 2 的 A1/A2/A3：
  C1 现状           L_base=同星期几 K=4 ；残差=全部历史池化
  C2 K=2            L_base=同星期几 K=2 （只缩窗口）
  C3 全部七天 span14 不分组、只把窗口截到 14 天
  C4 分组 span14     L_base 与残差都改用低需求日分组
  C5 分组 span14     L_base 保持同星期几 K=4（只改残差）→ 归因分解
  C6 分组 扩张       分组但不截窗口
"""
import os, sys, subprocess
import numpy as np
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(BASE, "代码", "诊断", "_p3arms")
os.makedirs(OUT, exist_ok=True)
ALL7 = "0,1,2,3,4,5,6"

# ⚠ 分组现在是脚本缺省，基线臂必须显式 `P3_GRP=""` 关掉，否则会静默跟随分组（见 _p3_mech.py）。
ARMS = [
    ("C1 现状 K=4", {"P3_GRP": ""}),
    ("C2 K=2", {"P3_GRP": "", "P3_KPEERS": "2"}),
    ("C3 全七天 span14", {"P3_GRP": ALL7, "P3_GSPAN": "14"}),
    ("C4 分组 span14", {"P3_GRP": "auto", "P3_GSPAN": "14", "P3_GBASE": "1"}),
    ("C5 分组 span14 仅残差", {"P3_GRP": "auto", "P3_GSPAN": "14", "P3_GBASE": "0",
                          "P3_HSRC": "group", "P3_MINR": "4"}),
    ("C6 分组 扩张", {"P3_GRP": "auto", "P3_GSPAN": "0", "P3_GBASE": "1"}),
]

def run_arm(tag, envx, extra=None):
    e = os.environ.copy()
    e.update({"P3_WRITE": "0", "P3_SENT": "0", "P3_DUMP": os.path.join(OUT, tag.split()[0] + ".npz")})
    if extra: e.update(extra)
    e.update(envx)
    p = subprocess.run([sys.executable, os.path.join(BASE, "代码", "problem3_v3.py")],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", env=e, cwd=BASE)
    if p.returncode != 0:
        print(f"[{tag}] 失败\n{p.stdout[-1500:]}\n{p.stderr[-1500:]}"); return None
    return np.load(e["P3_DUMP"])

res = {}
for tag, envx in ARMS:
    r = run_arm(tag, envx)
    if r is None: continue
    res[tag] = r
    print(f"  {tag:22s} 总 {float(r['total']):>12,.0f} 元   紧急 {float(r['kwh_em']):>9,.0f} kWh", flush=True)

base = res["C1 现状 K=4"]
nd = int(base["nd"]); win0 = int(base["win0"])
RD = np.arange(win0, nd)
print("\n" + "="*104)
print(f"逐日配对对照（计费窗口 {len(RD)} 天，第 {win0+1}–{nd} 天）")
print("="*104)
print(f"{'对照':<22}{'总费':>13}{'Δ vs C1':>13}{'日均Δ':>10}{'中位Δ':>10}"
      f"{'更便宜日':>10}{'块自助95%CI':>24}{'p':>8}")
print("-"*104)

def block_ci(d, blk=14, B=4000, seed=7):
    rng = np.random.default_rng(seed)
    n = len(d); nb = int(np.ceil(n / blk))
    means = np.empty(B)
    for b in range(B):
        st = rng.integers(0, n, nb)
        idx = np.concatenate([(np.arange(s, s+blk) % n) for s in st])
        means[b] = d[idx].mean()
    lo, hi = np.percentile(means, [2.5, 97.5])
    p = 2 * min((means <= 0).mean(), (means >= 0).mean())
    return lo, hi, p

rows = {}
for tag, r in res.items():
    d = (r["cost_day"][RD] - base["cost_day"][RD])
    rows[tag] = d
    if tag.startswith("C1"): continue
    lo, hi, p = block_ci(d)
    print(f"{tag:<22}{float(r['total']):>13,.0f}{d.sum():>+13,.0f}{d.mean():>+10,.0f}"
          f"{np.median(d):>+10,.0f}{int((d<0).sum()):>7}/{len(d):<3}"
          f"{f'[{lo:+,.0f}, {hi:+,.0f}]':>24}{p:>8.3f}")

print("\n" + "="*104)
print("稳健性：剔除最省的 N 天后剩余总差（A3−A2 那种尾部驱动的检查）")
print("="*104)
for tag in list(res)[1:]:
    s = np.sort(rows[tag])
    print(f"  {tag:<22} 总 {s.sum():>+12,.0f} ｜ "
          f"剔10 {s[10:].sum():>+12,.0f} ｜ 剔20 {s[20:].sum():>+12,.0f} ｜ 剔50 {s[50:].sum():>+12,.0f}")

print("\n" + "="*104)
print("前后半年是否一致（检验是否被某个时段独占）")
print("="*104)
half = len(RD)//2
print(f"{'对照':<22}{'前半Δ':>15}{'后半Δ':>15}{'前半更便宜':>12}{'后半更便宜':>12}")
for tag in list(res)[1:]:
    d = rows[tag]
    print(f"{tag:<22}{d[:half].sum():>+15,.0f}{d[half:].sum():>+15,.0f}"
          f"{int((d[:half]<0).sum()):>8}/{half:<4}{int((d[half:]<0).sum()):>8}/{len(d)-half:<4}")
