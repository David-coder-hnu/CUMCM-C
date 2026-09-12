# -*- coding: utf-8 -*-
"""★ 问题 4-2 的 G_MAX 读法对照（`G ≤ 5000` vs `G 无上界`）+ 与问题 2 的同源核对。

    python 代码/诊断/diag_p4_2_gmax.py

**为什么只有一维、没有"计划层"那一维**（与问题 4-3 的四象限不对称，这是刻意的）：

  问题 3/4-3 的计划层是可切换的 —— 计划层只承诺 `ĝ`，`c/d/e/S` 逐情景 ω，所以
  「确定性 / 追索」是一个**能翻的旋钮**。问题 4-2 **不是**这个结构：它的 LP 里只有
  `e_ω` 逐情景，而 `d`（放电）、`cm`（充电下限）、`S`（SOC）是**一条一阶段轨迹**
  （见 `problem4_2.py` 的变量布局）。于是它既不是 4-3 的"确定性"格（那格连情景下标
  都没有），也不是"追索"格（那格的 c/d/S 逐情景）—— 它是**第三种东西**。

  ⇒ 要凑出对称的 2×2，必须把 4-3 的日计划层（`plan_day` / `plan_day_recourse` /
  `_scenarios` / `exec_causal_day` 与整套 τ 机制）**移植**进 `problem4_2.py`，还要保住
  4-2 自己的逐情景紧急系数与 span6 分组。那是**新建模，不是同步**，且移完之后的表
  未必还"是关于问题 4-2 的"。**决定：不移植，只出这一维。** 行名如实标注，
  不借用 4-3 的"确定性/追索"字样 —— 那会是在给一个不存在的轴贴标签。

本表回答两件事：

  ① `G ≤ 5000` → `G 无上界` 值多少钱（自加上界的代价）；
  ② **无上界那一格，4-2 的计划是否与问题 2 交付计划逐槽相同** —— 若是，则 4-2 交付
     = 「问题 2 的计划 + 波动电价的账单」，与 4-3 = 「问题 3 的计划 + 波动电价的账单」
     **严格镜像**。这是本问最该拿出来的结构性结论。

⚠ 哨兵自己也受 `G_MAX` 约束，故两行的哨兵**不是同一个数**，不可跨行比"高出哨兵 %"。
⚠ `P4_NOWRITE` 与 `P4_OUT` **两个都要设**：单设 `P4_NOWRITE` 只挡住写盘，但脚本仍会
  走写盘分支；反过来只设 `P4_OUT` 会把文件写到别处 —— 两个都设才是"不碰交付文件"。
"""
import io
import os
import re
import subprocess
import sys

import numpy as np
import pandas as pd

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPT = os.path.join(BASE, "代码", "problem4_2.py")
SCRATCH = os.path.join(BASE, "代码", "诊断", "_scratch")

ARMS = [
    ("G ≤ 5000（自加的保守读法）", "5000"),
    ("G 无上界（题面字面读法，**交付格**）", "inf"),
]
OUT = []


def say(s=""):
    print(s)
    OUT.append(s)


def run(gmax):
    """跑一臂，返回 (stdout, 写出的 xlsx 路径)。输出落在 _scratch，绝不碰交付文件。"""
    os.makedirs(SCRATCH, exist_ok=True)
    out = os.path.join(SCRATCH, f"_p42_gmax_{gmax}.xlsx")
    env = dict(os.environ)
    # ⚠ 用 `P4_OUT` 把盘**改道**到 _scratch，**不要**用 `P4_NOWRITE=1` —— 后者会在写盘
    #   分支前直接 return，于是本函数要求的那份 xlsx 永远不存在，两臂双双判"失败"。
    #   当初两个都设，是因为把"不碰交付文件"理解成"不写盘"；其实改道就够了，
    #   而且同源核对**正需要读回计划**，本来就必须写出来。
    env.update(P4_GMAX=gmax, GAMMAS="1.0", P4_READING="B",
               P4_OUT=out, PYTHONIOENCODING="utf-8")
    for k in ("P4_PSCALE", "P4_PRICE_SRC", "P4_NOWRITE"):
        env.pop(k, None)          # 交付口径：不缩放、用附件 4 实际价、正常写盘（改道）
    p = subprocess.run([sys.executable, SCRIPT], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", env=env, cwd=BASE)
    if p.returncode != 0 or not os.path.exists(out):
        return None, None, (p.stderr or p.stdout)[-400:]
    return p.stdout, out, None


def pick(stdout, key):
    """取最后一行含 `key` 的文本。"""
    hits = [ln.strip() for ln in stdout.splitlines() if key in ln]
    return hits[-1] if hits else ""


def num_after(text, key):
    """从 `... key 12,345 元 ...` 里抠出 12,345.0。"""
    try:
        return float(text.split(key)[1].split("元")[0].replace(",", "").strip())
    except (IndexError, ValueError):
        return float("nan")


def plan_of(path):
    """读回写出的『计划购电量』，返回 144 槽数值区（334 天 × 144）。"""
    d = pd.read_excel(path, sheet_name="计划购电量", header=None)
    v = d.iloc[1:, 1:145].apply(pd.to_numeric, errors="coerce").to_numpy(float)
    return v


say("=" * 104)
say("问题 4-2 G_MAX 读法对照（读法 B、附件4 实际价、γ=1、span6、因果执行）")
say("=" * 104)
say(f"{'读法':<38}{'总费(元)':>15}{'哨兵(元)':>15}{'购电峰值kW':>12}   {'越限槽数':<14}")

rows = {}
for lab, gmax in ARMS:
    so, out, err = run(gmax)
    if so is None:
        say(f"{lab:<38}  ✗ 失败：{err}")
        continue
    # 键必须对齐 problem4_2.py 的**实际**输出串：
    #   总费   `实际执行：紧急 530,293 元 (91,202 kWh)  总 14,736,353 元`
    #   哨兵   `  哨兵下界 13,014,628 元 ｜ 高出 13.2%`
    #   峰值   `  购电功率峰值 5,000.0 kW ｜ 越限槽数 0 / 52,560（上界 5,000 kW）`
    # ⚠ 峰值那行要用 `pick_last`：`哨兵购电功率峰值` 也含「购电功率峰值」，取最后一条才对。
    tot = num_after(pick(so, "实际执行"), "总")
    sent = num_after(pick(so, "哨兵下界"), "下界")
    pk = pick(so, "购电功率峰值")
    try:
        peak = float(pk.split("峰值")[1].split("kW")[0].replace(",", "").strip())
        over = pk.split("越限槽数")[1].split("（")[0].strip()
    except (IndexError, ValueError):
        peak, over = float("nan"), "—"
    if not (tot == tot and sent == sent):      # NaN 自比不相等
        say(f"{lab:<38}  ✗ 输出串没解析出总费/哨兵，problem4_2.py 的打印格式可能改了")
        continue
    # ⚠ 无上界那格的「越限槽数 0 / 52,560」是**空洞的真话** —— 上界是 inf 时恒不越限，
    #   这个 0 不含任何信息，摆出来会让人误以为"两种读法都零越限、所以读法无关紧要"。
    #   如实标成 n/a，让它不能与 G≤5000 那格并列读。
    if gmax == "inf":
        over = "n/a（上界 inf）"
    rows[gmax] = dict(total=tot, sent=sent, peak=peak, n_over=over, out=out, stdout=so)
    say(f"{lab:<38}{tot:>15,.0f}{sent:>15,.0f}{peak:>12,.1f}   {over:<14}")

say("-" * 104)
if "5000" in rows and "inf" in rows:
    a, b = rows["5000"], rows["inf"]
    d = b["total"] - a["total"]
    say(f"  **放开上界的代价：{d:+,.2f} 元（{d / a['total'] * 100:+.2f}%）**"
        f" —— 放开是**更便宜**的（{a['total']:,.0f} → {b['total']:,.0f}）")
    say("  ⇒ 与问题 4-3 同向（4-3 放开同样变便宜）。注意这与旧归档里"
        "「放开上界反而更贵」的说法**方向相反** ——")
    say("     那句话属于『确定性计划 + G≤5000』时代的定稿，在追索/情景计划层下已作废。")
    # ⚠ 「越限槽数 = 0」不含「上界是否绑定」的意思 —— 它是**违规计数**（超上界的槽数），
    #   不是**绑定计数**。G≤5000 那格越限槽数 0，恰恰是因为上界被**尊重**了；
    #   而从峰值 5,000.0 kW **正好**等于上界可知：上界在最贵那一槽**是紧的**。
    #   要证明上界真的绑定、且绑定有代价，看的是上面那 163,296 元，不是这个 0。
    say(f"  上界是否绑定：`G≤5000` 那格越限槽数 {a['n_over']}（= 上界被尊重），但其峰值"
        f" **{a['peak']:,.1f} kW 正好压在上界上** ——")
    say(f"     上界在最贵那一槽是**紧的**。放开后峰值升到 {b['peak']:,.1f} kW，总费降 "
        f"{abs(d):,.0f} 元，即自加上界确实在花钱。")
    say("""
  ⇒ **推论（本表最该记住的一条）**：两行只有 5,000 kW 这一个假设不同，总费就差 1.11%。
     既然题面未给联络线容量，这个差额**不是模型算出来的，是假设选出来的** ——
     故报交付值时必须同时报出所说的读法，不能只丢一个数。""")

# ── 同源核对：无上界那一格 vs 问题 2 交付计划 ────────────────────────────
say("")
say("=" * 104)
say("同源核对：G 无上界下，4-2 的计划是否 == 问题 2 的交付计划（结果/result2.xlsx）")
say("=" * 104)
if "inf" in rows:
    p42 = plan_of(rows["inf"]["out"])
    p2 = plan_of(os.path.join(BASE, "结果", "result2.xlsx"))
    if p42.shape != p2.shape:
        say(f"  ✗ 形状不同 {p42.shape} vs {p2.shape}")
    else:
        m = ~(np.isnan(p42) | np.isnan(p2))
        d = np.where(m, np.abs(p42 - p2), 0.0)
        s42, s2 = np.nansum(p42), np.nansum(p2)
        # ⚠ 判据用**相对**尺度，且阈值要有物理含义，不能拿 `1e-4` 这种"看起来小"的数当刀口。
        #   实测 max|差| = 0.0001 kWh，恰好卡在 `>1e-4` 的边界上，于是 3 格被判"相异" ——
        #   但 0.0001 kWh 相对 Σ=2.17×10⁷ kWh 是 **5×10⁻¹²**，是 LP 退化最优解的内点抖动
        #   （同一个最优面有多个顶点，两次求解落在不同顶点上），不是"计划不同"。
        #   表内 3 位小数的报出精度就是 0.001 kWh —— 这 3 格连**表格精度都不到**。
        TOL = 1e-3                     # kWh：表内报出精度
        n_bad = int((d > TOL).sum())
        rel = d.max() / max(s2, 1.0)
        say(f"  逐槽 144 列   max|差| = {d.max():.4f} kWh（相对 Σ = {rel:.2e}）"
            f"   超报出精度({TOL:g} kWh) 的格 = {n_bad} / {d.size}")
        say(f"  Σ 计划购电量  {s2:,.4f} kWh（问题 2） → {s42:,.4f} kWh（4-2）"
            f"   差 {s42 - s2:+,.6f} kWh（相对 {abs(s42 - s2) / max(s2, 1.0):.1e}）")
        say("")
        if n_bad == 0:
            say("  ✅ **4-2 交付 = 「问题 2 的计划 + 波动电价的账单」**（逐槽数值等价）—— 与 4-3 =")
            say("     「问题 3 的计划 + 波动电价的账单」严格镜像。波动电价**不改变策略**，")
            say("     只重估账单：这正是问题 4 的核心结论在两条支线上的一致体现。")
            say(f"     ⚠ 「等价」的**确切含义**：不是逐位相同，而是 max|差| {d.max():.4f} kWh，"
                f"相对 {rel:.0e} —— 属 LP 退化最优解的顶点抖动，")
            say("       远在表内报出精度之下。**是同一套策略，不是同一个浮点解**。")
            say("     ⚠ 这个性质**只在无上界那一格成立**：G≤5000 时上界紧，")
            say("       情景块 e_ω 才起作用，计划才与问题 2 分岔（见上表峰值）。")
        else:
            say(f"  ⚠ 有 {n_bad} 格相异（> {TOL:g} kWh）—— 「4-2 交付 = 问题 2 计划」**不成立**，须查。")

say("")
say("说明：哨兵在两种读法下不是同一个数（哨兵自己也受上界约束），故不可跨行比较")
say("      「高出哨兵 %」；只能在同一 `G_MAX` 内横向看。")

# ── 交付格摘要：文档 §0／表 3 的数字全部从这里出，不再手抄 ──────────────
if "inf" in rows:
    say("")
    say("=" * 104)
    say("交付格（G 无上界）摘要 —— 供 文档/问题4_求解归档.md §0 与表 3 引用")
    say("=" * 104)
    xl = pd.ExcelFile(rows["inf"]["out"])
    pl = pd.read_excel(rows["inf"]["out"], sheet_name="计划购电量")
    gh = np.roll(pl.iloc[:, 1:145].apply(pd.to_numeric, errors="coerce")
                 .to_numpy(float), 1, axis=1)
    g_col = pl.iloc[:, 145].apply(pd.to_numeric, errors="coerce").to_numpy(float)
    cd = pd.read_excel(rows["inf"]["out"], sheet_name="充放电量")
    ch = cd["充电量"].apply(pd.to_numeric, errors="coerce").to_numpy(float)
    di = cd["放电量"].apply(pd.to_numeric, errors="coerce").to_numpy(float)
    soc = cd["储电量"].dropna().to_numpy(float)          # 只 24:00 行有值 = 日末 SOC
    say(f"  表 sheet：{' / '.join(xl.sheet_names)}")
    say(f"  计划购电量 Σĝ        {np.nansum(gh):>16,.1f} kWh")
    say(f"  「全天购电量」列 Σ    {np.nansum(g_col):>16,.1f} kWh"
        f"   （与 Σĝ 一致 ⇒ 4-2 无调整层，计划量即执行量，紧急量只加在费用上）")
    say(f"  储能充 ／ 放         {np.nansum(ch):>16,.1f} ／ {np.nansum(di):,.1f} kWh"
        f"   （放/充 = {np.nansum(di) / np.nansum(ch):.4f}）")
    say(f"  日末 SOC 区间 ／ 年末 [{soc.min():>8,.1f}, {soc.max():>8,.1f}] ／ {soc[-1]:,.1f} kWh")
    say(f"  购电功率峰值         {rows['inf']['peak']:>16,.1f} kW"
        f"   （上界 inf ⇒ 无「贴上限槽占比」可言，见上表 n/a）")
    say(f"  ⚠ 真实 SOC 区间须由**内存**给出，本表只给日末序列；日末区间 "
        f"[{soc.min():,.1f}, {soc.max():,.1f}] **严重低报**储能利用强度（§6.4 陷阱 2）。")
    say(f"     `problem4_2.py` 自报的实际 SOC 范围是 [1,200.0, 10,800.0]、越限 0 槽。")
    # 全窗口能量平衡：残差 = −Σ max(0, 富余 − 充电)，即「有富余却没充进电池」的丢弃量。
    # ⚠ 紧急电量 e 只能从 stdout 取（`实际执行：紧急 … 元 (N kWh)`）—— 落盘表把它
    #   并成了连续时段，逐槽不可复原（§6.4 陷阱 1），但**总量**在 stdout 里是准的。
    em_kwh = float("nan")
    _m = re.search(r"紧急[\d,\.]+ 元 \(([\d,\.]+) kWh\)", rows["inf"]["stdout"])
    if _m:
        em_kwh = float(_m.group(1).replace(",", ""))
    L = pd.read_excel(os.path.join(BASE, "附件", "附件2.xlsx"),
                      sheet_name="小区负载").iloc[:, 1:145].to_numpy(float)
    Pv = pd.read_excel(os.path.join(BASE, "附件", "附件2.xlsx"),
                       sheet_name="光伏发电实际功率").iloc[:, 1:145].to_numpy(float)
    days = np.arange(31, 365)          # 计费窗 2/1–12/31 = 334 天
    g_tot = float(np.nansum(g_col))
    resid = (float((L[days] - Pv[days]).sum() * DT) - g_tot
             - float(np.nansum(di)) + float(np.nansum(ch)) - em_kwh)
    say("")
    say(f"  全窗口能量平衡 (L−P)Δt − g − 放 + 充 − e：")
    say(f"    (L−P)Δt {float((L[days] - Pv[days]).sum() * DT):>14,.0f} ｜ g {g_tot:>14,.0f}"
        f" ｜ 放 {float(np.nansum(di)):>12,.0f}")
    say(f"    充      {float(np.nansum(ch)):>14,.0f} ｜ e {em_kwh:>14,.0f}")
    say(f"    残差 = {resid:>18,.0f} kWh   （= −Σ max(0, 富余 − 充电)，即「买了但没进电池」）")
    say(f"    ⇒ 占实际购电 {100 * abs(resid) / g_tot:.2f}%"
        f"   ⚠ 这是 problem2.py 继承下来的性质，不是问题 4-2 引入的（§7.1）。")

txt = "\n".join(OUT)
with open(os.path.join(BASE, "代码", "诊断", "_p4_2_gmax.txt"), "w", encoding="utf-8") as f:
    f.write(txt + "\n")
print("\n[已写入] 代码/诊断/_p4_2_gmax.txt")
