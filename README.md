# AI Cash Starter Kit

Landing page and checkout for the AI Cash Starter Kit digital product ($27 one-time).

## Tech Stack

- **FastAPI** — Backend
- **Jinja2** — HTML templates
- **Stripe** — Payment processing
- **Fly.io** — Hosting

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

## Environment Variables

Copy `.env.example` to `.env` and fill in your Stripe keys:

```bash
cp .env.example .env
```

## Run Locally

```bash
export STRIPE_SECRET_KEY="sk_test_..."
export STRIPE_PUBLISHABLE_KEY="pk_test_..."
uvicorn app.main:app --reload --port 8000
```

## Deploy to Fly.io

```bash
fly launch
fly secrets set STRIPE_SECRET_KEY="..." STRIPE_PUBLISHABLE_KEY="..." STRIPE_WEBHOOK_SECRET="..."
fly deploy
```

## Product Content

Product files are in the `products/` directory:
- `01-ai-income-playbook.md` — 7 methods to make money with AI
- `02-50-ai-prompts.md` — Copy-paste prompts for every use case
- `03-freelancer-templates.md` — Client proposals, outreach, pricing
- `04-digital-product-launch-guide.md` — From idea to first sale
- `05-ai-tools-cheat-sheet.md` — 35+ tools reviewed
- `06-30-day-action-plan.md` — Daily tasks for your first month
