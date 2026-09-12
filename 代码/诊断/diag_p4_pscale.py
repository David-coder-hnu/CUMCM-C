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
sys.path.insert(0, os.path.join(BASE, "代码", "诊断"))
import _p4_delivery as _D          # 交付配置的唯一真源（含 τ；见该模块说明）

SCALES = [round(0.70 + 0.05 * k, 2) for k in range(13)]      # 0.70 … 1.30
OUT = []


def say(s=""):
    print(s)
    OUT.append(s)


# ══════════════════ problem4_3：进程内 reload ══════════════════
# ⚠ 基准 = 交付配置（追索 + G 无上界 + **交付 τ**），不是旧的"确定性 + G≤5000"，
#   也不是那个"τ 继承自问题 3"的过渡版。τ 从 _DELIVERY 读，不手抄（归档 §6.4）。
_env, _info = _D.delivery()
os.environ.update({k: v for k, v in _env.items() if k != "PYTHONIOENCODING"})
os.environ["P4_NOWRITE"] = "1"
# ⚠ P4_WRITE=0 **必须显式给**：早期 problem4_3.py 不读 P4_NOWRITE，于是本段 13 档
#   每一档都覆盖过一次 结果/result4-3.xlsx（见 problem4_3.py 中 NOWRITE 的说明）。
os.environ["P4_WRITE"] = "0"

say("=" * 96)
say("问题 4-3 敏感性：实际结算价整体缩放（读法 B、WQ=0、追索、G 无上界）")
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
say("问题 4-2 敏感性：实际结算价整体缩放（读法 B、G 无上界 ＝ 4-2 交付读法）")
say("=" * 96)
say(f"{'缩放':>6}{'总费(元)':>18}{'相对基准':>12}{'相异槽数':>12}   说明：取自写盘后的 4-2 表"
    f"（逐日购电费求和）；相异槽数是与 s=1.00 的 ĝ 逐槽比较")
env = dict(os.environ)
# ⚠ `P4_GMAX` 取 **4-2 的交付读法（无上界）**，不是这里原先写死的 5000。
#   敏感性一节量的是"交付模型对价格缩放的响应"，必须站在交付配置上；
#   用 `G≤5000` 会把整张表换成另一个模型（差 163,296 元 / 1.11%，见
#   `diag_p4_2_gmax.py`），而表头仍写着"问题 4-2 敏感性"—— 名实不符。
env.update(P4_READING="B", P4_GMAX="inf", GAMMAS="1.0", PYTHONIOENCODING="utf-8")
env.pop("P4_NOWRITE", None)      # ← 必须去掉：4_3 段设过它，会顺着 os.environ 漏进来
tmpdir = os.path.join(BASE, "代码", "诊断")
tot42, pol42 = {}, {}
FAILED = []          # ⚠ 见文件末尾：缺行必须让脚本**失败**，不能静默交出一张残表
for s in SCALES:
    env["P4_PSCALE"] = str(s)
    out = os.path.join(tmpdir, f"_p4_2_pscale_{s:.2f}.xlsx")
    env["P4_OUT"] = out                     # 写到诊断目录，绝不碰交付文件
    p = subprocess.run([sys.executable, os.path.join(BASE, "代码", "problem4_2.py")],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", env=env, cwd=BASE)
    if p.returncode != 0 or not os.path.exists(out):
        say(f"{s:>6.2f}   ✗ 运行失败 rc={p.returncode}：{p.stdout[-200:]}{p.stderr[-300:]}")
        FAILED.append("4-2 s=%.2f" % s)
        continue
    d = pd.read_excel(out, sheet_name="计划购电量")
    # ⚠⚠ **两个**汇总列都要排除（归档 §6.4 陷阱 6）。表格是 147 列 = 日期 + 144 槽
    #   + `全天购电量` + `全天购电费`。早先这里只排了 `全天购电费`，于是 `全天购电量`
    #   （= 当日 Σĝ，一个**日总量**）被当成第 145 个"槽"混进策略数组，后果有两个：
    #     ① 分母虚报：A42.size 从 334×144=48,096 变成 334×145=48,430，而 4-3 侧报的是
    #        48,096 —— 两侧分母不可比，且"相异 N/48,430 **槽**"里混着 334 个日总量；
    #     ② roll 还原错位：145 列时 `np.roll(...,1,axis=1)` 会把最后一列（`全天购电量`）
    #        绕到第 0 位，于是数组变成 [日总量, 槽1..槽143, 槽0] —— **不是**槽序，
    #        而"逐日总量之差"也就成了 (日总量+Σ槽) 之差（约 2×）。
    #   排掉后 cols 恰为 144 列，roll 正好是写盘左移的精确逆运算，两侧分母一致。
    cols = [c for c in d.columns if c not in ("日期\\时间", "全天购电量", "全天购电费")]
    # 兜底断言：少排一列**不会报错**，只会让下面所有分母静默变大（陷阱 6 的复发形态）。
    assert len(cols) == 144, \
        f"策略数值区应恰为 144 个槽，实得 {len(cols)} —— 汇总列没排干净？末三列={cols[-3:]}"
    tot42[s] = float(d["全天购电费"].sum())
    # ⚠ 写盘时时间标签左移（第 k 列装 arr[(k+1) % N]），读回须 roll(1) 还原 —— 见归档 §8。
    pol42[s] = np.roll(d[cols].to_numpy(float), 1, axis=1)
    os.remove(out)
b2 = tot42.get(1.00)
A42 = pol42.get(1.00)
# ⚠ `s=1.00` 那一档是**整张表的基准**：它缺了，`b2` 就是 None，下面每一行都印不出相对值，
#   而线性性核对整块会被 `if b2 is not None` 静默跳过 —— 一张没有基准的残表照样写盘。
if b2 is None or A42 is None:
    say("  ⚠⚠ **基准档 s=1.00 没跑出来** ⇒ 4-2 段整表不可引用（相对值与线性性核对都缺基准）。")
    FAILED.append("4-2 s=1.00（基准）")
for s in SCALES:
    if s not in tot42:
        continue
    rel = "—（基准）" if abs(s - 1.0) < 1e-9 else f"{(tot42[s] / b2 - 1) * 100:+.2f}%"
    if A42 is None or abs(s - 1.0) < 1e-9:
        nd = "—"
    else:
        nd = f"{int((np.abs(pol42[s] - A42) > 1e-9).sum()):,}/{A42.size:,}"
    say(f"{s:>6.2f}{tot42[s]:>18,.2f}{rel:>12}{nd:>12}")
if b2 is not None:
    l2 = max(abs(v - s * b2) for s, v in tot42.items())
    worst = max((s for s in tot42 if abs(s - 1.0) > 1e-9),
                key=lambda s: abs(tot42[s] - s * b2), default=None)
    say("")
    # ⚠ 这里**不能**像 4_3 段那样用一个"舍入容差"判 ✓/✗。理由是本模型有更强的性质：
    #   约束（能量平衡／SOC 递推／功率上下限）里**根本不含价格**（价格只经 PR*PSCALE
    #   进目标函数，且是纯浮点乘法，无取整），故可行域与 s 无关
    #   ⇒ 最优值必须**精确**满足 V(s) = s·V(1)。任何偏差都是**求解器数值容差**，
    #   不是模型性质；用"逐日 2 位小数取舍"当容差（334×0.005=1.67 元）反而是
    #   用错的尺子 —— 它比实测小 55 倍，会把一个 5 ppm 的数值抖动渲染成"非线性"，
    #   而那句 `print` 又写着"远小于它"，自相矛盾（旧版本正是如此）。
    say(f"  线性性核对 max|total(s) − s·total(1.00)| = {l2:,.6f} 元"
        f"（相对 {l2 / b2 * 1e6:,.1f} ppm＝{l2 / b2 * 100:,.5f}%）"
        f"{'' if worst is None else f'，出现在 s={worst:.2f}'}")
    say("  理论上界：约束里不含价格 ⇒ 可行域与 s 无关 ⇒ V(s) = s·V(1) **必须精确成立**。")
    if A42 is not None and worst is not None:
        B = pol42[worst]
        nd = int((np.abs(B - A42) > 1e-9).sum())
        mx = float(np.abs(B - A42).max())
        dd = float(np.abs(B.sum(1) - A42.sum(1)).max())
        say(f"  成因：s={worst:.2f} 与 s=1.00 的 ĝ 有 {nd:,}/{A42.size:,} 槽相异，最大差 "
            f"{mx:,.4f} kWh，")
        say(f"        但**逐日总量**最大只差 {dd:,.6f} kWh ⇒ 这是**同一天内的再分配**"
            "（LP 有近似并列的顶点，")
        say("        求解器在不同 s 下选了不同顶点），不是策略真的变了。")
        say(f"        （分母 {A42.size:,} = 334 天 × 144 槽，与 4-3 侧同口径；"
            "逐日总量 = 144 槽之和，已不含汇总列。）")
    if l2 <= 1e-4:
        say("  ⇒ ✓ 与 4-3 侧同为精确线性。")
    else:
        say(f"  ⇒ ⚠ **4-2 侧不是 0 误差**（4-3 侧走内存数组是 0.000000 元）。偏差 "
            f"{l2:,.2f} 元＝{l2 / b2 * 100:,.5f}%，")
        say("     远低于论文的报告精度，但**足以否掉「逐元素完全相同」这句话**：")
        say("     论文里「策略逐槽不变」只能对 **4-3** 说；4-2 只能说到"
            "「账单线性、策略在报告精度内不变」。")

# ⚠⚠ **缺行必须让整个脚本失败**（2026-09-12 加）。同一天在 `diag_p4_readings.py` 上实测
#   踩到过：六行里**四行**因 `MemoryError`／`ImportError: DLL load failed ... 页面文件太小`
#   失败，而脚本仍 rc=0 照常写盘 —— 驱动器按 rc 判成功，一张残表就以"完整的表"留在归档里。
#   （本机的页面文件只有 2 GB，而每次求解要解一个 48,096 变量级 LP；多开几个就撞上限。）
txt = "\n".join(OUT)
if FAILED:
    say("")
    say("!" * 96)
    say("❌ 有 %d 格**没跑出来**：%s" % (len(FAILED), "、".join(FAILED)))
    say("   ⇒ 上表**不完整，不可引用**。先卸掉别的重活，再重跑：")
    say("      python 代码/诊断/run_p4_delivery_diags.py --only=pscale")
    say("!" * 96)
    txt += "\n" + "\n".join(OUT[-5:])
with open(os.path.join(BASE, "代码", "诊断", "_p4_pscale.txt"), "w", encoding="utf-8") as f:
    f.write(txt + "\n")
print("\n[已写入] 代码/诊断/_p4_pscale.txt")
if FAILED:
    raise SystemExit(1)
