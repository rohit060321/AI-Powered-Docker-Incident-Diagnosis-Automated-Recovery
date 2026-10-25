# NudgeBee gateway patches (local, against nudgebee@edge)

`~/dev/nudgebee-probe` is not a git checkout, so the three edited files are
preserved here verbatim. They add a `vllm` (self-hosted / OpenAI-compatible)
operator lane so NudgeBee's AI gateway can talk to JarvisLabs.

- `config.go`      — `GATEWAY_VLLM_API_KEY`, `GATEWAY_VLLM_ENDPOINT`
- `main.go`        — `providerCreds()` gains the vllm lane
- `provider.go`    — sets `VLLMKeyConfig{URL}` (bifrost rejects a vllm key without it)
- `docker-compose.override.yaml` — points the app's AI Gateway tab at the host gateway

Deploy: copy back over the matching paths, then `go build ./cmd/gateway` and rerun.
Never commit `llm/gateway/.env` — it holds the decrypted provider key.
