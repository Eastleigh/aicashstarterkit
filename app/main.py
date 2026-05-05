import os
import json
import hmac
import hashlib
from pathlib import Path

import stripe
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

BASE_DIR = Path(__file__).resolve().parent
PRODUCTS_DIR = BASE_DIR.parent / "products"
DOWNLOADS_DIR = BASE_DIR / "downloads"

app = FastAPI(title="AI Income Blueprint")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")

STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_PUBLISHABLE_KEY = os.getenv("STRIPE_PUBLISHABLE_KEY", "")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")
PRICE_CENTS = 2700  # $27
PRODUCT_NAME = "AI Income Blueprint"

if STRIPE_SECRET_KEY:
    stripe.api_key = STRIPE_SECRET_KEY

DOMAIN = os.getenv("DOMAIN", "http://localhost:8000")

DOWNLOAD_FILES = {
    "01-ai-income-playbook": "01-ai-income-playbook.pdf",
    "02-50-ai-prompts": "02-50-ai-prompts.pdf",
    "03-freelancer-templates": "03-freelancer-templates.pdf",
    "04-digital-product-launch-guide": "04-digital-product-launch-guide.pdf",
    "05-ai-tools-cheat-sheet": "05-ai-tools-cheat-sheet.pdf",
    "06-30-day-action-plan": "06-30-day-action-plan.pdf",
}

# Store verified session IDs in memory
verified_sessions: set[str] = set()


@app.get("/", response_class=HTMLResponse)
async def landing(request: Request):
    return templates.TemplateResponse(request, "landing.html", {
        "stripe_key": STRIPE_PUBLISHABLE_KEY,
    })


@app.get("/thank-you", response_class=HTMLResponse)
async def thank_you(request: Request):
    session_id = request.query_params.get("session_id", "")
    verified = False

    if session_id and STRIPE_SECRET_KEY:
        if session_id in verified_sessions:
            verified = True
        else:
            try:
                session = stripe.checkout.Session.retrieve(session_id)
                if session.payment_status == "paid":
                    verified = True
                    verified_sessions.add(session_id)
            except Exception:
                pass

    return templates.TemplateResponse(request, "thank_you.html", {
        "verified": verified,
        "session_id": session_id,
    })


@app.get("/download/{file_key}")
async def download_file(file_key: str, session_id: str = ""):
    if file_key not in DOWNLOAD_FILES:
        return JSONResponse({"error": "File not found"}, status_code=404)

    if not session_id or not STRIPE_SECRET_KEY:
        return JSONResponse({"error": "Invalid access"}, status_code=403)

    if session_id not in verified_sessions:
        try:
            session = stripe.checkout.Session.retrieve(session_id)
            if session.payment_status != "paid":
                return JSONResponse({"error": "Payment not verified"}, status_code=403)
            verified_sessions.add(session_id)
        except Exception:
            return JSONResponse({"error": "Invalid session"}, status_code=403)

    file_path = DOWNLOADS_DIR / DOWNLOAD_FILES[file_key]
    if not file_path.exists():
        return JSONResponse({"error": "File not available"}, status_code=404)

    return FileResponse(
        path=str(file_path),
        filename=DOWNLOAD_FILES[file_key],
        media_type="application/pdf",
    )


@app.post("/api/checkout")
async def create_checkout():
    if not STRIPE_SECRET_KEY:
        return JSONResponse(
            {"error": "Payment system not configured. Please try again later."},
            status_code=503,
        )
    try:
        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[{
                "price_data": {
                    "currency": "usd",
                    "product_data": {
                        "name": PRODUCT_NAME,
                        "description": "Your step-by-step blueprint to making your first $300 with AI. Templates, prompts, and a 30-day action plan.",
                    },
                    "unit_amount": PRICE_CENTS,
                },
                "quantity": 1,
            }],
            mode="payment",
            success_url=f"{DOMAIN}/thank-you?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{DOMAIN}/",
        )
        return JSONResponse({"checkout_url": session.url})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.post("/api/webhook")
async def stripe_webhook(request: Request):
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    if not STRIPE_WEBHOOK_SECRET:
        return JSONResponse({"status": "webhook secret not configured"}, status_code=400)

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, STRIPE_WEBHOOK_SECRET)
    except (ValueError, stripe.error.SignatureVerificationError):
        return JSONResponse({"error": "Invalid signature"}, status_code=400)

    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        customer_email = session.get("customer_details", {}).get("email", "unknown")
        session_id = session.get("id", "")
        if session_id:
            verified_sessions.add(session_id)
        print(f"[SALE] {customer_email} purchased {PRODUCT_NAME} for ${PRICE_CENTS / 100:.2f}")

    return JSONResponse({"status": "ok"})


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
