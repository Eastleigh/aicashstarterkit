import os
import csv
import json
import logging
import asyncio
import secrets as secrets_mod
from datetime import datetime, timezone, timedelta
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
DATA_DIR = BASE_DIR.parent / "data"
DATA_DIR.mkdir(exist_ok=True)

app = FastAPI(title="AI Income Blueprint")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")

STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_PUBLISHABLE_KEY = os.getenv("STRIPE_PUBLISHABLE_KEY", "")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")
PRICE_CENTS = 2700  # $27
DISCOUNT_PRICE_CENTS = 1900  # $19
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

# In-memory state
verified_sessions: set[str] = set()
purchase_count: int = 0

# Affiliate data file
AFFILIATES_FILE = DATA_DIR / "affiliates.json"
REFERRALS_FILE = DATA_DIR / "referrals.json"

# Email sequence schedule (days after purchase)
EMAIL_SEQUENCE = [
    {"day": 0, "subject": "Your AI Income Blueprint is ready to download", "template": "welcome"},
    {"day": 3, "subject": "Have you started your AI income journey?", "template": "day3"},
    {"day": 5, "subject": "Quick win: Try this AI prompt today", "template": "day5"},
    {"day": 7, "subject": "How others are earning with AI", "template": "day7"},
    {"day": 14, "subject": "Ready to level up your AI income?", "template": "day14"},
]

# Email queue file
EMAIL_QUEUE_FILE = DATA_DIR / "email_queue.json"


def load_json(path: Path, default=None):
    if default is None:
        default = {}
    if path.exists():
        try:
            return json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            return default
    return default


def save_json(path: Path, data):
    path.write_text(json.dumps(data, indent=2, default=str))


@app.on_event("startup")
async def startup():
    global purchase_count
    if STRIPE_SECRET_KEY:
        try:
            sessions = stripe.checkout.Session.list(limit=100, status="complete")
            purchase_count = len(sessions.data)
        except Exception as e:
            logger.warning(f"Could not fetch Stripe purchase count: {e}")
            purchase_count = 0
    asyncio.create_task(email_sequence_worker())


@app.get("/", response_class=HTMLResponse)
async def landing(request: Request):
    ref = request.query_params.get("ref", "")
    return templates.TemplateResponse(request, "landing.html", {
        "stripe_key": STRIPE_PUBLISHABLE_KEY,
        "ga_id": GA_MEASUREMENT_ID,
        "purchase_count": purchase_count,
        "ref": ref,
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

        logger.info(f"[SUBSCRIBER] {email}")
        return JSONResponse({"status": "ok"})
    except Exception:
        return JSONResponse({"error": "Something went wrong"}, status_code=500)


@app.post("/api/checkout")
async def create_checkout(request: Request):
    if not STRIPE_SECRET_KEY:
        return JSONResponse(
            {"error": "Payment system not configured. Please try again later."},
            status_code=503,
        )

    try:
        body = await request.json() if request.headers.get("content-type") == "application/json" else {}
    except Exception:
        body = {}

    discount = body.get("discount", False)
    ref = body.get("ref", "")
    price = DISCOUNT_PRICE_CENTS if discount else PRICE_CENTS
    price_label = f"${price / 100:.0f}"

    metadata = {}
    if ref:
        metadata["affiliate_ref"] = ref

    try:
        create_kwargs = {
            "line_items": [{
                "price_data": {
                    "currency": "usd",
                    "product_data": {
                        "name": PRODUCT_NAME,
                        "description": f"Your step-by-step blueprint to making your first $300 with AI. Templates, prompts, and a 30-day action plan. ({price_label})",
                    },
                    "unit_amount": price,
                },
                "quantity": 1,
            }],
            "mode": "payment",
            "success_url": f"{DOMAIN}/thank-you?session_id={{CHECKOUT_SESSION_ID}}",
            "cancel_url": f"{DOMAIN}/",
        }
        if metadata:
            create_kwargs["metadata"] = metadata
            create_kwargs["payment_intent_data"] = {"metadata": metadata}

        session = stripe.checkout.Session.create(**create_kwargs)
        return JSONResponse({"checkout_url": session.url})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.post("/api/webhook")
async def stripe_webhook(request: Request):
    global purchase_count
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
        amount = session.get("amount_total", 0)
        metadata = session.get("metadata", {})
        affiliate_ref = metadata.get("affiliate_ref", "")

        if session_id:
            verified_sessions.add(session_id)
        purchase_count += 1
        logger.info(f"[SALE] {customer_email} purchased {PRODUCT_NAME} for ${amount / 100:.2f}")

        # Track affiliate referral
        if affiliate_ref:
            track_referral(affiliate_ref, customer_email, amount)

        # Send welcome email (day 0)
        if SENDGRID_API_KEY and customer_email != "unknown":
            try:
                await send_purchase_email(customer_email, session_id)
                logger.info(f"[EMAIL] Sent download links to {customer_email}")
            except Exception as e:
                logger.error(f"[EMAIL] Failed to send to {customer_email}: {e}")

            # Queue follow-up emails (days 3, 5, 7, 14)
            queue_email_sequence(customer_email, session_id)

    return JSONResponse({"status": "ok"})


# ── Affiliate System ──

@app.post("/api/affiliate/register")
async def register_affiliate(request: Request):
    try:
        body = await request.json()
        email = body.get("email", "").strip().lower()
        if not email or "@" not in email:
            return JSONResponse({"error": "Invalid email"}, status_code=400)

        affiliates = load_json(AFFILIATES_FILE, {})
        existing = next((a for a in affiliates.values() if a["email"] == email), None)
        if existing:
            return JSONResponse({"error": "Already registered", "ref_code": existing.get("code", "")}, status_code=409)

        ref_code = secrets_mod.token_urlsafe(6)
        affiliates[ref_code] = {
            "email": email,
            "code": ref_code,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "total_referrals": 0,
            "total_earnings": 0,
        }
        save_json(AFFILIATES_FILE, affiliates)

        ref_link = f"{DOMAIN}/?ref={ref_code}"
        return JSONResponse({"status": "ok", "ref_code": ref_code, "ref_link": ref_link})
    except Exception as e:
        logger.error(f"[AFFILIATE] Registration error: {e}")
        return JSONResponse({"error": "Something went wrong"}, status_code=500)


@app.get("/api/affiliate/stats")
async def affiliate_stats(ref: str = ""):
    if not ref:
        return JSONResponse({"error": "Missing ref code"}, status_code=400)

    affiliates = load_json(AFFILIATES_FILE, {})
    affiliate = affiliates.get(ref)
    if not affiliate:
        return JSONResponse({"error": "Invalid ref code"}, status_code=404)

    referrals = load_json(REFERRALS_FILE, [])
    my_referrals = [r for r in referrals if r.get("ref_code") == ref]

    return JSONResponse({
        "ref_code": ref,
        "total_referrals": len(my_referrals),
        "total_earnings": sum(r.get("commission", 0) for r in my_referrals),
        "referrals": my_referrals[-10:],
    })


@app.get("/affiliate", response_class=HTMLResponse)
async def affiliate_page(request: Request):
    return templates.TemplateResponse(request, "affiliate.html", {
        "ga_id": GA_MEASUREMENT_ID,
        "domain": DOMAIN,
    })


def track_referral(ref_code: str, customer_email: str, amount: int):
    affiliates = load_json(AFFILIATES_FILE, {})
    if ref_code not in affiliates:
        return

    commission = int(amount * 0.50)  # 50% commission
    referrals = load_json(REFERRALS_FILE, [])
    referrals.append({
        "ref_code": ref_code,
        "customer_email": customer_email[:3] + "***",
        "amount": amount,
        "commission": commission,
        "date": datetime.now(timezone.utc).isoformat(),
    })
    save_json(REFERRALS_FILE, referrals)

    affiliates[ref_code]["total_referrals"] = affiliates[ref_code].get("total_referrals", 0) + 1
    affiliates[ref_code]["total_earnings"] = affiliates[ref_code].get("total_earnings", 0) + commission
    save_json(AFFILIATES_FILE, affiliates)
    logger.info(f"[AFFILIATE] Referral tracked: {ref_code} earned ${commission / 100:.2f}")


# ── Blog / SEO ──

@app.get("/blog", response_class=HTMLResponse)
async def blog_index(request: Request):
    return templates.TemplateResponse(request, "blog_index.html", {
        "ga_id": GA_MEASUREMENT_ID,
    })


@app.get("/blog/{slug}", response_class=HTMLResponse)
async def blog_post(request: Request, slug: str):
    posts = get_blog_posts()
    post = posts.get(slug)
    if not post:
        return JSONResponse({"error": "Post not found"}, status_code=404)
    return templates.TemplateResponse(request, "blog_post.html", {
        "ga_id": GA_MEASUREMENT_ID,
        "post": post,
    })


def get_blog_posts():
    return {
        "how-to-make-money-with-ai-2025": {
            "slug": "how-to-make-money-with-ai-2025",
            "title": "How to Make Money With AI in 2025: 7 Proven Methods",
            "description": "Discover 7 proven ways to earn money with AI in 2025. From freelancing to digital products, learn exactly how beginners are turning AI into income.",
            "content": """
<p>Artificial intelligence isn't just for tech companies anymore. In 2025, regular people are using AI tools like ChatGPT, Claude, and Midjourney to build real income streams - even without coding skills or a big budget.</p>

<p>Here are <strong>7 proven methods</strong> that are working right now:</p>

<h2>1. AI-Powered Freelancing</h2>
<p>Platforms like Upwork and Fiverr are flooded with clients looking for AI-assisted services. Copywriting, social media management, and content creation are the top earners. With the right prompts, you can deliver premium-quality work in a fraction of the time.</p>
<p><strong>Earning potential:</strong> $500-$5,000/month starting out</p>

<h2>2. Create and Sell Digital Products</h2>
<p>Use AI to create eBooks, templates, printables, and courses. Sell them on Gumroad, Etsy, or your own website. The key is finding a niche where people are actively looking for solutions.</p>
<p><strong>Earning potential:</strong> $200-$10,000/month (passive after setup)</p>

<h2>3. AI Content Creation</h2>
<p>Start a blog, YouTube channel, or social media presence using AI to help with ideation, scripting, and editing. Monetize through ads, sponsorships, and affiliate marketing.</p>
<p><strong>Earning potential:</strong> $100-$5,000/month</p>

<h2>4. AI Consulting</h2>
<p>Help small businesses integrate AI into their workflows. Most business owners know AI exists but don't know where to start. You can charge $50-$200/hour to show them how to use ChatGPT for customer service, marketing, and operations.</p>
<p><strong>Earning potential:</strong> $2,000-$10,000/month</p>

<h2>5. Prompt Engineering</h2>
<p>Companies are hiring prompt engineers to craft effective AI prompts. You can sell prompt packs, offer prompt optimization services, or work as a full-time prompt engineer.</p>
<p><strong>Earning potential:</strong> $1,000-$8,000/month</p>

<h2>6. AI-Powered Automation Services</h2>
<p>Build automated workflows for businesses using tools like Zapier, Make, and AI APIs. Automate their email marketing, lead generation, and data processing.</p>
<p><strong>Earning potential:</strong> $1,000-$5,000/month</p>

<h2>7. AI Tutoring and Coaching</h2>
<p>Teach others how to use AI tools effectively. Create courses, do 1-on-1 coaching, or build a community. The demand for AI education is exploding.</p>
<p><strong>Earning potential:</strong> $500-$5,000/month</p>

<h2>The Fastest Way to Start</h2>
<p>The hardest part isn't learning AI - it's knowing where to start. That's exactly why we created the <strong>AI Income Blueprint</strong>. It gives you the templates, prompts, and a 30-day action plan so you can skip the research phase and start earning immediately.</p>
""",
            "date": "2025-01-15",
        },
        "best-ai-side-hustles-beginners": {
            "slug": "best-ai-side-hustles-beginners",
            "title": "5 Best AI Side Hustles for Complete Beginners",
            "description": "No experience needed. These 5 AI side hustles can earn you $300-$3,000/month starting from scratch. Step-by-step guide included.",
            "content": """
<p>You don't need a computer science degree to make money with AI. These 5 side hustles are perfect for complete beginners and can be started this weekend.</p>

<h2>1. AI Copywriting</h2>
<p>Businesses need website copy, emails, and ads written constantly. Use ChatGPT to draft, then polish with your human touch. Start on Fiverr or Upwork - many sellers earn $500-$2,000/month within their first 90 days.</p>
<p><strong>Time to first dollar:</strong> 1-2 weeks</p>

<h2>2. Social Media Management with AI</h2>
<p>Small businesses will pay $500-$1,500/month to have someone manage their social media. Use AI to generate post ideas, write captions, and create content calendars. You can manage 3-5 clients working just 1-2 hours per day.</p>
<p><strong>Time to first dollar:</strong> 1-3 weeks</p>

<h2>3. AI-Generated Print-on-Demand</h2>
<p>Use AI image generators to create designs for t-shirts, mugs, and phone cases. Upload to Redbubble, TeeSpring, or Merch by Amazon. It's passive income - you create once and earn every time someone buys.</p>
<p><strong>Time to first dollar:</strong> 2-4 weeks</p>

<h2>4. Sell AI Prompt Packs</h2>
<p>Create themed prompt packs (e.g., "50 ChatGPT Prompts for Real Estate Agents") and sell them for $9-$27 on Gumroad or Etsy. These are pure digital products with zero inventory costs.</p>
<p><strong>Time to first dollar:</strong> 1 week</p>

<h2>5. AI Resume and Cover Letter Writing</h2>
<p>Help job seekers create optimized resumes and cover letters using AI. Charge $25-$75 per resume. With AI doing the heavy lifting, you can complete 5-10 per day.</p>
<p><strong>Time to first dollar:</strong> 1 week</p>

<h2>Get Started Today</h2>
<p>The <strong>AI Income Blueprint</strong> includes done-for-you templates, 50 plug-and-play prompts, and a 30-day action plan to help you launch any of these side hustles. No guessing required.</p>
""",
            "date": "2025-01-20",
        },
        "chatgpt-money-making-prompts": {
            "slug": "chatgpt-money-making-prompts",
            "title": "10 ChatGPT Prompts That Can Actually Make You Money",
            "description": "Stop using ChatGPT for fun. These 10 prompts are designed to help you earn real money through freelancing, content creation, and digital products.",
            "content": """
<p>Most people use ChatGPT to write essays or ask random questions. But with the right prompts, it becomes a money-making machine. Here are 10 prompts that can directly lead to income.</p>

<h2>1. The Client Proposal Prompt</h2>
<p><em>"Write a professional proposal for a [service type] project for [client industry]. Include deliverables, timeline, and pricing at [$X]. Make it persuasive but not pushy."</em></p>
<p>Use this to land freelance gigs on Upwork, Fiverr, or cold outreach. A good proposal can land you a $500-$2,000 contract.</p>

<h2>2. The Product Description Prompt</h2>
<p><em>"Write 5 compelling product descriptions for [product] targeting [audience]. Each should be 100-150 words, include benefits over features, and end with a call-to-action."</em></p>
<p>Sell this service to e-commerce stores. They'll pay $5-$15 per description, and you can write 50 in an hour with AI.</p>

<h2>3. The Blog Post Outline Prompt</h2>
<p><em>"Create a detailed blog post outline for '[topic]' targeting the keyword '[keyword]'. Include H2 and H3 headings, key points for each section, and internal linking suggestions."</em></p>
<p>Content agencies pay $50-$200 per blog post. With AI handling the outline and first draft, you can produce 3-5 posts per day.</p>

<h2>4. The Email Sequence Prompt</h2>
<p><em>"Write a 5-email welcome sequence for [business type]. Each email should build on the last, provide value, and subtly sell [product/service]. Include subject lines with open rate predictions."</em></p>
<p>Email marketing services are in massive demand. Charge $200-$500 per email sequence.</p>

<h2>5. The Social Media Content Calendar Prompt</h2>
<p><em>"Create a 30-day social media content calendar for [business] on [platform]. Include post copy, hashtags, best posting times, and content mix (educational, entertaining, promotional)."</em></p>
<p>Social media managers charge $500-$1,500/month. This prompt does 80% of the work.</p>

<h2>6. The Course Outline Prompt</h2>
<p><em>"Design a comprehensive online course outline on [topic] for [audience level]. Include module titles, lesson breakdowns, assignments, and bonus materials. Target 4-6 hours of content."</em></p>
<p>Online courses sell for $47-$497. Use this to plan and create yours.</p>

<h2>7. The Sales Page Copy Prompt</h2>
<p><em>"Write a high-converting sales page for [product] priced at [$X] targeting [audience]. Use the PAS framework (Problem, Agitate, Solution). Include testimonial placeholders and FAQ section."</em></p>
<p>Sales page copywriting pays $500-$5,000 per page.</p>

<h2>8. The Lead Magnet Prompt</h2>
<p><em>"Create a [type: checklist/guide/template] lead magnet titled '[title]' for [audience]. It should solve [specific problem] and be completable in [X minutes]. Include 5-10 actionable items."</em></p>
<p>Lead magnets grow email lists, which you can monetize through affiliate marketing and product sales.</p>

<h2>9. The Market Research Prompt</h2>
<p><em>"Analyze the market for [product/service] targeting [audience]. Identify top 5 competitors, their pricing, unique selling points, and gaps in the market I can exploit."</em></p>
<p>Use this before launching any product to validate demand and find your angle.</p>

<h2>10. The Passive Income Idea Prompt</h2>
<p><em>"Generate 10 digital product ideas I can create with AI in under a week that target [niche]. For each, include: product format, target audience, pricing suggestion, and potential monthly revenue."</em></p>
<p>This is your brainstorming engine for building passive income streams.</p>

<h2>Want 50 More Prompts Like These?</h2>
<p>The <strong>AI Income Blueprint</strong> includes 50 plug-and-play prompts organized by use case - plus templates, a freelancer quick-start guide, and a 30-day action plan. Everything you need to turn AI into income.</p>
""",
            "date": "2025-02-01",
        },
        "ai-freelancing-guide": {
            "slug": "ai-freelancing-guide",
            "title": "The Complete Guide to AI Freelancing in 2025",
            "description": "How to start freelancing with AI skills. Covers pricing, finding clients, delivering work, and scaling to $5K/month. Real strategies that work.",
            "content": """
<p>AI freelancing is one of the fastest paths to earning income online. Companies of all sizes need people who can use AI effectively, and they're willing to pay well for it.</p>

<h2>Why AI Freelancing?</h2>
<ul>
<li><strong>Low barrier to entry</strong> - No degree required, just learn the tools</li>
<li><strong>High demand</strong> - More businesses want AI help than there are freelancers</li>
<li><strong>Premium pricing</strong> - AI skills command 30-50% more than traditional freelancing</li>
<li><strong>Fast delivery</strong> - AI helps you do in hours what used to take days</li>
</ul>

<h2>Step 1: Choose Your Service</h2>
<p>The most profitable AI freelancing services right now:</p>
<ul>
<li><strong>AI Copywriting</strong> ($50-$200/piece) - Website copy, ads, emails</li>
<li><strong>AI Content Creation</strong> ($100-$500/post) - Blog posts, articles, scripts</li>
<li><strong>AI Social Media</strong> ($500-$1,500/month) - Content calendars, post creation</li>
<li><strong>AI Automation</strong> ($500-$2,000/project) - Workflow automation, chatbots</li>
<li><strong>AI Consulting</strong> ($100-$300/hour) - Helping businesses adopt AI</li>
</ul>

<h2>Step 2: Build Your Portfolio</h2>
<p>Create 3-5 sample projects using AI. These don't need to be for real clients - just show what you can do. Post them on your Upwork profile, personal website, or LinkedIn.</p>

<h2>Step 3: Set Your Pricing</h2>
<p>Start competitive, raise as you get reviews:</p>
<ul>
<li><strong>Beginner:</strong> 70% of market rate (to get first 5-10 reviews)</li>
<li><strong>Intermediate:</strong> Market rate (after 10+ reviews)</li>
<li><strong>Expert:</strong> 150% of market rate (after 50+ reviews)</li>
</ul>

<h2>Step 4: Find Your First Clients</h2>
<p>The best platforms for AI freelancing:</p>
<ol>
<li><strong>Upwork</strong> - Best for ongoing contracts</li>
<li><strong>Fiverr</strong> - Best for productized services</li>
<li><strong>LinkedIn</strong> - Best for B2B consulting</li>
<li><strong>Cold email</strong> - Best for premium clients</li>
</ol>

<h2>Step 5: Deliver and Scale</h2>
<p>The key to scaling is creating systems. Use AI to templatize your delivery process so you can handle more clients without working more hours.</p>

<h2>Get the Templates You Need</h2>
<p>The <strong>AI Income Blueprint</strong> includes freelancer quick-start templates - client proposals, pricing guides, and outreach scripts that are ready to customize and send.</p>
""",
            "date": "2025-02-10",
        },
        "digital-products-ai": {
            "slug": "digital-products-ai",
            "title": "How to Create and Sell Digital Products Using AI",
            "description": "Learn how to use AI to create eBooks, templates, courses, and printables that sell. Step-by-step guide for building passive income with digital products.",
            "content": """
<p>Digital products are the ultimate passive income. Create once, sell forever. And with AI, you can create professional-quality products in days instead of months.</p>

<h2>Why Digital Products?</h2>
<ul>
<li><strong>Zero inventory costs</strong> - No shipping, no storage, no manufacturing</li>
<li><strong>Infinite scalability</strong> - Sell to 1 person or 10,000 with the same effort</li>
<li><strong>High margins</strong> - 90%+ profit after platform fees</li>
<li><strong>Passive income</strong> - Earn while you sleep once it's set up</li>
</ul>

<h2>Best Digital Products to Create with AI</h2>

<h3>1. eBooks and Guides ($9-$47)</h3>
<p>Use AI to research, outline, and draft your eBook. Focus on solving a specific problem for a specific audience. A 30-50 page guide takes 2-3 days with AI help.</p>

<h3>2. Template Packs ($15-$67)</h3>
<p>Create Notion templates, spreadsheets, planners, or document templates. AI can help design the structure and write the content. Template packs on Etsy and Gumroad consistently sell well.</p>

<h3>3. Prompt Packs ($7-$27)</h3>
<p>Curate and test collections of AI prompts for specific niches. "50 ChatGPT Prompts for Real Estate Agents" or "AI Prompts for Social Media Managers." These are fast to create and have huge demand.</p>

<h3>4. Online Courses ($47-$497)</h3>
<p>Use AI to outline your curriculum, create lesson scripts, generate quiz questions, and build worksheets. Record short video lessons and package everything together.</p>

<h3>5. Printables ($3-$15)</h3>
<p>Planners, checklists, wall art, and organizational tools. Use AI for the content and Canva for the design. Sell on Etsy for consistent passive income.</p>

<h2>Where to Sell</h2>
<ul>
<li><strong>Gumroad</strong> - Best for eBooks and courses (simple setup, low fees)</li>
<li><strong>Etsy</strong> - Best for printables and templates (built-in traffic)</li>
<li><strong>Your own website</strong> - Best for premium products (full control)</li>
<li><strong>Teachable/Thinkific</strong> - Best for courses (professional delivery)</li>
</ul>

<h2>The Launch Formula</h2>
<ol>
<li><strong>Validate</strong> - Search for your product idea on Etsy/Gumroad. If competitors exist and have sales, there's demand.</li>
<li><strong>Create</strong> - Use AI to build your product in 2-5 days.</li>
<li><strong>Price</strong> - Start at the lower end of competitor pricing.</li>
<li><strong>Launch</strong> - Post on social media, run a small ad, or reach out to your email list.</li>
<li><strong>Iterate</strong> - Improve based on feedback and create related products.</li>
</ol>

<h2>Start Building Today</h2>
<p>The <strong>AI Income Blueprint</strong> includes a complete Digital Product Launch Guide with step-by-step instructions for going from idea to first sale. Plus 50 AI prompts to help you create content faster.</p>
""",
            "date": "2025-02-15",
        },
    }


# ── Email Sequence System ──

def queue_email_sequence(customer_email: str, session_id: str):
    queue = load_json(EMAIL_QUEUE_FILE, [])
    now = datetime.now(timezone.utc)
    for email_config in EMAIL_SEQUENCE[1:]:  # Skip day 0 (already sent)
        send_at = now + timedelta(days=email_config["day"])
        queue.append({
            "email": customer_email,
            "session_id": session_id,
            "template": email_config["template"],
            "subject": email_config["subject"],
            "send_at": send_at.isoformat(),
            "sent": False,
        })
    save_json(EMAIL_QUEUE_FILE, queue)
    logger.info(f"[EMAIL] Queued {len(EMAIL_SEQUENCE) - 1} follow-up emails for {customer_email}")


async def email_sequence_worker():
    while True:
        await asyncio.sleep(3600)  # Check every hour
        if not SENDGRID_API_KEY:
            continue
        try:
            queue = load_json(EMAIL_QUEUE_FILE, [])
            now = datetime.now(timezone.utc)
            updated = False
            for item in queue:
                if item.get("sent"):
                    continue
                send_at = datetime.fromisoformat(item["send_at"])
                if now >= send_at:
                    try:
                        html = get_sequence_email_html(item["template"], item["session_id"])
                        await send_email(item["email"], item["subject"], html)
                        item["sent"] = True
                        updated = True
                        logger.info(f"[EMAIL] Sent sequence email '{item['template']}' to {item['email']}")
                    except Exception as e:
                        logger.error(f"[EMAIL] Failed sequence email: {e}")
            if updated:
                save_json(EMAIL_QUEUE_FILE, queue)
        except Exception as e:
            logger.error(f"[EMAIL] Worker error: {e}")


def get_sequence_email_html(template: str, session_id: str) -> str:
    download_url = f"{DOMAIN}/thank-you?session_id={session_id}"

    templates_map = {
        "day3": f"""
        <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 600px; margin: 0 auto; padding: 40px 20px; color: #333;">
            <h1 style="color: #6c5ce7; font-size: 24px;">Have You Started Yet?</h1>
            <p style="font-size: 16px; line-height: 1.6;">Hey there,</p>
            <p style="font-size: 16px; line-height: 1.6;">It's been 3 days since you got the AI Income Blueprint. Have you opened it yet?</p>
            <p style="font-size: 16px; line-height: 1.6;">Here's the thing: <strong>the people who earn with AI aren't smarter</strong> - they just start. Even 15 minutes today puts you ahead of 90% of people who bought but never opened it.</p>
            <p style="font-size: 16px; line-height: 1.6;"><strong>Quick action step:</strong> Open the AI Income Playbook and read just the first section (5 minutes). Pick ONE method that interests you.</p>
            <div style="text-align: center; margin: 32px 0;">
                <a href="{download_url}" style="display: inline-block; background: linear-gradient(135deg, #6c5ce7, #a855f7); color: white; padding: 14px 32px; border-radius: 8px; text-decoration: none; font-weight: 700;">Access Your Downloads</a>
            </div>
            <p style="font-size: 14px; color: #888;">You got this. - AI Income Blueprint Team</p>
        </div>""",
        "day5": f"""
        <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 600px; margin: 0 auto; padding: 40px 20px; color: #333;">
            <h1 style="color: #6c5ce7; font-size: 24px;">Try This AI Prompt Today</h1>
            <p style="font-size: 16px; line-height: 1.6;">Here's a quick win you can get in the next 10 minutes:</p>
            <div style="background: #f8f9fa; border-left: 4px solid #6c5ce7; padding: 20px; margin: 20px 0; border-radius: 4px;">
                <p style="font-size: 15px; font-style: italic; margin: 0;">"Write a professional LinkedIn post about [your expertise/interest]. Make it conversational, include a personal insight, and end with a question to drive engagement. Keep it under 200 words."</p>
            </div>
            <p style="font-size: 16px; line-height: 1.6;">Paste this into ChatGPT, fill in the brackets, and post it on LinkedIn. This is how people start building an audience that leads to paid opportunities.</p>
            <p style="font-size: 16px; line-height: 1.6;">You have <strong>49 more prompts</strong> like this in your Prompt Pack. Each one is designed to produce something you can sell or use to attract clients.</p>
            <div style="text-align: center; margin: 32px 0;">
                <a href="{download_url}" style="display: inline-block; background: linear-gradient(135deg, #6c5ce7, #a855f7); color: white; padding: 14px 32px; border-radius: 8px; text-decoration: none; font-weight: 700;">Get Your 50 Prompts</a>
            </div>
        </div>""",
        "day7": f"""
        <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 600px; margin: 0 auto; padding: 40px 20px; color: #333;">
            <h1 style="color: #6c5ce7; font-size: 24px;">How Others Are Earning With AI</h1>
            <p style="font-size: 16px; line-height: 1.6;">One week in. Here's what's possible when you stick with the plan:</p>
            <ul style="font-size: 16px; line-height: 2;">
                <li>Freelancers are landing their first AI gigs within 2 weeks of starting</li>
                <li>Digital product creators are launching their first product in under 7 days</li>
                <li>Content creators are using the prompts to post consistently and grow their audience</li>
            </ul>
            <p style="font-size: 16px; line-height: 1.6;">The common thread? <strong>They followed the 30-Day Action Plan.</strong> Day by day, step by step. No skipping ahead, no overthinking.</p>
            <p style="font-size: 16px; line-height: 1.6;">If you haven't started the 30-Day Plan yet, today is Day 1. Open it up and do just the first task. It takes 20 minutes.</p>
            <div style="text-align: center; margin: 32px 0;">
                <a href="{download_url}" style="display: inline-block; background: linear-gradient(135deg, #6c5ce7, #a855f7); color: white; padding: 14px 32px; border-radius: 8px; text-decoration: none; font-weight: 700;">Start Your 30-Day Plan</a>
            </div>
        </div>""",
        "day14": f"""
        <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 600px; margin: 0 auto; padding: 40px 20px; color: #333;">
            <h1 style="color: #6c5ce7; font-size: 24px;">Ready to Level Up?</h1>
            <p style="font-size: 16px; line-height: 1.6;">It's been 2 weeks since you got the AI Income Blueprint. By now, you should be starting to see what's possible with AI.</p>
            <p style="font-size: 16px; line-height: 1.6;">Here's what to focus on next:</p>
            <ol style="font-size: 16px; line-height: 2;">
                <li><strong>Double down</strong> on the method that excites you most</li>
                <li><strong>Revisit the prompts</strong> - try 5 new ones this week</li>
                <li><strong>Share your progress</strong> - post about your journey on social media</li>
            </ol>
            <p style="font-size: 16px; line-height: 1.6;">Remember: consistency beats perfection. Even 30 minutes a day compounds into real results over time.</p>
            <p style="font-size: 16px; line-height: 1.6;">And if you know someone who could benefit from the Blueprint, <strong>share it with them</strong>. Help them skip the confusion and start earning too.</p>
            <div style="text-align: center; margin: 32px 0;">
                <a href="{DOMAIN}" style="display: inline-block; background: linear-gradient(135deg, #6c5ce7, #a855f7); color: white; padding: 14px 32px; border-radius: 8px; text-decoration: none; font-weight: 700;">Share the Blueprint</a>
            </div>
            <p style="font-size: 14px; color: #888;">Keep going. You're closer than you think. - AI Income Blueprint Team</p>
        </div>""",
    }
    return templates_map.get(template, "")


async def send_email(to_email: str, subject: str, html_content: str):
    payload = {
        "personalizations": [{"to": [{"email": to_email}]}],
        "from": {"email": FROM_EMAIL, "name": "AI Income Blueprint"},
        "subject": subject,
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


async def send_purchase_email(to_email: str, session_id: str):
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
    await send_email(to_email, "Your AI Income Blueprint is ready to download", html_content)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
