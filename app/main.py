"""FastAPI 진입점.

V-World 인증키는 프론트엔드로 내보내지 않는다. 배경지도 타일과 필지 조회를
모두 이 서버가 중계하므로 키는 서버 밖으로 나가지 않는다.
"""
import asyncio
import contextlib
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from . import config, crs, jobs
from .geom import BBox
from .sources import vworld

WEB = Path(__file__).resolve().parent.parent / "web"

VALID_LAYERS = {"parcel", "pnu"}
TILE_LAYERS = {"Base": "png", "gray": "png", "midnight": "png",
               "Satellite": "jpeg", "Hybrid": "png"}


@contextlib.asynccontextmanager
async def lifespan(_app: FastAPI):
    task = asyncio.create_task(_sweeper())
    yield
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


async def _sweeper():
    while True:
        await asyncio.sleep(1800)
        try:
            jobs.sweep_expired()
        except OSError:
            pass


app = FastAPI(title="지적도 DXF 추출 서비스", lifespan=lifespan)


@app.get("/api/config")
async def get_config():
    return {
        "max_area_km2": config.MAX_AREA_KM2,
        "has_vworld_key": bool(config.VWORLD_KEY),
        "crs": crs.catalog(),
        "default_crs": crs.DEFAULT,
        "stages": [{"key": k, "label": v} for k, v in jobs.STAGES],
    }


@app.get("/api/tiles/{layer}/{z}/{y}/{x}")
async def tile(layer: str, z: int, y: int, x: int):
    """V-World WMTS 중계. 인증키를 브라우저에 노출하지 않기 위한 경유지."""
    if layer not in TILE_LAYERS:
        raise HTTPException(404, "알 수 없는 배경지도")
    if not config.VWORLD_KEY:
        raise HTTPException(503, "V-World 인증키가 설정되지 않았습니다.")
    ext = TILE_LAYERS[layer]
    url = config.VWORLD_TILE_URL.format(
        key=config.VWORLD_KEY, layer=layer, z=z, y=y, x=x, ext=ext)
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            r = await client.get(url, headers={"User-Agent": config.USER_AGENT})
    except httpx.HTTPError:
        raise HTTPException(502, "배경지도 서버에 연결할 수 없습니다.") from None
    if r.status_code != 200:
        return Response(status_code=204)
    return Response(
        content=r.content,
        media_type="image/jpeg" if ext == "jpeg" else "image/png",
        headers={"Cache-Control": "public, max-age=86400"},
    )


@app.get("/api/parcels")
async def parcels_preview(
    bbox: str = Query(..., description="minLon,minLat,maxLon,maxLat"),
):
    """지도에 필지 경계를 미리 그려 주기 위한 GeoJSON."""
    box = _parse_bbox(bbox)
    if box.area_km2() > config.MAX_AREA_KM2 * 3:
        raise HTTPException(400, "미리보기 영역이 너무 넓습니다.")
    try:
        items = await vworld.fetch_parcels(box)
    except vworld.VWorldError as exc:
        raise HTTPException(502, str(exc)) from exc

    features = [{
        "type": "Feature",
        "properties": {"pnu": p["pnu"], "jibun": p["jibun"], "jimok": p["jimok"]},
        "geometry": {"type": "Polygon", "coordinates": [[list(pt) for pt in r]]},
    } for p in items for r in p["rings"][:1]]
    return {"type": "FeatureCollection", "features": features}


@app.get("/api/project")
async def project_point(
    lon: float = Query(...), lat: float = Query(...), crs_code: str = Query(..., alias="crs"),
):
    """선택 영역 모서리 좌표를 출력 파일과 똑같은 변환식으로 계산해 준다.

    브라우저의 proj4 정의는 구지적(5174) 데이텀 변환이 서버와 미세하게 다를 수
    있어, 화면에 확정값으로 보여 줄 숫자는 여기서 받아 간다.
    """
    if not crs.is_supported(crs_code):
        raise HTTPException(400, f"지원하지 않는 좌표계입니다: EPSG:{crs_code}")
    x, y = crs.transform_point(lon, lat, crs_code)
    return {"x": x, "y": y, "unit": crs.SUPPORTED[crs_code].unit}


@app.post("/api/jobs")
async def create_job(req: Request):
    body = await req.json()

    try:
        bbox = [float(v) for v in body["bbox"]]
        if len(bbox) != 4:
            raise ValueError
    except (KeyError, TypeError, ValueError):
        raise HTTPException(400, "bbox 형식이 올바르지 않습니다.") from None

    # CAD에서 부를 때는 도면 좌표(TM)를 그대로 보낸다. 여기서 경위도로 바꾼다.
    bbox_crs = str(body.get("bbox_crs", "4326"))
    if bbox_crs != "4326":
        if not crs.is_supported(bbox_crs):
            raise HTTPException(400, f"지원하지 않는 입력 좌표계입니다: EPSG:{bbox_crs}")
        x0, y0 = crs.to_wgs84(bbox[0], bbox[1], bbox_crs)
        x1, y1 = crs.to_wgs84(bbox[2], bbox[3], bbox_crs)
        bbox = [x0, y0, x1, y1]

    box = BBox(*bbox)
    area = box.area_km2()
    if area <= 0:
        raise HTTPException(400, "영역의 면적이 0입니다.")
    if area > config.MAX_AREA_KM2:
        raise HTTPException(
            400,
            f"선택 영역 {area:.2f} km²가 1회 추출 한도 "
            f"{config.MAX_AREA_KM2:.2f} km²를 초과했습니다.",
        )

    target = str(body.get("crs", crs.DEFAULT))
    if not crs.is_supported(target):
        raise HTTPException(400, f"지원하지 않는 좌표계입니다: EPSG:{target}")

    layers = [str(v) for v in body.get("layers", [])]
    unknown = set(layers) - VALID_LAYERS
    if unknown:
        raise HTTPException(400, f"알 수 없는 레이어: {', '.join(sorted(unknown))}")
    if not layers:
        raise HTTPException(400, "추출할 레이어를 하나 이상 선택하세요.")
    if set(layers) & {"parcel", "pnu"} and not config.VWORLD_KEY:
        raise HTTPException(
            503, "지적 레이어를 받으려면 V-World 인증키가 필요합니다.")

    try:
        job = jobs.create({
            "bbox": bbox,
            "crs": target,
            "layers": layers,
            "options": body.get("options", {}),
        })
    except jobs.Busy as exc:
        raise HTTPException(429, str(exc)) from exc
    return JSONResponse({"id": job.id}, status_code=202)


@app.get("/api/jobs/{job_id}")
async def job_status(job_id: str):
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(404, "작업을 찾을 수 없습니다. 만료되었을 수 있습니다.")
    return job.as_dict()


@app.get("/api/jobs/{job_id}/download")
async def job_download(job_id: str):
    job = jobs.get(job_id)
    if not job or job.state != "done" or not job.path or not job.path.exists():
        raise HTTPException(404, "다운로드할 파일이 없습니다.")
    return FileResponse(job.path, media_type="image/vnd.dxf", filename=job.filename)


def _parse_bbox(raw: str) -> BBox:
    try:
        parts = [float(v) for v in raw.split(",")]
        if len(parts) != 4:
            raise ValueError
    except ValueError:
        raise HTTPException(400, "bbox는 minLon,minLat,maxLon,maxLat 형식입니다.") from None
    return BBox(*parts)


app.mount("/", StaticFiles(directory=WEB, html=True), name="web")
