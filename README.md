# Autonomous SQL Analysis Agent

An AI agent that answers plain-English questions about an e-commerce
database by generating SQL, executing it, and self-reviewing the
result — retrying up to 3 times if it isn't confident, with no
hardcoded correctness rules. Built for the NextBridge AI internship.

## Architecture

```
Client → FastAPI (/ask) → Celery queue → Redis (broker + cache + status)
                                              ↓
                                   Agent loop (Celery worker)
                                              ↓
                                            Redis
```

- **POST `/ask`** — submits a question. Checks the Redis cache first;
  on a cache hit, returns a synthetic `cached-...` job ID immediately.
  On a miss, dispatches a Celery task and returns its job ID.
- **GET `/status/{job_id}`** — polls for the result (cached or from
  the Celery task).
- **Agent loop** (`orchestrator.py`) — for each attempt (max 3):
  1. **SQL Generator agent** writes and executes a SQL query using a
     custom tool, producing a plain-English answer.
  2. **Reviewer agent** independently judges whether the query and
     answer are trustworthy, using only its own reasoning — no
     hardcoded `if/else` correctness checks.
  3. Python only **routes** based on the reviewer's decision
     (accept the result / retry with the reviewer's feedback). The
     judgment of "is this correct" is entirely the LLM's.
- Only successful (`status: success`) results are cached, so a
  transient failure never gets permanently stuck in the cache.

**Stack:** FastAPI · Celery · Redis · PostgreSQL · CrewAI, in 4 Docker
containers (`api`, `worker`, `redis`, `postgres`).

## Dataset

[Olist Brazilian E-Commerce](https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce)
(Kaggle), using 4 tables:

| Table | Rows | Purpose |
|---|---|---|
| `customers` | 99,441 | Customer + location |
| `orders` | 99,441 | Order status and timestamps |
| `order_items` | 112,650 | Line items: price, freight, product |
| `products` | 32,951 | Product category |

**Deliberate trap:** `orders.order_status` has 8 possible values
(`delivered`, `shipped`, `canceled`, `unavailable`, `invoiced`,
`processing`, `created`, `approved`). Revenue-style calculations must
exclude `canceled` and `unavailable` orders — but simple counts
should not. Two of the eight test questions specifically target this.

## LLM

Started on Google Gemini (free tier), but hit repeated quota walls —
Gemini's free tier is capped **per Google Cloud project**, not per
API key, so even a freshly generated key on the same account shared
the same exhausted quota.

Switched to **Groq** (`openai/gpt-oss-120b`), which needed no card and
no phone verification. That surfaced its own set of issues, each
fixed along the way — documented in [Limitations](#limitations--things-learned)
below, since debugging them was as much a part of this assignment as
the agent logic itself.

## Test Questions & Verified Answers

All 8 were run through the live API and manually cross-checked
against the database.

| # | Question | Answer | Trap? |
|---|---|---|---|
| 1 | Total revenue for delivered orders | $13,221,498.11 | |
| 2 | Total orders placed | 99,441 | |
| 3 | Total revenue for delivered + canceled + unavailable orders combined | $13,318,741.07 | ✓ |
| 4 | Count of canceled orders | 625 | |
| 5 | State with the most orders | SP, 41,746 | |
| 6 | Average order value (price only) for delivered orders | $119.98 | |
| 7 | Unique products sold in delivered orders | 32,216 | |
| 8 | % of all orders canceled or unavailable | 1.24% | ✓ |

## Limitations & Things Learned

- **Question wording matters more than expected.** Question 3's
  original wording ("total revenue including canceled/unavailable")
  was ambiguous — the agent read "including" as "in addition to the
  normal revenue filter" rather than "explicitly count these
  statuses in the total." Rewording it to be unambiguous fixed this.
  This suggests real-world deployments need either very precise
  question templates or a clarification step before the agent
  commits to an interpretation.
- **The reviewer needs the same context as the generator.** Early on,
  the reviewer rejected a *correct* query for "average order value"
  because its task prompt didn't include the schema's definition of
  that term — only the generator's prompt did. Both agents now
  receive the same schema/definitions, otherwise the reviewer
  enforces its own (possibly wrong) assumptions instead of the
  agreed ground truth.
- **Free-tier LLM infrastructure is not "set and forget."** Across
  this project: Gemini's daily quota is per-project, not per-key;
  Groq's per-minute token limit is tight enough that 3 retries in
  quick succession can exhaust it; and a CrewAI library bug injects
  an Anthropic-specific caching marker into every request regardless
  of provider, which Groq's stricter API validation rejects outright.
  None of these were bugs in the agent's *logic* — they were
  infrastructure/library compatibility issues that only showed up
  under real testing, and were fixed with a short retry delay, a
  trimmed schema prompt, and a small monkey-patch, respectively.
- **Structured output (Pydantic) isn't universally supported.**
  CrewAI's `output_pydantic` forces a synthetic tool call to get
  JSON back from the LLM; Groq's stricter tool-call validation
  rejected that synthetic call. Switching to plain-text JSON output,
  parsed manually with `json_repair`, resolved it without losing the
  structured-data guarantee.

## Setup

```bash
docker compose up -d --build
```

Then POST a question:

```bash
curl -X POST http://localhost:8000/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "What is the average order value (price only) for delivered orders?"}'
```

Poll the result:

```bash
curl http://localhost:8000/status/{job_id}
```