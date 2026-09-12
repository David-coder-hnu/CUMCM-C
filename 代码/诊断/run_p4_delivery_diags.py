# -*- coding: utf-8 -*-
"""换交付 τ 之后，**按序**重跑所有依赖交付配置的诊断。

    python 代码/诊断/run_p4_delivery_diags.py            # 全跑
    python 代码/诊断/run_p4_delivery_diags.py --list     # 只看清单
    python 代码/诊断/run_p4_delivery_diags.py --only audit,cross_abl

为什么要有这个"驱动器"
------------------------------------------------------------------
`diag_p4_tau_opt.py` 一改交付 τ，下面这串诊断的每一张表都作废 —— 它们的标题印着
「交付配置」，数却来自旧 τ。逐个手跑有两个坑，本项目**两个都踩过**：

  ① **漏跑**：漏掉一个，那张表就带着旧数静静地留在归档里，而它看上去完全正常。
  ② **重叠**：这些脚本各自开 `WORKERS=6` 的子进程。两个并发（12 个 python）叠上
     其它会话的重活，把内存压垮，进程被系统杀掉 —— 表现是"**随机**失败"，容易被
     误判成模型或代码的 bug（`diag_p4_quad.py` 文件头记着这次事故的失败率数据）。
     故本驱动器**一律串行**：一个跑完再起下一个。

顺序不是随意的：`run_problem4.py` 必须最先（它才是重写 `结果/result4-3.xlsx` 的那一步），
`audit` 与 `cross_deliv` 必须排在它**之后**（两者审/比的都是那份文件本身），
其余各自独立重解、互相无依赖。
"""
import io
import os
import subprocess
import sys
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DIAG = os.path.join(BASE, "代码", "诊断")

# (键, 相对 BASE 的脚本路径, 附加 argv, 说明)
STEPS = [
    ("deliver", "代码/run_problem4.py", [],
     "重写 结果/result4-3.xlsx（唯一会动交付文件的一步）"),
    ("audit", "代码/诊断/diag_p4_audit.py", [],
     "§6.3 交付表四层独立审计 → _p4_audit.txt"),
    ("readings", "代码/诊断/diag_p4_readings.py", [],
     "表 1 口径矩阵（读法 × 价格源 × WQ）→ _p4_readings.txt"),
    ("pscale", "代码/诊断/diag_p4_pscale.py", [],
     "§5.3 价格缩放 ±30%（4-3 与 4-2 两侧）→ _p4_pscale.txt"),
    ("oracle", "代码/诊断/diag_p4_oracle.py", [],
     "§7.5 哨兵缺口四段分解 → _p4_oracle.txt"),
    ("gmax3", "代码/诊断/diag_p4_gmax3.py", [],
     "§5.5 的 4-3 行：G≤5000 vs 无上界（**交付 τ 钉死**）→ _p4_gmax3.txt"),
    ("cross_abl", "代码/诊断/diag_p4_cross_abl.py", [],
     "§6.1 受控消融（共享 τ）—— 只打屏，不写文件"),
    ("cross_deliv", "代码/诊断/diag_p4_cross.py", ["--deliv"],
     "§6.1b 交付文件对照（本问 τ vs 问题 3 τ）—— **必然相异**，只打屏"),
]


def main():
    only = None
    _bad = [a for a in sys.argv[1:] if a.startswith("--only") and "=" not in a]
    if _bad:
        # ⚠ 不静默降级成"跑全部"：那正是本项目反复踩的"看着对的命令、跑的是另一回事"。
        raise SystemExit("--only 需要写成 --only=audit,cross_abl")
    for a in sys.argv[1:]:
        if a.startswith("--only="):
            only = set(a.split("=", 1)[1].split(","))
    _known = {s[0] for s in STEPS}
    if only is not None and not only <= _known:
        raise SystemExit(f"--only 里有未知步骤：{sorted(only - _known)}；可选 {sorted(_known)}")
    if "--list" in sys.argv:
        for k, p, _, d in STEPS:
            print(f"  {k:<10} {p:<34} {d}")
        return 0

    print("=" * 100)
    print("换交付 τ 后的诊断重跑（**串行**：这些脚本各自开 6 个 worker，重叠会把内存压垮）")
    print("=" * 100)
    todo = [s for s in STEPS if only is None or s[0] in only]
    if not todo:
        print("  --only 没匹配到任何步骤")
        return 1

    fails = []
    t_all = time.time()
    for k, rel, extra, desc in todo:
        print("")
        print("-" * 100)
        print(f"▶ [{k}] {desc}")
        print(f"  $ python {rel} {' '.join(extra)}".rstrip())
        print("-" * 100, flush=True)
        t0 = time.time()
        p = subprocess.run([sys.executable, os.path.join(BASE, rel)] + extra,
                           cwd=BASE, env=dict(os.environ, PYTHONIOENCODING="utf-8"))
        dt = time.time() - t0
        ok = p.returncode == 0
        print("-" * 100)
        print(f"{'✓' if ok else '✗'} [{k}] rc={p.returncode}  用时 {dt / 60:.1f} min", flush=True)
        if not ok:
            fails.append(k)

    print("")
    print("=" * 100)
    print(f"全部跑完，用时 {(time.time() - t_all) / 60:.1f} min")
    if fails:
        print(f"❌ 失败：{', '.join(fails)} —— 相应的表**不可引用**，先修再归档。")
        return 1
    print("✅ 全部步骤成功。接下来核对各 _p4_*.txt 的数，再改归档文档。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
