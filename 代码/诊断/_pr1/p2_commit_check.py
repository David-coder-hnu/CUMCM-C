# -*- coding: utf-8 -*-
"""验证：problem2_stochastic_group.py 的 d̂ 是否是一阶段承诺（0:00 定死），
   以及这个承诺在执行层是否有代价。"""
import os, sys
import numpy as np, pandas as pd
from scipy.optimize import linprog
from scipy import sparse
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DT, ETA, P_MAX = 1.0/6.0, 0.9, 5000.0
SOC_MIN, SOC_MAX, SOC0 = 1200.0, 10800.0, 6000.0
N, NDAYS, REPORT = 144, 365, 31
T = N*NDAYS
BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
price_day = pd.read_excel(os.path.join(BASE,"附件","附件1.xlsx")).iloc[:,1].to_numpy(float)
load = pd.read_excel(os.path.join(BASE,"附件","附件2.xlsx"),sheet_name="小区负载").iloc[:,1:1+N].to_numpy(float)
pv   = pd.read_excel(os.path.join(BASE,"附件","附件2.xlsx"),sheet_name="光伏发电实际功率").iloc[:,1:1+N].to_numpy(float)
price = np.tile(price_day, NDAYS); win = np.zeros(T,bool); win[REPORT*N:] = True
L = load.ravel(); P = pv.ravel()

def peers_sw(k): return [[d-7*j for j in range(1,k+1) if d-7*j>=0] for d in range(NDAYS)]
def peers_group(dows, span=14):
    m = np.array([(d%7) in dows for d in range(NDAYS)])
    return [[t for t in range(max(0,d-span),d) if m[t]==m[d]] for d in range(NDAYS)]

def solve_deliver(peers, gamma=1.0):
    base_e = np.zeros(NDAYS, dtype=np.int64); _c = 0
    for d in range(NDAYS):
        base_e[d] = _c; _c += max(1,len(peers[d]))*N
    E_total = _c
    sc = lambda d: peers[d] if peers[d] else [d]
    G0,D0,S0_,CM0,E0 = 0,T,2*T,3*T+1,4*T+1
    n_vars = E0+E_total
    q = np.empty(T)
    for dd in range(NDAYS):
        p = sc(dd); vals = pv[p]-load[p]
        q[dd*N:(dd+1)*N] = np.quantile(vals,1.0-gamma,axis=0) if len(p)>1 else vals[0]
    c_obj = np.zeros(n_vars); c_obj[G0:G0+T] = price
    for dd in range(NDAYS):
        p = sc(dd); Kd = len(p)
        for w in range(Kd):
            sl = slice(base_e[dd]+w*N, base_e[dd]+(w+1)*N)
            c_obj[E0+sl.start:E0+sl.stop] = 5.0*price_day/Kd
    t = np.arange(T)
    A_eq = sparse.coo_matrix((np.concatenate([np.ones(T),-np.ones(T),-ETA*DT*np.ones(T),(DT/ETA)*np.ones(T)]),
        (np.concatenate([t,t,t,t]), np.concatenate([S0_+t+1,S0_+t,CM0+t,D0+t]))), shape=(T,n_vars)).tocsr()
    n1,n2 = T,E_total
    ur,uc,ud,ub = [],[],[],[]
    ur += [t,t,t]; uc += [CM0+t,G0+t,D0+t]; ud += [np.ones(T),-np.ones(T),-np.ones(T)]; ub.append(q)
    for dd in range(NDAYS):
        for w,pd_ in enumerate(sc(dd)):
            r = base_e[dd]+w*N; rr = n1+np.arange(r,r+N); tt = dd*N+np.arange(N)
            ur += [rr,rr,rr]; uc += [G0+tt,D0+tt,E0+np.arange(r,r+N)]
            ud += [-np.ones(N),-np.ones(N),-np.ones(N)]; ub.append(pv[pd_]-load[pd_])
    A_ub = sparse.coo_matrix((np.concatenate(ud),(np.concatenate(ur),np.concatenate(uc))),shape=(n1+n2,n_vars)).tocsr()
    bounds = ([(0,None)]*T+[(0,P_MAX)]*T+[(SOC0,SOC0)]+[(SOC_MIN,SOC_MAX)]*(T-1)+[(SOC0,SOC0)]
              +[(0,P_MAX)]*T+[(0,None)]*E_total)
    res = linprog(c_obj,A_eq=A_eq,b_eq=np.zeros(T),A_ub=A_ub,b_ub=np.concatenate(ub),bounds=bounds,method="highs")
    assert res.success, res.message
    return res.x[G0:G0+T], res.x[D0:D0+T], res.x[CM0:CM0+T]

def proper_rollout(g, d, c):          # PR 的 proper_rollout / honest_sim 逻辑
    soc=SOC0; d_act=np.zeros(T); c_act=np.zeros(T); e=np.zeros(T)
    for t in range(T):
        dt_ = min(d[t], max(0.0,(soc-SOC_MIN)*ETA/DT))          # 注意：只受 SOC 限，不受缺口限
        ct_ = min(c[t], max(0.0, P[t]+g[t]+dt_-L[t]), max(0.0,(SOC_MAX-soc)/(ETA*DT)))
        soc += (ETA*ct_ - dt_/ETA)*DT
        e[t] = max(0.0, L[t]-g[t]-P[t]-dt_); d_act[t]=dt_; c_act[t]=ct_
    return (price*g*DT)[win].sum()+(5*price*e*DT)[win].sum(), (e*DT)[win].sum(), d_act, c_act, e

def exec_causal(g):
    soc=SOC0; d=np.zeros(T); c=np.zeros(T); e=np.zeros(T)
    for t in range(T):
        defi = max(0.0, L[t]-P[t]-g[t])
        d[t] = min(defi, P_MAX, max(0.0,(soc-SOC_MIN)*ETA/DT))   # 缺口驱动，忽略 d̂
        c[t] = min(P_MAX, max(0.0, P[t]+g[t]+d[t]-L[t]), max(0.0,(SOC_MAX-soc)/(ETA*DT)))
        e[t] = max(0.0, L[t]-P[t]-g[t]-d[t]); soc += (ETA*c[t]-d[t]/ETA)*DT
    return (price*g*DT)[win].sum()+(5*price*e*DT)[win].sum(), (e*DT)[win].sum()

for tag, peers in [("A 同星期几 K=4", peers_sw(4)), ("B 同组 {Fri,Sat} (PR#1)", peers_group((2,3)))]:
    g, d_hat, c_plan = solve_deliver(peers, 1.0)
    deficit = np.maximum(0.0, L-P-g)
    nd = d_hat*DT
    tot_d = nd[win].sum(); waste = np.maximum(0.0, d_hat-deficit)[win].sum()*DT
    c_p, em_p, d_act, c_act, e_act = proper_rollout(g, d_hat, c_plan)
    c_c, em_c = exec_causal(g)
    print("="*94)
    print(tag)
    print("="*94)
    print(f"  d̂ 的总放电量            {tot_d:>14,.0f} kWh")
    print(f"    其中【无缺口时也在放】  {waste:>14,.0f} kWh  ({waste/tot_d*100:.1f}% of d̂)")
    print(f"    d̂ > 0 但缺口 = 0 的槽数 {(np.maximum(0.0,d_hat-deficit)[win]>1e-6).sum():>14,} / {win.sum():,}")
    print(f"  执行层 d_act 与 d̂ 的偏差  {np.abs(d_act-d_hat)[win].sum()*DT:>14,.0f} kWh (仅 SOC 限幅削掉的)")
    print(f"  循环：d̂ 放出又被充回     {waste:>14,.0f} kWh  →  白付 η 往返损失")
    print(f"  ① PR proper_rollout 费用 {c_p:>14,.0f} 元   紧急 {em_p:>10,.0f} kWh")
    print(f"  ② main 因果执行 费用     {c_c:>14,.0f} 元   紧急 {em_c:>10,.0f} kWh")
    print(f"  ① − ②                  {c_p-c_c:>+14,.0f} 元   ← 「按 d̂ 放电」的代价")
    print()
