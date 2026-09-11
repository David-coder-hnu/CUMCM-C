# -*- coding: utf-8 -*-
"""★ 问题 4 换基线的冲击评估：把问题 3 的低需求日分组移植进来，问题 4 会变多少？

背景：问题 3 于 2026-09-12 把 `L_base` 从「前 4 个同星期几」换成「过去 7 天内同组日」
（组={周五,周六}，由暖机期推出）。`problem4_3.py` 是 problem3_v3 的**冻结副本**，
`K_PEERS=4` 硬编码、没有任何分组旋钮 ⟹ 它输出的仍是旧基线轨迹，
问题 4 归档 §6.1 的头条交叉验证（「result4-3.xlsx 与 result3.xlsx 逐元素相同」）因此失效。

本脚本回答：**移植之后，问题 4 的全部报出量各自变多少？交叉验证能否恢复？**

做法：**不修改交付文件**。`import problem4_3` 只跑模块级的数据加载与常量计算
（`L_base`/`F_hat` 在 382–388 行算出），求解在 `if __name__ == "__main__"` 里。
于是可以：
  ① 直接调用 m.run(lam) 得基线臂；
  ② 猴补丁替换 `m.L_base` / `m.F_hat` 后再次调用得分组臂。
`run()` 在调用时才解析这两个全局名（715–760 行），故替换有效。

⚠ 残差那一路**不用动**：problem4_3 的 `net_hist` 是逐日累积的**全历史**池
（792 行），本来就等价于问题 3 定稿的 `P3_HSRC=all`。要移植的只有 `L_base` 一块。
"""
import os, sys, time
import numpy as np
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(BASE, "代码"))
os.environ["P4_WRITE"] = "0"          # 绝不动 结果/result4-3.xlsx
os.environ["P4_SENT"] = "0"
os.environ.setdefault("P4_LAMS", "1.0")
# 复现「旧口径」的数必须让分组旋钮缺省 —— 但 problem4_3.py 根本没有这个旋钮，
# 所以基线臂就是不加任何补丁的原样。

t0 = time.time()
import problem4_3 as m
print(f"已加载 {os.path.basename(m.__file__)}（模块级数据加载 {time.time() - t0:.1f}s）")
print(f"  基线口径 K_PEERS = {m.K_PEERS}（无分组旋钮）")
print(f"  L_base 源：前 {m.K_PEERS} 个同星期几日")


# ════════════════════════════════════════════════════════════════════════
# 分组基线：逐字复刻 problem3_v3.py 的 `_low_demand_dows` + `_grp_idx`
# ════════════════════════════════════════════════════════════════════════
def low_demand_dows():
    """按日均净负荷把七天分成【低需求日】与【其余】两组。只喂暖机期，无前视。"""
    nl = (m.load - m.pv).sum(axis=1)
    dw = np.array([d % 7 for d in range(m.NDAYS)])
    warm = np.arange(0, m.REPORT)
    means = np.array([nl[warm][dw[warm] == k].mean() for k in range(7)])
    o = np.argsort(means)
    return tuple(sorted((int(o[0]), int(o[1])))), means


GRP_DOWS, DOW_MEANS = low_demand_dows()
GRP_SPAN = 7
print(f"\n暖机期（前 {m.REPORT} 天）日均净负荷，按 d%7 分组：")
for k in range(7):
    tag = "  ← 低需求组" if k in GRP_DOWS else ""
    print(f"  d%7={k}  {DOW_MEANS[k]:>10,.0f} kWh/日{tag}")
print(f"  ⟹ 分组 GRP_DOWS = {GRP_DOWS}")


def grouped_L_base(span=GRP_SPAN):
    _gm = np.array([(d % 7) in GRP_DOWS for d in range(m.NDAYS)])
    Lb = np.zeros_like(m.load)
    for d in range(m.NDAYS):
        lo = max(0, d - span) if span > 0 else 0
        idx = [t for t in range(lo, d) if _gm[t] == _gm[d]]
        Lb[d] = m.load[idx].mean(axis=0) if idx else m.load.mean(axis=0)
    return Lb


L_base_GRP = grouped_L_base()
print(f"  L_base 差异：max|分组 − 同星期几K=4| = {np.abs(L_base_GRP - m.L_base).max():,.2f} kW  "
      f"（均值 {np.abs(L_base_GRP - m.L_base).mean():,.2f} kW）")


# ════════════════════════════════════════════════════════════════════════
# 两臂
# ════════════════════════════════════════════════════════════════════════
_L0, _F0 = m.L_base, m.F_hat

print("\n" + "=" * 108)
print("【臂 B】基线（K=4 同星期几，即当前交付 problem4_3.py 的口径）")
print("=" * 108)
tb = time.time()
rB = m.run(1.0)
print(f"  总 {rB['total']:>13,.0f} 元  [{time.time() - tb:.0f}s]")

print("\n" + "=" * 108)
print("【臂 G】低需求日分组 span7（问题 3 的新定稿口径）")
print("=" * 108)
m.L_base = L_base_GRP
m.F_hat = L_base_GRP[:, None, :] - m.P_hat
tg = time.time()
rG = m.run(1.0)
print(f"  总 {rG['total']:>13,.0f} 元  [{time.time() - tg:.0f}s]")
m.L_base, m.F_hat = _L0, _F0      # 还原


# ════════════════════════════════════════════════════════════════════════
# 逐日报表 + 配对自助
# ════════════════════════════════════════════════════════════════════════
nd, N, DT = rB["nd"], m.N, m.DT
pr = m.price_real[:nd * N]
W2 = m.WIN[:nd * N].reshape(nd, N)
RD = np.arange(m.WIN0, m.NDAYS_RUN)
LAB = ["计划 p·ĝ", "违约 0.5p", "超额 1.5p", "紧急 5p"]


def daily(r):
    gh = r["g_hat"].ravel(); gf = r["g_fin"].ravel(); e = r["e"].ravel()
    comp = np.stack([pr * gh,
                     0.5 * pr * np.maximum(gh - gf, 0),
                     1.5 * pr * np.maximum(gf - gh, 0),
                     5.0 * pr * e], axis=1) * DT
    return (comp.reshape(nd, N, 4) * W2[:, :, None]).sum(axis=1)   # (nd,4)


DB, DG = daily(rB), daily(rG)


def block_ci(d, blk=14, Bn=4000, seed=7):
    rng = np.random.default_rng(seed); n = len(d); nb = int(np.ceil(n / blk)); mm = np.empty(Bn)
    for b in range(Bn):
        st = rng.integers(0, n, nb)
        mm[b] = d[np.concatenate([(np.arange(s, s + blk) % n) for s in st])].mean()
    lo, hi = np.percentile(mm, [2.5, 97.5])
    return lo, hi, 2 * min((mm <= 0).mean(), (mm >= 0).mean())


print("\n" + "=" * 108)
print("① 报出量逐项对照（计费窗口 334 天）")
print("=" * 108)
rows = [
    ("总费用 (元)", rB["total"], rG["total"]),
    ("　计划 p·ĝ", rB["plan"], rG["plan"]),
    ("　违约费", rB["breach"], rG["breach"]),
    ("　超额费", rB["excess"], rG["excess"]),
    ("　紧急费", rB["emerg"], rG["emerg"]),
    ("Σĝ (kWh)", rB["kwh_gh"], rG["kwh_gh"]),
    ("Σg 实际购电 (kWh)", rB["kwh_gf"], rG["kwh_gf"]),
    ("紧急购电 (kWh)", rB["kwh_em"], rG["kwh_em"]),
    ("充电 (kWh)", rB["kwh_c"], rG["kwh_c"]),
    ("放电 (kWh)", rB["kwh_d"], rG["kwh_d"]),
    ("年末 SOC (kWh)", rB["soc_end"], rG["soc_end"]),
    ("SOC 轨迹下界", rB["soc_min"], rG["soc_min"]),
    ("SOC 轨迹上界", rB["soc_max"], rG["soc_max"]),
    ("紧急发生频率", rB["freq_em"], rG["freq_em"]),
    ("上调天数 n_adj", rB["n_adj"], rG["n_adj"]),
]
print(f"  {'项':<22}{'臂B 基线':>16}{'臂G 分组':>16}{'Δ':>16}{'相对':>10}")
for nm, a, b in rows:
    rel = f"{(b - a) / a * 100:+.2f}%" if abs(a) > 1e-9 else "—"
    print(f"  {nm:<22}{a:>16,.2f}{b:>16,.2f}{b - a:>+16,.2f}{rel:>10}")

print("\n  分项费分解（元）")
for i, nm in enumerate(LAB):
    a, b = DB[RD, i].sum(), DG[RD, i].sum()
    print(f"    {nm:<12}{a:>16,.2f}{b:>16,.2f}{b - a:>+16,.2f}")

print("\n" + "=" * 108)
print("② 配对检验：分组 − 基线（逐日总费，334 天）")
print("=" * 108)
d = DG[RD].sum(axis=1) - DB[RD].sum(axis=1)
lo, hi, p = block_ci(d); s = np.sort(d)
print(f"  总 Δ {d.sum():>+12,.0f} 元 ｜ 日均 {d.mean():>+9,.0f} ｜ 中位 {np.median(d):>+9,.0f} "
      f"｜ 更便宜 {int((d < 0).sum()):>3}/334 ｜ CI [{lo:+,.0f}, {hi:+,.0f}] ｜ p={p:.4f}")
print(f"  剔最省 10 天 {s[10:].sum():>+12,.0f} ｜ 剔 20 {s[20:].sum():>+12,.0f} "
      f"｜ 剔 50 {s[50:].sum():>+12,.0f}")


# ════════════════════════════════════════════════════════════════════════
# ③ 交叉验证恢复检查：与问题 3 新交付 result3.xlsx 逐元素比
# ════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 108)
print("③ 核心问题：移植后 result4-3 的策略表能否与新的 result3.xlsx 逐元素相同？")
print("=" * 108)
import pandas as pd
p3 = os.path.join(BASE, "结果", "result3.xlsx")
if not os.path.exists(p3):
    print("  ⚠ 找不到 result3.xlsx，跳过")
else:
    # ⚠ 首行是槽位标签表头，交给 pandas 消费（header=0），与 summarize_p3_blocks.py 同法。
    ws_p3 = pd.read_excel(p3, sheet_name="计划购电量")
    ws_a3 = pd.read_excel(p3, sheet_name="调整购电量")
    A3 = np.roll(ws_p3.iloc[:nd, 1:1 + N].to_numpy(float), 1, axis=1)
    G3 = np.roll(ws_a3.iloc[:nd, 1:1 + N].to_numpy(float), 1, axis=1)

    for tag, r in (("臂B 基线(K=4)", rB), ("臂G 分组(span7)", rG)):
        gh = (r["g_hat"] * DT).reshape(nd, N)
        gf = (r["g_fin"] * DT).reshape(nd, N)
        # result3.xlsx 只含计费窗口 334 行 ⟹ 与 run() 数组的第 WIN0 天起对位。
        dp = np.abs(gh[m.WIN0:] - A3); da = np.abs(gf[m.WIN0:] - G3)
        neq_p = int((dp > 5e-5).sum()); neq_a = int((da > 5e-5).sum())
        print(f"  {tag:<18} 计划购电量 max|差| {dp.max():>10,.4f}  相异格 {neq_p:>6} ｜ "
              f"调整购电量 max|差| {da.max():>10,.4f}  相异格 {neq_a:>6}")
    print("\n  ⇒ 相异格全 0 才算交叉验证恢复。")
    print("     已知基线臂的偏差就是 2026-09-12 发现的那笔（max|差| = 20,073.25）。")

np.savez(os.path.join(BASE, "代码", "诊断", "_p3arms", "_p4grp.npz"),
         totalB=rB["total"], totalG=rG["total"],
         dailyB=DB, dailyG=DG, RD=RD,
         Lbase_diff=(L_base_GRP - _L0))
print(f"\n[总计时] {(time.time() - t0) / 60:.1f} min")
