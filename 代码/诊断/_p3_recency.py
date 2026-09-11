# -*- coding: utf-8 -*-
"""分离「近期性」与「分组」：同星期几 K=1/2/3 是不分组的近期性对照。"""
import os, sys, subprocess
import numpy as np
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(BASE,"代码","诊断","_p3arms")
def run_arm(k, envx, dump):
    e = os.environ.copy(); e.update({"P3_WRITE":"0","P3_SENT":"0","P3_DUMP":os.path.join(OUT,dump+".npz")}); e.update(envx)
    p = subprocess.run([sys.executable, os.path.join(BASE,"代码","problem3_v3.py")],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", env=e, cwd=BASE)
    if p.returncode!=0: print(f"[{k}] 失败 {p.stderr[-600:]}"); return None
    return np.load(e["P3_DUMP"])

ARMS = [("E1 K=1", {"P3_KPEERS":"1"}, "E1"),
        ("E2 K=3", {"P3_KPEERS":"3"}, "E2"),
        ("E3 K=4", {}, "C1"),
        ("E4 分组 span7",  {"P3_GRP":"auto","P3_GSPAN":"7"},  "D6"),
        ("E5 分组 span14", {"P3_GRP":"auto","P3_GSPAN":"14"}, "D1"),
        ("E6 K=2", {"P3_KPEERS":"2"}, "C2")]
res={}
for tag, envx, dump in ARMS:
    r = run_arm(tag, envx, dump)
    if r is not None:
        res[tag]=r
        print(f"  {tag:16s} 总 {float(r['total']):>12,.0f} 元  紧急 {float(r['kwh_em']):>9,.0f} kWh", flush=True)

b = res["E3 K=4"]; RD = np.arange(int(b["win0"]), int(b["nd"])); c1 = b["cost_day"][RD]
print("\n"+"="*100)
print("同星期几的近期性对照（不分组，只把 L_base 的历史日拉近）")
print("="*100)
print(f"{'口径':<16}{'总费':>13}{'Δ vs K=4':>13}{'L_base 用几个历史日':>22}")
for tag in ("E1 K=1","E6 K=2","E2 K=3","E3 K=4"):
    if tag in res:
        k = tag.split("=")[1]
        print(f"{tag:<16}{float(res[tag]['total']):>13,.0f}{res[tag]['cost_day'][RD].sum()-c1.sum():>+13,.0f}{k+' 个（同星期几）':>22}")

print("\n"+"="*100)
print("★ 分组 vs 同星期几：同为「1 周前」，起点样本数不同")
print("="*100)
for tag in ("E4 分组 span7","E5 分组 span14"):
    r = res[tag]; d = r["cost_day"][RD]
    for nm, ref in (("K=1", res["E1 K=1"]), ("K=2", res["E6 K=2"]), ("K=4", b)):
        dd = d - ref["cost_day"][RD]
        print(f"  {tag:<16} − {nm} :  总 {dd.sum():>+11,.0f} ｜ 中位 {np.median(dd):>+8,.0f} ｜ 更便宜 {int((dd<0).sum()):>3}/334")

print("\n"+"="*100)
print("前后半年：最优口径是否稳定（防 in-sample 选参）")
print("="*100)
half = len(RD)//2
print(f"{'口径':<16}{'前半总费':>14}{'后半总费':>14}{'前半Δ':>12}{'后半Δ':>12}")
for tag in ("E1 K=1","E6 K=2","E2 K=3","E3 K=4","E4 分组 span7","E5 分组 span14"):
    if tag not in res: continue
    d = res[tag]["cost_day"][RD]; dc = c1
    print(f"{tag:<16}{d[:half].sum():>14,.0f}{d[half:].sum():>14,.0f}"
          f"{d[:half].sum()-dc[:half].sum():>+12,.0f}{d[half:].sum()-dc[half:].sum():>+12,.0f}")
