# Smart Engine CDP: Turning a Stalled Approval Into a Clear Product Line

**Role:** Product Manager
**Artifacts:** [Interactive prototype](./index.html) · [Full PRD](./prd.html)

## The problem

I was leading the PRD and architecture for "Smart Engine," a system meant to turn customer data into smart, personalized actions for a cross-functional group — Marketing, CX, Sales, Buyers/Ops, and Data Science.

The plan kept stalling in approval. Digging into why, the issue wasn't the vision — it was one specific phase: a "CDP" (Customer Data Platform) that every reviewer nodded along to but couldn't actually picture. It read as a black box between "we have data" and "smart things happen," which made the whole multi-phase plan feel bloated and hard to greenlight.

## My approach

**1. Reframed the CDP as a concrete decision layer, not an infrastructure phase.**
Instead of describing it as a data platform, I defined it by the one question it answers for every team: *given everything we know about a customer right now, what should we do — and why?* That single framing made it obvious the CDP wasn't optional plumbing — it was the thing preventing five teams from quietly building five different, conflicting versions of the same logic.

**2. Scoped it against explicit non-goals.**
The fastest way to stall approval on a platform concept is to let it sound infinite. I paired every capability with what it explicitly would *not* do (no campaign builder, no BI replacement, no per-channel custom logic), which made the ask feel bounded and lower-risk.

**3. Split delivery into three phases that each stand alone.**
Read-only customer context first, then eligibility and decisioning, then explainability and governance — so the roadmap read as sequenced value, not one large bet.

**4. Built a clickable prototype instead of relying on the doc alone.**
A PRD can describe explainability; it can't make a reviewer *feel* what "why was this customer included" looks like in a real interface. I built a guided-tour prototype covering Customer 360, model outputs, the decision/eligibility layer, activation, and a full explainability drill-down — with a live "decision ledger" showing individual decisions streaming through with their reasoning attached.

## The outcome

- The CDP stopped being the phase nobody could explain and became the anchor that made the rest of the roadmap make sense to stakeholders.
- The three-phase structure gave engineering, DS, and ops a shared, concrete scope to size instead of an abstract platform ask.
- The prototype gave non-technical reviewers a tangible way to react to the decisioning and explainability model before a line of production code was written — surfacing feedback (like the conflict-resolution priority order) earlier and more cheaply than a written spec would have.

## What this demonstrates

- Translating a stalled, ambiguous platform ask into a scoped, phased product.
- Designing for cross-functional trust — explainability as a first-class requirement, not an afterthought.
- Using a working prototype, not just a document, to de-risk a decision before engineering investment.

---
*All customer data shown in the prototype is fictional, generated for demonstration purposes.*
