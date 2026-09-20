from fastapi import APIRouter
from backend.app.services.storage import detect_backend, get_storage

router = APIRouter(prefix="/storage")


@router.get("")
def get_status():
    try:
        name = get_storage().name
    except Exception as e:
        name = "error: " + str(e)
    return {"backend": name, "detected": detect_backend()}
