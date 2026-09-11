# -*- coding: utf-8 -*-
"""关键的混淆检验：收益来自「按低需求日分组」还是仅仅来自「窗口从4周缩到2周」？
   A2 同星期几 K=2  = 只换窗口，不换分组
   A3 低需求日/其余  = 换分组（窗口同为 2 周）
   直接对 A3 − A2 做配对块自助。"""
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
L = load.ravel(); P = pv.ravel(); RDAYS = np.arange(REPORT, NDAYS)

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
    return res.x[G0:G0+T]

def exec_causal(g):
    c=np.zeros(T); d=np.zeros(T); e=np.zeros(T); soc=SOC0
    for t in range(T):
        defi = max(0.0, L[t]-P[t]-g[t])
        d[t] = min(defi, P_MAX, max(0.0,(soc-SOC_MIN)*ETA/DT))
        c[t] = min(P_MAX, max(0.0, P[t]+g[t]+d[t]-L[t]), max(0.0,(SOC_MAX-soc)/(ETA*DT)))
        e[t] = max(0.0, L[t]-P[t]-g[t]-d[t])
        soc += (ETA*c[t]-d[t]/ETA)*DT
    return e

def daily(g):
    e = exec_causal(g)
    return (price*g*DT + 5*price*e*DT).reshape(NDAYS,N).sum(axis=1)[RDAYS]

def boot(diff, block=14, n=4000, seed=0):
    rng = np.random.default_rng(seed); m = len(diff); nb = int(np.ceil(m/block))
    st = np.arange(m-block+1); out = np.empty(n)
    for i in range(n):
        s = rng.choice(st, nb, replace=True)
        idx = np.concatenate([np.arange(j,j+block) for j in s])[:m]
        out[i] = diff[idx].mean()
    return np.percentile(out,[2.5,97.5]), (out.mean()/out.std(ddof=1))

A1 = daily(solve_deliver(peers_sw(4)))
A2 = daily(solve_deliver(peers_sw(2)))
A3 = daily(solve_deliver(peers_group((2,3))))

print("="*88)
print("配对检验：收益来自「分组」还是「窗口更近」？")
print("="*88)
print(f"{'A1 同星期几 K=4':<22}{A1.sum():>16,.0f}")
print(f"{'A2 同星期几 K=2':<22}{A2.sum():>16,.0f}")
print(f"{'A3 低需求日/其余':<22}{A3.sum():>16,.0f}")
print("-"*88)
for lbl, a, b in [("A3 − A1  分组+窗口", A3, A1), ("A2 − A1  只换窗口", A2, A1), ("A3 − A2  只换分组", A3, A2)]:
    diff = a-b; ci, t = boot(diff)
    sig = "是" if (ci[0]>0)==(ci[1]>0) else "否"
    print(f"{lbl:<22}Δ {diff.sum():>+13,.0f}  日均 {diff.mean():>+9,.0f}  "
          f"95%CI [{ci[0]:+,.0f}, {ci[1]:+,.0f}]  块自助t={t:+.2f}  显著:{sig}")
print("-"*88)
print("A2 与 A1 窗口不同但分组相同 ⇒ 若 CI 含 0，说明『窗口变近』本身不构成收益")
print("A3 与 A2 窗口相同但分组不同 ⇒ 若 CI 不含 0，说明收益确由『分组』带来")
