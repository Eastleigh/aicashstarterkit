import os
import csv
import logging
from datetime import datetime, timezone
from pathlib import Path

import stripe
import httpx
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

logger = logging.getLogger(__name__)

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
SUBSCRIBERS_FILE = BASE_DIR.parent / "subscribers.csv"

SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY", "")
FROM_EMAIL = os.getenv("FROM_EMAIL", "support@aicashstarterkit.com")
GA_MEASUREMENT_ID = os.getenv("GA_MEASUREMENT_ID", "")

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
        "ga_id": GA_MEASUREMENT_ID,
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
        "ga_id": GA_MEASUREMENT_ID,
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


@app.post("/api/subscribe")
async def subscribe(request: Request):
    try:
        body = await request.json()
        email = body.get("email", "").strip().lower()
        if not email or "@" not in email:
            return JSONResponse({"error": "Invalid email"}, status_code=400)

        file_exists = SUBSCRIBERS_FILE.exists()
        with open(SUBSCRIBERS_FILE, "a", newline="") as f:
            writer = csv.writer(f)
            if not file_exists:
                writer.writerow(["email", "subscribed_at"])
            writer.writerow([email, datetime.now(timezone.utc).isoformat()])

        print(f"[SUBSCRIBER] {email}")
        return JSONResponse({"status": "ok"})
    except Exception:
        return JSONResponse({"error": "Something went wrong"}, status_code=500)


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
        logger.info(f"[SALE] {customer_email} purchased {PRODUCT_NAME} for ${PRICE_CENTS / 100:.2f}")

        if SENDGRID_API_KEY and customer_email != "unknown":
            try:
                await send_purchase_email(customer_email, session_id)
                logger.info(f"[EMAIL] Sent download links to {customer_email}")
            except Exception as e:
                logger.error(f"[EMAIL] Failed to send to {customer_email}: {e}")

    return JSONResponse({"status": "ok"})


async def send_purchase_email(to_email: str, session_id: str):
    """Send download links to buyer via SendGrid."""
    download_url = f"{DOMAIN}/thank-you?session_id={session_id}"

    html_content = f"""
    <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 600px; margin: 0 auto; padding: 40px 20px; color: #333;">
        <div style="text-align: center; margin-bottom: 32px;">
            <h1 style="color: #6c5ce7; font-size: 28px; margin: 0;">AI Income Blueprint</h1>
            <p style="color: #888; font-size: 14px; margin-top: 4px;">Your purchase is confirmed</p>
        </div>

        <p style="font-size: 16px; line-height: 1.6;">Hi there,</p>
        <p style="font-size: 16px; line-height: 1.6;">Thank you for purchasing the <strong>AI Income Blueprint</strong>! Your 6 resources are ready to download.</p>

        <div style="background: #f8f9fa; border-radius: 12px; padding: 24px; margin: 24px 0;">
            <h3 style="margin: 0 0 16px 0; font-size: 18px;">Your Downloads:</h3>
            <ul style="list-style: none; padding: 0; margin: 0;">
                <li style="padding: 8px 0; border-bottom: 1px solid #eee;">&#128218; AI Income Playbook (6 pages)</li>
                <li style="padding: 8px 0; border-bottom: 1px solid #eee;">&#128196; 50 Plug-and-Play AI Prompts (13 pages)</li>
                <li style="padding: 8px 0; border-bottom: 1px solid #eee;">&#128187; Freelancer Quick-Start Templates (7 pages)</li>
                <li style="padding: 8px 0; border-bottom: 1px solid #eee;">&#128176; Digital Product Launch Guide (6 pages)</li>
                <li style="padding: 8px 0; border-bottom: 1px solid #eee;">&#128200; AI Tools Cheat Sheet (5 pages)</li>
                <li style="padding: 8px 0;">&#127919; 30-Day Action Plan (8 pages)</li>
            </ul>
        </div>

        <div style="text-align: center; margin: 32px 0;">
            <a href="{download_url}" style="display: inline-block; background: linear-gradient(135deg, #6c5ce7, #a855f7); color: white; padding: 14px 32px; border-radius: 8px; text-decoration: none; font-weight: 700; font-size: 16px;">Access Your Downloads</a>
        </div>

        <p style="font-size: 14px; color: #888; line-height: 1.6;">Bookmark your download page so you can come back anytime. Your access never expires.</p>

        <hr style="border: none; border-top: 1px solid #eee; margin: 32px 0;">

        <p style="font-size: 13px; color: #aaa; text-align: center;">Questions? Reply to this email or contact <a href="mailto:support@aicashstarterkit.com" style="color: #6c5ce7;">support@aicashstarterkit.com</a></p>
    </div>
    """

    payload = {
        "personalizations": [{"to": [{"email": to_email}]}],
        "from": {"email": FROM_EMAIL, "name": "AI Income Blueprint"},
        "subject": "Your AI Income Blueprint is ready to download",
        "content": [{"type": "text/html", "value": html_content}],
    }

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://api.sendgrid.com/v3/mail/send",
            json=payload,
            headers={
                "Authorization": f"Bearer {SENDGRID_API_KEY}",
                "Content-Type": "application/json",
            },
            timeout=10.0,
        )
        resp.raise_for_status()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
