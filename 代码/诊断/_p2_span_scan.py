# -*- coding: utf-8 -*-
"""★ 问题 2 的 GROUP_SPAN 扫描 + 分组效应归因。

背景：`problem2.py` 定稿 `GROUP_SPAN = 14`，`problem3_v3.py` 定稿 `P3_GSPAN = 7`
—— **两问回看窗口不一致**，而问题 2 归档 §7.2 的五臂里**没有任何窗口变体**，
span 14 是直接选的、从未验证。本脚本补上这次扫描。

同时按问题 3 的方法学把「分组」与「窗口变近」两个效应拆开：
  · 分组臂  arm_group(s)  = 过去 s 天内与当日**同组**的历史日
  · 不分组臂 arm_all7(s)  = 过去 s 天内**全部**历史日（七天一组，等价于"只缩窗口"）
  · 旧基线   A1 K=4       = 前 4 个同星期几日
于是 「只换窗口」= arm_all7(s) − A1，「只换分组」= arm_group(s) − arm_all7(s)。

⚠ `problem2.py` 没有 env 旋钮、没有 `__main__` 守卫（模块级直跑且**无条件写盘**），
所以做**源码级补丁**：副本写进系统临时目录、`BASE` 钉成绝对路径、
`out_path` 改指临时目录（**绝不碰 `结果/result2.xlsx`**）。
"""
import os, sys, json, shutil, tempfile, subprocess
import numpy as np
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC = os.path.join(BASE, "代码", "problem2.py")

OLD_SPAN = "GROUP_SPAN = 6                  # 分组情景集的回看窗口（天）"
OLD_PEERS = """def build_peers_group(dows, span=GROUP_SPAN):
    \"\"\"同组情景集：回看 span 天内、与当日同组的历史日。\"\"\"
    m = np.array([(d % 7) in dows for d in range(NDAYS)])
    return [[t for t in range(max(0, d - span), d) if m[t] == m[d]] for d in range(NDAYS)]"""
OLD_BASE = "BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))"
OLD_OUT = 'out_path = os.path.join(BASE, "结果", "result2.xlsx")'

NEW_SPAN = 'GROUP_SPAN = int(os.environ.get("P2_GSPAN", 14))   # [扫描旋钮] 回看窗口（天）'

NEW_PEERS = '''def build_peers_group(dows, span=None):
    """同组情景集：回看 span 天内、与当日同组的历史日。

    [扫描补丁] `P2_ARM=group` 用分组；`P2_ARM=all7` 用七天一组（= 只缩窗口、
    不分组），用于把「分组」与「窗口变近」两个效应拆开。
    """
    span = GROUP_SPAN if span is None else span
    arm = os.environ.get("P2_ARM", "group").strip().lower()
    if arm == "wd":                       # 真正的旧基线：前 K_PEERS 个同星期几日
        return build_peers_weekday(K_PEERS)
    m = np.ones(NDAYS, dtype=bool) if arm == "all7"         else np.array([(d % 7) in dows for d in range(NDAYS)])
    return [[t for t in range(max(0, d - span), d) if m[t] == m[d]] for d in range(NDAYS)]'''

TAIL = '''

# ── [扫描补丁] 结果回传（不改任何交付文件）────────────────────────────
import json as _json
_TMPOUT = os.environ.get("P2_TMPOUT")
print("JSONP2 " + _json.dumps(dict(
    total=float(r1[0]), plan=float(r1[1]), emerg=float(r1[2]), kwh_em=float(r1[3]),
    sentinel=float(sent[0]), span=int(os.environ.get("P2_GSPAN", 14)),
    arm=os.environ.get("P2_ARM", "group"),
    npeers=float(np.mean([len(p) for p in peers])),
    kwh_g=float(g1.sum() * DT), kwh_c=float(c_exec.sum() * DT),
    kwh_d=float(d_exec.sum() * DT),
    soc_min=float(soc_exec.min()), soc_max=float(soc_exec.max()),
    fallback_all=int(sum(1 for pp in peers if not pp)),
    fallback_billed=int(sum(1 for d_ in range(REPORT, NDAYS) if not peers[d_])),
    daycost=[float(x) for x in
             (((price * g1 * DT) + (5 * price * np.maximum(0.0, L - g1 - P - d_exec) * DT))
              .reshape(NDAYS, N) * win.reshape(NDAYS, N)).sum(axis=1)],
)))
'''

src = open(SRC, encoding="utf-8").read()
for tag, old in [("GROUP_SPAN", OLD_SPAN), ("build_peers_group", OLD_PEERS),
                 ("BASE", OLD_BASE), ("out_path", OLD_OUT)]:
    assert old in src, f"找不到 {tag} 的定义 —— problem2.py 结构变了。"

patched = (src.replace(OLD_BASE, f'BASE = r"{BASE}"')
              .replace(OLD_SPAN, NEW_SPAN)
              .replace(OLD_PEERS, NEW_PEERS)
              .replace(OLD_OUT, 'out_path = os.path.join(BASE, "结果", "_p2_scan_tmp.xlsx")')
              + TAIL)

TMP = tempfile.mkdtemp(prefix="p2span_")
PATCHED = os.path.join(TMP, "problem2_patched.py")
open(PATCHED, "w", encoding="utf-8").write(patched)


def run(arm, span):
    e = os.environ.copy()
    e.update({"GAMMAS": "1.0", "P2_ARM": arm, "P2_GSPAN": str(span), "P2_TMPOUT": ""})
    p = subprocess.run([sys.executable, PATCHED], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", env=e, cwd=BASE)
    for ln in p.stdout.splitlines():
        if ln.startswith("JSONP2 "):
            return json.loads(ln[7:])
    print(f"  ✗ {arm} span={span} 失败\n{p.stdout[-900:]}\n{p.stderr[-900:]}")
    return None


print("=" * 100)
print("问题 2：GROUP_SPAN 扫描（γ=1 可交付计划 + 因果执行，334 个计费日）")
print("=" * 100)

res = {}
for span in (4, 5, 6, 7, 8, 10, 14, 21, 28):
    res[("group", span)] = run("group", span)
    print(f"  分组 span{span:<3} → " + (f"{res[('group', span)]['total']:>13,.0f} 元"
          if res[("group", span)] else "失败"), flush=True)
for span in (5, 6, 7, 10, 14, 21):
    res[("all7", span)] = run("all7", span)
    print(f"  全七天 span{span:<3} → " + (f"{res[('all7', span)]['total']:>13,.0f} 元"
          if res[("all7", span)] else "失败"), flush=True)

# 旧基线：K=4 同星期几（= problem2.py 换分组之前的 A1 臂）
res[("K4", 0)] = run("wd", 0)
print(f"  旧基线 K=4   → " + (f"{res[('K4', 0)]['total']:>13,.0f} 元"
      if res[("K4", 0)] else "失败"), flush=True)

print("\n" + "=" * 100)
print("① 窗口扫描（元）")
print("=" * 100)
print(f"  {'span':<8}{'分组（交付口径）':>20}{'全七天（只缩窗口）':>22}{'分组增益':>15}{'vs span14':>14}")
base_g = res[("group", 14)]["total"] if res[("group", 14)] else None
for span in (4, 5, 6, 7, 8, 10, 14, 21, 28):
    g = res.get(("group", span)); a = res.get(("all7", span))
    if not g: continue
    ga = f"{g['total'] - a['total']:>+15,.0f}" if a else f"{'—':>15}"
    vs = f"{g['total'] - base_g:>+14,.0f}" if base_g else "—"
    fb = g.get("fallback_billed", -1)
    star = "  ← 现状" if span == 14 else ""
    star += f"   ⚠ 计费窗口内前视回退 {fb} 天" if fb > 0 else ""
    star += "   ✓ 无前视回退" if fb == 0 else ""
    print(f"  {span:<8}{g['total']:>20,.0f}{(a['total'] if a else float('nan')):>22,.0f}{ga}{vs}{star}")

print("\n" + "=" * 100)
print("② 归因（照问题 2 归档 §7.3 的结构）")
print("=" * 100)
if res[("K4", 0)]:
    k4 = res[("K4", 0)]["total"]
    print(f"  旧基线 A1 同星期几 K=4 = {k4:,.0f} 元")
    for span in (7, 14):
        a, g = res.get(("all7", span)), res.get(("group", span))
        if not a or not g: continue
        print(f"  span{span}：")
        print(f"    只换窗口（全七天 − K=4）      {a['total'] - k4:>+12,.0f} 元")
        print(f"    只换分组（分组 − 全七天）      {g['total'] - a['total']:>+12,.0f} 元")
        print(f"    合计（分组 − K=4）            {g['total'] - k4:>+12,.0f} 元")

print("\n" + "=" * 100)
print("③ 交付现值校验")
print("=" * 100)
d14 = res.get(("group", 14))
if d14:
    ok = abs(d14["total"] - 14341723) < 1.0
    print(f"  分组 span14 = {d14['total']:,.2f} 元 ⟹ 对交付现值 14,341,723 "
          f"{'✓ 一致（补丁篮子可信）' if ok else '✗ 不符'}")
    print(f"  哨兵 {d14['sentinel']:,.2f} 元（应与问题 3 的 12,406,053 同口径）")

print("\n" + "=" * 100)
print("④ 配对检验（14 天块自助，逐日总费，334 天）")
print("=" * 100)


def block_ci(d, blk=14, Bn=4000, seed=7):
    rng = np.random.default_rng(seed); n = len(d); nb = int(np.ceil(n / blk))
    mm = np.empty(Bn)
    for b in range(Bn):
        st = rng.integers(0, n, nb)
        mm[b] = d[np.concatenate([(np.arange(s_, s_ + blk) % n) for s_ in st])].mean()
    lo, hi = np.percentile(mm, [2.5, 97.5])
    return lo, hi, 2 * min((mm <= 0).mean(), (mm >= 0).mean())


REPORT = 31


def daycost(key):
    r = res.get(key)
    return np.asarray(r["daycost"], dtype=float)[REPORT:] if r else None


for a, b, nm in [(("group", 7), ("group", 14), "分组 span7 − span14（换窗口）"),
                 (("group", 7), ("K4", 0), "分组 span7 − K=4（合计）"),
                 (("all7", 7), ("K4", 0), "全七天 span7 − K=4（只换窗口）"),
                 (("group", 7), ("all7", 7), "分组 span7 − 全七天 span7（只换分组）")]:
    da, db = daycost(a), daycost(b)
    if da is None or db is None:
        print(f"  {nm:<34} 缺臂，跳过"); continue
    d = da - db
    lo, hi, p = block_ci(d); so = np.sort(d)
    print(f"  {nm:<34} 总 {d.sum():>+12,.0f} ｜ 中位 {np.median(d):>+8,.0f} ｜ "
          f"更便宜 {int((d < 0).sum()):>3}/334 ｜ CI [{lo:+,.0f}, {hi:+,.0f}] ｜ p={p:.4f}")
    print(f"  {'':<34} 剔最省 10 天 {so[10:].sum():>+12,.0f} ｜ 剔 20 {so[20:].sum():>+12,.0f}")

shutil.rmtree(TMP, ignore_errors=True)
tmp_out = os.path.join(BASE, "结果", "_p2_scan_tmp.xlsx")
if os.path.exists(tmp_out):
    os.remove(tmp_out)
    print("  已清理临时写盘文件")
