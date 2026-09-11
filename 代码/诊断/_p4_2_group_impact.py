# -*- coding: utf-8 -*-
"""★ 问题 4-2 换基线的冲击评估：把低需求日分组移植进 problem4_2.py 会改多少？

`problem4_2.py` 与 `problem4_3.py` 结构不同 —— 它是**两阶段随机规划**，
情景集就是 `peers`（第 138 行，同星期几 K=4），不是 p4_3 的 `L_base`。
本文件也没有分组辅助函数、没有 `if __name__ == "__main__"` 守卫（模块级直跑），
所以只能做**源码级补丁**：把 `peers` 那行换成按分组的版本。

⚠ 补丁副本写到系统临时目录、并把 `BASE` 钉成绝对路径
（原式 `dirname(dirname(__file__))` 在别处会解析错），**不落进仓库**。

★ 一个跨问口径问题：`problem2.py` 定稿是 `{分组, span 14}`，`problem3_v3.py` 定稿是
`{分组, span 7}`。两问的回看窗口**不一致**，而 P2 从未扫过 span。故本脚本三臂全测：
基线 K=4 / 分组 span14（配 P2）/ 分组 span7（配 P3）。
"""
import os, sys, json, shutil, tempfile, subprocess
import numpy as np
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC = os.path.join(BASE, "代码", "problem4_2.py")

OLD_PEERS = ("peers = [[d - 7 * k for k in range(1, K_PEERS + 1) if d - 7 * k >= 0] "
             "for d in range(NDAYS)]")
OLD_BASE = "BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))"

NEW_PEERS = '''# ── [诊断补丁] 低需求日分组情景集（口径复刻 problem2.py / problem3_v3.py）──
_P42_SPAN = int(os.environ.get("P42_GSPAN", "0"))
_P42_TRAIN = int(os.environ.get("P42_TRAIN", str(REPORT)))


def _low_demand_dows(train_days):
    """按日均净负荷把七天分成【低需求日】与【其余】两组。只喂暖机期，无前视。"""
    _nl = (load - pv).sum(axis=1)
    _dw = np.array([d % 7 for d in range(NDAYS)])
    _mm = [_nl[train_days][_dw[train_days] == k].mean() for k in range(7)]
    _o = np.argsort(_mm)
    return (int(_o[0]), int(_o[1])), _mm


_GDOWS, _DOWM = _low_demand_dows(np.arange(0, _P42_TRAIN))
if _P42_SPAN > 0:
    _gm = np.array([(d % 7) in _GDOWS for d in range(NDAYS)])
    peers = [[t for t in range(max(0, d - _P42_SPAN), d) if _gm[t] == _gm[d]]
             for d in range(NDAYS)]
    print(f"[分组臂] span={_P42_SPAN}  低需求日 d%7={_GDOWS}  "
          f"（日均为其均值的 {min(_DOWM) / (sum(_DOWM) / 7):.2f} × 七天均值）")
else:
    peers = [[d - 7 * k for k in range(1, K_PEERS + 1) if d - 7 * k >= 0]
             for d in range(NDAYS)]
    print(f"[基线臂] 同星期几 K={K_PEERS}（回看 {K_PEERS} 周）")
'''

TAIL = '''

# ── [诊断补丁] 结果回传 ──────────────────────────────────────────────
import json as _json
print("JSONP42 " + _json.dumps(dict(
    total=float(r1[0]), plan=float(r1[1]), emerg=float(r1[2]), kwh_em=float(r1[3]),
    sentinel=float(sent[0]), best_gamma=float(best[1]),
    kwh_g=(float(g1.sum()) * DT), kwh_c=float(c_exec.sum() * DT),
    kwh_d=float(d_exec.sum() * DT),
    soc_min=float(soc_exec.min()), soc_max=float(soc_exec.max()),
    span=int(os.environ.get("P42_GSPAN", "0")), npeers=float(np.mean([len(p) for p in peers])),
)))
'''

src = open(SRC, encoding="utf-8").read()
assert OLD_PEERS in src, "找不到 peers 定义行 —— problem4_2.py 结构变了"
assert OLD_BASE in src, "找不到 BASE 定义行 —— problem4_2.py 结构变了"
patched = src.replace(OLD_BASE, f'BASE = r"{BASE}"').replace(OLD_PEERS, NEW_PEERS) + TAIL

TMP = tempfile.mkdtemp(prefix="p42grp_")
PATCHED = os.path.join(TMP, "problem4_2_patched.py")
open(PATCHED, "w", encoding="utf-8").write(patched)
print(f"补丁副本：{PATCHED}\n")


def run(span):
    e = os.environ.copy()
    e.update({"P4_NOWRITE": "1", "GAMMAS": "1.0", "P42_GSPAN": str(span)})
    p = subprocess.run([sys.executable, PATCHED], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", env=e, cwd=BASE)
    for ln in p.stdout.splitlines():
        if ln.startswith("JSONP42 "):
            return json.loads(ln[8:]), p.stdout
    return None, p.stdout + "\n" + p.stderr


res = {}
for span, nm in [(0, "基线 K=4 同星期几"), (14, "分组 span14（配 problem2.py）"),
                 (7, "分组 span7（配 problem3_v3.py）")]:
    r, out = run(span)
    if r is None:
        print(f"✗ {nm} 失败\n{out[-1200:]}"); continue
    res[span] = r
    print(f"  {nm:<30} 总 {r['total']:>13,.0f} 元 ｜ 计划 {r['plan']:>13,.0f} ｜ "
          f"紧急 {r['emerg']:>11,.0f}（{r['kwh_em']:>8,.0f} kWh）｜ 平均情景数 {r['npeers']:.2f}",
          flush=True)

if res:
    print("\n" + "=" * 104)
    print("问题 4-2（γ=1 可交付计划）")
    print("=" * 104)
    print(f"  {'臂':<30}{'总费(元)':>15}{'计划费':>15}{'紧急费':>14}{'紧急kWh':>13}{'情景数':>9}")
    for span, nm in [(0, "基线 K=4 同星期几"), (14, "分组 span14（配 P2）"),
                     (7, "分组 span7（配 P3）")]:
        if span not in res: continue
        r = res[span]
        print(f"  {nm:<30}{r['total']:>15,.0f}{r['plan']:>15,.0f}{r['emerg']:>14,.0f}"
              f"{r['kwh_em']:>13,.0f}{r['npeers']:>9.2f}")
    if 0 in res:
        for span in (14, 7):
            if span in res:
                d = res[span]["total"] - res[0]["total"]
                print(f"\n  分组 span{span} − 基线 = {d:>+12,.0f} 元 "
                      f"（{d / res[0]['total'] * 100:+.2f}%）")
    print(f"\n  哨兵（通用下界）：{res[0]['sentinel']:,.2f} 元 ｜ "
          f"交付现值 16,050,427 元 ⟹ 基线臂复现校验 "
          f"{'✓ 一致' if abs(res[0]['total'] - 16050427) < 1 else '✗ 不符'}")
    print(f"  年末 SOC 区间：基线 [{res[0]['soc_min']:,.0f}, {res[0]['soc_max']:,.0f}]")
    for span in (14, 7):
        if span in res:
            print(f"                 span{span} [{res[span]['soc_min']:,.0f}, "
                  f"{res[span]['soc_max']:,.0f}]")

shutil.rmtree(TMP, ignore_errors=True)
