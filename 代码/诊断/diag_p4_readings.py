# -*- coding: utf-8 -*-
"""问题 4 口径矩阵：读法 A / B × 购电上界 × 电价加权分位 WQ，外加完美预见哨兵。

为什么要单独跑这一张表：论文里「波动电价到底改变了什么」这个问题的答案
**完全由这张表的行间差给出**。每一行只动一个旋钮，差值就是那个旋钮的价格。

  · 读法 B − 读法 A   = **价格信息的价值**（0:00 是否已知全天电价）
  · G=∞ − G≤5000      = 自加购电上界的代价（正 = 上界反而是好事）
  · WQ=1 − WQ=0       = 电价加权分位是否值得开
  · 哨兵              = 绝对下界，任何低于它的结果都是 bug

用法：python 代码/诊断/diag_p4_readings.py
"""
import os
import sys
import subprocess

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(BASE, "代码"))

# (标签, P4_READING, P4_GMAX, P4_WQ, P4_SENT)  —— 每次只动一个旋钮（除首行基准）
CONFIGS = [
    ("读法 B  G≤5000  WQ=0（主交付）", "B", "5000", "0", "1"),
    ("读法 A  G≤5000  WQ=0（下界）", "A", "5000", "0", "1"),
    ("读法 B  G=∞     WQ=0", "B", "inf", "0", "1"),
    ("读法 B  G≤5000  WQ=1", "B", "5000", "1", "1"),
    ("读法 B  G=∞     WQ=1", "B", "inf", "1", "1"),
]

SNIP = '''
import sys
sys.path.insert(0, r"{code}")
import problem4_3 as P
r = P.run(1.0)
s = P.sentinel() if P.DO_SENT else None          # 返回 dict（或 None）
sent = s["total"] if s else float("nan")
print("RESULT|%.2f|%.2f|%.2f|%.2f|%.2f|%s|%s|%.2f"
      % (r["total"], r["plan"], r["breach"], r["excess"], r["emerg"],
         P.READING, int(P.WQ), sent))
'''

OUT = []


def say(s=""):
    print(s)
    OUT.append(s)


say("=" * 104)
say("问题 4 口径矩阵（problem4_3，2025-02-01 起 334 天计费窗口）")
say("=" * 104)
say(f"{'配置':<34}{'总费(元)':>16}{'计划 p·ĝ':>15}{'超额':>15}{'紧急':>15}"
    f"{'哨兵(元)':>16}{'高出哨兵':>10}")

rows = {}
for lab, rd, gm, wq, sent in CONFIGS:
    env = dict(os.environ)
    env.update(P4_READING=rd, P4_GMAX=gm, P4_WQ=wq, P4_SENT=sent,
               P4_NOWRITE="1", PYTHONIOENCODING="utf-8")
    env.pop("P4_PSCALE", None)          # 确保基准价，不受上一次扫描污染
    env.pop("P4_PRICE_SRC", None)
    p = subprocess.run([sys.executable, "-c", SNIP.format(code=os.path.join(BASE, "代码"))],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", env=env, cwd=BASE)
    line = next((l for l in p.stdout.splitlines() if l.startswith("RESULT|")), None)
    if line is None:
        say(f"{lab:<34}  ✗ 失败：{(p.stderr or p.stdout)[-260:]}")
        continue
    _, tot, pl, br, ex, em, r_, w_, sn = line.split("|")
    tot, pl, br, ex, em, sn = map(float, (tot, pl, br, ex, em, sn))
    rows[lab] = (tot, sn)
    say(f"{lab:<34}{tot:>16,.2f}{pl:>15,.2f}{ex:>15,.2f}{em:>15,.2f}"
        f"{sn:>16,.2f}{(tot / sn - 1) * 100:>9.2f}%")

say("-" * 104)
for a, b, name in (
        ("读法 B  G≤5000  WQ=0（主交付）", "读法 A  G≤5000  WQ=0（下界）", "价格信息的价值（B − A）"),
        ("读法 B  G=∞     WQ=0", "读法 B  G≤5000  WQ=0（主交付）", "放开购电上界的代价（∞ − 5000）"),
        ("读法 B  G≤5000  WQ=1", "读法 B  G≤5000  WQ=0（主交付）", "电价加权分位的增量（WQ=1 − WQ=0）"),
        ("读法 B  G=∞     WQ=1", "读法 B  G=∞     WQ=0", "G=∞ 下加权分位的增量")):
    if a in rows and b in rows:
        d = rows[a][0] - rows[b][0]
        say(f"  {name:<44}{d:>+16,.2f} 元")

say("")
say("⚠ 哨兵口径：哨兵自己也受 G_MAX 约束，所以 G=∞ 那一档的哨兵（12,782,591.81）")
say("  低于 G≤5000 的哨兵（13,014,628.45）。因此「高出哨兵 X%」**只能在同一 G_MAX 内")
say("  横向比较**，跨上界比会得出错误结论。两张哨兵都是真下界，只是约束集不同。")
say("")
say("读法：差值为 a − b，正数表示 b 更便宜。")
say("  · 价格信息的价值极小（B 仅比 A 贵 53,939.57 元，占 0.35%）是本模型的核心结论之一 ——")
say("    均匀价格平移不改变任何边际权衡（口径 A 四项都是同一个 p 的倍数），")
say("    所以 0:00 是否已知电价几乎不影响决策。")
say("  · 放开购电上界**更贵**（+412,877.20 元），方向与问题 3 一致 —— 计划里预留的")
say("    「波动电价可能让这条结论翻转」**没有发生**。")
say("  · 电价加权分位在主配置下是**负结果**（+12,581.11 元），故缺省关闭；")
say("    但它在 G=∞ 下反号（−33,269.97 元），说明该机制与上界存在交互，")
say("    这条留作未解问题，不作为交付配置。")

txt = "\n".join(OUT)
with open(os.path.join(BASE, "代码", "诊断", "_p4_readings.txt"), "w", encoding="utf-8") as f:
    f.write(txt + "\n")
print("\n[已写入] 代码/诊断/_p4_readings.txt")
