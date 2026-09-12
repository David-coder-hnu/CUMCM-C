# -*- coding: utf-8 -*-
"""★ 交叉验证：`结果/result4-3.xlsx` 与 `结果/result3.xlsx` 逐元素对照。

    python 代码/诊断/diag_p4_cross.py

这是在验证问题 4 的**头条结论**：「波动电价不改变最优策略，只改变账单」。
它不是推理，而是两份**独立交付物**的逐元素比对 —— 两侧由两个独立脚本、在两条不同的
价格序列下求解，若策略表逐槽相同，则"价格不进入决策"这件事被直接观测到了。

预期（读法 B + WQ=0 + **同 τ** + 同 G_MAX 读法）—— ⚠ **只在共享 τ 的受控消融下成立**：

  - 计划购电量、调整购电量、充放电量、紧急购电量 —— **相异 0**；
  - 唯一差异是**全天购电费列**：13,641,420 → 14,404,088（约 ×1.0559）。

上面那两个数属于**共享 τ** 那一跑。⚠ 自 2026-09-12 第四次起，交付 τ 已是本问自己的
五维最优，**14,404,088 不再是交付值，而是这次受控消融的金额**（消融跑 = 共享 τ + 附件 4）。
交付文件对照（4-3 用本问最优 τ）**必然相异**，其差异来自 τ 而非价格 ——
两种模式的读法见 `main()` 的 docstring 与 `__main__`。

⚠ 两个数都**随基准走**，只作参照，不作判据。**真正的判据是"策略表相异 0"** ——
  它是定性结论，换多少次基准都该成立；而金额会随基准平移（本行已随问题 3 第三次
  定稿从 13,630,568/14,392,700 改为 13,641,420/14,404,088）。

⚠ 三个必须避开的坑（都真踩过）：
  ① 两张表**列序相同**，比较时**两边都不许单方面 `np.roll`**。给任一侧单边 roll 会
     假报「相异 17,315 格」。左移一位的约定是**两边共有的**，直接对齐比较即可。
  ② `调整购电量` 的数值区里可能混着字符串单元格（时间标签），取数值区须
     `to_numeric(errors='coerce')`，否则比较会以 dtype 报错或静默变成字符串比较。
  ③ `ĝ` 表内单位是 **kWh/槽**（不是 kW），算 `Σp·ĝ` 时**不要再乘 Δt**。

本脚本**只读**，不写任何文件，也不 import 任何求解器 —— 它只信 xlsx 本身。
"""
import io
import os
import sys

import numpy as np
import openpyxl

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
N = 144
DT = 1.0 / 6.0


def numeric_region(ws, r0, r1, c0, c1):
    """把 [r0..r1] × [c0..c1] 读成 float 数组；非数值单元格记为 nan。"""
    out = np.full((r1 - r0 + 1, c1 - c0 + 1), np.nan)
    for i, r in enumerate(range(r0, r1 + 1)):
        for j, c in enumerate(range(c0, c1 + 1)):
            v = ws.cell(row=r, column=c).value
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                out[i, j] = float(v)
    return out


def cmp(tag, a, b, tol=5e-5, expect_diff=False):
    """比较两块数组，报 max|差| 与相异格数。

    ⚠ 空值模式必须**两侧一致**才算通过：某表某一列只填了部分行（如 `储电量` 每天只有
       「日初/日末」两格），若只比"两边都非空"的格，会把"一侧缺格"误判成通过。

    expect_diff: 交付文件对照模式下，**相异才是预期的**。此时把记号反过来
      （`≠ 预期` / `= 意外相同`），否则整屏 ✗ 会被读成"对照失败"——而它恰恰是成功。
    """
    assert a.shape == b.shape, f"{tag}: 形状不同 {a.shape} vs {b.shape}"
    both = ~(np.isnan(a) | np.isnan(b))
    mask_mismatch = int((np.isnan(a) != np.isnan(b)).sum())
    d = np.where(both, np.abs(a - b), 0.0)
    n_diff = int((d > tol).sum()) + mask_mismatch
    if expect_diff:
        mark = "≠ 预期" if n_diff else "= 意外相同"
    else:
        mark = "✓" if n_diff == 0 else "✗"
    extra = ""
    if not both.all():
        extra = f"  （非空格 {int(both.sum())}/{d.size}，空值模式{'一致' if not mask_mismatch else f'不一致 {mask_mismatch}'}）"
    print(f"  {tag:<30s} max|差| = {d.max():.5f}  相异 {n_diff} / {d.size}  {mark}{extra}")
    return n_diff


def load(fn):
    """按名字在 结果/ 下找；找不到就当成**绝对/相对路径**直接开（受控消融用的临时表）。"""
    p = os.path.join(BASE, "结果", fn)
    return openpyxl.load_workbook(p if os.path.exists(p) else fn)


def main(fn4="result4-3.xlsx", expect_same=True, title=None):
    """把 4-3 侧的表（`fn4`）与 `结果/result3.xlsx` 逐元素对照。

    ⚠ **`expect_same` 决定结论怎么读**，因为自 2026-09-12 起有**两种**对照，
      它们期望的结果**相反**，混起来会得出相反的话：

      · `expect_same=True` —— **受控消融**：4-3 侧在**与问题 3 共享的 τ** 下跑。
        此时"策略逐元素相异 0"成立，才是「波动电价只改账单、不改策略」的证据。
      · `expect_same=False` —— **交付文件对照**：4-3 侧是**本问最优 τ** 的交付表。
        此时策略**应当**不同（τ 不同 ⇒ 分位不同 ⇒ 计划不同），差异**不是**价格造成的。
        把这一跑读成"价格改变了策略"是**归因错误** —— 见归档 §5.2 第三节的常数价对照。

    早先本脚本只有一种模式，且把"相异 0"硬编码成通过标准；交付 τ 一改，
    它会立刻报 ❌ 而那个 ❌ **毫无信息**（τ 变了本来就不该相同）。

    ⚠ 返回值是**退出码**（0 = 符合该模式的预期），不是相异格数。
    """
    print("=" * 100)
    print(title or f"交叉验证：{fn4}  vs  result3.xlsx")
    print("=" * 100)
    if not expect_same:
        # ⚠ 先声明判据方向，否则整屏的「✗ / 有差异」会被读成对照失败 —— 而此时
        #   它们恰恰是**预期结果**。
        print("⚠ **本跑是「交付文件对照」：相异是预期的**，逐行记号按此读：")
        print("   「≠ 预期」= 两侧不同（应当不同，来自 τ）；「= 意外相同」才需要查。")
        print("=" * 100)
    w4 = load(fn4)
    w3 = load("result3.xlsx")
    assert w4.sheetnames == w3.sheetnames, f"表名不同：{w4.sheetnames} vs {w3.sheetnames}"

    def C(tag, x, y):
        """本跑口径下的比较（记号方向随 `expect_same` 翻转）。"""
        return cmp(tag, x, y, expect_diff=not expect_same)

    def lab(same):
        """标签列全等与否的记号，同样随模式翻转。"""
        if expect_same:
            return "✓ 全等" if same else "✗ 有差异"
        return "≠ 预期（应不同）" if not same else "= 意外相同"

    total_diff = 0
    for sn in ("计划购电量", "调整购电量"):
        print(f"\n【{sn}】（334 天 × 144 槽 + 两个合计列）")
        a = w4[sn]; b = w3[sn]
        assert a.max_row == b.max_row and a.max_column == b.max_column
        nd = a.max_row - 1
        # 144 个槽位：列 2..145；列 146 = 全天购电量；列 147 = 全天购电费
        s4 = numeric_region(a, 2, a.max_row, 2, 1 + N)
        s3 = numeric_region(b, 2, b.max_row, 2, 1 + N)
        total_diff += C("逐槽 144 列", s4, s3)
        e4 = numeric_region(a, 2, a.max_row, 2 + N, 2 + N).ravel()
        e3 = numeric_region(b, 2, b.max_row, 2 + N, 2 + N).ravel()
        total_diff += C("全天购电量列", e4, e3)
        f4 = numeric_region(a, 2, a.max_row, 3 + N, 3 + N).ravel()
        f3 = numeric_region(b, 2, b.max_row, 3 + N, 3 + N).ravel()
        print(f"  {'全天购电费列':<34s} {f3.sum():,.2f} 元 → {f4.sum():,.2f} 元"
              f"   （×{f4.sum() / f3.sum():.6f}）"
              + ("← 受控消融下预期**唯一**差异" if expect_same else "← 本模式下差异不止于此"))
        r = f4 / f3
        print(f"  {'  └ 逐日比值范围':<34s} [{np.nanmin(r):.4f}, {np.nanmax(r):.4f}]"
              f"   全变天数 {int((np.abs(r - 1) > 1e-9).sum())} / {nd}")
        print(f"  {'  └ 逐日 max|差|':<34s} {np.abs(f4 - f3).max():,.2f} 元")
        print(f"  {'Σ 槽位合计':<34s} {np.nansum(s3):,.2f} → {np.nansum(s4):,.2f} kWh"
              f"（{sn}）")

    print("\n【充放电量】（6 块/天 × 334 天 = 2004 行）")
    a = w4["充放电量"]; b = w3["充放电量"]
    assert a.max_row == b.max_row
    # 标签列（时间段 / 时刻）是文本，单独比字符串全等
    for tag, col in (("时间段标签", 2), ("时刻标签", 5)):
        l4 = [a.cell(row=r, column=col).value for r in range(2, a.max_row + 1)]
        l3 = [b.cell(row=r, column=col).value for r in range(2, b.max_row + 1)]
        same = l4 == l3
        print(f"  {tag:<30s} {lab(same)}")
        if not expect_same:
            # 交付文件模式下，标签列相同**不算差异**（时间标签本来就该逐行相同）。
            total_diff += 0
        else:
            total_diff += 0 if same else 1
    for tag, col in (("充电量", 3), ("放电量", 4), ("储电量（日初/日末）", 6)):
        x4 = numeric_region(a, 2, a.max_row, col, col).ravel()
        x3 = numeric_region(b, 2, b.max_row, col, col).ravel()
        total_diff += C(tag, x4, x3)
    # SOC：`储电量` 列每天只填两格 —— 第一行（时刻 0:00）= 日初，第二行（时刻 24:00）= 日末。
    # ⚠ 这两格构成的只是**日界序列**，其范围 [5,118.4, 9,791.4] **不等于日内轨迹范围**；
    #   真实日内轨迹要按 4h 块在块内重建（reconstruct 后恰为 [1200.00, 10800.00]）。
    #   旧归档曾把日界范围当成日内范围，写成"电池几乎不循环"，是错的。
    soc_a = numeric_region(a, 2, a.max_row, 6, 6).ravel()
    st, en = soc_a[0::2], soc_a[1::2]          # 步长 2：日初 / 日末
    print(f"  {'  └ 非空 SOC 格数':<30s} {int(np.isfinite(soc_a).sum())}"
          f"（= 334 天 × 2：日初 + 日末）")
    print(f"  {'  └ 日初 SOC 均值':<30s} {np.nanmean(st):,.1f}")
    print(f"  {'  └ 日末 SOC 均值':<30s} {np.nanmean(en):,.1f}")
    print(f"  {'  └ 日界序列范围 ⚠ 非日内轨迹':<30s} "
          f"[{np.nanmin(soc_a):,.1f}, {np.nanmax(soc_a):,.1f}]")
    print(f"  {'  └ 计费窗末日（12/31）日末 SOC':<30s} {en[np.isfinite(en)][-1]:,.1f}"
          f"（首日日初 {st[0]:,.1f}）")

    print("\n【紧急购电量】（变长明细：每天 0..若干段）")
    a = w4["紧急购电量"]; b = w3["紧急购电量"]
    x4 = np.array([[a.cell(row=r, column=c).value for c in (2, 3)]
                   for r in range(2, a.max_row + 1)], dtype=object)
    x3 = np.array([[b.cell(row=r, column=c).value for c in (2, 3)]
                   for r in range(2, b.max_row + 1)], dtype=object)
    print(f"  {'行数':<34s} {x3.shape[0]} vs {x4.shape[0]}"
          f"  {'✓' if x3.shape == x4.shape else '✗'}")
    lab_same = all((p[0] is None) == (q[0] is None) and (p[0] or "") == (q[0] or "")
                   for p, q in zip(x3, x4))
    # ⚠ 行数/标签列在**两种模式下都应当相同**（对照的是同一段时间轴），故记号不翻转。
    print(f"  {'时间段标签同序':<34s} {'✓ 全等' if lab_same else '✗ 有差异'}")
    e4 = np.array([float(p[1]) if isinstance(p[1], (int, float)) else 0.0 for p in x4])
    e3 = np.array([float(p[1]) if isinstance(p[1], (int, float)) else 0.0 for p in x3])
    # ⚠ 本 sheet 是**变长明细**（每天 0..若干段），行数**可以不同** —— 换 τ 之后段数就会变。
    #   直接 np 比较会因为形状不同而 assert 崩掉，那会把"预期差异"变成一条假故障。
    #   故：行数相同才逐行比；不同则只声明长度差异，改由合计/非零段数承载对照。
    if e4.shape == e3.shape:
        total_diff += C("电量列", e4, e3)
    else:
        print(f"  {'电量列逐行比对':<34s} 跳过（行数不同 {e3.size} vs {e4.size}）"
              f"  {'（预期）' if not expect_same else '⚠ 受控消融下本应相同，须查'}")
        if expect_same:
            total_diff += 1
    print(f"  {'电量合计':<34s} {e3.sum():,.2f} kWh → {e4.sum():,.2f} kWh")
    print(f"  {'非零段数（有紧急购电的段）':<34s} {int((e3 > 0).sum())} vs {int((e4 > 0).sum())}")

    print("\n" + "=" * 100)
    # ⚠ 返回值是**退出码语义**（0=符合预期），不是相异格数 —— 两种模式下"符合预期"
    #   的含义相反，用相异格数当返回值会让交付文件对照**必然 exit 1**（而它其实成功了）。
    if expect_same:
        if total_diff == 0:
            print("✅ 策略表逐元素相异 **0** —— 「波动电价不改变最优策略，只改变账单」得到直接验证。")
            print("   （本跑是**受控消融**：4-3 侧固定在与问题 3 共享的 τ 上；这就是该结论的适用范围。）")
            ok = True
        else:
            print(f"❌ 策略表共有 {total_diff} 格相异 —— 受控消融**不成立**，须查（见文件头三个坑）。")
            ok = False
    else:
        print(f"ℹ️ 策略表共有 {total_diff} 格相异 —— **这是预期的**，不是反例。")
        print("   本跑比较的是**两份交付文件**，而它们的 τ 不同（4-3 = 本问最优 τ，问题 3 = 原 τ）。")
        print("   故差异的**成因是 τ，不是价格**。要问「价格是否改变策略」，须看受控消融")
        print("   （`diag_p4_cross_abl.py`，共享 τ 下跑），不是看这里。")
        if total_diff == 0:
            print("   ⚠ 但两侧**一格都没差** —— 那是异常（τ 不同就该有差），须查是文件取错了还是 τ 没生效。")
            ok = False
        else:
            ok = True
    print("=" * 100)
    return 0 if ok else 1


if __name__ == "__main__":
    # ⚠ 默认走**受控消融**（`--abl`），而不是交付文件对照：后者必然相异，作为默认
    #   会让人把"τ 造成的差异"读成"价格造成的差异"。交付对照要显式 `--deliv`。
    if "--deliv" in sys.argv:
        sys.exit(main(expect_same=False,
                      title="交付文件对照：result4-3.xlsx（本问最优 τ） vs result3.xlsx"
                            " —— 差异预期来自 τ，不是价格"))
    import diag_p4_cross_abl as _abl
    sys.exit(_abl.main())
