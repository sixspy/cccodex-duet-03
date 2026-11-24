import os
import threading
from pathlib import Path

_tmp = Path(__file__).resolve().parent / "_tmp_同键"
_tmp.mkdir(exist_ok=True)
os.environ["数据目录"] = str(_tmp)
os.environ["夹具目录"] = str(Path(__file__).resolve().parents[2] / "fixtures")

from app import seed
from app.db import 连接
from app.services import 左装载, 右装载, 对齐, 结论
from app.modules import 同键多笔汇总

def setup_function():
    db = _tmp / "对拍.db"
    if db.exists():
        db.unlink()
    seed.初始化库()

def _左(事件):
    左装载.装一批({"事件": [
        {"事件编号": n, "业务键": k, "金额分": a, "源键": "渠甲", "事件时": t}
        for n, k, a, t in 事件
    ]})

def _右(事件):
    右装载.装一批({"事件": [
        {"事件编号": n, "业务键": k, "金额分": a, "源键": "核乙", "事件时": t}
        for n, k, a, t in 事件
    ]})

def _差(键):
    conn = 连接()
    try:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM 对齐差 WHERE 业务键=? ORDER BY 编号", (键,)
        ).fetchall()]
    finally:
        conn.close()

def test_同键左两笔右一笔_汇总一行_逐笔多行():
    # 左两笔共 300，右一笔 300：汇总对齐；逐笔一成一缺
    _左([("L1", "K1", 100, "2026-11-23T10:00:00Z"),
         ("L2", "K1", 200, "2026-11-23T10:00:01Z")])
    _右([("R1", "K1", 300, "2026-11-23T10:00:02Z")])

    r = 对齐.跑对齐("汇总")
    assert r["形态"] == "汇总"
    行 = _差("K1")
    assert len(行) == 1
    assert 行[0]["差型"] == "对齐"
    assert 行[0]["左金额分"] == 300 and 行[0]["右金额分"] == 300
    assert 行[0]["粒度"] == "汇总"

    r2 = 对齐.跑对齐("逐笔")
    assert r2["形态"] == "逐笔"
    行2 = _差("K1")
    assert len(行2) == 2
    assert all(x["粒度"] == "逐笔" for x in 行2)
    assert all(x["物化包"] for x in 行2)
    # 逐笔按事件时逐位配对：L1↔R1 金额不符，L2 无对位右缺
    assert {x["差型"] for x in 行2} == {"金额不符", "右缺"}
    assert [x["事件编号"] for x in 行2] == ["L1", "L2"]
    assert r2["物化行"] == 2

    # 读集合按物化包回读
    包 = 行2[0]["物化包"]
    back = 同键多笔汇总.物化包回读(包)
    assert back["条数"] == 2

def test_单笔双边两形态均一行():
    _左([("L1", "S1", 500, "2026-11-23T10:00:00Z")])
    _右([("R1", "S1", 500, "2026-11-23T10:00:01Z")])
    for 形态 in ("汇总", "逐笔"):
        对齐.跑对齐(形态)
        assert len(_差("S1")) == 1, 形态
        assert _差("S1")[0]["差型"] == "对齐"

def test_三笔左两笔右_差行数区分():
    _左([("L1", "T1", 100, "2026-11-23T10:00:00Z"),
         ("L2", "T1", 100, "2026-11-23T10:00:01Z"),
         ("L3", "T1", 100, "2026-11-23T10:00:02Z")])
    _右([("R1", "T1", 300, "2026-11-23T10:00:03Z"),
         ("R2", "T1", 0, "2026-11-23T10:00:04Z")])
    对齐.跑对齐("汇总")
    assert len(_差("T1")) == 1
    对齐.跑对齐("逐笔")
    assert len(_差("T1")) == 3  # max(3,2)

def test_粒度只读接口():
    _左([("L1", "K1", 100, "2026-11-23T10:00:00Z"),
         ("L2", "K1", 200, "2026-11-23T10:00:01Z")])
    _右([("R1", "K1", 300, "2026-11-23T10:00:02Z")])
    对齐.跑对齐("汇总")
    g = 同键多笔汇总.粒度摘要()
    assert g["形态"] == "汇总"
    assert g["valid"] is True
    k = g["键"][0]
    assert (k["业务键"], k["左笔数"], k["右笔数"], k["差行数"], k["形态标记"], k["valid"]) == \
        ("K1", 2, 1, 1, "汇总", True)

    对齐.跑对齐("逐笔")
    g2 = 同键多笔汇总.粒度摘要()
    k2 = g2["键"][0]
    assert (k2["差行数"], k2["形态标记"], k2["valid"]) == (2, "逐笔", True)

def test_择形校验():
    assert 同键多笔汇总.择定形态("未知")["ok"] is False
    assert 同键多笔汇总.择定形态("展开")["形态"] == "逐笔"
    assert 同键多笔汇总.当前形态()["已择定"] is True

def test_补装与对齐并发不双粒度():
    _左([("L1", "C1", 100, "2026-11-23T10:00:00Z")])
    _右([("R1", "C1", 100, "2026-11-23T10:00:01Z")])
    对齐.跑对齐("逐笔")

    错 = []

    def 补装():
        try:
            左装载.装一批({"事件": [
                {"事件编号": "L2", "业务键": "C1", "金额分": 50,
                 "源键": "渠甲", "事件时": "2026-11-23T10:00:02Z"},
            ]})
        except Exception as e:  # noqa: BLE001
            错.append(e)

    def 跑():
        try:
            对齐.跑对齐("逐笔")
        except Exception as e:  # noqa: BLE001
            错.append(e)

    ts = [threading.Thread(target=补装), threading.Thread(target=跑)]
    for t in ts: t.start()
    for t in ts: t.join()
    assert not 错, 错

    g = 同键多笔汇总.粒度摘要()
    assert g["形态"] == "逐笔"
    assert all(x["形态标记"] == "逐笔" for x in g["键"]), g
    # 并发窗口内锁串行化：不得双写差行（差行数不超过当次 max(左右笔数)），
    # 也不得出现混合粒度。
    for k in g["键"]:
        assert k["差行数"] <= max(k["左笔数"], k["右笔数"]), k

    # 补装落地后重跑一次对齐，粒度回到一致
    对齐.跑对齐("逐笔")
    g2 = 同键多笔汇总.粒度摘要()
    assert g2["valid"] is True, g2
    for k in g2["键"]:
        assert k["差行数"] == max(k["左笔数"], k["右笔数"]), k

def test_结论在逐笔形态下自洽():
    _左([("L1", "K1", 100, "2026-11-23T10:00:00Z"),
         ("L2", "K1", 200, "2026-11-23T10:00:01Z")])
    _右([("R1", "K1", 300, "2026-11-23T10:00:02Z")])
    对齐.跑对齐("逐笔")
    g = 结论.跑一次()
    assert g["是否通过"] is True, g
    assert g["形态"] == "逐笔"
