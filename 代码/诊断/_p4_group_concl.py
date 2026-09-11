# -*- coding: utf-8 -*-
"""★ 问题 4 各项**内部结论**在「基线臂 / 分组臂」下逐条重测 —— 选项(a) 的真实代价。

父进程给每个 (配置 × 两臂) 起一个子进程（`problem4_3.py` 的读法/分位/上界等
常量都在 import 时从 env 读，必须用子进程隔离）。分组臂用猴补丁替换 `L_base`/`F_hat`。

用法：python 代码/诊断/_p4_group_concl.py            # 跑全部
      python 代码/诊断/_p4_group_concl.py --worker B # 内部
"""
import os, sys, json, subprocess
import numpy as np
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
GRP = os.environ.get("_P4GRP_ARM", "")


def build_group_L(m):
    """逐字复刻 problem3_v3 的分组基线（暖机期推组 + 过去 7 天同组均值）。"""
    nl = (m.load - m.pv).sum(axis=1)
    dw = np.array([d % 7 for d in range(m.NDAYS)])
    warm = np.arange(0, m.REPORT)
    means = np.array([nl[warm][dw[warm] == k].mean() for k in range(7)])
    o = np.argsort(means)
    dows = (int(o[0]), int(o[1]))
    gm = np.array([(d % 7) in dows for d in range(m.NDAYS)])
    Lb = np.zeros_like(m.load)
    for d in range(m.NDAYS):
        lo = max(0, d - 7)
        idx = [t for t in range(lo, d) if gm[t] == gm[d]]
        Lb[d] = m.load[idx].mean(axis=0) if idx else m.load.mean(axis=0)
    return Lb


def scalarize(m, r):
    nd, N, DT = r["nd"], m.N, m.DT
    L = m.load.ravel()[:nd * N]; P = m.pv.ravel()[:nd * N]
    gh = r["g_hat"].ravel(); gf = r["g_fin"].ravel()
    c = r["c"].ravel(); d = r["d"].ravel(); e = r["e"].ravel()
    w = m.WIN[:nd * N]
    S = P + gf + d - L
    discard = float((-np.maximum(0.0, S - c))[w].sum() * DT)          # 丢弃购电 kWh
    disc_pct = discard / float((gf * DT)[w].sum()) * 100
    at_cap = float((gf[w] >= m.G_MAX - 1e-6).mean() * 100)             # 贴购电上界槽占比
    return dict(total=float(r["total"]), plan=float(r["plan"]), breach=float(r["breach"]),
                excess=float(r["excess"]), emerg=float(r["emerg"]),
                kwh_gh=float(r["kwh_gh"]), kwh_gf=float(r["kwh_gf"]),
                kwh_em=float(r["kwh_em"]), kwh_c=float(r["kwh_c"]),
                kwh_d=float(r["kwh_d"]), n_adj=int(r["n_adj"]),
                soc_end=float(r["soc_end"]), soc_min=float(r["soc_min"]),
                soc_max=float(r["soc_max"]), freq_em=float(r["freq_em"]),
                discard_kwh=discard, discard_pct=float(disc_pct),
                at_cap_pct=at_cap, sentinel=float(os.environ.get("_SENT", "nan")))


if __name__ == "__main__" and GRP:
    # ── 子进程：跑一个臂 ────────────────────────────────────────────
    sys.path.insert(0, os.path.join(BASE, "代码"))
    import problem4_3 as m
    if GRP == "G":
        Lb = build_group_L(m)
        m.L_base = Lb
        m.F_hat = Lb[:, None, :] - m.P_hat
    if os.environ.get("_P4SENT", "0") == "1":
        s = m.sentinel()
        print("JSON " + json.dumps({"sentinel_total": float(s["total"]) if s else None}))
        sys.exit(0)
    print("JSON " + json.dumps(scalarize(m, m.run(1.0))))
    sys.exit(0)


# ── 父进程：配置网格 × 两臂 ────────────────────────────────────────
CONFIGS = [
    ("定稿（读法B, WQ=0, τ=0.80/0.55, G≤5000）", {}),
    ("WQ=1 电价加权分位",            {"P4_WQ": "1"}),
    ("G=∞ + WQ=1",                   {"P4_GMAX": "inf", "P4_WQ": "1"}),
    ("读法A（计划层用实际价）",       {"P4_READING": "A"}),
    ("G=∞（放开购电上界）",          {"P4_GMAX": "inf"}),
    ("τ=0.836（理论报童位移）",      {"P4_TAU": "0.836"}),
    ("τ=0.50",                       {"P4_TAU": "0.50"}),
    ("τ'=0.337（后三块纯理论）",     {"P4_TAUP": "0.337"}),
    ("BANDS=2（去掉 18:00 档）",     {"P4_BANDS": "2"}),
    ("LEVEL=0（关水平校正）",        {"P4_LEVEL": "0"}),
    ("关调整通道 ADJ=0",             {"P4_ADJ": "0"}),
]


def run_one(arm, envx, want_sent=False):
    e = os.environ.copy()
    e.update({"_P4GRP_ARM": arm, "P4_WRITE": "0", "P4_SENT": "0",
              "P4_LAMS": "1.0", "_P4SENT": "1" if want_sent else "0"})
    e.update(envx)
    p = subprocess.run([sys.executable, os.path.abspath(__file__)],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", env=e, cwd=BASE)
    for ln in p.stdout.splitlines():
        if ln.startswith("JSON "):
            return json.loads(ln[5:])
    print(f"  ✗ 失败 arm={arm} {envx}\n{p.stdout[-600:]}\n{p.stderr[-600:]}")
    return None


print("=" * 112)
print("问题 4 全部内部结论 × 两种基线（臂B = 交付现状 K=4；臂G = 移植低需求日分组 span7）")
print("=" * 112)

print("\n【哨兵】完美预见 LP —— 只用实际 load/pv 与实际价，**与 L_base 无关，故两臂同值**")
for arm in ("B", "G"):
    s = run_one(arm, {}, want_sent=True)
    print(f"  臂{arm} 哨兵 {s['sentinel_total']:>14,.2f} 元" if s else f"  臂{arm} 失败")

res = {}
for nm, envx in CONFIGS:
    row = {}
    for arm in ("B", "G"):
        row[arm] = run_one(arm, envx)
    res[nm] = row

print("\n" + "=" * 112)
print("① 总费用（元）")
print("=" * 112)
print(f"  {'配置':<34}{'臂B 基线':>16}{'臂G 分组':>16}{'分组Δ':>14}{'分组%':>9}")
for nm, _ in CONFIGS:
    B, G = res[nm]["B"], res[nm]["G"]
    if not B or not G: continue
    if nm.startswith("定稿"):
        print(f"  {'─' * 34}{'─' * 16}{'─' * 16}{'─' * 14}{'─' * 9}")
    print(f"  {nm:<34}{B['total']:>16,.0f}{G['total']:>16,.0f}"
          f"{G['total'] - B['total']:>+14,.0f}{(G['total'] / B['total'] - 1) * 100:>8.2f}%")

print("\n" + "=" * 112)
print("② P4 的两条负结果 / 关键取舍：**结论方向会不会被分组翻掉？**")
print("=" * 112)
pairs = [
    ("WQ=1 − 定稿",        "WQ=1 电价加权分位",            "定稿（读法B, WQ=0, τ=0.80/0.55, G≤5000）"),
    ("读法A − 读法B",      "读法A（计划层用实际价）",       "定稿（读法B, WQ=0, τ=0.80/0.55, G≤5000）"),
    ("G=∞ − G≤5000",       "G=∞（放开购电上界）",          "定稿（读法B, WQ=0, τ=0.80/0.55, G≤5000）"),
    ("τ=0.836 − τ=0.80",   "τ=0.836（理论报童位移）",      "定稿（读法B, WQ=0, τ=0.80/0.55, G≤5000）"),
    ("τ=0.50 − τ=0.80",    "τ=0.50",                       "定稿（读法B, WQ=0, τ=0.80/0.55, G≤5000）"),
    ("BANDS=2 − BANDS=3",  "BANDS=2（去掉 18:00 档）",     "定稿（读法B, WQ=0, τ=0.80/0.55, G≤5000）"),
    ("LEVEL=0 − LEVEL=1",  "LEVEL=0（关水平校正）",        "定稿（读法B, WQ=0, τ=0.80/0.55, G≤5000）"),
    ("ADJ=0 − ADJ=1",      "关调整通道 ADJ=0",             "定稿（读法B, WQ=0, τ=0.80/0.55, G≤5000）"),
    ("★G=∞ 下 WQ=1−WQ=0",  "G=∞ + WQ=1",                   "G=∞（放开购电上界）"),
]
print(f"  {'对照':<22}{'臂B Δ':>15}{'臂B 方向':>10}   {'臂G Δ':>15}{'臂G 方向':>10}   {'方向':>8}")
for nm, a, b in pairs:
    ra, rb = res[a], res[b]
    if not (ra["B"] and ra["G"] and rb["B"] and rb["G"]): continue
    db = ra["B"]["total"] - rb["B"]["total"]; dg = ra["G"]["total"] - rb["G"]["total"]
    sb = "更贵" if db > 0 else "更省"; sg = "更贵" if dg > 0 else "更省"
    same = "✓ 一致" if (db > 0) == (dg > 0) else "✗ 翻转"
    print(f"  {nm:<22}{db:>+15,.0f}{sb:>10}   {dg:>+15,.0f}{sg:>10}   {same:>8}")

print("\n" + "=" * 112)
print("③ 交付表口径量：贴购电上界 / 丢弃购电 / 电量结构")
print("=" * 112)
print(f"  {'项':<26}{'臂B 基线':>18}{'臂G 分组':>18}{'Δ':>16}")
for k, nm, f in [("kwh_gh", "Σĝ (kWh)", "{:,.0f}"), ("kwh_gf", "Σg (kWh)", "{:,.0f}"),
                 ("kwh_em", "紧急 (kWh)", "{:,.0f}"), ("kwh_c", "充电 (kWh)", "{:,.0f}"),
                 ("kwh_d", "放电 (kWh)", "{:,.0f}"),
                 ("discard_kwh", "丢弃购电 (kWh)", "{:,.0f}"),
                 ("discard_pct", "丢弃占比 (%)", "{:.2f}"),
                 ("at_cap_pct", "贴购电上界占比 (%)", "{:.2f}"),
                 ("excess", "超额费 (元)", "{:,.0f}"),
                 ("emerg", "紧急费 (元)", "{:,.0f}"),
                 ("plan", "计划费 (元)", "{:,.0f}")]:
    B, G = res[CONFIGS[0][0]]["B"], res[CONFIGS[0][0]]["G"]
    print(f"  {nm:<26}{f.format(B[k]):>18}{f.format(G[k]):>18}{f.format(G[k] - B[k]):>16}")

print("\n" + "=" * 112)
print("④ 交付表口径量：对比基数（问题 2 / 问题 3 / 哨兵）")
print("=" * 112)
B0, G0 = res[CONFIGS[0][0]]["B"], res[CONFIGS[0][0]]["G"]
gm = res["G=∞（放开购电上界）"]
print(f"  问题 3 新交付 14,285,731.45 元 ⟹ 问题 4 分组臂 {G0['total']:,.2f} 元 "
      f"= ×{G0['total'] / 14285731.45:.6f}")
print(f"  问题 3 旧基线 14,712,825.34 元 ⟹ 问题 4 基线臂 {B0['total']:,.2f} 元 "
      f"= ×{B0['total'] / 14712825.34:.6f}")
print(f"  G_MAX 读法：臂B 放开 {gm['B']['total']:,.0f}（+{gm['B']['total'] - B0['total']:,.0f}）｜ "
      f"臂G 放开 {gm['G']['total']:,.0f}（+{gm['G']['total'] - G0['total']:,.0f}）")

np.save(os.path.join(BASE, "代码", "诊断", "_p3arms", "_p4grp_concl.npy"),
        np.array([res], dtype=object), allow_pickle=True)
print("\n[done]")
