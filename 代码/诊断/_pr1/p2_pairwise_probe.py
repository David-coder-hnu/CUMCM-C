# -*- coding: utf-8 -*-
"""追查 A3−A2 临界的原因：收益是否集中、符号是否一致、块长是否敏感。"""
import os, sys
import numpy as np, pandas as pd
from scipy.optimize import linprog
from scipy import sparse
from scipy import stats
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
DOW = np.array([['Wed','Thu','Fri','Sat','Sun','Mon','Tue'][d%7] for d in range(NDAYS)])

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

def boot(diff, block, n=20000, seed=0, stat=np.mean):
    rng = np.random.default_rng(seed); m = len(diff); nb = int(np.ceil(m/block))
    st = np.arange(m-block+1); out = np.empty(n)
    for i in range(n):
        s = rng.choice(st, nb, replace=True)
        out[i] = stat(diff[np.concatenate([np.arange(j,j+block) for j in s])[:m]])
    return out

A1 = daily(solve_deliver(peers_sw(4)))
A2 = daily(solve_deliver(peers_sw(2)))
A3 = daily(solve_deliver(peers_group((2,3))))
d32 = A3 - A2
d21 = A2 - A1
d31 = A3 - A1

print("="*92)
print("一、符号一致性与随机性检验（A3−A2，窗口同为 2 周，唯一差别是分组）")
print("="*92)
neg = (d32 < 0).sum(); pos = (d32 > 0).sum()
print(f"  更便宜的日数 = {neg} / 334   更贵的日数 = {pos}   持平 = {334-neg-pos}")
print(f"  符号检验 p(单侧) = {stats.binomtest(int(neg), int(neg+pos), 0.5, alternative='greater').pvalue:.4g}")
print(f"  配对 t 检验 p(双侧) = {stats.ttest_rel(A3, A2).pvalue:.4g}   (朴素，未考虑自相关，仅供参考)")
print(f"  均值 {d32.mean():+,.0f}  中位数 {np.median(d32):+,.0f}  标准差 {d32.std(ddof=1):,.0f}")
print()
print("  收益集中度：把 334 天按 Δ 从低到高排序")
srt = np.sort(d32)
for k in (5, 10, 20, 40):
    print(f"    最省的前 {k:>3} 天合计 {srt[:k].sum():>+12,.0f} 元  "
          f"（占总差 {srt[:k].sum()/d32.sum()*100:>6.1f}%）")
print(f"    去掉最省的 10 天后，剩余总差 = {srt[10:].sum():+,.0f}")
print(f"    去掉最省的 20 天后，剩余总差 = {srt[20:].sum():+,.0f}")

print()
print("="*92)
print("二、按星期几分组看 Δ（找收益的来源）")
print("="*92)
print(f"{'星期':<6}{'天数':>6}{'Δ合计':>15}{'Δ日均':>12}")
print("-"*92)
for k in range(7):
    m = np.array([d%7==k for d in RDAYS])
    nm = ['Wed','Thu','Fri','Sat','Sun','Mon','Tue'][k]
    print(f"{nm:<6}{m.sum():>6}{d32[m].sum():>+15,.0f}{d32[m].mean():>+12,.0f}")

print()
print("="*92)
print("三、块长敏感性（A3−A2），n=20000")
print("="*92)
print(f"{'块长':>6}{'95%CI 下':>13}{'95%CI 上':>13}{'含0':>7}{'单侧p(≈)':>10}")
print("-"*92)
for bl in (7, 14, 21, 28, 42, 56):
    o = boot(d32, bl)
    lo, hi = np.percentile(o, [2.5, 97.5])
    p1 = (o >= 0).mean()
    print(f"{bl:>6}{lo:>+13,.0f}{hi:>+13,.0f}{('是' if lo<=0<=hi else '否'):>7}{p1:>10.3f}")
print()
print("对照：A3−A1（同时换了分组和窗口）")
for bl in (14, 28):
    o = boot(d31, bl); lo,hi = np.percentile(o,[2.5,97.5])
    print(f"  块长{bl:>3}: [{lo:+,.0f}, {hi:+,.0f}]  单侧p={ (o>=0).mean():.3f}")
print("对照：A2−A1（只换窗口）")
for bl in (14, 28):
    o = boot(d21, bl); lo,hi = np.percentile(o,[2.5,97.5])
    print(f"  块长{bl:>3}: [{lo:+,.0f}, {hi:+,.0f}]  单侧p={ (o>=0).mean():.3f}")
