# -*- coding: utf-8 -*-
"""锚点修复（P3_ANCHOR: next→prev）之后，问题 3 的全部对照臂重测。

背景：pv_fc 的锚点 H[S] 原本取 pv[d,6S]（发布时刻**之后**那 10min 的实测），含一处
10 分钟前视；修复后取 pv[d,6S−1]（发布时刻**已观测完**的槽）。改动只影响调整层窗口
的头 5 槽，但 τ 是**计划层的伴生参数**，故所有对照都必须在新锚点下重测，不能留旧数。

跑四组：
  A  τ' 精细扫描（定稿配置，τ₀=0.55）—— 确认平台中心没移动
  B  τ₀ 扫描（定稿配置，τ'=0.42）
  C  四象限（计划层 × G_MAX 读法，**每格各自扫 τ 取最优**）
  D  消融（定稿 τ，逐项关掉）

只报数，不写盘（P3_WRITE=0 / P3_SENT=0）。
"""
import os
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC = os.path.join(BASE, "代码", "problem3_recourse.py")


def run(envx):
    e = os.environ.copy()
    e.update({"P3_WRITE": "0", "P3_SENT": "0"})
    e.pop("P3_OUT", None)
    e.update(envx)
    p = subprocess.run([sys.executable, SRC], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", env=e, cwd=BASE)
    if p.returncode != 0:
        return None
    for ln in p.stdout.splitlines():
        if "最优 λ" in ln:
            return float(ln.split("年费")[1].replace("元", "").replace(",", "").strip())
    return None


DELIV = {"P3_REC": "1", "P3_GMAX": "20000"}


def scan(tag, base, grid, build, label="τ'"):
    """build(v) -> 环境变量增量；v 是本次扫描的那个 τ。"""
    print(f"\n【{tag}】")
    best, bv = None, None
    for v in grid:
        t = run({**base, **build(v)})
        mark = ""
        if t is not None and (bv is None or t < bv):
            bv, best, mark = t, v, "  ←"
        print(f"    {label}={v:<6} {('—' if t is None else format(t, ',.0f')):>13}{mark}", flush=True)
    if bv is not None:
        print(f"    ⇒ 最优 {label}={best} → {bv:,.0f} 元")
    return best, bv


def tauprime(t0):
    """τ' 变动、第 0 块固定为 t0。"""
    return lambda v: {"P3_TAUB": f"{t0},{v},{v},{v}", "P3_TAUP": str(v)}


def taub0(tp):
    """τ₀ 变动、后三块固定为 tp。"""
    return lambda v: {"P3_TAUB": f"{v},{tp},{tp},{tp}", "P3_TAUP": str(tp)}


print("=" * 92)
print("锚点修复后的问题 3 全对照重测（P3_ANCHOR=prev，严格因果）")
print("=" * 92)

print("\n" + "─" * 92)
print("A  τ' 精细扫描（定稿配置：REC=1 / GMAX=20000 / τ₀=0.55）")
print("─" * 92)
a_best, a_val = scan("τ'", DELIV, [0.36, 0.38, 0.40, 0.42, 0.44, 0.46, 0.48], tauprime(0.55))

print("\n" + "─" * 92)
print("B  τ₀ 扫描（定稿配置，τ'=0.42）")
print("─" * 92)
b_best, b_val = scan("τ₀", DELIV, [0.45, 0.50, 0.52, 0.55, 0.58, 0.60], taub0(0.42), label="τ₀")

print("\n" + "─" * 92)
print("C  四象限（每格各自扫 τ 取最优；确定性 = P3_REC=0）")
print("─" * 92)
QUAD = [
    ("确定性 ＼ G≤5000",   {"P3_REC": "0", "P3_GMAX": "5000"},  tauprime(0.80), [0.50, 0.55, 0.60]),
    ("确定性 ＼ G 无上界", {"P3_REC": "0", "P3_GMAX": "20000"}, tauprime(0.90), [0.70, 0.75, 0.80]),
    ("追索   ＼ G≤5000",   {"P3_REC": "1", "P3_GMAX": "5000"},  tauprime(0.55), [0.26, 0.30, 0.34]),
    ("追索   ＼ G 无上界", {**DELIV},                            tauprime(0.55), [0.40, 0.42, 0.44]),
]
for tag, base, build, grid in QUAD:
    scan(tag, base, grid, build)

print("\n" + "─" * 92)
print("D  消融（定稿配置与 τ 固定，逐项关掉）")
print("─" * 92)
ABL = [
    ("定稿（基线）", {}),
    ("关水平校正 LEVEL=0", {"P3_LEVEL": "0"}),
    ("只用 0:00+6:00+12:00 档 BANDS=2", {"P3_BANDS": "2"}),
    ("只用 0:00+6:00 档 BANDS=1", {"P3_BANDS": "1"}),
    ("不用调整通道 BANDS=0", {"P3_BANDS": "0"}),
    ("关低需求日分组（同星期几 K=4）", {"P3_GRP": ""}),
]
FT = {"P3_TAUB": "0.55,0.42,0.42,0.42", "P3_TAUP": "0.42"}
base_val = None
for tag, envx in ABL:
    v = run({**DELIV, **FT, **envx})
    if base_val is None:
        base_val = v
    d = "" if v is None or base_val is None else f"  ({v - base_val:+,.0f})"
    print(f"    {tag:34s} {('—' if v is None else format(v, ',.0f')):>13}{d}", flush=True)

print("\n" + "=" * 92)
print("完成。交付值 = 追索 ＼ G 无上界 那一格，应等于 run_problem3.py 的产出。")
print("=" * 92)
