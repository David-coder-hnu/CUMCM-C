# -*- coding: utf-8 -*-
"""在**同一进程内**拿到"已按交付配置初始化"的 `problem4_3` 模块 —— 供需要 monkeypatch
的优化实验用（`_p4_delivery.py` 的 docstring 只给了 subprocess 用法，那只够跑黑盒）。

为什么不能直接 `os.environ.update(D.delivery()[0]); import problem4_3`
------------------------------------------------------------------
`_p4_delivery.delivery()` 为了读 `problem4_3._DELIVERY`，**自己会 import 一次
`problem4_3`**。那一次 import 把模块对象钉进了 `sys.modules`，而且是在**缺省环境**下
执行的 —— 于是后一句 `import problem4_3 as P` 拿到的是缓存，所有 `P4_*` 全部还是缺省值。
实测：`is_delivery()` 报 False，总费 14,790,954.05（缺省 `P4_GMAX=5000`）而不是
交付的 14,257,306 —— **一个不报错、只是安静跑在别的配置上的假阴性**，
正是本项目反复踩的那类坑（归档 §6.4 陷阱 8）。
⚠ 反过来说：**凡是"先 import 过 problem4_3、再改 env、再 import"的写法都不可信**，
即便它跑得出一个看着合理的数。`diag_p4_audit.py` / `diag_p4_oracle.py` 都因此
量错过一整个 §7.5 分解（症状：哨兵印成 `G≤5000` 格的 13,014,628）。

故本模块的顺序是：**先取 env → 写进 os.environ → 再 reload 模块**，让那些
`os.environ.get` 在 reload 时读到交付值。reload 会重读四个附件（约 4 秒），
相对一次 18 秒的求解可忽略。

用法
------------------------------------------------------------------
    import _p4_env as E
    P = E.load()                       # 交付配置，已断言 is_delivery()
    P = E.load(P4_TAUB="0.50,0.48,0.48,0.48")   # 交付形状 + 覆写 τ
    P = E.load(delivery=False)         # 不套交付 env（缺省旋钮），仅调试用

⚠ `load()` 默认会 **断言 `P.is_delivery()`**，并在覆写 τ 时自动跳过该断言
  （那时 τ 已不是交付 τ，`is_delivery()` 按设计就该为假）。写盘一律关掉。
"""
import importlib
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CODE = os.path.join(BASE, "代码")
DIAG = os.path.join(BASE, "代码", "诊断")
for _p in (CODE, DIAG):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def delivery_env(**over):
    """交付 env（字符串字典）+ 调用方的覆写。**不导入 problem4_3 的调用方适用。**

    ⚠ 必须走 `_p4_delivery.delivery_env()`（= `dict(os.environ)` + 覆写），
      **不能**用 `_p4_delivery.delivery()[0]` —— 那是个**只含 P4_\*** 的最小环境。
      本函数第一版就是那样写的，于是子进程在没有 `SystemRoot` / `PATH` 的环境里启动，
      直接 `Fatal Python error: _Py_HashRandomization_Init: failed to get random
      numbers to initialize Python`，返回码 1、stdout 空 ⇒ 上层看到的是"这一格算不出来"。
      这与 `_p4_delivery.py` 自己的 docstring 里逐字警告过的是**同一个坑**，
      本项目在 `diag_p4_readings.py` / `diag_p4_cross_abl.py` 也各犯过一次。
    """
    import _p4_delivery as D
    env = D.delivery_env()
    env.update(P4_WRITE="0", P4_NOWRITE="1", PYTHONIOENCODING="utf-8")
    env.update({k: str(v) for k, v in over.items()})
    return env


def load(delivery=True, strict=None, **over):
    """返回**已按给定 env 重新初始化**的 `problem4_3` 模块。

    delivery=False → 不套交付 env（用缺省旋钮 + over），仅用于对照/调试。
    strict         → 是否断言 `is_delivery()`；缺省 = 没覆写 τ 且用了交付 env。
    """
    env = delivery_env(**over) if delivery else {
        **{k: str(v) for k, v in os.environ.items()},
        "P4_WRITE": "0", "P4_NOWRITE": "1", "PYTHONIOENCODING": "utf-8",
        **{k: str(v) for k, v in over.items()}}
    os.environ.update(env)
    # 清掉 P4_TAU / P4_TAUB 的**互斥**残留：求解器对"两者同时给出"直接 SystemExit，
    # 而 env 是进程级累积的 —— 上一轮实验设过 P4_TAUB，这一轮若设 P4_TAU 就会误触。
    if "P4_TAU" in over and "P4_TAUB" not in over:
        os.environ.pop("P4_TAUB", None)
    if "P4_TAUB" in over and "P4_TAU" not in over:
        os.environ.pop("P4_TAU", None)

    import problem4_3 as P
    P = importlib.reload(P)

    if strict is None:
        strict = delivery and "P4_TAUB" not in over and "P4_TAU" not in over
    if strict and not P.is_delivery():
        raise AssertionError(
            "❌ 夹具没拿到交付配置 —— 旋钮与 _DELIVERY 不一致：\n     "
            + "  ".join(P.delivery_knobs()))
    return P


def knobs_diff(P):
    """当前旋钮 vs 交付旋钮的差异清单（自检报错时看这个）。"""
    import _p4_delivery as D
    d = D.delivery()[0]
    cur = dict(x.split("=", 1) for x in P.delivery_knobs())
    out = []
    for k, v in sorted(cur.items()):
        w = d.get(k)
        if w is not None and w != v:
            out.append("%s: 交付 %s → 实得 %s" % (k, w, v))
    return out
