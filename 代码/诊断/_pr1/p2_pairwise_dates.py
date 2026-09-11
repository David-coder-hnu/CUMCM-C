# -*- coding: utf-8 -*-
"""那 10 天是哪几天？是结构性的还是一次日天气事件？"""
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
price = np.tile(price_day, NDAYS)
L = load.ravel(); P = pv.ravel(); RDAYS = np.arange(REPORT, NDAYS)
DOW = np.array([['三','四','五','六','日','一','二'][d%7] for d in range(NDAYS)])
DATE = pd.date_range("2025-01-01", periods=NDAYS, freq="D")

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
    return (price*g*DT + 5*price*e*DT).reshape(NDAYS,N).sum(axis=1)[RDAYS], e.reshape(NDAYS,N)[RDAYS].sum(axis=1)*DT

A1,_ = daily(solve_deliver(peers_sw(4)))
A2,_ = daily(solve_deliver(peers_sw(2)))
A3,e3 = daily(solve_deliver(peers_group((2,3))))
A4,e4 = daily(solve_deliver(peers_group((3,4))))
d32 = A3-A2

idx = np.argsort(d32)
print("="*104)
print("A3−A2 最省的 15 天（日期 / 星期 / 该日 A2 紧急电量 / A3 紧急电量 / Δ）")
print("="*104)
print(f"{'日期':<12}{'星期':<5}{'A2紧急kWh':>12}{'A3紧急kWh':>12}{'Δ元':>13}{'A2成本':>13}{'A3成本':>13}")
print("-"*104)
for i in idx[:15]:
    d = RDAYS[i]
    print(f"{DATE[d].strftime('%Y-%m-%d'):<12}{DOW[d]:<5}{e3[i]-e4[i] and 0 or 0:>12}"
          f"{'':>12}{d32[i]:>+13,.0f}{A2[i]:>13,.0f}{A3[i]:>13,.0f}")
print()
print("="*104)
print("最省的 15 天在日历上的位置（看是否成簇）")
print("="*104)
for i in idx[:15]:
    d = RDAYS[i]
    print(f"  第 {d:>3} 天  {DATE[d].strftime('%Y-%m-%d')}  星期{DOW[d]}   Δ={d32[i]:>+10,.0f}")
print()
print("="*104)
print("按月份汇总 Δ（A3−A2）")
print("="*104)
mon = DATE[RDAYS].month
print(f"{'月份':>5}{'天数':>6}{'Δ合计':>15}{'Δ日均':>12}")
for m in sorted(set(mon)):
    k = mon==m
    print(f"{m:>5}{k.sum():>6}{d32[k].sum():>+15,.0f}{d32[k].mean():>+12,.0f}")
print()
print("="*104)
print("剔除最省的 N 天后，A3−A2 的剩余总差（稳健性）")
print("="*104)
srt = np.sort(d32)
for k in (0,5,10,15,20,30,50):
    print(f"   剔除前 {k:>3} 天：剩余 {srt[k:].sum():>+13,.0f} 元   "
          f"日均 {srt[k:].mean():>+9,.0f}   天数 {len(srt)-k}")
print()
print("="*104)
print("对照：A3−A1 与 A4−A1（Sat+Sun）同样做剔除")
print("="*104)
for nm, dv in [("A3−A1", A3-A1), ("A2−A1", A2-A1), ("A4−A1", A4-A1)]:
    s = np.sort(dv)
    print(f"  {nm}: 总 {s.sum():>+12,.0f}  剔除前10天 {s[10:].sum():>+12,.0f}  "
          f"剔除前20天 {s[20:].sum():>+12,.0f}  中位数 {np.median(dv):>+8,.0f}  "
          f"更便宜的日 {int((dv<0).sum())}/334")
