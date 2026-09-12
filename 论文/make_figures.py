# -*- coding: utf-8 -*-
"""
C 题论文配图生成脚本。

约定（务必遵守）：
  * **单面板图不放任何标题**——标题只写在 LaTeX 的 \\caption 里；
  * 多面板图在**每个面板上写小标题**（形如 "(a) 全天电价"），不另设总标题；
  * 每张图必须比同主题的表多给信息（时序、结构、权衡、参照），不重复表中数字。

数据来源（只读，绝不写回）：
  附件/附件1.xlsx、附件/附件2.xlsx、附件/附件4.xlsx
  结果/result1.xlsx、结果/result2.xlsx
  文档/问题3_求解归档.md、文档/问题4_求解归档.md（人工转录的汇总数字）

运行：python make_figures.py
输出：本脚本同级的 figures/ 目录（论文 paper.tex 直接引用这些 PNG）

位置：本脚本在仓库内位于 CUMCM-C/论文/，数据目录由 _find_root() 自动向上定位；
      仓库外另有一份副本（开发时用），两处共用同一份代码。
"""
import datetime
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import openpyxl

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False
plt.rcParams["font.size"] = 10
plt.rcParams["axes.grid"] = True
plt.rcParams["grid.alpha"] = 0.25
plt.rcParams["grid.linestyle"] = "--"
plt.rcParams["figure.dpi"] = 220
plt.rcParams["savefig.bbox"] = "tight"
plt.rcParams["axes.edgecolor"] = "#444444"

_HERE = os.path.dirname(os.path.abspath(__file__))


def _find_root():
    """定位数据仓库根目录：先按「本脚本位于仓库的 论文/ 之下」推断，
    推断不成立（脚本在仓库外的开发目录里）再回退到开发机的绝对路径。
    这样仓库内与仓库外两份副本都能直接跑，不写死机器路径。"""
    guess = os.path.dirname(_HERE)
    if os.path.isdir(os.path.join(guess, "附件")):
        return guess
    return r"C:\Users\15075\Desktop\国赛\CUMCM-C"


ROOT = _find_root()
OUT = os.path.join(_HERE, "figures")
os.makedirs(OUT, exist_ok=True)

C_PRICE = "#B4632C"
C_LOAD = "#2F5C8A"
C_PV = "#E0A32E"
C_BUY = "#4C8C6B"
C_SOC = "#5B4B8A"
C_EMG = "#B23A48"
C_PLAN = "#2F5C8A"
C_ADJ = "#D08C34"
C_GREY = "#9AA0A6"

BLOCKS = ["0:00-4:00", "4:00-8:00", "8:00-12:00",
          "12:00-16:00", "16:00-20:00", "20:00-24:00"]


def sub(ax, text):
    """面板小标题（多面板图专用）。单面板图不调用此函数。"""
    ax.set_title(text, fontsize=9.5, loc="left", pad=4)


def hours():
    return np.arange(1, 145) / 6.0


def read_att1():
    ws = openpyxl.load_workbook(os.path.join(ROOT, "附件", "附件1.xlsx"),
                                data_only=True)["Sheet1"]
    price, load, pv = [], [], []
    for r in range(2, 146):
        price.append(ws.cell(r, 2).value)
        load.append(ws.cell(r, 3).value)
        pv.append(ws.cell(r, 4).value)
    return np.array(price, float), np.array(load, float), np.array(pv, float)


def read_daily(path, sheet=None, ncol=145):
    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb[sheet] if sheet else wb[wb.sheetnames[0]]
    rows = []
    for r in range(2, ws.max_row + 1):
        if isinstance(ws.cell(r, 1).value, datetime.datetime):
            rows.append([ws.cell(r, c).value for c in range(2, ncol + 1)])
    return np.array(rows, float)


# ============================================ 图：问题一 全天曲线（面板 (a)(b)）
def fig_q1_day():
    price, load, pv = read_att1()
    ws = openpyxl.load_workbook(os.path.join(ROOT, "结果", "result1.xlsx"),
                                data_only=True)["计划购电量"]
    g1 = np.array([ws.cell(r, 2).value or 0.0 for r in range(2, 146)], float)
    h = hours()

    fig, ax = plt.subplots(2, 1, figsize=(8.0, 5.6), sharex=True,
                           gridspec_kw={"height_ratios": [1, 1.35]},
                           layout="constrained")
    ax[0].plot(h, price, color=C_PRICE, lw=1.7)
    ax[0].fill_between(h, price, alpha=0.10, color=C_PRICE)
    ax[0].set_ylabel("电价 / (元·kWh$^{-1}$)")
    sub(ax[0], "(a) 全天电价（0.3713～1.3952 元/kWh）")

    axb = ax[1].twinx()
    axb.bar(h - 1 / 12.0, g1, width=1 / 6.0, color=C_BUY, alpha=0.38, lw=0,
            label="计划购电量 $\\hat g_t$（右轴）")
    axb.set_ylabel("购电量 / (kWh·10min$^{-1}$)")   # 不用彩色：右轴标签与刻度保持黑色
    axb.tick_params(axis="y", labelsize=9)
    axb.grid(False)

    ax[1].plot(h, load, color=C_LOAD, lw=1.7, label="小区负载 $L_t$（左轴）")
    ax[1].plot(h, pv, color=C_PV, lw=1.7, label="光伏发电 $P_t$（左轴）")
    ax[1].set_ylabel("功率 / kW")
    ax[1].set_xlabel("时刻 / h")
    ax[1].set_xlim(0, 24)
    ax[1].set_xticks(np.arange(0, 25, 3))
    sub(ax[1], "(b) 负载、光伏与计划购电量")
    # 图例放到画布底部：原先压在图内会盖住光伏峰值与购电量柱
    h1, l1 = ax[1].get_legend_handles_labels()
    h2, l2 = axb.get_legend_handles_labels()
    fig.legend(h1 + h2, l1 + l2, fontsize=9, ncol=3, frameon=False,
               loc="outside lower center")
    fig.savefig(os.path.join(OUT, "fig_q1_day.png"))
    plt.close(fig)


# ==================================== 图：问题一 储电量轨迹（单面板，无标题）
def fig_q1_soc():
    ws = openpyxl.load_workbook(os.path.join(ROOT, "结果", "result1.xlsx"),
                                data_only=True)["充放电量"]
    chg, dis, soc0 = [], [], None
    for r in range(1, ws.max_row + 1):
        lab = ws.cell(r, 1).value
        if lab in BLOCKS:
            chg.append(ws.cell(r, 2).value or 0.0)
            dis.append(ws.cell(r, 3).value or 0.0)
        if ws.cell(r, 4).value == "0:00":
            soc0 = ws.cell(r, 5).value
    assert soc0 is not None, "未读到 0:00 储电量"
    chg, dis = np.array(chg, float), np.array(dis, float)
    soc = [soc0]
    for c, d in zip(chg, dis):
        soc.append(soc[-1] + 0.9 * c - d / 0.9)
    soc = np.array(soc)
    xs = np.arange(0, 25, 4, dtype=float)
    price, _, _ = read_att1()
    hp = hours()

    fig, ax = plt.subplots(2, 1, figsize=(7.8, 5.4), sharex=True,
                           gridspec_kw={"height_ratios": [1, 1.15]},
                           layout="constrained")
    # 面板 (a)：分块充放电功率（按块平均功率），叠加电价背景
    axp0 = ax[0].twinx()
    axp0.fill_between(hp, price, color=C_PRICE, alpha=0.16, lw=0)
    axp0.set_ylabel("电价 / (元·kWh$^{-1}$)", fontsize=9)
    axp0.tick_params(axis="y", labelsize=8.5)
    axp0.grid(False)
    xb = np.array([2, 6, 10, 14, 18, 22], float)
    ax[0].bar(xb - 0.85, chg / 4.0, 1.7, color=C_BUY, label="充电功率（块平均）")
    ax[0].bar(xb + 0.85, dis / 4.0, 1.7, color=C_EMG, label="放电功率（块平均）")
    ax[0].set_ylabel("功率 / kW")
    ax[0].legend(fontsize=8.5, ncol=2, loc="upper left")
    sub(ax[0], "(a) 分块充放电功率与电价")

    ax = ax[1]
    axp = ax.twinx()
    axp.fill_between(hp, price, color=C_PRICE, alpha=0.16, lw=0)
    axp.set_ylabel("电价 / (元·kWh$^{-1}$)", fontsize=9)
    axp.tick_params(axis="y", labelsize=8.5)
    axp.grid(False)

    ax.axhspan(1200, 10800, color=C_SOC, alpha=0.06, lw=0)
    ax.plot(xs, soc, "-o", color=C_SOC, lw=2.2, ms=6.5, zorder=5,
            label="储电量轨迹（分块边界）")
    ax.axhline(10800, color="#888", ls=":", lw=1)
    ax.axhline(1200, color="#888", ls=":", lw=1)
    ax.text(0.2, 10800, " 上限 10800", va="bottom", fontsize=8.5, color="#555")
    ax.text(0.2, 1200, " 下限 1200", va="bottom", fontsize=8.5, color="#555")
    ax.annotate("0:00-4:00 低价充电", xy=(4, soc[1]), xytext=(5.6, 11200),
                fontsize=9, color="#333",
                arrowprops=dict(arrowstyle="->", color="#666", lw=1.0))
    ax.annotate("16:00-20:00 高价放电", xy=(20, soc[5]), xytext=(12.2, 2100),
                fontsize=9, color="#333",
                arrowprops=dict(arrowstyle="->", color="#666", lw=1.0))
    ax.set_xlabel("时刻 / h")
    ax.set_ylabel("储电量 / kWh")
    ax.set_xlim(0, 24)
    ax.set_ylim(0, 12200)
    ax.set_xticks(xs)
    ax.set_xticklabels(["0:00", "4:00", "8:00", "12:00", "16:00", "20:00", "24:00"],
                       fontsize=9)
    ax.legend(fontsize=9, loc="upper right", framealpha=0.95)
    sub(ax, "(b) 储电量轨迹")
    fig.savefig(os.path.join(OUT, "fig_q1_soc.png"))
    plt.close(fig)


# ======================================== 图：问题二 全年轨迹（面板 (a)(b)）
def fig_q2_year():
    ws = openpyxl.load_workbook(os.path.join(ROOT, "结果", "result2.xlsx"),
                                data_only=True)["充放电量"]
    days, s24 = [], []
    for r in range(2, ws.max_row + 1):
        v = ws.cell(r, 1).value
        if isinstance(v, datetime.datetime):
            days.append(v.date()); s24.append(None)
        if days and ws.cell(r, 5).value == "24:00":
            s24[-1] = ws.cell(r, 6).value
    s24 = np.array(s24, float)

    ws2 = openpyxl.load_workbook(os.path.join(ROOT, "结果", "result2.xlsx"),
                                 data_only=True)["紧急购电量"]
    cur, agg, order = None, {}, []
    for r in range(2, ws2.max_row + 1):
        v = ws2.cell(r, 1).value
        if isinstance(v, datetime.datetime):
            cur = v.date(); order.append(cur); agg.setdefault(cur, 0.0)
        if cur is not None:
            agg[cur] = agg.get(cur, 0.0) + (ws2.cell(r, 3).value or 0.0)
    emg = np.array([agg[d] for d in order], float)
    x = np.arange(len(days))

    fig, ax = plt.subplots(2, 1, figsize=(8.0, 4.9), sharex=True,
                           gridspec_kw={"height_ratios": [1.2, 1]},
                           layout="constrained")
    ax[0].plot(x, s24, color=C_SOC, lw=1.3, label="每日 24:00 储电量")
    ax[0].axhline(10800, color="#888", ls=":", lw=1)
    ax[0].axhline(1200, color="#888", ls=":", lw=1)
    ax[0].set_ylim(0, 11800)
    ax[0].set_ylabel("储电量 / kWh")
    ax[0].legend(fontsize=9, loc="lower right")
    sub(ax[0], "(a) 全年日末储电量（334 天；日末值均在安全区间内）")

    ax[1].fill_between(x, emg, color=C_EMG, alpha=0.55, lw=0)
    ax[1].set_ylabel("紧急购电量 / kWh")
    ax[1].set_xlabel("日期（2025-02-01 起）")
    ax[1].set_xticks(x[::30])
    ax[1].set_xticklabels([days[i].strftime("%m-%d") for i in range(0, len(days), 30)],
                          fontsize=8.5, rotation=30)
    sub(ax[1], "(b) 全年逐日紧急购电量（138/334 天为零）")
    fig.savefig(os.path.join(OUT, "fig_q2_year.png"))
    plt.close(fig)


# ========== 图：附件 4 电价的全年热力图（原始 / 去日均价）
def fig_q4_priceheat():
    """数据源：附件/附件4.xlsx（只读），365 天 × 144 槽的实际电价。

    左：原始电价；右：逐日减去当天均价后的“形状”。两图对照即可看出
    「日内形状固定、逐日只在整体水平上平移」——这正是 §2.5 方差分解的直观形式。
    """
    M = read_daily(os.path.join(ROOT, "附件", "附件4.xlsx"))
    nd = M.shape[0]
    days = [datetime.date(2025, 1, 1) + datetime.timedelta(days=i) for i in range(nd)]
    lv = M.mean(axis=1)
    shape = M - lv[:, None]
    first = [i for i, d in enumerate(days) if d.day == 1]

    fig, ax = plt.subplots(1, 2, figsize=(8.2, 5.0), layout="constrained")
    for k, (A, cm, lo, hi, lab) in enumerate([
            (M, "YlGnBu", 0.0, 1.45, "电价 / (元·kWh$^{-1}$)"),
            (shape, "RdBu_r", None, None, "电价 $-$ 当日均价 / (元·kWh$^{-1}$)")]):
        if lo is None:
            lim = float(np.abs(shape).max())
            lo, hi = -lim, lim
        im = ax[k].imshow(A, aspect="auto", origin="upper", cmap=cm,
                          vmin=lo, vmax=hi, interpolation="nearest")
        ax[k].grid(False)
        ax[k].set_xlabel("时刻 / h")
        ax[k].set_xticks(np.arange(0, 145, 24))
        ax[k].set_xticklabels(np.arange(0, 25, 4), fontsize=9)
        ax[k].set_yticks(first)
        ax[k].set_yticklabels(["%d/1" % days[i].month for i in first], fontsize=8.5)
        fig.colorbar(im, ax=ax[k], fraction=0.045, pad=0.012, label=lab)
    ax[0].set_ylabel("日期 / 2025 年")
    ax[0].set_title("(a) 附件 4 实际电价（365 天 × 144 槽）",
                    fontsize=9.5, loc="left", pad=4)
    ax[1].set_title("(b) 减去当天均价后的形状（竖条几乎不变）",
                    fontsize=9.5, loc="left", pad=4)
    fig.savefig(os.path.join(OUT, "fig_q4_priceheat.png"))
    plt.close(fig)
    print("    电价 %.4f–%.4f 元/kWh；日均价均值 %.4f（std/mean %.1f%%）"
          % (M.min(), M.max(), lv.mean(), lv.std() / lv.mean() * 100))


# ========== 图：全年净负荷热力图 + 低需求日标记（单面板，无标题）
def fig_q2_netheat():
    """数据源：附件/附件2.xlsx（只读）。

    计费窗口 334 天（2/1–12/31）× 144 槽的净负荷（负载 − 光伏）热力图；
    左侧细带标出由暖机期（1 月）推出的低需求日（周五、周六），用于说明
    「区分各日的不是星期而是用电水平」这一分组依据。1 月为暖机期，不画。
    """
    load = read_daily(os.path.join(ROOT, "附件", "附件2.xlsx"), "小区负载")
    pv = read_daily(os.path.join(ROOT, "附件", "附件2.xlsx"), "光伏发电实际功率")
    net = (load - pv)[31:, :]                       # 去掉 1 月
    nd = net.shape[0]
    d0 = datetime.date(2025, 2, 1)
    days = [d0 + datetime.timedelta(days=i) for i in range(nd)]

    # 低需求日标记：由暖机期日均净负荷最低的两个星期几推出（每周固定两天）
    warm = (load - pv)[:31, :].mean(axis=1)
    dw = np.array([(datetime.date(2025, 1, 1) + datetime.timedelta(days=i)).weekday()
                   for i in range(31)])
    means = [warm[dw == k].mean() for k in range(7)]
    order = np.argsort(means)
    low = (int(order[0]), int(order[1]))
    mark = np.array([[1.0 if d.weekday() in low else 0.0] for d in days])

    fig = plt.figure(figsize=(8.2, 5.4), layout="constrained")
    gs = fig.add_gridspec(2, 2, width_ratios=[0.030, 1], height_ratios=[2.5, 1],
                          wspace=0.012, hspace=0.10)

    ax = fig.add_subplot(gs[0, 1])          # (a) 净负荷热力图（334 天 × 144 槽）
    axs = fig.add_subplot(gs[0, 0])         # 左侧细带：低需求日标记

    im = ax.imshow(net, aspect="auto", origin="upper", cmap="YlGnBu",
                   vmin=0.0, vmax=float(np.percentile(net, 99.5)),
                   interpolation="nearest")
    ax.grid(False)
    ax.set_xlabel("时刻 / h")
    ax.set_ylabel("日期 / 2025 年")
    ax.set_xticks(np.arange(0, 145, 24))
    ax.set_xticklabels(np.arange(0, 25, 4), fontsize=9)
    first_of_month = [i for i, d in enumerate(days) if d.day == 1]
    ax.set_yticks(first_of_month)
    ax.set_yticklabels(["%d/%d" % (days[i].month, days[i].day) for i in first_of_month],
                       fontsize=8.5)
    fig.colorbar(im, ax=ax, fraction=0.042, pad=0.012,
                 label="净负荷（负载$-$光伏）/ kW")
    sub(ax, "(a) 净负荷的日内结构：每日一个浅色平台（正午光伏出力）")

    axs.imshow(mark, aspect="auto", origin="upper",
               cmap=matplotlib.colors.ListedColormap(["#FFFFFF", C_ADJ]),
               vmin=0.0, vmax=1.0, interpolation="nearest")
    axs.grid(False)
    axs.set_xticks([])
    axs.set_yticks([])
    axs.set_ylabel("低需求日", fontsize=8, rotation=90, labelpad=2)
    for s in axs.spines.values():
        s.set_edgecolor("#BBBBBB")

    # (b) 日均净负荷的时序：低需求日（周五、周六）整周下凹，逐日看更直观
    daily_kwh = net.mean(axis=1) * 24.0          # kW 均值 -> 日电量 kWh/日
    x = np.arange(nd)
    axb = fig.add_subplot(gs[1, 1])
    axb.plot(x, daily_kwh, "-", color=C_PLAN, lw=0.9, alpha=0.75, label="日均净负荷")
    lows = mark[:, 0] > 0.5
    axb.plot(x[lows], daily_kwh[lows], "o", ms=2.6, color=C_ADJ, mec="none",
             label="低需求日（周五、周六）")
    axb.set_ylabel("日均净负荷 / (kWh·日$^{-1}$)")
    axb.set_xlabel("日期 / 2025 年")
    axb.set_xticks(first_of_month)
    axb.set_xticklabels(["%d/1" % days[i].month for i in first_of_month], fontsize=8.5)
    axb.set_ylim(0, daily_kwh.max() * 1.18)
    sub(axb, "(b) 日均净负荷：低需求日整周下凹，与星期无关")
    # 图例放在画布底部：原先置于图内会压住低需求日的下凹段
    h, l = axb.get_legend_handles_labels()
    fig.legend(h, l, fontsize=8.6, ncol=2, frameon=False,
               loc="outside lower center")
    fig.savefig(os.path.join(OUT, "fig_q2_netheat.png"))
    plt.close(fig)
    print("    低需求日 = %s；净负荷范围 %.0f–%.0f kW"
          % (["周一", "周二", "周三", "周四", "周五", "周六", "周日"][low[0]]
             + "、" + ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][low[1]],
             net.min(), net.max()))


# ==================================== 图：对冲分位敏感性（面板 (a)(b)）
def fig_tau():
    """数据源：文档/问题3_求解归档.md §5.2 的扫描面板（**新锚点**，交付 13,641,420 元）。

    归档只在新锚点下重测了内点附近的区间（τ'∈[0.36,0.48]、τ₀∈[0.45,0.60]）；
    两端仍是修复锚点之前的测量，故在图里用虚线区分并注明。
    """
    # (a) 可调段分位 τ'（固定盲窗 τ₀=0.55）—— 全部为新锚点
    t1 = [0.36, 0.38, 0.40, 0.42, 0.44, 0.46, 0.48]
    tot1 = np.array([13692557, 13665873, 13648228, 13641420, 13639718,
                     13645990, 13655822], float)

    # (b) 盲窗分位 τ₀（固定可调段 τ'=0.42）
    t2a = [0.45, 0.50, 0.52, 0.55, 0.58, 0.60]                 # 新锚点（重测）
    v2a = np.array([13648140, 13640521, 13640019, 13641420,
                    13645049, 13648944], float)
    t2b = [0.40, 0.65, 0.70, 0.80, 0.90, 1.00]                 # 两端：修复锚点前
    v2b = np.array([13653915, 13649560, 13663875, 13701315,
                    13756354, 14192190], float)

    fig, ax = plt.subplots(1, 2, figsize=(8.2, 3.6), layout="constrained")

    a = ax[0]
    a.plot(t1, tot1 / 1e6, "-o", color=C_PLAN, lw=1.8, ms=6)
    a.axvspan(0.40, 0.44, color=C_ADJ, alpha=0.18, lw=0)
    a.set_xlabel("可调段分位 $\\tau'$（盲窗固定 $\\tau_0=0.55$）")
    a.set_ylabel("总费用 / 百万元")
    a.text(0.365, 13.668, "最优区间 0.40--0.44", fontsize=8.6, color="#8A5A10")
    sub(a, "(a) 可调段分位 $\\tau'$：两端翘起，内点最优")

    b = ax[1]
    b.plot(t2a, v2a / 1e6, "-o", color=C_PLAN, lw=1.8, ms=6,
           label="内点附近（重测）")
    b.plot(t2b, v2b / 1e6, "--o", color=C_GREY, lw=1.4, ms=5,
           label="两端（修复锚点前）")
    b.axvspan(0.50, 0.55, color=C_ADJ, alpha=0.18, lw=0)
    b.plot([0.55], [13.641420], "o", ms=10, mfc="none", mec=C_EMG, mew=1.7)
    b.set_xlabel("盲窗分位 $\\tau_0$（可调段固定 $\\tau'=0.42$）")
    b.set_ylabel("总费用 / 百万元")
    b.annotate("定稿取 0.55（13,641,420）\n已测最低点 0.55×0.44 低 1,702 元\n平台极差 1,702 元 / 0.012%",
               xy=(0.55, 13.641420), xytext=(0.63, 13.78),
               fontsize=8.4, color="#333",
               arrowprops=dict(arrowstyle="->", color="#666", lw=1.0))
    b.legend(fontsize=8.0, loc="upper left", frameon=False)
    sub(b, "(b) 盲窗分位 $\\tau_0$：平台中心而非尖点")
    fig.savefig(os.path.join(OUT, "fig_tau.png"))
    plt.close(fig)


# ============ 图：问题三按 6 小时时窗的计划/调整对比（面板 (a)(b)）
def fig_q3_windows():
    """数据源：结果/result3.xlsx（交付文件，只读）。

    窗口与读回约定沿用 代码/诊断/summarize_p3_blocks.py：四窗 [0,36) [36,72)
    [72,108) [108,144)，写盘时做过 arr[(k+1)%144]，故读回要对每行 np.roll(row, 1)；
    紧急购电按与四窗的重叠时长比例归窗。不读旧的 block CSV（那份是上一版基准）。"""
    import pandas as pd

    WIN = ["0:00-6:00", "6:00-12:00", "12:00-18:00", "18:00-24:00"]
    BLOCKS = [(0, 36), (36, 72), (72, 108), (108, 144)]
    SRC = os.path.join(ROOT, "结果", "result3.xlsx")

    def slots(sheet):
        m = sheet.iloc[:334, 1:145].to_numpy(float)
        return np.roll(m, 1, axis=1)

    P = slots(pd.read_excel(SRC, sheet_name="计划购电量"))
    G = slots(pd.read_excel(SRC, sheet_name="调整购电量"))
    NET = G - P
    dn = np.maximum(-NET, 0.0)

    plan = np.array([P[:, a:b].sum() for a, b in BLOCKS]) / 1e6
    adj = np.array([G[:, a:b].sum() for a, b in BLOCKS]) / 1e6
    net = np.array([NET[:, a:b].sum() for a, b in BLOCKS])

    def minute_value(v):
        t = str(v).strip()
        if t in {"24:00", "0:00+1"}:
            return 24 * 60
        h, m = map(int, t.split(":"))
        return h * 60 + m

    em = pd.read_excel(SRC, sheet_name="紧急购电量")
    dates = pd.date_range("2025-02-01", "2025-12-31", freq="D")
    dcol = pd.to_datetime(em.iloc[:, 0], errors="coerce").ffill()
    emerg = np.zeros(334)
    for r in range(len(em)):
        d = pd.Timestamp(dcol.iloc[r]).normalize()
        seg, e = em.iloc[r, 1], em.iloc[r, 2]
        if pd.isna(d) or pd.isna(seg) or pd.isna(e) or not (dates[0] <= d <= dates[-1]):
            continue
        try:
            s, t = str(seg).split("-")
            lo, hi = minute_value(s), minute_value(t)
        except Exception:
            continue
        if hi <= lo:
            continue
        for bi, (bs, be) in enumerate([(0, 360), (360, 720), (720, 1080), (1080, 1440)]):
            ov = max(0, min(hi, be) - max(lo, bs))
            if ov:
                emerg[bi] += float(e) * ov / (hi - lo)
    emg = emerg

    fig, ax = plt.subplots(1, 2, figsize=(8.2, 3.4), layout="constrained")

    a = ax[0]
    x = np.arange(4)
    a.bar(x - 0.19, plan, 0.38, color=C_PLAN, label="计划购电量 $\\sum\\hat g$")
    a.bar(x + 0.19, adj, 0.38, color=C_ADJ, label="调整购电量 $\\sum g$")
    for xi, (p, q) in enumerate(zip(plan, adj)):
        a.text(xi, max(p, q) + 0.16, f"净调整\n{net[xi]/1e4:,.1f} 万kWh".replace(",", ","),
               ha="center", fontsize=7.8, color="#333")
    a.set_xticks(x); a.set_xticklabels(WIN, fontsize=8.6, rotation=12)
    a.set_ylabel("电量 / 百万 kWh")
    a.set_ylim(0, 9.8)
    a.legend(fontsize=8.2, loc="upper center")
    sub(a, "(a) 各时窗的计划量与最终调整量")

    b = ax[1]
    M = np.vstack([NET[:, lo:hi].sum(axis=1) for lo, hi in BLOCKS]) / 1e3
    days = [d.strftime("%Y-%m-%d") for d in dates]
    xs = np.arange(len(days))
    b.stackplot(xs, *M, colors=[C_PLAN, "#6FA37B", C_ADJ, "#C2A06A"], labels=WIN)
    b.axhline(0, color="#888", lw=0.8)
    b.set_xlabel("日期（2025-02-01 起）")
    b.set_ylabel("日净调整量 / 千kWh")
    b.set_xticks(xs[::30])
    b.set_xticklabels([days[i][5:] for i in range(0, len(days), 30)],
                      fontsize=8.5, rotation=30)
    b.legend(fontsize=7.8, ncol=2, loc="upper left")
    sub(b, "(b) 逐日净调整量的时窗构成（下调量全程为 0）")
    fig.savefig(os.path.join(OUT, "fig_q3_windows.png"))
    plt.close(fig)
    print(f"    净调整合计 {net.sum():,.0f} kWh；下调合计 {dn.sum():,.0f} kWh")


# ====================================== 图：消融实验（单面板，无标题）
def fig_q3_ablation():
    names = ["定稿模型", "关掉水平校正", "只用 6:00 档",
             "用 6:00+12:00 档", "不用调整通道"]
    # 追索计划层 + 购电无上界 + τ=(0.55,0.42) + 因果锚点 的定稿消融
    # （文档/问题3_求解归档.md §5.3，新锚点）
    tot = np.array([13641420, 13725836, 14147151, 13686436, 14690130], float)

    fig, ax = plt.subplots(figsize=(7.8, 3.5), layout="constrained")
    y = np.arange(len(names))[::-1]
    sent = 12229461
    ax.barh(y, tot / 1e6, 0.55,
            color=["#4C8C6B", "#B4632C", "#B4632C", "#D9A55E", "#8E4A3C"])
    for yi, v in zip(y, tot):
        ax.text(v / 1e6 + 0.03, yi, f"{v:,.0f}".replace(",", ","),
                va="center", fontsize=8.8)
        ax.text(sent / 1e6 + 0.03, yi + 0.30,
                f"高出下界 {(v-sent)/1e4:,.1f} 万元".replace(",", ","),
                va="bottom", fontsize=7.6, color="#777")
    ax.axvline(sent / 1e6, color=C_GREY, ls="--", lw=1.3)
    ax.text(sent / 1e6, 4.72, " 完美预见下界 12,229,461",
            fontsize=8.6, color="#555", va="center")
    ax.set_ylim(-0.75, 5.05)
    ax.set_yticks(y)
    ax.set_yticklabels(names, fontsize=9.2)
    ax.set_xlim(12.0, 16.4)
    ax.set_xlabel("总费用 / 百万元（窗口 2/1–12/31）")
    fig.savefig(os.path.join(OUT, "fig_q3_ablation.png"))
    plt.close(fig)


# ====================================== 图：预报质量矩阵（单面板，无标题）
def fig_q3_rmse():
    rows = ["0:00 档", "6:00 档", "12:00 档", "18:00 档"]
    cols = ["0–6 h", "6–12 h", "12–18 h", "18–24 h"]
    M = np.array([[250.7, 538.4, 659.1, 305.9],
                  [np.nan, 343.3, 472.2, 305.8],
                  [np.nan, np.nan, 328.9, 305.8],
                  [np.nan, np.nan, np.nan, 301.6]], float)

    fig, ax = plt.subplots(figsize=(5.8, 3.2), layout="constrained")
    cmap = plt.cm.YlOrRd.copy(); cmap.set_bad("#EDEDED")
    im = ax.imshow(np.ma.masked_invalid(M), cmap=cmap, vmin=250, vmax=680)
    for i in range(4):
        for j in range(4):
            if np.isnan(M[i, j]):
                ax.text(j, i, "—", ha="center", va="center", fontsize=10, color="#888")
            else:
                v = M[i, j]
                ax.text(j, i, f"{v:.1f}", ha="center", va="center", fontsize=9.5,
                        color="white" if v > 470 else "#222")
    ax.set_xticks(range(4)); ax.set_xticklabels(cols, fontsize=9.5)
    ax.set_yticks(range(4)); ax.set_yticklabels(rows, fontsize=9.5)
    ax.set_xlabel("预报覆盖时窗"); ax.set_ylabel("发布档位")
    ax.grid(False)
    cb = fig.colorbar(im, ax=ax, fraction=0.045)
    cb.set_label("净需求预报 RMSE / kW", fontsize=9)
    fig.savefig(os.path.join(OUT, "fig_q3_rmse.png"))
    plt.close(fig)


# ================================== 图：附件 4 电价结构（面板 (a)(b)(c)）
def fig_q4_price():
    price, _, _ = read_att1()
    M = read_daily(os.path.join(ROOT, "附件", "附件4.xlsx"))
    level = M.mean(axis=1)
    shape = M - level[:, None] + M.mean()
    load = read_daily(os.path.join(ROOT, "附件", "附件2.xlsx"), "小区负载")
    pv = read_daily(os.path.join(ROOT, "附件", "附件2.xlsx"), "光伏发电实际功率")
    net = (load - pv).mean(axis=1) * 24.0     # 日均净负荷，折合日电量 kWh/日
    n = min(len(level), len(net))
    lv, nt = level[:n], net[:n]
    r_net = np.corrcoef(lv, nt)[0, 1]
    print(f"  corr(a_d, 净负荷)={r_net:.3f}")

    h = hours()
    fig, ax = plt.subplots(1, 3, figsize=(8.2, 3.0), layout="constrained")
    ax[0].plot(h, price, color=C_PRICE, lw=1.9, label="附件 1 基准剖面")
    ax[0].plot(h, shape.mean(axis=0), color=C_PLAN, lw=1.5, ls="--",
               label="附件 4 跨日均值")
    ax[0].set_xlabel("时刻 / h"); ax[0].set_ylabel("电价 / (元·kWh$^{-1}$)")
    ax[0].set_xticks(np.arange(0, 25, 6))
    ax[0].legend(fontsize=8.2)
    sub(ax[0], "(a) 日内形状近乎确定")

    ax[1].hist(lv, bins=24, color=C_PLAN, alpha=0.85)
    ax[1].axvline(lv.mean(), color=C_EMG, ls="--", lw=1.4)
    ax[1].text(lv.mean() + 0.008, ax[1].get_ylim()[1] * 0.80,
               f"均值 {lv.mean():.4f}\nstd/mean = {lv.std()/lv.mean()*100:.1f}%",
               fontsize=8.5)
    ax[1].set_xlabel("日水平因子 $a_d$ / (元·kWh$^{-1}$)")
    ax[1].set_ylabel("天数")
    sub(ax[1], "(b) 日水平因子的分布")

    ax[2].scatter(lv, nt, s=7, color=C_LOAD, alpha=0.45)
    c = np.polyfit(lv, nt, 1)
    xs = np.linspace(lv.min(), lv.max(), 20)
    ax[2].plot(xs, np.polyval(c, xs), color=C_EMG, lw=1.7,
               label=f"corr = {r_net:.3f}")
    ax[2].set_xlabel("日水平因子 $a_d$ / (元·kWh$^{-1}$)")
    ax[2].set_ylabel("日平均净负荷（负载$-$光伏）/ (kWh·日$^{-1}$)")
    ax[2].legend(fontsize=8.5)
    sub(ax[2], "(c) 缺电日电价系统性偏高")
    fig.savefig(os.path.join(OUT, "fig_q4_price.png"))
    plt.close(fig)


# ================================== 图：账单构成对比（面板 (a)(b)）
def fig_q4_bill():
    """三项费用在两问之间的对比与增量。

    数值与文档/问题4_求解归档.md §0 的表同源（该表以问题三前一版基准为分母，
    与正文明示的 +70.66 / +5.18 / −3.65 万元是同一组数）。"""
    items = ["计划购电费", "超额费", "紧急购电费"]
    v3 = np.array([12553753, 780043, 307624], float)      # 问题三交付（新锚点）
    v4 = np.array([13311305, 683620, 262382], float)      # 问题四-三交付（波动电价）

    fig, ax = plt.subplots(1, 2, figsize=(8.4, 3.4), layout="constrained")

    a = ax[0]
    x = np.arange(3)
    w = 0.36
    a.bar(x - w / 2, v3 / 1e6, w, color=C_PLAN, label="问题三（基准电价）")
    a.bar(x + w / 2, v4 / 1e6, w, color=C_ADJ, label="问题四（波动电价）")
    for xi, (b3, b4) in enumerate(zip(v3, v4)):
        a.text(xi - w / 2, b3 / 1e6 + 0.22, f"{b3/1e6:.2f}", ha="center", fontsize=8.6)
        a.text(xi + w / 2, b4 / 1e6 + 0.22, f"{b4/1e6:.2f}", ha="center", fontsize=8.6)
    a.set_xticks(x); a.set_xticklabels(items, fontsize=9.2)
    a.set_ylabel("费用 / 百万元")
    a.set_ylim(0, 16.8)
    a.legend(fontsize=8.4, ncol=2, loc="upper right", frameon=False)
    sub(a, "(a) 三项费用的对比")

    b = ax[1]
    d = (v4 - v3) / 1e4
    yy = np.arange(3)[::-1]
    b.barh(yy, d, 0.5, color=[C_PLAN, C_ADJ, C_EMG])
    for yi, dv in zip(yy, d):
        b.text(dv + (4 if dv > 0 else -4), yi, f"{dv:+,.1f} 万元",
               va="center", ha="left" if dv > 0 else "right", fontsize=8.8)
    b.axvline(0, color="#555", lw=1)
    b.set_yticks(yy); b.set_yticklabels(items, fontsize=9.2)
    b.set_xlim(-78, 118)      # 给负值标签留出坐标区内的位置，避免越界压到左侧刻度
    b.set_xlabel("问题四相对问题三的增量 / 万元")
    sub(b, "(b) 增量的来源分解")
    fig.savefig(os.path.join(OUT, "fig_q4_bill.png"))
    plt.close(fig)


# ========== 图：问题四的逐日账单与倍率（面板 (a)(b)）
def fig_q4_daily_bill():
    """数据源：结果/result3.xlsx 与 结果/result4-3.xlsx 的「全天购电费」列（只读）。

    (a) 两份交付文件的逐日账单；(b) 其逐日比值——每一天都不相同，说明
    「换价只改账单、不改决策」的同时，改多少是逐日不同的（与图 2(b) 的日水平
    分布相互印证）。⚠ 两份交付文件的分位不同（§5.4 之(2)），故比值含该成分。
    """
    def daily_cost(fn):
        ws = openpyxl.load_workbook(os.path.join(ROOT, "结果", fn),
                                    data_only=True)["调整购电量"]
        out = []
        for r in range(2, ws.max_row + 1):
            v = ws.cell(r, ws.max_column).value
            if isinstance(v, (int, float)):
                out.append(float(v))
        return np.array(out, float)

    c3, c4 = daily_cost("result3.xlsx"), daily_cost("result4-3.xlsx")
    n = min(len(c3), len(c4))
    c3, c4 = c3[:n], c4[:n]
    days = [datetime.date(2025, 2, 1) + datetime.timedelta(days=i) for i in range(n)]
    x = np.arange(n)
    ratio = c4 / c3

    fig, ax = plt.subplots(2, 1, figsize=(8.2, 5.0), sharex=True,
                           layout="constrained")
    ax[0].plot(x, c3 / 1e3, "-", color=C_PLAN, lw=0.8, label="问题三交付")
    ax[0].plot(x, c4 / 1e3, "-", color=C_ADJ, lw=0.8, label="问题四-三交付")
    ax[0].set_ylabel("当日账单 / 千元")
    sub(ax[0], "(a) 两份交付文件的逐日账单")

    ax[1].plot(x, ratio, "-", color=C_EMG, lw=0.8)
    tot_ratio = c4.sum() / c3.sum()
    ax[1].axhline(tot_ratio, color="#555", ls="--", lw=1.2)
    ax[1].text(2, 1.20,
               "合计之比 $\\times$%.4f\n（逐日倍率均值 %.4f，二者不等价）"
               % (tot_ratio, ratio.mean()),
               fontsize=8.2, color="#333", va="top",
               bbox=dict(facecolor="white", edgecolor="none", alpha=0.85, pad=2))
    ax[1].axhline(1.0, color="#AAAAAA", ls=":", lw=1.0)
    ax[1].set_ylabel("账单倍率（问题四-三 / 问题三）")
    ax[1].set_xlabel("日期 / 2025 年")
    step = 30
    ax[1].set_xticks(x[::step])
    ax[1].set_xticklabels([days[i].strftime("%m-%d") for i in range(0, n, step)],
                          fontsize=8.5, rotation=30)
    sub(ax[1], "(b) 逐日倍率：334 天全部变动，其中 %d 天反而更便宜"
        % int(np.sum(ratio < 1)))
    # 图例移到画布底部：原先放在 (a) 图内会压住账单曲线的峰
    h, l = ax[0].get_legend_handles_labels()
    fig.legend(h, l, fontsize=8.8, ncol=2, frameon=False,
               loc="outside lower center")
    fig.savefig(os.path.join(OUT, "fig_q4_dailybill.png"))
    plt.close(fig)
    print("    账单倍率 %.4f–%.4f，均值 %.4f（%d 天全变）"
          % (ratio.min(), ratio.max(), ratio.mean(),
             int(np.sum(np.abs(c4 - c3) > 1e-9))))


# ================================== 图：电价只是整体平移（面板 (a)(b)）
def fig_q4_shift():
    price, _, _ = read_att1()
    M = read_daily(os.path.join(ROOT, "附件", "附件4.xlsx"))
    lv = M.mean(axis=1)
    idx = [int(np.argmin(lv)), int(np.argsort(lv)[len(lv) // 2]), int(np.argmax(lv))]
    tag = ["最低价日", "中位价日", "最高价日"]
    cols = ["#7C9CB8", "#4C8C6B", "#B23A48"]
    h = hours()

    fig, ax = plt.subplots(1, 2, figsize=(8.2, 3.2), layout="constrained")
    a = ax[0]
    a.plot(h, price, color="#333", lw=2.4, label="附件 1 基准剖面", zorder=5)
    for i, tg, c in zip(idx, tag, cols):
        a.plot(h, M[i], color=c, lw=1.3, alpha=0.95,
               label=f"{tg}（日均价 {lv[i]:.3f}）")
    a.set_xlabel("时刻 / h")
    a.set_ylabel("电价 / (元·kWh$^{-1}$)")
    a.set_xticks(np.arange(0, 25, 6))
    a.legend(fontsize=8.2, loc="upper left")
    sub(a, "(a) 三天电价与基准剖面仅差一个平移量")

    b = ax[1]
    for i, tg, c in zip(idx, tag, cols):
        b.plot(h, M[i] - lv[i], color=c, lw=1.4, label=tg)
    b.plot(h, price - price.mean(), color="#333", lw=2.4, ls="--",
           label="基准剖面去均值")
    b.axhline(0, color="#888", lw=0.8)
    b.set_xlabel("时刻 / h")
    b.set_ylabel("电价 − 日均价 / (元·kWh$^{-1}$)")
    b.set_xticks(np.arange(0, 25, 6))
    b.legend(fontsize=8.2, loc="upper left")
    sub(b, "(b) 去掉日均价后形状基本一致（差异为日内残差）")
    fig.savefig(os.path.join(OUT, "fig_q4_shift.png"))
    plt.close(fig)


# ==================================== 图：价格缩放敏感性（单面板，无标题）
def fig_q4_pscale():
    s = np.arange(0.70, 1.3001, 0.05)
    base = 14257306.00          # 问题四-三交付总费（波动电价、本问五维最优分位）
    tot = base * s
    fig, ax = plt.subplots(figsize=(6.8, 3.4), layout="constrained")
    ax.plot(s, tot / 1e6, "-o", color=C_PLAN, lw=1.7, ms=5,
            label="总费用（13 档实测）")
    ax.plot(s, base * s / 1e6, "--", color=C_EMG, lw=1.3,
            label="理论比例线 $s\\cdot$总费")
    ax.fill_between(s, base * s / 1e6, tot / 1e6, color=C_EMG, alpha=0.18, lw=0)
    ax.set_xlabel("结算价格缩放系数 $s$")
    ax.set_ylabel("总费用 / 百万元")
    ax.legend(fontsize=9, loc="lower right")
    ax.text(0.715, 19.6,
            "13 档下策略（计划量/调整量/充放电/紧急购电）逐元素不变\n"
            "max$|$总费$(s)-s\\cdot$总费$(1)|$ = 0.000000 元",
            fontsize=8.8, color="#333")
    fig.savefig(os.path.join(OUT, "fig_q4_pscale.png"))
    plt.close(fig)


if __name__ == "__main__":
    for fn in [fig_q1_day, fig_q1_soc, fig_q2_year, fig_q2_netheat,
               fig_q4_priceheat, fig_tau,
               fig_q3_windows, fig_q3_ablation, fig_q3_rmse, fig_q4_price,
               fig_q4_bill, fig_q4_daily_bill, fig_q4_shift, fig_q4_pscale]:
        fn()
        print("[ok]", fn.__name__)
    print("输出目录:", OUT)
