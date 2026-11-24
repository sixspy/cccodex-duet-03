"""同业务键对齐：双边金额比对，落对齐差 + 悬账单。

同键多笔的折叠/展开形态由 `同键多笔汇总` 编排；本服务只保留入口，
保证差表粒度与当次形态同票。
"""
from __future__ import annotations

from app.modules import 同键多笔汇总


def 跑对齐(形态: object = None) -> dict:
    return 同键多笔汇总.跑对齐(形态)
