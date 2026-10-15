# Voice requests to actions (B3b)

What happens between "open notepad" and the broker. Code: `reva_core/language/{rules,entities,router,outcomes}.py`.

1. **Refusals first.** Pay, transfer, buy, bank login, medical dosing or diagnosis, shell commands, deleting files and sending email are matched before anything else. They become a proposal under a forbidden capability name, so `authorize()` answers `FORBIDDEN_CAPABILITY` and the reply is a template ("I can't move money…"). No grant is ever made.
2. **Rules.** Plain regular expressions with positive and negative fixtures (`tests/unit/test_language_rules.py`): open/close an app, today, spending summary, remember, recall. A rule only builds a typed proposal.
3. **App names, in order:** exact (canonical name) → alias (`vs code`, `google chrome`) → lexical (`note pad`) → fuzzy (`spotfy`, standard-library `difflib`, no new dependency) → vector (shadow only: called so scores can be logged, never changes the answer) → ask.
   - Only exact and alias act. Lexical and fuzzy get "Did you mean Spotify?" and only a click-free spoken **yes to the name** proposes it (marked `confirmed`). That yes confirms a name, it is not an approval of the action.
   - Filler words (`the`, `please`, `app`, …) are ignored. Any other word left over ("open notepad tomorrow") is an unresolved term and the broker refuses it.
   - A name outside the allowed list ("photoshop") never reaches the broker.
4. **Broker.** T0 (read-only) is authorized, logged, then the assistant answers from data. T1 (open) is granted and REVA says "Asking your PC to open Notepad." (a request, not a result). T2 (close, remember, voice expense) waits for a click or tap on screen: "Close Spotify? Approve it on screen." A spoken "yes" never approves T2.
5. **Success words** ("Opened", "Saved", "Closed") only come from `verified` outcomes with executor evidence (`outcomes.py`); B3c's executor supplies it.

Not in this slice: assistant stop/repeat/undo (they are not capabilities in the registry), the spaCy matcher (regular expressions cover the fixtures; revisit if a rule needs grammar), the real vector scorer.
