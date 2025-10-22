# AGA Grading (Render-ready)
Pricing locked: $15/card and 5 for $50. Includes AI pre-checks, QR certs, labels, PDFs, registry, and pop report.

## Deploy
- Build: `pip install -r requirements.txt`
- Start: `gunicorn app:app`

Routes: `/`, `/pricing`, `/submit`, `/lookup`, `/registry`, `/pop-report`, `/api/*`, `/c/<cert>/<hash>`, `/health`.
