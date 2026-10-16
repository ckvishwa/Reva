# C2b Windows phone-request review

The desktop polls the Core-token loopback inbox. The gateway exposes no inbox or approval endpoint to a phone. T1 orders flow through `AppActionExecutor`, which verifies the signed grant; T2 cards require a click on this PC before Core supplies an order. The executor's report, including failure or unknown, is the only source of a completed status. The coordinator deduplicates grant IDs before execution and the Core hands orders out once.

Review fix: a non-object entry in an otherwise valid inbox array made `TryGetProperty` throw and could stop the background poller. The parser now drops that entry. `A_malformed_inbox_item_does_not_stop_valid_requests` failed before and passed afterward. Full desktop suite: 833 passed, 0 failed; 12 existing opt-in UI tests skipped. Python gateway and UI-fixture subset: 32 passed with real Kernel binding. Physical PC card, approval, and paired-phone result checks remain `NEEDS_HARDWARE`.
