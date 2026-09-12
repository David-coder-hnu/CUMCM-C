# -*- coding: utf-8 -*-
"""★ 问题 3 四象限：计划层（确定性 / 追索）× `G_MAX` 读法（≤5000 / 无上界），**每格各自调 τ**。

    python 代码/诊断/diag_p3_quad.py --seed     # 先算锚点，验证扫描可信
    python 代码/诊断/diag_p3_quad.py            # 粗扫
    python 代码/诊断/diag_p3_quad.py --refine   # 再加密一轮
    python 代码/诊断/diag_p3_quad.py --table    # 只打表

**本文件是 `diag_p4_quad.py` 的问题 3 镜像版**（同 `problem3_recourse.py` / `problem4_3.py`
的关系），两边的网格、锚点判据、缓存机制、并发度**必须保持一致** —— 否则两张四象限表
不可并列比较。**改一边请同步改另一边。**

为什么要重扫（本脚本存在的理由）：问题 3 第三次定稿把调整层的整点锚点从 `pv[d, 6S]`
（含 10 分钟前视）改成 `pv[d, 6S−1]`（严格因果）。交付值 13,630,568 → **13,641,420**。
而本轮的头条方法学结论是 **τ 必须随计划层重调** —— 预报换了，计划层就换了，
**τ 的最优位置必须重扫，不能沿用**。旧四象限里那四个 τ（0.55 / 0.75 / 0.30 / 0.42）
全是**含前视**基准下调出来的，故整张表都要重出。

锚点：追索 + G无上界 + τ=(0.55,0.42) 必须 = **13,641,420**（= 现行交付值）。
锚点扫不出来 = 旋钮或脚本坏了，**不要信这张表**。
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
SCRIPT = os.path.join(BASE, "代码", "problem3_recourse.py")
CACHE = os.path.join(BASE, "代码", "诊断", "_p3_quad_cache.json")
WORKERS = 6          # ⚠ 别调高。2026-09-12 实测：两个扫描（8+12 并发）同时跑、
                     #   再叠上其它会话的重活，把 31.8 GB 内存压垮，进程被系统杀掉 ——
                     #   表现是 `run()` 拿到非零返回码后记 None，而**失败率与运行时长
                     #   正相关**（最慢的 rec=1/G无上界 挂 66.7%，最快的 rec=0/G无上界
                     #   挂 0%）。那是**资源争抢，不是模型或代码的错**：同样的配置单跑
                     #   必成。故本表要在**独跑**时以低并发重算，且两个扫描**不要并行**。

T0 = [0.50, 0.55, 0.60, 0.70, 0.80, 0.90]
T1 = [0.25, 0.30, 0.36, 0.42, 0.48, 0.55, 0.65, 0.75]

CELLS = [
    ("确定性计划 + G≤5000",   "0", "5000",  "四象限·左上"),
    ("确定性计划 + G无上界",  "0", "20000", "四象限·右上"),
    ("追索计划   + G≤5000",   "1", "5000",  "四象限·左下"),
    ("追索计划   + G无上界",  "1", "20000", "四象限·右下（现交付格）"),
]
ANCHORS = {("1", "20000"): (0.55, 0.42, 13641420.0)}


_SAVE_LOCK = threading.Lock()


def _load():
    if os.path.exists(CACHE):
        with open(CACHE, encoding="utf-8") as f:
            return {tuple(json.loads(k)): v for k, v in json.load(f).items()}
    return {}


def _save(c):
    with _SAVE_LOCK:
        tmp = CACHE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({json.dumps(list(k)): v for k, v in c.items()}, f, indent=0)
        os.replace(tmp, CACHE)


def run(rec, gmax, t0, t1):
    """跑一格，返回总费（元）；失败返回 None。"""
    e = os.environ.copy()
    e.update(P3_REC=rec, P3_GMAX=gmax,
             P3_TAUB=f"{t0},{t1},{t1},{t1}", P3_TAUP=str(t1),
             P3_WRITE="0", P3_SENT="0", PYTHONIOENCODING="utf-8")
    # ⚠ 必须清掉 P3_TAU（第 0 块简写旋钮）与其它残留：不清就会静默覆盖 P3_TAUB[0]，
    #   扫出来的却是"混合 τ"的表 —— 本项目反复踩的坑（taskrun §6.5）。
    for k in ("P3_TAU", "P3_GRP", "P3_HSRC", "P3_OUT", "P3_ANCHOR"):
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
    # ⚠ 必须用 `cache.get(j) is None` 而**不是** `j not in cache`：失败格的缓存值是 None，
    #   键是**在**的 —— 用 `not in` 会把失败当成"已算过"，于是**失败格永远不会重试**，
    #   一轮里挂掉的格就永久留在表里当空白。2026-09-12 实测：两个扫描在争抢内存时
    #   挂了 66/370（p3）、110/428（p4）格，其中交付格 rec=1/G无上界 挂了 66.7%，
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
        with _SAVE_LOCK:
            done[0] += 1
            n = done[0]
        if n % 10 == 0 or n == len(todo):
            print(f"    …{n}/{len(todo)}", flush=True)
            _save(cache)
        return j, v

    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        for _ in ex.map(one, todo):
            pass
    _save(cache)


def grid_of(rec, gmax, t0s, t1s):
    return [(rec, gmax, a, b) for a in t0s for b in t1s]


def argmin(cache, rec, gmax):
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
            print(f"  rec={rec} gmax={gmax} τ=({a},{b}) → "
                  f"{'算不出' if v is None else format(v, ',.0f')}  期望 {want:,.0f}  "
                  f"{'✓' if hit else '✗'}")
        _save(cache)
        return 0

    if "--table" not in sys.argv:
        print("=" * 104)
        print("问题 3 四象限 τ 扫描（problem3_recourse.py，整点锚点=因果 prev）")
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
    for rec, name in (("0", "确定性计划"), ("1", "追索计划（现交付）")):
        cs = []
        for gmax in ("5000", "20000"):
            b, v = rows.get((rec, gmax), (None, None))
            cs.append("—" if v is None else f"{v:,.0f}（τ₀={b[0]:.2f}, τ'={b[1]:.2f}）")
        print(f"  {name:<24s}{cs[0]:>26s}{cs[1]:>26s}")
    print("\n  锚点校验")
    ok = True
    for (rec, gmax), (a0, b0, want) in ANCHORS.items():
        got = cache.get((rec, gmax, a0, b0))
        hit = got is not None and abs(got - want) < 1e-6
        ok &= hit
        print(f"    rec={rec} gmax={gmax} τ=({a0},{b0}) → "
              f"{'—' if got is None else format(got, ',.0f')}  期望 {want:,.0f}  "
              f"{'✓' if hit else '✗ 与已知值不符'}")
    print(f"\n  {'✅ 锚点命中 —— 扫描可信。' if ok else '❌ 锚点未命中 —— 本表不可信，先查旋钮。'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
