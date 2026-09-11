# -*- coding: utf-8 -*-
"""问题 4（对应问题 3）—— 波动电价下、口径 A 的三层购电策略。

由 problem3_v3.py 派生，模型结构、账本、三层架构、全部既有约定一字不改；
**只改价格进入模型的方式**，共 7 处（见 §Q4-2）。

════════════════════════════════════════════════════════════════════════════
§Q4-1  与问题 3 的差别：价格不再是一条常数剖面
════════════════════════════════════════════════════════════════════════════
问题 3 题面「每天的电价相同」⇒ 全程共用附件1 的一条 144 槽剖面。
问题 4 题面「外网的电价也是实时波动的」⇒ 结算改用附件4 的 365×144 实际电价。

实测两个价格的共同结构（代码/诊断/_p4_price_diag.txt）：
  · 附件4 的逐槽跨日均值剖面与附件1 最大绝对差 5.151e-05 元
    ⇒ 附件1 就是「典型日分时电价」形状，附件4 = 该形状 + 波动
  · 方差分解：日内形状 84.6% / 日水平因子 9.2% / 日内残差 6.2%
  · 日水平因子 a_d 是**全天均匀平移**，而口径 A 的四项（p·ĝ、0.5p、1.5p、5p）
    都是同一个 p 的倍数 ⇒ 均匀平移不改变任何边际权衡 ⇒ **不改变最优策略，只改变账单**

  ⇒ 单日储能套利 LP 实测：完美价格信息相对任何预报只值 1.04%；把价格 MAE 从
     0.0968 砍到 0.0475（同星期几预报器）只买回 0.02%。所以本文件**不新造价格预报器**。

════════════════════════════════════════════════════════════════════════════
§Q4-2  价格进入模型的 7 处（前 6 处是替换，第 7 处是新增机理）
════════════════════════════════════════════════════════════════════════════
  #  位置                    问题 3              问题 4
  1  数据加载                price=tile(附件1)   + PR=附件4；price_real=PR.ravel()
  2  sentinel 目标            price[:T]           price_real[:T]（完美预见，必须用实际价）
  3  exec_day 的 MPC 窗口价   price_day           PR[d]（读法A）/ price_day（读法B）
  4  _solve → plan_day        price_day           PR[d]（读法A）/ price_day（读法B）
  5  run 结算                 price[:nd*N]        price_real[:nd*N]
  6  write_result4_3.day_fee  price_day           PR[di]
  7  计划/调整层的分位        普通分位             **按该历史日实际电价加权的分位**（WQ）

  分工铁律：**结算与写盘永远用实际价**（唯一花钱的地方）；计划层的价格系数取决于读法。

════════════════════════════════════════════════════════════════════════════
§Q4-3  第 7 处：本问真正的机理，价格与缺口的**联合分布**
════════════════════════════════════════════════════════════════════════════
报童临界比是 c_u/(c_u+c_o)，其中 c_u = 4·E[p | 缺口]、c_o = E[p | 过剩]。
附件4 里缺电的日子电价系统性更高 —— 日水平因子 a_d 与日均净负荷 corr = **0.982**，
逐槽跨天 median 0.933 ⇒ E[p|缺口] 比独立假设下高约 20%（q=0.8 处实测 1.206×）
⇒ 有效紧急边际成本更高 ⇒ 理论上同一个 τ 对应的 ĝ 应当更高（0.80 → ≈0.836）。

样本实现：对历史残差取分位时，用**该历史日同日同槽的实际电价 PR[q, t] 作权重**
（WQ=1）。高价样本被推高权重，把分位向上抬。

⚠⚠ **实测为负结果，故缺省关闭（P4_WQ=0）。** 三组对照（读法B、G≤5000）：
      WQ=0 τ=0.80        15,443,245   ← 最优
      WQ=1 τ=0.80        15,455,826   紧急购电 −6.3%（488,970→457,989），
                                      但计划购电 +65,429，净亏 12,581
      WQ=1 重扫 τ(=0.78) 15,453,379   仍输 10,134
   τ 重扫（WQ=0）：0.70→15,467,307 ｜ 0.75→15,452,761 ｜ **0.80→15,443,245** ｜
                   0.836→15,450,067 ｜ 0.86→15,460,124 ｜ 0.90→15,503,329
   ⇒ **最优 τ 仍停在 0.80，没有出现理论预测的 0.836 上移。** 三点原因：
     (a) τ=0.80 本就是**扫出来的经验最优值**，它已经吸收了价格结构，再加权是重复计数；
     (b) 储能的削峰作用把"缺/余"两侧的代价差削平了（v3 已记录过同一现象）；
     (c) 0.75–0.86 整个区间只差 7,363 元（0.05%），效应幅度本就小于标定噪声。
   ⇒ 正确表述是：**价格与缺口的正相关在数据里真实存在，但不改变最优策略。**
     这与 §Q4-1 的总结论（均匀平移不改变边际权衡）互为印证，是论文的正面结论。

对照：WQ=0 退回问题 3 的普通分位，可复现 result3.xlsx 的 14,712,825 元。

════════════════════════════════════════════════════════════════════════════
§Q4-4  两种读法（两者都做）
════════════════════════════════════════════════════════════════════════════
  读法 B（主模型，P4_READING=B，缺省）：0:00 不知道当天实际电价，只有外网**公布**的
      分时电价剖面（附件1）可依据。价格不确定性由加权分位承载。
  读法 A（下界 + 敏感性，P4_READING=A）：0:00 已知全天实际电价 PR[d]。
  两者之差 = 价格信息的价值。实测该差值很小，故「两种都做」成本低，
  本身就是一条稳健性论据（对应 文档/复核报告.md §5 第 10 条）。

  ⚠ 读法 B 下，附件1 的角色从「结算价」变成「公布价」。这不是权宜之计：附件1 本来就
    是分时电价表，附件4 才是实际结算价，微网 0:00 能拿到的正是公布曲线。

  ★★ 读法 B + WQ=0 下的**强结论（已实测，非推理）**：波动电价**不改变最优策略，只改变账单**。
    理由不是估计，而是结构：读法 B 下所有**影响决策**的价格进入点（#3 exec_day 的 pr_d、
    #4 plan_day 的价格系数，以及 #7 关闭时的普通分位）都退回 price_day，与 problem3_v3
    **逐字相同**；只有 #2 哨兵、#5 结算、#6 写盘改用实际价。于是本文件的策略轨迹必然
    与问题 3 完全相同 —— 实测验证（代码/诊断/diag_p4_audit.py 的 L2）：
        结果/result3.xlsx 与 结果/result4-3.xlsx 的
        「计划购电量」「调整购电量」「充放电量」「紧急购电量」四张表**逐格 bit-identical**，
        全天购电量列零差异；只有「全天购电费」列不同：
            14,712,825.34 元 → 15,443,245.19 元（×1.0496，+4.96%）
    这一条把 §Q4-1 的「均匀平移不改变边际权衡」从**论证**升级为**两份独立交付物的互证**，
    是论文最硬的一条结论：**分时电价波动的经济后果全部落在账单上，不落在策略上。**

════════════════════════════════════════════════════════════════════════════
§Q4-5  购电功率上界（自加假设，必须声明）
════════════════════════════════════════════════════════════════════════════
题面（附录1）只给了储能「最大充放电功率 5000 kW」，**没有给微网与外网的联络线容量**。
缺省 G_MAX=5000 是自加的保守假设，旋钮 P4_GMAX；字面读法放开：P4_GMAX=inf。
⚠ 常数价下「放开反而更贵」（v3 实测 +35.8 万），但**波动电价下这个结论会翻转** ——
  详见 文档/问题4_求解归档.md。论文必须如实报出这个反转。

★★ 与上界直接相关的另一条**必须声明**的性质：交付表的购电量里有**12.23%** 既未供负载、
  也未进电池。代数上（diag_p4_audit.py §L1）：令 S = P + g + d − L（富余），则
      能量平衡残差 = Σ(c − S)·1[S≥0] ≡ −Σ max(0, S − c) ≤ 0
  实测该残差 = −2,647,466 kWh/年（占实际购电 12.23%，72.2% 的槽都有丢弃），
  按 6 小时窗口分解：盲窗 13.4% / 6–12h 46.0% / 12–18h 29.4% / 18–24h 11.2%。
  同时 **g 有 36.40% 的槽贴在 G_MAX=5,000 kW 上** ⇒ 这道自加上界是**紧的**，
  它同时也是防止过度购电的唯一闸门（这也是放开上界反而更贵的原因）。
  ⚠ 这不是问题 4 引入的：result3.xlsx 同法测得**完全相同的** −2,647,465 kWh，
  即它是 problem3_v3（以及 problem2.py）继承下来的口径性质。
  口径含义：口径 A 是**照付不议（take-or-pay）**—— 承诺量 ĝ 全额付费、与实收无关，
  所以为对冲缺口而多买的电即便用不上也**已经付过钱**，账单本身自洽；
  但"购电量"这一列因此**不等于可交付电量**，论文必须写明，否则会被误读成该电量被利用了。

════════════════════════════════════════════════════════════════════════════
以下 §0–§3 为 problem3_v3.py 原文，模型本身未改，全部仍然适用
════════════════════════════════════════════════════════════════════════════

与 problem3_v2.py **无任何代码依赖**：数据、账本、哨兵、计划、调整、执行、结算全部
独立重写。目的是把问题 3 从"问题 2 的账本 + 事后补一个分位数"拉回题面本身。

════════════════════════════════════════════════════════════════════════════
§0  口径 A（题目三项费用并列，计划购电费按全额 ĝ 计）
════════════════════════════════════════════════════════════════════════════
题面（C题.md 52–56 行）：
  「可根据 0:00 的预报，制定当天的计划购电策略，也可根据其他时刻的预报，调整购电
    策略。计划购电量高于调整购电量的部分，违约电价是交易时刻电价的 50%。调整购电量
    高于计划购电量的部分，超出部分的电价是交易时刻电价的 1.5 倍。总的购电费用包括
    计划购电费用、紧急购电费用和调整购电量的相关费用。」

本脚本采用的账本：
    总费 = p·ĝ + 0.5p·(ĝ−g)⁺ + 1.5p·(g−ĝ)⁺ + 5p·e
  g = 该时段**最终**购电量；0:00–6:00 无调整机会 ⇒ g ≡ ĝ。
  e = max(0, L − g − P − d)。题面「微网提供的电能不可低于小区负载」⇒ 供电 = 购电 +
      光伏 + 放电。**e 不含充电量 c**（充电是微网内部负荷，不是"提供给小区的电能"）。

口径 A 的两个结构性推论（用于自检，不用于构造解）：
  (1) **违约费在最优解上恒为零。** p·ĝ 已照付；把 g 下调到 ĝ 以下只多付 0.5p 且毫无
      收益 ⇒ 最优 g ≥ ĝ 逐槽成立 ⇒ 报出的违约费若不为 0，说明解没收敛到最优。
  (2) **统一临界分位 0.8。** need = L − P − d（电池放完后的残余缺口）：
        盲窗段 p − 5p·P(need>ĝ) = 0          ⇒ ĝ = Q₀.₈(need)
        可调段 最优 g* = max(ĝ, Q₀.₇(need))，而 Q₀.₈ > Q₀.₇ ⇒ g* = ĝ
      ⇒ 在**不条件化**的意义上，调整通道不被使用。但一旦允许 g 以**新预报**为条件
      （§3），Q₀.₇(need | 新预报) 可以超过 ĝ —— 调整通道的价值全部来自这里。

对照口径 B（v2 归档采用）：
    总费 = p·min(g,ĝ) + 0.5p·(ĝ−g)⁺ + 1.5p·(g−ĝ)⁺ + 5p·e
  B 下 g 下调能省 p ⇒ 下调有益 ⇒ 最优 g 可能低于 ĝ，违约费非零。
  A/B 之别决定题面第二问的答案，不是记账细节。

════════════════════════════════════════════════════════════════════════════
§1  v2 的病根（为什么要另起）
════════════════════════════════════════════════════════════════════════════
交付物 result4-3.xlsx（14,722,577.56 元）已定位为 v2 的 `PLAN=lp EXEC_NAIVE=1`（复现
14,723,850），而 v2 的脚本默认是 `PLAN=sp`（15,715,709）。三步病：
 (1) **ĝ 在没有调整通道的世界里定出来。**
     PLAN=lp：`solve_annual` 是确定性 LP，约束 g+d−c = N_plan（等式），目标只有 Σp·ĝ。
     PLAN=sp：`solve_annual_sp` 目标 = Σp·ĝ + Σ5p·e_ω/K（口径 A 下这个目标是对的），
       但场景集只有 K_PEERS=4 个同星期几日 —— 4 点经验分布的 0.8 分位≈样本极值 ⇒
       **过度对冲**，比 lp 路径贵 53 万。两条路都没有把调整通道放进 ĝ 的优化。
 (2) **对冲分位数非因果。** `Qtab` 在全部 365 天的残差上取分位，第 d 天用到第 d+1..365
     天的信息。
 (3) **执行层从未真正调整 g。** 三条路径下 g_fin ≡ g_hat ⇒ 交付账本的违约费/超额费
     恒为 0。归档中"调整通道值 48.1 万"实为**换对冲分位数**（0.74 vs 0.89）的差。

════════════════════════════════════════════════════════════════════════════
§2  模型（三层，全部因果：第 d 天只用 < d 天的信息）
════════════════════════════════════════════════════════════════════════════
 [哨兵] 完美预见全年 LP（口径 A）—— 任何因果策略都不可能低于它。
 [计划] ĝ_t = F̂_t^(0档) + Q_τ({ need_{q,t} − F̂_{q,t}^(0档) }_{q<d})，clip 到 [0,Pmax]。
        报童不动点：d 依赖 ĝ，故残差分布随 ĝ 变，只能在线迭代（每天用截至昨天的残差
        重算分位）。v2 的 HEDGE_NPY 钩子指向的就是这个对象，但从未实现、且分位非因果。
 [调整] 6/12/18：g_e = clip(max(ĝ, F̂^(e档) + Q_{τ'}({need − F̂^(e档)}_{q<d})), 0, Pmax)
        τ' = 0.7 由可调段一阶条件 1.5p = 5p(1−F(g)) 给出（§3）。
 [执行] 逐槽滚动 MPC：当前槽用**实测**净需求，未来槽用**该时刻最新一档预报**；
        目标 = Σ5p·e·Δt + λ·(末端SOC)。逐槽提交 (c,d)，按实测双向限幅，缺多少买多少
        紧急电。**结算一律用实测执行轨迹**，报出的数真能实现。

 λ 是储能跨日影子价格（元/kWh），不是硬约束。把日末 SOC 钉回当日起点是自指的，会让 SOC
 单向棘轮下滑到下限后电池全年瘫痪（问题 2 实测 18.19M→32.8M）。λ 是线性末端价值函数
 （Benders 意义下的割）；跨日加总后 λ 项自动抵消，年费只由 Σp·ĝ + Σ5p·e 决定，λ 只负责
 把储能分配到正确的日子。

════════════════════════════════════════════════════════════════════════════
§3  第二问（"是否需要引入其他时刻的预报"）的机理解剖
════════════════════════════════════════════════════════════════════════════
设 need_t 为该槽电池放完后的残余缺口，ĝ 已在 0:00 定死。在 e 档时刻把该块购电量调成 g：
    多买 1 kWh（g>ĝ）：付 1.5p；少买 1 kWh：付 0.5p 且毫无收益（p·ĝ 已照付）⇒ 永不下调
    多买 1 kWh 少买 1 kWh 紧急电：省 5p，概率 P(need>g | 该档预报)
  ⇒ 一阶条件 1.5p = 5p·P(need>g|预报) ⇒ **P(need>g|预报) = 0.3**，即 g = Q₀.₇(need|预报)。
ĝ 是 0:00 档条件下的 Q₀.₈，g 是 e 档条件下的 Q₀.₇。e 档预报越差（报出的 need 越高），
Q₀.₇(need|e档) 越可能超过 ĝ ⇒ 调整通道被激活。**调整的价值直接由附件 3 各档的预报精度
决定。** 实测 RMSE 矩阵（净需求 kW，2/1–12/31，各档只在其覆盖时段评）：

    档            00:00起6h   06:00起6h   12:00起6h   18:00起6h
    附件3+历史负荷   250.7       343.3       328.9       301.6
    同星期几持续性   250.8       687.7       676.9       299.6

  ⇒ 0:00 档与"同星期几持续性"打平（无增量）；6:00 与 12:00 档把误差砍半；18:00 档相对
    当日 0:00 档亦无增量。故第二问应按**档位分开回答**。v3 用 P4_BANDS 分别报：
    BANDS=0（只用 0:00 档）／1（+6:00）／2（+12:00）／3（+18:00）四条线的费用差。

════════════════════════════════════════════════════════════════════════════
用法
════════════════════════════════════════════════════════════════════════════
    python 代码/problem4_3.py                  # 全年，扫 λ
    P4_LAM=0.6 python 代码/problem4_3.py       # 单一 λ
    P4_ADJ=0 python 代码/problem4_3.py         # 关掉调整通道
    P4_BANDS=0/1/2/3                            # 允许的最高档位
    P4_DAYS=60 python 代码/problem4_3.py       # 只跑前 60 天（计时）
    P4_SENT=0 python 代码/problem4_3.py        # 跳过哨兵（哨兵较慢）
    P4_READING=A python 代码/problem4_3.py     # 读法 A（0:00 已知实际电价）→ 下界
    P4_WQ=0 python 代码/problem4_3.py          # 关掉电价加权分位（退回普通分位）
    P4_PRICE_SRC=att1 python 代码/problem4_3.py  # 回归自检：须复现 result3.xlsx
"""
import datetime as dt
import os
import sys
import time

import numpy as np
import openpyxl
import pandas as pd
from scipy.optimize import linprog
from scipy import sparse

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

# ════════════════════════════════════════════════════════════════════════
# 参数
# ════════════════════════════════════════════════════════════════════════
DT = 1.0 / 6.0
ETA = 0.9
P_MAX = 5000.0
# 购电功率上界。⚠ 题面（附录 1）**只给了储能 5000 kW 的充放电功率上限**，并没有给
# 微网与外网联络线的容量。缺省取 P_MAX 是**自加的保守假设**（与储能同量级），它对
# 计划层是实质约束：低价时段要把电池顶到 5000 kW 满充、同时负载也在用电，就需要
# g = 净负荷 + 5000 kW > 5000 kW。按字面读法放开上界：P4_GMAX=inf。
G_MAX = float(os.environ.get("P4_GMAX", P_MAX))
# ── 问题 4 新增：电价读法与联合加权分位 ────────────────────────────────
# READING="B"（主模型）：0:00 不知道当天实际电价，计划层只能用公布的分时电价剖面
#                       price_day（= 附件1）；价格不确定性由**加权分位**承载（见 WQ）。
# READING="A"（下界）  ：0:00 已知全天实际电价 PR[d]，计划层直接用实际价。
READING = os.environ.get("P4_READING", "B").strip().upper()
assert READING in ("A", "B"), f"P4_READING 只能是 A 或 B，实得 {READING!r}"
# 加权分位开关：对历史残差取分位时，用**该历史日同日同槽的实际电价**作权重。
# 动机：日水平因子 a_d 与日均净负荷 corr=0.982，缺口大的日子电价系统性更高，
#       按电价加权应把分位往上推（有效紧急边际成本更高）。
# ⚠ 实测**负结果**，故缺省关闭（P4_WQ=0）：
#     读法B G≤5000  WQ=0 τ=0.80 → 15,443,245（最优）
#                   WQ=1 τ=0.80 → 15,455,826   紧急 −6.3% 但计划 +65,429，净亏 12,581
#                   WQ=1 重扫 τ（最优 0.78）→ 15,453,379，仍输 10,134
#   机理在数据里真实存在，但换算不成收益：τ=0.80 本就是扫出来的经验最优值，
#   再加权等于重复计数；且储能的削峰作用把两侧代价差削平了。
#   保留为机理探针，论文按负结果如实报出。
WQ = bool(int(os.environ.get("P4_WQ", 0)))
SOC_MIN = 1200.0
SOC_MAX = 10800.0
SOC0 = 6000.0
N = 144
NDAYS = 365
REPORT = 31
S_HOUR = [0, 6, 12, 18]
BLOCKS = [(0, 36), (36, 72), (72, 108), (108, 144)]

# τ' 是**调整层**的分位（6/12/18 档把后续时窗的目标净需求抬到哪一分位）。缺省 0.55 是
# 实测定稿值：见 §调参。注意它远高于纯理论值 1/3 —— 因为 1.5p 的上调本身是在**不完美
# 预报**下做的，理论临界比只对"确定能买到"成立。
TAUP = float(os.environ.get("P4_TAUP", 0.55))
# 分块临界分位 [0:00块, 6:00块, 12:00块, 18:00块]。缺省 (0.80, 0.55, 0.55, 0.55) 是定稿值。
# 0:00–6:00 那一块**不可调整**（6:00 档发布前已执行完），缺口只能用 5p 紧急购电补，
# 故临界比 = 4p/(4p+p) = 0.80；后三块可用 1.5p 上调兜底，临界比低得多。
# 用全天单一 τ 会把这个结构差别抹平，正是单一 τ 下总费在 0.65–0.70 压成平台的原因。
TAU_B = [float(x) for x in os.environ.get("P4_TAUB", "").split(",")] if os.environ.get("P4_TAUB") \
    else [0.80, 0.55, 0.55, 0.55]
# ⚠ P4_TAU 是 TAU_B[0] 的**简写旋钮**（只扫 0:00 块那一个分位，实际调参中最常用）。
#   历史坑：早期版本里 TAU 是一个**从未接入模型**的独立变量，只在日志里打印，
#   于是扫 P4_TAU 会得到 13 个一字不差的总费却毫无报错 —— 一个静默的假阴性。
#   现在它直接改写 TAU_B[0]，扫它必然生效；TAU 这个名字保留为 TAU_B[0] 的别名，
#   使日志里打印的 τ 与真正进入模型的值恒等。
if os.environ.get("P4_TAU"):
    TAU_B[0] = float(os.environ["P4_TAU"])
assert len(TAU_B) == 4, "P4_TAUB 需给 4 个数"
TAU = TAU_B[0]                  # 仅供打印/诊断引用，恒等于模型真正使用的 0:00 块分位
# λ 只在 EXEC="mpc"（自解执行）下起作用；缺省 EXEC="plan"（跟随计划充放电）时
# 执行轨迹由 plan_day 的 LP 唯一确定，λ 完全不进模型 ⇒ 扫多个 λ 只会得到同一串数。
LAMS = [float(x) for x in os.environ.get("P4_LAMS", "1.0").split(",")]
LAM_SET = os.environ.get("P4_LAM")
ADJ = bool(int(os.environ.get("P4_ADJ", 1)))
LEVEL = bool(int(os.environ.get("P4_LEVEL", 1)))   # 调整层是否做"已发生比值"水平校正
BANDS = int(os.environ.get("P4_BANDS", 3))
NDAYS_RUN = int(os.environ.get("P4_DAYS", NDAYS))
MINR = int(os.environ.get("P4_MINR", 14))
MPC_RES = int(os.environ.get("P4_RES", 1))
H_MAX = int(os.environ.get("P4_H", 144))
DO_SENT = bool(int(os.environ.get("P4_SENT", 1)))
DO_WRITE = bool(int(os.environ.get("P4_WRITE", 1)))   # 跑完把最优配置写 结果/result4-3.xlsx
PLAN = os.environ.get("P4_PLAN", "lp")      # "lp" = 日前套利 LP ｜ "quant" = 追负荷分位规则
EXEC = os.environ.get("P4_EXEC", "plan")    # "plan" = 跟随计划充放电 ｜ "mpc" = 只收 ĝ 自己重解

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ════════════════════════════════════════════════════════════════════════
# 数据
# ════════════════════════════════════════════════════════════════════════
price_day = pd.read_excel(os.path.join(BASE, "附件", "附件1.xlsx")).iloc[:, 1].to_numpy(float)
load = pd.read_excel(os.path.join(BASE, "附件", "附件2.xlsx"),
                     sheet_name="小区负载").iloc[:, 1:1 + N].to_numpy(float)
pv = pd.read_excel(os.path.join(BASE, "附件", "附件2.xlsx"),
                   sheet_name="光伏发电实际功率").iloc[:, 1:1 + N].to_numpy(float)
fc3 = pd.read_excel(os.path.join(BASE, "附件", "附件3.xlsx"), header=None) \
        .iloc[1:, 2:].to_numpy(float).reshape(NDAYS, 4, 24)

actual_net = load - pv

# ── 问题 4：两个价格向量，分工不可混用（详见模块 docstring）──────────────
# price      = 外网**公布**的分时电价剖面（附件1），计划层的价格预期
# PR         = **实际结算**电价（附件4），逐日逐槽波动
# price_real = PR 的展平版，供按全局槽号切片
PR = pd.read_excel(os.path.join(BASE, "附件", "附件4.xlsx")) \
       .iloc[:, 1:1 + N].to_numpy(float)
assert PR.shape == (NDAYS, N), f"附件4 形状应为 (365, 144)，实得 {PR.shape}"
if os.environ.get("P4_PRICE_SRC", "att4").strip().lower() == "att1":
    PR = np.tile(price_day, (NDAYS, 1))     # 回归自检：退回常数价，须复现 result3.xlsx
price = np.tile(price_day, NDAYS)
# PSCALE 是价格整体缩放旋钮，用于论文敏感性一节（文献 3 规范：±30%、5% 步长）。
# 它加在**实际结算价向量 PR 上**：本文件有 7 个价格进入点（见模块 docstring），
# 其中读法 A 的计划层、day_fee 的按日价、加权分位都直接读 PR，只缩放 price_real
# 会漏掉它们。只缩放 PR 而不缩放附件1 的计划层预期，是为了让「读法 B 下 0:00
# 价格未知」这一结构在扰动中保持不变。
PSCALE = float(os.environ.get("P4_PSCALE", 1.0))
PR = PR * PSCALE
price_real = PR.ravel()


def wquantile(v, w, q, axis=0):
    """按权重 w 对 v 取 q 分位（沿 axis）。WQ=0 或缺权重时退化为普通分位。

    实现：按 v 排序后取加权 CDF 首次达到 q 的位置（线性插值）。
    """
    if not WQ:
        return np.quantile(v, q, axis=axis)
    v = np.asarray(v, float); w = np.asarray(w, float)
    if v.ndim == 1:
        v = v[:, None]; w = w[:, None]
    o = np.argsort(v, axis=0)
    vs = np.take_along_axis(v, o, axis=0)
    ws = np.take_along_axis(w, o, axis=0)
    cw = np.cumsum(ws, axis=0)
    totw = cw[-1]
    tgt = q * totw
    idx = np.argmax(cw >= tgt, axis=0)          # 首个加权 CDF ≥ q 的位置
    out = vs[idx, np.arange(v.shape[1])]
    # 全零权重（理论上不会出现）时退回普通分位
    bad = ~np.isfinite(totw) | (totw <= 1e-12)
    if np.any(bad):
        out = np.where(bad, np.quantile(v, q, axis=0), out)
    return out

Wm = np.zeros((N, 25))
for k in range(N):
    t = (k + 1) / 6.0
    lo = int(np.floor(t)); hi = min(int(np.ceil(t)), 24)
    if lo == hi:
        Wm[k, lo] = 1.0
    else:
        Wm[k, lo] = 1.0 - (t - lo); Wm[k, hi] = t - lo


def pv_fc(d, s):
    """第 d 天第 s 档（0/6/12/18 时发布）预报的当日 144 槽光伏。

    `预报k小时` = 发布后第 k 小时 ⇒ H[h] = fc3[d,s,h−s_hour−1]，h ≥ s_hour+1。
    跨到次日的部分被更晚发布的同目标档位支配，丢弃无损（实测见 §3）。
    """
    H = np.zeros(25)
    if S_HOUR[s] > 0:
        H[S_HOUR[s]] = pv[d, 6 * S_HOUR[s]]
    for h in range(S_HOUR[s] + 1, 25):
        H[h] = fc3[d, s, h - S_HOUR[s] - 1]
    return H @ Wm.T


P_hat = np.stack([[pv_fc(d, s) for s in range(4)] for d in range(NDAYS)])    # (365,4,144)

K_PEERS = 4                             # 同星期几情景数（L_base 已改用分组，此处仅留作对照）
GRP_SPAN = int(os.environ.get("P4_GSPAN", 7))      # 分组回看窗口（天）
GRP_TRAIN = int(os.environ.get("P4_GTRAIN", REPORT))


def low_demand_dows(train_days):
    """从 train_days 推断「低需求日」：日均净负荷最低的两个星期几。只喂暖机期，无前视。"""
    nl = (load - pv).sum(axis=1)
    dow = np.array([d % 7 for d in range(NDAYS)])
    means = [nl[train_days][dow[train_days] == k].mean() for k in range(7)]
    order = np.argsort(means)
    return (int(order[0]), int(order[1]))


# ⚠ L_base 口径 = problem3_v3.py 定稿（低需求日分组 {Fri,Sat}，回看 7 天），
#   不是本文件早先的「同星期几 K=4」。换口径的理由与实测见 文档/问题4_求解归档.md：
#   换基线前 problem4_3 与 result3.xlsx 逐元素相同，换基线后必须同步移植才能保住
#   那条交叉验证。span=7 取 P3 定稿值 —— P3 实测 span6 比 span7 贵 32,095（14,317,826
#   vs 14,285,731），因为低需求日只剩 1 个样本、情景均线形状失真，故 P3 不能用 6。
#   本文件的残差那一路不受影响：net_hist 是逐日累积的全历史池，已等价于 P3_HSRC="all"。
GRP_DOWS = low_demand_dows(np.arange(0, GRP_TRAIN))
_gm = np.array([(d % 7) in GRP_DOWS for d in range(NDAYS)])

L_base = np.zeros_like(load)
for d in range(NDAYS):
    idx = [t for t in range(max(0, d - GRP_SPAN), d) if _gm[t] == _gm[d]]
    L_base[d] = load[idx].mean(axis=0) if idx else load.mean(axis=0)

F_hat = L_base[:, None, :] - P_hat      # (365,4,144)
WIN0 = min(REPORT, NDAYS_RUN)
WIN = np.zeros(NDAYS * N, dtype=bool)
WIN[WIN0 * N:NDAYS_RUN * N] = True


# ════════════════════════════════════════════════════════════════════════
# 哨兵：完美预见全年 LP（口径 A）
# ════════════════════════════════════════════════════════════════════════
def sentinel(ndays=None):
    nd = ndays or NDAYS
    T = nd * N
    GH, G, C, D, S, E, AP, AN = 0, T, 2 * T, 3 * T, 4 * T, 5 * T + 1, 6 * T + 1, 7 * T + 1
    nv = AN + T
    net = actual_net.ravel()[:T]
    # 哨兵是完美预见：价格与负荷都已知，故必须用**实际结算价**最小化，
    # 否则它不是一个真下界，下面的 assert 就会失去意义。
    pr = price_real[:T]
    t = np.arange(T)

    obj = np.zeros(nv)
    obj[GH:GH + T] = pr * DT
    obj[E:E + T] = 5.0 * pr * DT
    obj[AP:AP + T] = 1.5 * pr * DT
    obj[AN:AN + T] = 0.5 * pr * DT

    rows, cols, vals = [], [], []

    def add(r, c, v):
        r = np.atleast_1d(r); v = np.atleast_1d(v)
        rows.append(np.full(len(v), r[0]) if len(r) == 1 else r)
        cols.append(np.atleast_1d(c)); vals.append(v)

    # 等式
    r_eq, c_eq, v_eq = [], [], []

    def eadd(r, c, v):
        r_eq.append(np.atleast_1d(r)); c_eq.append(np.atleast_1d(c)); v_eq.append(np.atleast_1d(v))

    eadd(0, [S], [1.0])
    eadd(1 + t, S + t + 1, np.ones(T))
    eadd(1 + t, S + t, -np.ones(T))
    eadd(1 + t, C + t, -ETA * DT * np.ones(T))
    eadd(1 + t, D + t, (DT / ETA) * np.ones(T))
    eadd(1 + T, [S + T], [1.0])
    eadd(1 + T + 1 + t, AN + t, np.ones(T))
    eadd(1 + T + 1 + t, AP + t, -np.ones(T))
    eadd(1 + T + 1 + t, G + t, np.ones(T))
    eadd(1 + T + 1 + t, GH + t, -np.ones(T))
    bl = np.arange(*BLOCKS[0])
    eadd(2 * T + 2 + np.arange(len(bl)), G + bl, np.ones(len(bl)))
    eadd(2 * T + 2 + np.arange(len(bl)), GH + bl, -np.ones(len(bl)))
    n_eq = 2 * T + 2 + len(bl)
    A_eq = sparse.coo_matrix(
        (np.concatenate(v_eq), (np.concatenate(r_eq), np.concatenate(c_eq))),
        shape=(n_eq, nv)).tocsr()
    b_eq = np.concatenate([[SOC0], np.zeros(T), [SOC0], np.zeros(T), np.zeros(len(bl))])

    # 不等式
    r1 = t; r2 = T + t
    r_ub = np.concatenate([r1, r1, r1, r2, r2, r2])
    c_ub = np.concatenate([C + t, G + t, D + t, G + t, D + t, E + t])
    v_ub = np.concatenate([np.ones(T), -np.ones(T), -np.ones(T),
                           -np.ones(T), -np.ones(T), -np.ones(T)])
    A_ub = sparse.coo_matrix((v_ub, (r_ub, c_ub)), shape=(2 * T, nv)).tocsr()
    b_ub = np.concatenate([-net, -net])

    lo = np.zeros(nv); hi = np.full(nv, np.inf)
    hi[C:C + T] = P_MAX; hi[D:D + T] = P_MAX; hi[G:G + T] = G_MAX
    lo[S:S + T + 1] = SOC_MIN; hi[S:S + T + 1] = SOC_MAX

    r = linprog(obj, A_eq=A_eq, b_eq=b_eq, A_ub=A_ub, b_ub=b_ub,
                bounds=list(zip(lo, hi)), method="highs")
    if not r.success:
        print(f"  [哨兵] LP 失败：{r.message}")
        return None
    x = r.x
    w = slice(WIN0 * N, nd * N)
    return dict(
        total=(pr * x[GH:GH + T] * DT)[w].sum()
        + (1.5 * pr * x[AP:AP + T] * DT)[w].sum()
        + (0.5 * pr * x[AN:AN + T] * DT)[w].sum()
        + (5.0 * pr * x[E:E + T] * DT)[w].sum(),
        plan=(pr * x[GH:GH + T] * DT)[w].sum(),
        excess=(1.5 * pr * x[AP:AP + T] * DT)[w].sum(),
        breach=(0.5 * pr * x[AN:AN + T] * DT)[w].sum(),
        emerg=(5.0 * pr * x[E:E + T] * DT)[w].sum(),
        kwh_em=(x[E:E + T] * DT)[w].sum(),
        kwh_g=(x[G:G + T] * DT)[w].sum(),
    )


# ════════════════════════════════════════════════════════════════════════
# 执行层：逐槽滚动 MPC
# ════════════════════════════════════════════════════════════════════════
def mpc(netf, g, pp, soc, lam, s_ref=SOC0):
    """当前槽的 MPC。netf[0] 是实测净需求，netf[1:] 是最新一档预报。

    末端价值用**在参考水位 s_ref 处饱和**的分段线性函数 λ·min(s_H, s_ref)（用辅助变量 u
    线性化）。理由：线性 λ·s_H 是 bang-bang 的 —— 只要 λ>0，电池就把全年富余吃干、顶在
    SOC_MAX 上不下来（实测年末 SOC 10,202 kWh），而 λ=0 又一路放空到 1200。饱和段表示
    "超过参考水位的那部分电是迟早要弃掉的富余，边际价值为零"，正好把年轨迹钉在参考水位
    附近。标量 λ 无法同时表达"留住电量"与"用掉电量"，这是本项目已确认的负结果，故这里
    退一步用饱和价值并如实报出敏感性，不声称它是最优价值函数。
    """
    H = len(netf)
    C0, D0, S0, E0 = 0, H, 2 * H, 3 * H + 1
    U = E0 + H
    nv = U + 1
    obj = np.zeros(nv)
    obj[E0:E0 + H] = 5.0 * pp * DT
    obj[U] = -lam            # 负号 = 奖励留存，别写反（写正会把电池一路放空）
    i = np.arange(H)

    r_eq = np.concatenate([np.zeros(1, int), 1 + i, 1 + i, 1 + i, 1 + i])
    c_eq = np.concatenate([np.array([S0]), S0 + i + 1, S0 + i, C0 + i, D0 + i])
    v_eq = np.concatenate([np.ones(1), np.ones(H), -np.ones(H),
                           -ETA * DT * np.ones(H), (DT / ETA) * np.ones(H)])
    A_eq = sparse.coo_matrix((v_eq, (r_eq, c_eq)), shape=(H + 1, nv)).tocsr()
    b_eq = np.concatenate([[soc], np.zeros(H)])

    # 充电只吃富余：c_j − d_j ≤ g_j − netf_j
    # 负载必须供上：d_j + e_j ≥ netf_j − g_j  ⇔  −d_j − e_j ≤ g_j − netf_j
    # u ≤ s_H（末端价值饱和）
    # ⚠ g 是外生参数，只进右端项。曾把它当变量塞进第 3 列，D+j 在同一行出现两次被 COO
    #   就地累加成 −2d_j、且 −g 系数落空 ⇒ LP 不可行。两行的右端项恰好相同。
    r_ub = np.concatenate([i, i, H + i, H + i, [2 * H, 2 * H]])
    c_ub = np.concatenate([C0 + i, D0 + i, D0 + i, E0 + i, [U, S0 + H]])
    v_ub = np.concatenate([np.ones(H), -np.ones(H), -np.ones(H), -np.ones(H),
                           [1.0, -1.0]])
    A_ub = sparse.coo_matrix((v_ub, (r_ub, c_ub)), shape=(2 * H + 1, nv)).tocsr()
    b_ub = np.concatenate([g - netf, g - netf, [0.0]])

    lo = np.zeros(nv); hi = np.full(nv, np.inf)
    hi[C0:C0 + H] = P_MAX; hi[D0:D0 + H] = P_MAX
    lo[S0:S0 + H + 1] = SOC_MIN; hi[S0:S0 + H + 1] = SOC_MAX
    hi[U] = s_ref
    r = linprog(obj, A_eq=A_eq, b_eq=b_eq, A_ub=A_ub, b_ub=b_ub,
                bounds=list(zip(lo, hi)), method="highs")
    if not r.success:
        return 0.0, 0.0
    return r.x[C0], r.x[D0]


def exec_day(d, g_day, lam, soc):
    """执行第 d 天。返回 (c, d, e, g, soc_end)。结算口径为实测轨迹。"""
    c_a = np.zeros(N); d_a = np.zeros(N); e_a = np.zeros(N)
    net_d = actual_net[d]
    # MPC 窗口的紧急电价系数：读法 A 下当天电价已知（用 PR[d]）；读法 B 下只能用
    # 公布剖面作为预期。⚠ 这一处只影响 MPC 的充放电安排，不改账本（计划购电费在
    # run() 结算层按全额 ĝ 另计），所以它错了是**隐蔽错误**，必须与读法保持一致。
    pr_d = PR[d] if READING == "A" else price_day
    nplan = 0.0
    for t in range(N):
        if t % MPC_RES == 0:
            epo = t // 36
            epo = min(epo, 3)
            H = min(H_MAX, N - t)
            netf = np.empty(H)
            netf[0] = net_d[t]
            if H > 1:
                netf[1:] = F_hat[d, epo, t + 1:t + H]
            c_p, d_p = mpc(netf, g_day[t:t + H], pr_d[t:t + H], soc, lam)
            # 本次重解覆盖到下一个重解点
            seg = min(MPC_RES, N - t)
            c_seg = np.full(seg, c_p); d_seg = np.full(seg, d_p)
        j = t % MPC_RES
        c_t = c_seg[j]; d_t = d_seg[j]

        d_t = min(d_t, max(0.0, (soc - SOC_MIN) * ETA / DT))
        d_t = max(0.0, d_t)
        c_t = min(c_t, max(0.0, pv[d, t] + g_day[t] + d_t - load[d, t]),
                  max(0.0, (SOC_MAX - soc) / (ETA * DT)))
        c_t = max(0.0, c_t)
        e_t = max(0.0, load[d, t] - g_day[t] - pv[d, t] - d_t)
        c_a[t], d_a[t], e_a[t] = c_t, d_t, e_t
        soc += (ETA * c_t - d_t / ETA) * DT
        nplan += d_t * DT
    return c_a, d_a, e_a, soc


def exec_plan(d, gh, c0, d0, soc):
    """按日前计划执行：(c, d) 取计划值，受物理限幅；计划放得不够则补放，不让负载掉线。

    为什么执行器必须跟随计划的 (c, d)，而不能只收 ĝ 自己重解
    ──────────────────────────────────────────────────────
    计划层的 ĝ 与 (c, d) 是**同一个 LP 联合**解出来的：ĝ 之所以在正午买到 P_MAX、
    在晚高峰压到 0，正是因为那里的电池会存、会放。只把 ĝ 交给一个目标为
    `min 5p·e − λ·u` 的 MPC 重解充放电，等于把联合最优解拆成两半 —— 实测同一 ĝ 下
    MPC 只兑现了一半充放电量，紧急购电从 0 涨到 251,557 kWh（29 天）。

    `补放` 不是可选项：电池里明明有电、计划却没安排放，让负载掉线去付 5 倍紧急电价，
    在任何口径下都是纯亏。补放严格优于放弃，故恒开。
    """
    c_a = np.zeros(N); d_a = np.zeros(N); e_a = np.zeros(N)
    for t in range(N):
        d_max = max(0.0, (soc - SOC_MIN) * ETA / DT)
        d_t = min(max(d0[t], 0.0), d_max)
        if load[d, t] - gh[t] - pv[d, t] - d_t > 0.0:      # 计划放得不够 → 补放到物理上限
            d_t = min(max(0.0, load[d, t] - gh[t] - pv[d, t]), d_max)
        c_t = min(max(c0[t], 0.0),
                  max(0.0, pv[d, t] + gh[t] + d_t - load[d, t]),   # 充电只吃富余
                  max(0.0, (SOC_MAX - soc) / (ETA * DT)))          # SOC 上限
        c_t = max(0.0, c_t)
        e_t = max(0.0, load[d, t] - gh[t] - pv[d, t] - d_t)
        c_a[t], d_a[t], e_a[t] = c_t, d_t, e_t
        soc += (ETA * c_t - d_t / ETA) * DT
    return c_a, d_a, e_a, soc


# ════════════════════════════════════════════════════════════════════════
# 主循环：因果在线
# ════════════════════════════════════════════════════════════════════════
def plan_day(soc_in, Nt, pr, soc_end=None):
    """日前计划 LP（口径 A）：整日 ĝ 与储能充放电**联合**优化，日末 SOC 回到起点。

    为什么必须有这一层
    ──────────────────
    口径 A 下 `p·ĝ` 全额付费、与实收无关，于是**购电的时序本身就是钱**。题面开篇
    即写明储能的经济动机："在外部电网电价较低……的时间段为储能设备充电，并在外网
    电价较高的时间段释放电能"。要让电池在低价段充电，计划就必须在低价段**多买**，
    即 `ĝ_t > 净需求_t`。

    早先的实现用 `ĝ = F̂ + 分位` 的追负荷规则，购电永远贴着净需求走，执行器又受
    `c ≤ g + P − L` 约束（充电只能吃富余），于是电池拿不到任何可存的富余。实测全年
    买 21.4M kWh、均价 0.781 元/kWh（正是净需求自身的电价加权均价），而完美预见的
    哨兵只花 0.616 —— 差出来的约 180 万元全在这一条约束上，与预报精度无关。

    模型
    ────
        min  Σ p_t·ĝ_t·Δt + 5p_t·e_t·Δt
        s.t. s_{t+1} = s_t + (η·c_t − d_t/η)·Δt        （SOC 动力学）
             c_t − d_t ≤ ĝ_t − N_t                      （充电只吃富余）
             d_t + e_t ≥ N_t − ĝ_t                      （负荷必须供上）
             s_0 = soc_in,  s_T = soc_end               （默认 soc_end = 6000）
             ĝ, c, d ∈ [0, P_MAX]   s ∈ [SOC_MIN, SOC_MAX]   e ≥ 0

    日末 SOC 用**显式等式**钉住，而不是给一个标量影子价格 λ —— λ 的值函数是 bang-bang
    的（λ=0 一路放空、λ>0 一路充满），无法同时表达"留住电量"与"用掉电量"。

    末点取 6000（题面附录 1 的初值、也是本队问题 1 的约定）而非当日起点，是为了让
    SOC 有**回归力**。执行期的限幅与补放会带来每天约 −5 kWh 的净泄漏；若末点钉回当天
    起点，泄漏就无人补偿，SOC 只能单向滑向下限 —— 实测全年触底 1200 后电池瘫痪，
    最后 1/3 年全靠紧急购电。钉回 6000 后计划每天主动把 SOC 拉回，泄漏被吸收。

    ⚠ 与问题 2 同源的保留：s_T = 6000 是**自加假设**（题面只要求问题 1 的 0:00/24:00
    相同），它给套利幅度设了上限，须声明并做敏感性。

    参数：soc_in 当日 0:00 储电量；Nt (144,) 计划依据的净需求目标 = F̂ + 分位缓冲；
          pr (144,) 当日分时电价；soc_end 日末 SOC 目标。返回 (gh, c, d, s) 或 None。
    """
    T = N
    GH, C, D, S, E = 0, T, 2 * T, 3 * T, 4 * T + 1
    nv = E + T

    obj = np.zeros(nv)
    obj[GH:GH + T] = pr * DT
    obj[E:E + T] = 5.0 * pr * DT

    # SOC 等式（T+1 行，互相独立）：
    #   第 0 行   s_0 = soc_in
    #   第 1..T−1 行动力学递推，逐行显式构造 —— COO 会把同一 (行, 列) 上的重复项
    #              **就地累加**，用花式索引偷懒会让 s_i 变成系数 2。
    #   第 T 行   日能量中性 Σ(η·c_t − d_t/η)·Δt = 0
    # 状态变量只设 s_0..s_{T−1}：末点由中性行**在 c/d 上**强制，不必再占一个变量
    # （曾把 s_T 放进来，它不进任何等式 ⇒ 悬空，读出来恒为下界 1200，看着像"没回起点"）。
    # ⚠ 中性行不能省。早先只写动力学（覆盖到 s_{T−1}），末点不受任何约束，LP 每天把
    #   电池放到 1,200 就算收工 → 计划永不回到起点 → 逐日棘轮下滑，执行器随后全天挨饿
    #   （实测紧急购电从 547 kWh 炸到 309,565 kWh）。
    i = np.arange(1, T)
    j = np.arange(T)
    r_eq = np.concatenate([[0], i, i, i, i, np.full(T, T), np.full(T, T)])
    c_eq = np.concatenate([[S], S + i, S + i - 1, C + i - 1, D + i - 1,
                           C + j, D + j])
    v_eq = np.concatenate([[1.0], np.ones(T - 1), -np.ones(T - 1),
                           -ETA * DT * np.ones(T - 1), (DT / ETA) * np.ones(T - 1),
                           ETA * DT * np.ones(T), -(DT / ETA) * np.ones(T)])
    A_eq = sparse.coo_matrix((v_eq, (r_eq, c_eq)), shape=(T + 1, nv)).tocsr()
    se = soc_in if soc_end is None else soc_end
    b_eq = np.zeros(T + 1); b_eq[0] = soc_in; b_eq[T] = se - soc_in

    # 不等式分两个**不同的行块**（0..T−1 充电、T..2T−1 供载）。若两块共用行号，
    # D+j 会在同一行出现两次被累加成 −2d_j，且 −ĝ 系数落空 ⇒ LP 不可行。
    r_ub = np.concatenate([j, j, j, T + j, T + j, T + j])
    c_ub = np.concatenate([C + j, D + j, GH + j, D + j, E + j, GH + j])
    v_ub = np.concatenate([np.ones(T), -np.ones(T), -np.ones(T),
                           -np.ones(T), -np.ones(T), -np.ones(T)])
    A_ub = sparse.coo_matrix((v_ub, (r_ub, c_ub)), shape=(2 * T, nv)).tocsr()
    b_ub = np.concatenate([-Nt, -Nt])

    lo = np.zeros(nv); hi = np.full(nv, np.inf)
    hi[GH:GH + T] = G_MAX; hi[C:C + T] = P_MAX; hi[D:D + T] = P_MAX
    lo[S:S + T] = SOC_MIN; hi[S:S + T] = SOC_MAX

    r = linprog(obj, A_eq=A_eq, b_eq=b_eq, A_ub=A_ub, b_ub=b_ub,
                bounds=list(zip(lo, hi)), method="highs")
    if not r.success:
        return None
    # 末点按上面的能量等式回填：Σ(η·c − d/η)·Δt = se − soc_in ⇒ s_T = se
    return (r.x[GH:GH + T], r.x[C:C + T], r.x[D:D + T],
            np.append(r.x[S:S + T], se))


# ════════════════════════════════════════════════════════════════════════
# 主循环：因果在线
# ════════════════════════════════════════════════════════════════════════
def run(lam, ndays=None, verbose=False):
    nd = ndays or NDAYS_RUN
    need_hist = []              # 每日 (144,) 电池放完后的实际残余缺口（追负荷规则用）
    net_hist = []               # 每日 (144,) 毛净需求 L−P（套利计划用，见 h 的注释）
    g_hat = np.zeros((nd, N))
    g_fin = np.zeros((nd, N))
    c_all = np.zeros((nd, N)); d_all = np.zeros((nd, N)); e_all = np.zeros((nd, N))
    soc = SOC0
    soc_tr = []
    n_adj = 0
    for d in range(nd):
        # ---- 分位缓冲 h：贴在净需求目标上的可靠性垫层，与购电时序无关 ----
        # ⚠ 缓冲必须对准**毛净需求** L−P 的预报误差。曾用"电池放完后的残余缺口"来标定，
        #   在套利计划下等于把放电算了两遍（残余里已经扣过一次 d），计划据此少买 ⇒
        #   紧急购电暴涨（60 天 126,880 kWh）。残余口径只对"计划层不含电池"的追负荷
        #   规则成立 —— 见 PLAN="quant" 分支。
        if PLAN == "lp" or not need_hist:
            src = net_hist
        else:
            src = need_hist
        if len(src) >= MINR:
            H0 = np.array(src) - F_hat[:len(src), 0, :]
        else:
            H0 = actual_net[:max(d, 1)] - F_hat[:max(d, 1), 0, :]
        # 分位**按块取**：0:00–6:00 不可调整（顶补价 5p ⟹ 临界比 0.8），
        # 6:00 之后的块可用 1.5p 顶补（顶补价降到 1.5p ⟹ 临界比 0.5p/(0.5p+p)=1/3）。
        # 用全天单一 τ 会把这个差别抹平：τ 取低则 0:00 块欠买（只能按 5p 补救），
        # τ 取高则后三块过买 —— 这正是单一 τ 下总费在 0.65–0.70 压成平台的原因。
        h = np.zeros(N)
        if len(H0) > 0:
            for e in range(4):
                a, b = BLOCKS[e]
                # 问题 4：分位按**该历史日同日同槽的实际电价**加权（WQ=1）。
                # 报童的临界比是 c_u/(c_u+c_o)，而 c_u=4·E[p|缺口]、c_o=E[p|过剩]。
                # 附件4 里缺电的日子电价系统性更高（a_d 与日均净负荷 corr=0.982），
                # 于是 c_u/c_o 比"独立"假设下更大 ⇒ 同一个 τ 对应的 ĝ 应当更高。
                # 按电价加权分位正是这件事的样本实现：高价样本被推高权重，把分位向上抬。
                h[a:b] = wquantile(H0[:, a:b], PR[:len(H0), a:b], TAU_B[e])
        Nt = F_hat[d, 0, :] + h

        # ---- 调整目标：用 6/12/18 档的预报把后续时窗的目标净需求抬高 ----
        # ⚠ 只允许**上调**。口径 A 下 p·ĝ 已全额付清，下调 ĝ 一分钱也省不下来，反而
        #   要付 0.5p 违约费 ⇒ 下调在任何分位数下都不是最优。上调则是真金白银：
        #   高出 ĝ 的部分按 1.5p 计费。这条不对称正是口径 A 与 B 的分水岭。
        Nt_adj = Nt.copy()
        Nh = np.array(src) if src else np.zeros((0, N))
        if ADJ and len(src) >= MINR:
            for e in (1, 2, 3):
                if e > BANDS:
                    break
                a, b = BLOCKS[e]
                if LEVEL:
                    # 水平校正：预报误差里"整天整体偏高/偏低"那一支是强自相关的，
                    # 用当天已发生时段的【实测负荷 / 基准负荷】比值 r 直接测出来，
                    # 再按 r 缩放剩余时段的负荷预报。只取残差分位抓不到这一支 ——
                    # 实测这是 v3 相对归档最大的缺口（v2 的 solve_stage 有这个比值修正）。
                    den = L_base[d, :a].sum()
                    r = float(load[d, :a].sum() / den) if den > 1e-6 else 1.0
                    rd = L_base[:len(Nh), :a].sum(axis=1)
                    rp = np.where(rd > 1e-6,
                                  load[:len(Nh), :a].sum(axis=1) / np.maximum(rd, 1e-9), 1.0)
                    Ncor = r * L_base[d, a:b] - P_hat[d, e, a:b]
                    Rcor = (actual_net[:len(Nh), a:b]
                            - (rp[:, None] * L_base[:len(Nh), a:b] - P_hat[:len(Nh), e, a:b]))
                else:
                    Ncor = F_hat[d, e, a:b]
                    Rcor = Nh[:, a:b] - F_hat[:len(Nh), e, a:b]
                # 同 §计划层：调整层的分位也按该历史日的实际电价加权。
                Nt_adj[a:b] = np.maximum(Nt_adj[a:b],
                                         Ncor + wquantile(Rcor, PR[:len(Nh), a:b], TAUP))

        # ---- 计划 ĝ 与计划充放电 ----
        def _solve(target):
            """对给定目标解一次日前 LP，返回 (ĝ, c, d)。追负荷规则作兜底。"""
            if PLAN == "lp":
                # 计划层的价格系数：读法 B 用 0:00 能拿到的公布剖面；读法 A 用已知实际价。
                # plan_day 本来就按 pr 参数化（v3 只是每代都传同一条 price_day）。
                pl = plan_day(soc, target, PR[d] if READING == "A" else price_day, SOC0)
                if pl is not None:
                    return np.clip(pl[0], 0.0, G_MAX), pl[1], pl[2]
            return np.clip(target, 0.0, G_MAX), None, None

        gh, c_pl, d_pl = _solve(Nt)           # 0:00 的计划 —— 结算违约/超额的基准
        g_hat[d] = gh
        if ADJ and np.any(Nt_adj > Nt + 1e-9):
            gd, c_pl, d_pl = _solve(Nt_adj)   # 调整后的计划 —— 实际执行的就是它
            n_adj += 1
        else:
            gd = gh
        g_fin[d] = gd

        # ---- 执行 ----
        if c_pl is not None and EXEC == "plan":
            c_a, d_a, e_a, soc = exec_plan(d, gd, c_pl, d_pl, soc)
        else:
            c_a, d_a, e_a, soc = exec_day(d, gd, lam, soc)
        c_all[d], d_all[d], e_all[d] = c_a, d_a, e_a
        need_hist.append(actual_net[d] - d_a)
        net_hist.append(actual_net[d])
        soc_tr.append(soc)
        if verbose:
            print(f"    day {d + 1:>3d}  SOC止 {soc:>8,.0f}  "
                  f"紧急 {e_a.sum() * DT:>8,.0f} kWh", flush=True)

    # ---- 结算（口径 A，用实测轨迹） ----
    L = load.ravel()[:nd * N]; P = pv.ravel()[:nd * N]
    gh_f = g_hat.ravel(); gf_f = g_fin.ravel()
    c_f = c_all.ravel(); d_f = d_all.ravel(); e_f = e_all.ravel()
    pr = price_real[:nd * N]      # 结算永远用实际价 —— 唯一真正花钱的地方
    w = WIN[:nd * N]
    plan_fee = (pr * gh_f * DT)[w].sum()
    breach = (0.5 * pr * np.maximum(gh_f - gf_f, 0) * DT)[w].sum()
    excess = (1.5 * pr * np.maximum(gf_f - gh_f, 0) * DT)[w].sum()
    em_fee = (5 * pr * e_f * DT)[w].sum()
    # 真实逐槽 SOC 轨迹：由充放电唯一确定（exec_plan 与 plan_day 共用同一递推，
    # 实测重建的日末值与 soc_tr 逐日相符到 0.000000 kWh）。
    # ⚠ 报 SOC 区间**必须**用它。plan_day 把每日末端钉在 SOC0，日末序列只覆盖
    #   [2830, 6000]，看上去像电池没在全幅循环 —— 实际日内打满 [1200, 10800]。
    soc_full = np.concatenate([[SOC0], SOC0 + np.cumsum((ETA * c_f - d_f / ETA) * DT)])
    return dict(
        total=plan_fee + breach + excess + em_fee,
        plan=plan_fee, breach=breach, excess=excess, emerg=em_fee,
        kwh_gh=(gh_f * DT)[w].sum(), kwh_gf=(gf_f * DT)[w].sum(),
        kwh_em=(e_f * DT)[w].sum(), kwh_c=(c_f * DT)[w].sum(),
        kwh_d=(d_f * DT)[w].sum(), n_adj=n_adj,
        soc_end=soc, soc_min=float(soc_full.min()), soc_max=float(soc_full.max()),
        soc_day_min=float(np.min(soc_tr)), soc_day_max=float(np.max(soc_tr)),
        freq_em=float((e_f[w] > 1e-9).mean()),
        g_hat=g_hat, g_fin=g_fin, c=c_all, d=d_all, e=e_all,
        # 逐日**日末** SOC（长度 nd）；写盘器要的是每天的 0:00/24:00 储电量，
        # 0:00 那天取 SOC0，之后取前一日末值。轨迹只有日末才落盘，日内不落。
        soc_day=np.array(soc_tr, dtype=float), nd=nd,
    )


def show(tag, lam, r):
    if r is None:
        print(f"  {tag:12s} λ={lam:>5.2f}   —— LP 不可行")
        return
    print(f"  {tag:12s} λ={lam:>5.2f}  总 {r['total']:>13,.0f}  "
          f"计划 {r['plan']:>13,.0f}  违约 {r['breach']:>8,.0f}  "
          f"超额 {r['excess']:>10,.0f}  紧急 {r['emerg']:>11,.0f} "
          f"({r['kwh_em']:>8,.0f} kWh)  SOC止 {r['soc_end']:>7,.0f}  "
          f"[{r['soc_min']:>6,.0f},{r['soc_max']:>7,.0f}]  紧急频率 {r['freq_em']:.3f}")


# ════════════════════════════════════════════════════════════════════════
# 落盘：结果/result4-3.xlsx（沿用 附件5/result4-3.xlsx 模板）
# ════════════════════════════════════════════════════════════════════════
BLOCKS6 = [("0:00-4:00", 0, 24), ("4:00-8:00", 24, 48), ("8:00-12:00", 48, 72),
           ("12:00-16:00", 72, 96), ("16:00-20:00", 96, 120), ("20:00-24:00", 120, 144)]


def fmt_time(m):
    m = int(m)
    return "24:00" if m >= 1440 else f"{m // 60:02d}:{m % 60:02d}"


def emergency_segments(e_kwh):
    """把一天 144 个区间的紧急购电量(kWh)聚成连续时间段。"""
    segs, i = [], 0
    while i < N:
        if e_kwh[i] > 1e-6:
            j = i
            while j + 1 < N and e_kwh[j + 1] > 1e-6:
                j += 1
            segs.append((fmt_time(i * 10) + "-" + fmt_time((j + 1) * 10),
                         float(e_kwh[i:j + 1].sum())))
            i = j + 1
        else:
            i += 1
    return segs


def write_result4_3(r, out_path=None):
    """把 run() 的结果按 附件5/result4-3.xlsx 模板写盘。账本是**口径 A**。

    列约定与 problem2.py 一致：附件1 的 144 个槽位按【结束时刻】标号（"0:10-0:20"…），
    所以第 k 列（k 从 0 起）装 arr[(k+1) % N]。这是标签对齐，不是错位 —— 同一份约定
    在 problem2.py:355 / problem3_v2.py:850,862 里一致使用。

    口径 A 的每日费用，写在「计划购电量」「调整购电量」的「全天购电费」列：
        p·ĝ 全额  +  0.5p·(ĝ−g)⁺  +  1.5p·(g−ĝ)⁺  +  5p·e
    最优解上第一项罚金恒为 0（推论 1：g ≥ ĝ），保留该项是为了账本对任意轨迹都自洽、
    可拿去核任何一条实测轨迹（包括归档的旧轨迹）。

    ⚠ 两张购电量表的「全天购电费」都是**当天的全口径总费**（它们描述同一个物理日），
      读表只能取其一，**不可相加**。
    ⚠ 「计划购电量」的 144 个槽位是 ĝ（0:00 的承诺量），「调整购电量」是 g（实际执行量）。
      全天购电量列 = 本表 144 槽之和，故两表该列分别等于 Σĝ / Σg。
    """
    nd = r["nd"]
    g_hat = (r["g_hat"] * DT).reshape(nd, N)
    g_fin = (r["g_fin"] * DT).reshape(nd, N)
    c_day = (r["c"] * DT).reshape(nd, N)
    d_day = (r["d"] * DT).reshape(nd, N)
    e_day = (r["e"] * DT).reshape(nd, N)
    soc_mid = np.concatenate([[SOC0], r["soc_day"]])      # soc_mid[d] = 第 d 天 0:00 储电量

    def day_fee(di):
        p = PR[di]        # ⚠ 必须与实际结算（run 的 price_real[:nd*N]）同源，否则下面断言直接炸
        gh, gf, ed = g_hat[di], g_fin[di], e_day[di]
        return float((p * gh).sum()
                     + (0.5 * p * np.maximum(gh - gf, 0)).sum()
                     + (1.5 * p * np.maximum(gf - gh, 0)).sum()
                     + (5.0 * p * ed).sum())

    out_path = out_path or os.path.join(BASE, "结果", "result4-3.xlsx")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    wb = openpyxl.load_workbook(os.path.join(BASE, "附件", "附件5", "result4-3.xlsx"))
    # 计费窗口与 run() 结算用的 WIN 掩码严格同源，否则表内合计对不上 r["total"]。
    report_days = range(WIN0, min(nd, NDAYS_RUN))
    date0 = dt.date(2025, 1, 1)

    ws_p, ws_a = wb["计划购电量"], wb["调整购电量"]
    for j, di in enumerate(report_days):
        row = j + 2
        fee = day_fee(di)
        for k in range(N):
            ws_p.cell(row=row, column=2 + k).value = round(float(g_hat[di][(k + 1) % N]), 4)
            ws_a.cell(row=row, column=2 + k).value = round(float(g_fin[di][(k + 1) % N]), 4)
        ws_p.cell(row=row, column=2 + N).value = round(float(g_hat[di].sum()), 4)
        ws_a.cell(row=row, column=2 + N).value = round(float(g_fin[di].sum()), 4)
        ws_p.cell(row=row, column=3 + N).value = round(fee, 2)
        ws_a.cell(row=row, column=3 + N).value = round(fee, 2)

    ws_c = wb["充放电量"]
    ws_c.delete_rows(2, ws_c.max_row - 1)
    for j, di in enumerate(report_days):
        base = j * 6 + 2
        dv = date0 + dt.timedelta(days=di)
        for bj, (name, a, b) in enumerate(BLOCKS6):
            rr = base + bj
            ws_c.cell(row=rr, column=1).value = dv if bj == 0 else None
            ws_c.cell(row=rr, column=2).value = name
            ws_c.cell(row=rr, column=3).value = round(float(c_day[di][a:b].sum()), 4)
            ws_c.cell(row=rr, column=4).value = round(float(d_day[di][a:b].sum()), 4)
        ws_c.cell(row=base, column=5).value = "0:00"
        ws_c.cell(row=base, column=6).value = round(float(soc_mid[di]), 4)
        ws_c.cell(row=base + 1, column=5).value = "24:00"
        ws_c.cell(row=base + 1, column=6).value = round(float(soc_mid[di + 1]), 4)

    ws_e = wb["紧急购电量"]
    ws_e.delete_rows(2, ws_e.max_row - 1)
    rr = 2
    for di in report_days:
        ws_e.cell(row=rr, column=1).value = date0 + dt.timedelta(days=di)
        segs = emergency_segments(e_day[di])
        if segs:
            for tstr, kwh in segs:
                ws_e.cell(row=rr, column=2).value = tstr
                ws_e.cell(row=rr, column=3).value = round(kwh, 4)
                rr += 1
        else:
            ws_e.cell(row=rr, column=3).value = 0.0
            rr += 1

    wb.save(out_path)
    tot = sum(day_fee(di) for di in report_days)
    print(f"\n已写入 {out_path}")
    print(f"  计费窗口第 {report_days.start + 1}–{report_days.stop} 天，共 {len(report_days)} 天")
    print(f"  表内「全天购电费」合计 {tot:,.2f} 元 ｜ run() 结算 {r['total']:,.2f} 元 ｜ "
          f"差 {tot - r['total']:+,.4f}")
    assert abs(tot - r["total"]) < 1.0, "写盘费用与 run() 结算不一致 —— 窗口口径错位"
    return out_path


if __name__ == "__main__":
    print("=" * 118)
    print(f"问题 4（对应问题 3） · 口径 A · 波动电价   读法 {READING}   "
          f"电价加权分位 {'开' if WQ else '关'}   G_MAX={G_MAX:,.0f}")
    print(f"  计划分位 τ_块={TAU_B}  调整分位 τ'={TAUP}  调整通道={'开' if ADJ else '关'}  "
          f"最高可用档位 {BANDS}（0=0:00, 1=+6:00, 2=+12:00, 3=+18:00）")
    print(f"  天数 {NDAYS_RUN}  计费窗口第 {WIN0 + 1}–{NDAYS_RUN} 天  "
          f"MPC 重解间隔 {MPC_RES} 槽  时域 {H_MAX}")
    print("=" * 118)
    t0 = time.time()

    if DO_SENT:
        print("\n【哨兵】完美预见全年 LP（口径 A）")
        s = sentinel()
        if s:
            print(f"  总 {s['total']:>13,.0f} 元   计划 {s['plan']:>13,.0f}  "
                  f"超额 {s['excess']:>10,.0f}  违约 {s['breach']:>9,.0f}  "
                  f"紧急 {s['emerg']:>9,.0f}")
            print(f"  购电 {s['kwh_g']:>12,.0f} kWh  紧急 {s['kwh_em']:>10,.0f} kWh")
            print("  ⇒ 任何因果策略都不可能低于此值；报出低于它的数必是 bug。")
        print(f"  [{time.time() - t0:.0f}s]")

    print("\n【执行】因果在线：计划 → 6/12/18 调整 → 逐槽 MPC 执行")
    print("-" * 118)
    grid = {}
    if LAM_SET is not None:
        r = run(float(LAM_SET))
        grid[float(LAM_SET)] = r
        show("单点", float(LAM_SET), r)
    else:
        for lam in LAMS:
            r = run(lam)
            grid[lam] = r
            show("扫 λ", lam, r)
            print(f"               [{time.time() - t0:.0f}s]", flush=True)

    live = {k: v for k, v in grid.items() if v is not None}
    if live:
        bk = min(live, key=lambda k: live[k]["total"])
        b = live[bk]
        print("-" * 118)
        print(f"  最优 λ = {bk} → 年费 {b['total']:,.0f} 元")
        print(f"    分项：计划 {b['plan']:,.0f} ｜ 违约 {b['breach']:,.0f} ｜ "
              f"超额 {b['excess']:,.0f} ｜ 紧急 {b['emerg']:,.0f}")
        print(f"    电量：计划 {b['kwh_gh']:,.0f} kWh ｜ 实际购电 {b['kwh_gf']:,.0f} kWh ｜ "
              f"紧急 {b['kwh_em']:,.0f} kWh")
        print(f"    储能：充 {b['kwh_c']:,.0f} kWh ｜ 放 {b['kwh_d']:,.0f} kWh ｜ "
              f"年末 SOC {b['soc_end']:,.0f}")
        print(f"    SOC 真实日内轨迹区间 [{b['soc_min']:,.0f}, {b['soc_max']:,.0f}] kWh"
              f"（限 {SOC_MIN:,.0f}–{SOC_MAX:,.0f}）"
              f" ｜ 日末序列 [{b['soc_day_min']:,.0f}, {b['soc_day_max']:,.0f}]"
              f"（计划每日末端钉在 SOC0={SOC0:,.0f}，故区间窄，不代表电池没在循环）")
        print(f"    自检：实测紧急频率 {b['freq_em']:.4f}｜发生过上调的天数 {b['n_adj']}")
        print("      ⚠ 无储能时口径 A 的一阶条件给 P(need>ĝ)=0.2，但**有储能时两侧代价被"
              "削平**，")
        print("        有效临界分位不再等于 0.2 —— τ 只能扫、不能推。故本行仅作记录，"
              "不当作合格判据。")
        if b["breach"] > 1.0:
            print(f"    ⚠ 违约费 {b['breach']:,.0f} 元 ≠ 0 —— 与口径 A 的推论(1)矛盾，须查。")
        else:
            print("    ✓ 违约费 ≈ 0，与口径 A 推论(1)（最优 g ≥ ĝ）一致。")
        if DO_WRITE:
            write_result4_3(b)
    print(f"  [总计时] {(time.time() - t0) / 60:.1f} min")
