# -*- coding: utf-8 -*-
"""问题 4-3 的 `G_MAX` 读法对照（`G ≤ 5000` vs `G ≤ 20000` vs `G 无上界`），**交付 τ 钉死**。

    python 代码/诊断/diag_p4_gmax3.py
    python 代码/诊断/diag_p4_gmax3.py --tau=0.58,0.36,0.40,0.70,0.28

它回答 §5.5 那两行：**在交付 τ 下**，把自加的 `G ≤ 5000` 放开值多少钱；
以及"放开"该放到哪个读法上。

为什么需要它（2026-09-12 新增）
------------------------------------------------------------------
归档 §5.5 原先的 4-3 行写着「τ=(0.55,0.42) 保持不变 → 14,790,954 / 14,404,088 / 放开 −386,866 元」。
交付 τ 一改，这一行**两侧的数都要重出**（**新数已写回归档 §5.5**：
14,712,029 / **14,257,306** / **−454,723 元**；本文件头下方那段是当时的原始记录）：
  · 无上界那一侧 = 新的交付值（由 `run_problem4.py` 产出）；
  · `G≤5000` 那一侧**没人算过** —— 旧数是在旧 τ 下量的，直接留用就是拿错误的 τ
    去诋毁保守读法（同一个坑，§5.5 自己已因它翻过一次符号）。

★★ 四个臂，以及为什么不能只跑两个臂（2026-09-12 第二次修）
------------------------------------------------------------------
本脚本原先只有两个臂：`5000` 与 `inf`，且把 `inf` 那格标成「题面字面读法，★交付格」。
**那个标签是错的** —— 交付 `_DELIVERY["gmax"] = 20000`，不是 `inf`（`is_shape()` 用
`abs(G_MAX - 20000) < 1e-9` 判，`inf` 一跑就不算交付配置）。于是那张表里
「★交付格 = 14,258,486」与真正的交付值 14,257,306.50 差了 1,179.68 元，
而表头宣称它就是交付格 —— 又一个名实不符。

更关键的是：**这个差不是模型差**。四臂实测（`G_MAX` 单位是 **kW**，
`hi[GH] = G_MAX` 见 `problem4_3.py:890`）：

    臂              总费(元)        购电峰值(kW)     上界是否紧
    G ≤ 5000        14,712,029.00   5,000.0         **紧**（峰值被压在上界上）
    G ≤ 20000       14,257,306.49   10,172.8        不紧（峰值只有上界的一半）
    G ≤ 1e9         14,257,523.71   10,172.8        不紧
    G = inf         14,258,486.17   10,172.8        不紧

后三臂的峰值**逐位相同**（10,172.8 kW），都远低于各自上界 ⇒ 三个 LP 在数学上
**是同一个问题**，最优值应当相同。可它们给出了 0 / +218 / +1,180 元三个不同的数，
且**随上界数值单调变差**。这是 **HiGHS 的数值性**：上界越大，LP 的系数尺度越差
（equilibration 之后仍偏），单纯形在**退化顶点**间挑到的那个点越偏离真最优。
⇒ 结论有两层：

  ① `5000 → 放开` 的 −453,543 元（3.08%）是**真的**（5000 那一格上界是紧的，真的改了解）；
  ② 而 `20000 → inf` 的 −1,179.68 元（83 ppm）**是求解器噪声，不是建模差异**。
     故交付格取 **20000**：它宽到非紧（>10,172.8 kW），又窄到 LP 尺度最好
     —— 这不是挑数字，是"非紧上界里条件数最好的那个"。

⚠ 本脚本**只钉 τ、只换上界**，不重扫 τ。要让两格**各自调平 τ**，那是
  `diag_p4_quad.py`（四象限）的职责，不是本脚本的 —— 本脚本量的就是"同一个 τ 下
  上界值多少钱"这一个量，故 τ 必须钉死，否则两个变量一起动，差值不可归因。

⚠ 4-2 侧的对应脚本是 `diag_p4_2_gmax.py`（4-2 无 τ）。**注意 4-2 交付用的是 `inf`**
  （`P4_GMAX=inf`），与 4-3 的 `20000` 不同 —— 由上面 ② 可知这不构成口径差异
  （两臂上界都不紧，差的是数值路径），但两边各自与自己文档里写的读法必须一致。
⚠ `P4_OUT` 把盘改道到 `_scratch/`，**绝不碰** `结果/result4-3.xlsx`。
"""
import io
import os
import subprocess
import sys

import pandas as pd

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(BASE, "代码", "诊断"))
import _p4_delivery as _D          # noqa: E402  交付配置与共享 τ 的唯一真源

SCRATCH = os.path.join(BASE, "代码", "诊断", "_scratch")
# ⚠ 臂序 = 上界数值升序。`inf` **不再是** ★交付格（那是旧标签，错的）：交付是 `20000`。
#   `1e9` 这一臂是**对照**，不加它就无法区分"20000 与 inf 的差来自上界本身"还是
#   "来自数值路径" —— 见文件头 ①②。
ARMS = [("G ≤ 5000（自加的保守读法）", "5000"),
        ("G ≤ 20000（★交付格）", "20000"),
        ("G ≤ 1e9（非紧对照臂）", "1e9"),
        ("G 无上界（题面字面读法）", "inf")]
OUT = []


def say(s=""):
    print(s, flush=True)
    OUT.append(s)


def run(gmax, tau):
    os.makedirs(SCRATCH, exist_ok=True)
    out = os.path.join(SCRATCH, "_p43_gmax_%s.xlsx" % gmax)
    # ⚠ 交付配置整体从 `_DELIVERY` 读（`delivery_env` 含完整 os.environ），只把
    #   `P4_GMAX` 换掉。τ 显式钉死，**不靠缺省** —— 缺省 τ 现在是历史值，不是交付值。
    env = _D.delivery_env(pin_tau=(list(tau[:4]), tau[4]))
    env.update(P4_GMAX=gmax, P4_OUT=out, PYTHONIOENCODING="utf-8")
    for k in ("P4_PSCALE", "P4_PRICE_SRC", "P4_NOWRITE", "P4_TAU"):
        env.pop(k, None)
    p = subprocess.run([sys.executable, os.path.join(BASE, "代码", "problem4_3.py")],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", env=env, cwd=BASE, timeout=3600)
    if p.returncode != 0 or not os.path.exists(out):
        return None, (p.stderr or p.stdout)[-400:]
    return (p.stdout, out), None


def peak_kw(path):
    """从写出的表里取购电功率峰值（kW）。

    ⚠ 用 `调整购电量` sheet（= 调整后的最终 `g`，非负），**不是** `计划购电量`（那是 `ĝ`）——
      两者在有调整层时不等（§6.4 陷阱 7）。列区间取 `iloc[:, 1:145]`：**两个汇总列
      （`全天购电量`/`全天购电费`）都在最右**，只排一个会把日总量当成第 145 个槽混进来
      （§6.4 陷阱 6，本项目踩过两次）。
    ⚠ 写盘有左移约定（第 k 列装 `arr[(k+1)%144]`），但**峰值对平移不敏感**，故不还原。
    """
    d = pd.read_excel(path, sheet_name="调整购电量", header=None)
    v = d.iloc[1:, 1:145].apply(pd.to_numeric, errors="coerce").to_numpy(float)
    assert v.shape[1] == 144, "调整购电量 数值区不是 144 列 —— 汇总列没排干净"
    return float(v.max()) * 6.0          # kWh/槽 → kW（Δt = 1/6 h）


def pick(stdout, key):
    hits = [ln.strip() for ln in stdout.splitlines() if key in ln]
    return hits[-1] if hits else ""


def num_after(text, key):
    try:
        return float(text.split(key)[1].split("元")[0].replace(",", "").strip())
    except (IndexError, ValueError):
        return float("nan")


def main():
    tau = None
    for a in sys.argv[1:]:
        if a.startswith("--tau="):
            v = [float(x) for x in a.split("=", 1)[1].split(",")]
            assert len(v) == 5, "--tau 需要五个数（四块分位 + 调整层分位）"
            tau = v
    if tau is None:
        info = _D.delivery()[1]
        tau = list(info["taub"]) + [info["taup"]]

    say("=" * 104)
    say("问题 4-3 G_MAX 读法对照（交付格：追索 + 读法B + WQ=0 + 因果锚点，**τ 钉死**）")
    say("  τ = (%s)/%g   ← 交付 τ（本脚本不重扫 τ，见文件头）"
        % (", ".join("%g" % x for x in tau[:4]), tau[4]))
    say("=" * 104)
    say("{:<38}{:>17}{:>14}".format("读法", "总费(元)", "购电峰值kW"))
    rows = {}
    for lab, gmax in ARMS:
        res, err = run(gmax, tau)
        if res is None:
            say("{:<38}  ✗ 失败：{}".format(lab, err))
            continue
        so, out = res
        # ⚠ 总费只从 stdout 的 `年费 {b['total']:,.0f} 元` 取，**精度到元**（打印就是
        #   `,.0f`）。本表只做"放开上界值多少钱"这一个判断，量级 10⁵，元级足够；
        #   要元以下的精度请看交付值本身（`run_problem4.py` 的 stdout）。
        tot = num_after(pick(so, "年费"), "年费")
        if tot != tot:
            say("{:<38}  ✗ 没解析出总费；problem4_3.py 的打印格式可能改了".format(lab))
            continue
        peak = peak_kw(out)
        rows[gmax] = dict(total=tot, peak=peak)
        say("{:<38}{:>17,.2f}{:>14,.1f}".format(lab, tot, peak))

    say("-" * 104)
    if len(rows) == len(ARMS):
        a, b = rows["5000"], rows["20000"]
        d = b["total"] - a["total"]
        say("  ① **放开上界（5000 → 20000）：{:+,.2f} 元（{:+.2f}%）** —— {}".format(
            d, d / a["total"] * 100, "放开**更便宜**" if d < 0 else "放开**更贵**"))
        tight = abs(a["peak"] - 5000.0) < 1.0
        say("     峰值 {:,.1f} → {:,.1f} kW ⇒ 保守格的上界{}。".format(
            a["peak"], b["peak"],
            "**是紧的**（峰值正好压在上界上，放开真的换了解）" if tight else "未压满 ⚠"))
        if not tight:
            say("     ⚠ 上界没压满 ⇒ 这一格量的不是上界值多少钱，须查。")
        # ── ② 非紧臂之间的散差：这是本脚本真正新增的信息 ──
        nb = [("20000", "20000"), ("1e9", "1e9"), ("inf", "inf")]
        say("")
        say("  ② 三个**非紧**臂（峰值都是 {:,.1f} kW，数学上是同一个 LP）之间：".format(
            rows["20000"]["peak"]))
        base = rows["20000"]["total"]
        for lab, key in nb:
            say("       G ≤ {:<6s}{:>16,.2f} 元   相对 20000 {:+,.2f} 元（{:+.1f} ppm）".format(
                key, rows[key]["total"], rows[key]["total"] - base,
                (rows[key]["total"] - base) / base * 1e6))
        seq = [rows[k]["total"] for _, k in nb]
        mono = all(x <= y for x, y in zip(seq, seq[1:]))
        say("      ⇒ 上界越大越贵，**单调**（{}）⇒ 这是 HiGHS 的数值尺度效应：".format(
            "已实测单调" if mono else "本跑不单调，须查"))
        say("         上界数值越大 ⇒ LP 系数尺度越差 ⇒ 单纯形在退化顶点间挑得越偏。")
        say("         **不是建模差异** —— 若上界真的起作用，峰值会被压到上界上，而它没有。")
        say("      ⇒ 故交付格取 **20000**（宽到非紧、窄到尺度最好），"
            "而 `20000 ↔ inf` 的 83 ppm 不写进结论。")
        peaks = {k: rows[k]["peak"] for _, k in nb}
        if max(peaks.values()) - min(peaks.values()) > 1.0:
            say("      ⚠ 三臂峰值不完全相同（{}）⇒ 非紧的前提有疑，须查。".format(
                "、".join("%s=%.1f" % (k, v) for k, v in peaks.items())))
        say("")
        say("  ⇒ 与四象限（§4 表 1b）的追索行同向；方向才是结论，绝对值随 τ 走。")
        say("  ⚠ 本表 τ **钉死**；要「每格各自调平 τ」请看四象限，两者不可混引。")
    else:
        say("  ✗ 四臂没跑全（实得 {} 臂），不可据此下结论。".format(len(rows)))

    with open(os.path.join(BASE, "代码", "诊断", "_p4_gmax3.txt"), "w",
              encoding="utf-8") as f:
        f.write("\n".join(OUT) + "\n")
    print("\n[已写入] 代码/诊断/_p4_gmax3.txt")
    return 0 if len(rows) == len(ARMS) else 1


if __name__ == "__main__":
    sys.exit(main())
