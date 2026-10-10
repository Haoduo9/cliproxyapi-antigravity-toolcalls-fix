# CPA `delta.tool_calls must be an array` — root cause & one-line byte patch

Reproducible analysis and fix for a bug in **CLIProxyAPI (CPA)** where its
**antigravity → OpenAI chat-completions** streaming translator emits
`"tool_calls":null` on every non-tool frame, breaking strict clients
(SillyTavern "Agent" mode, Hermes, and anything else that validates
`delta.tool_calls` as an array).

## Symptom

A strict OpenAI-compatible client aborts a streaming tool-enabled request with:

```
model.upstream_invalid_response: OpenAI Chat response delta.tool_calls must be an array
```

## Root cause

Not the client. Not configuration. It is hardcoded in CPA's upstream source:

`internal/translator/antigravity/openai/chat-completions/antigravity_openai_response.go`

```go
// line 98 — the streaming response template
template := []byte(`{"id":"","object":"chat.completion.chunk","created":12345,"model":"model",
  "choices":[{"index":0,"delta":{"role":null,"content":null,
  "reasoning_content":null,"tool_calls":null}, ...}]}`)
                                     ^^^^^^^^^^^^^^^^^^^^
```

The field is only turned into an array when a real `functionCall` arrives
(lines 178–196). Every other frame is emitted with a literal `null`, so the
client sees *a field that exists but is not an array*.

Observed frame sequence (captured from a real request):

```
frame 1  "tool_calls":null          <-- triggers the client error
frame 2  "tool_calls":[{...}]       ok
frame 3  "tool_calls":null          <-- again
```

## Fix — equal-length byte patch

Replace `,"tool_calls":null` (18 bytes) with 18 spaces:

```
{"role":null,"content":null,"reasoning_content":null                  },
                                                     ^^^^^^^^^^^^^^^^^^
```

- JSON stays valid, the key simply disappears, **file size is unchanged** —
  the patch can never desync ELF offsets.
- The string appears **3 times** in the binary: one streaming delta template
  (must patch) and two non-streaming `message` templates (must not).
  `scripts/cpa_patch_toolcalls.py` locates the right one by requiring the
  surrounding context to contain `"object":"chat.completion.chunk"`.

### Why this cannot break tool calls

The upstream branch is:

```go
if toolCallsResult.Exists() && toolCallsResult.IsArray() { ... } else {
    template, _ = sjson.SetRawBytes(template, "choices.0.delta.tool_calls", []byte(`[]`))
}
```

`gjson` returns `Exists() == false` for **both** `null` **and a missing key**,
so tool-bearing frames take the same `else` path and are regenerated
identically. Tool-call frames are byte-for-byte unchanged.

## Verified result

| Build | frames containing `"tool_calls":null` (plain text stream) | tool-call frame |
|---|---|---|
| unpatched | **3** (broken) | 1 (fine) |
| patched | **0** | **1 (still fine)** |

```
md5  020f8fae30877957e8fd240199505d24   (before)
md5  a49e003f6775cf2b1d1bfbefc3ec62e4   (after, size unchanged 69769832)
```

Upstream status: **still unfixed as of v8.0.23** (2026-10-09). The patch is
lost on every CPA upgrade and must be re-applied.

## Layout

```
scripts/
  cpa_patch_toolcalls.py   apply the byte patch to a binary (writes .patched)
  swap_prod_binary.sh      backup -> stop -> swap -> start, with md5 gates
  verify_prod_8317.py      post-swap acceptance test (frames + tool calls)
  probe_patched_cpa.py     run a patched copy on a probe port and diff frames
  mk_probe_cfg.py          derive a probe config by text substitution
upstream-reference/
  antigravity_openai_response.go.txt   upstream source snapshot (for the patch target)
```

## Usage

```bash
# 1. Produce a patched binary (defaults to ./cli-proxy-api in the CPA dir)
python3 scripts/cpa_patch_toolcalls.py

# 2. Swap it in (stops the service first — see pitfall)
bash scripts/swap_prod_binary.sh

# 3. Verify
python3 scripts/verify_prod_8317.py
```

If upstream renumbers lines, `cpa_patch_toolcalls.py` bails out on
`assert len(targets) == 1` instead of patching the wrong string. Re-check by
hand before continuing.

Rollback:

```bash
systemctl --user stop cli-proxy-api
cp -a <backup> <cpa-dir>/cli-proxy-api && chmod 755 <cpa-dir>/cli-proxy-api
systemctl --user start cli-proxy-api
```

## Pitfalls learned the hard way

- **`ETXTBSY` on swapping a running binary** — stop the service first.
- **A probe instance must reuse the same `oauth.auth-dir`**, and `/v1/models`
  must be **polled** (~6 s) because models register asynchronously. Fire a
  request too early and you get a misleading
  `unknown provider for model X` 400 — not a sign the patch broke anything.
- **Derive probe configs by text substitution**, never by
  re-serialising with `yaml.safe_dump` (it rewrites the config in ways CPA
  rejects).
- Scripts carry **no credentials**; the API key is read from `~/.hermes/.env`
  at runtime.

## Reproducing the frame capture

```bash
curl -sN http://127.0.0.1:8317/v1/chat/completions \
  -H "Authorization: Bearer $CPA_KEY" -H 'Content-Type: application/json' \
  -d '{"model":"<model>","stream":true,
       "messages":[{"role":"user","content":"call the weather tool"}],
       "tools":[{"type":"function","function":{"name":"get_weather",
         "description":"weather","parameters":{"type":"object",
         "properties":{"city":{"type":"string"}},"required":["city"]}}}]}' \
  | grep '^data:' | grep -c '"tool_calls":null'
```

`3` before the patch, `0` after.
