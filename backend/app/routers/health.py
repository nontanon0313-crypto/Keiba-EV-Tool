from fastapi import APIRouter
from backend.app.services.storage import detect_backend, get_storage

router = APIRouter()


@router.get("/health")
def health():
    try:
        backend = get_storage().name
    except Exception as e:
        backend = "error: " + str(e)
    return {"ok": True, "storage": backend, "detected": detect_backend()}
