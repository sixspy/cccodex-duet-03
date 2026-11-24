"""同键多笔汇总：双源入库后的键对齐编排。

两种形态，跑对齐前择定，写差与读集合全程按同一形态：
- 形态甲 `汇总`（折叠）：同键金额先加总再比，对齐差一键一行。
- 形态乙 `逐笔`（展开）：按事件逐笔物化对照，键下多行，
  逐笔写入「对齐差物化」包，读集合按物化包回读。

并发：择定形态、写差、写悬账、写物化包在同一 `BEGIN IMMEDIATE` 事务内，
补装与对齐串行化，避免双成功 / 双写差行 / 双粒度。
"""
from __future__ import annotations

import uuid

from app.db import 连接
from app.seed import 此刻

汇总 = "汇总"
逐笔 = "逐笔"

形态别名 = {
    "汇总": 汇总,
    "折叠": 汇总,
    "形态甲": 汇总,
    "键汇总": 汇总,
    "逐笔": 逐笔,
    "展开": 逐笔,
    "形态乙": 逐笔,
    "物化": 逐笔,
}

形态说明 = {
    汇总: "形态甲·键汇总：同键金额先加总再比，对齐差一键一行",
    逐笔: "形态乙·事件逐笔：键下逐笔物化对照，对齐差一键多行，按物化包回读",
}

轨规形态键 = "同键形态"
轨规轮次键 = "同键轮次"


def 形态选项() -> list[dict]:
    return [{"形态": 名, "说明": 形态说明[名]} for 名 in (汇总, 逐笔)]


def 归一形态(值: object) -> str | None:
    键 = str(值 or "").strip()
    if not 键:
        return None
    return 形态别名.get(键)


def _读轨规(conn, 键: str) -> str | None:
    行 = conn.execute("SELECT 值 FROM 轨规 WHERE 键=?", (键,)).fetchone()
    return 行["值"] if 行 else None


def _写轨规(conn, 键: str, 值: str) -> None:
    conn.execute(
        "INSERT INTO 轨规(键, 值) VALUES (?, ?) ON CONFLICT(键) DO UPDATE SET 值=excluded.值",
        (键, 值),
    )


def 当前形态() -> dict:
    """只读：返回当前择定的形态与轮次。未择定时形态为 None。"""
    conn = 连接()
    try:
        形态 = 归一形态(_读轨规(conn, 轨规形态键))
        轮次 = _读轨规(conn, 轨规轮次键)
        return {
            "形态": 形态,
            "形态标记": 形态 or "",
            "说明": 形态说明.get(形态, "尚未择定同键多笔形态"),
            "轮次": 轮次 or "",
            "已择定": 形态 is not None,
        }
    finally:
        conn.close()


def 择定形态(形态: object) -> dict:
    """跑对齐前择定折叠 / 展开形态。落库加锁，后续读集合按此形态回读。"""
    选定 = 归一形态(形态)
    if 选定 is None:
        return {"ok": False, "错误": f"未知形态：{形态!r}，可选：{' / '.join((汇总, 逐笔))}"}
    conn = 连接()
    try:
        conn.execute("BEGIN IMMEDIATE")
        _写轨规(conn, 轨规形态键, 选定)
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()
    return {"ok": True, **当前形态()}


def _事件序(行: dict) -> tuple[str, str]:
    return (行["事件时"], 行["事件编号"])


def _插差(
    conn,
    业务键: str,
    左金额分: int | None,
    右金额分: int | None,
    差型: str,
    说明: str,
    时刻: str,
    粒度: str,
    事件编号: str,
    物化包: str,
    轮次: str,
) -> None:
    conn.execute(
        """INSERT INTO 对齐差
           (业务键,左金额分,右金额分,差型,说明,时刻,粒度,事件编号,物化包,轮次)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (业务键, 左金额分, 右金额分, 差型, 说明, 时刻, 粒度, 事件编号, 物化包, 轮次),
    )


def _插悬(
    conn,
    业务键: str,
    悬边: str,
    金额分: int,
    事件编号: str,
    原因: str,
    时刻: str,
) -> None:
    conn.execute(
        "INSERT INTO 悬账单(业务键,悬边,金额分,事件编号,原因,时刻) VALUES (?,?,?,?,?,?)",
        (业务键, 悬边, 金额分, 事件编号, 原因, 时刻),
    )


def _插物化(
    conn,
    物化包: str,
    轮次: str,
    业务键: str,
    左事件: str,
    右事件: str,
    左金额分: int | None,
    右金额分: int | None,
    差型: str,
    说明: str,
    时刻: str,
) -> None:
    conn.execute(
        """INSERT INTO 对齐差物化
           (物化包,轮次,业务键,左事件,右事件,左金额分,右金额分,差型,说明,时刻)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (物化包, 轮次, 业务键, 左事件, 右事件, 左金额分, 右金额分, 差型, 说明, 时刻),
    )


def _折键(conn, 键, 左行, 右行, 容差, 时刻, 轮次) -> tuple[int, int, int]:
    """形态甲：一键一行。返回 (对齐数, 非对齐差行数, 悬账数)。"""
    左代表 = max(左行, key=_事件序)["事件编号"] if 左行 else ""
    右代表 = max(右行, key=_事件序)["事件编号"] if 右行 else ""
    左额 = sum(int(r["金额分"]) for r in 左行) if 左行 else None
    右额 = sum(int(r["金额分"]) for r in 右行) if 右行 else None
    对齐 = 差 = 悬 = 0
    if 左行 and 右行:
        if abs(int(左额) - int(右额)) <= 容差:
            _插差(
                conn, 键, 左额, 右额, "对齐", "双边金额在容差内（键汇总）",
                时刻, 汇总, 左代表, "", 轮次,
            )
            对齐 += 1
        else:
            _插差(
                conn, 键, 左额, 右额, "金额不符", f"左{左额}-右{右额}",
                时刻, 汇总, 左代表, "", 轮次,
            )
            差 += 1
    elif 左行:
        _插差(
            conn, 键, 左额, None, "右缺", "仅左轨有键",
            时刻, 汇总, 左代表, "", 轮次,
        )
        _插悬(conn, 键, "左", int(左额), 左代表, "右轨缺键", 时刻)
        差 += 1
        悬 += 1
    else:
        _插差(
            conn, 键, None, 右额, "左缺", "仅右轨有键",
            时刻, 汇总, 右代表, "", 轮次,
        )
        _插悬(conn, 键, "右", int(右额), 右代表, "左轨缺键", 时刻)
        差 += 1
        悬 += 1
    return 对齐, 差, 悬


def _展键(conn, 键, 左行, 右行, 容差, 时刻, 轮次) -> tuple[int, int, int, int]:
    """形态乙：逐笔物化，键下多行。返回 (对齐数, 非对齐差行数, 悬账数, 物化行数)。"""
    左行 = sorted(左行, key=_事件序)
    右行 = sorted(右行, key=_事件序)
    物化包 = f"{轮次}|{键}"
    对齐 = 差 = 悬 = 物化 = 0
    for i in range(max(len(左行), len(右行))):
        l = 左行[i] if i < len(左行) else None
        r = 右行[i] if i < len(右行) else None
        左事件 = l["事件编号"] if l else ""
        右事件 = r["事件编号"] if r else ""
        左额 = int(l["金额分"]) if l else None
        右额 = int(r["金额分"]) if r else None
        if l and r:
            if abs(左额 - 右额) <= 容差:
                差型, 说明 = "对齐", f"逐笔 {左事件}↔{右事件} 在容差内"
                对齐 += 1
            else:
                差型, 说明 = "金额不符", f"逐笔 左{左额}-右{右额}"
                差 += 1
        elif l:
            差型, 说明 = "右缺", f"逐笔 {左事件} 右轨缺事件"
            差 += 1
            悬 += 1
        else:
            差型, 说明 = "左缺", f"逐笔 {右事件} 左轨缺事件"
            差 += 1
            悬 += 1
        _插差(
            conn, 键, 左额, 右额, 差型, 说明,
            时刻, 逐笔, 左事件 or 右事件, 物化包, 轮次,
        )
        _插物化(
            conn, 物化包, 轮次, 键, 左事件, 右事件,
            左额, 右额, 差型, 说明, 时刻,
        )
        物化 += 1
        if l and not r:
            _插悬(conn, 键, "左", 左额, 左事件, "逐笔右轨缺事件", 时刻)
        elif r and not l:
            _插悬(conn, 键, "右", 右额, 右事件, "逐笔左轨缺事件", 时刻)
    return 对齐, 差, 悬, 物化


def 跑对齐(形态: object = None) -> dict:
    """键对齐编排主链：择定形态 → 加锁清空 → 按形态写差 → 同成同败提交。"""
    入参形态 = 归一形态(形态)
    if 形态 not in (None, "") and 入参形态 is None:
        return {
            "ok": False,
            "错误": f"未知形态：{形态!r}，可选：{' / '.join((汇总, 逐笔))}",
        }

    conn = 连接()
    try:
        conn.execute("BEGIN IMMEDIATE")
        已存 = 归一形态(_读轨规(conn, 轨规形态键))
        if 入参形态 is not None:
            选定 = 入参形态
            来源 = "入参"
        elif 已存 is not None:
            选定 = 已存
            来源 = "轨规"
        else:
            选定 = 汇总
            来源 = "默认"
        轮次 = f"轮-{此刻()}-{uuid.uuid4().hex[:6]}"
        容差行 = _读轨规(conn, "金额容差分")
        容差 = int(容差行 or "0")

        # 清空上次对齐结果；与下面的写差同事务，避免半截对齐。
        conn.execute("DELETE FROM 对齐差")
        conn.execute("DELETE FROM 悬账单")
        conn.execute("DELETE FROM 对齐差物化")
        # 形态与轮次随本次写差一起落库：形态、差行、代表事件同成同败。
        _写轨规(conn, 轨规形态键, 选定)
        _写轨规(conn, 轨规轮次键, 轮次)

        左表: dict[str, list] = {}
        for r in conn.execute("SELECT * FROM 左轨流水 WHERE 命运='已入左'").fetchall():
            左表.setdefault(r["业务键"], []).append(r)
        右表: dict[str, list] = {}
        for r in conn.execute("SELECT * FROM 右轨流水 WHERE 命运='已入右'").fetchall():
            右表.setdefault(r["业务键"], []).append(r)

        所有键 = sorted(set(左表) | set(右表))
        对齐 = 差 = 悬 = 物化 = 0
        时刻 = 此刻()

        for 键 in 所有键:
            左行 = 左表.get(键, [])
            右行 = 右表.get(键, [])
            if 选定 == 逐笔:
                a, d, h, m = _展键(conn, 键, 左行, 右行, 容差, 时刻, 轮次)
                对齐 += a
                差 += d
                悬 += h
                物化 += m
            else:
                a, d, h = _折键(conn, 键, 左行, 右行, 容差, 时刻, 轮次)
                对齐 += a
                差 += d
                悬 += h

        conn.commit()
        return {
            "ok": True,
            "键总数": len(所有键),
            "形态": 选定,
            "形态标记": 选定,
            "形态来源": 来源,
            "形态说明": 形态说明[选定],
            "轮次": 轮次,
            "对齐": 对齐,
            "差与悬": 差,
            "差行": 对齐 + 差,
            "悬账": 悬,
            "物化行": 物化,
            "容差分": 容差,
            "时刻": 时刻,
        }
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def 粒度摘要() -> dict:
    """只读：按业务键给出 左笔数 / 右笔数 / 差行数 / 形态标记 / valid。"""
    conn = 连接()
    try:
        形态 = 归一形态(_读轨规(conn, 轨规形态键))
        轮次 = _读轨规(conn, 轨规轮次键) or ""
        左数: dict[str, int] = {}
        for r in conn.execute(
            "SELECT 业务键, COUNT(*) AS c FROM 左轨流水 WHERE 命运='已入左' GROUP BY 业务键"
        ).fetchall():
            左数[r["业务键"]] = r["c"]
        右数: dict[str, int] = {}
        for r in conn.execute(
            "SELECT 业务键, COUNT(*) AS c FROM 右轨流水 WHERE 命运='已入右' GROUP BY 业务键"
        ).fetchall():
            右数[r["业务键"]] = r["c"]
        差行: dict[str, list[dict]] = {}
        for r in conn.execute(
            "SELECT 业务键, 差型, 粒度, 物化包 FROM 对齐差 ORDER BY 编号"
        ).fetchall():
            差行.setdefault(r["业务键"], []).append(dict(r))

        键表 = []
        for 键 in sorted(set(左数) | set(右数) | set(差行)):
            行列 = 差行.get(键, [])
            粒度集 = {x["粒度"] for x in 行列} if 行列 else set()
            if len(粒度集) > 1:
                标记 = "混合"
            elif 粒度集:
                标记 = next(iter(粒度集))
            else:
                标记 = 形态 or ""
            l, rr = 左数.get(键, 0), 右数.get(键, 0)
            差行数 = len(行列)
            valid = True
            if 形态 is None or 差行数 == 0 or 粒度集 != {形态}:
                valid = False
            elif 形态 == 汇总:
                valid = 差行数 == 1
            else:
                valid = 差行数 == max(l, rr) and all(x["物化包"] for x in 行列)
            键表.append({
                "业务键": 键,
                "左笔数": l,
                "右笔数": rr,
                "差行数": 差行数,
                "形态标记": 标记,
                "valid": valid,
            })

        有效键数 = sum(1 for x in 键表 if x["valid"])
        return {
            "形态": 形态,
            "形态标记": 形态 or "",
            "说明": 形态说明.get(形态, "尚未择定同键多笔形态"),
            "轮次": 轮次,
            "键": 键表,
            "总数": len(键表),
            "有效键数": 有效键数,
            "无效键数": len(键表) - 有效键数,
            "valid": len(键表) == 0 or 有效键数 == len(键表),
        }
    finally:
        conn.close()


def 物化包回读(包: str) -> dict:
    """只读：形态乙读集合按物化包回读，与汇总口径不同。"""
    conn = 连接()
    try:
        行 = conn.execute(
            "SELECT * FROM 对齐差物化 WHERE 物化包=? ORDER BY 编号", (包,)
        ).fetchall()
        return {"物化包": 包, "条数": len(行), "行": [dict(r) for r in 行]}
    finally:
        conn.close()


def 物化包列表() -> dict:
    """只读：当前轮次下的全部物化包行，供逐笔列表回读。"""
    conn = 连接()
    try:
        轮次 = _读轨规(conn, 轨规轮次键) or ""
        行 = conn.execute(
            "SELECT * FROM 对齐差物化 WHERE 轮次=? ORDER BY 编号", (轮次,)
        ).fetchall()
        return {
            "轮次": 轮次,
            "条数": len(行),
            "包数": len({r["物化包"] for r in 行}),
            "行": [dict(r) for r in 行],
        }
    finally:
        conn.close()
