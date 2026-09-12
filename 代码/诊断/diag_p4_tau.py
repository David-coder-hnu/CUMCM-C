# -*- coding: utf-8 -*-
"""问题 4 交付点 τ 的**精修**：τ₀ ／ τ'(第 1–3 块) ／ τ''(调整层) 三维，各自独立。

    python 代码/诊断/diag_p4_tau.py

> ⚠⚠ **本脚本是历史记录，不是交付 τ 的来源。** 它只跑了**手挑的 6 个联合配置点**，
>   故其结论「三维联合调平最多省 49,621 元」「**交付仍取问题 3 的 τ**」**已被取代**：
>   自 2026-09-12 起，交付 τ 由 `diag_p4_tau_opt.py` 的**五维坐标下降**搜索给出
>   （把 τ₁/τ₂/τ₃ 各自放开，见该脚本文件头），省下的远多于 49,621 元。
>   本脚本保留的原因是：§5.2 的一/二/三/五节（单维表、可加性失效、**常数价归因**）
>   仍然出自这里，那几条结论与"最终取哪个 τ"无关，仍然成立。
>   **跑本脚本会打出"交付仍取问题 3 的 τ"—— 那句已作废，别引用。**
本脚本解决一个**由我自己的四象限扫描引入的隐患**：

`diag_p4_quad.py` 与 `diag_p3_quad.py` 都把**调整层分位 τ''(P4_TAUP) 与第 1–3 块的分位
τ'(P4_TAUB[1:]) 绑成同一个数**。这样做是为了让 τ 保持二维、扫描可承受，也与交付点
（τ=(0.55, 0.42) 且 TAUP=0.42）及问题 3 四象限的记法一致。**但那是一个假设**：
如果调整层其实偏好**另一个**分位，那么四象限的每一格都略微次优，
"每格各自调平 τ"这句话就打了折扣。

本脚本就测这个假设：在交付格（追索 + G无上界）上，把 τ' 与 τ'' **拆开**分别扫，
回答三件事 ——

  ① 交付点 (τ₀=0.55, τ'=0.42) 是否仍是**内点最优**（不是被网格边缘卡住的伪最优）；
  ② 把 τ'' 解绑后，调整层是否偏好 ≠0.42 的分位 ⇒ **绑定的代价是多少元**；
  ③ τ' 与 τ'' 是否**近似可分离**（若是，"绑定"就是个无害的简化，可以写进论文）。

⚠ 为什么必须重扫（而不是沿用任何旧值）：问题 3 第三次定稿把调整层的整点锚点
   从含 10 分钟前视改成严格因果，预报一换、计划层就换，而**τ 必须随计划层重调**是本轮
   的头条方法学结论。旧 τ 面板全部作废。

⚠ 历史坑（本脚本保留下来的判据）：早期版本里 `P4_TAU` 从未接入模型，扫它会得到
   一串**一字不差**的总费却毫无报错 —— 一个静默的假阴性。故每张表都打印
   "不同取值的个数"，全同即报"旋钮失效"。
"""
import io
import os
import sys
import subprocess

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SNIP = '''
import sys
sys.path.insert(0, r"{code}")
import problem4_3 as P
r = P.run(1.0)
print("RESULT|%.2f|%.4f|%.4f" % (r["total"], P.TAU_B[0], P.TAUP))
'''

T0 = [0.45, 0.50, 0.52, 0.55, 0.58, 0.60, 0.65]
T1 = [0.34, 0.38, 0.40, 0.42, 0.44, 0.48, 0.52]
T2 = [0.30, 0.34, 0.38, 0.40, 0.42, 0.44, 0.48, 0.55, 0.65]
OUT = []


def say(s=""):
    print(s)
    OUT.append(s)


def run(t0=None, t1=None, t2=None, src=None):
    """跑一格。**显式钉死**交付配置的其余旋钮，只放开被扫的那一维。

    src 只给第五节用（常数价对照）；为 None 时**不设** P4_PRICE_SRC，走求解器缺省 att4。
    """
    env = dict(os.environ)
    env.update(P4_REC="1", P4_GMAX="20000", P4_READING="B", P4_WQ="0", P4_SENT="0",
               P4_WRITE="0", P4_NOWRITE="1", PYTHONIOENCODING="utf-8")
    env.pop("P4_PSCALE", None)
    env.pop("P4_PRICE_SRC", None)
    env.pop("P4_TAU", None)
    if src is not None:
        env["P4_PRICE_SRC"] = src
    a = 0.55 if t0 is None else t0
    b = 0.42 if t1 is None else t1
    c = 0.42 if t2 is None else t2
    # ⚠ 两个都设：P4_TAU 是 TAU_B[0] 的简写旋钮，与 P4_TAUB 同时给出会被硬报错拦住，
    #   故这里**只**用 P4_TAUB 设全 4 块，第 0 块也在里面。
    env.update(P4_TAUB=f"{a},{b},{b},{b}", P4_TAUP=str(c))
    p = subprocess.run([sys.executable, "-c", SNIP.format(code=os.path.join(BASE, "代码"))],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", env=env, cwd=BASE)
    ln = next((l for l in p.stdout.splitlines() if l.startswith("RESULT|")), None)
    if ln is None:
        say(f"    ✗ 失败：{(p.stderr or p.stdout)[-260:]}")
        return None
    _, tot, tau0, taup = ln.split("|")
    return float(tot), float(tau0), float(taup)


def panel(title, xs, fixed, axis, note="", base_val=None):
    """扫一维。fixed 是另外两维的取值。axis ∈ {'t0','t1','t2'}。

    ⚠ base_val 必须**显式**给：早先写成 `fixed.get(axis, 0.42)`，而 `fixed` 里
      只放**另外两维**，于是 τ₀ 那张表的 base 落成 0.42 —— 0.42 不在 T0 里，
      `res.get(...)` 得 None，**整列"与基准之差"静默印成空白**，看上去像
      "这一维没有基准"，实则是查表查错了键。τ'／τ'' 两张表只是碰巧 0.42 在表内才没露馅。
    """
    say("")
    say(title)
    if note:
        say(f"  {note}")
    say(f"{'取值':>8}{'总费(元)':>18}{'与基准之差':>18}")
    res = {}
    for x in xs:
        kw = dict(fixed)
        kw[axis] = x
        r = run(**kw)
        if r:
            res[x] = r[0]
    if not res:
        return None, None
    base = res.get(base_val)
    assert base is not None, f"{axis} 的基准值 {base_val} 不在扫描表内，差值列会全空"
    for x in xs:
        if x not in res:
            continue
        d = "—（交付点）" if base is not None and abs(res[x] - base) < 1e-9 else \
            (f"{res[x] - base:+,.2f} 元" if base is not None else "")
        say(f"{x:>8.3f}{res[x]:>18,.2f}{d:>18}")
    best = min(res, key=res.get)
    uniq = len(set(round(v, 2) for v in res.values()))
    say(f"  ⇒ 最优 {axis} = {best:.3f}（{res[best]:,.2f} 元）"
        f" ｜ 不同取值个数 {uniq}/{len(res)}"
        f" ⇒ {'✓ 旋钮生效' if uniq > 1 else '✗ 旋钮失效，全表同值！'}")
    return best, res


say("=" * 96)
say("问题 4-3 交付点 τ 精修（追索 + G无上界 + 读法B + WQ=0 + 价格源 att4，334 天口径 A）")
say("=" * 96)

b0, r0 = panel("一、第 0 块分位 τ₀（固定 τ'=τ''=0.42）", T0, dict(t1=0.42, t2=0.42), "t0",
               "第 0 块不可调整，静态临界比 = 4p/(4p+p) = 0.80；追索计划层下实测最优远低于它。",
               base_val=0.55)
b1, r1 = panel("二、第 1–3 块分位 τ'（固定 τ₀=0.55, τ''=0.42）", T1, dict(t0=0.55, t2=0.42), "t1",
               base_val=0.42)
b2, r2 = panel("三、调整层分位 τ''（固定 τ₀=0.55, τ'=0.42）——**本脚本的核心问题**",
               T2, dict(t0=0.55, t1=0.42), "t2",
               "四象限扫描把 τ'' 绑在 τ' 上；此表检验绑定是否有代价。", base_val=0.42)

say("")
say("四、联合重扫（三旋钮同时放开）——**单维最优不可叠加**", )
say("  一/二/三 三张表都是**单维**扫描：固定另外两维在交付点上动一维。三张表各自的"
    "最优")
say("  (τ₀=0.50, τ'=0.48, τ''=0.34) **不是**同一个点，三个增益**不能相加**"
    "（旋钮间有交互）。")
say("  本节就把它们放到一起跑，量出「都调平」之后真实能省多少。")
JOINT = [(0.55, 0.42, 0.42, "交付点"),
         (0.50, 0.42, 0.42, "只动 τ₀"),
         (0.55, 0.48, 0.42, "只动 τ'"),
         (0.55, 0.42, 0.34, "只动 τ''"),
         (0.50, 0.48, 0.48, "τ₀,τ' 取单维最优、τ'' 仍绑到 τ'"),
         (0.50, 0.48, 0.34, "三维各自最优")]
# ⚠ 一行一个、标签在前 —— 早期把它排成表并给 `说明` 只有 10 列宽，而中文按 1 计宽、
#   实际渲染占 2 列，于是 "τ₀,τ' 最优 + τ'' 绑到 τ'" 直接**压进左边那一列数字里**，
#   印出 "+13,042.84 元τ₀,τ' 最优…"。别再用定宽表排中文。
_jr, _jb = {}, None
for _t0, _t1, _t2, _lab in JOINT:
    _r = run(_t0, _t1, _t2)
    if _r:
        _jr[(_t0, _t1, _t2)] = (_r[0], _lab)
        if _lab == "交付点":
            _jb = _r[0]
        _key = "(" + ", ".join(f"{x:g}" for x in (_t0, _t1, _t2)) + ")"
        say(f"  · {_lab:<28}{_key:>22}{_r[0]:>18,.2f} 元")
_jbest = min(_jr, key=lambda k: _jr[k][0]) if _jr else None
if _jbest is not None and _jb is not None:
    _jg = _jb - _jr[_jbest][0]
    say(f"  ⇒ 联合最优 {tuple(f'{x:g}' for x in _jbest)}，"
        f"比交付点省 **{_jg:+,.2f} 元（{_jg / _jb * 100:+.3f}%）**")
    _solo = sum(max(0.0, _jb - min(r.values())) for r in (r0, r1, r2) if r)
    _syn = _jg - _solo
    say(f"     三维单维最优增益之和 = {_solo:+,.2f} 元，联合实得 {_jg:+,.2f} 元")
    # ⚠ 符号必须分情况说：早期无条件写「交互吃掉 {solo-jg} 元」，而本题 solo<jg，
    #   于是印出「交互吃掉 -20,394 元」—— 一个负数被叫成"吃掉"，读者会以为是损失，
    #   实际是**协同**（联合增益超过单维之和）。措辞与符号必须一致。
    if _syn > 1:
        say(f"     ⇒ 差 **{_syn:+,.2f} 元**：联合增益**超过**单维之和 ⇒ 三旋钮**协同**"
            "（可加性失效，单维表只可用于判方向）")
    elif _syn < -1:
        say(f"     ⇒ 差 **{_syn:+,.2f} 元**：联合增益**小于**单维之和 ⇒ 旋钮间有**损耗**"
            "（可加性失效，单维表只可用于判方向）")
    else:
        say("     ⇒ 三旋钮近似**可加**，单维表可直接相加")

say("")
say("五、常数价对照：τ' 的缺口是**波动电价造成的**，还是**继承自问题 3 的 τ 选择**？")
say("  （本节作于 2026-09-12 之前，当时交付 τ 是**从问题 3 直接继承**的 (0.55,0.42,0.42)，")
say("    问题 4 与问题 3 因此构成**只改价格**的受控对照。该对照现已降级为 §6.1 的")
say("    受控消融 —— 交付 τ 换了，但**这一节的归因结论不受影响**，故保留。）")
say("  若 τ'=0.42 在**常数价**下就已次优，那 §二的 17,771 元缺口就不是波动电价的代价，")
say("  而是继承来的 —— 两种归因对论文的含义完全不同，必须分开量。")
say("")
say(f"{'价格源':>10}{'τ':>8}{'总费(元)':>18}{'与 (0.42) 之差':>18}")
_c_res = {}
for _t1 in (0.42, 0.44, 0.48):
    _r = run(0.55, _t1, 0.42, src="att1")
    if _r:
        _c_res[_t1] = _r[0]
if _c_res:
    _cb = _c_res.get(0.42)
    for _t1 in (0.42, 0.44, 0.48):
        if _t1 in _c_res:
            d = "—（交付 τ）" if _t1 == 0.42 and _cb is not None else \
                (f"{_c_res[_t1] - _cb:+,.2f} 元" if _cb is not None else "")
            say(f"{'att1 常数价':>10}{_t1:>8.2f}{_c_res[_t1]:>18,.2f}{d:>18}")
    if _cb is not None:
        say(f"  · 常数价下 (0.55,0.42,0.42) 应**精确复现问题 3 的定稿值 13,641,420 元**："
            f"实得 {_cb:,.2f} 元 ⇒ "
            f"{'✓ 回归锚点成立' if abs(_cb - 13_641_420.38) < 1 else '✗ 与问题 3 定稿不符！'}")
        _cbest = min(_c_res, key=_c_res.get)
        _cg = _cb - _c_res[_cbest]
        say(f"  · 常数价最优 τ' = {_cbest:.2f}（比 0.42 省 {_cg:+,.2f} 元）")
        if _cbest != 0.42 and _cg > 5000:
            say("    ⇒ **缺口在常数价下就存在** ⇒ 它主要是**继承自问题 3 的 τ 选择**，"
                "不是波动电价的代价。")
            say("      这同时是给问题 3 的一个交叉观察：若属实，问题 3 自身也留有同量级的改进空间"
                "（本脚本不据此改问题 3 的交付，只报告）。")
        elif _cbest == 0.42:
            say("    ⇒ **常数价下 0.42 就是最优** ⇒ §二的缺口确由**波动电价**造成，"
                "归因干净。")

say("")
say("=" * 96)
say("结论")
say("=" * 96)
d_base = run(0.55, 0.42, 0.42)
say(f"  交付点 (τ₀=0.55, τ'=0.42, τ''=0.42) 总费 = "
    f"{'算不出' if d_base is None else format(d_base[0], ',.2f')} 元")
if b2 is not None and d_base is not None:
    cost = d_base[0] - r2[b2]
    say(f"  解绑 τ'' 到 {b2:.2f} 可省 **{cost:+,.2f} 元**"
        f"（{cost / d_base[0] * 100:+.3f}%）")
    if abs(b2 - 0.42) < 1e-9:
        say("  ⇒ τ'' 的最优**恰在交付点**，"
            "「把 τ'' 绑到 τ'」在本交付格上**无代价**，四象限的简化成立。")
    elif cost < 5000:
        say(f"  ⇒ τ'' 偏好 {b2:.2f}，但解绑只省 {cost:,.0f} 元（<5,000，占比 <0.04%）——"
            "绑定是**无害简化**，但论文须写明这一约定。")
    else:
        say(f"  ⚠ τ'' 偏好 {b2:.2f}，解绑可省 {cost:,.0f} 元 —— "
            "**绑定不再无害**，四象限每一格都次优，须在论文中披露并考虑解绑重扫。")
if _jbest is not None and _jb is not None:
    _gap = _jb - _jr[_jbest][0]
    say(f"  三维**联合**调平（在**本脚本手挑的 6 个点上**）最多省 {_gap:+,.2f} 元"
        f"（{_gap / _jb * 100:+.3f}%）")
    say(f"     ⇒ 早在只有 6 个候选点时，就已看出 (0.55,0.42,0.42) 不是本问的最优。")
    say("  ★ **交付是否取问题 3 的 τ —— 答案已改为「不取」。**（2026-09-12）")
    say(f"     当时的取舍是「共享 τ 才能让 §6.1「波动电价不改策略、只改账单」的逐槽")
    say(f"     相异 0 成立，代价 {_gap:,.0f} 元（{_gap / _jb * 100:.3f}%）远小于该结论的价值」。")
    say("     但这个取舍**前提就不牢**：本节的 6 个点连 τ₁/τ₂/τ₃ 都没分开（三者被绑成")
    say("     同一个数），故它给出的只是**下界**。`diag_p4_tau_opt.py` 把五维全部放开后")
    say("     （见该脚本），省下的远多于本节 —— 冻结一个次优的 τ 去换一条**可以在")
    say("     共享 τ 下单独跑消融**就能得到的证据，是笔亏本买卖。")
    say("     ⇒ 交付取**本问自己的五维最优 τ**；§6.1 降级为**明确标注的受控消融**")
    say("       （`diag_p4_cross_abl.py`，共享 τ 下重跑），头条结论不变，但适用条件写明。")

txt = "\n".join(OUT)
with open(os.path.join(BASE, "代码", "诊断", "_p4_tau.txt"), "w", encoding="utf-8") as f:
    f.write(txt + "\n")
print("\n[已写入] 代码/诊断/_p4_tau.txt")
