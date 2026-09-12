# -*- coding: utf-8 -*-
"""问题 4-3 的**交付入口**：把交付配置的旋钮全部钉死，再跑 problem4_3.py。

    python 代码/run_problem4.py

为什么要有这个文件：problem4_3.py 有 20 多个环境旋钮，直接跑它得到的是**缺省配置**
（`P4_GMAX=5000`、`P4_REC=1`），**不是交付值**。"跑了个非交付配置却以为拿到交付值"
是这个项目踩过多次的坑（taskrun §6.5）。这里把交付配置固化在一处，使复现只需一条命令。

交付配置（与问题 3 只差"价格如何进入"这一层；**τ 除外，见下**）：

    P4_REC=1        计划层用追索变量（问题 2 两阶段），对齐 P3_REC=1
    P4_GMAX=20000   购电上界。⚠ **不是字面意义上的 `inf`**：题面未给联络线容量，
                    而 20,000 kW 已远高于实测峰值 10,172.8 kW ⇒ 上界**不紧**，
                    建模上与"无上界"同解。之所以不写 `inf`：HiGHS 在退化 LP 上
                    有数值尺度效应，上界数值越大解越偏（实测 `1e9` +218 元、
                    `inf` +1,180 元，且**随上界单调**），20000 是非紧取值里
                    条件数最好的那个。四臂实测见 `诊断/diag_p4_gmax3.py`、归档 §5.5。
    P4_TAUB/TAUP    **本问自己的最优 τ**（五维搜索产出）。⚠ 自 2026-09-12 起
                    **不再**继承问题 3 的 τ —— 继承版是刻意的受控对照，但实测代价
                    **146,781.57 元（1.019%）**（早先按手挑 6 点估的 49,621 元
                    只是对角线上的一个点，低估了三倍）；交付改为本问最优，
                    §6.1 那条对照随之降级为受控消融。
                    共享 τ 仍记在 `problem4_3._SHARED_TAU`，常数价回归用它。
    P4_READING=B    0:00 不知道当天实际电价（主模型）
    P4_WQ=0         电价加权分位 —— **负结果**，缺省关闭
    P4_PSCALE=1.0   不缩放价格
    P4_PRICE_SRC=att4  实际价用附件 4（波动）；设 att1 则退回常数价，用于回归自检

跑完会打印一行「本配置 = / ≠ 交付配置」的自检，以及一行「失同步自检」（常数价回归
是否精确复现问题 3 的交付值）。**以那两行为准。**

⚠ 注意与问题 3 的一个差别：问题 3 的哨兵（完美预见下界）用附件 1 的常数价，而本文件
  的哨兵用**附件 4 的实际价**，故两者的哨兵值不同口径、不可并列比较。
"""
import os
import runpy
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

# ⚠ τ **不再手抄在这里**，改从 problem4_3._DELIVERY 读（唯一真源）。
#   本文件原先把 `P4_TAUB="0.55,0.42,0.42,0.42"` 抄了一遍；τ 一改，这份副本**不会报错**，
#   只会让"官方复现命令"跑在与交付值不同的配置上，而自检仍印着交付横幅 ——
#   一个静默错位。改 τ 现在只需改 problem4_3._DELIVERY 一处。
sys.path.insert(0, os.path.join(HERE, "诊断"))
try:
    import _p4_delivery as _D
    _deliv_env, _deliv_info = _D.delivery()
except Exception as _e:                     # 兜底：读不到就显式报错，绝不用猜的 τ
    raise SystemExit(f"[FATAL] 无法从 problem4_3._DELIVERY 读取交付 τ：{_e}")

# ⚠ 一律用 setdefault：**调用方显式设过的环境变量必须优先**。
#   早先这里写的是直接赋值，结果是 `P4_WRITE=0 python 代码/run_problem4.py` 仍会写盘、
#   `P4_PRICE_SRC=att1 ...` 仍会用附件 4 波动价 —— 复现命令看着对、实际跑的是另一回事，
#   而且**静默**（2026-09-12 实测踩到：att1 回归跑出了波动价的数）。
#   交付配置是**缺省**，不是对调用方的强制。
_DEFAULTS = dict(
    # 形状类旋钮直接从 _DELIVERY 生成，不再手抄
    **{k: v for k, v in _deliv_env.items() if k != "PYTHONIOENCODING"},
    P4_SENT="1",
    P4_WRITE="1",
)
_DEFAULTS.setdefault("P4_ANCHOR", "prev")   # 整点锚点严格因果，去 10 分钟前视
for _k, _v in _DEFAULTS.items():
    os.environ.setdefault(_k, _v)

runpy.run_path(os.path.join(HERE, "problem4_3.py"), run_name="__main__")
