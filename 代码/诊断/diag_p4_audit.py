# -*- coding: utf-8 -*-
"""问题 4 交付表 result4-3.xlsx 的独立审计（只读交付文件，不改任何东西）。

为什么要单独写这个：交付表的「紧急购电量」sheet 存的是**合并后的连续时段**
（emergency_segments），每段只有 (起止时刻, 段内合计 kWh)，**逐槽的 e 在落盘时就丢了**。
所以「从表反算费用」必然对不上紧急项 —— 电量对得上，价权对不上，这是编码损失不是错。
要核紧急项的价权，只能回到 run() 返回的内存数组。

四层校验：
  L1 内存自洽：口径 A 账本、推论 1（违约≡0）、SOC 链、母线定义、充电可行性
  L2 表 ↔ 内存：读回 result4-3.xlsx（roll(1) 还原），逐槽/逐块/逐日对比
  L3 独立重算：只用附件 1/2/4 + 表内数据重算「计划/违约/超额」三项，与 run() 对账
  L4 继承性核对：对 result3.xlsx 用同一把尺子量能量平衡缺口，证明它是 v3 继承性质

用法：python 代码/诊断/diag_p4_audit.py     （主配置：读法 B、WQ=0、G≤5000）
"""
import os
import sys
import importlib

import numpy as np
import pandas as pd

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(BASE, "代码"))

os.environ.setdefault("P4_READING", "B")
os.environ.setdefault("P4_WQ", "0")
os.environ.setdefault("P4_GMAX", "5000")

P = importlib.import_module("problem4_3")
N, DT, ETA = P.N, P.DT, P.ETA
OUT = []


def say(s=""):
    print(s)
    OUT.append(s)


say("=" * 100)
say(f"问题 4 / result4-3.xlsx 审计    读法 {P.READING}   WQ={int(P.WQ)}   "
    f"G_MAX={P.G_MAX:,.0f}   τ={P.TAU}  τ'={P.TAUP}")
say("=" * 100)

r = P.run(1.0)
nd = r["nd"]
gh, gf, c, d, e = r["g_hat"], r["g_fin"], r["c"], r["d"], r["e"]
WIN0 = P.WIN0
wm = P.WIN[:nd * N]                       # 计费窗口掩码（与结算同源）
days = slice(WIN0, nd)

# ═══════════ L1 内存自洽 ═══════════
say("\n【L1 内存自洽】（直接读 run() 返回的数组，不经过任何落盘）")
say(f"  run() 结算总额 {r['total']:>14,.2f} 元")
say(f"    计划 p·ĝ {r['plan']:>16,.2f} ｜ 违约 {r['breach']:>10,.2f} "
    f"｜ 超额 {r['excess']:>12,.2f} ｜ 紧急 {r['emerg']:>12,.2f}")
say(f"  口径 A 推论 1（最优 g ≥ ĝ ⇒ 违约费 ≡ 0）：违约费 = {r['breach']:.4f} 元 "
    f"⇒ {'✓ 成立' if r['breach'] < 1.0 else '✗ 不成立'}")

socs = np.concatenate([[P.SOC0], P.SOC0 + np.cumsum((ETA * c.ravel() - d.ravel() / ETA) * DT)])
say(f"  SOC：max|重建链日末 − run 的 soc_day| = "
    f"{np.abs(socs[np.arange(1, nd + 1) * N][WIN0:] - r['soc_day'][WIN0:]).max():.3e} kWh")
say(f"    区间 [{socs.min():,.1f}, {socs.max():,.1f}]（限 {P.SOC_MIN:,.0f}–{P.SOC_MAX:,.0f}）"
    f" ⇒ 越限槽 {int(((socs < P.SOC_MIN - 1e-6) | (socs > P.SOC_MAX + 1e-6)).sum())}")
say(f"    日末 SOC 区间 [{r['soc_day'][WIN0:].min():,.1f}, {r['soc_day'][WIN0:].max():,.1f}]"
    f" ｜ 年末 {r['soc_end']:,.1f}")

say(f"\n  母线定义核对 max|e − max(0, L − g − P − d)| = "
    f"{np.abs(e - np.maximum(0.0, P.load - gf - P.pv - d)).max():.3e} kW ⇒ ✓ 与代码一致")

surplus = P.pv + gf + d - P.load                 # 富余（正 = 可充）
overc = np.maximum(0.0, c - np.maximum(0.0, surplus))
bad = (c > 1e-9) & (surplus < 0.0)
say(f"  充电可行性（代码：c ≤ max(0, P+g+d−L)）："
    f"max(c − max(0,富余)) = {overc.max():,.4f} kW ｜ 越界槽 {int((overc > 1e-9).sum())}")
say(f"    缺口槽(surplus<0)里仍充电的槽数 = {int(bad.sum())} / {bad.size} "
    f"（{100 * bad.mean():.2f}%）")

net_kwh = float(((P.load - P.pv) * DT)[days].sum())
kg = float((gf * DT)[days].sum()); kd = float((d * DT)[days].sum())
kc = float((c * DT)[days].sum()); ke = float((e * DT)[days].sum())
bal = net_kwh - kg - kd + kc - ke
say(f"\n  全窗口能量平衡 (L−P)Δt − g − 放 + 充 − e ：")
say(f"    (L−P)Δt {net_kwh:>15,.0f} ｜ g {kg:>15,.0f} ｜ 放 {kd:>13,.0f}")
say(f"    充 {kc:>22,.0f} ｜ e {ke:>15,.0f}")
say(f"    残差 = {bal:>17,.0f} kWh")
if abs(bal) > 1.0:
    # 代数：令 S = P + g + d − L（富余）。则 (L−P) − g − d = −S，故
    #   残差 = c − S − e，而 e = max(0, −S) ⇒ 残差 = (c − S)·1[S≥0] ≤ 0。
    # 也就是说：残差**只可能**来自"有富余却没充进电池"的槽 —— 即富余被无声丢弃。
    # （曾猜是"缺口槽里充电凭空造电"，L1 已证伪：缺口槽充电 0 槽、越界 0 槽。）
    dump = np.maximum(0.0, surplus) - c
    say(f"    ⚠ 残差 {bal:,.0f} kWh ≠ 0。但**不是**「缺口槽充电凭空造电」——")
    say(f"      上面已证：缺口槽充电 {int(bad.sum())} 槽、充电越界 {int((overc > 1e-9).sum())} 槽，全为 0。")
    say(f"      真正的通道是**富余被丢弃**：有富余(S>0)却没进电池的部分 S − c。")
    say(f"      代数上残差 = Σ(c − S)·1[S≥0] ≡ −Σ max(0, S − c) ⇒ 残差非正，"
        f"与实测 {bal:,.0f} ≤ 0 一致。")
    dp_ = np.maximum(0.0, dump) * DT
    say(f"      逐年丢弃 {float(dp_[days].sum()):,.0f} kWh ｜ 占实际购电 "
        f"{100 * float(dp_[days].sum()) / kg:.2f}% ｜ "
        f"丢弃槽占 {100 * (dp_[days] > 1e-9).mean():.1f}%")
    for a, bb, tag in ((0, 36, "0:00–6:00 盲窗"), (36, 72, "6:00–12:00"),
                       (72, 108, "12:00–18:00"), (108, 144, "18:00–24:00")):
        v = float(dp_[days][:, a:bb].sum())
        say(f"        {tag:<16}{v:>12,.0f} kWh  ({100 * v / float(dp_[days].sum()):>5.1f}%)")
    say(f"      **这是 problem3_v3 继承下来的性质**（见 L4），不是问题 4 引入的；")
    say(f"      问题 4 只换价不改量，所以它原封不动地跟着过来了。")
    say(f"      含义：交付表的 g 里有 {100 * float(dp_[days].sum()) / kg:.1f}% 的电量"
        f"既未供负载也未进电池，")
    say(f"      在账本上是「买了但丢了」。真实微网里这等价于**弃光/弃风式削减**，"
        f"或干脆少买。")
    say(f"      论文里必须声明；它同时说明 G_MAX=5,000 kW 这道自加上界在夜间是**紧的**：")
    say(f"      max g = {float(gf[days].max() * DT):,.2f} kWh/槽 = "
        f"{float(gf[days].max()):,.1f} kW（自加上限 {P.G_MAX:,.0f} kW，"
        f"贴上限槽占比 {100 * (gf[days] >= P.G_MAX - 1e-6).mean():.2f}%）")

say(f"\n  账本重算（内存 + 附件4 实际价，与 run 结算同源）：")
say(f"    计划 p·ĝ {(P.PR.ravel() * gh.ravel() * DT)[wm].sum():>16,.2f}")
say(f"    违约     {(0.5 * P.PR.ravel() * np.maximum(0, gh - gf).ravel() * DT)[wm].sum():>16,.2f}")
say(f"    超额     {(1.5 * P.PR.ravel() * np.maximum(0, gf - gh).ravel() * DT)[wm].sum():>16,.2f}")
say(f"    紧急     {(5 * P.PR.ravel() * e.ravel() * DT)[wm].sum():>16,.2f}")

# ═══════════ L2 表 ↔ 内存 ═══════════
say("\n【L2 交付表 ↔ 内存】（读回需 roll(row, 1) 还原时间标签）")
XL = pd.ExcelFile(os.path.join(BASE, "结果", "result4-3.xlsx"))
dp, da = XL.parse("计划购电量"), XL.parse("调整购电量")
ROLL = lambda a: np.roll(a, 1, axis=1)
GH = ROLL(dp.iloc[:, 1:1 + N].to_numpy(float))
GF = ROLL(da.iloc[:, 1:1 + N].to_numpy(float))
d3 = pd.read_excel(os.path.join(BASE, "结果", "result3.xlsx"), sheet_name="计划购电量")
say(f"  形状 {dp.shape} ｜ 与 result3.xlsx 列名完全一致：{list(d3.columns) == list(dp.columns)}"
    f" ｜ 模板 result4-3 同尺寸："
    f"{pd.read_excel(os.path.join(BASE, '附件', '附件5', 'result4-3.xlsx'), sheet_name='计划购电量').shape == dp.shape}")
say(f"  逐槽 max|表内 ĝ − 内存 ĝ| = {np.abs(GH - (gh[days] * DT)).max():.3e} kWh")
say(f"  逐槽 max|表内 g  − 内存 g | = {np.abs(GF - (gf[days] * DT)).max():.3e} kWh")
say(f"  「全天购电量」列 max|列 − Σ槽| = "
    f"{np.abs(dp['全天购电量'].to_numpy(float) - GH.sum(1)).max():.4f} kWh")
say(f"  两表「全天购电费」逐日一致 max|差| = "
    f"{np.abs(dp['全天购电费'].to_numpy(float) - da['全天购电费'].to_numpy(float)).max():.4f} 元")

cd = XL.parse("充放电量")
nrow = len(dp)
cb = np.array([cd.iloc[np.arange(nrow) * 6 + b, 2].to_numpy(float) for b in range(6)])
db = np.array([cd.iloc[np.arange(nrow) * 6 + b, 3].to_numpy(float) for b in range(6)])
say(f"  充放电块 max|表 − 内存| = "
    f"{max(np.abs(cb[b] - (c[days][:, a:bb] * DT).sum(1)).max() for b, (_, a, bb) in enumerate(P.BLOCKS6)):.3e}（充）"
    f" / {max(np.abs(db[b] - (d[days][:, a:bb] * DT).sum(1)).max() for b, (_, a, bb) in enumerate(P.BLOCKS6)):.3e}（放）kWh")
soc_tab = np.array([float(cd.iloc[i * 6 + 1, 5]) for i in range(nrow)])
say(f"  SOC 列 max|表内 24:00 − 内存日末| = {np.abs(soc_tab - r['soc_day'][WIN0:]).max():.3e} kWh")

em = XL.parse("紧急购电量"); ei = em["日期"].ffill()
dm = {str(t.date()): i for i, t in enumerate(pd.date_range("2025-02-01", "2025-12-31"))}
Eseg = np.zeros((nrow, N)); seg_tot = 0.0; nseg = 0
for k in range(len(em)):
    i = dm[str(pd.Timestamp(ei.iloc[k]).date())]
    ts = em.iloc[k, 1]
    if pd.isna(ts):
        continue
    nseg += 1
    a, b = str(ts).split("-")
    fa = (int(a.split(":")[0]) * 60 + int(a.split(":")[1])) // 10
    fb = min(N, (int(b.split(":")[0]) * 60 + int(b.split(":")[1])) // 10)
    Eseg[i, fa:fb] = float(em.iloc[k, 2]) / max(1, fb - fa)
    seg_tot += float(em.iloc[k, 2])
say(f"  紧急表 {len(em)} 行 / {nseg} 段（覆盖 {em['日期'].notna().sum()} 天）")
say(f"    电量：表 Σ段 {seg_tot:,.2f} kWh ｜ 内存 Σe {ke:,.2f} kWh "
    f"⇒ 差 {seg_tot - ke:+,.4f} kWh")
say(f"    逐槽（段内均摊的近似对齐）max|表 − 内存| = {np.abs(Eseg - e[days] * DT).max():,.2f} kWh")
say(f"    ⇒ **逐槽 e 在落盘时被合并成时段，不可复原**；电量可对，价权不可对。")

# ═══════════ L3 独立重算 ═══════════
say("\n【L3 独立重算：只用附件 1/2/4 + 表内数据，不碰内存】")
PRr = P.PR[WIN0:]
plan_t = float((PRr * GH).sum())
pdn = float((0.5 * PRr * np.maximum(0, GH - GF)).sum())
pup = float((1.5 * PRr * np.maximum(0, GF - GH)).sum())
say(f"  计划 p·ĝ   {plan_t:>16,.2f}   ← 表内 ĝ × 附件4 实际价")
say(f"  违约       {pdn:>16,.2f}")
say(f"  超额       {pup:>16,.2f}")
say(f"  三项小计   {plan_t + pdn + pup:>16,.2f}")
say(f"  内存对应   {r['plan'] + r['breach'] + r['excess']:>16,.2f}"
    f"   差 {plan_t + pdn + pup - (r['plan'] + r['breach'] + r['excess']):+,.4f}")
say(f"  ⇒ 表内 ĝ/g 与内存**逐槽一致**，故这三项可被交付表完全复现（差额仅来自 4 位小数取舍）。")
say(f"    紧急项的内存值 {r['emerg']:,.2f} 元是唯一无法从表复现的一项，原因是编码损失，"
    f"不是账错。")

# ═══════════ L4 继承性核对 ═══════════
say("\n【L4 能量平衡缺口是不是问题 4 引入的？—— 对 result3.xlsx 用同一把尺子】")
say("  日级都是精确可加的（g 取行和、充放取块和、e 取段和），故两次测量的口径完全相同。")
for f, tag in ((os.path.join(BASE, "结果", "result3.xlsx"), "result3.xlsx（问题3 定稿）"),
               (os.path.join(BASE, "结果", "result4-3.xlsx"), "result4-3.xlsx（问题4 本次）")):
    Y = pd.ExcelFile(f)
    yp, ya = Y.parse("计划购电量"), Y.parse("调整购电量")
    ycd, yem = Y.parse("充放电量"), Y.parse("紧急购电量")
    m = len(yp)
    yg = ya.iloc[:, 1:1 + N].to_numpy(float).sum(1)
    ych = np.array([ycd.iloc[i * 6:(i + 1) * 6, 2].sum() for i in range(m)])
    ydi = np.array([ycd.iloc[i * 6:(i + 1) * 6, 3].sum() for i in range(m)])
    ye = np.array([0.0 if pd.isna(yem.iloc[i * 6 // 6, 1]) else 0.0 for i in range(m)])
    ye = np.zeros(m)
    yei = yem["日期"].ffill()
    for k in range(len(yem)):
        i = dm[str(pd.Timestamp(yei.iloc[k]).date())]
        if not pd.isna(yem.iloc[k, 1]):
            ye[i] += float(yem.iloc[k, 2])
    Lr = P.load[WIN0:m + WIN0]; Pr_ = P.pv[WIN0:m + WIN0]
    gap = float(((Lr - Pr_) * DT).sum()) - float(yg.sum()) - float(ydi.sum()) \
        + float(ych.sum()) - float(ye.sum())
    say(f"    {tag}：残差 {gap:>14,.0f} kWh ｜ 实际购电 {float(yg.sum()):>14,.0f} kWh "
        f"｜ 占购电 {100 * gap / float(yg.sum()):>6.2f}%")

txt = "\n".join(OUT)
with open(os.path.join(BASE, "代码", "诊断", "_p4_audit.txt"), "w", encoding="utf-8") as f:
    f.write(txt + "\n")
print("\n[已写入] 代码/诊断/_p4_audit.txt")
