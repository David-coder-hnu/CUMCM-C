# -*- coding: utf-8 -*-
"""问题 4 分位重扫：0:00 块分位 τ_块[0]（以及调整层 τ'）。

为什么要重扫：问题 3 的 τ=0.80 是在**常数电价**下扫出来的。问题 4 里电价与缺口
正相关（附件4 的日水平因子 a_d 与日均净负荷 corr = 0.982），缺电时电价系统性更高，
所以报童临界比 c_u/(c_u+c_o) 会移动：
    c_u = 4·E[p | 缺口] ,  c_o = E[p | 过剩]
若缺口时 p 更高，则临界比 > 0.80，最优 τ 应**上移**。纯理论估计给出 ≈0.836。

本脚本的职责就是**实测这个位移到底有没有出现**。预期与实测的差别本身就是结论。

⚠ 本脚本存在的原因之一：早期版本里 P4_TAU 从未接入模型（见 problem4_3.py 中
  该旋钮旁的注释）。若旋钮失效，下表会退化成 13 个一字不差的总费 —— 所以
  表里第一列是「与基准的差」，全 0 就是旋钮又坏了。

用法：python 代码/诊断/diag_p4_tau.py
"""
import os
import sys
import subprocess

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SNIP = '''
import sys
sys.path.insert(0, r"{code}")
import problem4_3 as P
r = P.run(1.0)
print("RESULT|%.2f|%.4f" % (r["total"], P.TAU_B[0]))
'''

TAUS = [0.70, 0.75, 0.78, 0.80, 0.82, 0.836, 0.86, 0.90]
TAUPS = [0.45, 0.50, 0.55, 0.60, 0.65]
OUT = []


def say(s=""):
    print(s)
    OUT.append(s)


def run(**kw):
    env = dict(os.environ)
    env.update(P4_READING="B", P4_GMAX="5000", P4_WQ="0", P4_SENT="0",
               P4_NOWRITE="1", PYTHONIOENCODING="utf-8")
    for k in ("P4_PSCALE", "P4_PRICE_SRC", "P4_TAU", "P4_TAUB", "P4_TAUP"):
        env.pop(k, None)
    env.update({k: str(v) for k, v in kw.items()})
    p = subprocess.run([sys.executable, "-c", SNIP.format(code=os.path.join(BASE, "代码"))],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", env=env, cwd=BASE)
    ln = next((l for l in p.stdout.splitlines() if l.startswith("RESULT|")), None)
    if ln is None:
        say(f"    ✗ 失败：{(p.stderr or p.stdout)[-260:]}")
        return None
    _, tot, tau_used = ln.split("|")
    return float(tot), float(tau_used)


say("=" * 88)
say("问题 4 分位重扫（读法 B、WQ=0、G ≤ 5000 kW、无哨兵）")
say("=" * 88)
say("一、0:00 块分位 τ_块[0]（P4_TAU）。理论预期最优在 ≈0.836。")
say(f"{'τ':>8}{'总费(元)':>18}{'与 τ=0.80 之差':>18}")

res = {}
for t in TAUS:
    r = run(P4_TAU=t)
    if r:
        res[t] = r[0]
    else:
        continue
base = res.get(0.80)
for t in TAUS:
    if t not in res:
        continue
    d = "—（基准）" if abs(t - 0.80) < 1e-9 else f"{res[t] - base:+,.2f} 元"
    say(f"{t:>8.3f}{res[t]:>18,.2f}{d:>18}")
if res:
    best = min(res, key=res.get)
    uniq = len(set(round(v, 2) for v in res.values()))
    say(f"\n  实测最优 τ = {best:.3f}（{res[best]:,.2f} 元）"
        f" ｜ 不同取值的个数 = {uniq}/{len(res)}"
        f" ⇒ {'✓ 旋钮生效' if uniq > 1 else '✗ 旋钮失效，全表同值'}")
    say(f"  理论预期的 0.836 是否成为最优：{'✓ 是' if abs(best - 0.836) < 0.01 else '✗ 否'}")

say("")
say("二、调整层分位 τ'（P4_TAUP），τ_块 固定为定稿值。")
_hdr = "τ'"
say(f"{_hdr:>8}{'总费(元)':>18}")
rb = res.get(0.80)
for tp in TAUPS:
    r = run(P4_TAUP=tp)
    if r:
        say(f"{tp:>8.2f}{r[0]:>18,.2f}"
            + (f"   ({r[0] - rb:+,.2f} 元)" if rb else ""))

txt = "\n".join(OUT)
with open(os.path.join(BASE, "代码", "诊断", "_p4_tau.txt"), "w", encoding="utf-8") as f:
    f.write(txt + "\n")
print("\n[已写入] 代码/诊断/_p4_tau.txt")
