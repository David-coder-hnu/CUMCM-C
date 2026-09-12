# -*- coding: utf-8 -*-
"""追索无上界 —— 一键复现脚本（问题 3 计划层充放电改成问题 2 追索变量 + 购电无上界）。

把「追索变量 + 购电无上界」这套配置固化，直接产出 result3_recourse_unbounded.xlsx。
等价于命令行：

    P3_REC=1 P3_GMAX=20000 P3_SENT=1 P3_WRITE=1 \
    P3_OUT="problem3优化/result3_recourse_unbounded.xlsx" \
    python problem3优化/problem3_v3_recourse.py

改动内容（详见 problem3_v3_recourse.py 顶部 docstring 与 追索无上界_结果.md）：
  · 计划层 c/d/e/S 逐情景 ω（追索变量），只有 ĝ 是一阶段承诺 —— 问题 2 两阶段思路；
  · 执行层 exec_causal_day（因果贪婪，= 问题 2 execute_soc_causal 的逐日版）；
  · 购电功率上界 P3_GMAX 取大数（20000，实际不触发），回到题面「未给联络线容量」的字面读法；
  · 其余（预测 F̂、分位缓冲 h、6/12/18 调整层、口径 A 结算、低需求日分组 span7、日末回归 6000）全部保留。

结果：总费 13,822,501 元，比问题 2 交付 13,846,553 元便宜 24,052 元（−0.17%）。
"""
import os
import runpy

HERE = os.path.dirname(os.path.abspath(__file__))

# 固化配置（直接赋值，保证一键复现一致；如需调整直接改这里即可）
os.environ["P3_REC"] = "1"        # 追索变量（问题 2 两阶段）
os.environ["P3_GMAX"] = "20000"   # 购电无上界（大数，实际不触发；峰值约 10,443 kW << 20000）
os.environ["P3_SENT"] = "1"       # 同时输出完美预见哨兵
os.environ["P3_WRITE"] = "1"      # 写 result3 xlsx
os.environ["P3_OUT"] = os.path.join(HERE, "result3_recourse_unbounded.xlsx")

runpy.run_path(os.path.join(HERE, "problem3_v3_recourse.py"), run_name="__main__")
