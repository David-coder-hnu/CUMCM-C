# -*- coding: utf-8 -*-
"""问题 4-3：把「高出哨兵 X%」这个数**拆开** —— 结构代价 vs 信息代价。

    python 代码/诊断/diag_p4_oracle.py

背景（为什么需要本脚本）
------------------------------------------------------------------
归档文档反复报「交付 14,257,306 元，高出哨兵 **11.54%**」，并把它当作
「离完美预见的距离」。但那个哨兵与交付模型**约束结构不同**，这个 % 里混着两类
完全不同的东西：

  (1) **信息代价** —— 预报不准、价格未知。不可消除。
  (2) **结构代价** —— 交付模型自己加的约束。可消除（改模型即可）。

具体地，`problem4_3.sentinel()` 的 LP 与交付模型有两处结构差异：

  ★ 差异 1：**日末 SOC 不回位**。
     哨兵只有 S_0 = SOC0 与 S_T = SOC0 两条，全年是一条连续轨迹；
     交付模型每条 `plan_day_recourse` 都强制 **S_{T,ω} = SOC0**，
     即电池每天必须回到 6,000 kWh，**不能跨日搬运能量**。
     这是自加假设（见 problem4_3.py `plan_day` docstring 的「与问题 2 同源的保留」）。

  ★ 差异 2：**0:00–6:00 盲窗没有承诺约束**。
     交付模型 0:00 的 ĝ 是**全天承诺量**，6:00 之前已执行完、只能按 5p 紧急补救；
     6:00 之后才允许按 1.5p 上调（且这种上调还带着 τ'' 分位目标，不是价格最优）。
     哨兵的 `bl = np.arange(*BLOCKS[0])` **只取第 0 天**的 0:00–6:00（36 槽），
     而第 0 天不在计费窗口内 ⇒ **实际全年没有任何盲窗承诺约束**。

于是本脚本造三个 LP，逐层把结构约束加回去：

  A  `sentinel()` 原样                      —— 文档报的 12,782,592（最松）
     ⚠ 这个数**只在 G_MAX=20000 下成立**（哨兵自己也被 `G ≤ G_MAX` 约束；
       在 `G ≤ 5000` 下它是 13,014,628）。故本脚本必须真跑在交付配置上 —— 见下方
       `_p4_env.load()` 那段关于"缓存模块假阴性"的警告。
  B  A + 每日 SOC 回位                       —— 隔离「不能跨日搬运」的代价
  C  B + 全年每日 0:00–6:00 的 G≡GH          —— 隔离「盲窗承诺」的代价
                                              **C 才是与交付模型同结构的完美预见下界**

读数：
    交付 − C = 预报误差 + τ/启发式调参损失   ← **真正"还能努力"的部分**
    C − A    = 模型自选结构的代价             ← 改模型才拿得到，不是调参能拿到的
    A        = 理论地板（同价格口径、同口径 A 计费）

⚠ 本脚本只读，不写任何交付文件。`P4_WRITE=0` 已钉死。
"""
import io
import os
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(BASE, "代码", "诊断"))
import _p4_delivery as _D          # noqa: E402  交付配置的唯一真源
import _p4_env as E                # noqa: E402  同进程内正确加载交付配置（见下）

# ---- 交付配置旋钮：一次给全，任何一项都不能靠缺省（§6.4 陷阱 4） ----
# ⚠ 原来这里是**手抄**的一份旋钮（含 P4_TAUB="0.55,0.42,0.42,0.42"）。τ 一改，手抄的
#   副本不会报错，只会让本脚本的"交付值"变成另一个配置的值 —— 而 `DELIV` 那个数还
#   印在标题上。改从 `problem4_3._DELIVERY` 读，与其余诊断脚本同源。
#
# ⚠⚠ **别再写成 `os.environ.update(_D.delivery()[0])` + `import problem4_3`**（2026-09-12
#   实测踩到，本脚本整个 §7.5 分解因此跑在错的模型上）：
#   `_D.delivery()` 为了读 `_DELIVERY` **自己会 import 一次 `problem4_3`**，那一次是在
#   **缺省环境**下执行的，模块对象被钉进 `sys.modules`；此后那句 `import problem4_3 as P`
#   拿到的**是缓存**，所有 `P4_*` 仍是缺省值。症状：`P.G_MAX` 是 5,000 而不是 20,000，
#   哨兵 A 落在 **13,014,628**（= G≤5000 的哨兵）而不是 **12,782,592**，
#   而标题照印「G_MAX=20000」—— 一个不报错、只是安静跑在别的配置上的假阴性，
#   下游整张「结构代价 vs 信息代价」分解全建在这个错的哨兵上。
#   正确顺序是 `_p4_env.load()`：**先取 env → 写进 os.environ → 再 `importlib.reload`**，
#   且它会在末位断言 `P.is_delivery()`（本脚本不覆写 τ，故断言生效 —— 配置一错就当场炸，
#   不会再安静地出一张表）。
for _k in ("P4_TAU", "P4_TAUB", "P4_TAUP", "P4_OUT", "P4_PSCALE", "P4_PRICE_SRC",
           "P4_GMAX", "P4_ANCHOR", "P4_SENT"):
    # 清掉**进程级残留**：`delivery_env()` 是 `dict(os.environ)` + 覆写，残留会漏进来。
    # 其中 `P4_TAU` 与交付用的 `P4_TAUB` **互斥**，两者同时在会让求解器直接 SystemExit。
    os.environ.pop(_k, None)
P = E.load(P4_GTRAIN="31", P4_WRITE="0", P4_NOWRITE="1", P4_SENT="0")

import numpy as np                      # noqa: E402
from scipy.sparse import coo_matrix     # noqa: E402
from scipy.optimize import linprog      # noqa: E402


def oracle(daily_reset=False, blind_block0=False, verbose=True):
    """完美预见全年 LP（口径 A）。`sentinel()` 的推广版，可逐层加结构约束。

    daily_reset  : 每日日界 SOC 强制 = SOC0（交付模型的结构）
    blind_block0 : 每日 0:00–6:00 强制 G = GH（盲窗承诺，交付模型的结构）
    """
    nd = P.NDAYS
    T = nd * P.N
    N, DT, ETA = P.N, P.DT, P.ETA
    GH, G, C, D, S, E, AP, AN = 0, T, 2 * T, 3 * T, 4 * T, 5 * T + 1, 6 * T + 1, 7 * T + 1
    nv = AN + T
    net = P.actual_net.ravel()[:T]
    pr = P.price_real[:T]
    t = np.arange(T)

    obj = np.zeros(nv)
    obj[GH:GH + T] = pr * DT
    obj[E:E + T] = 5.0 * pr * DT
    obj[AP:AP + T] = 1.5 * pr * DT
    obj[AN:AN + T] = 0.5 * pr * DT

    r_eq, c_eq, v_eq = [], [], []

    def eadd(r, c, v):
        r_eq.append(np.atleast_1d(r)); c_eq.append(np.atleast_1d(c))
        v_eq.append(np.atleast_1d(v))

    # 基准三条（与 sentinel() 逐字相同）
    eadd(0, [S], [1.0])
    eadd(1 + t, S + t + 1, np.ones(T))
    eadd(1 + t, S + t, -np.ones(T))
    eadd(1 + t, C + t, -ETA * DT * np.ones(T))
    eadd(1 + t, D + t, (DT / ETA) * np.ones(T))
    eadd(1 + T, [S + T], [1.0])
    eadd(1 + T + 1 + t, AN + t, np.ones(T))
    eadd(1 + T + 1 + t, AP + t, -np.ones(T))
    eadd(1 + T + 1 + t, G + t, np.ones(T))
    eadd(1 + T + 1 + t, GH + t, -np.ones(T))
    n_eq = 2 * T + 2

    if not daily_reset:
        # A：原样 —— sentinel() 的那条「只第 0 天」的盲窗约束
        bl = np.arange(*P.BLOCKS[0])
        eadd(n_eq + np.arange(len(bl)), G + bl, np.ones(len(bl)))
        eadd(n_eq + np.arange(len(bl)), GH + bl, -np.ones(len(bl)))
        n_eq += len(bl)
    else:
        # B/C：每日日界 SOC 回位  s_{(d+1)N} − s_{dN} = 0
        dd = np.arange(nd)
        eadd(n_eq + dd, S + (dd + 1) * N, np.ones(nd))
        eadd(n_eq + dd, S + dd * N, -np.ones(nd))
        n_eq += nd
        if blind_block0:
            # C：每日 0:00–6:00 的 G ≡ GH
            a0, b0 = P.BLOCKS[0]
            idx = (dd[:, None] * N + np.arange(a0, b0)[None, :]).ravel()
            k = len(idx)
            eadd(n_eq + np.arange(k), G + idx, np.ones(k))
            eadd(n_eq + np.arange(k), GH + idx, -np.ones(k))
            n_eq += k

    A_eq = coo_matrix(
        (np.concatenate(v_eq), (np.concatenate(r_eq), np.concatenate(c_eq))),
        shape=(n_eq, nv)).tocsr()
    # ⚠ b_eq 必须按**唯一行数** n_eq 构造，不能按上面的三元组块逐块拼 ——
    #   COO 把同一 (行,列) 累加，动力学那 4 个 eadd 落在**同一批** T 行上，
    #   逐块拼出来的长度是 8T+38 而 A_eq 只有 2T+38 行，直接 ValueError。
    #   除 S_0、S_T 外所有等式都是齐次的（=0），故只需钉这两行。
    b_eq = np.zeros(n_eq)
    b_eq[0] = P.SOC0
    b_eq[T + 1] = P.SOC0

    r1 = t; r2 = T + t
    r_ub = np.concatenate([r1, r1, r1, r2, r2, r2])
    c_ub = np.concatenate([C + t, G + t, D + t, G + t, D + t, E + t])
    v_ub = np.concatenate([np.ones(T), -np.ones(T), -np.ones(T),
                           -np.ones(T), -np.ones(T), -np.ones(T)])
    A_ub = coo_matrix((v_ub, (r_ub, c_ub)), shape=(2 * T, nv)).tocsr()
    b_ub = np.concatenate([-net, -net])

    lo = np.zeros(nv); hi = np.full(nv, np.inf)
    hi[C:C + T] = P.P_MAX; hi[D:D + T] = P.P_MAX; hi[G:G + T] = P.G_MAX
    lo[S:S + T + 1] = P.SOC_MIN; hi[S:S + T + 1] = P.SOC_MAX

    if verbose:
        print(f"    LP：{nv:,} 变量 / {n_eq:,} 等式 + {2 * T:,} 不等式"
              f"（daily_reset={daily_reset} blind_block0={blind_block0}）", flush=True)
    r = linprog(obj, A_eq=A_eq, b_eq=b_eq, A_ub=A_ub, b_ub=b_ub,
                bounds=list(zip(lo, hi)), method="highs")
    if not r.success:
        print(f"    ❌ LP 失败：{r.message}")
        return None
    x = r.x
    w = slice(P.WIN0 * N, nd * N)
    return dict(
        total=((pr * x[GH:GH + T] * DT)[w].sum() + (1.5 * pr * x[AP:AP + T] * DT)[w].sum()
               + (0.5 * pr * x[AN:AN + T] * DT)[w].sum() + (5.0 * pr * x[E:E + T] * DT)[w].sum()),
        plan=(pr * x[GH:GH + T] * DT)[w].sum(),
        excess=(1.5 * pr * x[AP:AP + T] * DT)[w].sum(),
        breach=(0.5 * pr * x[AN:AN + T] * DT)[w].sum(),
        emerg=(5.0 * pr * x[E:E + T] * DT)[w].sum(),
        kwh_g=(x[G:G + T] * DT)[w].sum(),
        kwh_em=(x[E:E + T] * DT)[w].sum(),
    )


def main():
    OUT = []
    FAILED = []      # ⚠ 见文件末尾：哨兵分解缺臂时**必须**返回非零，不能静默交残表
    def say(s=""):
        print(s, flush=True)
        OUT.append(s)

    say("=" * 100)
    say("问题 4-3 哨兵缺口分解：结构代价 vs 信息代价")
    say("  交付配置：追索 + G_MAX=20000 + τ=%s/%g + 读法B + WQ=0 + 因果锚点"
        % (_D.delivery()[1]["taub_str"], _D.delivery()[1]["taup"]))
    say("=" * 100)
    say(f"  天数 {P.NDAYS} ｜ 计费窗口第 {P.WIN0 + 1}–{P.NDAYS} 天（{P.NDAYS - P.WIN0} 天）"
        f" ｜ SOC0={P.SOC0:,.0f} ｜ G_MAX={P.G_MAX:,.0f}")
    # ⚠ 上面那行 `G_MAX` 是**从模块读的**，不是字面量：本脚本曾因 `_p4_delivery` 的
    #   import 副作用拿到**缓存模块**，标题宣称 20000 而 `P.G_MAX` 实为 5,000，
    #   整张分解因此建在错的哨兵上（见文件头）。把配置判据**逐条印出来**，
    #   让"标题与实得不符"这件事在输出里立刻可见，而不是靠人去比两个数。
    _kn = [x for x in P.delivery_knobs()
           if x.split("=")[0] in ("P4_GMAX", "P4_TAUB", "P4_TAUP", "P4_PRICE_SRC",
                                  "P4_READING", "P4_ANCHOR", "P4_REC")]
    say("  " + "  ".join(_kn) + "   ⇒ is_delivery()="
        + ("✓" if P.is_delivery() else "✗ **不是交付配置，本表不可引用**"))
    say("")

    # ⚠ 这个数**不从本文件抄**：它由 problem4_3._DELIVERY["total"] 声明，而且
    #   `problem4_3.__main__` 会在交付配置下拿实得总费与它硬对账。改 τ 忘了同步，
    #   求解器自己就会报错，不会让本脚本安静地用旧值做分解。
    DELIV = _D.delivery_total()
    say(f"  【交付值】result4-3.xlsx = {DELIV:,.0f} 元"
        f"（= problem4_3._DELIVERY['total']，文档 §0）")
    say("")

    TAGS = {"A": "原样（文档报的那个）",
            "B": "+ 每日 SOC 回位",
            "C": "+ 每日盲窗承诺  ← 与交付模型同结构的完美预见下界"}
    res = {}
    for tag, kw in (("A", dict()),
                    ("B", dict(daily_reset=True)),
                    ("C", dict(daily_reset=True, blind_block0=True))):
        say("  【哨兵 %s】%s" % (tag, TAGS[tag]))
        r = oracle(**kw)
        res[tag] = r
        if r:
            say(f"    总 {r['total']:>13,.0f} 元 ｜ 计划 {r['plan']:>12,.0f} ｜ "
                f"超额 {r['excess']:>10,.0f} ｜ 紧急 {r['emerg']:>9,.0f}")
            say(f"    购电 {r['kwh_g']:>12,.0f} kWh ｜ 紧急 {r['kwh_em']:>10,.0f} kWh")
        say("")

    a, b, c = (res[k]["total"] if res[k] else None for k in "ABC")
    if None in (a, b, c):
        say("❌ 有 LP 失败，下面的分解不可信。")
        # ⚠ 2026-09-12：原先只打印这句、脚本仍 return 0 —— 驱动器按 rc 判成功，一张
        #   **没有分解**的表照样写盘。现已改为在文件末尾返回非零（同 `diag_p4_pscale.py`）。
        FAILED.append("哨兵分解：%s 有 LP 失败" % "、".join(k for k in "ABC" if res[k] is None))
    else:
        # ⚠ 分母口径：归档文档 §0 的「高出哨兵 11.54%」是 (交付−哨兵)/**哨兵**。
        #   本脚本原先误用交付值作分母（得 11.26%），与文档对不上。两个都报，以文档口径为准。
        #   ⚠ 「高出哨兵 X%」本身随交付 τ 变（共享 τ 时是 12.69%）—— 引用时须写明 τ。
        say("=" * 100)
        # ⚠ 原来这里写的是 `("分解（元；%s 列 = …）")` —— 一个**没有参数的 %s**，
        #   于是标题里原地印出字面的「%s 列」。改成讲清楚那两列各是什么。
        say("分解（元；「与交付之差」列 = v − 交付，负 = 比交付便宜；")
        say("      「%」列 = (v − 交付) / 哨兵A，**对齐归档文档 §0 的分母口径**）")
        say("=" * 100)
        rows = [
            ("A 理论地板（无结构约束的完美预见）", a),
            ("B = A + 每日 SOC 回位", b),
            ("C = B + 每日盲窗承诺", c),
            ("交付值", DELIV),
        ]
        for nm, v in rows:
            say(f"  {nm:<38s} {v:>13,.0f}   {v - DELIV:>+13,.0f}   {(v - DELIV) / a * 100:>+7.2f}%")
        say("")
        say("  ★ 拆出来的三段（正向 = 更贵）：")
        say(f"    ① 结构代价·跨日搬运   B − A = {b - a:>+12,.0f} 元  （占交付 { (b - a) / DELIV * 100:>+6.2f}%）")
        say(f"    ② 结构代价·盲窗承诺   C − B = {c - b:>+12,.0f} 元  （占交付 { (c - b) / DELIV * 100:>+6.2f}%）")
        say(f"    ③ 信息 + 调参        交付 − C = {DELIV - c:>+12,.0f} 元  （占交付 { (DELIV - c) / DELIV * 100:>+6.2f}%）")
        say("    ────────────────────────────────────────────")
        say(f"    文档口径「高出哨兵」  交付 − A = {DELIV - a:>+12,.0f} 元  "
            f"（{(DELIV - a) / a * 100:>+6.2f}% of 哨兵）")
        say("")
        # ⚠ 这里原先是 `(a - c)`，**符号写反了**：结构约束把地板从 a **抬到** c，
        #   故结构代价是 `c - a`（正数）。写成 `a - c` 会印出「模型自选结构只占 −3.2%」
        #   —— 一个负的百分比，读者只会当成排版错误，而它其实是把"结构更贵"读成了"更便宜"。
        say(f"  ⇒ 文档报的「高出哨兵 {(DELIV - a) / a * 100:.2f}%」里："
            f"模型自选结构占 { (c - a) / (DELIV - a) * 100:.1f}%，"
            f"信息+调参占 { (DELIV - c) / (DELIV - a) * 100:.1f}%。")

    # ════════════════════════════════════════════════════════════════
    # 第二层：把「信息」再拆一刀 —— 净需求预报误差的代价
    # ════════════════════════════════════════════════════════════════
    # 造一个"净需求完美预报"的因果跑：只把负荷预报 L_base 换成实测、光伏预报 P_hat
    # 换成实测，其余（追索计划层、τ 缓冲、调整层、exec_causal_day 贪婪执行器、
    # 逐日日末 SOC 回位）**一律不动**。于是残差 H0 ≡ 0 ⇒ 分位缓冲 h ≡ 0、
    # 水平校正 r ≡ 1，模型退化成"知道今天净需求"的因果策略。
    #
    # 读法：
    #   交付 − X = **净需求预报误差的代价**（价格仍未知、因果结构仍在）
    #   X − C    = **政策/结构代价**（即使信息完美也还在：贪婪执行器、逐日回位、
    #              0:00 承诺机制本身）
    say("")
    say("=" * 100)
    say("第二层：净需求完美预报（其余旋钮一字不改）")
    say("=" * 100)
    say("  覆盖：L_base := 实测负荷、P_hat := 实测光伏（四档全同）⇒ 残差 0 ⇒ h ≡ 0")
    _Lb, _Ph, _Fh = P.L_base, P.P_hat, P.F_hat
    try:
        P.L_base = P.load.copy()
        P.P_hat = np.stack([P.pv] * 4, axis=1)
        P.F_hat = P.L_base[:, None, :] - P.P_hat
        rx = P.run(1.0)
        x = rx["total"]
        say(f"  总 {x:>13,.2f} 元 ｜ 计划 {rx['plan']:>12,.2f} ｜ 超额 {rx['excess']:>10,.2f} ｜ "
            f"紧急 {rx['emerg']:>9,.2f}")
        say(f"  购电 {rx['kwh_gf']:>12,.0f} kWh ｜ 紧急 {rx['kwh_em']:>10,.0f} kWh")
    finally:
        P.L_base, P.P_hat, P.F_hat = _Lb, _Ph, _Fh
    say("")
    say("  ★ 三分解（正向 = 更贵）：")
    say(f"    (i)  净需求预报误差    交付 − X = {DELIV - x:>+12,.0f} 元  "
        f"（占交付 { (DELIV - x) / DELIV * 100:>+6.2f}%）")
    say(f"    (ii) 政策/结构（信息完美也无法消除）  X − C = {x - c:>+12,.0f} 元  "
        f"（占交付 { (x - c) / DELIV * 100:>+6.2f}%）")
    say(f"    (iii) 纯粹的信息地板        C − A = {c - a:>+12,.0f} 元  "
        f"（占交付 { (c - a) / DELIV * 100:>+6.2f}%）")
    say("")
    say(f"  ⇒ 交付值比完美预见高 {DELIV - a:,.0f} 元，其中 **{ (DELIV - x) / (DELIV - a) * 100:.0f}% "
        f"是净需求预报误差**，{ (x - a) / (DELIV - a) * 100:.0f}% 是模型结构（含贪婪执行器）。")
    say("  ⚠ 「净需求预报误差」这一支里仍含**电价不确定性**：X 那一跑的价格读法仍是 B，")
    say("     0:00 不知道当天实际价。读法 A（价格信息）相对交付只值 126,247 元（§4 表 1）")
    say("     ⇒ 该支很小，故这里不单独再拆。")

    # ════════════════════════════════════════════════════════════════
    # 第三层：把「情景对冲机制」从 X − C 里摘出来
    # ════════════════════════════════════════════════════════════════
    # X 那一跑里，`_scenarios()` 仍按**历史同组日**给出 K 个情景。但此时点预报已经精确，
    # 那批情景的离散度**全部是噪声**，而追索 LP 照样按它对冲 ⇒ 计划被系统性抬高。
    # 把情景集塌成单情景（`_scenarios → Nt[None,:]`，此时追索 LP 退化为确定性 plan_day），
    # 其余一律不动，即得 `X_single`。
    #
    #    X − X_single = **情景对冲机制本身的代价**（信息完美时它纯属空转）
    #   X_single − C  = 剩下与信息无关的结构：贪婪执行器 `exec_causal_day`、0:00 承诺机制
    say("")
    say("=" * 100)
    say("第三层：情景集塌成单情景（仍为完美净需求预报）")
    say("=" * 100)
    _sc = P._scenarios
    try:
        P.L_base = P.load.copy()
        P.P_hat = np.stack([P.pv] * 4, axis=1)
        P.F_hat = P.L_base[:, None, :] - P.P_hat
        P._scenarios = lambda d, Nt: Nt[None, :]
        rs = P.run(1.0)
        xs = rs["total"]
        say(f"  总 {xs:>13,.2f} 元 ｜ 计划 {rs['plan']:>12,.2f} ｜ 超额 {rs['excess']:>10,.2f} ｜ "
            f"紧急 {rs['emerg']:>9,.2f}")
        say(f"  购电 {rs['kwh_gf']:>12,.0f} kWh ｜ 紧急 {rs['kwh_em']:>10,.0f} kWh")
    finally:
        P._scenarios = _sc
        P.L_base, P.P_hat, P.F_hat = _Lb, _Ph, _Fh
    say("")
    say("  ★ 完整四段分解（全部以「交付 − 完美预见」= %s 元 为 100%%）：" % format(DELIV - a, ",.0f"))
    segs = [
        ("净需求预报误差（不可消除）", DELIV - x),
        ("情景对冲空转（信息完美时的机制代价）", x - xs),
        ("贪婪执行器 + 0:00 承诺结构", xs - c),
        ("逐日日末 SOC 回位（自加假设）", c - a),
    ]
    tot = DELIV - a
    for nm, v in segs:
        say(f"    {nm:<34s} {v:>+12,.0f} 元   {v / tot * 100:>6.1f}%")
    say(f"    {'合计':<34s} {tot:>+12,.0f} 元   100.0%")
    say("")
    say(f"  ⇒ **候选项里可努力的最大一块是「{max(segs, key=lambda s: s[1])[0]}」**"
        f"（{max(segs, key=lambda s: s[1])[1]:,.0f} 元）。")
    say("  ⚠ 归因纪律：X − X_single 量的是**机制代价**，不是「应该删掉对冲」——")
    say("     在真实预报下那批情景携带真实信息，对冲是**有偿**的。此处的数只说明")
    say("     「该机制在信息完美时会纯空转」，不能直接当作可回收的节省。")

    # ⚠⚠ **缺臂必须让整个脚本失败**（2026-09-12 加）：同一天在 `diag_p4_readings.py` 上
    #   实测踩到过「四行失败、脚本仍 rc=0」的静默半成品。本脚本没有下面这道闸，就同样会
    #   交出一张缺了分解的残表，而它看上去完全正常。
    if FAILED:
        say("")
        say("!" * 100)
        for f in FAILED:
            say(f"❌ {f}")
        say("   ⇒ 上面的分解**不完整，不可引用**。先卸掉别的重活，再重跑。")
        say("!" * 100)
        OUT.append("")
        OUT.extend(FAILED)

    with open(os.path.join(BASE, "代码", "诊断", "_p4_oracle.txt"), "w",
              encoding="utf-8") as f:
        f.write("\n".join(OUT) + "\n")
    print("\n[已写入] 代码/诊断/_p4_oracle.txt")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
