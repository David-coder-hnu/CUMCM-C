# -*- coding: utf-8 -*-
"""把 `problem4_3._DELIVERY` 翻成 env 字符串 —— 各诊断脚本取"交付配置"的**唯一真源**。

    import _p4_delivery as D
    env, info = D.delivery()
    env.update(P4_WRITE="0", P4_NOWRITE="1")
    ... subprocess.run(..., env=env)        # 只设 os.environ 的用这个

    env = D.delivery_env()                  # 要传给 subprocess 的用这个（含完整环境）

⚠⚠ **要在本进程内 monkeypatch 求解器的调用方，别用上面的写法** —— 用 `_p4_env.load()`。
  因为 `delivery()` 为了读 `_DELIVERY` **自己会 import 一次 `problem4_3`**，那一次是在
  **缺省环境**下跑的，模块对象被钉进 `sys.modules`；此后 `os.environ.update(...)` +
  `import problem4_3` 拿到的是**缓存**，旋钮全还是缺省值。症状是 `P.G_MAX` 停在 5,000
  而不是 20,000，**不报错，只是安静跑在另一个配置上**。`_p4_env.load()` 的修法是
  "先写 env、再 `importlib.reload`"，并在末位断言 `is_delivery()`。
  实例：`diag_p4_audit.py` 与 `diag_p4_oracle.py` 都曾因它把整张表建在 `G≤5000` 上
  （哨兵 13,014,628 而非 12,782,592）。

为什么要有这个文件
------------------------------------------------------------------
交付 τ **会变**。2026-09-12 之前它逐位继承问题 3（受控对照），此后改为**本问自己的
最优**（五维搜索，见 `diag_p4_tau_opt.py`）。而诊断脚本里有五六处把交付 τ 当字面量
抄了一遍：

    P4_TAUB="0.55,0.42,0.42,0.42", P4_TAUP="0.42"

τ 一改，这些副本**不会报错**，只会安静地跑在"看起来像交付、其实不是"的配置上，
而输出标题仍印着「交付配置」—— 本项目反复踩的那类静默错位（归档 §6.4）。
故此处不做副本，改为从解算器本身读，改 τ 只需改 `problem4_3._DELIVERY` 一处。

⚠ 本模块**只读常量**，不跑求解：`problem4_3` 的求解全部在 `main()` 里、由
  `__main__` 触发，导入它只读盘建数组（数秒）。导入时也**没有**替换 `sys.stdout`
  （只 `reconfigure`），故对调用方无副作用；导入期的横幅仍会被压掉，免得污染
  各诊断脚本自己攒的 `_p4_*.txt`。
"""
import contextlib
import io
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_CODE = os.path.join(BASE, "代码")


def delivery(pin_tau=None):
    """交付配置的 env 字符串字典，外加一份便于打印的 info。

    pin_tau: 若给定 `(taub_list, taup)`，则 **τ 用给的那份**而不是交付 τ。
             失同步自检/常数价回归要用**与问题 3 共享的 τ**，那是另一个量
             （`problem4_3._SHARED_TAU`），不能拿交付 τ 去顶。
    """
    if _CODE not in sys.path:
        sys.path.insert(0, _CODE)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        import problem4_3 as P
    d = P._DELIVERY
    taub, taup = (list(d["taub"]), d["taup"]) if pin_tau is None else pin_tau
    env = dict(P4_REC="1" if d["rec"] else "0", P4_GMAX="%g" % d["gmax"],
               P4_TAUB=",".join("%g" % x for x in taub), P4_TAUP="%g" % taup,
               P4_READING=d["reading"], P4_WQ="1" if d["wq"] else "0",
               P4_PSCALE="%g" % d["pscale"], P4_PRICE_SRC=d["price_src"],
               P4_GSPAN="%d" % d["span"], P4_LEVEL="1" if d["level"] else "0",
               P4_BANDS="%d" % d["bands"], P4_ANCHOR=d["anchor"],
               P4_ADJ="1" if d["adj"] else "0", P4_PLAN=d["plan"],
               P4_EXEC=d["exec_"], P4_LAMS=",".join("%g" % x for x in d["lams"]),
               # 跑多长/多细的四个旋钮也**显式给全**。它们缺省恰好等于交付值，但
               # `is_shape()` 现在会检查它们 —— 靠缺省就等于"这一跑算不算交付"
               # 取决于调用方有没有恰好继承到干净环境（§6.4 陷阱 4）。
               P4_DAYS="%d" % d["days"], P4_MINR="%d" % d["minr"],
               P4_RES="%d" % d["res"], P4_H="%d" % d["h"],
               PYTHONIOENCODING="utf-8")
    return env, dict(taub=taub, taup=taup,
                     taub_str=",".join("%g" % x for x in taub),
                     taup_str="%g" % taup,
                     pinned=pin_tau is not None)


def delivery_env(pin_tau=None):
    """`os.environ` 的副本 + 交付配置覆写 —— 可直接拿去 `subprocess.run(env=...)`。

    ⚠ **不要**把 `delivery()` 的返回值直接当 `env=` 用：那是个只含 P4_* 的**最小环境**，
      子进程会在没有 PATH / SystemRoot 的环境里启动。Windows 下多数时候"看起来能跑"，
      但那是运气，不是保证 —— 本项目在 `diag_p4_readings.py` / `diag_p4_cross_abl.py`
      两处都这么写过，此处统一收口。
    """
    e = dict(os.environ)
    e.update(delivery(pin_tau)[0])
    return e


def delivery_total():
    """声明的交付总费（= `problem4_3._DELIVERY["total"]`）。

    ⚠ 这个数**会被 `problem4_3.__main__` 硬校验**（实得 ≠ 声明就 SystemExit(1)），
      所以诊断脚本引用它比自己抄一个字面量安全。
    """
    if _CODE not in sys.path:
        sys.path.insert(0, _CODE)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        import problem4_3 as P
    return float(P._DELIVERY["total"])


def shared_tau():
    """**与问题 3 共享的 τ**（= 常数价回归/失同步自检该站的那一点）。"""
    if _CODE not in sys.path:
        sys.path.insert(0, _CODE)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        import problem4_3 as P
    s = P._SHARED_TAU
    return list(s["taub"]), s["taup"]
