"""Account-control endpoints: enqueue title/rank/locate/scan commands and read
the queue + backend status."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ..auth import require_auth
from ..db import get_conn
from ..models import (ChangeRankIn, GiveTitleIn, LocateIn, ScanJobIn, TITLES)
from ..control import get_adapter
from ..control.worker import enqueue

# Every control endpoint requires a valid session (set CONTROL_PASSWORD).
router = APIRouter(prefix="/api/control", tags=["control"],
                   dependencies=[Depends(require_auth)])


@router.get("/status")
def status():
    a = get_adapter()
    return {"adapter": a.name, **a.status(), "titles": TITLES}


@router.post("/connect")
def connect():
    res = get_adapter().connect()
    return {"ok": res.ok, "detail": res.detail, "data": res.data}


@router.post("/give-title")
def give_title(body: GiveTitleIn):
    if body.title not in TITLES:
        raise HTTPException(400, f"title must be one of {TITLES}")
    cid = enqueue("give_title", player_id=body.player_id, params={"title": body.title})
    return {"command_id": cid, "queued": True}


@router.post("/change-rank")
def change_rank(body: ChangeRankIn):
    cid = enqueue("change_rank", player_id=body.player_id,
                  params={"new_rank": body.new_rank})
    return {"command_id": cid, "queued": True}


@router.post("/locate")
def locate(body: LocateIn):
    cid = enqueue("locate", player_id=body.player_id)
    return {"command_id": cid, "queued": True}


@router.post("/scan")
def scan(body: ScanJobIn):
    cid = enqueue("scan", params={"kind": body.kind, "pages": body.pages})
    return {"command_id": cid, "queued": True}


@router.get("/commands")
def commands(limit: int = 50):
    rows = get_conn().execute(
        """SELECT c.*, p.name AS player_name FROM commands c
           LEFT JOIN players p ON p.id = c.player_id
           ORDER BY c.id DESC LIMIT ?""",
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]
