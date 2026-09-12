# -*- coding: utf-8 -*-
"""O2/O3/O4 优化实验的**调度器**（变体实现见 `_p4_variant.py`，不碰交付文件）。

    python 代码/诊断/diag_p4_hedge.py lam              # A：λ 阻尼扫描
    python 代码/诊断/diag_p4_hedge.py cd [τ起跑点]      # B：λ × 五维 τ 联合坐标下降
    python 代码/诊断/diag_p4_hedge.py fc [τ起跑点]      # C：预报器变体（各自重扫 τ₀）
    python 代码/诊断/diag_p4_hedge.py pv               # C2：光伏混合
    python 代码/诊断/diag_p4_hedge.py exec [τ起跑点]    # D：价格感知执行器
    python 代码/诊断/diag_p4_hedge.py shift [τ起跑点]   # E：直接平移族

为什么要跑 per-cell subprocess 而不是进程池
------------------------------------------------------------------
Windows 的 spawn 会重新 import `__main__`，驱动模块的 `sys.stdout` 改写与表打印
跟着重跑一遍，实测直接把进程池打崩（`BrokenProcessPool`）。本项目既有的
`diag_p4_tau_opt.py` 用的是"**每格一个 subprocess + 片段**"，那条路已验证可行；
本脚本沿用，并把变体函数隔离到无副作用的 `_p4_variant.py` 里。

⚠ 每格必须**先复现锚点**：λ=1 + 交付 τ 必须给出交付值，否则整表作废。
  （锚点与 τ 都从 `problem4_3._DELIVERY` 读，不手抄 —— 交付 τ 会变。）
⚠ 本脚本是**探索性**的（O2/O3/O4 变体实验）。自 2026-09-12 起交付 τ 已是本问自己的
  五维最优，故这里的 `tau` 基点是**交付 τ**；若要比较的是"共享 τ 下的变体"，须显式传
  τ 起跑点（见命令行第 2 个参数）。
⚠ 全部 `P4_WRITE=0`（`_p4_env.delivery_env` 已设）—— 绝不写交付文件。
"""
import io
import json
import os
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _p4_env as E                                     # noqa: E402

BASE = E.BASE
CACHE = os.path.join(E.DIAG, "_p4_hedge_cache.json")
OUT = []
_LOCK = threading.Lock()
WORKERS = 6
STEP = 0.02

# ⚠ 这两个**从 `problem4_3._DELIVERY` 读，不手抄**（与 `_p4_delivery.py` 同一条纪律）。
#   本行原先硬编码 `(0.55,0.42,0.42,0.42,0.42)` / `14,404,088.07` —— 那是**旧交付 τ**
#   的值。交付 τ 一改，硬编码不会报错，只会让下面第 155 行的锚点校验**恒判失败**
#   （"✗ 整表作废"），而表面原因看起来像脚本坏了。
import _p4_delivery as _D                               # noqa: E402
_dinfo = _D.delivery()[1]
DELIV_TAU = tuple(list(_dinfo["taub"]) + [_dinfo["taup"]])
DELIV_TOTAL = _D.delivery_total()


def say(s=""):
    print(s, flush=True)
    OUT.append(s)


# ════════════════════════════════════════════════════════════════════════
# 执行一格
# ════════════════════════════════════════════════════════════════════════
def _snip(spec):
    return (
        "import sys\n"
        "sys.path.insert(0, r'{code}')\n"
        "sys.path.insert(0, r'{diag}')\n"
        "import _p4_env as E, _p4_variant as V\n"
        "P = E.load()\n"
        "V.apply_spec(P, {spec!r})\n"
        "r = P.run(1.0)\n"
        "print('RESULT|{{:.4f}}'.format(r['total']))\n"
    ).format(code=E.CODE, diag=E.DIAG, spec=spec)


def run_one(spec):
    """跑一格。失败返回 None（**None 必须当作"没算过"**）。"""
    env = E.delivery_env()
    try:
        p = subprocess.run([sys.executable, "-c", _snip(spec)], capture_output=True,
                           text=True, encoding="utf-8", errors="replace",
                           env=env, cwd=BASE, timeout=1800)
    except subprocess.TimeoutExpired:
        return None
    if p.returncode != 0:
        return None
    for ln in p.stdout.splitlines():
        if ln.startswith("RESULT|"):
            try:
                return float(ln.split("|")[1])
            except ValueError:
                return None
    return None


def _load():
    if os.path.exists(CACHE):
        with open(CACHE, encoding="utf-8") as f:
            return {k: v for k, v in json.load(f).items()}
    return {}


def _save(c):
    with _LOCK:
        tmp = CACHE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(c, f, indent=0)
        os.replace(tmp, CACHE)


def key_of(spec):
    return json.dumps(spec, sort_keys=True)


def run_jobs(specs, cache):
    """并行评测一组 spec（带缓存）。返回 {key: 值-or-None}。"""
    todo = [s for s in specs if key_of(s) not in cache or cache[key_of(s)] is None]
    if todo:
        done = [0]

        def one(s):
            v = run_one(s)
            with _LOCK:
                cache[key_of(s)] = v
                done[0] += 1
                n = done[0]
            if n % 5 == 0 or n == len(todo):
                _save(cache)
        say("      （%d/%d 格需算，%d 并发）" % (len(todo), len(specs), WORKERS))
        with ThreadPoolExecutor(max_workers=WORKERS) as ex:
            for _ in ex.map(one, todo):
                pass
        _save(cache)
    return {key_of(s): cache.get(key_of(s)) for s in specs}


def fmt(v):
    return "—" if v is None else format(v, ",.2f")


def _g(x):
    return ("%.2f" % x) if isinstance(x, float) else str(x)


def _fmt_spec(s):
    out = []
    if "scen" in s:
        v = s["scen"]
        out.append("λ=%s" % _g(v) if not isinstance(v, (list, tuple))
                   else "shift=%s" % (",".join("%.0f" % x for x in v[1]),))
    if "fc" in s:
        out.append("fc=%s" % s["fc"])
    if "pv" in s:
        out.append("w=%s" % _g(s["pv"]))
    if s.get("exec"):
        out.append("exec=%s" % (s["exec"],))
    if s.get("tau"):
        out.append("τ=(%s)" % ",".join("%.2f" % x for x in s["tau"]))
    return " ".join(out)


def anchor_check(cache):
    """锚点：λ=1 + 交付 τ。对不上就整表作废（本项目的判据纪律）。"""
    a = dict(scen=1.0, tau=DELIV_TAU)
    v = run_jobs([a], cache)[key_of(a)]
    ok = isinstance(v, float) and abs(v - DELIV_TOTAL) < 1.0
    say("锚点 λ=1 + 交付τ → %s 元（期望 %s）%s"
        % (fmt(v), format(DELIV_TOTAL, ",.2f"), "✓" if ok else "✗ 整表作废！"))
    return ok, v


def tau_grids(base):
    S = STEP
    return [
        [round(0.36 + S * i, 2) for i in range(23)],     # τ₀ 0.36..0.80
        [round(0.16 + S * i, 2) for i in range(30)],     # τ₁ 0.16..0.74
        [round(0.16 + S * i, 2) for i in range(30)],     # τ₂ 0.16..0.74
        [round(0.16 + S * i, 2) for i in range(38)],     # τ₃ 0.16..0.90
        [round(0.16 + S * i, 2) for i in range(28)],     # τ'' 0.16..0.70
    ]


def cd(cache, spec0, axes, grids, rounds=6):
    """坐标下降：axes 列出要动的键（"scen"|"tau"|…），grids 同位序候选表。"""
    cur = dict(spec0)
    best = run_jobs([cur], cache)[key_of(cur)]
    if not isinstance(best, float):
        say("  ✗ 起点评测失败")
        return cur, best
    say("  起点 %s → %s 元" % (_fmt_spec(cur), fmt(best)))
    for rnd in range(1, rounds + 1):
        moved = False
        for ax, grid in zip(axes, grids):
            specs = []
            for x in grid:
                s = dict(cur)
                s[ax] = x
                specs.append(s)
            r = run_jobs(specs, cache)
            cand = [(x, r.get(key_of(s))) for x, s in zip(grid, specs)]
            cand = [(x, v) for x, v in cand if isinstance(v, float)]
            if not cand:
                say("      %-5s ✗ 本维全部失败，跳过（**不要**据此判无改进）" % ax)
                continue
            bx, bv = min(cand, key=lambda t: t[1])
            uniq = len(set(round(v, 2) for _, v in cand))
            lo = min(x for x, _ in cand); hi = max(x for x, _ in cand)
            edge = (isinstance(bx, float) and (abs(bx - lo) < 1e-9 or abs(bx - hi) < 1e-9))
            say("      %-5s ∈ [%s, %s]：最优 %s（%s）｜不同取值 %d/%d %s%s"
                % (ax, _g(lo), _g(hi), _g(bx), fmt(bv), uniq, len(cand),
                   "✓" if uniq > 1 else "✗ 旋钮失效，全表同值！",
                   "  ⚠ 落在扫描边界 ⇒ 真最优可能在区间外，须扩区" if edge else ""))
            if bv < best - 1e-6:
                cur[ax] = bx
                best = bv
                moved = True
        say("    第 %d 轮 ⇒ %s（%s 元）" % (rnd, _fmt_spec(cur), fmt(best)))
        if not moved:
            say("    ⇒ 全部维度无改进 ⇒ 收敛")
            break
    return cur, best


def basin(cache, best_val, tol=2000.0, tag=""):
    near = [(k, v) for k, v in cache.items() if isinstance(v, float) and v <= best_val + tol]
    say("  盆地平坦度%s：最优 +%s 元内共 %d 格" % (tag, format(tol, ",.0f"), len(near)))
    for ax in ("scen", "fc", "pv", "exec", "tau"):
        vs = set()
        for k, _ in near:
            d = json.loads(k)
            if ax in d:
                vs.add(str(d[ax]))
        if vs:
            say("    %-5s 取到 %d 种：%s" % (ax, len(vs), ", ".join(sorted(vs)[:8])))
    say("    ⇒ 邻域越宽 = 最优点越不唯一 = 增益在报告精度上越不稳健；须如实披露。")


# ════════════════════════════════════════════════════════════════════════
def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "lam"
    base = tuple(float(x) for x in sys.argv[2].split(",")) if len(sys.argv) > 2 else DELIV_TAU
    cache = _load()
    say("=" * 100)
    say("问题 4 优化实验 ｜ 模式 %s ｜ 起跑 τ = %s" % (mode, ",".join("%.2f" % x for x in base)))
    say("交付基线 %s 元（result4-3.xlsx）" % format(DELIV_TOTAL, ",.2f"))
    say("=" * 100)
    ok, _ = anchor_check(cache)
    if not ok:
        say("❌ 锚点未命中 ⇒ 夹具或脚本坏了，**不要信下面的搜索**。")
        return 1

    if mode == "lam":
        lams = [0.0, 0.25, 0.5, 0.75, 1.0]
        say("")
        say("【阶段 A】情景中心阻尼 λ：中心 = F̂ + λ·h（λ=1 即交付，λ=0 即 τ 失效）")
        specs = [dict(scen=l, tau=base) for l in lams]
        r = run_jobs(specs, cache)
        say("  %-8s %18s %16s" % ("λ", "总费(元)", "与交付之差"))
        for l in lams:
            v = r[key_of(dict(scen=l, tau=base))]
            dv = "—（锚点）" if l == 1.0 else (format(v - DELIV_TOTAL, "+,.2f") if isinstance(v, float) else "—")
            say("  %-8.2f %18s %16s" % (l, fmt(v), dv))
        cand = [(l, r[key_of(dict(scen=l, tau=base))]) for l in lams]
        cand = [(l, v) for l, v in cand if isinstance(v, float)]
        if cand:
            bl, bv = min(cand, key=lambda t: t[1])
            say("  ⇒ 固定 τ 下 λ 最优 %.2f（%s 元），比交付省 %s 元"
                % (bl, fmt(bv), format(DELIV_TOTAL - bv, ",.2f")))

    elif mode == "cd":
        say("")
        say("【阶段 B】λ × 五维 τ 联合坐标下降（6 维）")
        axes = ["scen"] + ["tau"] * 5
        grids = [[0.0, 0.25, 0.5, 0.75, 1.0]] + [[base[i]] for i in range(5)]
        c, b = cd(cache, dict(scen=1.0, tau=base), axes, grids)
        # 第二轮：τ 全网格放开
        axes2 = ["scen"] + ["tau"] * 5
        grids2 = [[0.0, 0.25, 0.5, 0.75, 1.0]] + tau_grids(base)
        c2, b2 = cd(cache, c, axes2, grids2, rounds=6)
        if isinstance(b2, float):
            say("")
            say("  ⇒ 联合最优 %s → **%s 元**（比交付省 **%s 元 / %.3f%%**）"
                % (_fmt_spec(c2), fmt(b2), format(DELIV_TOTAL - b2, ",.2f"),
                   (DELIV_TOTAL - b2) / DELIV_TOTAL * 100))
            basin(cache, b2)

    elif mode == "fc":
        say("")
        say("【阶段 C】预报器变体（O3）—— 先在起跑 τ 上**筛一遍**，只给有希望的变体重扫 τ₀")
        modes = ["deliv", "span14", "span21", "span28", "all", "dow", "pool",
                 "lev0.35", "lev0.7", "lev1.0"]
        s0s = [dict(fc=m, tau=base) for m in modes]
        r0 = run_jobs(s0s, cache)
        say("  %-10s %18s %16s" % ("变体", "总费(元)", "与交付之差"))
        ranked = []
        for m in modes:
            v = r0[key_of(dict(fc=m, tau=base))]
            say("  %-10s %18s %16s" % (m, fmt(v),
               "" if not isinstance(v, float) else format(v - DELIV_TOTAL, "+,.2f")))
            if isinstance(v, float):
                ranked.append((v, m))
        # τ 未重扫 ⇒ 起跑点比较**只用于排序**，不是结论。重扫前 4 名。
        ranked.sort()
        say("")
        say("  ⇒ 起跑点排序前 4：%s（⚠ τ 未重扫，此序**只用于筛**，不是结论）"
            % ", ".join(m for _, m in ranked[:4]))
        modes = [m for _, m in ranked[:4]]
        for m in modes:
            s0 = dict(fc=m, tau=base)
            v0 = run_jobs([s0], cache)[key_of(s0)]
            say("")
            say("  ── fc=%s 起跑点 %s" % (m, fmt(v0)))
            grid = [round(0.36 + STEP * i, 2) for i in range(23)]
            specs = [dict(fc=m, tau=(x,) + tuple(base[1:])) for x in grid]
            r = run_jobs(specs, cache)
            cand = [(x, r[key_of(s)]) for x, s in zip(grid, specs)]
            cand = [(x, v) for x, v in cand if isinstance(v, float)]
            if not cand:
                say("     ✗ 全部失败"); continue
            bx, bv = min(cand, key=lambda t: t[1])
            uniq = len(set(round(v, 2) for _, v in cand))
            say("     τ₀ 重扫最优 %.2f → %s 元｜不同取值 %d/%d %s"
                % (bx, fmt(bv), uniq, len(cand), "✓" if uniq > 1 else "✗ 旋钮失效！"))

    elif mode == "lamcd":
        say("")
        say("【阶段 B2】λ<1 时**重扫 τ₀**，检验它能否反超 λ=1 的 τ 最优 —— O2 是否还有独立增益")
        say("  ⚠ 定 τ 下 λ=0.75 已知劣于 λ=1。若放开 τ₀ 仍不能反超，则 O2 的增益**已被 O1 吃尽**。")
        for lam in (0.5, 0.75, 1.0):
            grid = [round(0.36 + STEP * i, 2) for i in range(23)]
            specs = [dict(scen=lam, tau=(x,) + tuple(base[1:])) for x in grid]
            r = run_jobs(specs, cache)
            cand = [(x, r[key_of(s)]) for x, s in zip(grid, specs)]
            cand = [(x, v) for x, v in cand if isinstance(v, float)]
            if not cand:
                say("  λ=%.2f ✗ 全部失败" % lam); continue
            bx, bv = min(cand, key=lambda t: t[1])
            uniq = len(set(round(v, 2) for _, v in cand))
            say("  λ=%.2f  τ₀ 重扫最优 %.2f → %s 元（%s ｜ 不同取值 %d/%d %s）"
                % (lam, bx, fmt(bv),
                   "**反超**" if bv < DELIV_TOTAL - 146781 - 1 else "未反超",
                   uniq, len(cand), "✓" if uniq > 1 else "✗ 旋钮失效！"))

    elif mode == "pv":
        say("")
        say("【阶段 C2】光伏预报混合 w（0=纯附件3，1=纯同槽历史均值）")
        ws = [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]
        specs = [dict(pv=w, tau=base) for w in ws]
        r = run_jobs(specs, cache)
        for w in ws:
            v = r[key_of(dict(pv=w, tau=base))]
            say("  w=%.1f  %18s  %s" % (w, fmt(v),
               "" if not isinstance(v, float) else format(v - DELIV_TOTAL, "+,.2f")))

    elif mode == "win":
        say("")
        say("【阶段 C3】残差分位池的**近期窗口**（交付=全历史累积池）")
        say("  ⚠ 起跑点比较**不可直接判优** —— 每个窗口都要重扫 τ₀ 才算数。")
        ks = [0, 30, 60, 90, 120, 180, 240]
        specs = [dict(win=k, tau=base) for k in ks]
        r = run_jobs(specs, cache)
        say("  %-8s %18s %16s" % ("窗口(天)", "总费(元)", "与交付之差"))
        for k in ks:
            v = r[key_of(dict(win=k, tau=base))]
            say("  %-8s %18s %16s" % ("全部" if k == 0 else k, fmt(v),
               "" if not isinstance(v, float) else format(v - DELIV_TOTAL, "+,.2f")))
        ranked = sorted((v, k) for k in ks
                        for v in [r[key_of(dict(win=k, tau=base))]] if isinstance(v, float))
        for v, k in ranked[:3]:
            say("")
            say("  ── 窗口=%s（起跑点 %s）：重扫 τ₀" % ("全部" if k == 0 else k, fmt(v)))
            grid = [round(0.36 + STEP * i, 2) for i in range(23)]
            sp = [dict(win=k, tau=(x,) + tuple(base[1:])) for x in grid]
            rr = run_jobs(sp, cache)
            cand = [(x, rr[key_of(s)]) for x, s in zip(grid, sp)]
            cand = [(x, v2) for x, v2 in cand if isinstance(v2, float)]
            if not cand:
                say("     ✗ 全部失败"); continue
            bx, bv = min(cand, key=lambda t: t[1])
            uniq = len(set(round(v2, 2) for _, v2 in cand))
            say("     τ₀ 重扫最优 %.2f → %s 元｜不同取值 %d/%d %s"
                % (bx, fmt(bv), uniq, len(cand), "✓" if uniq > 1 else "✗ 旋钮失效！"))

    elif mode == "exec":
        say("")
        say("【阶段 D】价格感知执行器（O4）")
        specs = [dict(tau=base), dict(exec="planfollow", tau=base),
                 dict(exec="refill", tau=base)] \
            + [dict(exec=["gate", q], tau=base) for q in (0.25, 0.5, 0.6, 0.75, 0.9)]
        r = run_jobs(specs, cache)
        say("  %-24s %18s %16s" % ("执行器", "总费(元)", "与交付之差"))
        for s in specs:
            v = r[key_of(s)]
            say("  %-24s %18s %16s" % (_fmt_spec(s) or "交付贪心", fmt(v),
               "" if not isinstance(v, float) else format(v - DELIV_TOTAL, "+,.2f")))

    elif mode == "shift":
        say("")
        say("【阶段 E】直接平移族：中心 = F̂ + shift（绕过 τ 的非线性参数化）")
        shs = [0, 200, 400, 600, 800, 1000, 1500]
        specs = [dict(scen=["shift", [s] * 4], tau=base) for s in shs]
        r = run_jobs(specs, cache)
        for s in shs:
            v = r[key_of(dict(scen=["shift", [s] * 4], tau=base))]
            say("  shift=%5d kWh  %18s  %s" % (s, fmt(v),
               "" if not isinstance(v, float) else format(v - DELIV_TOTAL, "+,.2f")))
    else:
        say("未知模式 %r" % mode)
        return 2

    txt = "\n".join(OUT)
    with open(os.path.join(E.DIAG, "_p4_hedge_%s.txt" % mode), "w", encoding="utf-8") as f:
        f.write(txt + "\n")
    print("\n[已写入] 代码/诊断/_p4_hedge_%s.txt" % mode)
    return 0


if __name__ == "__main__":
    sys.exit(main())
