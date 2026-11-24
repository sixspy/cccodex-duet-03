from fastapi import APIRouter, HTTPException
from app.services import 目录, 左装载, 右装载, 对齐, 结论, 夹具, 统计, 说明
from app.modules import 同键多笔汇总

路由 = APIRouter()

@路由.get("/api/概览")
def api_概览():
    return 目录.概览()

@路由.get("/api/轨规")
def api_轨规():
    return 目录.轨规()

@路由.post("/api/轨规")
def api_改轨规(体: dict):
    return 目录.改轨规(体)

@路由.get("/api/源登记")
def api_源():
    return 目录.源列表()

@路由.get("/api/左轨")
def api_左():
    return 目录.左列表()

@路由.get("/api/右轨")
def api_右():
    return 目录.右列表()

@路由.get("/api/对齐差")
def api_差():
    return 目录.差列表()

@路由.get("/api/悬账单")
def api_悬():
    return 目录.悬列表()

@路由.get("/api/对拍结论")
def api_结论列表():
    return 目录.结论列表()

@路由.get("/api/夹具")
def api_夹具():
    return 夹具.列表()

@路由.post("/api/左轨/装载")
def api_左装(体: dict):
    return 左装载.装一批(体)

@路由.post("/api/右轨/装载")
def api_右装(体: dict):
    return 右装载.装一批(体)

@路由.post("/api/左轨/夹具/{name}")
def api_左夹(name: str):
    # Starlette 只认 ASCII 路径参数名；URL 形态不变（/api/左轨/夹具/<夹具名>）。
    try:
        return 左装载.装一批(夹具.读取(name))
    except FileNotFoundError:
        raise HTTPException(404, name)

@路由.post("/api/右轨/夹具/{name}")
def api_右夹(name: str):
    try:
        return 右装载.装一批(夹具.读取(name))
    except FileNotFoundError:
        raise HTTPException(404, name)

@路由.post("/api/对齐/跑")
def api_对齐(体: dict | None = None):
    return 对齐.跑对齐((体 or {}).get("形态"))

@路由.post("/api/对拍结论/跑")
def api_结论():
    return 结论.跑一次()


@路由.get("/api/同键多笔/形态")
def api_同键形态():
    return 同键多笔汇总.当前形态()

@路由.post("/api/同键多笔/形态")
def api_同键择形(体: dict):
    return 同键多笔汇总.择定形态((体 or {}).get("形态"))

@路由.get("/api/同键多笔/粒度")
def api_同键粒度():
    return 同键多笔汇总.粒度摘要()

@路由.get("/api/同键多笔/物化")
def api_同键物化():
    return 同键多笔汇总.物化包列表()

@路由.get("/api/同键多笔/物化/{name}")
def api_同键物化包(name: str):
    # Starlette 只认 ASCII 路径参数名；URL 形态 /api/同键多笔/物化/<物化包>。
    return 同键多笔汇总.物化包回读(name)


@路由.get("/api/统计/左命运")
def api_左命运():
    return 统计.左命运()

@路由.get("/api/统计/右命运")
def api_右命运():
    return 统计.右命运()

@路由.get("/api/统计/差型")
def api_差型():
    return 统计.差型分布()

@路由.get("/api/统计/悬边")
def api_悬边():
    return 统计.悬边分布()


@路由.get("/api/仓情")
def api_仓情():
    return 说明.仓情()

@路由.get("/api/空桩")
def api_空桩():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1] / "modules"
    已实现 = {"同键多笔汇总"}
    out = []
    if root.is_dir():
        for p in sorted(root.iterdir()):
            if p.is_dir() and p.name != "__pycache__" and (p / "__init__.py").is_file():
                if p.name in 已实现:
                    continue
                out.append(p.name)
    return {"空桩": out, "条数": len(out), "已实现": sorted(已实现)}

