# -*- coding: utf-8 -*-
"""诊断三：信息价值阶梯 —— 把 12.23M(完美预见) 与 15.68M(问题3现状) 之间的
   3.45M 差额拆开：是"调整通道不值钱"，还是"日内预报太糙"？

全部使用同一套成本口径 p·g + 0.5p|g−ĝ| + 5p·e，同一套 SOC 锚定，差别只在
「0:00 计划的净负荷输入」和「日内调整看到的信息」这两个开关：
  A  完美计划 + 完美日内  = 完美预见（下界，应 ≈ 12.23M）
  B  现实计划 + 完美日内  = 日内预报无误差，只剩 0:00 计划误差
  C  完美计划 + 现实日内  = 0:00 计划无误差，只剩日内预报误差
  D  现实计划 + 现实日内  = 现行 problem3.py myopic（确定性等价）
"""
import numpy as np
import importlib.util
from scipy.optimize import linprog
from scipy import sparse

spec = importlib.util.spec_from_file_location('p3s', '代码/p3_stoch.py')
M = importlib.util.module_from_spec(spec); spec.loader.exec_module(M)

DT, ETA, N, NDAYS, REPORT = M.DT, M.ETA, M.N, M.NDAYS, M.REPORT
SOC_MIN, SOC_MAX, SOC0, P_MAX = M.SOC_MIN, M.SOC_MAX, M.SOC0, M.P_MAX
load, pv, price_day, L_base, P_hat = M.load, M.pv, M.price_day, M.L_base, M.P_hat
PVFC, RESID, STAGES = M.PVFC, M.RESID, M.STAGES
win = np.zeros(NDAYS, bool); win[REPORT:] = True


def solve_stage_ce(si, soc_start, soc_end, P_rem, L_rem, ghat_rem, price_rem):
    """现行 problem3.py 的确定性等价调整 LP（无紧急购电变量）。"""
    n = N - si
    G0, C0, D0, SL, S = 0, n, 2 * n, 3 * n, 4 * n
    AP, AN = 5 * n + 1, 6 * n + 1
    nv = 7 * n + 1
    c = np.zeros(nv)
    c[G0:G0 + n] = price_rem * DT
    c[AP:AP + n] = 0.5 * price_rem * DT
    c[AN:AN + n] = 0.5 * price_rem * DT
    i = np.arange(n)
    r1 = np.concatenate([i] * 4); c1 = np.concatenate([G0 + i, D0 + i, C0 + i, SL + i])
    d1 = np.concatenate([np.ones(n), np.ones(n), -np.ones(n), -np.ones(n)])
    r2 = np.concatenate([n + i] * 4); c2 = np.concatenate([S + i + 1, S + i, C0 + i, D0 + i])
    d2 = np.concatenate([np.ones(n), -np.ones(n), -ETA * DT * np.ones(n), (DT / ETA) * np.ones(n)])
    r3 = np.concatenate([2 * n + i] * 3); c3 = np.concatenate([G0 + i, AP + i, AN + i])
    d3 = np.concatenate([np.ones(n), -np.ones(n), np.ones(n)])
    A = sparse.coo_matrix((np.concatenate([d1, d2, d3]),
                           (np.concatenate([r1, r2, r3]), np.concatenate([c1, c2, c3]))),
                          shape=(3 * n, nv)).tocsr()
    b = np.concatenate([L_rem - P_rem, np.zeros(n), ghat_rem])
    lo = ([0.0] * n * 4 + [soc_start, SOC_MIN] + [SOC_MIN] * (n - 2) + [soc_end] + [0.0] * n + [0.0] * n)
    hi = ([None] * n + [P_MAX] * n + [P_MAX] * n + [None] * n
          + [soc_start, SOC_MAX] + [SOC_MAX] * (n - 2) + [soc_end] + [None] * n + [None] * n)
    res = linprog(c, A_eq=A, b_eq=b, bounds=list(zip(lo, hi)), method="highs")
    assert res.success, res.message
    x = res.x
    return x[G0:G0 + n], x[C0:C0 + n], x[D0:D0 + n]


def rollout(plan_net, intraday):
    """plan_net: (365,144) 0:00 计划用的净负荷输入；intraday: 'ce'|'perfect'。"""
    gp, cp, dp, socp = M.solve_annual(plan_net.ravel())
    gp = gp.reshape(NDAYS, N); cp = cp.reshape(NDAYS, N); dp = dp.reshape(NDAYS, N)
    sm = socp[::N]
    gf, cf, df = gp.copy(), cp.copy(), dp.copy()
    for d in range(NDAYS):
        soc_end = sm[d + 1] if d + 1 < NDAYS else SOC0
        for (s_hour, s_idx), Pfull in zip(STAGES, PVFC[d]):
            si = s_hour * 6
            s = sm[d]
            for t in range(si):
                s += ETA * cf[d, t] * DT - df[d, t] * DT / ETA
            if intraday == 'perfect':
                P_rem, L_rem = pv[d, si:], load[d, si:]
            else:
                P_rem = Pfull[si:]
                den = L_base[d, :si].sum()
                L_rem = (load[d, :si].sum() / den if den > 1e-6 else 1.0) * L_base[d, si:]
            g, c, dd = solve_stage_ce(si, s, soc_end, P_rem, L_rem, gp[d, si:], price_day[si:])
            nx = si + 36
            gf[d, si:nx] = g[:36]; cf[d, si:nx] = c[:36]; df[d, si:nx] = dd[:36]
    e = np.maximum(0.0, load + cf - gf - pv - df)
    pf = (price_day * gf * DT)[win].sum()
    af = (0.5 * price_day * np.abs(gf - gp) * DT)[win].sum()
    ef = (5 * price_day * e * DT)[win].sum()
    return pf, af, ef, (e * DT)[win].sum()


if __name__ == "__main__":
    real = (L_base - P_hat)                     # 现实 0:00 输入（附件3 预报 + 统计负荷）
    perf = load - pv                            # 完美 0:00 输入
    print(f"{'阶梯':<28}{'计划费':>14}{'调整费':>12}{'紧急费':>13}{'总费':>14}")
    print("-" * 82)
    for name, net, mode in [
        ("A 完美计划 + 完美日内", perf, 'perfect'),
        ("B 现实计划 + 完美日内", real, 'perfect'),
        ("C 完美计划 + 现实日内", perf, 'ce'),
        ("D 现实计划 + 现实日内", real, 'ce'),
    ]:
        pf, af, ef, ek = rollout(net, mode)
        print(f"{name:<28}{pf:>14,.0f}{af:>12,.0f}{ef:>13,.0f}{pf+af+ef:>14,.0f}")
