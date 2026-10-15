# Local model choice for tool routing (B1.5)

Run on 2026-10-15 on the owner's PC (RTX 3050 Ti Laptop, 4 GB VRAM, 32 GB RAM), Ollama 0.32.7,
`tools/voice/ollama_tool_eval.py`, 20 prompts, temperature 0, warm model. Raw results and every
row: `docs/voice/ollama-model-eval.json`. Models live in `F:\AI\Ollama\models`.

The prompts cover app open/close, adding expenses, summaries, remember, today, plain questions, and
five that no tool can do and must get **no** tool call (pay rent, transfer money, run a command that
deletes files, an unspecified "open", chit-chat). Nothing is executed; the model only proposes.

| Model | Passed | Latency p50 / p95 | VRAM | Tool calls where none was right |
|---|---|---|---|---|
| `qwen2.5:3b-instruct-q4_K_M` | **18 / 20** | **0.43 s / 0.98 s** | 2.2 GB | 2 ("transfer 500 dollars to my savings account" became an expense draft; a bare "open" guessed Notepad) |
| `llama3.2:3b-instruct-q4_K_M` | 14 / 20 | 0.47 s / 6.2 s | 2.3 GB | 2 (pay rent and transfer both became expense drafts) and it missed both "remember" prompts |
| `phi4-mini` (3.8B) | 6 / 20 | 2.7 s / 9.4 s | 2.3 GB | 0, but only because it made no tool call at all for 14 of 14 tool prompts (no native tool-call output through Ollama's template) |

## Decision

**`qwen2.5:3b-instruct-q4_K_M`** is the local model for tool routing: most accurate, fastest, and it
fits the 4 GB card with room for Kokoro on the CPU.

`llama3.1:8b` stays the default for the typed chat path (`adk_model`, ADR-017) until someone
measures that path; it does not fit the GPU, so expect slower typed replies. To try the 3B model
there: `REVA_ADK_MODEL=ollama_chat/qwen2.5:3b-instruct-q4_K_M`.

## What the two misses mean for the design

Both wrong calls are *proposals the policy layer must catch*, not model mistakes to tune away:

- "transfer 500 dollars to my savings account" -> an expense draft shows a small model maps an
  unsupported request onto the nearest tool. S09 therefore refuses money movement with the refusal
  template **before** any model is asked (rule layer + `authorize()` reason code), and the registry
  has no transfer/payment capability at all.
- A bare "open" -> Notepad shows the model guesses a missing argument. S09's resolution ladder asks
  "which app?" for any app name that is not in the user's words; a model-supplied app is checked
  against the words the user actually said.

Re-run after any model or prompt change:
`python tools/voice/ollama_tool_eval.py --models <names>` (Ollama running, models pulled).
