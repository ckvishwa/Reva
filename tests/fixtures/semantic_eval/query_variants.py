# tests/fixtures/semantic_eval/query_variants.py
"""Semantic evaluation query variants (Slice 6). Each variant is an
EVALUATION QUERY, never persisted as a memory — see
docs/superpowers/plans/2026-08-10-semantic-eval-and-e2e.md section 7.
`canonical_memory_substring` is checked against CANONICAL_MEMORIES by
tests/unit/test_semantic_eval_fixtures.py and used by
scripts/semantic_eval/run_evaluation.py to score Recall@k without
hand-maintained IDs.

QUERY_VARIANTS is the semantic/paraphrase set (>=100 required): every
`query` is deliberately reworded away from the source memory's wording
so lexical LIKE matching should NOT find it — that's what makes it a
semantic-retrieval test.

LEXICAL_QUERY_VARIANTS is a separate, deliberately literal set (>=30
required): every `query` is copied verbatim as a contiguous 3+-word
substring straight out of some CANONICAL_MEMORIES entry (not a
paraphrase), because `MemoryRepository.query`'s whole-string substring
`LIKE` match can only ever hit on literal text. Without this set,
lexical-only mode would score 0.0 recall on 100% of queries in this
corpus (every semantic query was written with low keyword overlap on
purpose) and hybrid would degenerate to a pure monotone transform of
semantic-only (lexical_score == 0.0 for every candidate on every
query), making the "hybrid Recall@3 >= semantic-only" acceptance check
pass by algebraic identity rather than by measuring anything real.
`canonical_memory_substring` here follows the same convention as
QUERY_VARIANTS: a distinguishing identifier from the same memory (a
proper noun or unique term), used to score which memory correctly
satisfied the query — it does not need to equal `query` verbatim.
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
    # REVA / software architecture
    QueryVariant("does REVA rely on the cloud or run locally?", "local-first"),
    QueryVariant(
        "can C# read REVA's database directly?", "must not access the REVA SQLite database"
    ),
    QueryVariant(
        "does REVA save every single chat as memory?", "explicit rather than automatically saving"
    ),
    QueryVariant("which local model powers REVA's agent path?", "llama3.1:8b"),
    QueryVariant(
        "is REVA's session memory the same as durable memory?",
        "ADK session state is not REVA durable memory",
    ),
    QueryVariant("what port does the local Core API listen on by default?", "port 8756 by default"),
    QueryVariant(
        "how does the desktop app prove its identity to Core?", "bearer-token authentication"
    ),
    QueryVariant("where does the desktop client keep its login token?", "local_auth_token"),
    QueryVariant(
        "should the auth token ever show up in a log file?", "must never be shown in the UI or logs"
    ),
    QueryVariant(
        "what visual tone should the Windows app have?", "dark, technical, calm, and compact"
    ),
    QueryVariant("what markup language builds the Windows UI?", "uses XAML"),
    QueryVariant("what UI architectural pattern does the desktop follow?", "small MVVM structure"),
    QueryVariant(
        "should C# reimplement logic that already lives in the backend?",
        "avoid duplicating backend logic in C#",
    ),
    QueryVariant(
        "is plain keyword search good enough for finding old memories?",
        "needs improvement beyond lexical matching",
    ),
    QueryVariant(
        "should semantic search live in the desktop client or the backend?",
        "should remain a Core concern rather than a C# concern",
    ),
    QueryVariant(
        "when is it time to add a dedicated vector store?",
        "should not be introduced until scale proves SQLite insufficient",
    ),
    QueryVariant("what other mobile platform might get a client eventually?", "expand to Android"),
    # Technical environment
    QueryVariant(
        "what operating system do I primarily develop on?", "development environment is Windows"
    ),
    QueryVariant("which GPU is in my dev machine?", "RTX 3050"),
    QueryVariant("have I worked with message queues?", "Kafka/Redpanda"),
    QueryVariant("what security certification have I completed?", "Security+"),
    QueryVariant("what did I do at Cognizant?", "Programmer Analyst"),
    QueryVariant("what SOC tooling have I used?", "Splunk"),
    QueryVariant("what CLI project did I build for job hunting?", "JobMachine"),
    QueryVariant("what degree am I pursuing or hold?", "M.S. in Cybersecurity"),
    QueryVariant("what English test am I preparing for?", "IELTS"),
    QueryVariant("what muscle groups do I train?", "shoulders"),
    QueryVariant("which phone is my backup device?", "Samsung Galaxy S24 Ultra"),
    QueryVariant("what instrument am I learning?", "guitar"),
    QueryVariant("what chess opening have I studied?", "Vienna opening"),
    QueryVariant("what tools do I use to track code changes?", "Git and GitHub"),
    QueryVariant("have I written any TypeScript before?", "worked with TypeScript"),
    QueryVariant("have I worked with Java in the past?", "worked with Java"),
    QueryVariant("what shell do I lean on for scripting?", "PowerShell frequently"),
    QueryVariant("what's my heaviest-used programming language?", "work heavily with Python"),
    QueryVariant(
        "what language is the new desktop client written in?",
        "using C# for the new REVA Windows desktop",
    ),
    QueryVariant("what web framework serves REVA's backend API?", "I use FastAPI."),
    QueryVariant("have I used a hosted Postgres platform before?", "worked with Supabase"),
    QueryVariant("have I used an ORM in any past project?", "worked with Prisma"),
    QueryVariant("what .NET runtime version is on my machine?", ".NET 10 installed"),
    # Career
    QueryVariant(
        "what other security-focused title am I considering?",
        "Security Engineer focused on SOC/DFIR",
    ),
    QueryVariant("would I take a more junior position right now?", "Junior roles are acceptable"),
    QueryVariant("what exact title did I hold at my last company?", "Programmer Analyst"),
    QueryVariant("when did my previous job start and end?", "January 2022 through July 2023"),
    QueryVariant("what kind of QA testing did I perform professionally?", "functional testing"),
    QueryVariant(
        "what tool did I use to check REST endpoints at work?", "Postman for REST API validation"
    ),
    QueryVariant(
        "what tool tracked bugs during my QA role?", "Jira for defect lifecycle management"
    ),
    QueryVariant("what Python test framework do I rely on?", "use Pytest"),
    QueryVariant("have I automated browser tests with anything besides Selenium?", "used Cypress"),
    QueryVariant("am I curious about probing AI systems adversarially?", "explored AI red teaming"),
    # Cybersecurity
    QueryVariant("have I built lab environments for spotting attacks?", "SOC/detection labs"),
    QueryVariant("do I capture detailed Windows process activity anywhere?", "I use Sysmon."),
    QueryVariant(
        "have I dug through Windows logs for investigations?", "worked with Windows Event Logs"
    ),
    QueryVariant("have I practiced with a domain-controller environment?", "Active Directory labs"),
    QueryVariant(
        "do I tie attacker behavior back to a known technique framework?", "MITRE ATT&CK mappings"
    ),
    QueryVariant(
        "have I practiced sorting suspicious emails from real ones?", "practiced phishing triage"
    ),
    QueryVariant("have I built alerts for repeated failed logins?", "built brute-force detections"),
    QueryVariant(
        "have I built alerts for attackers maintaining access?", "built persistence detections"
    ),
    QueryVariant("what tool have I used for probing web app security?", "used Burp Suite"),
    QueryVariant("have I reverse-engineered binaries with a disassembler?", "used Ghidra"),
    # Projects
    QueryVariant(
        "what project of mine deals with least-privilege access paths?", "Access Risk Analyzer"
    ),
    QueryVariant("what project did I make to help study for exams?", "CertForge"),
    QueryVariant("does my cert-prep project cover networking exam content?", "CCNA material"),
    QueryVariant("what order-fulfillment style project have I built?", "FulfillX"),
    QueryVariant(
        "what streaming/message broker backs my fulfillment project?",
        "FulfillX uses Kafka/Redpanda",
    ),
    QueryVariant(
        "does my fulfillment project have a front-end for admins?", "React admin interface"
    ),
    QueryVariant("what quality-automation-focused project have I made?", "QualityMesh"),
    QueryVariant("roughly how large did my job-hunt tool's test suite get?", "185 tests"),
    # Education / learning
    QueryVariant(
        "what did I study before focusing on security?", "computer and information science"
    ),
    QueryVariant(
        "am I currently brushing up on networking fundamentals?", "networking/CCNA concepts"
    ),
    QueryVariant("do I learn best by reading or by doing?", "hands-on learning"),
    QueryVariant(
        "do I keep probing a topic until it actually clicks?",
        "follow-up questions until concepts make sense",
    ),
    QueryVariant("what teaching style works best for me?", "explanations with concrete examples"),
    QueryVariant(
        "how do I check that I truly understand something?", "same topic from multiple angles"
    ),
    # Fitness
    QueryVariant("where do I usually go to lift weights?", "Planet Fitness"),
    QueryVariant("do I gravitate toward machines over free weights?", "use machines frequently"),
    QueryVariant("what pushing movements are part of my split?", "train push exercises"),
    QueryVariant("what pulling movements are part of my split?", "train pull exercises"),
    QueryVariant("do I include lower-body work in my routine?", "train legs"),
    QueryVariant("do I specifically isolate my calves?", "train calves"),
    QueryVariant("do I train the width of my back?", "train back width"),
    QueryVariant("do I train biceps as their own movement?", "train biceps"),
    QueryVariant("do I train triceps as their own movement?", "train triceps"),
    QueryVariant("what machine do I use for lat width?", "lat pulldowns"),
    # Devices
    QueryVariant(
        "do I lean toward Android's feel or Apple's?", "feel and animation quality of iOS"
    ),
    QueryVariant("what newer iPhone model have I thought about upgrading to?", "iPhone 18 Pro"),
    QueryVariant("why would I skip the biggest iPhone size option?", "Pro Max is too large for me"),
    QueryVariant(
        "does camera performance factor into my phone choice?",
        "Photography and video quality matter to me",
    ),
    QueryVariant(
        "have I looked into how phone storage chips differ across brands?",
        "iPhone storage technology with Android UFS",
    ),
    QueryVariant(
        "did one of my past phones have a charging cable issue?",
        "wired-charging problems while wireless charging still worked",
    ),
    # Hobbies
    QueryVariant("what guitar model do I actually own?", "Fender Stratocaster HSS"),
    QueryVariant("what amplifier do I play my guitar through?", "Fender LT15 amplifier"),
    QueryVariant("what song have I been working on for guitar practice?", "Dandelions"),
    QueryVariant("roughly where does my chess rating sit?", "700 Elo"),
    QueryVariant(
        "have I asked about a well-known queen-sacrifice chess opening?", "Queen's Gambit"
    ),
)

# Lexical/exact-oriented set (>=30 required) — see module docstring.
# Every `query` below is a verbatim, contiguous, 3+-word substring of a
# real CANONICAL_MEMORIES entry, confirmed by
# test_every_lexical_query_variant_is_a_literal_canonical_substring in
# tests/unit/test_semantic_eval_fixtures.py.
LEXICAL_QUERY_VARIANTS: tuple[QueryVariant, ...] = (
    # MalTrace
    QueryVariant("analyzes malware behavior", "MalTrace"),
    QueryVariant("uses CAPEv2 output", "MalTrace"),
    QueryVariant("Random Forest classification", "MalTrace"),
    QueryVariant("maps behavior to MITRE ATT&CK", "MalTrace"),
    QueryVariant("reported an F1 score", "MalTrace"),
    # SDET / career
    QueryVariant("primary job target is SDET", "SDET"),
    QueryVariant("currently my primary job profile", "SDET"),
    QueryVariant("title was Programmer Analyst", "Programmer Analyst"),
    QueryVariant("ran from January 2022 through", "January 2022 through July 2023"),
    QueryVariant("for REST API validation", "Postman for REST API validation"),
    QueryVariant("for defect lifecycle management", "Jira for defect lifecycle management"),
    # Devices
    QueryVariant("as my main phone", "iPhone 12"),
    QueryVariant("have a Samsung Galaxy S24 Ultra", "Samsung Galaxy S24 Ultra"),
    # Fitness
    QueryVariant("around five days per week", "five days per week"),
    QueryVariant("train at Planet Fitness", "Planet Fitness"),
    # REVA architecture
    QueryVariant("uses port 8756 by default", "port 8756 by default"),
    QueryVariant("stored locally in local_auth_token", "local_auth_token"),
    QueryVariant("never be shown in the UI or logs", "must never be shown in the UI or logs"),
    QueryVariant("uses a small MVVM structure", "small MVVM structure"),
    QueryVariant("application uses XAML", "uses XAML"),
    QueryVariant(
        "must not access the REVA SQLite database", "must not access the REVA SQLite database"
    ),
    QueryVariant("exposes a FastAPI localhost API", "FastAPI localhost API"),
    QueryVariant("has a Core Connected/Core Unavailable", "Core Connected/Core Unavailable"),
    # Projects
    QueryVariant("is a Python CLI job-hunt system", "JobMachine"),
    QueryVariant("reached around 185 tests", "185 tests"),
    QueryVariant("models access paths and least privilege", "Access Risk Analyzer"),
    QueryVariant("is for certification preparation", "CertForge"),
    QueryVariant("includes CCNA material", "CCNA material"),
    QueryVariant("includes a React admin interface", "React admin interface"),
    QueryVariant("is a quality automation-related project", "QualityMesh"),
    QueryVariant("FulfillX uses Kafka/Redpanda", "FulfillX"),
    # Cybersecurity
    QueryVariant("My SOC lab work has included", "Windows domain-controller and endpoint systems"),
    QueryVariant("built an enterprise SOC detection lab", "enterprise SOC detection lab"),
    # Hobbies
    QueryVariant("been around 700 Elo", "700 Elo"),
    QueryVariant("studied the Vienna opening", "Vienna opening"),
    QueryVariant("use a Fender Stratocaster HSS", "Fender Stratocaster HSS"),
)
