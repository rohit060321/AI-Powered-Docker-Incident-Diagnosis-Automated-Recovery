# OOM incident → two agents → agreement bridge → one recovery

Working end to end on this machine.

```
docker job OOMKilled (128m)
      │
      ▼
 evidence.json ──┬─► Diagnostician ─► 640m ─┐
                 │  (NudgeBee gateway →      ├─► bridge.py ─► AGREE → execute once → verify
                 │   Gemma on JarvisLabs)    │
                 └─► Challenger ────► 640m ─┘
```

Last verified run:

```
1. evidence   oom-job: exit=137 oom_killed=True limit=128m
2. agents     evidence cf4c17c45327e17d sent to both
              diagnostician: OOM_MEMORY_LIMIT / RESTART_WITH_HIGHER_MEMORY_LIMIT / 640m
              challenger:    OOM_MEMORY_LIMIT / RESTART_WITH_HIGHER_MEMORY_LIMIT / 640m
3. bridge     AGREE: both propose 640m; permitted
4. execute    executed once with --memory=640m
5. verify     recovered=True oom_killed=False exit_code=0 signal=WORK_COMPLETE
```

## Run it

The gateway must be up first (it is not a compose service):

```bash
cd ~/dev/nudgebee-probe/llm/gateway && make run     # listens on :8010
```

Then:

```bash
cd ~/dev/mlh-thing
./demo.sh                 # agree → one recovery → verified
./demo.sh --conflict      # disagreement → human review, nothing executed
./demo.sh --proposals out/proposals.json   # replay (survives a dead model endpoint)
```

Artifacts land in `out/`: `evidence.json`, `proposals.json`, `verdict.json`,
`verification.json`, and `ledger.jsonl` (one line per stage, the decision trail).

## Files

| File | What |
|---|---|
| `pipeline.py` | The whole flow: evidence → two calls → bridge → execute → verify → ledger |
| `oom_job/oom.py` | The failing job; logs its own RSS and the requirement (`alloc=512MiB`) |
| `demo.sh` | Injects the OOM, then runs the pipeline |
| `proof.sh` | Four proofs on one screen: the kernel OOM, the recovered container, NudgeBee's metered requests, the decision trail |
| `card.py` | Renders the last run as Markdown for a Kepler war room |
| `.env` | Gateway URL/token, model id, job limits |

## The bridge

Compares three fields — `cause`, `action`, `params.memory_limit` (normalised to bytes,
so `1g` == `1024Mi`). Verdicts:

- **AGREE** → permitted → execute once → verify
- **DISAGREE** → any field differs → human review, nothing executed
- **DENIED** → they agree but the action is not permitted (not the allowlisted action,
  no raise over the failing limit, no 25% headroom over `required_memory_mb`, or over 4 GiB)
- **NO_DECISION** → an agent's answer did not parse

`DENIED` is the interesting one: **agreement alone does not authorise execution.**
Both agents agreeing on 256m was denied by the bridge, because the job asked for
512 MiB and 256m would have OOM'd again — the gate is not consensus.

## Two patches to NudgeBee (upstream gaps, in `~/dev/nudgebee-probe`)

Its OSS gateway can only take operator credentials for anthropic/openai/gemini/hf, and
the per-tenant LLM-integration path needs the enterprise credential resolver — so a
`custom` provider configured in the UI can never be resolved. Fix, ~15 lines total:

1. `config/config.go` — add `GATEWAY_VLLM_API_KEY` / `GATEWAY_VLLM_ENDPOINT`.
2. `cmd/gateway/main.go` — add the `vllm` lane to `providerCreds()`.
3. `engine/provider.go` — set `VLLMKeyConfig{URL}` on the key (bifrost rejects a vllm
   key without it: "vllm_key_config is required").

Two details that cost time and are worth saying out loud in the pitch:

- The vllm lane builds `{baseURL}/v1/chat/completions`, so the endpoint must be
  `https://models.jarvislabs.net` — **not** `.../v1`.
- `gemma-4-26b-a4b-it` is a reasoning model: without
  `chat_template_kwargs: {"enable_thinking": false}` it streams its whole thinking
  trace into `content` and truncates before the answer.

The JarvisLabs key in `llm/gateway/.env` was decrypted from NudgeBee's own
`integration_config_values` row with `NUDGEBEE_ENCRYPTION_KEY` — the UI integration is
real, it just can't be resolved without the patches above.

## Honest framing

- **NudgeBee is in the loop for real:** both analyses go through its AI gateway, its
  auth, its metering, to your JarvisLabs model.
- Its **collectors are not** watching the container — the pipeline hands it the
  evidence. Say "NudgeBee analysed the incident", not "NudgeBee detected it".
- **Kepler** is the approval surface, not a decision-maker. The verdict is
  deterministic code; that is the point.
- Still to do for the demo: open a Kepler war room and paste `out/verdict.json` plus
  both proposals for the disagree path.
