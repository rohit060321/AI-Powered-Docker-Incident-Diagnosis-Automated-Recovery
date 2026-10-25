# OOM Incident → Two Agents → Kepler War Room → One Recovery

**Status:** plan only, nothing built yet. Three open questions at the bottom must be
answered before code starts (see [Blocking questions](#blocking-questions)).

---

## 0. One hour: what survives

The 3-hour plan below does not fit. This is the 60-minute version. Ranked by
minutes saved per unit of credibility lost.

### Keep real (in this order — stop when time runs out)

1. **NudgeBee gateway → Gemma.** Already installed; only the gateway process and one
   provider row are missing. This is the most valuable *and* most fragile step, so it
   goes first, not last. (§4, step 1–3.)
2. **The OOM** — 2 min. `docker run --memory=128m` with a mounted `oom.py`, no image
   build. Never fake it.
3. **The bridge** — 15 min. The deterministic comparator *is* the contribution.
4. **Execute once + verify** — 10 min. Lock file + second run + completion marker.
5. **Kepler war room approval** — 10 min. The visual payoff; also free.
6. **Second opinion** — the Challenger is a prompt and a model in the same step as #1.
   Costs nothing extra once the gateway answers.

### Cut, in this order

| # | Cut | Saves | What it costs |
|---|---|---|---|
| 1 | **JarvisLabs provider registered in the UI** — if the Providers screen fights you, call the endpoint directly with the same prompt. | 15 min | "NudgeBee prompt profile (gateway not wired)" instead of "NudgeBee analysed it." Decide by minute 20. |
| 2 | **No Dockerfile.** `docker run -v $PWD/oom_job:/j python:3.12-slim python /j/oom.py`. | 5 min | None. |
| 3 | **No Observer, no cluster.** Kepler stays disconnected. | 10 min | Kepler *approves*; the pipeline executes. Phrase as "approval gate," never "Kepler ran the fix." |
| 4 | **Drop `INSUFFICIENT` and the confidence threshold.** Only `AGREE` / `DISAGREE` / `DENIED`. | 10 min | One less demo branch. |
| 5 | **Compare 3 fields, not 4:** `cause`, `action`, `params.memory_limit`. `target` is whatever container failed. | 10 min | If asked about target matching: "the incident is scoped to one container." |
| 6 | **One model, two roles** instead of two models. | 10 min | "Two role-separated agents on one model" — not "two agents." |
| 7 | **No JSON repair retry.** One strict parse; failure = human review. | 10 min of debugging | A chatty model becomes a flagged incident. Arguably correct anyway. |

### Not a cut — build this, it saves the demo

`pipeline.py --proposals out/proposals.json` — read the two proposals from a file
instead of calling the agents. Five minutes. When the gateway or Gemma dies live on
stage, you rerun from the bridge and the rest of the demo continues. Rehearse the
switch once so it doesn't look like panic.

### 60-minute budget

| Min | Do |
|---|---|
| 0–3 | `docker run --memory=128m` OOMs → confirm `ExitCode 137`, `OOMKilled true`. `curl $GEMMA_BASE_URL/v1/models` → exact tag. |
| 3–8 | Gateway up on :8010 (`make run`), tenant id wired, `.env` written. |
| 8–20 | **Provider row for JarvisLabs + one successful `curl` through :8010.** This is the whole NudgeBee claim; nothing else starts until it returns 200. |
| 20–30 | `oom_job/oom.py`, `pipeline.py` (evidence → two calls → bridge). |
| 30–40 | `execute_once` + `verify` + `ledger.jsonl`. |
| 40–48 | Scenario A end to end. Fix. |
| 48–54 | Scenario B: mutate one field in `proposals.json`, rerun the bridge. |
| 54–60 | Kepler war room + rehearse once. |

**The gate at minute 20 is hard.** If the gateway has not returned a real completion by
then, switch to direct JarvisLabs calls, keep the NudgeBee prompt and the provider
config on screen, and spend the rest of the hour on the bridge.

**The 20 containers are already running** — do not restart them, and do not run them
down before the demo. They are the only reason the NudgeBee claim is possible at all.

---

## 1. Does the Kepler-as-aggregator idea make sense?

**As the surface: yes. As the decision logic: no.**

Kepler is a desktop chat agent (RubixKube's, released Sept 2026). A war room has a
lead plus a member per angle, a single approval queue, and postures
(Observe / Assist / Yolo). That is an excellent **place for a human to accept or
reject a recovery**, and it gives the demo a real UI instead of a console dump.

But if the war room's lead *authors* the verdict, then "both agents agreed" becomes
an LLM's opinion, and there is no artifact that proves agreement. Your stated
contribution is the agreement check — don't hand it to a third model.

So: **a 60-line deterministic script computes the verdict; the war room displays it
and a human approves it.** The war room is the *aggregation surface*, the script is
the *comparator*. One extra file, and the claim survives a judge's "how do you know?"

```
Docker job OOMKilled
      │
      ▼
 evidence.json ──┬─► Diagnostician ──► proposal A ─┐   both via NudgeBee's
 (identical      │                                  ├─► bridge.py ─► verdict
  bytes to both) └─► Challenger ─────► proposal B ─┘   gateway → JarvisLabs Gemma
                                                          (deterministic)
                                                                          │
              ┌───────────────────────────────────────────────────────────┴────────┐
              ▼                                                                     ▼
     AGREE + permitted                                            DISAGREE / thin evidence
     execute once (idempotent)                                     no execution
              │                                                                     │
              ▼                                                                     ▼
     verify: OOMKilled=false, log marker                              Kepler war room:
              │                                                      both proposals + evidence
              └──────────────────► ledger.jsonl ◄───────────────────────────┘
```

---

## 2. The pieces

Six moving parts. Nothing else — no queue, no database, no web server, no plugin
surface.

| # | Piece | Form | Notes |
|---|---|---|---|
| 1 | **The failing job** | `oom_job/` (Dockerfile + 30-line Python) | Allocates 512 MB under `--memory=128m`. App logs its own RSS every 200 ms, so the last log line *is* the evidence ("RSS 131.2 MB > limit 128 MiB"). |
| 2 | **Evidence builder** | `pipeline.py::collect_evidence()` | `docker inspect` (`ExitCode`, `OOMKilled`, `HostConfig.Memory`) + last 50 log lines → `out/evidence.json`. |
| 3 | **Two agent calls** | `pipeline.py::ask_both()` | Parallel (`ThreadPoolExecutor`). Both go to NudgeBee's gateway at `:8010` with `GATEWAY_STATIC_TOKEN`; they differ only in model and system prompt. Same prompt string for the evidence; the script logs `evidence_sha256` on both calls and asserts they match. |
| 4 | **The bridge** | `pipeline.py::bridge()` | Deterministic. See §3. |
| 5 | **Execute + verify** | `pipeline.py::execute_once()` / `verify()` | `docker rm -f` + `docker run --memory=1g`; guarded by `out/executed.lock` so a second invocation is a no-op. Verify = new container has `OOMKilled=false` **and** prints the completion marker. |
| 6 | **Kepler war room** | manual, one room per incident | Paste the decision card (evidence hash, both proposals, verdict, exact command). Approve in **Assist** posture. Kepler's own model does not need to be Gemma. |

`out/ledger.jsonl` is the decision trail: append-only, one line per stage
(incident, proposal A, proposal B, verdict, execution, verification), each with a
timestamp and the evidence hash. That is the whole "preserved trail."

**Files:**

```
mlh-thing/
  PLAN.md
  demo.sh                    # one command: fail → analyse → bridge → recover → verify
  oom_job/
    Dockerfile
    oom.py
  pipeline.py                # 5 numbered functions, ~300 lines, stdlib only
  out/                       # evidence.json, proposals.json, verdict.json, ledger.jsonl
  .env.example
```

---

## 3. The bridge, exactly

Both agents must return this JSON (strict prompt, one repair retry):

```json
{"cause": "OOM_MEMORY_LIMIT", "target": "oom-job", "action": "RESTART_WITH_HIGHER_MEMORY_LIMIT",
 "params": {"memory_limit": "1g"}, "confidence": 0.82, "diagnosis_text": "free text, shown not compared"}
```

Four compared fields, because `diagnosis` as free text never matches and you would
flag every incident:

| Field | Compared how |
|---|---|
| `cause` | enum from a fixed list of 3 — exact match |
| `target` | container name, lowercased — exact match |
| `action` | enum — exact match |
| `params.memory_limit` | normalized to bytes (`1g` = `1024m` = `1073741824`) — exact match |

Then the permission check (separate from agreement):

- `action` is in the allowlist of exactly one action: `RESTART_WITH_HIGHER_MEMORY_LIMIT`
- `target` is the container that actually failed
- new limit > old limit and ≤ 1 GiB

Verdicts: `AGREE` (both fields equal + permitted) → execute.
`DISAGREE` (any field differs) → war room. `INSUFFICIENT` (unparseable, missing
field, or `confidence < 0.6`) → war room. `DENIED` (agree but not permitted) → war
room. Three of four outcomes are "no execution," which is the point.

Lying about the diagnosis is easy for a small model; the enum plus the exact-parameter
equality is what makes agreement meaningful.

---

## 4. What's left to install: a gateway and a provider row

NudgeBee itself is done. Two gaps remain: its AI gateway is not a compose service, and
no LLM provider is registered yet (`public.integrations` is empty past migrations).

### JarvisLabs / Gemma — config, no code (~10 min)

One deployment, two consumers. Confirm the served tag first, don't trust the URL:

```bash
curl -s $GEMMA_BASE_URL/v1/models | jq '.data[].id'
```

```bash
GEMMA_BASE_URL=https://<instance>.jarvislabs.ai   # or ssh -L 11434:localhost:11434
GEMMA_MODEL=<exact tag from the call above>
```

If the box has no public URL, the SSH tunnel is the reliable path (this is the same
seam the existing `nudgebee-gemma-triage` POC uses).

### NudgeBee — already installed on this machine

**Verified state (do not re-install):**

| | |
|---|---|
| Checkout | `/Users/sohamsunilp/dev/nudgebee-probe` |
| Compose project | `nudgebee-probe`, 20 containers up, `migrations` exited 0 |
| UI | `http://localhost:3000` → 200 |
| API | `http://localhost:8000` → 200 |
| llm-server | `http://localhost:8005/health` → 200 |
| Tenant | `346aa2cd-d511-4501-80ee-ae3c43a46885` ("admin's Org") |
| LLM integrations configured | **none** (`public.integrations` count = 0) |
| Gateway | **not running** — it is not a compose service |
| Toolchain present | Go 1.27.3, Python 3.11.16, Node 22 (Node version is fine; the app runs in a container) |

Compose here is the hyphenated binary (`/opt/homebrew/bin/docker-compose`, v5.6.1);
`docker compose` as a subcommand does not resolve on this machine. Use
`docker-compose ...` or the repo `Makefile`.

**Two things are missing: the gateway process, and a JarvisLabs provider.**
Everything else is done.

#### Step 1 — start NudgeBee's AI gateway (5 min)

The gateway is deliberately **not** in `docker-compose.yaml`; it runs from source.
Its `Makefile` target is `go run ./cmd/gateway`.

```bash
cd /Users/sohamsunilp/dev/nudgebee-probe/llm/gateway
cat > .env <<EOF
PORT=8010                                  # 8000 is api-server
GATEWAY_DB_URL=postgres://postgres:postgrespassword@localhost:5432/nudgebee?sslmode=disable
NUDGEBEE_ENCRYPTION_KEY=$(grep '^NUDGEBEE_ENCRYPTION_KEY=' ../../api-server/services/.env | cut -d= -f2)
CACHE_PROVIDER=inmemory
GATEWAY_AUTH_MODE=static
GATEWAY_STATIC_TOKEN=nb-demo-token
GATEWAY_STATIC_TENANT_ID=346aa2cd-d511-4501-80ee-ae3c43a46885
GATEWAY_STATIC_USER_ID=demo
GATEWAY_ALLOW_PRIVATE_ENDPOINTS=true        # required if Gemma is reached over a tunnel
EOF
make run
```

`GATEWAY_STATIC_TENANT_ID` must be the real tenant id above, not a placeholder —
the gateway resolves the provider **per tenant**, so a fake id finds no integration.

#### Step 2 — register JarvisLabs as an LLM provider (10 min, highest risk)

The gateway reads **no** `LLM_PROVIDER_*` block — that was removed on purpose (its
`config.go` says so). Custom OpenAI-compatible endpoints come from **per-tenant LLM
integrations**, stored encrypted with `NUDGEBEE_ENCRYPTION_KEY`. So JarvisLabs gets
registered the way any provider does:

1. Open `http://localhost:3000`, sign in (Admin Login: any email + `Test!24#5`).
2. **Admin → AI & Tools → Providers** → add an OpenAI-compatible provider:
   - Base URL: `$GEMMA_BASE_URL` (public JarvisLabs URL, or `http://localhost:11434`
     over an SSH tunnel — the latter needs `GATEWAY_ALLOW_PRIVATE_ENDPOINTS=true`)
   - API key: whatever the endpoint expects (often none)
   - Model: the exact tag from `curl $GEMMA_BASE_URL/v1/models`
3. Confirm the row landed:
   `docker exec nudgebee-probe-postgres-1 psql -U postgres -d nudgebee -tAc "select count(*) from public.integrations;"`

If the Providers screen does not accept it in time, that is the fallback trigger —
see "If step 2 fails" below. Do not burn more than ten minutes here.

#### Step 3 — one call through NudgeBee to Gemma (2 min)

```bash
curl -s localhost:8010/v1/chat/completions \
  -H 'Authorization: Bearer nb-demo-token' -H 'Content-Type: application/json' \
  -d '{"model":"<provider>/<model-tag>",
       "messages":[{"role":"user","content":"Reply with {\"ok\":true} and nothing else."}]}'
```

That request is the moment "NudgeBee is in the loop" becomes true. Everything after
it is pipeline code.

**If step 2 fails:** call the JarvisLabs OpenAI-compatible endpoint directly with the
same prompt, and label the proposal "NudgeBee prompt profile (gateway not wired)."
You keep the analysis, you lose the platform claim. Decide by minute 20.

**Honest claim afterwards:** the incident is analysed through NudgeBee's own AI
gateway, with its provider config, on your JarvisLabs model. NudgeBee's *collectors*
are not watching the OOM — the pipeline hands it the evidence. That is a fair
sentence; "NudgeBee detected the incident" is not.

---

## 4a. Multiple opinions without RubixKube

Removing RubixKube does not remove the second opinion; it relocates it inside
NudgeBee. Three options, ranked. The bridge code is identical for all three — only
the source of proposal B changes.

**A. Two NudgeBee agents, different models** (best, ~10 min if the screen behaves)
NudgeBee ships an agent configuration surface (Admin → AI & Tools → Agents). Create
two: `Diagnostician` and `Challenger`. Point them at two different models — Gemma on
JarvisLabs for one, any second model reachable through the same gateway for the
other. Different weights + different role prompt = two genuinely independent
proposals over the same evidence.
*Slide:* "two agents, two models, one evidence packet."

**B. Two models, one agent role** (same effort, less structure)
Both calls go through the gateway, addressed as `<providerA>/<model>` and
`<providerB>/<model>`. Only worth it if you already have a second model key.
*Slide:* "two models investigate in parallel."

**C. One model, two roles** (fallback, ~10 lines, zero dependencies)
Same Gemma, two system prompts: Diagnostician proposes; Challenger must diagnose
independently and is told to object. This is the version to ship if A and B both
eat time.
*Slide:* "two role-separated agents on one model." Do **not** call this "two agents"
without the qualifier — a judge will ask which models, and the honest answer is
"one, twice."

**Do not** manufacture the disagreement with `temperature` sampling. Two samples of
one model disagreeing is noise, not a second opinion, and it makes `DISAGREE`
meaningless the moment someone asks why the agents disagreed.

**What this costs the story:** the original two-vendor framing ("RubixKube and
NudgeBee independently investigate") becomes "two independent analyses inside
NudgeBee." The bridge, the single execution, the verification, and the trail are all
unchanged — and the two-vendor version remains the roadmap line, not the demo claim.

### Kepler — desktop app (~10 min, unchanged)

- Download from `trykepler.rubixkube.ai`; sign in (free, no RubixKube account).
- Default hosted model is fine — Kepler is the *approval surface*, not an analyst.
- Posture **Assist**; one war room per incident id with both proposals as members and
  the bridge verdict pinned by the lead.

Note the naming collision: Kepler is a RubixKube product, so RubixKube is still in
the demo — as the governance surface, not as one of the two analysts. Say it that way
and the removal is coherent.

---

## 5. Demo script (4 minutes, two scenarios only)

**Scenario A — agreement → one recovery → verified**
1. `./demo.sh` injects the OOM (show `docker inspect` → `ExitCode 137`, `OOMKilled true`).
2. Diagnostician and Challenger proposals land in parallel through NudgeBee; same
   `evidence_sha256` on both.
3. Bridge prints `AGREE` on the compared fields, allowlist passes, executes **once**.
4. Verification: new container `OOMKilled=false` + completion marker. `ledger.jsonl`
   shows exactly one execution row.
5. Kepler war room shows the card; approve in Assist.

**Scenario B — disagreement → human review**
6. `./demo.sh --conflict` makes the Challenger propose a different parameter.
7. Bridge prints `DISAGREE`, executes nothing, war room shows both explanations.
   Ledger records the no-op and why.

Two scenarios, one dial. Skip the deny path — same code, extra minutes.


---

## 6. What is real, what is a seam (say this before a judge asks)

| Claim | Reality |
|---|---|
| "NudgeBee analysed the incident" | True at the transport level: both calls go through NudgeBee's own AI gateway, resolved against its provider config, on your JarvisLabs model. NudgeBee's collectors are **not** watching the container — the pipeline hands it the evidence. Never say "NudgeBee detected it." |
| "Two independent agents investigated" | Depends on the option you got to. Two models = genuinely independent weights. One model, two roles = role separation only; say so. In both cases: one evidence hash, no cross-talk. |
| "Custom-model analysis from JarvisLabs" | True for both analysts now — same gateway, same model, your endpoint. This is the cleanest claim in the whole demo. |
| "Kepler decided" | Kepler's war room is where a human approves; the comparison is deterministic code. Frame it as governance, not intelligence. |
| "We executed once" | True — a lock file, not a distributed lock. Single-host demo, so that is sufficient and honest. |
| "Verified recovery" | Two signals: `OOMKilled=false` and the job's own completion marker. Real, cheap, defensible. |
| "Decision trail" | `ledger.jsonl`, append-only, every stage, with the evidence hash. |

---

## 7. Decisions taken as defaults (60-minute mode — override only if you disagree)

There is no time to wait on these, so the plan proceeds with:

1. **Plain Docker**, not a cluster. `docker run --memory=128m`. No Observer, no K8s agent.
2. **NudgeBee's gateway on :8010** with `GATEWAY_AUTH_MODE=static` and the real tenant id.
   JarvisLabs is registered as a provider integration; the model is addressed as
   `<provider>/<tag>`. If the provider screen fails by minute 20, direct JarvisLabs
   calls with the same prompt, labelled as such.
3. **Kepler approval is manual.** The pipeline prints the exact command, a human
   approves it in the war room, then the pipeline executes. No API integration.
4. **Second opinion = two NudgeBee role agents.** Two models if a second one is
   reachable, otherwise one Gemma with Diagnostician/Challenger prompts.


---

## 8. Where this plan came from

§1–§6 describe the full version: two vendors (NudgeBee + RubixKube), Kepler's Observer
connected, four fields compared. That is the version to show *as the intended system*
in one slide. What actually runs in 60 minutes is §0, and RubixKube is out of it.

Worth saying in the pitch: the full version is not more ambitious — it is the same
pipeline with one more vendor. The 60-minute version already contains the entire
contribution — two independent proposals, a deterministic agreement check, exactly one
recovery, a verification, and a trail.

---

## 9. Deliberately not building

No webhook server, no message queue, no database, no multi-incident correlation, no
unit-test suite, no plugin/hook points, no second failure type, no auto-rollback, no
prompt tuning loop. Any of these is a good follow-up and a bad use of the remaining
hours.
