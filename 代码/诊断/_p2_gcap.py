# -*- coding: utf-8 -*-
"""问题 2 §9 第 6 条（购电功率上界）需要的「越限槽数」在各情景集下的对照。

背景：`result2.xlsx` 的交付计划是否有槽超过 5000 kW，取决于情景集。
本脚本按 `P2_ARM` 跑 K=4 / 分组 span6 / 分组 span14 三种配置，各自报：
  峰值功率、>5000 kW 的槽数（计费窗口 334 天 = 48,096 槽）、有越限的天数。

⚠ 与 `_p2_span_scan.py` 一样走**源码级补丁**，副本写进临时目录，绝不碰
`结果/result2.xlsx`。
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

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

NEW_SPAN = 'GROUP_SPAN = int(os.environ.get("P2_GSPAN", 6))   # [补丁] 回看窗口'
NEW_PEERS = '''def build_peers_group(dows, span=None):
    """[补丁] P2_ARM=wd 用同星期几 K=4；否则用分组。"""
    span = GROUP_SPAN if span is None else span
    if os.environ.get("P2_ARM", "group").strip().lower() == "wd":
        return build_peers_weekday(K_PEERS)
    m = np.array([(d % 7) in dows for d in range(NDAYS)])
    return [[t for t in range(max(0, d - span), d) if m[t] == m[d]] for d in range(NDAYS)]'''

TAIL = '''

# ── [补丁] 越限槽数统计（不改任何交付文件）──────────────────────────────
import json as _json
_G = g1.reshape(NDAYS, N)[REPORT:]
print("JSONP2 " + _json.dumps(dict(
    total=float(r1[0]),
    kwh=float(g1.reshape(NDAYS, N)[REPORT:].sum() * DT),
    peak_kw=float(_G.max()),
    over=int((_G > P_MAX).sum()),
    nslots=int(_G.size),
    days_over=int(((_G > P_MAX).sum(axis=1) > 0).sum()),
)))
'''

src = open(SRC, encoding="utf-8").read()
for tag, old in [("GROUP_SPAN", OLD_SPAN), ("build_peers_group", OLD_PEERS),
                 ("BASE", OLD_BASE), ("out_path", OLD_OUT)]:
    assert old in src, f"找不到 {tag} —— problem2.py 结构变了。"

patched = (src.replace(OLD_BASE, f'BASE = r"{BASE}"')
              .replace(OLD_SPAN, NEW_SPAN)
              .replace(OLD_PEERS, NEW_PEERS)
              .replace(OLD_OUT, 'out_path = os.path.join(BASE, "结果", "_p2_scan_tmp.xlsx")')
           + TAIL)

TMP = tempfile.mkdtemp(prefix="p2gcap_")
PATCHED = os.path.join(TMP, "problem2_patched.py")
open(PATCHED, "w", encoding="utf-8").write(patched)


def run(arm, span):
    e = os.environ.copy()
    e.update({"GAMMAS": "1.0", "P2_ARM": arm, "P2_GSPAN": str(span)})
    p = subprocess.run([sys.executable, PATCHED], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", env=e, cwd=BASE)
    for ln in p.stdout.splitlines():
        if ln.startswith("JSONP2 "):
            return json.loads(ln[7:])
    print(f"  ✗ {arm} span={span} 失败\n{p.stdout[-700:]}\n{p.stderr[-700:]}")
    return None


print("=" * 96)
print("问题 2：交付计划越限槽数（购电功率上界 5000 kW）在各情景集下的对照")
print("计费窗口 2025.2.1–12.31，334 天 = 48,096 个 10 分钟槽")
print("=" * 96)
for arm, span, name in [("wd", 0, "A1 同星期几 K=4（换分组之前的基线）"),
                        ("group", 6, "★ A3 分组 span6（本版交付）"),
                        ("group", 14, "　 分组 span14（旧交付）")]:
    r = run(arm, span)
    if not r:
        continue
    print(f"  {name:<34} 总费 {r['total']:>13,.0f} ｜ Σĝ {r['kwh']:>14,.0f} kWh ｜ "
          f"峰值 {r['peak_kw']:>9,.1f} kW ｜ 越限 {r['over']:>6,} / {r['nslots']:,} 槽 ｜ "
          f"有越限 {r['days_over']:>3} / 334 天", flush=True)

shutil.rmtree(TMP, ignore_errors=True)
tmp_out = os.path.join(BASE, "结果", "_p2_scan_tmp.xlsx")
if os.path.exists(tmp_out):
    os.remove(tmp_out)
    print("\n  已清理临时写盘文件")
