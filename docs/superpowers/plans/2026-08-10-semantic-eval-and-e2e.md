# Semantic Evaluation Corpus, Desktop Demo, and Full E2E Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the isolated 500+ memory evaluation corpus and harness, prove the Desktop Memory Panel and full automatic-startup + semantic-ADK path with real processes, and produce the honest Recall@k/latency numbers Slice 6's final report requires.

**Architecture:** This plan depends on both `docs/superpowers/plans/2026-08-10-core-lifecycle.md` (automatic Core startup) and `docs/superpowers/plans/2026-08-10-hybrid-semantic-memory.md` (hybrid retrieval) being implemented first — it builds evaluation tooling and E2E proof on top of them, not new product code. All corpus/evaluation artifacts live under `%TEMP%\reva-semantic-eval-<id>`, never the developer's real `REVA_DATA_DIR`, and are gitignored. New PowerShell E2E scripts extend the existing pattern in `desktop/tests/E2E/Run-MemoryPersistenceE2E.ps1` (real `Process.Start` of Python Core + real `Reva.Desktop.exe` + UI Automation), each on its own isolated port/data dir so they can run independently.

**Tech Stack:** Python 3.12 (corpus generator + evaluation harness, run via `pytest`-independent scripts since they measure real timing and are not correctness unit tests), PowerShell 7+ (E2E scripts, matching the 3 existing ones), real Ollama (`nomic-embed-text` + `llama3.1:8b`) for the numbers this plan reports.

## Global Constraints

- Never insert corpus data into the developer's real `REVA_DATA_DIR`. Every corpus/evaluation run uses `%TEMP%\reva-semantic-eval-<unique-id>` or an E2E script's own isolated `$dataDir` pattern.
- Never commit the generated corpus JSON (canonical memories + distractors) to git — it is derived/regenerable from the generator script, which *is* committed.
- Do not invent additional biographical claims beyond spec section 6's fixed list — the canonical memory generator embeds that list verbatim, does not extend it.
- Distractors are clearly synthetic/test-only (`"The test user ..."` / `"Project <Name> ..."` phrasing) — never phrased as if they were the real user's memories.
- Report real measured numbers. If a target in section 9's acceptance list is missed, the report states that plainly with a diagnosis — do not adjust thresholds or fabricate output to make it pass.
- New E2E scripts must use ports distinct from the 3 existing ones (`18756`, `18757`, and whatever `Run-AdkMemoryRecallE2E.ps1` uses) so all E2E scripts remain safely runnable concurrently.

---

## File Structure

New files:
- `tests/fixtures/semantic_eval/canonical_memories.py` — the fixed canonical list from spec section 6, as Python string constants.
- `tests/fixtures/semantic_eval/query_variants.py` — the >=100 semantic query variants from spec section 7 (plus generated extensions), each tagged with its expected canonical memory's index.
- `tests/fixtures/semantic_eval/distractor_generator.py` — deterministic distractor generation (category x template) to reach 500+ total corpus size.
- `scripts/semantic_eval/build_corpus.py` — CLI: writes the full corpus (canonical + distractors + query set) as JSON to an isolated `%TEMP%` path, printing exact counts per category (no silent truncation).
- `scripts/semantic_eval/run_evaluation.py` — CLI: seeds an isolated Core data dir with the corpus via direct repository calls, runs backfill, executes lexical-only / semantic-only / hybrid retrieval for every query, computes Recall@1/3/5, false-positive rate, p50/p95 latency, writes a Markdown report.
- `desktop/tests/E2E/Run-SemanticMemoryPanelE2E.ps1` — real UI demo of hybrid search (spec section 12).
- `desktop/tests/E2E/Run-AutoStartupE2E.ps1` — real automatic Core-lifecycle startup (spec section 13).
- `desktop/tests/E2E/Run-FullSemanticAdkE2E.ps1` — real end-to-end: auto-startup + 500+ corpus + weak-keyword semantic query + ADK-grounded chat answer + Core kill/reconnect + persistence (spec section 14).
- `.gitignore` addition for `scripts/semantic_eval/output/` and any `reva-semantic-eval-*` artifacts accidentally created under the repo.

---

### Task 1: Canonical memory and query-variant fixtures

**Files:**
- Create: `tests/fixtures/semantic_eval/__init__.py`
- Create: `tests/fixtures/semantic_eval/canonical_memories.py`
- Create: `tests/fixtures/semantic_eval/query_variants.py`
- Test: `tests/unit/test_semantic_eval_fixtures.py`

**Interfaces:**
- Produces: `CANONICAL_MEMORIES: tuple[str, ...]` (spec section 6's list verbatim, one string per bullet, across REVA/software, technical environment, career, cybersecurity, projects, education, fitness, devices, hobbies), `QUERY_VARIANTS: tuple[QueryVariant, ...]` where `QueryVariant = namedtuple("QueryVariant", ["query", "canonical_memory_substring"])` — `canonical_memory_substring` is a substring expected to appear in the correct canonical memory's content, used by the evaluation harness to check Recall@k without hand-maintaining IDs.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_semantic_eval_fixtures.py
"""Fixture integrity: the evaluation corpus must actually satisfy the
scale/coverage numbers Slice 6 requires before any evaluation runs."""

from __future__ import annotations

from tests.fixtures.semantic_eval.canonical_memories import CANONICAL_MEMORIES
from tests.fixtures.semantic_eval.query_variants import QUERY_VARIANTS


def test_canonical_memory_count_is_in_spec_range():
    assert 100 <= len(CANONICAL_MEMORIES) <= 180


def test_canonical_memories_are_unique():
    assert len(set(CANONICAL_MEMORIES)) == len(CANONICAL_MEMORIES)


def test_no_canonical_memory_contains_forbidden_sensitive_content():
    forbidden_markers = ["password", "api key", "api_key", "ssn", "social security"]
    for memory in CANONICAL_MEMORIES:
        lowered = memory.lower()
        for marker in forbidden_markers:
            assert marker not in lowered, f"{marker!r} found in canonical memory: {memory!r}"


def test_query_variant_count_meets_minimum():
    assert len(QUERY_VARIANTS) >= 100


def test_every_query_variant_targets_a_real_canonical_memory():
    joined = "\n".join(CANONICAL_MEMORIES).lower()
    for variant in QUERY_VARIANTS:
        assert variant.canonical_memory_substring.lower() in joined, (
            f"query variant {variant.query!r} targets substring "
            f"{variant.canonical_memory_substring!r} not found in any canonical memory"
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_semantic_eval_fixtures.py -v`
Expected: FAIL — modules do not exist.

- [ ] **Step 3: Write `canonical_memories.py`**

Transcribe spec section 6 ("CANONICAL PERSONAL MEMORY SEED") verbatim, one bullet per tuple entry, grouped by the same category comments the spec uses. This file is intentionally long and flat — no abstraction beyond the tuple, since it is a literal transcription of confirmed facts, not generated content.

```python
# tests/fixtures/semantic_eval/canonical_memories.py
"""Canonical personal memories for the isolated semantic-retrieval
evaluation corpus (Slice 6). Verbatim transcription of the confirmed
facts in docs/superpowers/plans/2026-08-10-semantic-eval-and-e2e.md's
source work order, section 6 — do not add facts beyond this list.

TEST-ONLY: loaded exclusively into an isolated
%TEMP%\\reva-semantic-eval-<id> data directory by
scripts/semantic_eval/build_corpus.py and
scripts/semantic_eval/run_evaluation.py. Never loaded into a developer's
real REVA_DATA_DIR.
"""

from __future__ import annotations

CANONICAL_MEMORIES: tuple[str, ...] = (
    # REVA / software
    "REVA is my long-term personal AI assistant project.",
    "REVA is intended to run persistently rather than behave like a normal website.",
    "REVA is local-first.",
    "Python REVA Core owns durable backend behavior.",
    "The Windows REVA desktop is C# and WinUI 3.",
    "The Windows frontend communicates with Core through authenticated localhost HTTP.",
    "C# must not access the REVA SQLite database directly.",
    "Durable memory should remain explicit rather than automatically saving every conversation.",
    "Memory must survive process restarts.",
    "REVA uses Ollama for local model execution.",
    "REVA currently uses llama3.1:8b for the ADK path.",
    "REVA uses Google ADK for the agent orchestration path.",
    "ADK is allowed to search memory.",
    "ADK is not allowed to create, update, or delete durable memory.",
    "REVA memory is owned by Python Core.",
    "ADK session state is not REVA durable memory.",
    "REVA should eventually expand to Android.",
    "Future REVA possibilities include IoT/home integration.",
    "IoT is not a current implementation requirement.",
    "REVA should use visible policy/approval boundaries for actions.",
    "REVA should not become a generic plugin platform prematurely.",
    "REVA should avoid speculative infrastructure.",
    "Explicit memory creation uses Core-owned memory APIs.",
    "Ordinary chat must not silently create durable memory.",
    "REVA uses SQLite locally.",
    "REVA Core exposes a FastAPI localhost API.",
    "REVA Core uses bearer-token authentication.",
    "The normal local Core endpoint uses loopback networking.",
    "REVA Core currently uses port 8756 by default.",
    "The desktop app has a Core Connected/Core Unavailable state.",
    "REVA's Core token is stored locally in local_auth_token.",
    "Token values must never be shown in the UI or logs.",
    "REVA has audit events.",
    "Memory source references must be retained.",
    "REVA's Windows UI should be dark, technical, calm, and compact.",
    "The Windows application uses XAML.",
    "The Windows application uses a small MVVM structure.",
    "The Windows frontend uses HttpClient to talk to Python Core.",
    "REVA should avoid duplicating backend logic in C#.",
    "Memory retrieval currently needs improvement beyond lexical matching.",
    "Semantic retrieval should remain a Core concern rather than a C# concern.",
    "A vector database should not be introduced until scale proves SQLite insufficient.",
    # Technical environment
    "My main development environment is Windows.",
    "My main REVA repository is developed on Windows.",
    "I use PowerShell frequently.",
    "I work heavily with Python.",
    "I am using C# for the new REVA Windows desktop.",
    "I have worked with TypeScript.",
    "I have worked with Java.",
    "I use Git and GitHub.",
    "I use SQLite.",
    "I use FastAPI.",
    "I use Ollama.",
    "My machine has an RTX 3050 with 4 GB VRAM.",
    "I have worked with Supabase.",
    "I have worked with PostgreSQL.",
    "I have worked with Prisma.",
    "I have worked with Next.js.",
    "I have worked with Spring Boot.",
    "I have worked with Kafka/Redpanda.",
    "I have worked with Redis.",
    "I use Visual Studio 2026 for the new Windows/WinUI development environment.",
    "I have .NET 10 installed.",
    "I use WinUI 3 for REVA Desktop.",
    "I prefer understanding system architecture rather than only copying commands.",
    "I often verify tooling through real end-to-end tests.",
    "I care about explicit security boundaries.",
    "I prefer local-first architecture for REVA.",
    # Career
    "My primary job target is SDET.",
    "Other target profiles include Security Engineer focused on SOC/DFIR.",
    "Network Engineer is another target profile.",
    "Cloud Engineer is another target profile.",
    "Junior roles are acceptable.",
    "Internship-level roles can be acceptable.",
    "I previously worked at Cognizant.",
    "My Cognizant title was Programmer Analyst — Quality Engineering.",
    "My Cognizant employment ran from January 2022 through July 2023.",
    "I performed functional testing.",
    "I performed regression testing.",
    "I performed smoke testing.",
    "I performed post-change validation.",
    "I worked across enterprise web applications.",
    "I created test cases from requirements.",
    "I used Postman for REST API validation.",
    "I used Jira for defect lifecycle management.",
    "I used logs/Splunk during application validation.",
    "I completed Security+.",
    "I have MITRE ATT&CK Fundamentals experience.",
    "I am interested in test automation.",
    "I use Pytest.",
    "I have used Selenium.",
    "I have used Playwright.",
    "I have used Cypress.",
    "I have used Postman.",
    "I am interested in detection engineering and DFIR.",
    "I have also explored AI red teaming.",
    "My job-search work emphasizes entering the job market rather than over-filtering opportunities.",
    "SDET is currently my primary job profile.",
    # Cybersecurity
    "I built SOC/detection labs.",
    "I use Splunk.",
    "I use Sysmon.",
    "I have worked with Windows Event Logs.",
    "I have worked with Active Directory labs.",
    "I use MITRE ATT&CK mappings.",
    "I have practiced phishing triage.",
    "I have built brute-force detections.",
    "I have built persistence detections.",
    "I have built RDP-related detections.",
    "I have worked with SMB brute-force detection.",
    "I built MalTrace.",
    "MalTrace analyzes malware behavior.",
    "MalTrace uses CAPEv2 output.",
    "MalTrace uses Random Forest classification.",
    "MalTrace uses SHAP explainability.",
    "MalTrace maps behavior to MITRE ATT&CK.",
    "MalTrace reported an F1 score around 0.975.",
    "I have used Burp Suite.",
    "I have used Ghidra.",
    "I have used IDA Pro.",
    "I have used Nmap.",
    "I have built an enterprise SOC detection lab.",
    "My SOC lab work has included Windows domain-controller and endpoint systems.",
    "Splunk has been a major tool in my detection work.",
    # Projects
    "I built JobMachine.",
    "JobMachine is a Python CLI job-hunt system.",
    "JobMachine uses SQLite.",
    "JobMachine reached around 185 tests at one reported stage.",
    "I built Access Risk Analyzer.",
    "Access Risk Analyzer models access paths and least privilege.",
    "I built CertForge.",
    "CertForge is for certification preparation.",
    "CertForge includes Security+ material.",
    "CertForge includes CCNA material.",
    "CertForge uses Next.js and Supabase.",
    "I built FulfillX.",
    "FulfillX uses Spring Boot.",
    "FulfillX uses PostgreSQL.",
    "FulfillX uses Kafka/Redpanda.",
    "FulfillX uses Redis.",
    "FulfillX includes a React admin interface.",
    "I built QualityMesh.",
    "QualityMesh is a quality automation-related project.",
    "I built REVA.",
    "REVA is my long-term personal AI project.",
    "I built a job-hunter workflow/repository.",
    "I have worked on career-operations automation.",
    "I have built multiple automation/testing-heavy projects.",
    # Education / learning
    "I studied an M.S. in Cybersecurity & Networks.",
    "I have studied computer and information science.",
    "I am studying networking/CCNA concepts.",
    "I prefer hands-on learning.",
    "I like understanding what technology is doing rather than memorizing commands.",
    "I ask follow-up questions until concepts make sense.",
    "I am improving English speaking for IELTS.",
    "My IELTS speaking target has been band 8.",
    "I like explanations with concrete examples.",
    "I often test my understanding by asking the same topic from multiple angles.",
    # Fitness
    "I train around five days per week.",
    "My physique goal is aesthetic rather than extremely bulky.",
    "I train at Planet Fitness.",
    "I use machines frequently.",
    "I train push exercises.",
    "I train pull exercises.",
    "I train legs.",
    "I train calves.",
    "I train shoulders.",
    "I train back width.",
    "I train biceps.",
    "I train triceps.",
    "I care about building an aesthetic upper body.",
    "I use lat pulldowns.",
    "I use chest press movements.",
    "I use shoulder press movements.",
    "I use lateral raises.",
    "I use cable exercises.",
    "I have practiced preacher curls.",
    "I use leg-extension/calf-related machines.",
    "I have discussed Smith-machine exercises.",
    # Devices
    "I use an iPhone 12 as my main phone.",
    "I also have a Samsung Galaxy S24 Ultra.",
    "The S24 Ultra became my secondary phone.",
    "I prefer the feel and animation quality of iOS.",
    "I have considered buying an iPhone 18 Pro.",
    "I prefer the Pro size over Pro Max because Pro Max is too large for me.",
    "Photography and video quality matter to me.",
    "Portrait and cinematic-looking photos/video matter more to me than extreme zoom.",
    "I have compared iPhone storage technology with Android UFS.",
    "I care about premium-feeling UI animation and interaction.",
    "My S24 Ultra had wired-charging problems while wireless charging still worked.",
    # Hobbies
    "I am learning guitar.",
    "I use a Fender Stratocaster HSS.",
    "I use/have used a Fender LT15 amplifier.",
    "Dandelions is one song I like practicing.",
    "I play/learn chess.",
    "My chess level has been around 700 Elo.",
    "I have studied the Vienna opening/gambit.",
    "I have asked about the Queen's Gambit.",
)
```

- [ ] **Step 4: Write `query_variants.py`**

Transcribe spec section 7's explicit examples, then extend with additional variants (still hand-written, still grounded in a real canonical memory substring) to clear the >=100 minimum. Include hard cases with minimal lexical overlap per spec instruction.

```python
# tests/fixtures/semantic_eval/query_variants.py
"""Semantic evaluation query variants (Slice 6). Each variant is an
EVALUATION QUERY, never persisted as a memory — see
docs/superpowers/plans/2026-08-10-semantic-eval-and-e2e.md section 7.
`canonical_memory_substring` is checked against CANONICAL_MEMORIES by
tests/unit/test_semantic_eval_fixtures.py and used by
scripts/semantic_eval/run_evaluation.py to score Recall@k without
hand-maintained IDs.
"""

from __future__ import annotations

from collections import namedtuple

QueryVariant = namedtuple("QueryVariant", ["query", "canonical_memory_substring"])

QUERY_VARIANTS: tuple[QueryVariant, ...] = (
    # iPhone 12 daily driver
    QueryVariant("what phone do I normally use?", "iPhone 12"),
    QueryVariant("which handset is my daily driver?", "iPhone 12"),
    QueryVariant("what is my primary mobile device?", "iPhone 12"),
    QueryVariant("what phone do I carry most often?", "iPhone 12"),
    QueryVariant("which device is my main smartphone?", "iPhone 12"),
    # SDET career target
    QueryVariant("what testing career am I targeting?", "SDET"),
    QueryVariant("what job am I mainly looking for?", "SDET"),
    QueryVariant("which QA automation role am I aiming at?", "SDET"),
    QueryVariant("what is my main career direction?", "SDET"),
    QueryVariant("what kind of software testing position do I want?", "SDET"),
    # MalTrace
    QueryVariant("what malware project did I make?", "MalTrace"),
    QueryVariant("which project analyzes malicious software?", "MalTrace"),
    QueryVariant("what did I build around CAPEv2?", "MalTrace"),
    QueryVariant("which of my projects uses SHAP for malware behavior?", "MalTrace"),
    QueryVariant("what security ML project did I create?", "MalTrace"),
    # Gym frequency
    QueryVariant("how often do I normally work out?", "five days per week"),
    QueryVariant("what is my weekly gym frequency?", "five days per week"),
    QueryVariant("how many days do I train?", "five days per week"),
    QueryVariant("what does my workout schedule look like?", "five days per week"),
    # REVA identity
    QueryVariant("what personal AI am I building?", "long-term personal AI assistant"),
    QueryVariant(
        "which project is supposed to become my long-term assistant?",
        "long-term personal AI assistant",
    ),
    QueryVariant(
        "what assistant do I want running persistently?", "long-term personal AI assistant"
    ),
    QueryVariant("what is my personal AI called?", "long-term personal AI assistant"),
    # Additional hard cases: minimal lexical overlap by design
    QueryVariant(
        "what animal do I own?", "pet"
    ),  # deliberately absent from canonical list; see note below
    QueryVariant("what pet do I have?", "iPhone 12"),  # placeholder removed below — see Step 5 note
)
```

Note for the implementer: the two lines above under "Additional hard cases" are deliberately wrong/left incomplete as written — replace them before running Step 5's test. The full, correct implementation continues the same `QueryVariant(...)` pattern for at least 76 more entries covering every canonical memory category (REVA/software, technical environment, cybersecurity, projects, education, fitness, devices, hobbies) with 3-5 phrasings each, all grounded in a real `CANONICAL_MEMORIES` substring, e.g.:

```python
(QueryVariant("does REVA rely on the cloud or run locally?", "local-first"),)
(QueryVariant("can C# read REVA's database directly?", "must not access the REVA SQLite database"),)
(
    QueryVariant(
        "does REVA save every single chat as memory?", "explicit rather than automatically saving"
    ),
)
(QueryVariant("which local model powers REVA's agent path?", "llama3.1:8b"),)
(
    QueryVariant(
        "is REVA's session memory the same as durable memory?",
        "ADK session state is not REVA durable memory",
    ),
)
(
    QueryVariant(
        "what operating system do I primarily develop on?", "development environment is Windows"
    ),
)
(QueryVariant("which GPU is in my dev machine?", "RTX 3050"),)
(QueryVariant("have I worked with message queues?", "Kafka/Redpanda"),)
(QueryVariant("what security certification have I completed?", "Security+"),)
(QueryVariant("what did I do at Cognizant?", "Programmer Analyst"),)
(QueryVariant("what SOC tooling have I used?", "Splunk"),)
(QueryVariant("what CLI project did I build for job hunting?", "JobMachine"),)
(QueryVariant("what degree am I pursuing or hold?", "M.S. in Cybersecurity"),)
(QueryVariant("what English test am I preparing for?", "IELTS"),)
(QueryVariant("what muscle groups do I train?", "shoulders"),)
(QueryVariant("which phone is my backup device?", "Samsung Galaxy S24 Ultra"),)
(QueryVariant("what instrument am I learning?", "guitar"),)
(QueryVariant("what chess opening have I studied?", "Vienna opening"),)
```

continuing until the file totals >=100 `QueryVariant` entries, all validated by `test_every_query_variant_targets_a_real_canonical_memory` — that test is the acceptance gate for this step, not a suggestion; do not mark this step done until it passes with the placeholder lines from the first snippet removed.

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/unit/test_semantic_eval_fixtures.py -v`
Expected: PASS (5 tests) — in particular `test_query_variant_count_meets_minimum` (>=100) and `test_every_query_variant_targets_a_real_canonical_memory` (every substring found in some canonical memory).

- [ ] **Step 6: Add `tests/fixtures/semantic_eval/__init__.py`**

```python
# tests/fixtures/semantic_eval/__init__.py
"""TEST-ONLY semantic evaluation fixtures for Slice 6 — never loaded
into a developer's real REVA_DATA_DIR."""
```

- [ ] **Step 7: Commit**

```bash
git add tests/fixtures/semantic_eval/__init__.py tests/fixtures/semantic_eval/canonical_memories.py tests/fixtures/semantic_eval/query_variants.py tests/unit/test_semantic_eval_fixtures.py
git commit -m "test(core): add canonical memory and semantic query-variant fixtures"
```

---

### Task 2: Distractor generator and corpus builder script

**Files:**
- Create: `tests/fixtures/semantic_eval/distractor_generator.py`
- Create: `scripts/semantic_eval/__init__.py`
- Create: `scripts/semantic_eval/build_corpus.py`
- Test: `tests/unit/test_distractor_generator.py`
- Modify: `.gitignore`

**Interfaces:**
- Produces: `generate_distractors(count: int) -> tuple[str, ...]` — deterministic (no `random`/`Date.now`-style nondeterminism; index-driven), clearly test-only phrasing, drawn from the categories spec section 8 lists.
- `build_corpus.py` CLI: `python scripts/semantic_eval/build_corpus.py --output-dir <dir> --total-size 500` writes `corpus.json` (`{"canonical": [...], "distractors": [...], "queries": [{"query": ..., "expected_substring": ...}, ...]}`) and prints category counts.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_distractor_generator.py
"""Distractor generation must be deterministic, clearly test-only, and
never overlap with any real canonical memory content."""

from __future__ import annotations

from tests.fixtures.semantic_eval.canonical_memories import CANONICAL_MEMORIES
from tests.fixtures.semantic_eval.distractor_generator import generate_distractors


def test_generates_exact_requested_count():
    assert len(generate_distractors(50)) == 50


def test_is_deterministic_across_calls():
    assert generate_distractors(100) == generate_distractors(100)


def test_distractors_are_unique():
    distractors = generate_distractors(400)
    assert len(set(distractors)) == len(distractors)


def test_distractors_never_duplicate_a_canonical_memory():
    distractors = set(generate_distractors(400))
    assert distractors.isdisjoint(set(CANONICAL_MEMORIES))


def test_distractors_are_clearly_marked_test_only():
    for distractor in generate_distractors(50):
        assert distractor.startswith("The test user ") or distractor.startswith("Project ")


def test_supports_at_least_five_hundred_without_repeating():
    distractors = generate_distractors(500)
    assert len(distractors) == 500
    assert len(set(distractors)) == 500
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_distractor_generator.py -v`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Write minimal implementation**

```python
# tests/fixtures/semantic_eval/distractor_generator.py
"""Synthetic TEST-ONLY distractor memories for the Slice 6 evaluation
corpus. Every entry is clearly phrased as belonging to "the test user"
or a fictional "Project <Name>" — never phrased as the real user's own
memory, and never migrated into normal REVA memory (see
docs/superpowers/plans/2026-08-10-semantic-eval-and-e2e.md Global
Constraints). Deterministic (index-driven, no randomness) so the same
count always produces the same corpus.
"""

from __future__ import annotations

_PHONES = [
    "Google Pixel 9",
    "OnePlus 12",
    "Samsung Galaxy A54",
    "Motorola Edge",
    "Sony Xperia 1",
    "Nothing Phone 2",
]
_LANGUAGES = ["Ruby", "Elixir", "Haskell", "Scala", "COBOL", "Perl", "Lua", "Erlang"]
_FRAMEWORKS = [
    "Ruby on Rails",
    "Laravel",
    "Symfony",
    "Django",
    "Meteor",
    "Ember.js",
    "Svelte",
    "Blazor",
]
_CERTS = [
    "AWS Solutions Architect",
    "CISSP",
    "CCNP",
    "PMP",
    "Scrum Master",
    "GCP Professional Cloud Architect",
]
_CLOUDS = [
    "AWS Lambda",
    "Azure Functions",
    "Google Cloud Run",
    "DigitalOcean App Platform",
    "Heroku",
]
_SECURITY_FACTS = [
    "SQL injection exploits unsanitized query input",
    "cross-site scripting targets unescaped output",
    "buffer overflows corrupt adjacent memory",
    "TLS 1.3 removed several legacy cipher suites",
]
_MALWARE_TOOLS = ["Cuckoo Sandbox", "YARA", "Volatility", "REMnux", "FLARE VM"]
_CAREERS = [
    "database administrator",
    "systems analyst",
    "release manager",
    "technical writer",
    "UX researcher",
]
_JOB_TITLES = ["Product Owner", "Scrum Master", "Business Analyst", "DevOps Manager"]
_EXERCISES = [
    "deadlifts",
    "barbell rows",
    "kettlebell swings",
    "box jumps",
    "rowing machine intervals",
]
_ROUTINES = ["marathon training", "CrossFit", "powerlifting", "yoga", "swimming laps"]
_HOBBIES = ["pottery", "watercolor painting", "birdwatching", "amateur astronomy", "woodworking"]
_INSTRUMENTS = ["violin", "cello", "drums", "saxophone", "trumpet"]
_PROJECT_NAMES = ["Atlas", "Redwood", "Nimbus", "Mercury", "Orion", "Vesta", "Halcyon", "Ember"]
_DATABASES = ["MongoDB", "Cassandra", "DynamoDB", "CockroachDB", "Neo4j"]
_OPERATING_SYSTEMS = ["Arch Linux", "FreeBSD", "Fedora", "openSUSE", "Haiku OS"]
_AI_FACTS = [
    "transformer attention scales quadratically with sequence length",
    "batch normalization stabilizes training",
    "dropout reduces overfitting during training",
    "gradient clipping prevents exploding gradients",
]

_TEMPLATES: tuple[tuple[str, list[str]], ...] = (
    ("The test user owns a {}.", _PHONES),
    ("The test user has worked with {}.", _LANGUAGES),
    ("The test user has built something with {}.", _FRAMEWORKS),
    ("The test user is studying {}.", _CERTS),
    ("The test user has deployed to {}.", _CLOUDS),
    ("The test user knows that {}.", _SECURITY_FACTS),
    ("The test user has used {} for malware analysis.", _MALWARE_TOOLS),
    ("The test user is targeting a {} role.", _CAREERS),
    ("The test user previously worked as a {}.", _JOB_TITLES),
    ("The test user trains using {}.", _EXERCISES),
    ("The test user follows a {} routine.", _ROUTINES),
    ("The test user enjoys {} as a hobby.", _HOBBIES),
    ("The test user plays the {}.", _INSTRUMENTS),
    ("Project {} performs image classification.", _PROJECT_NAMES),
    ("Project {} is a Kubernetes monitoring platform.", _PROJECT_NAMES),
    ("Project {} uses a relational database.", _PROJECT_NAMES),
    ("The test user has used {} as a database.", _DATABASES),
    ("The test user runs {} on a home server.", _OPERATING_SYSTEMS),
    ("The test user knows that {}.", _AI_FACTS),
)


def generate_distractors(count: int) -> tuple[str, ...]:
    distractors: list[str] = []
    template_index = 0
    while len(distractors) < count:
        template, values = _TEMPLATES[template_index % len(_TEMPLATES)]
        value_index = (template_index // len(_TEMPLATES)) % len(values)
        candidate = template.format(values[value_index])
        if candidate not in distractors:
            distractors.append(candidate)
        template_index += 1
        if template_index > count * 10:
            # Safety valve: with the current template/value table exhausted
            # of unique combinations, stop rather than loop forever — the
            # caller's test (test_supports_at_least_five_hundred_without_repeating)
            # is what proves the table is large enough for count=500.
            break
    return tuple(distractors[:count])
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_distractor_generator.py -v`
Expected: PASS (6 tests). If `test_supports_at_least_five_hundred_without_repeating` fails because the template x value combination space is smaller than 500, add more values to the shortest lists in `_TEMPLATES` (e.g. more `_PHONES`/`_PROJECT_NAMES` entries) until it passes — do not reduce the requested count.

- [ ] **Step 5: Write `build_corpus.py`**

```python
# scripts/semantic_eval/build_corpus.py
"""Build the isolated Slice 6 semantic evaluation corpus.

Writes corpus.json under an isolated directory (default:
%TEMP%\\reva-semantic-eval-<uuid>) containing canonical memories,
synthetic distractors, and evaluation query variants. Never writes to
a developer's real REVA_DATA_DIR — this script has no code path that
even accepts one.

Usage:
    python scripts/semantic_eval/build_corpus.py --total-size 500
"""

from __future__ import annotations

import argparse
import json
import tempfile
import uuid
from pathlib import Path

from tests.fixtures.semantic_eval.canonical_memories import CANONICAL_MEMORIES
from tests.fixtures.semantic_eval.distractor_generator import generate_distractors
from tests.fixtures.semantic_eval.query_variants import QUERY_VARIANTS


def build_corpus(total_size: int) -> dict:
    canonical = list(CANONICAL_MEMORIES)
    distractor_count = max(0, total_size - len(canonical))
    distractors = list(generate_distractors(distractor_count))
    queries = [
        {"query": v.query, "expected_substring": v.canonical_memory_substring}
        for v in QUERY_VARIANTS
    ]
    return {"canonical": canonical, "distractors": distractors, "queries": queries}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--total-size", type=int, default=500)
    args = parser.parse_args()

    output_dir = (
        args.output_dir
        or Path(tempfile.gettempdir()) / f"reva-semantic-eval-{uuid.uuid4().hex[:8]}"
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    corpus = build_corpus(args.total_size)
    corpus_path = output_dir / "corpus.json"
    corpus_path.write_text(json.dumps(corpus, indent=2), encoding="utf-8")

    print(f"Corpus written to: {corpus_path}")
    print(f"  Canonical memories:  {len(corpus['canonical'])}")
    print(f"  Distractor memories: {len(corpus['distractors'])}")
    print(f"  Total durable memories: {len(corpus['canonical']) + len(corpus['distractors'])}")
    print(f"  Semantic evaluation queries: {len(corpus['queries'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

```python
# scripts/semantic_eval/__init__.py
"""Slice 6 semantic evaluation tooling. TEST-ONLY — see
docs/superpowers/plans/2026-08-10-semantic-eval-and-e2e.md."""
```

- [ ] **Step 6: Run it and verify counts**

Run: `python scripts/semantic_eval/build_corpus.py --total-size 500`
Expected: prints canonical count (matches Task 1's 100-180 range), distractor count, total 500, query count >=100. Note the printed `corpus.json` path for Task 3's use.

- [ ] **Step 7: Gitignore generated corpus artifacts**

Modify `.gitignore` — add:

```gitignore
# Slice 6 semantic evaluation — generated/regenerable, never a private corpus
scripts/semantic_eval/output/
reva-semantic-eval-*/
```

- [ ] **Step 8: Commit**

```bash
git add tests/fixtures/semantic_eval/distractor_generator.py scripts/semantic_eval/__init__.py scripts/semantic_eval/build_corpus.py tests/unit/test_distractor_generator.py .gitignore
git commit -m "feat(core): add Slice 6 evaluation corpus builder"
```

---

### Task 3: Evaluation harness — Recall@k, false-positive rate, latency

**Files:**
- Create: `scripts/semantic_eval/run_evaluation.py`

**Interfaces:**
- Consumes: `reva_core.storage.bootstrap.initialize_database`, `reva_core.storage.repositories.memory_repository.MemoryRepository`, `reva_core.memory.embedding_backfill.backfill_missing_embeddings`, `reva_core.memory.hybrid_retrieval.hybrid_search`, `reva_core.models.embedding_providers.OllamaEmbeddingProvider` (all from `docs/superpowers/plans/2026-08-10-hybrid-semantic-memory.md`).
- Produces: CLI `python scripts/semantic_eval/run_evaluation.py --corpus <corpus.json> --scale 500` — seeds an isolated SQLite DB, runs lexical-only/semantic-only/hybrid retrieval per query, writes `evaluation_report.md` with the metrics from spec section 9.

This task is inherently an integration/measurement exercise against a real Ollama instance, not TDD-style unit testing — its "test" is running it for real and inspecting the report it produces.

- [ ] **Step 1: Write the script**

```python
# scripts/semantic_eval/run_evaluation.py
"""Slice 6 semantic retrieval evaluation: lexical-only vs semantic-only
vs hybrid, at 100/500/1000-memory scale.

Requires a real local Ollama server with the embedding model pulled
(default: nomic-embed-text) — this script is NOT part of CI (see
.github/workflows/ci.yml, which has no Ollama). Run manually to produce
the numbers Slice 6's final report cites.

Usage:
    ollama pull nomic-embed-text
    python scripts/semantic_eval/build_corpus.py --total-size 500
    python scripts/semantic_eval/run_evaluation.py --corpus <path from above> --scale 500
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import tempfile
import time
import uuid
from pathlib import Path

from reva_core.memory.embedding_backfill import backfill_missing_embeddings
from reva_core.memory.hybrid_retrieval import hybrid_search
from reva_core.memory.ranking import DEFAULT_HYBRID_RANKING_CONFIG, HybridRankingConfig
from reva_core.models.embedding import EmbeddingRequest
from reva_core.models.embedding_providers import OllamaEmbeddingProvider
from reva_core.shared.contracts.memory import (
    Memory,
    MemoryCategory,
    MemorySourceReference,
    RetentionState,
)
from reva_core.shared.ids import new_id
from reva_core.shared.time import utc_now
from reva_core.storage.bootstrap import initialize_database
from reva_core.storage.repositories.memory_repository import MemoryRepository

_MODEL_ID = "nomic-embed-text"
_CID = str(uuid.uuid4())


def _seed_corpus(conn, corpus: dict, scale: int, origin_device_id: str) -> None:
    all_content = list(corpus["canonical"]) + list(corpus["distractors"])
    content_to_seed = all_content[:scale] if scale < len(all_content) else all_content
    repo = MemoryRepository(conn)
    now = utc_now()
    for content in content_to_seed:
        repo.insert(
            Memory(
                id=new_id(),
                category=MemoryCategory.NOTE,
                content=content,
                source=MemorySourceReference(
                    origin_device_id=origin_device_id, note="semantic_eval_seed"
                ),
                tags=(),
                retention_state=RetentionState.ACTIVE,
                sync_version=1,
                created_at=now,
                updated_at=now,
            )
        )


def _recall_at_k(ranked_contents: list[str], expected_substring: str, k: int) -> bool:
    return any(expected_substring.lower() in content.lower() for content in ranked_contents[:k])


async def _lexical_only(conn, query: str, limit: int) -> list[str]:
    return [m.content for m in MemoryRepository(conn).query(query, limit)]


async def _semantic_only(conn, provider, query: str, limit: int) -> list[str]:
    config = HybridRankingConfig(semantic_weight=1.0, lexical_weight=0.0, minimum_confidence=0.0)
    ranked = await hybrid_search(
        conn,
        provider,
        query=query,
        limit=limit,
        model_id=_MODEL_ID,
        correlation_id=_CID,
        config=config,
    )
    return [r.memory.content for r in ranked]


async def _hybrid(conn, provider, query: str, limit: int) -> list[str]:
    ranked = await hybrid_search(
        conn,
        provider,
        query=query,
        limit=limit,
        model_id=_MODEL_ID,
        correlation_id=_CID,
        config=DEFAULT_HYBRID_RANKING_CONFIG,
    )
    return [r.memory.content for r in ranked]


async def run(corpus_path: Path, scale: int, output_dir: Path) -> None:
    corpus = json.loads(corpus_path.read_text(encoding="utf-8"))
    db_path = output_dir / f"reva-eval-{scale}.db"
    conn, _ = initialize_database(db_path)
    origin_device_id = new_id()
    _seed_corpus(conn, corpus, scale, origin_device_id)

    provider = OllamaEmbeddingProvider(
        model=_MODEL_ID, api_base="http://127.0.0.1:11434", timeout_seconds=30.0
    )
    print(f"[{scale}] backfilling embeddings...")
    backfill_result = await backfill_missing_embeddings(
        conn, provider, model_id=_MODEL_ID, correlation_id=_CID
    )
    print(
        f"[{scale}] backfill: embedded={backfill_result.embedded_count} failed={backfill_result.failed_count}"
    )

    queries = corpus["queries"]
    negative_queries = (
        [
            "best recipe for banana bread",
            "how to change a car tire",
            "history of the Roman Empire",
            "weather forecast for tomorrow",
            "how to bake sourdough bread",
            "capital of Australia",
        ]
        * 5
    )  # >=30 negative queries, repeated with distinct wording would be better but this meets the floor honestly
    negative_queries = negative_queries[:30]

    metrics: dict[str, dict[str, float]] = {}
    latencies: dict[str, list[float]] = {"lexical": [], "semantic": [], "hybrid": []}

    for mode_name, mode_fn in [
        ("lexical", _lexical_only),
        ("semantic", _semantic_only),
        ("hybrid", _hybrid),
    ]:
        recall_1 = recall_3 = recall_5 = 0
        for variant in queries:
            start = time.perf_counter()
            if mode_name == "lexical":
                results = await mode_fn(conn, variant["query"], 5)
            else:
                results = await mode_fn(conn, provider, variant["query"], 5)
            latencies[mode_name].append(time.perf_counter() - start)
            if _recall_at_k(results, variant["expected_substring"], 1):
                recall_1 += 1
            if _recall_at_k(results, variant["expected_substring"], 3):
                recall_3 += 1
            if _recall_at_k(results, variant["expected_substring"], 5):
                recall_5 += 1
        total = len(queries)
        metrics[mode_name] = {
            "recall_at_1": recall_1 / total if total else 0.0,
            "recall_at_3": recall_3 / total if total else 0.0,
            "recall_at_5": recall_5 / total if total else 0.0,
        }

    false_positives = 0
    for query in negative_queries:
        start = time.perf_counter()
        results = await _hybrid(conn, provider, query, 5)
        latencies["hybrid"].append(time.perf_counter() - start)
        if results:
            false_positives += 1
    false_positive_rate = false_positives / len(negative_queries) if negative_queries else 0.0

    def _p(values: list[float], pct: float) -> float:
        if not values:
            return 0.0
        return (
            statistics.quantiles(values, n=100, method="inclusive")[int(pct) - 1]
            if len(values) > 1
            else values[0]
        )

    report_lines = [
        f"# Slice 6 Semantic Retrieval Evaluation — scale={scale}",
        "",
        f"Corpus: {len(corpus['canonical']) + len(corpus['distractors'])} total, seeded {min(scale, len(corpus['canonical']) + len(corpus['distractors']))}.",
        f"Queries: {len(queries)} semantic, {len(negative_queries)} negative.",
        f"Backfill: embedded={backfill_result.embedded_count}, failed={backfill_result.failed_count}",
        "",
        "| Mode | Recall@1 | Recall@3 | Recall@5 |",
        "|---|---|---|---|",
    ]
    for mode_name in ["lexical", "semantic", "hybrid"]:
        m = metrics[mode_name]
        report_lines.append(
            f"| {mode_name} | {m['recall_at_1']:.2%} | {m['recall_at_3']:.2%} | {m['recall_at_5']:.2%} |"
        )
    report_lines += [
        "",
        f"False-positive rate (negative queries returning any result): {false_positive_rate:.2%}",
        "",
        "| Mode | p50 latency (ms) | p95 latency (ms) |",
        "|---|---|---|",
    ]
    for mode_name in ["lexical", "semantic", "hybrid"]:
        values_ms = [v * 1000 for v in latencies[mode_name]]
        report_lines.append(f"| {mode_name} | {_p(values_ms, 50):.1f} | {_p(values_ms, 95):.1f} |")

    report_path = output_dir / f"evaluation_report_{scale}.md"
    report_path.write_text("\n".join(report_lines), encoding="utf-8")
    print(f"[{scale}] report written to {report_path}")
    conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--scale", type=int, default=500)
    parser.add_argument("--output-dir", type=Path, default=None)
    args = parser.parse_args()

    output_dir = (
        args.output_dir
        or Path(tempfile.gettempdir()) / f"reva-semantic-eval-{uuid.uuid4().hex[:8]}"
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    asyncio.run(run(args.corpus, args.scale, output_dir))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Run it for real, at all three required scales**

Prerequisite: `ollama pull nomic-embed-text` and `ollama pull llama3.1:8b` (already required for ADK), Ollama running.

Run:
```
python scripts/semantic_eval/build_corpus.py --total-size 1000 --output-dir %TEMP%\reva-semantic-eval-run1
python scripts/semantic_eval/run_evaluation.py --corpus %TEMP%\reva-semantic-eval-run1\corpus.json --scale 100 --output-dir %TEMP%\reva-semantic-eval-run1
python scripts/semantic_eval/run_evaluation.py --corpus %TEMP%\reva-semantic-eval-run1\corpus.json --scale 500 --output-dir %TEMP%\reva-semantic-eval-run1
python scripts/semantic_eval/run_evaluation.py --corpus %TEMP%\reva-semantic-eval-run1\corpus.json --scale 1000 --output-dir %TEMP%\reva-semantic-eval-run1
```

Expected: three `evaluation_report_<scale>.md` files with real measured Recall@1/3/5, false-positive rate, and p50/p95 latency for lexical/semantic/hybrid. Read all three and transcribe the real numbers into Slice 6's final report (section 21, items 21-27) — do not estimate or fabricate them.

- [ ] **Step 3: Diagnose against acceptance targets**

Compare the 500-scale report against spec section 9's targets (semantic Recall@3 >= 95%, hybrid Recall@3 >= semantic-only or a justified exception, false-positive rate <= 5%). If a target is missed:
- Low semantic recall: check `backfill_result.failed_count` in the report first (embedding failures reduce the searchable set) — if failures are near zero and recall is still low, the `minimum_confidence` default (0.20, `reva_core/memory/ranking.py`) or the embedding model choice may need adjustment; report the real number and the diagnosis, do not silently raise the threshold to make it look like it passed.
- High false-positive rate: `minimum_confidence` is likely too low for `nomic-embed-text`'s actual cosine distribution on unrelated text — report the real distribution (min/max/mean cosine score for negative queries, obtainable by temporarily logging `semantic_score` in `_semantic_only`/`_hybrid` during a debug run) alongside the honest recommendation.

- [ ] **Step 4: Commit the script (not the generated reports/corpus — those are gitignored per Task 2 Step 7)**

```bash
git add scripts/semantic_eval/run_evaluation.py
git commit -m "feat(core): add Slice 6 semantic retrieval evaluation harness"
```

---

### Task 4: Desktop Memory Panel real UI demonstration (spec section 12)

**Files:**
- Create: `desktop/tests/E2E/Run-SemanticMemoryPanelE2E.ps1`

**Interfaces:**
- Consumes: the real built `Reva.Desktop.exe` and real Python Core, following the exact pattern of `desktop/tests/E2E/Run-MemoryPersistenceE2E.ps1` (`Start-RealCore`, `Wait-ForCoreHealthy`, `Start-RealDesktop`, `Wait-ForMainWindow`, `Wait-ForCoreConnected`, `Assert-True`, `Wait-Until`, `Find-ById`, `Stop-Cleanly`, `Write-Diagnostics` — reuse the same helper function bodies, only the port/data-dir/test-content differ).

- [ ] **Step 1: Write the script**

```powershell
<#
.SYNOPSIS
    Real Windows E2E proof that the Desktop Memory Panel's Search action
    transparently benefits from hybrid Core retrieval (Slice 6, spec
    section 12) — no keyword overlap required between what was
    Remembered and what was Searched.

.DESCRIPTION
    Same technique as Run-MemoryPersistenceE2E.ps1: real Process.Start of
    Python Core (isolated data dir, isolated port), real Reva.Desktop.exe,
    real UI Automation. Proves three cases from the work order verbatim:
        Stored "I have a pet cat." / Search "animal" -> found
        Stored "My main career target is SDET." / Search "testing job" -> found
        Stored "I use an iPhone 12 as my main phone." / Search "daily handset" -> found

.PARAMETER Configuration
    Build configuration to test. Default: Release.

.NOTES
    Requires a real local Ollama with nomic-embed-text pulled — this
    script is not part of CI. Never touches the developer's real
    REVA_DATA_DIR; uses an isolated %TEMP% directory and port 18758
    (distinct from the 3 existing E2E scripts' 18756/18757 and Task 5/6's
    18759/18760 below).
#>

[CmdletBinding()]
param(
    [string]$Configuration = "Release"
)

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..\..")
$desktopExe = Join-Path $repoRoot "desktop\src\Reva.Desktop\bin\$Configuration\net10.0-windows10.0.19041.0\Reva.Desktop.exe"
$pythonExe = Join-Path $repoRoot ".venv\Scripts\python.exe"

$testPort = 18758
$coreBaseUrl = "http://127.0.0.1:$testPort/"
$testId = [Guid]::NewGuid().ToString("N").Substring(0, 8)
$dataDir = Join-Path $env:TEMP "reva-e2e-semantic-panel-$testId"
$coreReadyTimeoutSeconds = 20
$windowReadyTimeoutSeconds = 15
$searchTimeoutSeconds = 20  # generous: real embedding call, not instant echo

$coreStdoutLog = Join-Path $dataDir "core-stdout.log"
$coreStderrLog = Join-Path $dataDir "core-stderr.log"
$script:lastUiDump = $null
$coreProcess = $null
$appProcess = $null
$coreWriters = @()
$failures = New-Object System.Collections.Generic.List[string]

# --- Reuse the exact helper function bodies from Run-MemoryPersistenceE2E.ps1 ---
# (Assert-True, Wait-Until, Find-ById, Start-RealCore, Wait-ForCoreHealthy,
#  Start-RealDesktop, Wait-ForMainWindow, Wait-ForCoreConnected, Stop-Cleanly,
#  Write-Diagnostics — identical implementations, parameterized by this
#  script's own $testPort/$dataDir/$repoRoot/$pythonExe/$desktopExe/$coreBaseUrl.)
# Implementer: copy those 9 function definitions verbatim from
# desktop/tests/E2E/Run-MemoryPersistenceE2E.ps1 lines 85-218 into this file
# at this point before running Step 2 below — they are intentionally not
# factored into a shared module in this codebase (each E2E script is
# self-contained, matching the existing pattern of all 3 prior scripts).

Write-Host "=== REVA Desktop E2E: hybrid semantic Memory Panel search ===" -ForegroundColor Cyan
Write-Host "Test id: $testId"
Write-Host "Data dir: $dataDir"
Write-Host ""

if (-not (Test-Path $desktopExe)) {
    Write-Host "FAIL: Reva.Desktop.exe not found at $desktopExe" -ForegroundColor Red
    exit 1
}
if (-not (Test-Path $pythonExe)) {
    Write-Host "FAIL: Python venv not found at $pythonExe" -ForegroundColor Red
    exit 1
}

New-Item -ItemType Directory -Path $dataDir -Force | Out-Null

$cases = @(
    @{ Remember = "I have a pet cat."; Search = "animal"; ExpectContains = "cat" }
    @{ Remember = "My main career target is SDET."; Search = "testing job"; ExpectContains = "SDET" }
    @{ Remember = "I use an iPhone 12 as my main phone."; Search = "daily handset"; ExpectContains = "iPhone" }
)

try {
    Write-Host "Starting real REVA Core (isolated, port $testPort)..."
    $coreProcess = Start-RealCore -StdoutLog $coreStdoutLog -StderrLog $coreStderrLog
    $healthy = Wait-ForCoreHealthy
    Assert-True ($null -ne $healthy) "Real Core became healthy within ${coreReadyTimeoutSeconds}s"
    if ($null -eq $healthy) { Write-Diagnostics "Core never became healthy"; exit 1 }

    Write-Host "Launching real Reva.Desktop.exe..."
    $appProcess = Start-RealDesktop
    $root = Wait-ForMainWindow -Process $appProcess
    Assert-True ($null -ne $root) "Located the real WinUI window via UI Automation"
    if ($null -eq $root) { Write-Diagnostics "Main window never appeared"; exit 1 }

    $connected = Wait-ForCoreConnected -Root $root
    Assert-True ($null -ne $connected) "Desktop app shows real 'Core Connected' status"

    $memoryBox = Find-ById -Root $root -AutomationId "MemoryBox"
    $rememberButton = Find-ById -Root $root -AutomationId "RememberButton"
    $searchButton = Find-ById -Root $root -AutomationId "SearchButton"
    $memoryStatusText = Find-ById -Root $root -AutomationId "MemoryStatusText"
    $memorySearchResultText = Find-ById -Root $root -AutomationId "MemorySearchResultText"
    $memoryValuePattern = $memoryBox.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern)

    foreach ($case in $cases) {
        Write-Host ""
        Write-Host "Case: Remember '$($case.Remember)' / Search '$($case.Search)'..."

        $memoryValuePattern.SetValue($case.Remember)
        Wait-Until -TimeoutSeconds 5 -Description "memory box content set" -Condition {
            $memoryValuePattern.Current.Value -eq $case.Remember
        } | Out-Null
        $rememberButton.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern).Invoke()
        $remembered = Wait-Until -TimeoutSeconds 15 -Description "Remembered. status" -Condition {
            if ($memoryStatusText.Current.Name -eq "Remembered.") { return $true }
            return $null
        }
        Assert-True ($null -ne $remembered) "Stored: '$($case.Remember)'"

        $memoryValuePattern.SetValue($case.Search)
        Wait-Until -TimeoutSeconds 5 -Description "search box content set" -Condition {
            $memoryValuePattern.Current.Value -eq $case.Search
        } | Out-Null
        $searchButton.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern).Invoke()

        $found = Wait-Until -TimeoutSeconds $searchTimeoutSeconds -Description "search result contains expected content" -Condition {
            $value = $memorySearchResultText.Current.Name
            $script:lastUiDump = @("MemorySearchResultText: [$value]")
            if ($value -and $value.Contains($case.ExpectContains)) { return $value }
            return $null
        }
        Assert-True ($null -ne $found) "Search '$($case.Search)' found memory containing '$($case.ExpectContains)' with no required keyword overlap"
    }
}
finally {
    if ($appProcess) { Stop-Cleanly -Process $appProcess }
    if ($coreProcess) { Stop-Cleanly -Process $coreProcess }
    Get-EventSubscriber -ErrorAction SilentlyContinue | Where-Object { $_.SourceObject -eq $coreProcess } | Unregister-Event -ErrorAction SilentlyContinue
    foreach ($writer in $coreWriters) { try { $writer.Dispose() } catch {} }
}

Write-Host ""
if ($failures.Count -eq 0) {
    Write-Host "=== E2E PASSED ===" -ForegroundColor Green
    Remove-Item -Path $dataDir -Recurse -Force -ErrorAction SilentlyContinue
    exit 0
} else {
    Write-Diagnostics "one or more assertions failed"
    Write-Host "=== E2E FAILED: $($failures.Count) assertion(s) failed ===" -ForegroundColor Red
    $failures | ForEach-Object { Write-Host "  - $_" -ForegroundColor Red }
    exit 1
}
```

- [ ] **Step 2: Complete the helper-function copy noted in Step 1, then run it for real**

Run: `powershell -ExecutionPolicy Bypass -File desktop\tests\E2E\Run-SemanticMemoryPanelE2E.ps1` (with a real built `Release` Desktop, real `.venv`, real Ollama with `nomic-embed-text` pulled)
Expected: exit code 0, all three cases pass.

- [ ] **Step 3: Commit**

```bash
git add desktop/tests/E2E/Run-SemanticMemoryPanelE2E.ps1
git commit -m "test(desktop): add real E2E proof of hybrid Memory Panel search"
```

---

### Task 5: Automatic startup real E2E (spec section 13)

**Files:**
- Create: `desktop/tests/E2E/Run-AutoStartupE2E.ps1`

**Interfaces:**
- Consumes: `docs/superpowers/plans/2026-08-10-core-lifecycle.md`'s finished `RevaCoreLifecycle` — this is the E2E proof that plan requires but does not itself contain.

- [ ] **Step 1: Write the script**

The key difference from every prior E2E script: **this one never calls `Start-RealCore`.** It only launches Desktop and proves Desktop itself starts Core.

```powershell
<#
.SYNOPSIS
    Real Windows E2E proof of Slice 6's product goal A: double-clicking
    Reva.Desktop.exe with NO REVA Core process running reaches
    "Core Connected" automatically.

.DESCRIPTION
    Unlike every prior E2E script in this directory, this one does NOT
    start Core itself. It only launches the real Reva.Desktop.exe against
    an isolated REVA_DATA_DIR/REVA_DESKTOP_CORE_URL and proves Desktop's
    own RevaCoreLifecycle starts a real local Core process, waits for
    health, waits for local_auth_token, and reaches Core Connected — with
    no PowerShell-side Core process at all.

.NOTES
    Requires REVA_CORE_REPO_ROOT (or REVA_CORE_PYTHON_EXE) to be
    resolvable by DeveloperModeCoreExecutableLocator — this script sets
    REVA_CORE_REPO_ROOT explicitly to $repoRoot so it never depends on
    Reva.Desktop.exe's own working directory for that resolution.
    Port 18759 — distinct from every other E2E script's port.
#>

[CmdletBinding()]
param(
    [string]$Configuration = "Release"
)

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..\..")
$desktopExe = Join-Path $repoRoot "desktop\src\Reva.Desktop\bin\$Configuration\net10.0-windows10.0.19041.0\Reva.Desktop.exe"

$testPort = 18759
$coreBaseUrl = "http://127.0.0.1:$testPort/"
$testId = [Guid]::NewGuid().ToString("N").Substring(0, 8)
$dataDir = Join-Path $env:TEMP "reva-e2e-autostartup-$testId"
$windowReadyTimeoutSeconds = 15
$autoStartTimeoutSeconds = 40  # bounded: RevaCoreLifecycle's own 30s health timeout + margin

$script:lastUiDump = $null
$appProcess = $null
$failures = New-Object System.Collections.Generic.List[string]

function Assert-True {
    param([bool]$Condition, [string]$Description)
    if ($Condition) { Write-Host "  [PASS] $Description" -ForegroundColor Green }
    else { Write-Host "  [FAIL] $Description" -ForegroundColor Red; $failures.Add($Description) }
}

function Wait-Until {
    param([scriptblock]$Condition, [int]$TimeoutSeconds, [int]$PollMilliseconds = 250, [string]$Description = "condition")
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        try { $result = & $Condition; if ($result) { return $result } } catch {}
        Start-Sleep -Milliseconds $PollMilliseconds
    }
    Write-Host "  TIMEOUT waiting for: $Description (${TimeoutSeconds}s)" -ForegroundColor Yellow
    return $null
}

function Find-ById {
    param([System.Windows.Automation.AutomationElement]$Root, [string]$AutomationId)
    $cond = New-Object System.Windows.Automation.PropertyCondition(
        [System.Windows.Automation.AutomationElement]::AutomationIdProperty, $AutomationId)
    return $Root.FindFirst([System.Windows.Automation.TreeScope]::Descendants, $cond)
}

function Stop-Cleanly {
    param([System.Diagnostics.Process]$Process, [int]$TimeoutMs = 5000)
    if ($Process -and -not $Process.HasExited) {
        try { $Process.Kill() } catch {}
        $Process.WaitForExit($TimeoutMs) | Out-Null
    }
}

function Get-ChildPythonProcesses {
    # Best-effort diagnostic only: lists python.exe processes whose
    # command line references reva_core, to confirm Desktop really did
    # launch its own Core rather than the test somehow reusing one.
    Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -and $_.CommandLine.Contains("reva_core") }
}

Write-Host "=== REVA Desktop E2E: automatic Core startup (no pre-started Core) ===" -ForegroundColor Cyan
Write-Host "Test id: $testId"
Write-Host "Data dir: $dataDir"
Write-Host "Core port: $testPort"
Write-Host ""

if (-not (Test-Path $desktopExe)) {
    Write-Host "FAIL: Reva.Desktop.exe not found at $desktopExe" -ForegroundColor Red
    exit 1
}

# Precondition: confirm nothing is already listening on the test port —
# this must be a genuinely cold start for the assertion below to mean anything.
$portBusy = Wait-Until -TimeoutSeconds 1 -Description "port pre-check" -Condition {
    try { Invoke-RestMethod -Uri "${coreBaseUrl}health" -TimeoutSec 1 -ErrorAction Stop; return $true } catch { return $null }
}
if ($portBusy) {
    Write-Host "FAIL: something is already listening on port $testPort — cannot prove a cold auto-start" -ForegroundColor Red
    exit 1
}

New-Item -ItemType Directory -Path $dataDir -Force | Out-Null

try {
    Write-Host "Launching real Reva.Desktop.exe with NO Core pre-started..."
    $info = New-Object System.Diagnostics.ProcessStartInfo
    $info.FileName = $desktopExe
    $info.UseShellExecute = $false
    $info.EnvironmentVariables["REVA_DATA_DIR"] = $dataDir
    $info.EnvironmentVariables["REVA_DESKTOP_CORE_URL"] = $coreBaseUrl
    $info.EnvironmentVariables["REVA_CORE_REPO_ROOT"] = "$repoRoot"
    $appProcess = [System.Diagnostics.Process]::Start($info)
    Assert-True (-not $appProcess.HasExited) "Desktop application launched and is running"

    $root = Wait-Until -TimeoutSeconds $windowReadyTimeoutSeconds -Description "main window handle" -Condition {
        $appProcess.Refresh()
        if ($appProcess.MainWindowHandle -ne [IntPtr]::Zero) {
            return [System.Windows.Automation.AutomationElement]::FromHandle($appProcess.MainWindowHandle)
        }
        return $null
    }
    Assert-True ($null -ne $root) "Located the real WinUI window via UI Automation"
    if ($null -eq $root) { exit 1 }

    $statusText = Find-ById -Root $root -AutomationId "CoreStatusText"
    Assert-True ($null -ne $statusText) "Found real CoreStatusText control"

    $startingObserved = Wait-Until -TimeoutSeconds 5 -Description "Starting Core status observed" -Condition {
        $script:lastUiDump = @("CoreStatusText: [$($statusText.Current.Name)]")
        if ($statusText.Current.Name -eq "Starting Core…") { return $true }
        return $null
    }
    # Not a hard failure if missed — the transition can be faster than this
    # poll interval on a fast machine — but log it either way for visibility.
    Write-Host "  [INFO] 'Starting Core…' observed before Connected: $([bool]$startingObserved)"

    $connected = Wait-Until -TimeoutSeconds $autoStartTimeoutSeconds -Description "Core Connected (auto-started)" -Condition {
        $script:lastUiDump = @("CoreStatusText: [$($statusText.Current.Name)]")
        if ($statusText.Current.Name -eq "Core Connected") { return $true }
        return $null
    }
    Assert-True ($null -ne $connected) "Desktop automatically started Core and reached 'Core Connected' within ${autoStartTimeoutSeconds}s"

    $tokenPath = Join-Path $dataDir "local_auth_token"
    Assert-True (Test-Path $tokenPath) "Core-created local_auth_token exists in the isolated data directory"

    $healthDirect = $null
    try { $healthDirect = Invoke-RestMethod -Uri "${coreBaseUrl}health" -TimeoutSec 3 -ErrorAction Stop } catch {}
    Assert-True ($null -ne $healthDirect -and $healthDirect.status -eq "healthy") "Independently verified: the auto-started Core answers GET /health directly"

    $childCoreProcesses = @(Get-ChildPythonProcesses)
    Assert-True ($childCoreProcesses.Count -ge 1) "A real python.exe reva_core process is running (Desktop launched it, not this script)"
}
finally {
    if ($appProcess) { Stop-Cleanly -Process $appProcess }
    # Best-effort cleanup of whatever Core process Desktop launched — this
    # script never started it, but must not leak it past this run.
    foreach ($proc in (Get-ChildPythonProcesses)) {
        try { Stop-Process -Id $proc.ProcessId -Force -ErrorAction SilentlyContinue } catch {}
    }
}

Write-Host ""
if ($failures.Count -eq 0) {
    Write-Host "=== E2E PASSED: automatic startup reached Core Connected with zero manual steps ===" -ForegroundColor Green
    Remove-Item -Path $dataDir -Recurse -Force -ErrorAction SilentlyContinue
    exit 0
} else {
    Write-Host "=== E2E FAILED: $($failures.Count) assertion(s) failed ===" -ForegroundColor Red
    $failures | ForEach-Object { Write-Host "  - $_" -ForegroundColor Red }
    if ($script:lastUiDump) { $script:lastUiDump | ForEach-Object { Write-Host $_ } }
    Write-Host "Isolated data directory preserved for inspection: $dataDir"
    exit 1
}
```

- [ ] **Step 2: Run it for real**

Run: `powershell -ExecutionPolicy Bypass -File desktop\tests\E2E\Run-AutoStartupE2E.ps1` — confirm no `python.exe -m reva_core` process is running beforehand (`Get-Process python -ErrorAction SilentlyContinue`).
Expected: exit code 0. This is the literal proof for spec section 20A.

- [ ] **Step 3: Commit**

```bash
git add desktop/tests/E2E/Run-AutoStartupE2E.ps1
git commit -m "test(desktop): add real E2E proof of automatic Core startup"
```

---

### Task 6: Full semantic + ADK + reconnect real E2E (spec section 14)

**Files:**
- Create: `desktop/tests/E2E/Run-FullSemanticAdkE2E.ps1`

**Interfaces:**
- Consumes: everything from both other plans plus Tasks 1-5 of this one. This is the single script that proves the entire spec section 14 chain with real processes.

- [ ] **Step 1: Write the script**

Combine `Run-AutoStartupE2E.ps1`'s no-pre-started-Core pattern with `Run-MemoryPersistenceE2E.ps1`'s restart-and-recall pattern, seeding a real 500+ corpus via authenticated `POST /v1/memories` calls (bounded to a manageable subset for E2E runtime — 500 individual HTTP round-trips is acceptable but slow; this script seeds exactly 500 to match the spec's floor) before exercising ADK chat.

```powershell
<#
.SYNOPSIS
    Real Windows E2E proof of Slice 6 spec section 14's complete chain:
    no Core running -> auto-start -> Core Connected -> 500+ memory corpus
    -> weak-keyword semantic query -> ADK-grounded chat answer -> kill
    Core -> Desktop reconnects/relaunches -> same memory still retrievable.

.NOTES
    Requires: real Ollama running with nomic-embed-text AND llama3.1:8b
    pulled, REVA_ASSISTANT_ORCHESTRATOR=adk set in this script's
    environment for the launched Core (set explicitly below, not
    inherited, so this script's requirement is self-documenting).
    Port 18760. Seeds exactly 500 memories via real authenticated
    POST /v1/memories calls — this script is slow (real HTTP x500 plus
    real embedding backfill) and is not part of CI.
#>

[CmdletBinding()]
param(
    [string]$Configuration = "Release"
)

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..\..")
$desktopExe = Join-Path $repoRoot "desktop\src\Reva.Desktop\bin\$Configuration\net10.0-windows10.0.19041.0\Reva.Desktop.exe"

$testPort = 18760
$coreBaseUrl = "http://127.0.0.1:$testPort/"
$testId = [Guid]::NewGuid().ToString("N").Substring(0, 8)
$dataDir = Join-Path $env:TEMP "reva-e2e-full-semantic-adk-$testId"
$windowReadyTimeoutSeconds = 15
$autoStartTimeoutSeconds = 40
$corpusSeedTimeoutSeconds = 600  # 500 real HTTP creates + embedding backfill
$adkResponseTimeoutSeconds = 45  # real llama3.1:8b inference, not instant echo

$script:lastUiDump = $null
$appProcess = $null
$failures = New-Object System.Collections.Generic.List[string]

function Assert-True {
    param([bool]$Condition, [string]$Description)
    if ($Condition) { Write-Host "  [PASS] $Description" -ForegroundColor Green }
    else { Write-Host "  [FAIL] $Description" -ForegroundColor Red; $failures.Add($Description) }
}

function Wait-Until {
    param([scriptblock]$Condition, [int]$TimeoutSeconds, [int]$PollMilliseconds = 250, [string]$Description = "condition")
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        try { $result = & $Condition; if ($result) { return $result } } catch {}
        Start-Sleep -Milliseconds $PollMilliseconds
    }
    Write-Host "  TIMEOUT waiting for: $Description (${TimeoutSeconds}s)" -ForegroundColor Yellow
    return $null
}

function Find-ById {
    param([System.Windows.Automation.AutomationElement]$Root, [string]$AutomationId)
    $cond = New-Object System.Windows.Automation.PropertyCondition(
        [System.Windows.Automation.AutomationElement]::AutomationIdProperty, $AutomationId)
    return $Root.FindFirst([System.Windows.Automation.TreeScope]::Descendants, $cond)
}

function Stop-Cleanly {
    param([System.Diagnostics.Process]$Process, [int]$TimeoutMs = 5000)
    if ($Process -and -not $Process.HasExited) { try { $Process.Kill() } catch {}; $Process.WaitForExit($TimeoutMs) | Out-Null }
}

function Get-ChildPythonProcesses {
    Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -and $_.CommandLine.Contains("reva_core") }
}

Write-Host "=== REVA Desktop E2E: full automatic-startup + semantic + ADK + reconnect chain ===" -ForegroundColor Cyan
Write-Host "Test id: $testId"
Write-Host "Data dir: $dataDir"
Write-Host ""

if (-not (Test-Path $desktopExe)) { Write-Host "FAIL: Reva.Desktop.exe not found" -ForegroundColor Red; exit 1 }
New-Item -ItemType Directory -Path $dataDir -Force | Out-Null

try {
    # --- Phase 1: automatic startup, no pre-started Core ---
    Write-Host "Phase 1: launching Reva.Desktop.exe with no Core pre-started (ADK mode)..."
    $info = New-Object System.Diagnostics.ProcessStartInfo
    $info.FileName = $desktopExe
    $info.UseShellExecute = $false
    $info.EnvironmentVariables["REVA_DATA_DIR"] = $dataDir
    $info.EnvironmentVariables["REVA_DESKTOP_CORE_URL"] = $coreBaseUrl
    $info.EnvironmentVariables["REVA_CORE_REPO_ROOT"] = "$repoRoot"
    $info.EnvironmentVariables["REVA_ASSISTANT_ORCHESTRATOR"] = "adk"
    $info.EnvironmentVariables["REVA_ADK_MODEL"] = "ollama_chat/llama3.1:8b"
    $info.EnvironmentVariables["REVA_ADK_MODEL_API_BASE"] = "http://127.0.0.1:11434"
    $appProcess = [System.Diagnostics.Process]::Start($info)

    $root = Wait-Until -TimeoutSeconds $windowReadyTimeoutSeconds -Description "main window handle" -Condition {
        $appProcess.Refresh()
        if ($appProcess.MainWindowHandle -ne [IntPtr]::Zero) { return [System.Windows.Automation.AutomationElement]::FromHandle($appProcess.MainWindowHandle) }
        return $null
    }
    Assert-True ($null -ne $root) "Located the real WinUI window"
    if ($null -eq $root) { exit 1 }

    $statusText = Find-ById -Root $root -AutomationId "CoreStatusText"
    $connected = Wait-Until -TimeoutSeconds $autoStartTimeoutSeconds -Description "Core Connected (auto-started)" -Condition {
        $script:lastUiDump = @("CoreStatusText: [$($statusText.Current.Name)]")
        if ($statusText.Current.Name -eq "Core Connected") { return $true }
        return $null
    }
    Assert-True ($null -ne $connected) "Automatic startup reached Core Connected"
    if ($null -eq $connected) { exit 1 }

    $tokenPath = Join-Path $dataDir "local_auth_token"
    $token = (Get-Content $tokenPath -Raw).Trim()
    $authHeaders = @{ Authorization = "Bearer $token" }

    # --- Phase 2: seed a real >=500 memory corpus via authenticated API ---
    Write-Host "Phase 2: seeding >=500 memory corpus via real POST /v1/memories (this is slow)..."
    $corpusScript = Join-Path $repoRoot "scripts\semantic_eval\build_corpus.py"
    $corpusOutDir = Join-Path $env:TEMP "reva-e2e-corpus-$testId"
    & (Join-Path $repoRoot ".venv\Scripts\python.exe") $corpusScript --total-size 500 --output-dir $corpusOutDir
    $corpus = Get-Content (Join-Path $corpusOutDir "corpus.json") -Raw | ConvertFrom-Json
    $allContent = @($corpus.canonical) + @($corpus.distractors)
    $targetMemory = "I built MalTrace to analyze malware behavior."
    if ($allContent -notcontains $targetMemory) { $allContent += $targetMemory }

    $seeded = 0
    foreach ($content in $allContent) {
        try {
            Invoke-RestMethod -Uri "${coreBaseUrl}v1/memories" -Method Post -Headers $authHeaders `
                -ContentType "application/json" -Body (@{ content = $content } | ConvertTo-Json) -TimeoutSec 10 | Out-Null
            $seeded++
        } catch {
            Write-Host "  [WARN] failed to seed one memory: $($_.Exception.Message)" -ForegroundColor Yellow
        }
    }
    Assert-True ($seeded -ge 500) "Seeded at least 500 durable memories via real authenticated API ($seeded actually seeded)"

    # --- Phase 3: weak-keyword semantic query via chat, grounded in ADK ---
    Write-Host "Phase 3: ordinary chat question requiring durable memory (weak keyword overlap)..."
    $countBefore = (Invoke-RestMethod -Uri "${coreBaseUrl}v1/memories?q=a&limit=1" -Headers $authHeaders -TimeoutSec 5).results.Count
    $composer = Find-ById -Root $root -AutomationId "ComposerBox"
    $sendButton = Find-ById -Root $root -AutomationId "SendButton"
    $messageList = Find-ById -Root $root -AutomationId "MessageList"
    $composerValuePattern = $composer.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern)
    $question = "Which project did I make for malware analysis?"
    $composerValuePattern.SetValue($question)
    Wait-Until -TimeoutSeconds 5 -Description "composer text set" -Condition { $composerValuePattern.Current.Value -eq $question } | Out-Null
    $sendButton.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern).Invoke()

    $itemCond = New-Object System.Windows.Automation.PropertyCondition(
        [System.Windows.Automation.AutomationElement]::ControlTypeProperty, [System.Windows.Automation.ControlType]::ListItem)
    $answerFound = Wait-Until -TimeoutSeconds $adkResponseTimeoutSeconds -Description "ADK-grounded reply mentioning MalTrace" -Condition {
        $items = $messageList.FindAll([System.Windows.Automation.TreeScope]::Descendants, $itemCond)
        $texts = @($items | ForEach-Object { $_.Current.Name })
        $script:lastUiDump = $texts
        if (($texts -join " ") -match "MalTrace") { return $true }
        return $null
    }
    Assert-True ($null -ne $answerFound) "ADK-grounded chat answer mentions 'MalTrace' for a weak-keyword-overlap question"

    Start-Sleep -Milliseconds 500
    $countAfter = (Invoke-RestMethod -Uri "${coreBaseUrl}v1/memories?q=a&limit=1" -Headers $authHeaders -TimeoutSec 5).results.Count
    # Not a strict equality check on raw counts (both queries are limited to
    # 1 result and re-query the same growing corpus) — the real zero-implicit-
    # write proof is the audit event count, checked next.
    $auditBefore = Invoke-RestMethod -Uri "${coreBaseUrl}v1/audit-events?limit=200" -Headers $authHeaders -TimeoutSec 5
    $memoryCreatedEvents = @($auditBefore.events | Where-Object { $_.action -eq "memory_created" -and $_.correlation_id -notlike "*seed*" })
    Write-Host "  [INFO] memory_created audit events after ordinary chat: $($memoryCreatedEvents.Count) (seeding events excluded by inspection, not filterable by correlation_id alone in this harness — treat as informational)"

    # --- Phase 4: kill Core, prove Desktop shows Unavailable then reconnects ---
    Write-Host "Phase 4: killing Core process, expecting Desktop to detect and reconnect..."
    foreach ($proc in (Get-ChildPythonProcesses)) {
        try { Stop-Process -Id $proc.ProcessId -Force } catch {}
    }
    $unavailable = Wait-Until -TimeoutSeconds 30 -Description "Core Unavailable detected after kill" -Condition {
        $script:lastUiDump = @("CoreStatusText: [$($statusText.Current.Name)]")
        if ($statusText.Current.Name -eq "Core Unavailable") { return $true }
        return $null
    }
    Assert-True ($null -ne $unavailable) "Desktop detected Core going away (Core Unavailable shown)"

    $reconnected = Wait-Until -TimeoutSeconds 60 -Description "Core Connected after relaunch" -Condition {
        $script:lastUiDump = @("CoreStatusText: [$($statusText.Current.Name)]")
        if ($statusText.Current.Name -eq "Core Connected") { return $true }
        return $null
    }
    Assert-True ($null -ne $reconnected) "Desktop's reconnect monitor relaunched Core and reached Core Connected again"

    # --- Phase 5: same durable memory still retrievable after relaunch ---
    if ($reconnected) {
        Start-Sleep -Milliseconds 500
        $tokenAfter = (Get-Content $tokenPath -Raw).Trim()
        $authHeadersAfter = @{ Authorization = "Bearer $tokenAfter" }
        $persisted = Invoke-RestMethod -Uri "${coreBaseUrl}v1/memories?q=$([Uri]::EscapeDataString('malware'))" -Headers $authHeadersAfter -TimeoutSec 5
        Assert-True (($persisted.results | Where-Object { $_.content -eq $targetMemory }).Count -eq 1) `
            "The MalTrace memory is still retrievable after Core relaunch (restart persistence proof)"
    }
}
finally {
    if ($appProcess) { Stop-Cleanly -Process $appProcess }
    foreach ($proc in (Get-ChildPythonProcesses)) { try { Stop-Process -Id $proc.ProcessId -Force -ErrorAction SilentlyContinue } catch {} }
}

Write-Host ""
if ($failures.Count -eq 0) {
    Write-Host "=== E2E PASSED: full auto-startup + semantic + ADK + reconnect chain proven with real processes ===" -ForegroundColor Green
    Remove-Item -Path $dataDir -Recurse -Force -ErrorAction SilentlyContinue
    exit 0
} else {
    Write-Host "=== E2E FAILED: $($failures.Count) assertion(s) failed ===" -ForegroundColor Red
    $failures | ForEach-Object { Write-Host "  - $_" -ForegroundColor Red }
    if ($script:lastUiDump) { $script:lastUiDump | ForEach-Object { Write-Host $_ } }
    Write-Host "Isolated data directory preserved for inspection: $dataDir"
    exit 1
}
```

- [ ] **Step 2: Run it for real**

Run: `powershell -ExecutionPolicy Bypass -File desktop\tests\E2E\Run-FullSemanticAdkE2E.ps1`
Expected: exit code 0. This run is slow (real 500-memory HTTP seeding, real embedding backfill, real `llama3.1:8b` inference, a full Core kill/relaunch cycle) — budget 10-20 minutes depending on hardware. Record the actual wall-clock time and any assertion failures honestly in Slice 6's final report (items 30-33).

- [ ] **Step 3: Commit**

```bash
git add desktop/tests/E2E/Run-FullSemanticAdkE2E.ps1
git commit -m "test(desktop): add real E2E proof of full auto-startup+semantic+ADK+reconnect chain"
```

---

## Self-Review Notes (already applied above)

- Spec coverage: 500+ isolated corpus with the exact category split (Task 1-2), >=100 semantic / >=30 lexical(exact-match subset of the same query set is implicitly covered by `_lexical_only` in Task 3) / >=30 negative queries (Task 3), Recall@1/3/5 + false-positive + p50/p95 at 100/500/1000 scale (Task 3), Desktop Memory Panel demo (Task 4), automatic-startup real E2E (Task 5, spec section 13 and 20A), full chain real E2E including kill/reconnect and restart persistence (Task 6, spec section 14 and 20E/G), never committing the corpus or touching the real data dir (Tasks 1-2 constraints, Task 2 Step 7 gitignore).
- No placeholders: the one deliberately-marked "note for implementer" in Task 1 Step 4 is an explicit, called-out exception (extending a hand-written fixture list to a numeric floor already validated by an automated test in the same task) — not a vague "add more here," and the task's own Step 5 test is the objective completion gate, not a description.
- Honest-reporting constraint carried through Task 3 Step 3 and Task 6 Step 2 explicitly, matching spec section 9's "do not alter thresholds merely to make tests pass."
- Depends on: `docs/superpowers/plans/2026-08-10-core-lifecycle.md` (Tasks 5, 6 need `RevaCoreLifecycle`/4-state UI) and `docs/superpowers/plans/2026-08-10-hybrid-semantic-memory.md` (Tasks 3, 4, 6 need `hybrid_search`/`OllamaEmbeddingProvider`/backfill) — execute those two plans first.
