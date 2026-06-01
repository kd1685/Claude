"""Manual scan ingest + scan history."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..db import get_conn
from ..models import ScanIn
from ..services import VALID_KINDS, ingest_scan

router = APIRouter(prefix="/api/scans", tags=["scans"])


@router.post("")
def create_scan(body: ScanIn):
    if body.kind not in VALID_KINDS:
        raise HTTPException(400, f"kind must be one of {sorted(VALID_KINDS)}")
    rows = [r.model_dump(exclude_none=True) for r in body.rows]
    return ingest_scan(body.kind, rows, captured_at=body.captured_at,
                       source=body.source)


@router.get("")
def list_scans(limit: int = 50):
    rows = get_conn().execute(
        "SELECT id, kind, captured_at, source, device, rows, created_at "
        "FROM scans ORDER BY id DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]
