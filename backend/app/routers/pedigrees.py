from fastapi import APIRouter, HTTPException, Query
import os
import json

from backend.app.services import turso_client

router = APIRouter(prefix="/pedigrees")


def _get_client():
    return turso_client.get_client()


@router.get("/sires")
def list_sires(limit: int = 200):
    """父一覧を産駒数順で返す。"""
    client, err = _get_client()
    if client is None:
        raise HTTPException(500, "turso: " + str(err))
    try:
        r = client.execute(
            "SELECT sire, COUNT(*) as cnt FROM pedigree_index "
            "WHERE sire != '' GROUP BY sire ORDER BY cnt DESC LIMIT ?",
            [limit],
        )
        return {"items": [{"name": row[0], "count": row[1]} for row in r.rows]}
    except Exception as e:
        raise HTTPException(500, repr(e))


@router.get("/dam_sires")
def list_dam_sires(limit: int = 200):
    """母父一覧を産駒数順で返す。"""
    client, err = _get_client()
    if client is None:
        raise HTTPException(500, "turso: " + str(err))
    try:
        r = client.execute(
            "SELECT dam_sire, COUNT(*) as cnt FROM pedigree_index "
            "WHERE dam_sire != '' GROUP BY dam_sire ORDER BY cnt DESC LIMIT ?",
            [limit],
        )
        return {"items": [{"name": row[0], "count": row[1]} for row in r.rows]}
    except Exception as e:
        raise HTTPException(500, repr(e))


@router.get("/offspring")
def get_offspring(kind: str = Query("sire"), name: str = Query(""), limit: int = 200):
    """指定した父 or 母父の産駒一覧を返す。"""
    if not name:
        return {"items": []}
    client, err = _get_client()
    if client is None:
        raise HTTPException(500, "turso: " + str(err))
    col = "sire" if kind == "sire" else "dam_sire"
    try:
        r = client.execute(
            "SELECT lineage_nb, name, sire, dam, dam_sire FROM pedigree_index WHERE " + col + "=? LIMIT ?",
            [name, limit],
        )
        return {"items": [
            {"lineage_nb": row[0], "name": row[1], "sire": row[2], "dam": row[3], "dam_sire": row[4]}
            for row in r.rows
        ]}
    except Exception as e:
        raise HTTPException(500, repr(e))
