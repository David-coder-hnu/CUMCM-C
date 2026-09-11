# -*- coding: utf-8 -*-
"""问题 2 定稿 span=6 之后的**归因与显著性**重测（补齐归档 §7.2–§7.4）。

`_p2_span_scan.py` 做了窗口扫描（14 臂），但归因分解与配对检验是在 **span14** 上做的。
定稿改成 span6 之后，A3 换了对象，所以 A3−A1 / A3−A2 必须在新 span 下重测。

臂的定义（全部走同一个 γ=1 可交付 LP + `execute_soc_causal`）：
  K4            前 4 个同星期几日（旧基线 A1）
  K2            前 2 个同星期几日（A2，只换窗口的配平对象）
  group(s)      过去 s 天内与当日**同组**的历史日（交付口径）
  all7(s)       过去 s 天内**全部**历史日（= 只缩窗口、不分组）
  weekend(s)    过去 s 天内 {周六,周日} 的历史日（A4，日历直觉对照）

⚠ 与 `_p2_span_scan.py` 一样走**源码级补丁**：副本写进临时目录，绝不碰
`结果/result2.xlsx`。
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

import numpy as np

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC = os.path.join(BASE, "代码", "problem2.py")
REPORT = 31

OLD_SPAN = "GROUP_SPAN = 6                  # 分组情景集的回看窗口（天）"
OLD_PEERS = '''def build_peers_group(dows, span=GROUP_SPAN):
    """同组情景集：回看 span 天内、与当日同组的历史日。"""
    m = np.array([(d % 7) in dows for d in range(NDAYS)])
    return [[t for t in range(max(0, d - span), d) if m[t] == m[d]] for d in range(NDAYS)]'''
OLD_BASE = "BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))"
OLD_OUT = 'out_path = os.path.join(BASE, "结果", "result2.xlsx")'

NEW_SPAN = 'GROUP_SPAN = int(os.environ.get("P2_GSPAN", 6))   # [扫描旋钮] 回看窗口（天）'
NEW_PEERS = '''def build_peers_group(dows, span=None):
    """[扫描补丁] P2_ARM 选臂：group / all7 / weekend / wd。"""
    span = GROUP_SPAN if span is None else span
    arm = os.environ.get("P2_ARM", "group").strip().lower()
    if arm == "wd":
        return build_peers_weekday(int(os.environ.get("P2_KPEERS", K_PEERS)))
    if arm == "all7":
        m = np.ones(NDAYS, dtype=bool)
    elif arm == "weekend":                 # 2025-01-01 = 周三 ⟹ 周六=3, 周日=4
        m = np.array([(d % 7) in (3, 4) for d in range(NDAYS)])
    else:
        m = np.array([(d % 7) in dows for d in range(NDAYS)])
    return [[t for t in range(max(0, d - span), d) if m[t] == m[d]] for d in range(NDAYS)]'''

TAIL = '''

# ── [扫描补丁] 结果回传 ──────────────────────────────────────────────
import json as _json
print("JSONP2 " + _json.dumps(dict(
    total=float(r1[0]), plan=float(r1[1]), emerg=float(r1[2]), kwh_em=float(r1[3]),
    npeers=float(np.mean([len(p) for p in peers])),
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

TMP = tempfile.mkdtemp(prefix="p2attr_")
PATCHED = os.path.join(TMP, "problem2_patched.py")
open(PATCHED, "w", encoding="utf-8").write(patched)


def run(arm, span, kpeers=None):
    e = os.environ.copy()
    e.update({"GAMMAS": "1.0", "P2_ARM": arm, "P2_GSPAN": str(span)})
    if kpeers is not None:
        e["P2_KPEERS"] = str(kpeers)
    p = subprocess.run([sys.executable, PATCHED], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", env=e, cwd=BASE)
    for ln in p.stdout.splitlines():
        if ln.startswith("JSONP2 "):
            return json.loads(ln[7:])
    print(f"  ✗ {arm} span={span} 失败\n{p.stdout[-800:]}\n{p.stderr[-800:]}")
    return None


ARMS = [("wd", 0, None, "A1 同星期几 K=4（旧基线）"),
        ("wd", 0, 2, "A2 同星期几 K=2"),
        ("group", 6, None, "★ A3 低需求日分组 span6（本版交付）"),
        ("group", 7, None, "　 低需求日分组 span7"),
        ("group", 14, None, "　 低需求日分组 span14（旧交付）"),
        ("all7", 6, None, "　 全七天一组 span6"),
        ("all7", 7, None, "　 全七天一组 span7"),
        ("all7", 14, None, "　 全七天一组 span14"),
        ("weekend", 6, None, "A4 日历周末 {六,日} span6"),
        ("weekend", 14, None, "　 日历周末 {六,日} span14")]

print("=" * 104)
print("问题 2：span6 定稿后的归因与显著性（γ=1 可交付 + 因果执行，334 个计费日）")
print("=" * 104)
res = {}
for arm, span, kp, name in ARMS:
    r = run(arm, span, kp)
    res[(arm, kp or 0, span)] = r
    print(f"  {name:<34}" + (f"{r['total']:>15,.0f} 元  "
          f"(计划 {r['plan']:>12,.0f} ｜ 紧急 {r['emerg']:>10,.0f} / {r['kwh_em']:>9,.0f} kWh ｜ "
          f"情景数 {r['npeers']:.2f} ｜ 前视回退 {r['fallback_billed']} 天)"
          if r else "失败"), flush=True)

print("\n" + "=" * 104)
print("① 交付现值校验")
print("=" * 104)
d6 = res.get(("group", 0, 6))
if d6:
    print(f"  分组 span6 = {d6['total']:,.2f} 元 ⟹ 对交付现值 13,846,553.27 "
          f"{'✓ 一致' if abs(d6['total'] - 13846553.27) < 1.0 else '✗ 不符'}")
    print(f"  计费窗口内前视回退天数 = {d6['fallback_billed']}"
          f"（span5 为 47 天 ⟹ span6 是**第一个干净窗口**）")


def block_ci(d, blk=14, Bn=4000, seed=7):
    rng = np.random.default_rng(seed)
    n = len(d)
    nb = int(np.ceil(n / blk))
    mm = np.empty(Bn)
    for b in range(Bn):
        st = rng.integers(0, n, nb)
        mm[b] = d[np.concatenate([(np.arange(s_, s_ + blk) % n) for s_ in st])].mean()
    lo, hi = np.percentile(mm, [2.5, 97.5])
    return lo, hi, 2 * min((mm <= 0).mean(), (mm >= 0).mean())


def dc(key):
    r = res.get(key)
    return np.asarray(r["daycost"], dtype=float)[REPORT:] if r else None


print("\n" + "=" * 104)
print("② 归因分解与配对检验（14 天块自助，逐日总费，334 天，4000 次重抽）")
print("=" * 104)
PAIRS = [(("group", 0, 6), ("wd", 0, 0), "A3−A1　分组+缩短窗口（合计）"),
         (("group", 0, 6), ("wd", 2, 0), "A3−A2　只换分组（配平窗口=2周）"),
         (("wd", 2, 0), ("wd", 0, 0), "A2−A1　只换窗口"),
         (("group", 0, 6), ("all7", 0, 6), "分组 span6 − 全七天 span6（只换分组）"),
         (("all7", 0, 6), ("wd", 0, 0), "全七天 span6 − K=4（只换窗口）"),
         (("weekend", 0, 6), ("wd", 0, 0), "A4−A1　日历周末 span6 − K=4"),
         (("group", 0, 6), ("weekend", 0, 6), "A3−A4　分组 − 日历周末"),
         (("group", 0, 6), ("group", 0, 14), "span6 − span14（换交付口径）")]
for ka, kb, nm in PAIRS:
    da, db = dc(ka), dc(kb)
    if da is None or db is None:
        print(f"  {nm:<36} 缺臂，跳过")
        continue
    d = da - db
    lo, hi, p = block_ci(d)
    so = np.sort(d)
    print(f"  {nm:<36} 总 {d.sum():>+12,.0f} ｜ 中位 {np.median(d):>+8,.0f} ｜ "
          f"更便宜 {int((d < 0).sum()):>3}/334 ｜ CI [{lo:+,.0f}, {hi:+,.0f}] ｜ p={p:.4f}")
    print(f"  {'':<36} 剔最省 10 天 {so[10:].sum():>+12,.0f} ｜ 剔 20 {so[20:].sum():>+12,.0f}")

shutil.rmtree(TMP, ignore_errors=True)
tmp_out = os.path.join(BASE, "结果", "_p2_scan_tmp.xlsx")
if os.path.exists(tmp_out):
    os.remove(tmp_out)
    print("\n  已清理临时写盘文件")
