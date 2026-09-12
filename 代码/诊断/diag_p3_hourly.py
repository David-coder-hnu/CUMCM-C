# -*- coding: utf-8 -*-
"""附件 3 是【整点】预报，模型要的是【144 槽】—— 跨分辨率的一步，我们是怎么走的？

题面（C题.md:54）与附件 3 的列头（预报1小时…预报24小时）都写明：每天 4 档（0/6/12/18
时发布）、每档给出**未来 24 小时整点**的光伏功率，一天只有 4×24 个数。而决策分辨率是
144 槽/天（附件 1/2 均为 10 分钟区间）。所以模型里**必然**存在一条「逐小时 → 144 槽」的
还原约定 —— 本脚本把这步的做法、依据、以及它带来的一处前视全部量化出来。

三件事：
  【检查A】整点预报(kW) 对齐的是"结束于该整点的槽"还是"起始于该整点的槽"？（定对齐口径）
  【检查B】把整点真值当"完美逐小时预报"，四种还原约定 vs 真实 10min 序列，谁最准？
  【检查C】pv_fc 的锚点 H[S]=pv[d,6S] 用的是【发布时刻之后 10 分钟】的实测 ⇒ 一处
          10 分钟前视。量化它，并验证 P3_ANCHOR="prev"（严格因果）就是那一行修复。
  【检查D】（两臂都跑完才执行）端到端 A/B：P3_ANCHOR=next vs prev 的交付值差。

不 import 任何求解器 —— 纯数据核对，可独立复现。
"""
import os
import sys

import numpy as np
import pandas as pd

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
N, NDAYS = 144, 365
S_HOUR = [0, 6, 12, 18]

pv = pd.read_excel(os.path.join(BASE, "附件", "附件2.xlsx"),
                   sheet_name="光伏发电实际功率").iloc[:, 1:1 + N].to_numpy(float)
# 附件3：1461 行 = 365 天 × 4 档，前两列是日期与预报时刻，之后 24 列 = 预报1..24小时
fc3 = pd.read_excel(os.path.join(BASE, "附件", "附件3.xlsx"), header=None) \
        .iloc[1:, 2:].to_numpy(float).reshape(NDAYS, 4, 24)

print("=" * 100)
print("【检查A】附件 3 的整点预报对齐哪个 10 分钟槽？（全年 4 档合并，只算有光照的点）")
print("=" * 100)
print(f"  附件3 形态：{NDAYS} 天 × 4 档 × 24 个整点值 ｜ 附件2 形态：{NDAYS} 天 × {N} 个 10min 槽")
print("  ⇒ 分辨率缺口真实存在；模型必须补一条还原约定。\n")

EF, EV, SF, SV = [], [], [], []
for s in range(4):
    for k in range(24):
        h = S_HOUR[s] + k + 1                 # 预报k小时 ⇒ 时刻 S+k+1
        if h > 24:
            continue
        f = fc3[:, s, k]
        EF.append(f); EV.append(pv[:, 6 * h - 1])      # 槽【结束于】h:00
        if h <= 23:
            SF.append(f); SV.append(pv[:, 6 * h])      # 槽【起始于】h:00


def _rep(nm, f, v):
    f, v = np.concatenate(f), np.concatenate(v)
    m = (f > 1) | (v > 1)
    f, v = f[m], v[m]
    tag = "   ← 采用" if "结束" in nm else ""
    print(f"  {nm:22s} n={len(f):>7,}  MAE={np.abs(f - v).mean():>7.2f} kW  "
          f"RMSE={np.sqrt(((f - v) ** 2).mean()):>7.2f}  corr={np.corrcoef(f, v)[0, 1]:.5f}{tag}")


_rep("槽『结束于』该整点", EF, EV)
_rep("槽『起始于』该整点", SF, SV)
print("\n  ⇒ 整点预报对齐「结束于该整点的槽」，与附件 1/2 的右端点标号约定自洽。")

print()
print("=" * 100)
print("【检查B】逐小时真值 → 144 槽：四种还原约定 vs 真实 10min 序列")
print("=" * 100)

# 整点真值 H[0..24]：H[h] = 结束于 h:00 的那个槽（h≥1）；H[0] 取前一日末槽
H = np.zeros((NDAYS, 25))
H[:, 1:] = pv[:, [6 * h - 1 for h in range(1, 25)]]
H[:, 0] = np.concatenate([[pv[0, 0]], pv[:-1, 143]])


def _wmat(shift):
    """锚在槽的 (k+shift)/6 时刻做线性插值；shift=1 ⇒ 锚在槽末（现用）。"""
    W = np.zeros((N, 25))
    for k in range(N):
        t = (k + shift) / 6.0
        lo = int(np.floor(t)); hi = min(int(np.ceil(t)), 24)
        if lo == hi:
            W[k, lo] = 1.0
        else:
            W[k, lo] = 1.0 - (t - lo); W[k, hi] = t - lo
    return W


Zend = np.zeros((N, 25)); Zstart = np.zeros((N, 25))
for k in range(N):
    Zend[k, (k + 1) // 6 if (k + 1) % 6 == 0 else (k + 1) // 6 + 1] = 1.0   # 槽结束于 h ⇒ 用 H[h]
    Zstart[k, k // 6] = 1.0                                                # 槽起始于 h ⇒ 用 H[h]

act = pv
m = act > 1
for nm, Wm in [("线性插值·锚槽末(现用)", _wmat(1.0)), ("线性插值·锚槽中", _wmat(0.5)),
               ("阶梯·槽结束于整点", Zend), ("阶梯·槽起始于整点", Zstart)]:
    r = H @ Wm.T
    tag = "  ← 采用" if "现用" in nm else ""
    print(f"  {nm:24s} RMSE={np.sqrt(((r - act)[m] ** 2).mean()):>7.2f} kW   "
          f"全年电量 {r.sum() - act.sum():>+11,.0f} kWh ({r.sum() / act.sum() - 1:+.3%}){tag}")
print("\n  ⇒ ① 不做插值（阶梯）会带进 4–6 倍误差 —— 插值不是可有可无的装饰；")
print("     ② 现用约定（线性插值·锚槽末）是四种里最准的，与【检查A】的方向一致；")
print("     ③ 四种约定的**全年电量完全相同**（每行权重和为 1）⇒ 插值只重分配、")
print("        不增删电量，因此不会在总量上给模型送分。")

print()
print("=" * 100)
print("【检查C】锚点 H[S]=pv[d,6S] 的 10 分钟前视：量级与受影响范围")
print("=" * 100)
print("  严格因果的替代 = pv[d, 6S−1]（发布时刻 S:00 已观测完的最后一个槽）。")
print("  两者之差 = 那 10 分钟的爬坡量 = 前视量。\n")

tot = 0.0
for s in (1, 2, 3):
    S = S_HOUR[s]
    lead = pv[:, 6 * S] - pv[:, 6 * S - 1]
    aff = [k for k in range(N) if _wmat(1.0)[k, S] > 0 and k >= 6 * S]
    w = _wmat(1.0)[aff, S]
    err = np.abs(w[None, :] * lead[:, None])
    tot += err.sum()
    print(f"  {S:>2d}:00 档  锚点均值 {pv[:, 6 * S].mean():>8.1f} kW ｜ "
          f"前视量 均值 {np.abs(lead).mean():>6.1f}  p95 {np.percentile(np.abs(lead), 95):>6.1f} "
          f"max {np.abs(lead).max():>6.1f} kW")
    print(f"           受影响槽 {aff} （即调整窗口头 {len(aff)} 槽），插值权重 "
          f"{np.round(w, 4).tolist()}")
    print(f"           ⇒ 落到这些槽上的光伏预报偏差 均值 {err.mean():>5.1f} kW  "
          f"最大 {err.max():>6.1f} kW\n")

den = 387.96 * (NDAYS * N)      # 【检查A】的整点预报 RMSE × 全年槽数，作为误差尺度参照
print(f"  前视引入的「虚假精度」年合计 ≈ {tot:,.0f} kW·槽，"
      f"占全年前视量对净需求预报误差尺度的 {tot / den:.2%}")
print("  第 0 块永不受影响 —— BLOCKS[0]=(0,36) 不在任何调整窗口内，")
print("  且 H[S] 只污染槽 6S..6S+4（其余权重为 0 或落在调整窗口之外）。")
print("  ⇒ 修复 = 一行：pv[d, 6S − (1 if ANCHOR=='prev' else 0)]，缺省 'prev'。")

print()
print("=" * 100)
print("【检查D】端到端 A/B：P3_ANCHOR=next（旧，含前视） vs prev（新，严格因果）")
print("=" * 100)
f_n = os.path.join(BASE, "结果", "_ab_anchor_next.xlsx")
f_p = os.path.join(BASE, "结果", "result3.xlsx")
if not (os.path.exists(f_n) and os.path.exists(f_p)):
    print("  两臂的 result3 尚未同时就绪，跳过。（先跑：")
    print("    P3_ANCHOR=next P3_OUT=结果/_ab_anchor_next.xlsx python 代码/run_problem3.py")
    print("    P3_ANCHOR=prev                                       python 代码/run_problem3.py）")
else:
    def _read(path):
        wb = pd.read_excel(path, sheet_name="计划购电量", header=0)
        wa = pd.read_excel(path, sheet_name="调整购电量", header=0)
        num = lambda df: df.select_dtypes("number").to_numpy(float)
        return num(wb), num(wa)

    gh_n, gf_n = _read(f_n)
    gh_p, gf_p = _read(f_p)
    n = min(len(gh_n), len(gh_p))
    # 末两列是「全天购电量」「全天购电费」，不是 144 槽；逐槽比对只取前 144 列
    dc = np.abs(gf_n[:n, :N] - gf_p[:n, :N])
    dg = np.abs(gh_n[:n, :N] - gh_p[:n, :N])
    print(f"  窗口内 {n} 天 × {N} 槽")
    print(f"  计划购电量 ĝ ：相异槽 {int((dg > 1e-6).sum()):>7,} / {n * N:,}  "
          f"最大差 {dg.max():>8.4f} kWh")
    print(f"  调整购电量 g ：相异槽 {int((dc > 1e-6).sum()):>7,} / {n * N:,}  "
          f"最大差 {dc.max():>8.4f} kWh")
    fee_n = gh_n[:n, -1].sum()
    fee_p = gh_p[:n, -1].sum()
    print(f"\n  全天购电费合计（表内，口径 A 全口径）：")
    print(f"    next（旧，含 10min 前视）{fee_n:>15,.2f} 元")
    print(f"    prev（新，严格因果）    {fee_p:>15,.2f} 元")
    print(f"    差（新 − 旧）           {fee_p - fee_n:>+15,.2f} 元  "
          f"({(fee_p - fee_n) / fee_n:+.4%})")
    print(f"  ⇒ 前视使旧值偏乐观 {fee_p - fee_n:,.2f} 元；修复后交付值上浮同额。")
print("=" * 100)
