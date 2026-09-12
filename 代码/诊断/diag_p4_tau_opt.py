# -*- coding: utf-8 -*-
"""问题 4-3 **交付用** τ 的最优搜索（五维联合，坐标下降 + 缓存）。

    python 代码/诊断/diag_p4_tau_opt.py            # 搜索
    python 代码/诊断/diag_p4_tau_opt.py --table    # 只打印已缓存结果，不跑求解

为什么需要本脚本
------------------------------------------------------------------
**原交付 τ=(0.55, 0.42, 0.42) 是从问题 3 逐位继承的** —— 目的是让问题 4 与问题 3
构成**只换价格向量**的受控对照（§6.1 那条"策略逐槽相异 0/48,096"）。

但 `diag_p4_tau.py` 实测：本问自己的最优远不在此（三维联合可省约 4.96 万元）。
而那一轮**只试了 6 个手挑的配置点**，不是搜索 ⇒ 那个数只是"已知的一个好点"。

本脚本把这件事做干净：在交付格（追索 + `G` 无上界 + 读法 B + WQ=0 + 因果锚点）
上做**坐标下降**，逐轮把各维扫到底，直到无改进。产出**本问自己扫出来的最优 τ**，
并据此**替换交付 τ**（自 2026-09-12 起；旧的共享 τ 退居为 §6.1 受控消融的固定点）。

**为什么是五维而不是三维**（这是与 `diag_p4_tau.py` 的关键区别）
`TAU_B` 是四块分位；交付点与问题 3 的记法把**第 1–3 块绑成同一个数**（τ₁=τ₂=τ₃），
于是 τ 只有 (τ₀, τ', τ'') 三个自由度。**但那个绑定是继承来的约定，不是本问的性质**：
附件 3 的逐档预报质量本就不同（净需求 RMSE 矩阵显示 6:00／12:00 档有独立信息，
**18:00 档无增量**）⇒ 三块的不确定性结构不同，没有理由用同一个分位。
故本脚本把 τ₁／τ₂／τ₃ 各自放开，共五维。绑定只是这个五维空间里的一条对角线。

⚠ 交付换成最优 τ 之后，**§6.1 的受控对照就断了**（τ 不再与问题 3 相同）。
那是刻意的取舍，不是副作用；那一条结论降级为**明确标注的受控消融**保留。

⚠ 判据纪律（本项目反复踩的坑，一律保留）：
  · 每张扫描表都打印「不同取值个数」—— 全同即"旋钮失效"，是静默假阴性；
  · 锚点必须先把**共享 τ 点**扫出 **14,404,088**，否则整表不可信
    （该点是历史交付值，**不是**本次要交付的点）；
  · 收敛后打印**盆地平坦度**：若最优邻域内几十元内的点有一大片，
    说明"增益"本身在报告精度上不稳健，必须如实披露。
"""
import io
import json
import os
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CACHE = os.path.join(BASE, "代码", "诊断", "_p4_tauopt_cache.json")
WORKERS = 6          # ⚠ 别调高：内存争抢会把进程压垮，表现是"随机"失败（见 diag_p4_quad.py）
STEP = 0.02

#                       τ₀      τ₁      τ₂      τ₃      τ''
LABELS = ("τ₀(0:00)", "τ₁(6:00)", "τ₂(12:00)", "τ₃(18:00)", "τ''(调整层)")
# ⚠ 区间是**扩过一次**的，别缩回去。第一版取 τ₀ 0.36–0.72、其余 0.20–0.60，结果
#   **τ₃ 的最优直接顶在上边界 0.60** —— 那多半是被网格卡住的伪最优，不是内点最优
#   （`sweep_axis()` 现在会硬提示）。故 τ₃ 上界提到 0.90，其余各维也一并放宽，
#   免得改完 τ₃ 之后 τ₁/τ₂ 的最优又跑到别处的边界外面去。
#   每次扩区都不作废已算的格：缓存以五维元组为键，扩区只是新增要算的点。
GRIDS = (
    [round(0.36 + STEP * i, 2) for i in range(23)],      # τ₀  0.36 .. 0.80
    [round(0.16 + STEP * i, 2) for i in range(30)],      # τ₁  0.16 .. 0.74
    [round(0.16 + STEP * i, 2) for i in range(30)],      # τ₂  0.16 .. 0.74
    [round(0.16 + STEP * i, 2) for i in range(38)],      # τ₃  0.16 .. 0.90（曾顶到 0.60 上界）
    [round(0.16 + STEP * i, 2) for i in range(28)],      # τ'' 0.16 .. 0.70
)
NAX = len(GRIDS)

# ⚠ 下面这两个是**锚点**，不是交付值：SHARED = 与问题 3 共享的 τ（受控对照用），
#   它的总费 14,404,088.07 是**历史点**，用来证明"本脚本的旋钮与脚本本身没坏"。
#   交付 τ 由本脚本搜出来的最优点给出（见文末结果），**不再是**这个点。
SHARED = (0.55, 0.42, 0.42, 0.42, 0.42)     # 继承自问题 3
SHARED_TOTAL = 14_404_088.0                 # 该锚点必须复现的值（= 历史 4-3 交付值）
DELIVERY = SHARED                           # 保留旧名，供坐标下降起点与对账使用
DELIVERY_TOTAL = SHARED_TOTAL
OUT = []


def say(s=""):
    print(s, flush=True)
    OUT.append(s)


_LOCK = threading.Lock()


def _load():
    if os.path.exists(CACHE):
        with open(CACHE, encoding="utf-8") as f:
            return {tuple(json.loads(k)): v for k, v in json.load(f).items()}
    return {}


def _save(c):
    with _LOCK:
        tmp = CACHE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({json.dumps(list(k)): v for k, v in c.items()}, f, indent=0)
        os.replace(tmp, CACHE)


def _snip():
    return (
        "import sys\n"
        "sys.path.insert(0, r'%s')\n"
        "import problem4_3 as P\n"
        "r = P.run(1.0)\n"
        "print('RESULT|%%.4f' %% (r['total'],))\n" % os.path.join(BASE, "代码")
    )


def run_one(k):
    """跑一格（五维分位）。失败返回 None（**None 必须当作"没算过"**，见 quad 脚本）。"""
    env = dict(os.environ)
    # ⚠ 交付配置的旋钮**一次给全**（与 problem4_3._DELIVERY 逐项对齐）。
    #   这几个的缺省值当前恰好等于交付值，但**不能靠缺省**：只设一部分旋钮会静默拿到
    #   "交付 τ + 别的缺省" 的杂配，而输出看上去完全正常 —— 本项目反复踩的坑（§6.4 陷阱 4）。
    #   另有锚点兜底：交付点必须复现 14,404,088，对不上就直接判失败。
    env.update(P4_REC="1", P4_GMAX="20000", P4_READING="B", P4_WQ="0", P4_SENT="0",
               P4_WRITE="0", P4_NOWRITE="1", P4_ANCHOR="prev", PYTHONIOENCODING="utf-8",
               P4_GSPAN="7", P4_GTRAIN="31", P4_LEVEL="1", P4_BANDS="3",
               P4_ADJ="1", P4_PLAN="lp", P4_EXEC="plan", P4_LAMS="1.0")
    for kk in ("P4_PSCALE", "P4_PRICE_SRC", "P4_OUT", "P4_TAU"):
        env.pop(kk, None)
    env["P4_TAUB"] = ",".join("%.2f" % x for x in k[:4])
    env["P4_TAUP"] = "%.2f" % k[4]
    try:
        p = subprocess.run([sys.executable, "-c", _snip()], capture_output=True,
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


def sweep_axis(cache, axis, base_pt, xs):
    """沿一维扫到底（其余维钉在 base_pt）。返回 (最优取值, 总费)。"""
    jobs = []
    for x in xs:
        pt = list(base_pt)
        pt[axis] = x
        jobs.append(tuple(pt))
    todo = [j for j in jobs if cache.get(j) is None]
    if todo:
        say("    %s：%d 点，其中 %d 点需算（%d 并发）"
            % (LABELS[axis], len(jobs), len(todo), WORKERS))
        done = [0]

        def one(j):
            v = run_one(j)
            with _LOCK:
                cache[j] = v
                done[0] += 1
                n = done[0]
            if n % 10 == 0 or n == len(todo):
                _save(cache)

        with ThreadPoolExecutor(max_workers=WORKERS) as ex:
            for _ in ex.map(one, todo):
                pass
        _save(cache)
    else:
        say("    %s：%d 点全部命中缓存" % (LABELS[axis], len(jobs)))

    vals = {j[axis]: cache[j] for j in jobs if cache.get(j) is not None}
    if not vals:
        say("      ✗ 本维全部失败，跳过（**不要**据此判无改进）")
        return None, None
    best = min(vals, key=vals.get)
    uniq = len(set(round(v, 2) for v in vals.values()))
    say("      %s ∈ [%.2f, %.2f]：最优 %.2f（%s 元）｜不同取值 %d/%d %s"
        % (LABELS[axis], min(vals), max(vals), best,
           format(vals[best], ",.2f"), uniq, len(vals),
           "✓ 旋钮生效" if uniq > 1 else "✗ 旋钮失效，全表同值！"))
    # ⚠ **边界命中检查**：若本维最优落在扫描区间的端点上，那多半不是真最优，
    #   而是被网格边缘卡住了 —— 一个"伪内点最优"。本项目在 `diag_p4_tau.py` 里
    #   专门为此写过警告（τ₀ 那张表曾把 base 查错键而整列静默空白），此处改为硬提示。
    #   实测：第一轮 τ₃ 的最优就落在上边界 0.60，扩到 0.80 后确实又降了 3,600 元。
    if best is not None and (abs(best - min(vals)) < 1e-9 or abs(best - max(vals)) < 1e-9):
        say("      ⚠ **最优落在扫描边界上（%s = %.2f）** ⇒ 真最优可能在此区间**之外**，"
            % (LABELS[axis], best))
        say("        本维结论**不可当内点最优**用，须扩 GRIDS[%d] 后重跑（缓存会保留已算格）。"
            % axis)
    return best, vals[best]


def basin(cache, pt, best_val, tol=2_000.0):
    """盆地平坦度：最优邻域 tol 元内的点各维取值范围。"""
    say("")
    say("盆地平坦度（总费在最优 +%s 元以内的点，各维的取值范围）" % format(tol, ",.0f"))
    near = [k for k, v in cache.items()
            if v is not None and len(k) == NAX and v <= best_val + tol]
    say("  +%s 元内共 %d 格（含最优点）" % (format(tol, ",.0f"), len(near)))
    for i in range(NAX):
        vs = sorted({k[i] for k in near})
        say("    %-12s %s" % (LABELS[i],
                              "—" if not vs else
                              ("%.2f" % vs[0] if len(vs) == 1
                               else "%.2f ～ %.2f（%d 档）" % (vs[0], vs[-1], len(vs)))))
    say("  ⇒ 邻域越宽 = 最优点越不唯一 = 增益在报告精度上越不稳健；须如实披露。")


def main():
    cache = _load()
    if "--table" in sys.argv:
        ok = {k: v for k, v in cache.items() if v is not None and len(k) == NAX}
        if not ok:
            say("缓存里没有五维结果。")
            return 0
        best = min(ok, key=ok.get)
        say("缓存 %d 格（有效 %d）；最优 %s → %s 元"
            % (len(cache), len(ok), best, format(ok[best], ",.2f")))
        return 0

    say("=" * 100)
    say("问题 4-3 交付用 τ 最优搜索（**五维**：τ₀/τ₁/τ₂/τ₃/τ''）")
    say("交付格：追索 + G无上界 + 读法B + WQ=0 + 因果锚点，334 天口径 A，步长 %.2f" % STEP)
    say("=" * 100)

    if cache.get(DELIVERY) is None:
        cache[DELIVERY] = run_one(DELIVERY)
        _save(cache)
    got = cache.get(DELIVERY)
    say("锚点：τ=%s（继承自问题 3）→ %s 元，期望 %s %s"
        % (DELIVERY, "算不出" if got is None else format(got, ",.2f"),
           format(DELIVERY_TOTAL, ",.2f"),
           "✓" if got is not None and abs(got - DELIVERY_TOTAL) < 1.0 else "✗"))
    if got is None or abs(got - DELIVERY_TOTAL) >= 1.0:
        say("❌ 锚点未命中 —— 旋钮或脚本坏了，**不要信下面的搜索**。")
        return 1

    say("")
    say("坐标下降（每轮五维各自扫到底，取全局最优方向前进）")
    pt = list(DELIVERY)
    cur = got
    for rnd in range(1, 8):
        say("")
        say("  第 %d 轮：从 %s（%s 元）出发"
            % (rnd, tuple("%.2f" % x for x in pt), format(cur, ",.2f")))
        moved = False
        for axis in range(NAX):
            bx, bv = sweep_axis(cache, axis, pt, GRIDS[axis])
            if bv is not None and bv < cur - 1e-6:
                pt[axis] = bx
                cur = bv
                moved = True
        say("    ⇒ 本轮结束于 %s（%s 元）"
            % (tuple("%.2f" % x for x in pt), format(cur, ",.2f")))
        if not moved:
            say("    ⇒ 五维均已无改进 ⇒ **收敛**")
            break
    else:
        say("")
        say("  ⚠ 已达最大轮数仍未收敛，最优可能还在更远处（报告时须声明）。")

    say("")
    say("=" * 100)
    say("结果")
    say("=" * 100)
    say("  交付点（继承问题 3 的 τ）%s → **%s 元**"
        % (tuple("%.2f" % x for x in DELIVERY), format(got, ",.2f")))
    say("  本问最优 τ（五维搜索）      %s → **%s 元**"
        % (tuple("%.2f" % x for x in pt), format(cur, ",.2f")))
    d = got - cur
    say("  ⇒ 换用最优 τ 可省 **%s 元（%.3f%%）**"
        % (format(d, ",.2f"), d / got * 100))
    say("")
    # 与"三块绑在一起"的旧结论对账，免得两个数被混引。
    say("  对照：若仍把第 1–3 块绑成同一个 τ'（承袭问题 3 的记法），本脚本第 2/3/4 维")
    say("        就退化成同一条对角线 —— 旧记录的三维联合最优 14,354,467 元即那条线上")
    say("        的手挑点。五维放开后还能再往下走多少，看上面的差值即可。")
    say("")
    basin(cache, pt, cur)
    say("")
    # 直接把要改的那两行**原样打印**出来：转录这一步本项目已经错过不止一次
    # （手抄的 τ 副本不会报错，只会安静地跑在别的配置上）。照抄比手打安全。
    say("  ── 抄这一行进 `problem4_3._DELIVERY`（τ 与声明总费一起改，别只改一半）──")
    say("     taub=[%s], taup=%g, total=%s)"
        % (", ".join("%g" % x for x in pt[:4]), pt[4], format(cur, ".2f")))
    say("     ⚠ `total` 会被 `problem4_3.__main__` 硬校验：改成 %.2f 之后，" % cur)
    say("       必须同时重跑 `python 代码/run_problem4.py` 生成新的 result4-3.xlsx，")
    say("       否则下一次跑交付配置会直接 SystemExit。")
    say("     ⚠ `_SHARED_TAU` **不要动** —— 它是与问题 3 共享的 τ，供受控消融用。")
    say("")
    say("  ⚠ **代价（必须与上面的收益一起披露）**：换 τ 之后，问题 4 与问题 3 的 τ 不再相同，")
    say("     §6.1 那条「只换价格向量、策略逐槽相异 0/48,096」的**受控对照断掉**。")
    say("     故该结论须降级为**明确标注的受控消融**（τ 固定为 %s 的那一跑），"
        % (tuple("%.2f" % x for x in DELIVERY),))
    say("     不能再作为交付配置下的头条验证。")

    txt = "\n".join(OUT)
    with open(os.path.join(BASE, "代码", "诊断", "_p4_tauopt.txt"), "w", encoding="utf-8") as f:
        f.write(txt + "\n")
    print("\n[已写入] 代码/诊断/_p4_tauopt.txt")
    return 0


if __name__ == "__main__":
    sys.exit(main())
