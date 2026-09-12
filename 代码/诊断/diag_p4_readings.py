# -*- coding: utf-8 -*-
"""问题 4-3 口径矩阵：读法 A/B × 电价加权分位 WQ（+ 常数价回归基准），附完美预见哨兵。

    python 代码/诊断/diag_p4_readings.py

**本表只回答两个问题**，购电上界的问题**不在这里**（见 `diag_p4_quad.py`）：

  · 读法 A − 读法 B = **价格信息的价值**（0:00 是否已知全天电价）；
  · WQ=1 − WQ=0     = 电价加权分位是否值得开；
  · 常数价 → 交付    = **波动电价本身的账单增量**（与 `diag_p4_cross.py` 互为佐证）；
  · 哨兵             = 绝对下界，任何**低于**它的结果都是 bug。

⚠ 常数价那一维有**两行**，不是一行（2026-09-12 起）：交付 τ 与共享 τ 是两个不同的点，
  一行承担不了「价格效应」与「回归锚点」两个角色（详见 `CONFIGS` 上方那段注）。

⚠ 为什么不把 `G≤5000` 那一行也放进来（旧版本有）：**τ 必须随计划层与上界读法重调**。
  若在"无上界"的 τ 下测 `G≤5000`，测到的是"错误 τ 之下的保守读法"，
  不是在测"自加上界的代价" —— 那是**用错误的 τ 诋毁对方**。上界的那一维
  已由 `diag_p4_quad.py` 的四个格子**各自调平 τ** 后回答。两张表分工不重叠。

⚠ 哨兵口径：哨兵自己也受 `G_MAX` 约束，所以不同上界下的哨兵**不是同一个数**，
  「高出哨兵 X%」只能在同一 `G_MAX` 内横向比较。本表全部行都在交付读法（无上界）下，
  故哨兵可直接对比。

⚠ 早期版本设 `P4_NOWRITE=1` 而不设 `P4_WRITE=0`，而当时的 `problem4_3.py`
  **不读 `P4_NOWRITE`** ⇒ 本脚本**每一行都覆盖过一次 `结果/result4-3.xlsx`**。
  现已两处都修（脚本显式给 `P4_WRITE=0`，求解器也认 `P4_NOWRITE`）。**别再只给一个。**
"""
import io
import os
import sys
import subprocess

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(BASE, "代码", "诊断"))
import _p4_delivery as _D          # 交付配置的唯一真源（含 τ；见该模块说明）

# (标签, P4_READING, P4_PRICE_SRC, P4_WQ, τ 钉法)  —— 除交付行外，每次只动一个旋钮。
#
# ⚠ **τ 钉法这一列是必需的，不是装饰**：自 2026-09-12 起交付 τ ≠ 与问题 3 共享的 τ，
#   于是"换成常数价"这件事有两层含义，混在一行里会得出错的话：
#     · `None`  —— 交付 τ + att1：问「只把价格向量换掉，账单差多少」⇒ **价格效应**，可比；
#     · `"shared"` —— 共享 τ + att1：必须**逐分复现问题 3 的交付值 13,641,420.38**
#       ⇒ **回归锚点**，证明 problem4_3 ≡ problem3_recourse（同源）。
#   早先只有一行、且用的是交付 τ，那行**既不是**回归锚点（τ 不同了，复现不出来），
#   又被下游当成"交付 − 常数价"的对照 —— 一个标签承担了它承担不了的两个角色。
CONFIGS = [
    ("交付：读法 B、WQ=0", "B", "att4", "0", None),
    ("读法 A（0:00 已知全天电价）", "A", "att4", "0", None),
    ("读法 B、WQ=1", "B", "att4", "1", None),
    ("读法 A、WQ=1", "A", "att4", "1", None),
    ("常数价（att1，交付 τ，只换价格）", "B", "att1", "0", None),
    ("常数价（att1，共享 τ）＝问题 3 交付", "B", "att1", "0", "shared"),
]
CONST_DEV = "常数价（att1，交付 τ，只换价格）"       # 用于"价格效应"的对照
CONST_ANCHOR = "常数价（att1，共享 τ）＝问题 3 交付"  # 回归锚点
P3_DELIVERY = 13_641_420.38                          # 问题 3 交付值（共享 τ + att1）

SNIP = '''
import hashlib
import sys

import numpy as np

sys.path.insert(0, r"{code}")
import problem4_3 as P
r = P.run(1.0)
s = P.sentinel() if P.DO_SENT else None          # 返回 dict（或 None）
sent = s["total"] if s else float("nan")
# ★ 策略指纹：把五个决策数组**逐槽**哈希。下游那张表原先写着一句
#   「本表两行之间策略也相同」，可它是**断言、不是实测** —— 五个旋钮里到底哪几个
#   真的不改决策，从来没人量过。指纹把它变成观测量（见下方 `策略指纹` 列）。
#   ⚠ 用 tobytes() 而不是 sum()/mean()：日总量相同**不代表**策略相同
#     （4-2 侧就出现过"逐日总量只差 1e-6、槽位却差 21/48,096"的退化再分配，见 §5.3）。
fp = hashlib.md5()
for a in (r["g_hat"], r["g_fin"], r["c"], r["d"], r["e"]):
    fp.update(np.ascontiguousarray(np.asarray(a, dtype=float)).tobytes())
print("RESULT|%.2f|%.2f|%.2f|%.2f|%.2f|%s|%s|%.2f|%.4f|%.4f"
      % (r["total"], r["plan"], r["breach"], r["excess"], r["emerg"],
         P.READING, int(P.WQ), sent, P.TAU_B[0], P.TAUP))
print("FP|" + fp.hexdigest())
'''

OUT = []


def say(s=""):
    print(s)
    OUT.append(s)


def run(reading, src, wq, tau=None):
    # ⚠ 交付形状（含 τ）从 problem4_3._DELIVERY 读，**不手抄**：τ 一改，手抄的副本
    #   不会报错，只会让本表跑在与交付值不同的配置上而标题仍写着「交付」（归档 §6.4）。
    #   用 `delivery_env()`（含完整 os.environ）而不是 `delivery()[0]`：后者只含 P4_*，
    #   子进程会在没有 PATH/SystemRoot 的环境里启动。
    #   tau="shared" 时改用**与问题 3 共享的 τ**（回归锚点那一行要用它）。
    env = _D.delivery_env() if tau is None else _D.delivery_env(pin_tau=_D.shared_tau())
    env.update(P4_READING=reading, P4_PRICE_SRC=src, P4_WQ=wq,
               # ⚠ 只放开这一行要动的那一个，其余钉死在交付配置上。
               P4_SENT="1", P4_WRITE="0", P4_NOWRITE="1")
    for k in ("P4_PSCALE", "P4_TAU", "P4_OUT"):
        env.pop(k, None)
    p = subprocess.run([sys.executable, "-c", SNIP.format(code=os.path.join(BASE, "代码"))],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", env=env, cwd=BASE)
    ln = next((l for l in p.stdout.splitlines() if l.startswith("RESULT|")), None)
    fpl = next((l for l in p.stdout.splitlines() if l.startswith("FP|")), None)
    if ln is None or fpl is None:
        # ⚠ 指纹缺失也要算失败：少了它，下面那张表会**静默退回**到"只印金额"的旧样子，
        #   而"策略是否逐槽不变"又变回一句没人验证的断言。
        return None, ("缺 RESULT/FP 行｜" + (p.stderr or p.stdout)[-240:])
    f = ln.split("|")[1:]
    return (dict(total=float(f[0]), plan=float(f[1]), breach=float(f[2]),
                 excess=float(f[3]), emerg=float(f[4]), reading=f[5], wq=f[6],
                 sent=float(f[7]), tau0=float(f[8]), taup=float(f[9]),
                 fp=fpl.split("|", 1)[1].strip()), None)


_INFO = _D.delivery()[1]
say("=" * 112)
# ⚠ τ 印**五维**（四块分位 + 调整层分位）：交付 τ 自 2026-09-12 起是五维搜索的结果，
#   只印四个 taub 会漏掉 τ'' —— 而 τ'' 恰恰是五维里增益最大的一维之一。
say("问题 4-3 口径矩阵（追索 + G 无上界 + 交付 τ=(%s)/%s，334 天计费窗口，口径 A）"
    % (_INFO["taub_str"], _INFO["taup_str"]))
say("=" * 112)
say(f"{'配置':<30}{'总费(元)':>16}{'计划 p·ĝ':>15}{'超额':>14}{'紧急':>14}"
    f"{'哨兵(元)':>16}{'高出哨兵':>10}{'策略指纹':>12}")

rows = {}
failed = []
DEL = "交付：读法 B、WQ=0"
ref_fp = None            # 交付行的策略指纹；其余行与它比（交付行在 CONFIGS 里是第一个）
for lab, rd, src, wq, tau in CONFIGS:
    r, err = run(rd, src, wq, tau)
    if r is None:
        say(f"{lab:<30}  ✗ 失败：{err}")
        failed.append(lab)
        continue
    rows[lab] = r
    if ref_fp is None:
        ref_fp = r["fp"]
        fpm = "—（基准）" if lab == DEL else "(基准)"
    else:
        fpm = "✓ 逐槽同" if r["fp"] == ref_fp else "✗ 变了"
    say(f"{lab:<32}{r['total']:>16,.2f}{r['plan']:>15,.2f}{r['excess']:>14,.2f}"
        f"{r['emerg']:>14,.2f}{r['sent']:>16,.2f}{(r['total'] / r['sent'] - 1) * 100:>9.2f}%"
        f"{fpm:>14}")
    if lab == CONST_ANCHOR:
        # ⚠ 回归锚点必须**逐分**命中；不命中说明 problem4_3 与 problem3_recourse 失同步了
        #   （或共享 τ 写错）。这一条比"数值接近"强得多 —— 它是同源证明。
        hit = abs(r["total"] - P3_DELIVERY) < 1.0
        say(f"{'  └ 回归锚点校验':<32}{r['total']:>16,.2f}   期望 {P3_DELIVERY:,.2f}  "
            f"{'✓ 与问题 3 同源（逐分命中）' if hit else '✗ 失同步，须查！'}")

say("-" * 112)
for a, b, name in (
        ("读法 A（0:00 已知全天电价）", DEL, "价格信息的价值（读法A − 交付）"),
        ("读法 B、WQ=1", DEL, "电价加权分位的增量（WQ=1 − 交付）"),
        # ⚠ 这一条的 a／b 顺序**反了**：循环算的是 `rows[a] − rows[b]`，而这里原先
        #   把常数价当 a、交付当 b，于是标着「交付 − 常数价」却印出 −762,667.69 ——
        #   符号与标签相反（实际价是**更贵**的，应为 +）。而且百分比的分母也跟着从
        #   常数价变成了交付，与其它三行的口径不一致。交换 a／b 即可同修。
        (DEL, CONST_DEV, "波动电价的账单增量（交付 − 常数价，同 τ）"),
        ("读法 A、WQ=1", "读法 A（0:00 已知全天电价）", "读法 A 下再开 WQ 的增量")):
    if a in rows and b in rows:
        d = rows[a]["total"] - rows[b]["total"]
        pct = d / rows[b]["total"] * 100
        say(f"  {name:<46}{d:>+16,.2f} 元   {pct:>+7.3f}%")

say("")
say("读法：差值为 a − b；`策略指纹`列是五个决策数组（ĝ / g / c / d / e）的逐槽 md5，"
    "基准 = 交付行。")
if DEL in rows and CONST_DEV in rows:
    d = rows[DEL]["total"] - rows[CONST_DEV]["total"]
    same = rows[DEL]["fp"] == rows[CONST_DEV]["fp"]
    say(f"  · **波动电价的全部代价就是这一项**：常数价 → 实际价帐单 "
        f"**+{d:,.2f} 元（+{d / rows[CONST_DEV]['total'] * 100:.2f}%）**，而策略"
        + ("**逐槽不变**（指纹相同 ⇒ 上面那列已实测，不是断言）"
           if same else
           "⚠ **变了**（指纹不同）—— 与旧版结论相反，须查！"))
    say("    ⚠ 这一对照两侧**同为交付 τ**，故差价**只**来自价格向量。")
    say("    （另一条独立证据在 `diag_p4_cross_abl.py`：共享 τ 下与 result3 逐元素相异 0。）")
    say("    · **机制**（不是「价格不重要」，而是「它压根没进计划层」）：")
    say("        计划层的价格由 `problem4_3.py:1097` 的 `pr_plan = PR[d] if READING=="
        "\"A\" else price_day` 给出。")
    say("        `price_day` = **附件1 公布的分时剖面**，是模块级常量（`:387`），"
        "与 `PRICE_SRC` 无关；")
    say("        附件4 的实际价 `PR` **只出现在结算 `day_fee`**（和读法 A／WQ 里）。")
    say("        故读法 B 下换价格源 ⇒ `pr_plan` 逐位不变 ⇒ 决策逐槽不变，只有账单被重估。")
    say("      ⇒ 这正是「波动电价的**唯一**作用是重估账单」的**成因**，也是本问核心结论。")
    # ⚠ 旧版这里写的是「读法 B 下决策只经 price_day，与价格源无关」—— 方向对，但那是
    #   一句**没人量过**的断言（当时本脚本根本不导出策略，比不了），且容易读成
    #   "价格怎么变都不影响决策"。指纹列把它变成观测量，下面的 ✗ 行正是反例。
    chg = [lab for lab in rows if lab != DEL and rows[lab]["fp"] != rows[DEL]["fp"]]
    say(f"    · 指纹列读法：本表 {len(rows)} 行里，策略与交付**不同**的有 "
        f"{len(chg)} 行" + (f"（{'、'.join(chg)}）" if chg else "（→ 连读法 A、WQ 都不改策略）") + "。")
    say("      ⚠ 读法 A 与 WQ=1 **会**改策略 —— 后者是因为它们把 `PR` 引进了计划层/分位。")
    say("        所以上面那句话**只对读法 B + 换价格源成立**，不要扩张成「价格不影响决策」。")
if DEL in rows and "读法 A（0:00 已知全天电价）" in rows:
    d = rows["读法 A（0:00 已知全天电价）"]["total"] - rows[DEL]["total"]
    say(f"  · 价格信息的价值极小（读法 B 仅比 A 贵 {abs(d):,.2f} 元，"
        f"占 {abs(d) / rows[DEL]['total'] * 100:.2f}%）——")
    say("    因为口径 A 的四项费用 `p·ĝ`、`0.5p(ĝ−g)⁺`、`1.5p(g−ĝ)⁺`、`5p·e` **都是同一个 p")
    say("    的倍数**，对 p 做缩放不改变任何边际权衡 ⇒ 0:00 是否已知电价几乎不影响决策。")

# ⚠⚠ **缺行必须让整个脚本失败。** 2026-09-12 实测踩到：本脚本六行里**四行**因
#   `MemoryError`／`ImportError: DLL load failed ... 页面文件太小` 失败（机器内存/页面
#   文件被别的重活压满），而脚本仍 rc=0、照常写出 `_p4_readings.txt` —— 驱动器按 rc
#   判成功，于是一张**只有 2/6 行**的表被当成完整的表留在归档里，而它看上去完全正常。
#   这正是本项目反复出现的那一类"静默的部分成功"。故此处显式返回非零。
#   （这个故障与 §5.3 记的 4-2 侧 5 ppm 抖动**不是**一回事：那是数值抖，这是进程被杀。）
txt = "\n".join(OUT)
if failed:
    say("")
    say("!" * 112)
    say(f"❌ 有 {len(failed)}/{len(CONFIGS)} 行**没跑出来**：{'、'.join(failed)}")
    say("   ⇒ 上表**不完整，不可引用**。先解决内存/页面文件压力，再重跑本脚本：")
    say("      python 代码/诊断/run_p4_delivery_diags.py --only=readings")
    say("!" * 112)
    txt += "\n" + "\n".join(OUT[-6:])
with open(os.path.join(BASE, "代码", "诊断", "_p4_readings.txt"), "w", encoding="utf-8") as f:
    f.write(txt + "\n")
print("\n[已写入] 代码/诊断/_p4_readings.txt")
if failed:
    raise SystemExit(1)
