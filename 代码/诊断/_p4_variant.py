# -*- coding: utf-8 -*-
"""问题 4 优化实验的**变体库**：只放纯函数 + `apply_spec`，**无任何模块级副作用**。

为什么单独一个文件
------------------------------------------------------------------
驱动脚本 `diag_p4_hedge.py` 要改 `sys.stdout`、要打印表格，那些是**副作用**。
若变体函数与它们同处一个模块，就**没法**被"每格一个 subprocess"的方式调用
（子进程 import 那个模块会把副作用重跑一遍 —— 在 Windows 的 spawn 下实测直接把
进程池打崩：`BrokenProcessPool`）。故变体单独成模块，驱动只管调度。

本模块的用法（由驱动生成的片段调用）：

    import _p4_env as E, _p4_variant as V
    P = E.load()
    V.apply_spec(P, {'scen': 0.0, 'tau': (0.5, 0.36, 0.40, 0.70, 0.28)})
    r = P.run(1.0)

⚠ 与交付模型的关系：**本模块不碰 `problem4_3.py`**。它只在进程内 monkeypatch，
  跑完即弃。只有**胜出**的变体才回写进求解器（届时再走正式旋钮 + 自检）。
"""
import numpy as np


# ════════════════════════════════════════════════════════════════════════
# O2：情景中心阻尼
# ════════════════════════════════════════════════════════════════════════
def scen_with(P, lam):
    """`_scenarios(d, Nt)` 的变体：中心 = F̂[d,0] + λ·(Nt − F̂[d,0])。

    λ=1 → 逐字节等价于交付实现（`Nt + 形变`）。
    λ=0 → 中心退化为点预报，`Nt` 再不出现 ⇒ **τ 从模型里消失**，
          缓冲全部由追索 LP 自己承担（"只抬一次"的端点）。
    """
    Fh = P.F_hat[:, 0, :]

    def _sc(d, Nt):
        pidx = P.LB_IDX[d]
        if not pidx:
            return Nt[None, :]
        base = P.actual_net[pidx]
        C = Fh[d] + lam * (Nt - Fh[d])
        return C[None, :] + (base - base.mean(axis=0))
    return _sc


def scen_shift(P, shift):
    """`_scenarios` 变体：中心 = F̂[d,0] + shift（**直接扫描的平移量**，与 τ 无关）。

    用来把 h 从"残差分位数"这一个非线性方向里解放出来 —— 见优化文档 §3/O2。
    shift 是 (4,) 逐块平移，或标量。
    """
    Fh = P.F_hat[:, 0, :]
    sh = np.broadcast_to(np.asarray(shift, float), (4,))
    BL = P.BLOCKS

    def _sc(d, Nt):
        pidx = P.LB_IDX[d]
        if not pidx:
            return Nt[None, :]
        base = P.actual_net[pidx]
        C = Fh[d].copy()
        for e in range(4):
            a, b = BL[e]
            C[a:b] = C[a:b] + sh[e]
        return C[None, :] + (base - base.mean(axis=0))
    return _sc


# ════════════════════════════════════════════════════════════════════════
# O3：预报器变体
# ════════════════════════════════════════════════════════════════════════
def rebuild_fc(P, mode):
    """重建 `(LB_IDX, L_base, F_hat)`。mode：

      "deliv"  交付口径（低需求日分组 + GRP_SPAN=7）
      "spanN"  同口径、回看窗口改 N 天
      "all"    全历史池化（严格 < d），不用分组
      "dow"    同星期几、全历史（严格 < d）
      "pool"   分组只定**日水平**，逐槽形状用全历史  ⇒ 样本量 ~2 → ~30
      "levK"   交付口径 + **昨日实现水位比**前移（K = 收缩系数，见 `_level_carry`）
    """
    N = P.NDAYS
    dow = np.array([d % 7 for d in range(N)])
    P.GRP_SPAN = int(mode[4:]) if mode.startswith("span") else 7
    base_mode = "deliv" if mode.startswith("lev") else mode
    if base_mode == "deliv":
        idx = [P._grp_idx(d) for d in range(N)]
    elif base_mode == "all":
        idx = [list(range(d)) for d in range(N)]
    elif base_mode == "dow":
        idx = [[t for t in range(d) if dow[t] == dow[d]] for d in range(N)]
    elif base_mode == "pool":
        idx = [P._grp_idx(d) for d in range(N)]
    else:
        raise ValueError(mode)

    P.LB_IDX = idx
    Lb = np.zeros_like(P.load)
    if base_mode == "pool":
        # 形状＝全历史逐槽均值（样本多、稳），水平＝同组同伴日的**日总量比**缩放。
        # 严格因果：只用 < d 的历史。
        for d in range(N):
            hist = P.load[:d] if d > 0 else P.load[:1]
            shape = hist.mean(axis=0)
            if idx[d]:
                lvl = P.load[idx[d]].sum(axis=1).mean() / max(shape.sum(), 1e-9)
            else:
                lvl = 1.0
            Lb[d] = shape * lvl
    else:
        if mode.startswith("lev"):
            Lb = _level_carry(P, idx, float(mode[3:]))
        else:
            for d in range(N):
                Lb[d] = P.load[idx[d]].mean(axis=0) if idx[d] else P.load.mean(axis=0)
    P.L_base = Lb
    P.F_hat = Lb[:, None, :] - P.P_hat
    return mode


def _level_carry(P, idx, kappa):
    """交付基线 × 「昨日实现水位比」的因果前移。

    动机：调整层的水平校正 `r = Σ实测负荷/Σ基准负荷`（`LEVEL=1`）**只够得到当日已发生
    的时段**，而 **0:00–6:00 块在 0:00 就要定死、之后不可调整** —— 修正对它无效。
    但"整天整体偏高/偏低"这一支是**强自相关**的（交付代码自己的注释就这么写），
    ⇒ 昨日的实现比值 `r_{d−1}` 是 0:00 就能合法拿到的信息，可以前移进点预报。

        L_base[d] ← L_base[d] · (1 + κ·(r_{d−1} − 1)),   r_{d−1} = Σload[d−1] / ΣL_base[d−1]

    κ=0 退化为交付；κ=1 完全采纳。严格因果：只用 d−1 及更早。
    """
    N = P.NDAYS
    raw = np.zeros_like(P.load)
    for d in range(N):
        raw[d] = P.load[idx[d]].mean(axis=0) if idx[d] else P.load.mean(axis=0)
    out = raw.copy()
    for d in range(1, N):
        den = raw[d - 1].sum()
        r = float(P.load[d - 1].sum() / den) if den > 1e-6 else 1.0
        if not np.isfinite(r) or r <= 0:
            r = 1.0
        out[d] = raw[d] * (1.0 + kappa * (r - 1.0))
    return out


def pv_blend(P, w):
    """光伏预报混合：P_hat ← (1−w)·附件3 + w·同槽历史均值（严格因果）。

    依据：附件 3 的 **0:00 档**已知比历史统计还差（问题 2 归档）。w=0 即交付。
    """
    N = P.NDAYS
    hist = np.zeros_like(P.pv)
    for d in range(N):
        hist[d] = P.pv[:d].mean(axis=0) if d > 0 else P.pv[:1].mean(axis=0)
    P.P_hat = (1.0 - w) * P.P_hat + w * hist[:, None, :]
    P.F_hat = P.L_base[:, None, :] - P.P_hat
    return w


# ════════════════════════════════════════════════════════════════════════
# O3b：残差分位池的近期窗口
# ════════════════════════════════════════════════════════════════════════
def wquantile_window(P, K):
    """把 `wquantile` 的分位样本限制在**最近 K 天**。

    交付实现给的是**全历史累积池**：`H0 = net_hist − F_hat[:len(src),0,:]`，从第 1 天
    一直累积到昨天。若预报质量随时间漂移（暖机期样本少、后期分组同伴更充分），
    池子里的老样本就不再代表当期误差分布，而分位数对尾部样本敏感。
    K=None 退化为交付。**这是一个此前从未被检验过的自由度**（`MINR=14` 只控制
    "至少几天才开始用分位"，不控制"用多久"）。

    ⚠ 同时作用于计划层与调整层（两处都走 `wquantile`）—— 口径一致，不是 bug。
    """
    orig = P.wquantile

    def f(v, w, q, axis=0):
        if K is not None and v.ndim == 2 and v.shape[0] > K:
            v = v[-K:]
            w = w[-K:] if w is not None and w.shape[0] >= K else w
        return orig(v, w, q, axis=axis)
    return f


# ════════════════════════════════════════════════════════════════════════
# O4：价格感知执行器
# ════════════════════════════════════════════════════════════════════════
def exec_planfollow(P, allow_refill=False):
    """跟随**价格感知的**日前计划放电轨迹，而不是逐槽贪心。

    交付的 `exec_causal_day` 见缺口就放（"先放电再充电"），**完全不看价格**。
    但分时电价下放电时序不是中性的：在**高价缺电槽**放电（省 5p）优于在低价缺电槽放。
    本变体用 `plan_day(…, price_day)` 解出的 d 轨迹作放电上限 —— 那条轨迹是**带价格**
    优化出来的，会主动把电量留到晚高峰。

    allow_refill=False 时计划少放就少放（把电留给后面更贵的槽）；
    True 时退回 `exec_plan` 的「补放」语义（不让负载掉线），用作对照。
    """
    cache = {}

    def _ex(d, g_day, soc):
        c = np.zeros(P.N); d_ = np.zeros(P.N); e = np.zeros(P.N)
        if d not in cache:
            pl = P.plan_day(soc, P.F_hat[d, 0, :] + 0.0, P.price_day, P.SOC0)
            cache[d] = None if pl is None else np.clip(np.asarray(pl[2], float), 0.0, P.P_MAX)
        d0 = cache[d]
        for t in range(P.N):
            deficit = max(0.0, P.load[d, t] - P.pv[d, t] - g_day[t])
            d_max = max(0.0, (soc - P.SOC_MIN) * P.ETA / P.DT)
            if d0 is None:
                d_t = min(deficit, P.P_MAX, d_max)
            else:
                d_t = min(max(d0[t], 0.0), d_max, P.P_MAX)
                if allow_refill and deficit > d_t:
                    d_t = min(deficit, d_max)
            surplus = max(0.0, P.pv[d, t] + g_day[t] + d_t - P.load[d, t])
            c_max = max(0.0, (P.SOC_MAX - soc) / (P.ETA * P.DT))
            c[t] = min(P.P_MAX, surplus, c_max)
            e[t] = max(0.0, P.load[d, t] - P.pv[d, t] - g_day[t] - d_t)
            soc += (P.ETA * c[t] - d_[t] / P.ETA) * P.DT
        return c, d_, e, soc
    return _ex


def exec_gated(P, q):
    """价格闸门贪心：只在当日公布价 ≥ 该日 q 分位时才放电，否则把电留到后面。

    q=0 退化为交付的贪心（凡有缺口就放）。用**附件1 公布剖面**定闸门 ——
    读法 B 下 0:00 拿不到当日实际价，这是执行层合法可得的全部价格信息。
    """
    def _ex(d, g_day, soc):
        c = np.zeros(P.N); d_ = np.zeros(P.N); e = np.zeros(P.N)
        thr = np.quantile(P.price_day, q) if q > 0 else -np.inf
        for t in range(P.N):
            deficit = max(0.0, P.load[d, t] - P.pv[d, t] - g_day[t])
            d_max = max(0.0, (soc - P.SOC_MIN) * P.ETA / P.DT)
            d_t = min(deficit, P.P_MAX, d_max) if P.price_day[t] >= thr else 0.0
            surplus = max(0.0, P.pv[d, t] + g_day[t] + d_t - P.load[d, t])
            c_max = max(0.0, (P.SOC_MAX - soc) / (P.ETA * P.DT))
            c[t] = min(P.P_MAX, surplus, c_max)
            e[t] = max(0.0, P.load[d, t] - P.pv[d, t] - g_day[t] - d_t)
            soc += (P.ETA * c[t] - d_[t] / P.ETA) * P.DT
        return c, d_, e, soc
    return _ex


# ════════════════════════════════════════════════════════════════════════
# 装配
# ════════════════════════════════════════════════════════════════════════
def apply_spec(P, spec):
    """按 spec 装配 monkeypatch。spec 的键：

        scen : float(λ) | ("shift", [s0,s1,s2,s3])
        fc   : 预报器 mode 字符串
        pv   : 光伏混合权重 w
        exec : "planfollow" | "refill" | ("gate", q)
        tau  : (τ₀,τ₁,τ₂,τ₃,τ'')
    """
    if "scen" in spec:
        s = spec["scen"]
        P._scenarios = scen_shift(P, s[1]) if isinstance(s, (list, tuple)) \
            else scen_with(P, float(s))
    if "fc" in spec:
        rebuild_fc(P, spec["fc"])
    if "pv" in spec:
        pv_blend(P, float(spec["pv"]))
    if "win" in spec:
        wv = spec["win"]
        P.wquantile = wquantile_window(P, None if wv in (0, "all") else int(wv))
    if "exec" in spec:
        e = spec["exec"]
        if isinstance(e, (list, tuple)):
            P.exec_causal_day = exec_gated(P, float(e[1]))
        elif e == "planfollow":
            P.exec_causal_day = exec_planfollow(P, False)
        elif e == "refill":
            P.exec_causal_day = exec_planfollow(P, True)
        else:
            raise ValueError(e)
    if "tau" in spec:
        t = spec["tau"]
        P.TAU_B = [float(x) for x in t[:4]]
        P.TAUP = float(t[4])
    return spec
