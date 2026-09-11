# -*- coding: utf-8 -*-
"""问题 4 敏感性：实际结算价整体缩放 ±30%（5% 步长）—— 文献 3 的规范。

预期（可证）：口径 A 的四项费用 p·ĝ、0.5p、1.5p、5p 都是**同一个 p 的倍数**，
所以对 p 做均匀缩放不改变任何边际权衡 ⇒
  · 最优策略（ĝ, g, c, d, e）**逐槽不变**；
  · 账单**精确线性缩放**，total(s) = s · total(1)。

本脚本的价值不在"再跑一遍"，而在于**实测确认上述两条**：
如果策略随 s 变了，说明模型里还有一处价格进入了非对称的位置（那才需要写进论文）。

实现说明：problem4_3 是可 import 的模块 → 用 importlib.reload 在进程内循环（省去重复读盘）；
problem4_2 是顶层脚本，没有 run() 入口 → 只能每档起一个子进程。

用法：python 代码/诊断/diag_p4_pscale.py
"""
import os
import subprocess
import sys
import importlib

import numpy as np
import pandas as pd

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(BASE, "代码"))

SCALES = [round(0.70 + 0.05 * k, 2) for k in range(13)]      # 0.70 … 1.30
OUT = []


def say(s=""):
    print(s)
    OUT.append(s)


# ══════════════════ problem4_3：进程内 reload ══════════════════
os.environ["P4_READING"] = "B"
os.environ["P4_WQ"] = "0"
os.environ["P4_GMAX"] = "5000"
os.environ["P4_NOWRITE"] = "1"

say("=" * 96)
say("问题 4-3 敏感性：实际结算价整体缩放（读法 B、WQ=0、G ≤ 5000 kW）")
say("=" * 96)
say(f"{'缩放':>6}{'总费(元)':>16}{'计划 p·ĝ':>16}{'超额':>14}{'紧急':>13}"
    f"{'相对基准':>12}{'策略是否逐槽不变':>18}")

P = importlib.import_module("problem4_3")
res43 = {}
for s in SCALES:
    os.environ["P4_PSCALE"] = str(s)
    P = importlib.reload(P)
    r = P.run(1.0)
    # 策略指纹：五个决策数组。s=1.00 那一档作为"是否逐槽不变"的基准。
    res43[s] = (r, (r["g_hat"], r["g_fin"], r["c"], r["d"], r["e"]))

t100 = res43[1.00][0]["total"]
ref = res43[1.00][1]
allsame = True
for s in SCALES:
    r, pol = res43[s]
    if abs(s - 1.0) < 1e-9:
        rel, same = "—（基准）", "—（基准）"
    else:
        ok = all(np.array_equal(a, b) for a, b in zip(pol, ref))
        allsame &= ok
        rel = f"{(r['total'] / t100 - 1) * 100:+.2f}%"
        same = "✓ 一致" if ok else "✗ 有差异"
    say(f"{s:>6.2f}{r['total']:>16,.2f}{r['plan']:>16,.2f}{r['excess']:>14,.2f}"
        f"{r['emerg']:>13,.2f}{rel:>12}{same:>12}")

lin = max(abs(res43[s][0]["total"] - s * t100) for s in SCALES)
say(f"\n  线性性核对 max|total(s) − s·total(1.00)| = {lin:,.6f} 元"
    f" ⇒ {'✓ 精确线性' if lin < 1e-4 else '✗ 非线性'}")
say(f"  策略逐槽不变（ĝ/g/充/放/紧急 五数组逐元素相等）："
    f"{'✓ 13 档全部一致' if allsame else '✗ 存在差异，见上表'}")
say("  含义：波动电价的**水平**不影响决策，只影响账单；真正进入决策的是")
say("  「价格 × 缺口」的**联合分布形状**（日内形状 84.6%），而它不随缩放改变。")

# ══════════════════ problem4_2：子进程 ══════════════════
say("")
say("=" * 96)
say("问题 4-2 敏感性：实际结算价整体缩放（读法 B、G ≤ 5000 kW）")
say("=" * 96)
say(f"{'缩放':>6}{'总费(元)':>18}{'相对基准':>12}   说明：取自写盘后的 result4-2 表（逐日购电费求和），"
    f"不受 stdout 取整影响")
env = dict(os.environ)
env.update(P4_READING="B", P4_GMAX="5000", GAMMAS="1.0", PYTHONIOENCODING="utf-8")
env.pop("P4_NOWRITE", None)      # ← 必须去掉：4_3 段设过它，会顺着 os.environ 漏进来
tmpdir = os.path.join(BASE, "代码", "诊断")
tot42 = {}
for s in SCALES:
    env["P4_PSCALE"] = str(s)
    out = os.path.join(tmpdir, f"_p4_2_pscale_{s:.2f}.xlsx")
    env["P4_OUT"] = out                     # 写到诊断目录，绝不碰交付文件
    p = subprocess.run([sys.executable, os.path.join(BASE, "代码", "problem4_2.py")],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", env=env, cwd=BASE)
    if p.returncode != 0 or not os.path.exists(out):
        say(f"{s:>6.2f}   ✗ 运行失败 rc={p.returncode}：{p.stdout[-200:]}{p.stderr[-300:]}")
        continue
    tot42[s] = float(pd.read_excel(out, sheet_name="计划购电量")["全天购电费"].sum())
    os.remove(out)
b2 = tot42.get(1.00)
for s in SCALES:
    if s not in tot42:
        continue
    rel = "—（基准）" if abs(s - 1.0) < 1e-9 else f"{(tot42[s] / b2 - 1) * 100:+.2f}%"
    say(f"{s:>6.2f}{tot42[s]:>18,.2f}{rel:>12}")
if b2 is not None:
    l2 = max(abs(v - s * b2) for s, v in tot42.items())
    # 容差必须按"表内逐日 2 位小数取舍"来定：334 天 × 0.005 元 = 1.67 元。
    # 比这更严的阈值只会误报 —— 4_3 走内存数组所以是 0.000000，
    # 4_2 走写盘表所以必然带舍入。
    tol = len(pd.read_excel(os.path.join(BASE, "结果", "result4-2.xlsx"),
                            sheet_name="计划购电量")) * 0.005
    say(f"\n  线性性核对 max|total(s) − s·total(1.00)| = {l2:,.6f} 元"
        f" ⇒ {'✓ 线性（差 ≤ 舍入上界）' if l2 <= tol else '✗ 非线性'}")
    say(f"  （容差 {tol:,.2f} 元 = 天数 × 0.005，即表内逐日 2 位小数取舍之和；"
        f"实测 {l2:.3f} 元远小于它）")

txt = "\n".join(OUT)
with open(os.path.join(BASE, "代码", "诊断", "_p4_pscale.txt"), "w", encoding="utf-8") as f:
    f.write(txt + "\n")
print("\n[已写入] 代码/诊断/_p4_pscale.txt")
