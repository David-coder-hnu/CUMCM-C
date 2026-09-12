# -*- coding: utf-8 -*-
"""问题 4-3 的**回看窗口** `P4_GSPAN` 复查（τ 已被重调之后）。

    python 代码/诊断/diag_p4_span.py                      # 用交付 τ
    python 代码/诊断/diag_p4_span.py --tau=0.56,0.36,0.40,0.66,0.30
    python 代码/诊断/diag_p4_span.py --spans=6,7,10

为什么要补这一张表
------------------------------------------------------------------
`P4_GSPAN=7`（分组回看窗口）是**从问题 3 抄来的**，在问题 4 里从未单独扫过。
问题 3 的归档 §5.4 记着一条与本问直接相关的教训：

  > span 6 曾**优于** span 7（13,737,838 vs 13,822,501），一度看起来"问题 3 也该取 6"；
  > **把 τ 调到定稿值后结论翻回来** —— 那次"span 6 更省"是 **τ 未调平的假象**。

即 **span 与 τ 会互相干扰**。本问的 τ 刚刚被重调过（五维搜索，见 `diag_p4_tau_opt.py`），
故"span 7 仍是最优"这句话**必须在新 τ 下重新验证一次**，不能沿用旧 τ 下的结论。

判据：把交付格（追索 + `G` 无上界 + 读法B + WQ=0 + 因果锚点）的 τ 钉住，
只换 `P4_GSPAN`，比总费。**若 7 不在内点最优上，则 §5.2 的 τ 最优也要跟着 span 重扫。**

⚠ 这**不是**把 span 也纳入联合搜索：本脚本只做"7 是不是还在内点"这一个判断。
   真要联合扫，得在 span 的每一档上各自重调一遍五维 τ（代价 = 5 × 本表）。
"""
import io
import os
import subprocess
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(BASE, "代码", "诊断"))
import _p4_delivery as _D          # noqa: E402

SPANS = (6, 7, 10, 14)
OUT = []


def say(s=""):
    print(s, flush=True)
    OUT.append(s)


def _snip():
    return (
        "import sys\n"
        "sys.path.insert(0, r'%s')\n"
        "import problem4_3 as P\n"
        "r = P.run(1.0)\n"
        "print('RESULT|%%.4f' %% (r['total'],))\n" % os.path.join(BASE, "代码")
    )


def run(span, tau):
    env = _D.delivery_env(pin_tau=(list(tau[:4]), tau[4]))
    env.update(P4_GSPAN=str(span), P4_SENT="0", P4_WRITE="0", P4_NOWRITE="1")
    for k in ("P4_PSCALE", "P4_PRICE_SRC", "P4_OUT", "P4_TAU"):
        env.pop(k, None)
    p = subprocess.run([sys.executable, "-c", _snip()], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", env=env, cwd=BASE, timeout=1800)
    for ln in p.stdout.splitlines():
        if ln.startswith("RESULT|"):
            return float(ln.split("|")[1])
    say("      ✗ span=%s 失败：%s" % (span, (p.stderr or p.stdout)[-300:]))
    return None


def main():
    spans = SPANS
    tau = None
    for a in sys.argv[1:]:
        if a.startswith("--spans="):
            spans = tuple(int(x) for x in a.split("=", 1)[1].split(","))
        elif a.startswith("--tau="):
            v = [float(x) for x in a.split("=", 1)[1].split(",")]
            assert len(v) == 5, "--tau 需要五个数（四块分位 + 调整层分位）"
            tau = v
    if tau is None:
        taub, taup = _D.delivery()[1]["taub"], _D.delivery()[1]["taup"]
        tau = list(taub) + [taup]

    say("=" * 100)
    say("问题 4-3 回看窗口 span 复查（交付格，τ 钉死）")
    say("  τ = (%s)/%g   ← 五维搜索的最优 τ" % (", ".join("%g" % x for x in tau[:4]), tau[4]))
    say("=" * 100)
    vals = {}
    for s in spans:
        v = run(s, tau)
        vals[s] = v
        say("  span %-3d → %s 元" % (s, "算不出" if v is None else format(v, ",.2f")))
    ok = {k: v for k, v in vals.items() if v is not None}
    uniq = len(set(round(v, 2) for v in ok.values()))
    say("")
    say("  不同取值 %d/%d %s" % (uniq, len(ok), "✓ 旋钮生效" if uniq > 1 else "✗ 旋钮失效！"))
    if not ok:
        say("❌ 全部失败，不可据此下结论。")
        return 1
    best = min(ok, key=ok.get)
    say("  ⇒ 最优 span = **%d**（%s 元）" % (best, format(ok[best], ",.2f")))
    if 7 in ok and best != 7:
        say("  ⚠⚠ **span 7 不再是内点最优**（差 %s 元）⇒ §5.2 的 τ 最优是在 span=7 上扫的，"
            % format(ok[7] - ok[best], ",.2f"))
        say("     也就是说 τ 与 span 都没定 —— 须在 span=%d 上重跑一遍五维 τ 搜索再定稿。" % best)
    elif 7 in ok:
        say("  ✓ span 7 仍是内点最优，边际 %s 元（%.2f%%）。"
            % (format(min(v for k, v in ok.items() if k != 7) - ok[7], ",.2f"),
               (min(v for k, v in ok.items() if k != 7) - ok[7]) / ok[7] * 100))
        say("     ⇒ 可以继续用继承来的 span=7；但**联合最优未扫**（见文件头最后一段）。")
    # 边界提示：最优落在扫描区间的端点上时不算内点最优。
    if best in (min(ok), max(ok)) and len(ok) > 2:
        say("  ⚠ 最优落在扫描区间的端点（span=%d）⇒ 真最优可能在区间之外，须扩 --spans。" % best)

    with open(os.path.join(BASE, "代码", "诊断", "_p4_span.txt"), "w",
              encoding="utf-8") as f:
        f.write("\n".join(OUT) + "\n")
    print("\n[已写入] 代码/诊断/_p4_span.txt")
    return 0


if __name__ == "__main__":
    sys.exit(main())
