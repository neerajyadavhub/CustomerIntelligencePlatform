# Smart Engine — Interactive Prototype

A clickable prototype of Smart Engine: one identity layer (Person ID), and three surfaces built on top of it — a CDP decision engine, a Rep App, and a Marketing Intelligence Platform.

Built to demonstrate product thinking (not a real backend): every screen is populated with realistic mock data so the flow reads like a live product.

**[View the live demo](#)** *(add your GitHub Pages link here once deployed)*

📄 [Read the full PRD](./prd.html) · 📝 [Read the case study](./CASE-STUDY.md)

## What it shows

Use the app switcher at the top of the sidebar to move between three connected apps:

| App | Screens | What it demonstrates |
|---|---|---|
| **CDP** | Customer 360, Signals & Models, Decision Layer, Activation, Explainability | The decision engine — identity, model outputs, eligibility, and a full "why" trace for any decision |
| **Rep App** | Customer Search, Unified Profile, Escalations | Search any identifier (email/phone/TRR ID), see every linked account for a person, and what happens when identity resolution is uncertain |
| **Marketing** | Audience Builder, Audience Library, Channel Sync | Build a rule-based audience straight from CDP signals, save it, and push it to email/ad channels with per-channel sync status |

All three read from the same underlying idea: a **Person ID** that unifies multiple TRR accounts (personal, business, anonymous session) into one identity, resolved via Segment and surfaced through a Customer 360 Identity API.

A "Decision Ledger" ticker at the bottom of every screen streams mock events across all three apps, to make the shared-identity thesis tangible at a glance.

## Running it locally

No build step or dependencies — it's a single static HTML file.

```bash
open index.html
# or
python3 -m http.server 8000   # then visit http://localhost:8000
```

## Hosting on GitHub Pages

1. Create a new repo (e.g. `smart-engine-demo`) and push these files to it.
2. In the repo, go to **Settings → Pages**.
3. Under "Build and deployment," set **Source: Deploy from a branch**, branch **main**, folder **/(root)**.
4. Save. GitHub will publish it at `https://<your-username>.github.io/<repo-name>/` within a minute or two.
5. Add that link to this README and to your resume/portfolio.

## Files

| File | Purpose |
|---|---|
| `index.html` | The interactive prototype — CDP, Rep App, and Marketing, with an app switcher |
| `prd.html` | Full product requirements: identity layer, CDP, Rep App, Marketing Intelligence, phasing |
| `CASE-STUDY.md` | Problem → approach → outcome write-up for portfolio/LinkedIn |

## Notes

- All names, IDs, and figures are fictional.
- This is a UI prototype, not a functioning system — there is no backend, database, Segment integration, or real model behind any of the numbers shown.
- Built to accompany a multi-part PRD covering a shared identity layer and three consuming products.
