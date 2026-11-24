from datetime import datetime, timezone
from app.db import 连接

建表 = """
CREATE TABLE IF NOT EXISTS 轨规 (
  键 TEXT PRIMARY KEY,
  值 TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS 源登记 (
  源键 TEXT PRIMARY KEY,
  轨别 TEXT NOT NULL,
  名称 TEXT NOT NULL,
  说明 TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS 左轨流水 (
  事件编号 TEXT PRIMARY KEY,
  业务键 TEXT NOT NULL,
  金额分 INTEGER NOT NULL,
  源键 TEXT NOT NULL,
  事件时 TEXT NOT NULL,
  处理时 TEXT NOT NULL,
  命运 TEXT NOT NULL DEFAULT '已入左',
  批次编号 TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS 右轨流水 (
  事件编号 TEXT PRIMARY KEY,
  业务键 TEXT NOT NULL,
  金额分 INTEGER NOT NULL,
  源键 TEXT NOT NULL,
  事件时 TEXT NOT NULL,
  处理时 TEXT NOT NULL,
  命运 TEXT NOT NULL DEFAULT '已入右',
  批次编号 TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS 对齐差 (
  编号 INTEGER PRIMARY KEY AUTOINCREMENT,
  业务键 TEXT NOT NULL,
  左金额分 INTEGER,
  右金额分 INTEGER,
  差型 TEXT NOT NULL,
  说明 TEXT NOT NULL DEFAULT '',
  时刻 TEXT NOT NULL,
  粒度 TEXT NOT NULL DEFAULT '汇总',
  事件编号 TEXT NOT NULL DEFAULT '',
  物化包 TEXT NOT NULL DEFAULT '',
  轮次 TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS 对齐差物化 (
  编号 INTEGER PRIMARY KEY AUTOINCREMENT,
  物化包 TEXT NOT NULL,
  轮次 TEXT NOT NULL,
  业务键 TEXT NOT NULL,
  左事件 TEXT NOT NULL DEFAULT '',
  右事件 TEXT NOT NULL DEFAULT '',
  左金额分 INTEGER,
  右金额分 INTEGER,
  差型 TEXT NOT NULL,
  说明 TEXT NOT NULL DEFAULT '',
  时刻 TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS 悬账单 (
  编号 INTEGER PRIMARY KEY AUTOINCREMENT,
  业务键 TEXT NOT NULL,
  悬边 TEXT NOT NULL,
  金额分 INTEGER NOT NULL,
  事件编号 TEXT NOT NULL DEFAULT '',
  原因 TEXT NOT NULL,
  时刻 TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS 对拍结论 (
  编号 INTEGER PRIMARY KEY AUTOINCREMENT,
  时刻 TEXT NOT NULL,
  左笔数 INTEGER NOT NULL,
  右笔数 INTEGER NOT NULL,
  对齐笔数 INTEGER NOT NULL,
  悬账笔数 INTEGER NOT NULL,
  是否通过 INTEGER NOT NULL,
  说明 TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS 装载批次 (
  编号 TEXT PRIMARY KEY,
  轨别 TEXT NOT NULL,
  时刻 TEXT NOT NULL,
  报告 TEXT NOT NULL DEFAULT '{}'
);
"""


def 此刻() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _补列(conn) -> None:
    """旧库补列：对齐差新增粒度/事件编号/物化包/轮次，保持只读兼容。"""
    现有 = {r["name"] for r in conn.execute("PRAGMA table_info(对齐差)").fetchall()}
    for 名, 定义 in (
        ("粒度", "TEXT NOT NULL DEFAULT '汇总'"),
        ("事件编号", "TEXT NOT NULL DEFAULT ''"),
        ("物化包", "TEXT NOT NULL DEFAULT ''"),
        ("轮次", "TEXT NOT NULL DEFAULT ''"),
    ):
        if 名 not in 现有:
            conn.execute(f"ALTER TABLE 对齐差 ADD COLUMN {名} {定义}")


建索引 = """
CREATE INDEX IF NOT EXISTS 对齐差物化_包 ON 对齐差物化(物化包);
CREATE INDEX IF NOT EXISTS 对齐差物化_轮次 ON 对齐差物化(轮次);
CREATE INDEX IF NOT EXISTS 对齐差_物化包 ON 对齐差(物化包);
CREATE INDEX IF NOT EXISTS 对齐差_轮次 ON 对齐差(轮次);
"""


def 初始化库() -> None:
    conn = 连接()
    conn.executescript(建表)
    _补列(conn)
    # 索引须在补列之后建：旧库先补 物化包/轮次 列，否则建索引会报缺列。
    conn.executescript(建索引)
    if conn.execute("SELECT COUNT(*) AS c FROM 轨规").fetchone()["c"] == 0:
        for k, v in {
            "站名": "对拍",
            "对齐键": "业务键",
            "金额容差分": "0",
            "骨架": "左轨装载→右轨装载→同键对齐落差→单边悬账→对拍结论",
            "皮": "支付渠道回执 vs 核心记账",
            "去皮": "双源键对齐管道",
        }.items():
            conn.execute("INSERT INTO 轨规(键, 值) VALUES (?, ?)", (k, v))
    if conn.execute("SELECT COUNT(*) AS c FROM 源登记").fetchone()["c"] == 0:
        conn.execute(
            "INSERT INTO 源登记(源键,轨别,名称,说明) VALUES (?,?,?,?)",
            ("渠甲", "左", "渠道回执甲", "支付渠道回执流"),
        )
        conn.execute(
            "INSERT INTO 源登记(源键,轨别,名称,说明) VALUES (?,?,?,?)",
            ("核乙", "右", "核心记账乙", "核心系统记账流"),
        )
    conn.commit()
    conn.close()
