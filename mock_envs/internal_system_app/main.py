from pathlib import Path

from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.responses import RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from mock_envs.shared.chaos import chaos_manager
from mock_envs.internal_system_app import db

app = FastAPI(title="Internal Invoice System (Mock)")
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

db.init_db()


class InvoiceIn(BaseModel):
    company: str
    invoice_number: str = ""
    amount: float
    due_date: str


# --- Human-facing UI (for the Browser tool) -------------------------------

@app.get("/")
def dashboard(request: Request):
    invoices = db.get_invoices()
    return templates.TemplateResponse("dashboard.html", {"request": request, "invoices": invoices})


@app.get("/form")
def form_page(request: Request):
    return templates.TemplateResponse("form.html", {"request": request})


@app.post("/form/submit")
def form_submit(
    company: str = Form(...),
    invoice_number: str = Form(""),
    amount: float = Form(...),
    due_date: str = Form(...),
):
    try:
        chaos_manager.maybe_disrupt_before("/form/submit")
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))

    db.insert_invoice(company, invoice_number, amount, due_date)
    return RedirectResponse(url="/", status_code=303)


# --- JSON API (for the API tool, and for independent Verifier checks) ----

@app.post("/invoices")
def create_invoice(payload: InvoiceIn):
    try:
        chaos_manager.maybe_disrupt_before("/invoices")
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))

    invoice_id = db.insert_invoice(
        company=payload.company,
        invoice_number=payload.invoice_number,
        amount=payload.amount,
        due_date=payload.due_date,
    )
    result = {"id": invoice_id, "status": "entered"}

    rule = chaos_manager.peek("/invoices")
    if rule and rule.mode in ("missing_field", "rename_field"):
        result = chaos_manager.mutate_data(rule, result)
        chaos_manager.consume("/invoices")

    return JSONResponse(result)


@app.get("/invoices")
def list_invoices(company: str | None = None):
    try:
        chaos_manager.maybe_disrupt_before("/invoices")
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))

    invoices = db.get_invoices(company)

    rule = chaos_manager.peek("/invoices")
    if rule and rule.mode in ("missing_field", "rename_field") and invoices:
        invoices = [chaos_manager.mutate_data(rule, inv) for inv in invoices]
        chaos_manager.consume("/invoices")

    return JSONResponse(invoices)


# --- Admin: chaos control --------------------------------------------------

@app.post("/admin/chaos")
def set_chaos(rule: dict):
    chaos_manager.set_rule(
        target=rule["target"],
        mode=rule["mode"],
        times=rule.get("times", 1),
        field_name=rule.get("field_name"),
        rename_to=rule.get("rename_to"),
        duration=rule.get("duration", 5.0),
    )
    return {"status": "ok", "active_rules": chaos_manager.get_rules()}


@app.get("/admin/chaos")
def get_chaos():
    return chaos_manager.get_rules()


@app.delete("/admin/chaos")
def clear_chaos(target: str | None = None):
    chaos_manager.clear(target)
    return {"status": "cleared", "active_rules": chaos_manager.get_rules()}