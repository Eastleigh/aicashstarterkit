import os
import json
import hmac
import hashlib
from pathlib import Path

import stripe
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

BASE_DIR = Path(__file__).resolve().parent
PRODUCTS_DIR = BASE_DIR.parent / "products"

app = FastAPI(title="AI Cash Starter Kit")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")

STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_PUBLISHABLE_KEY = os.getenv("STRIPE_PUBLISHABLE_KEY", "")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")
PRICE_CENTS = 2700  # $27
PRODUCT_NAME = "AI Cash Starter Kit"

if STRIPE_SECRET_KEY:
    stripe.api_key = STRIPE_SECRET_KEY

DOMAIN = os.getenv("DOMAIN", "http://localhost:8000")


@app.get("/", response_class=HTMLResponse)
async def landing(request: Request):
    return templates.TemplateResponse("landing.html", {
        "request": request,
        "stripe_key": STRIPE_PUBLISHABLE_KEY,
    })


@app.get("/thank-you", response_class=HTMLResponse)
async def thank_you(request: Request):
    return templates.TemplateResponse("thank_you.html", {"request": request})


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
                        "description": "Instant access to templates, scripts, and step-by-step guides for making money with AI.",
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
        print(f"[SALE] {customer_email} purchased {PRODUCT_NAME} for ${PRICE_CENTS / 100:.2f}")

    return JSONResponse({"status": "ok"})


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
