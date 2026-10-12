from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from mock_envs.shared.chaos import chaos_manager
from mock_envs.ticket_system_app import db

app = FastAPI(title="Internal Ticket System (Mock)")

db.init_db()
db.seed_if_empty()


class ResolveIn(BaseModel):
    resolution_notes: str
    approved: bool = True


@app.get("/tickets")
def list_tickets(status: str | None = None, customer: str | None = None):
    try:
        chaos_manager.maybe_disrupt_before("/tickets")
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))

    tickets = db.get_tickets(status=status, customer=customer)

    rule = chaos_manager.peek("/tickets")
    if rule and rule.mode in ("missing_field", "rename_field") and tickets:
        tickets = [chaos_manager.mutate_data(rule, t) for t in tickets]
        chaos_manager.consume("/tickets")

    return JSONResponse(tickets)


@app.post("/tickets/{ticket_id}/resolve")
def resolve_ticket(ticket_id: int, payload: ResolveIn):
    try:
        chaos_manager.maybe_disrupt_before("/tickets/resolve")
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))

    db.resolve_ticket(ticket_id, payload.resolution_notes, payload.approved)
    return JSONResponse({"id": ticket_id, "status": "resolved" if payload.approved else "escalated"})


@app.post("/admin/chaos")
def set_chaos(rule: dict):
    chaos_manager.set_rule(
        target=rule["target"], mode=rule["mode"], times=rule.get("times", 1),
        field_name=rule.get("field_name"), rename_to=rule.get("rename_to"),
        duration=rule.get("duration", 5.0),
    )
    return {"status": "ok", "active_rules": chaos_manager.get_rules()}


@app.delete("/admin/chaos")
def clear_chaos(target: str | None = None):
    chaos_manager.clear(target)
    return {"status": "cleared"}