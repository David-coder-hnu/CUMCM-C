# -*- coding: utf-8 -*-
"""★ 负结果专项：把低需求日分组搬到「残差分位取样」那一路上，是有益还是有害？

背景：问题 2 里分组有效，是因为低需求日的净负荷只有其余日的约 1/3，
`q_γ` 取组内最小值时组间量级差极大。问题 3 的预报残差**组不变**（逐槽 std 437 vs 422），
所以预期无益。本脚本把三处口径拆开独立开关，实测之：

  A 仅 L_base 分组（定稿口径）      P3_GBASE=1, P3_HSRC=all
  B 仅残差分组                      P3_GBASE=0, P3_HSRC=group
  C 两者都分组                      P3_GBASE=1, P3_HSRC=group

⚠ 残差那一路要真正激活必须同时放开 `P3_MINR`（组内样本数 < 14 会触发回退）。
"""
import os, sys, subprocess
import numpy as np
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(BASE, "代码", "诊断", "_p3arms"); os.makedirs(OUT, exist_ok=True)

ARMS = [
    ("R1 仅L_base分组 span14", {"P3_GRP": "auto", "P3_GSPAN": "14", "P3_GBASE": "1", "P3_HSRC": "all"}),
    ("R2 仅残差分组 span14",   {"P3_GRP": "auto", "P3_GSPAN": "14", "P3_GBASE": "0",
                           "P3_HSRC": "group", "P3_MINR": "4"}),
    ("R3 两者都分组 span14",   {"P3_GRP": "auto", "P3_GSPAN": "14", "P3_GBASE": "1",
                           "P3_HSRC": "group", "P3_MINR": "4"}),
    ("R4 仅残差分组 扩张",     {"P3_GRP": "auto", "P3_GSPAN": "0", "P3_GBASE": "0",
                           "P3_HSRC": "group", "P3_MINR": "4"}),
    ("R5 两者都分组 扩张",     {"P3_GRP": "auto", "P3_GSPAN": "0", "P3_GBASE": "1",
                           "P3_HSRC": "group", "P3_MINR": "4"}),
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


def block_ci(d, blk=14, B=4000, seed=7):
    rng = np.random.default_rng(seed); n = len(d); nb = int(np.ceil(n / blk))
    m = np.empty(B)
    for b in range(B):
        st = rng.integers(0, n, nb)
        m[b] = d[np.concatenate([(np.arange(s, s + blk) % n) for s in st])].mean()
    lo, hi = np.percentile(m, [2.5, 97.5])
    return lo, hi, 2 * min((m <= 0).mean(), (m >= 0).mean())


res = {}
for tag, envx in ARMS:
    r = run_arm(tag, envx)
    if r is not None:
        res[tag] = r
        print(f"  {tag:24s} 总 {float(r['total']):>12,.0f} 元  紧急 {float(r['kwh_em']):>9,.0f} kWh", flush=True)

RD = np.arange(int(res["R1 仅L_base分组 span14"]["win0"]), int(res["R1 仅L_base分组 span14"]["nd"]))
d1 = res["R1 仅L_base分组 span14"]["cost_day"][RD]

print("\n" + "=" * 100)
print("残差那一路分组的效果（基准 = 仅 L_base 分组，即定稿那一侧）")
print("=" * 100)
for tag, r in res.items():
    if tag.startswith("R1"): continue
    d = r["cost_day"][RD] - d1
    lo, hi, p = block_ci(d)
    print(f"  {tag:24s} Δ {d.sum():>+11,.0f} ｜ 中位 {np.median(d):>+7,.0f} ｜ "
          f"更便宜 {int((d < 0).sum()):>3}/334 ｜ CI [{lo:+,.0f}, {hi:+,.0f}] ｜ p={p:.3f}")

print("\n" + "=" * 100)
print("★ 关键配对：两者都分组 − 仅 L_base 分组（span14）")
print("=" * 100)
d = res["R3 两者都分组 span14"]["cost_day"][RD] - d1
lo, hi, p = block_ci(d); s = np.sort(d)
print(f"  总 {d.sum():>+11,.0f} ｜ 日均 {d.mean():>+7,.0f} ｜ 中位 {np.median(d):>+7,.0f} ｜ "
      f"更便宜 {int((d < 0).sum()):>3}/334 ｜ CI [{lo:+,.0f}, {hi:+,.0f}] ｜ p={p:.3f}")
print(f"  剔10 {s[10:].sum():>+11,.0f} ｜ 剔20 {s[20:].sum():>+11,.0f} ｜ 剔50 {s[50:].sum():>+11,.0f}")
print(f"\n  结论：p={p:.3f} {'不显著' if p > 0.05 else '显著'}，"
      f"中位日差 {np.median(d):+,.0f} 元 ⟹ "
      f"{'残差分组没有带来任何东西' if p > 0.05 else '需重看'}")
