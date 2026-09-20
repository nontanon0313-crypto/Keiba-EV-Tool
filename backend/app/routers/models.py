from fastapi import APIRouter
from backend.app.services.prediction_store import list_all

router = APIRouter(prefix="/models")


@router.get("")
def list_models():
    items = list_all()
    versions = {}
    for it in items:
        v = it.get("model_version")
        if not v:
            continue
        if v not in versions:
            versions[v] = {"model_version": v, "count": 0, "latest_at": ""}
        versions[v]["count"] += 1
        t = it.get("created_at", "")
        if t > versions[v]["latest_at"]:
            versions[v]["latest_at"] = t
    out = sorted(versions.values(), key=lambda x: x["model_version"])
    return {"models": out}
