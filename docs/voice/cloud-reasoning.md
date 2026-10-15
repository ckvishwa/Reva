# Cloud reasoning (B1.7): opt-in, per-domain, with a local fallback

Off by default. Nothing leaves this PC until the owner stores a key and switches cloud on.

## What is sent, and when

| Sent when cloud is on | Never sent |
|---|---|
| What you say in a free-form question (the text after speech recognition) | Your voice or any audio |
| A short fixed instruction ("voice assistant, cannot act, answer in 1-3 sentences") | Your screen |
| Data from a domain **only if that domain's own switch is on** | Memory, Finance, Health, Personal data while their switches are off (they start off, as does every domain) |
| | Anything for commands REVA handles itself (adding an expense, opening an app) |

The hosted model replies with text only. It cannot propose or run an action here.

## Settings API (loopback, Bearer token)

| Call | Does |
|---|---|
| `GET /v1/settings/cloud` | `enabled`, per-domain switches, `key_configured` (true/false), `model`, `timeout_seconds`, and the disclosure text above |
| `PUT /v1/settings/cloud` | `{"enabled": bool?, "domains": {"coach": true}?}`. Switching on without a stored key is refused (409 `key_required`). Unknown domain: 422 |
| `PUT /v1/settings/cloud/key` | `{"api_key": "sk-ant-..."}` -> Windows Credential Manager (`reva.provider.anthropic`). Never returned, never logged, never echoed in an error |
| `DELETE /v1/settings/cloud/key` | Removes the key and switches cloud off |

Every change is an audit event (`cloud_settings_changed`, `cloud_key_stored`, `cloud_key_removed`); the key is never in one.

## Failure behaviour

Timeout (8 s default, `REVA_CLOUD_TIMEOUT_SECONDS`), no network, rejected key, rate limit, refusal or empty
answer: the turn is answered by the local model and the reply event carries a `notice` ("The cloud model was
too slow, so I answered with the local model."). The notice is shown, not spoken over the answer.
The model is `REVA_CLOUD_MODEL` (default `claude-opus-5-5`); for a quicker voice reply try `claude-sonnet-5-5`.

## NEEDS_HARDWARE: one real cloud turn

1. In the app: Voice on. In a terminal with the app's Core token (from `%REVA_DATA_DIR%\local_auth_token`):
   `curl -X PUT http://127.0.0.1:8756/v1/settings/cloud/key -H "Authorization: Bearer <token>" -d "{\"api_key\":\"<your key>\"}"`
   then `curl -X PUT .../v1/settings/cloud -d "{\"enabled\":true}"` (same header).
2. Hold Ctrl+Space and ask "What is the capital of Australia?". Expect a spoken answer and
   `provider: "cloud"` in the `assistant.text.final` event (or the log line `turns-*.jsonl` route `chat`).
3. Disconnect the network and ask again: the answer must come from the local model with the notice.
4. `DELETE .../v1/settings/cloud/key`: cloud is off again.
Tell me what you saw; I will flip `B1-cloud-real-turn` to PASS.
