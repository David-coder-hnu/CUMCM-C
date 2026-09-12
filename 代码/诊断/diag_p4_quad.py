# -*- coding: utf-8 -*-
"""★ 问题 4 四象限：计划层（确定性 / 追索）× `G_MAX` 读法（≤5000 / 无上界），**每格各自调 τ**。

    python 代码/诊断/diag_p4_quad.py            # 扫描（带缓存，已算过的格直接读缓存）
    python 代码/诊断/diag_p4_quad.py --refine   # 在各方格最优点周围加密再扫一轮
    python 代码/诊断/diag_p4_quad.py --seed     # 只算两个锚点，**先验扫描可信再花时间扫全表**
    python 代码/诊断/diag_p4_quad.py --table    # 只打印汇总表，不跑任何求解

为什么必须"每格各自调 τ"：**τ 必须随计划层重调**（本轮头条方法学结论）。旧 τ=(0.80,0.55)
是确定性计划时代的定稿，搬到追索层偏贵 185,974 元。跨格比较若用同一套 τ，等于**用错误的
τ 去诋毁对方**，四象限表就失去意义。故本脚本的做法是：每格先扫 τ 到最优，再横向比总费。

τ 的记法：τ₀ = 第 0 块（0:00，不可调整）的分位；τ' = 第 1–3 块与调整层的分位。
本脚本把**调整层分位 τ'（P4_TAUP）与第 1–3 块的分位绑成同一个数** —— 与交付点一致
（交付点 τ=(0.55, 0.42) 且 TAUP=0.42），也与问题 3 四象限的记法一致。

两个**已知锚点**用于验证本脚本没说谎（扫描必须把它们扫出来）：

  · 总费锚 `追索 + G无上界 + τ=(0.55,0.42)` → **14,404,088** = 4-3 **历史**交付值
    （自 2026-09-12 起 4-3 交付 τ 改为本问自己的五维最优，见 `diag_p4_tau_opt.py`；
     这个点**已不是交付值**，但它的值不随交付 τ 改动而变，故仍可用来证明管线没漂）；
  · 同源锚 同一格改用**常数价回归**（`P4_PRICE_SRC=att1`）→ 必须逐位复现问题 3 的交付值
    **13,641,420**。后者比前者强：它证明两条交付物**同源**，而不是碰巧同值。

⚠ 旧文档曾写「确定性 + G≤5000 → 14,285,731 是 4-3 旧交付」——那是**去前视之前**的数，
  已作废；现在该格的最优由本表自己扫出（见 `--table`），不由外部给定。

锚点扫不出来 = 脚本或旋钮坏了，**不要信这张表**。

⚠ 旋钮必须一次给全：只设 `P4_GMAX` 而不设 `P4_REC`/τ，会静默拿到"缺省 τ + 指定上界"
   的杂配，正是本项目反复踩的坑（taskrun §6.5）。
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
SCRIPT = os.path.join(BASE, "代码", "problem4_3.py")
CACHE = os.path.join(BASE, "代码", "诊断", "_p4_quad_cache.json")
WORKERS = 6          # ⚠ 别调高。2026-09-12 实测：两个扫描（12+8 并发）同时跑、
                     #   再叠上其它会话的重活，把 31.8 GB 内存压垮，进程被系统杀掉 ——
                     #   表现是 `run()` 拿到非零返回码后记 None，而**失败率与运行时长
                     #   正相关**（最慢的 rec=1/G无上界 挂 42.5%，最快的 rec=0/G无上界
                     #   挂 20.4%）。那是**资源争抢，不是模型或代码的错**：同样的配置
                     #   单跑必成。故本表要在**独跑**时以低并发重算，且两个扫描不要并行。

T0 = [0.50, 0.55, 0.60, 0.70, 0.80, 0.90]                 # 第 0 块分位
T1 = [0.25, 0.30, 0.36, 0.42, 0.48, 0.55, 0.65, 0.75]     # 第 1–3 块 + 调整层分位

# (标签, P4_REC, P4_GMAX, 该格 τ 是否与问题 3 已知锚点一致)
CELLS = [
    ("确定性计划 + G≤5000",   "0", "5000",  "四象限·左上"),
    ("确定性计划 + G无上界",  "0", "20000", "四象限·右上"),
    ("追索计划   + G≤5000",   "1", "5000",  "四象限·左下"),
    ("追索计划   + G无上界",  "1", "20000", "四象限·右下（问题 3 交付格；4-3 不再定稿于此）"),
]
# ⚠ 锚点是**管线检查**（证明本扫描用的旋钮/脚本没坏），不是"交付点"。
#   自 2026-09-12 起交付 τ 改为**本问自己的五维最优**（见 diag_p4_tau_opt.py），
#   而本表只扫二维 τ 切片、且把 τ'' 绑在 τ' 上 —— **交付点已不在本表的网格里**。
#   保留这个历史点做锚点仍然正确：它的值不随交付 τ 改动而变，故仍能证明管线没漂。
ANCHORS = {("1", "20000"): (0.55, 0.42, 14404088.0)}
# 同源锚点：同一格在**常数价回归**（P4_PRICE_SRC=att1）下必须精确复现问题 3 的交付值。
# 这是比"总费对得上"更强的判据 —— 它证明两条交付物**逐位同源**，而非碰巧同值。
# ⚠ 问题 3 第三次定稿（整点锚点去前视）后此值为 13,641,420；再定稿须同步。
P3_SYNC_TOTAL = 13_641_420.0
P3_SYNC_CELL = ("1", "20000", 0.55, 0.42)


def _load():
    if os.path.exists(CACHE):
        with open(CACHE, encoding="utf-8") as f:
            return {tuple(json.loads(k)): v for k, v in json.load(f).items()}
    return {}


_SAVE_LOCK = threading.Lock()


def _save(c):
    # 加锁：_save 现在会被多个 worker 线程调用，两个 json.dump 交错会写出坏 JSON。
    # 而坏 JSON 会让**整轮缓存作废** —— 正是这机制本该避免的损失。
    with _SAVE_LOCK:
        tmp = CACHE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({json.dumps(list(k)): v for k, v in c.items()}, f, indent=0)
        os.replace(tmp, CACHE)          # 原子替换：崩在写一半也不会留下残缺缓存


def run(rec, gmax, t0, t1, price_src="att4"):
    """跑一格，返回总费（元）；失败返回 None。price_src='att1' 走常数价回归（同源自检用）。"""
    e = os.environ.copy()
    e.update(P4_REC=rec, P4_GMAX=gmax,
             P4_TAUB=f"{t0},{t1},{t1},{t1}", P4_TAUP=str(t1),
             P4_WRITE="0", P4_SENT="0", PYTHONIOENCODING="utf-8",
             P4_PRICE_SRC=price_src)
    for k in ("P4_TAU", "P4_PSCALE", "P4_OUT", "P4_NOWRITE"):
        e.pop(k, None)
    try:
        p = subprocess.run([sys.executable, SCRIPT], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", env=e, cwd=BASE, timeout=900)
    except subprocess.TimeoutExpired:
        return None
    if p.returncode != 0:
        return None
    for ln in reversed(p.stdout.splitlines()):
        if "年费" in ln and "元" in ln:
            try:
                return float(ln.split("年费")[1].replace("元", "").replace(",", "").strip())
            except ValueError:
                return None
    return None


def sweep(cache, jobs, label):
    """并行跑 jobs（未缓存的），就地填 cache。"""
    # ⚠ 必须用 `cache.get(j) is None` 而**不是** `j not in cache`：失败格的缓存值是 None，
    #   键是**在**的 —— 用 `not in` 会把失败当成"已算过"，于是**失败格永远不会重试**。
    #   实测：两轮扫描争内存时挂了 110/428 格，交付格 rec=1/G无上界 挂了 42.5%，
    #   而 `not in` 让这些缺口一次都没被补上。None 必须当作"没算"。
    todo = [j for j in jobs if cache.get(j) is None]
    if not todo:
        print(f"  {label}：{len(jobs)} 格全部命中缓存")
        return
    print(f"  {label}：{len(jobs)} 格，其中 {len(todo)} 格需算"
          f"（{WORKERS} 并发，约 {len(todo) * 20 / WORKERS / 60:.1f} min）", flush=True)
    done = [0]

    def one(j):
        v = run(*j)
        cache[j] = v
        # ⚠ 计数必须在锁里：`done[0] += 1` 是 LOAD/ADD/STORE 三步，多个 worker 线程并发时
        #   会丢增量 —— 症状是进度条偏慢、且 `== len(todo)` 可能永不成立（于是**最后一次
        #   边跑边存不触发**）。结尾那次 `_save` 还在，所以不至丢数据，但进度与存盘时机都会
        #   失真。`diag_p3_quad.py` 一直是有锁的，这里是补上对齐。
        with _SAVE_LOCK:
            done[0] += 1
            n = done[0]
        if n % 10 == 0 or n == len(todo):
            print(f"    …{n}/{len(todo)}", flush=True)
            _save(cache)      # ⚠ 必须**边跑边存**：只在最后存一次的话，中途 Ctrl-C
                              #   就丢掉整轮（每格 20s，一轮十几分钟，丢不起）。
        return j, v

    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        for _ in ex.map(one, todo):
            pass
    _save(cache)


def grid_of(rec, gmax, t0s, t1s):
    return [(rec, gmax, a, b) for a in t0s for b in t1s]


def argmin(cache, rec, gmax):
    """该格已算过的点里的最优 (τ₀, τ') 与总费。"""
    best, bv = None, None
    for k, v in cache.items():
        if k[0] == rec and k[1] == gmax and v is not None and (bv is None or v < bv):
            bv, best = v, (k[2], k[3])
    return best, bv


def show(cache, rec, gmax, t0s, t1s, title):
    print(f"\n  {title}")
    print("     τ₀＼τ'".ljust(11) + "".join(f"{b:>12.2f}" for b in t1s))
    best, bv = None, None
    for a in t0s:
        row = []
        for b in t1s:
            v = cache.get((rec, gmax, a, b))
            row.append(v)
            if v is not None and (bv is None or v < bv):
                bv, best = v, (a, b)
        cells = "".join("          — " if v is None else f"{v:>12,.0f}" for v in row)
        print(f"     {a:<6.2f}{cells}")
    if best:
        print(f"     ⇒ 内点最优 τ₀={best[0]:.2f}  τ'={best[1]:.2f}  → **{bv:,.0f} 元**")
    return best, bv


def main():
    refine = "--refine" in sys.argv
    cache = _load()

    if "--seed" in sys.argv:
        print("只算锚点（不扫全表）——先验证旋钮/脚本没说谎。")
        for (rec, gmax), (a, b, want) in ANCHORS.items():
            k = (rec, gmax, a, b)
            if cache.get(k) is None:
                cache[k] = run(rec, gmax, a, b)
            v = cache[k]
            hit = v is not None and abs(v - want) < 1e-6
            print(f"  [总费] rec={rec} gmax={gmax} τ=({a},{b}) → "
                  f"{'算不出' if v is None else format(v, ',.0f')}  期望 {want:,.0f}  "
                  f"{'✓' if hit else '✗'}")
        # 同源自检：常数价回归必须精确复现问题 3 交付值
        w = run(*P3_SYNC_CELL, price_src="att1")
        hit = w is not None and abs(w - P3_SYNC_TOTAL) < 1.0
        print(f"  [同源] rec={P3_SYNC_CELL[0]} gmax={P3_SYNC_CELL[1]} "
              f"τ=({P3_SYNC_CELL[2]},{P3_SYNC_CELL[3]}) 常数价回归 → "
              f"{'算不出' if w is None else format(w, ',.2f')}  "
              f"期望 {P3_SYNC_TOTAL:,.0f}  {'✓ 与问题 3 同源' if hit else '✗ 失同步'}")
        _save(cache)
        return 0

    if "--table" not in sys.argv:
        print("=" * 104)
        print("问题 4 四象限 τ 扫描（problem4_3.py，价格源 att4，读法 B，WQ=0，span7）")
        print("=" * 104)
        coarse = [j for _, rec, gmax, _ in CELLS for j in grid_of(rec, gmax, T0, T1)]
        sweep(cache, coarse, f"粗扫 4×{len(T0) * len(T1)}")

        if refine:
            print("\n加密轮（各方格最优点 ±0.05 / ±0.06 内）")
            for _, rec, gmax, _ in CELLS:
                cur = show(cache, rec, gmax, T0, T1, f"粗扫 rec={rec} gmax={gmax}")
                if not cur[0]:
                    continue
                a0, b0 = cur[0]
                a_s = [round(a0 + d, 2) for d in (-0.05, -0.04, -0.03, -0.02, -0.01, 0.01,
                                                 0.02, 0.03, 0.04, 0.05)]
                b_s = [round(b0 + d, 2) for d in (-0.06, -0.04, -0.02, 0.02, 0.04, 0.06)]
                sweep(cache, grid_of(rec, gmax, a_s, b_s), f"  加密 rec={rec} gmax={gmax}")
                show(cache, rec, gmax, sorted(set(T0 + a_s)), sorted(set(T1 + b_s)),
                     f"加密后 rec={rec} gmax={gmax}")

    print("\n" + "=" * 104)
    print("四象限汇总（每格各自调平 τ）")
    print("=" * 104)
    print(f"  {'计划层 ＼ G_MAX 读法':<24s}{'G ≤ 5000':>26s}{'G 无上界':>26s}")
    rows = {k: argmin(cache, *k) for k in ((c[1], c[2]) for c in CELLS)}
    for rec, name in (("0", "确定性计划"), ("1", "追索计划")):
        cs = []
        for gmax in ("5000", "20000"):
            b, v = rows.get((rec, gmax), (None, None))
            cs.append("—" if v is None else f"{v:,.0f}（τ₀={b[0]:.2f}, τ'={b[1]:.2f}）")
        print(f"  {name:<24s}{cs[0]:>26s}{cs[1]:>26s}")
    print("\n  锚点校验（必须逐位命中；先跑 --seed 再跑本表）")
    ok = True
    for (rec, gmax), (a0, b0, want) in ANCHORS.items():
        got = cache.get((rec, gmax, a0, b0))
        hit = got is not None and abs(got - want) < 1e-6
        ok &= hit
        print(f"    [总费] rec={rec} gmax={gmax} τ=({a0},{b0}) → "
              f"{'—' if got is None else format(got, ',.0f')}  期望 {want:,.0f}  "
              f"{'✓' if hit else '✗ 与已知值不符'}")
    print(f"\n  {'✅ 锚点命中 —— 扫描可信。' if ok else '❌ 锚点未命中 —— 本表不可信，先查旋钮。'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
