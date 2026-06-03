"""Account-control endpoints: one-off commands, bulk title rotations, the
audit log (with CSV export), and backend status. Every action is tagged with
the officer who issued it."""
from __future__ import annotations

import csv
import io

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from ..auth import require_action, require_ready
from ..db import get_conn
from ..models import (ChangeRankIn, GiveTitleIn, LocateIn, RotationIn, ScanJobIn,
                      TITLES)
from ..permissions import permissions_for
from ..control import get_adapter, rotation
from ..control.worker import enqueue

router = APIRouter(prefix="/api/control", tags=["control"])


def _enqueue(kind, user, *, player_id=None, params=None) -> dict:
    cid = enqueue(kind, player_id=player_id, params=params,
                  issued_by=user["id"], issued_by_name=user["username"])
    return {"command_id": cid, "queued": True}


@router.get("/status")
def status(user=Depends(require_ready)):
    a = get_adapter()
    return {"adapter": a.name, **a.status(), "titles": TITLES,
            "permissions": permissions_for(user["role"]), "role": user["role"]}


@router.post("/connect")
def connect(user=Depends(require_ready)):
    res = get_adapter().connect()
    return {"ok": res.ok, "detail": res.detail, "data": res.data}


@router.post("/give-title")
def give_title(body: GiveTitleIn, user=Depends(require_action("give_title"))):
    if body.title not in TITLES:
        raise HTTPException(400, f"title must be one of {TITLES}")
    return _enqueue("give_title", user, player_id=body.player_id,
                    params={"title": body.title})


@router.post("/change-rank")
def change_rank(body: ChangeRankIn, user=Depends(require_action("change_rank"))):
    # Promoting to R5 (kingdom leader) is admin-only.
    if body.new_rank == 5 and user["role"] != "admin":
        raise HTTPException(403, "promoting to R5 requires an admin")
    return _enqueue("change_rank", user, player_id=body.player_id,
                    params={"new_rank": body.new_rank})


@router.post("/locate")
def locate(body: LocateIn, user=Depends(require_action("locate"))):
    return _enqueue("locate", user, player_id=body.player_id)


@router.post("/scan")
def scan(body: ScanJobIn, user=Depends(require_action("scan"))):
    return _enqueue("scan", user, params={"kind": body.kind, "pages": body.pages})


@router.post("/scan-profiles")
def scan_profiles(body: ScanJobIn, user=Depends(require_action("scan"))):
    """Deep scan (opens each governor's profile) to capture dead troops."""
    return _enqueue("scan_profiles", user, params={"pages": body.pages})


@router.post("/scan-rallies")
def scan_rallies(body: ScanJobIn, user=Depends(require_action("scan"))):
    return _enqueue("scan_rallies", user, params={"pages": body.pages})


# ---- bulk title rotation ----

@router.post("/rotation")
def start_rotation(body: RotationIn, user=Depends(require_action("rotation"))):
    try:
        rid = rotation.create_rotation(body.title, body.player_ids,
                                       body.hold_seconds, user)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {"rotation_id": rid}


@router.get("/rotation/active")
def rotation_active(user=Depends(require_ready)):
    return rotation.active_rotation() or {"rotation": None}


@router.get("/rotations")
def rotations(limit: int = 20, user=Depends(require_ready)):
    return rotation.list_rotations(limit)


@router.post("/rotation/{rotation_id}/cancel")
def rotation_cancel(rotation_id: int, user=Depends(require_action("rotation"))):
    if not rotation.cancel(rotation_id):
        raise HTTPException(400, "rotation is not running")
    return {"ok": True}


@router.post("/rotation/{rotation_id}/skip")
def rotation_skip(rotation_id: int, user=Depends(require_action("rotation"))):
    if not rotation.skip_current(rotation_id):
        raise HTTPException(400, "no active member to skip")
    return {"ok": True}


# ---- audit log ----

def _audit_query(kind, officer, frm, to, limit):
    where, args = [], []
    if kind:
        where.append("c.kind = ?"); args.append(kind)
    if officer:
        where.append("c.issued_by_name = ?"); args.append(officer)
    if frm:
        where.append("date(c.created_at) >= ?"); args.append(frm)
    if to:
        where.append("date(c.created_at) <= ?"); args.append(to)
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    sql = (f"SELECT c.*, p.name AS player_name FROM commands c "
           f"LEFT JOIN players p ON p.id = c.player_id {clause} "
           f"ORDER BY c.id DESC LIMIT ?")
    return sql, (*args, limit)


@router.get("/commands")
def commands(limit: int = 50, kind: str | None = None, officer: str | None = None,
             frm: str | None = Query(default=None, alias="from"),
             to: str | None = None, user=Depends(require_ready)):
    sql, args = _audit_query(kind, officer, frm, to, limit)
    return [dict(r) for r in get_conn().execute(sql, args).fetchall()]


@router.get("/commands.csv")
def commands_csv(kind: str | None = None, officer: str | None = None,
                 frm: str | None = Query(default=None, alias="from"),
                 to: str | None = None, limit: int = 5000,
                 user=Depends(require_ready)):
    sql, args = _audit_query(kind, officer, frm, to, limit)
    rows = get_conn().execute(sql, args).fetchall()
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["id", "kind", "player", "issued_by", "status", "error",
                "created_at", "finished_at"])
    for r in rows:
        w.writerow([r["id"], r["kind"], r["player_name"] or "", r["issued_by_name"] or "",
                    r["status"], r["error"] or "", r["created_at"], r["finished_at"] or ""])
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]), media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=audit_log.csv"})
