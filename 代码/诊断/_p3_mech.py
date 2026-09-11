# -*- coding: utf-8 -*-
"""机制检查：分组收益是否经由「水平校正 r」进入？+ 关键对照的块自助 CI。"""
import os, sys, subprocess
import numpy as np
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(BASE,"代码","诊断","_p3arms")
def arm(envx, dump):
    e = os.environ.copy(); e.update({"P3_WRITE":"0","P3_SENT":"0","P3_DUMP":os.path.join(OUT,dump+".npz")}); e.update(envx)
    p = subprocess.run([sys.executable, os.path.join(BASE,"代码","problem3_v3.py")],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", env=e, cwd=BASE)
    if p.returncode!=0: print(f"[{dump}] 失败 {p.stderr[-500:]}"); return None
    return np.load(e["P3_DUMP"])

def block_ci(d, blk=14, B=4000, seed=7):
    rng=np.random.default_rng(seed); n=len(d); nb=int(np.ceil(n/blk)); m=np.empty(B)
    for b in range(B):
        st=rng.integers(0,n,nb); m[b]=d[np.concatenate([(np.arange(s,s+blk)%n) for s in st])].mean()
    lo,hi=np.percentile(m,[2.5,97.5]); return lo,hi,2*min((m<=0).mean(),(m>=0).mean())

# ⚠ 分组现在是脚本缺省，必须显式 `P3_GRP=""` 才能关掉，否则所谓"K=4 基线"臂
# 会静默地跟着分组跑，全部对照退化成 +0（本脚本旧版就这么错过一次）。
_K4 = {"P3_GRP": "", "P3_KPEERS": "4"}
CFG = [("K=4 LEVEL1", dict(_K4), "F1"),
       ("K=4 LEVEL0", {**_K4, "P3_LEVEL": "0"}, "F2"),
       ("K=4 ADJ0",   {**_K4, "P3_ADJ": "0"},   "F3"),
       ("sp7 LEVEL1", {"P3_GRP": "auto", "P3_GSPAN": "7"}, "E4"),
       ("sp7 LEVEL0", {"P3_GRP": "auto", "P3_GSPAN": "7", "P3_LEVEL": "0"}, "F4"),
       ("sp7 ADJ0",   {"P3_GRP": "auto", "P3_GSPAN": "7", "P3_ADJ": "0"},   "F5"),
       ("K=1 LEVEL1", {"P3_GRP": "", "P3_KPEERS": "1"}, "E1")]
res={}
for tag,envx,dump in CFG:
    r = arm(envx,dump)
    if r is not None: res[tag]=r; print(f"  {tag:14s} 总 {float(r['total']):>12,.0f} 元  紧急 {float(r['kwh_em']):>9,.0f} kWh", flush=True)

RD=np.arange(int(res["K=4 LEVEL1"]["win0"]), int(res["K=4 LEVEL1"]["nd"]))
print("\n"+"="*104)
print("机制检查：关掉水平校正(LEVEL=0)或整个调整通道(ADJ=0)之后，分组还剩多少收益")
print("="*104)
for a,b_,nm in [("sp7 LEVEL1","K=4 LEVEL1","调整层全开"),
                ("sp7 LEVEL0","K=4 LEVEL0","关水平校正"),
                ("sp7 ADJ0","K=4 ADJ0","关整个调整通道")]:
    d = res[a]["cost_day"][RD]-res[b_]["cost_day"][RD]
    lo,hi,p = block_ci(d); s=np.sort(d)
    print(f"  {nm:<14} 分组 span7 − K=4 :  总 {d.sum():>+11,.0f} ｜ 中位 {np.median(d):>+7,.0f} "
          f"｜ 更便宜 {int((d<0).sum()):>3}/334 ｜ CI [{lo:+,.0f}, {hi:+,.0f}] ｜ p={p:.3f}")
    print(f"                 剔10 {s[10:].sum():>+11,.0f} ｜ 剔20 {s[20:].sum():>+11,.0f} ｜ 剔50 {s[50:].sum():>+11,.0f}")

print("\n"+"="*104)
print("★ 关键对照块自助（去掉近期性后的纯分组效应）")
print("="*104)
for a,b_,nm in [("sp7 LEVEL1","K=1 LEVEL1","分组 span7 − 同星期几 K=1（同为 1 周前）"),
                ("sp7 LEVEL1","K=4 LEVEL1","分组 span7 − 现状 K=4")]:
    d = res[a]["cost_day"][RD]-res[b_]["cost_day"][RD]
    lo,hi,p = block_ci(d); s=np.sort(d)
    print(f"  {nm}")
    print(f"     总 {d.sum():>+11,.0f} ｜ 日均 {d.mean():>+8,.0f} ｜ 中位 {np.median(d):>+8,.0f} "
          f"｜ 更便宜 {int((d<0).sum()):>3}/334 ｜ CI [{lo:+,.0f}, {hi:+,.0f}] ｜ p={p:.3f}")
    print(f"     剔10 {s[10:].sum():>+11,.0f} ｜ 剔20 {s[20:].sum():>+11,.0f} ｜ 剔50 {s[50:].sum():>+11,.0f}")
