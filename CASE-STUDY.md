# Case Study: Smart Engine — a shared identity layer for CDP, sales, and marketing

**Role:** Product Manager (solo, end-to-end — PRD, UX, and reference engineering)
**Timeline:** Prototype built over several iterations, from single-feature demo to a three-app platform with a working backend.

## Problem

Three teams at a growing e-commerce/resale business each needed to know
"who is this customer," and each solved it differently:

- **Lifecycle/CRM** sent reactivation offers based on whatever signals
  it had locally — sometimes to customers who'd already converted on a
  different account, or who should have been suppressed.
- **Sales/concierge reps** fielded calls from high-value customers but
  had to manually cross-reference personal and business accounts to see
  full purchase history, costing time on every call and risking a
  disjointed experience for the customer.
- **Marketing** built audiences from exports and spreadsheets, with no
  shared source of truth for who belonged in a segment or why, no
  visibility into real match rates once an audience hit an ad channel,
  and no way to see how that audience actually performed afterward
  without logging into each channel's dashboard separately and manually
  reconciling the numbers.

None of these were engineering problems in isolation — they were the
same problem, solved three times, with three incompatible answers.

## Approach

Rather than fixing each team's tool separately, I proposed a shared
**identity-resolution layer**: every known identifier (email, phone,
external account ID) resolves to one canonical Person ID, and every
downstream product — CDP, Rep App, Marketing — reads from and writes to
that same graph instead of maintaining its own partial view.

I wrote the PRD in parts rather than as one flat document — an identity
layer section all three teams' requirements reference, then a dedicated
section per product — so each team's stakeholders could review their
part without wading through the others, while the identity contract
stayed the single source of truth everyone built against.

To de-risk the design before asking for engineering investment, I built
a working reference implementation myself:

- An interactive, click-through **prototype** of all three apps sharing
  one identity layer and one "Decision Ledger" showing every automated
  decision's reasoning in real time — so stakeholders could *see* the
  behavior, not just read about it.
- A real, tested **backend** (PersonGraph API) implementing identity
  resolution, a rules-based decision engine, audience segmentation, and
  post-activation measurement — not a mockup, but working code with
  swappable provider interfaces so a real identity source (e.g. Segment)
  and real channel reporting APIs (Meta, Google) can be dropped in later
  without touching the rest of the system.
- The prototype wired to the live backend, with graceful fallback to
  realistic static data when the backend isn't reachable — so the demo
  works equally well in a hallway conversation or a sandboxed review.

## Key decisions

- **Suppression always overrides the model.** Early in design, a high
  propensity-to-convert score could still produce an offer to a
  suppressed customer if the rules weren't explicit about precedence.
  I made suppression a hard override in the decision engine and logged
  every such conflict explicitly, rather than letting it fail silently.
- **Decisions are explainable by default.** Every automated decision
  records which rule fired, the model and version used, and a
  human-readable reason — because compliance and marketing ops both
  needed to audit *why*, not just *what*.
- **One identity contract, three consumers.** The Rep App and Marketing
  Platform never implement their own matching logic — they call the
  same `GET /identity/lookup` the CDP uses, so identity logic changes
  once and propagates everywhere.
- **Swappable, not hardcoded, integrations.** The identity resolver and
  the decision engine are both built behind small interfaces so a real
  Segment connection or a new eligibility rule can be added without
  rewriting the apps that consume them.

## Outcome

A fully working, three-app reference platform:

- An interactive demo covering 11 views across CDP, Rep App, and
  Marketing, usable standalone or live-wired to a real backend.
- A tested FastAPI backend with identity resolution, decisioning, and
  audience/activation logic, deployable via Docker to any standard host.
- A PRD structured so each team can review its own requirements against
  one shared identity contract, rather than three disconnected specs.

This project demonstrates end-to-end product ownership — from framing a
cross-team problem, to writing requirements that scale across products,
to building and testing the reference system myself to prove the design
before asking anyone else to commit engineering time to it.
