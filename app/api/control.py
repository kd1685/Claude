"""Account-control endpoints: enqueue title/rank/locate/scan commands and read
the queue + backend status. Every command is tagged with the officer who issued
it (audit log)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ..auth import require_ready
from ..db import get_conn
from ..models import (ChangeRankIn, GiveTitleIn, LocateIn, ScanJobIn, TITLES)
from ..control import get_adapter
from ..control.worker import enqueue

# Every control endpoint requires a logged-in officer (Depends(require_ready)).
router = APIRouter(prefix="/api/control", tags=["control"])


def _enqueue(kind, user, *, player_id=None, params=None) -> dict:
    cid = enqueue(kind, player_id=player_id, params=params,
                  issued_by=user["id"], issued_by_name=user["username"])
    return {"command_id": cid, "queued": True}


@router.get("/status")
def status(user=Depends(require_ready)):
    a = get_adapter()
    return {"adapter": a.name, **a.status(), "titles": TITLES}


@router.post("/connect")
def connect(user=Depends(require_ready)):
    res = get_adapter().connect()
    return {"ok": res.ok, "detail": res.detail, "data": res.data}


@router.post("/give-title")
def give_title(body: GiveTitleIn, user=Depends(require_ready)):
    if body.title not in TITLES:
        raise HTTPException(400, f"title must be one of {TITLES}")
    return _enqueue("give_title", user, player_id=body.player_id,
                    params={"title": body.title})


@router.post("/change-rank")
def change_rank(body: ChangeRankIn, user=Depends(require_ready)):
    return _enqueue("change_rank", user, player_id=body.player_id,
                    params={"new_rank": body.new_rank})


@router.post("/locate")
def locate(body: LocateIn, user=Depends(require_ready)):
    return _enqueue("locate", user, player_id=body.player_id)


@router.post("/scan")
def scan(body: ScanJobIn, user=Depends(require_ready)):
    return _enqueue("scan", user, params={"kind": body.kind, "pages": body.pages})


@router.get("/commands")
def commands(limit: int = 50, user=Depends(require_ready)):
    rows = get_conn().execute(
        """SELECT c.*, p.name AS player_name FROM commands c
           LEFT JOIN players p ON p.id = c.player_id
           ORDER BY c.id DESC LIMIT ?""",
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]
