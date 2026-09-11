# -*- coding: utf-8 -*-
"""前提检查：问题3 的分组有没有可用的统计基础？
   1) 残差 (actual_net − F_hat[.,0,:]) 的尺度是否按低需求日分组而不同？
   2) 分组分位 vs 池化分位，差多少 kWh？"""
import os, sys
import numpy as np, pandas as pd
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
N, NDAYS, REPORT = 144, 365, 31
BLOCKS = [(0,36),(36,72),(72,108),(108,144)]
TAU_B = [0.80,0.55,0.55,0.55]
DOW_NAME = ["Wed","Thu","Fri","Sat","Sun","Mon","Tue"]

load = pd.read_excel(os.path.join(BASE,"附件","附件2.xlsx"),sheet_name="小区负载").iloc[:,1:1+N].to_numpy(float)
pv   = pd.read_excel(os.path.join(BASE,"附件","附件2.xlsx"),sheet_name="光伏发电实际功率").iloc[:,1:1+N].to_numpy(float)
fc3  = pd.read_excel(os.path.join(BASE,"附件","附件3.xlsx"),header=None).iloc[1:,2:].to_numpy(float).reshape(NDAYS,4,24)
actual_net = load - pv
Wm = np.zeros((N,25))
for k in range(N):
    t=(k+1)/6.0; lo=int(np.floor(t)); hi=min(int(np.ceil(t)),24)
    if lo==hi: Wm[k,lo]=1.0
    else: Wm[k,lo]=1.0-(t-lo); Wm[k,hi]=t-lo
S_HOUR=[0,6,12,18]
def pv_fc(d,s):
    H=np.zeros(25)
    if S_HOUR[s]>0: H[S_HOUR[s]]=pv[d,6*S_HOUR[s]]
    for h in range(S_HOUR[s]+1,25): H[h]=fc3[d,s,h-S_HOUR[s]-1]
    return H@Wm.T
P_hat=np.stack([[pv_fc(d,s) for s in range(4)] for d in range(NDAYS)])
K=4
L_base=np.zeros_like(load)
for d in range(NDAYS):
    idx=[d-7*k for k in range(1,K+1) if d-7*k>=0]
    L_base[d]=load[idx].mean(axis=0) if idx else load.mean(axis=0)
F_hat = L_base[:,None,:]-P_hat

# ---- 低需求日分组（只喂暖机期）----
dow = np.array([d%7 for d in range(NDAYS)])
warm = np.arange(0,REPORT)
nl = actual_net.sum(axis=1)
mean_nl = np.array([nl[warm][dow[warm]==k].mean() for k in range(7)])
order = np.argsort(mean_nl)
GRP = (int(order[0]), int(order[1]))
print("="*100)
print("暖机期（前 31 天）各星期几日均净负荷 (kWh/日)")
print("="*100)
for k in range(7):
    print(f"  {DOW_NAME[k]:<4} {mean_nl[k]:>12,.0f}" + ("   ← 低需求日" if k in GRP else ""))
print(f"  ⟹ 低需求日 = {{{', '.join(DOW_NAME[k] for k in GRP)}}}")

R = actual_net - F_hat[:,0,:]          # 残差，行=天
m_lo = np.array([ (d%7) in GRP for d in range(NDAYS)])

print("\n"+"="*100)
print("残差尺度 by 组（全年）：逐槽 std 的日均、以及 |残差| 的日均")
print("="*100)
print(f"{'':<6}{'天数':>6}{'逐槽std均值':>14}{'|残差|均值':>14}{'净负荷均值':>14}{'std/净负荷':>12}")
for nm, m in [("低需求日", m_lo), ("其余五天", ~m_lo)]:
    sd = R[m].std(axis=0).mean()
    ad = np.abs(R[m]).mean()
    lo_ = actual_net[m].mean()
    print(f"{nm:<6}{m.sum():>6}{sd:>14,.0f}{ad:>14,.0f}{lo_:>14,.0f}{sd/lo_*100:>11.1f}%")

print("\n"+"="*100)
print("关键：同一时刻上，「分组分位」与「池化分位」差多少？（正值=池化买得更多）")
print("="*100)
print(f"{'块':<14}{'τ':>6}{'池化分位':>12}{'低需求日分位':>14}{'其余五天分位':>14}"
      f"{'池化−低':>12}{'池化−其余':>12}")
for e,(a,b) in enumerate(BLOCKS):
    qp = np.quantile(R[:,a:b], TAU_B[e], axis=0).mean()
    ql = np.quantile(R[m_lo][:,a:b], TAU_B[e], axis=0).mean()
    qh = np.quantile(R[~m_lo][:,a:b], TAU_B[e], axis=0).mean()
    nm = f"{a/6:.0f}:00-{b/6:.0f}:00"
    print(f"{nm:<14}{TAU_B[e]:>6.2f}{qp:>12,.0f}{ql:>14,.0f}{qh:>14,.0f}{qp-ql:>12,.0f}{qp-qh:>12,.0f}")
print("\n  池化分位落在两组之间 ⟹ 对低需求日【过买】、对高需求日【欠买】，两个方向同时存在。")
