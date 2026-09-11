# -*- coding: utf-8 -*-
"""问题 4 电价诊断：波动电价的结构、可预测性、以及电价信息的价值。

只读附件 1/2/4，不写任何交付文件。
"""
import numpy as np
import pandas as pd
from scipy.optimize import linprog
from scipy.sparse import lil_matrix, csr_matrix, vstack

DT, ETA, PMAX = 1/6, 0.9, 5000.0
SMIN, SMAX, S0 = 1200.0, 10800.0, 6000.0
N = 144

P4 = pd.read_excel('附件/附件4.xlsx', header=0)
PR = P4.iloc[:, 1:].to_numpy(float)                       # 365 x 144 实际电价
P1 = pd.read_excel('附件/附件1.xlsx', header=0)
B = P1.iloc[:, 1].to_numpy(float).ravel()                 # 144 基准电价剖面
LOAD = pd.read_excel('附件/附件2.xlsx', sheet_name='小区负载', header=0).iloc[:, 1:].to_numpy(float)
PV = pd.read_excel('附件/附件2.xlsx', sheet_name='光伏发电实际功率', header=0).iloc[:, 1:].to_numpy(float)
assert PR.shape == (365, 144) and B.shape == (144,) and LOAD.shape == (365, 144)


def build(Ld, Pd):
    """单日 144 槽储能套利 LP。变量 g|c|d|s|SOC，共 721。"""
    Aeq = lil_matrix((2 * N, 721))
    beq = np.zeros(2 * N)
    for t in range(N):
        Aeq[t, t] = 1; Aeq[t, 288 + t] = 1; Aeq[t, 144 + t] = -1; Aeq[t, 432 + t] = -1
        beq[t] = Ld[t] - Pd[t]
    for t in range(N):
        Aeq[N + t, 576 + t + 1] = 1; Aeq[N + t, 576 + t] = -1
        Aeq[N + t, 144 + t] = -ETA * DT; Aeq[N + t, 288 + t] = DT / ETA
    Aeq = Aeq.tocsr()
    Aeq = vstack([Aeq, csr_matrix(np.r_[np.zeros(576), [1.0] + [0.0] * 144][None, :])])
    beq = np.r_[beq, S0]
    Aeq = vstack([Aeq, csr_matrix(np.r_[np.zeros(720), [1.0]][None, :])])
    beq = np.r_[beq, S0]
    lb = np.zeros(721); ub = np.full(721, np.inf)
    lb[144:288] = 0.0; ub[144:288] = PMAX
    lb[288:432] = 0.0; ub[288:432] = PMAX
    lb[576:721] = SMIN; ub[576:721] = SMAX
    return Aeq, beq, lb, ub


def solve(cost_g, Ld, Pd):
    Aeq, beq, lb, ub = build(Ld, Pd)
    c = np.zeros(721); c[:N] = cost_g * DT
    return linprog(c, A_eq=Aeq, b_eq=beq, bounds=list(zip(lb, ub)), method='highs')


def main():
    out = []
    out.append('### 1. 波动电价的结构（附件4 vs 附件1 基准剖面）')
    mu = PR.mean(0)
    out.append('基准剖面 B 与 附件4 逐槽均值 mu 的最大绝对差 = %.3e' % np.abs(mu - B).max())
    out.append('日均价: mean %.4f  std %.4f  min %.4f  max %.4f  (std/mean = %.1f%%)'
               % (PR.mean(1).mean(), PR.mean(1).std(), PR.mean(1).min(), PR.mean(1).max(),
                  100 * PR.mean(1).std() / PR.mean(1).mean()))
    R = PR - mu
    a = R.mean(1); E = R - a[:, None]
    out.append('方差分解: 总 %.6f | 日内形状 %.1f%% | 日水平因子 %.1f%% | 日内残差 %.1f%%'
               % (PR.var(), 100 * mu.var() / PR.var(), 100 * a.var() / PR.var(), 100 * E.var() / PR.var()))
    out.append('日水平因子 lag-1 自相关 = %.3f' % np.corrcoef(a[:-1], a[1:])[0, 1])
    out.append('日内残差 lag-1 自相关 = %.3f' % np.corrcoef(E[:, :-1].ravel(), E[:, 1:].ravel())[0, 1])

    out.append('')
    out.append('### 2. 电价偏离的可预测性（水平校正）')
    for cut in [0, 12, 36, 72, 108]:
        num = den = 0.0
        for d in range(365):
            if cut == 0:
                pred = np.zeros(N)
            else:
                pred = np.r_[R[d, :cut], np.full(N - cut, R[d, :cut].mean())]
            num += ((pred - R[d]) ** 2).sum(); den += (R[d] ** 2).sum()
        out.append('  用前 %3d 槽(%4.1fh) 校正 -> 余下时段残余 MSE 占比 %.3f  (R2=%.3f)'
                   % (cut, cut / 6, num / den, 1 - num / den))

    out.append('')
    out.append('### 3. 电价与负荷/光伏的耦合')
    net = LOAD - PV
    netd = net.mean(1)
    out.append('  日水平因子 a_d  vs  日均净负荷 : corr = %.3f' % np.corrcoef(a, netd)[0, 1])
    out.append('  日水平因子 a_d  vs  日均负荷   : corr = %.3f' % np.corrcoef(a, LOAD.mean(1))[0, 1])
    out.append('  日水平因子 a_d  vs  日均光伏   : corr = %.3f' % np.corrcoef(a, PV.mean(1))[0, 1])

    out.append('')
    out.append('### 4. 电价信息的价值（单日储能套利 LP，无紧急购电，2025-02-01 起 334 天）')
    fore_wd = np.zeros_like(PR)
    for d in range(365):
        idx = [k for k in range(max(0, d - 28), d) if (d - k) % 7 == 0]
        fore_wd[d] = PR[idx].mean(0) if idx else B

    cost = {'perfect': 0.0, 'base_profile': 0.0, 'weekday_forecast': 0.0, 'base+level(6h)': 0.0}
    for d in range(31, 365):
        Ld, Pd = LOAD[d], PV[d]
        r = solve(PR[d], Ld, Pd)
        if not r.success:
            out.append('  !! LP fail day %d' % d); continue
        cost['perfect'] += PR[d] @ r.x[:N] * DT
        for name, fc in [('base_profile', B), ('weekday_forecast', fore_wd[d])]:
            r2 = solve(fc, Ld, Pd)
            cost[name] += PR[d] @ r2.x[:N] * DT
        fc = np.clip(B + (PR[d, :36] - B[:36]).mean(), 1e-3, None)
        r3 = solve(fc, Ld, Pd)
        cost['base+level(6h)'] += PR[d] @ r3.x[:N] * DT

    ref = cost['perfect']
    out.append('  %-18s %18s %14s' % ('口径', '实际价格下费用(元)', '相对完美预见'))
    for k, v in cost.items():
        out.append('  %-18s %18.0f %13.0f (%.2f%%)' % (k, v, v - ref, 100 * (v - ref) / ref))

    txt = '\n'.join(out)
    print(txt)
    with open('代码/诊断/_p4_price_diag.txt', 'w', encoding='utf-8') as f:
        f.write(txt + '\n')


if __name__ == '__main__':
    main()
