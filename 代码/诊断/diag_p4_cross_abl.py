# -*- coding: utf-8 -*-
"""★ **受控消融**：把问题 4-3 固定在**与问题 3 共享的 τ** 上跑一遍，再与 `result3.xlsx` 逐元素对照。

    python 代码/诊断/diag_p4_cross_abl.py

为什么需要它（这是本仓库最容易搞错的一处归因）
------------------------------------------------------------------
`diag_p4_cross.py` 逐元素对照两份表，得出头条结论「波动电价不改变最优策略，只改变账单」。
但那条结论**成立的前提是两侧 τ 相同** —— 它是个**受控实验**：固定模型超参，只换价格向量。

自 2026-09-12 起，问题 4-3 的**交付 τ 改成了本问自己的最优**（五维搜索，
见 `diag_p4_tau_opt.py`），于是：

  · `结果/result4-3.xlsx`（交付，最优 τ）与 `结果/result3.xlsx`（原 τ）**策略必然不同**；
  · 而这个差异的**成因是 τ，不是价格** —— 拿它当"价格改变了策略"的证据是**归因错误**。

故头条结论必须改由一个**显式的受控消融**承载：本脚本把 4-3 侧钉死在
`problem4_3._SHARED_TAU`（= 问题 3 的交付 τ）上重跑一遍，写到**临时表**（绝不碰交付文件），
再用 `diag_p4_cross.py` 那套判据（含它躲过的三个坑）逐元素比。

判据：**策略表相异 0**。金额会随基准平移，不作判据。

⚠ 与 `_SHARED_TAU` 的一致性：那两个数必须与问题 3 的交付 τ 逐位相同。若问题 3 再定稿改了 τ，
  这条消融就断了 —— 届时须同步 `problem4_3._SHARED_TAU`（`problem4_3` 里已有注释标明）。
"""
import os
import subprocess
import sys

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(BASE, "代码", "诊断"))
import _p4_delivery as _D          # noqa: E402  交付配置与共享 τ 的唯一真源
import diag_p4_cross as _cross     # noqa: E402  复用同一套比较判据（含三个坑的规避）

TMP = os.path.join(BASE, "代码", "诊断", "_p4_abl_shared_tau.xlsx")


def main():
    taub, taup = _D.shared_tau()
    print("=" * 100)
    print("受控消融：问题 4-3 固定在**与问题 3 共享的 τ** 上重跑，再与 result3.xlsx 逐元素对照")
    print("=" * 100)
    print(f"  共享 τ：P4_TAUB={','.join('%g' % x for x in taub)}  P4_TAUP={taup:g}")
    print("  （= 问题 3 的交付 τ；两侧只有「价格如何进入」不同，这才是受控实验）")

    # ⚠ 显式钉死共享 τ，且 **P4_OUT 重定向到临时表** —— 绝不覆盖交付文件。
    #   ⚠⚠ `P4_WRITE=0` / `P4_NOWRITE=1` 在这里**不能设**（2026-09-12 修）：那两行是
    #      "**根本别写盘**"，而 `P4_OUT` 只是"**写到哪个路径**"（`problem4_3.py:1252` 选路径、
    #      `:1451` 由 `DO_WRITE` 整块跳过）。三者同时给出时写盘被整块跳过 ⇒ **临时表根本
    #      不生成** ⇒ 下面 `not os.path.exists(TMP)` 恒真 ⇒ 本消融**每次都报"失败"，
    #      于是从未真正跑成过一次**，而报出来的原因看起来像"求解器崩了"（实为 rc=0、算完 14,404,088）。
    #      隔离靠的是 `P4_OUT` 改道，不是关掉写盘。
    #   用 `delivery_env()`（含完整 os.environ）而不是 `delivery()[0]`：后者是只含 P4_*
    #   的最小环境，子进程会在没有 PATH/SystemRoot 的环境里启动。
    env = _D.delivery_env(pin_tau=(taub, taup))
    env.update(P4_WRITE="1", P4_OUT=TMP, P4_SENT="0")
    env.pop("P4_NOWRITE", None)          # ← 反向别名同样必须清掉
    p = subprocess.run([sys.executable, os.path.join(BASE, "代码", "problem4_3.py")],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", env=env, cwd=BASE)
    if p.returncode != 0 or not os.path.exists(TMP):
        print(f"  ✗ 消融跑失败 rc={p.returncode}（临时表{'已' if os.path.exists(TMP) else '未'}生成）")
        print((p.stderr or p.stdout)[-800:])
        return 1

    print(f"  ✓ 消融表已生成（临时）：{os.path.relpath(TMP, BASE)}")
    try:
        rc = _cross.main(fn4=TMP, expect_same=True,
                         title="受控消融：4-3（共享 τ） vs 问题 3 —— 只换价格向量")
    finally:
        # 临时表用完即删：留在 诊断/ 里会被误当成交付物（.gitignore 也会漏掉它）。
        if os.path.exists(TMP):
            os.remove(TMP)
            print(f"\n[已删除临时表] {os.path.relpath(TMP, BASE)}")
    return 0 if rc == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
