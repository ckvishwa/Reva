package app.reva.policy

import java.io.File
import java.time.Instant
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test

private fun contracts() = File(System.getProperty("reva.contracts"))
private fun fixtures() = File(System.getProperty("reva.fixtures"))

fun loadRegistry(): Registry = Registry(JSONObject(File(contracts(), "capability-registry.v2.json").readText()))

/**
 * Replays `tests/fixtures/authorize-cases.json`, written by the Python `authorize()`, against this port: about a
 * thousand proposals across every capability (valid, wrong arguments, forbidden and unknown names, entities of
 * every kind, unresolved words, consent, device scopes, and every way an approval can be wrong). One difference in
 * any of them (allowed, reason, tier, unresolved words, clarification, argument problems) fails the build.
 */
class AuthorizeParityTest {
    private val registry = loadRegistry()
    private val data = JSONObject(File(fixtures(), "authorize-cases.json").readText())

    private fun JSONArray.strings() = (0 until length()).map { getString(it) }
    private fun JSONObject.stringOrNull(key: String) = if (isNull(key)) null else getString(key)
    private fun JSONObject.doubleOrNull(key: String) = if (isNull(key)) null else getDouble(key)

    private fun entity(o: JSONObject) = Entity(
        o.getString("slot"), o.getString("phrase"), Resolution.of(o.getString("resolution")),
        o.doubleOrNull("score"), o.doubleOrNull("margin"), o.getJSONArray("candidates").strings(),
    )

    private val now = Instant.parse(data.getString("now"))

    @Test fun the_fixture_was_written_for_this_registry() {
        assertEquals(data.getInt("registry_revision"), registry.revision)
    }

    @Test fun every_case_gets_the_same_decision_as_the_python_authorize() {
        val cases = data.getJSONArray("cases")
        assertTrue("fixture should be large", cases.length() > 900)
        for (i in 0 until cases.length()) {
            val case = cases.getJSONObject(i)
            val p = case.getJSONObject("proposal")
            val proposal = Proposal(
                proposalId = p.getString("proposal_id"),
                capability = p.getString("capability"),
                args = Json.toMap(p.getJSONObject("args")),
                entities = (0 until p.getJSONArray("entities").length()).map { entity(p.getJSONArray("entities").getJSONObject(it)) },
                unresolvedTerms = p.getJSONArray("unresolved_terms").strings(),
                originDevice = p.getString("origin_device"),
                targetDevice = p.getString("target_device"),
                hostedOrigin = p.getBoolean("hosted_origin"),
            )
            val s = case.getJSONObject("state")
            val approval = if (s.isNull("approval")) null else s.getJSONObject("approval").let {
                Approval(
                    it.getString("proposal_id"), it.getString("args_hash"), it.getString("target_device"),
                    it.getString("user"), it.getString("via"), now.plusSeconds(it.getLong("expires_in_s")),
                )
            }
            val consent = Json.toMap(s.getJSONObject("consent")).mapValues { it.value as Boolean }
            val scopes = if (s.isNull("device_scopes")) null else s.getJSONArray("device_scopes").strings().toSet()

            val got = authorize(proposal, AuthState(now, approval, "owner", consent, scopes), registry)

            val want = case.getJSONObject("expected")
            val label = "case ${case.getString("id")} ${p.getString("capability")}"
            assertEquals(label, want.getBoolean("allowed"), got.allowed)
            assertEquals(label, want.getString("reason"), got.reason)
            assertEquals(label, want.stringOrNull("tier"), got.tier)
            assertEquals(label, want.getJSONArray("unresolved").strings(), got.unresolved)
            // `problems` is documented as "for logs and tests, not in the contract" (authorize.py): its order
            // follows Python dict iteration, which `org.json.JSONObject` does not preserve across the JSON
            // round trip. Compare content, not order.
            assertEquals(label, want.getJSONArray("problems").strings().sorted(), got.problems.sorted())
            val wantClarification = if (want.isNull("clarification")) null else Json.toMap(want.getJSONObject("clarification"))
            assertEquals(label, wantClarification, got.clarification)
        }
    }

    @Test fun canonical_arguments_and_their_hash_equal_the_python_ones() {
        val hashes = data.getJSONArray("hashes")
        for (i in 0 until hashes.length()) {
            val row = hashes.getJSONObject(i)
            val args = Json.toMap(row.getJSONObject("args"))
            assertEquals(row.getString("canonical"), canonicalArgs(args))
            assertEquals(row.getString("canonical"), row.getString("hash"), argsHash(args))
        }
    }

    // ---- invariants that do not depend on the fixture

    @Test fun the_decision_is_pure_the_same_inputs_give_the_same_answer() {
        val proposal = Proposal("p-1", "finance.summary", mapOf("period" to "month"))
        val state = AuthState(now)
        assertEquals(authorize(proposal, state, registry), authorize(proposal, state, registry))
    }

    @Test fun a_spoken_yes_never_approves_a_t2_action() {
        val args = mapOf<String, Any?>("amount" to 12, "currency" to "USD", "category" to "x", "note" to "y")
        val proposal = Proposal("p-1", "finance.add_transaction", args)
        for (via in listOf("speech", "voice", "yes", "", "SPEECH")) {
            val approval = Approval("p-1", argsHash(args), "local", "owner", via, now.plusSeconds(60))
            val decision = authorize(proposal, AuthState(now, approval), registry)
            assertFalse(via, decision.allowed)
            assertEquals(via, "APPROVAL_REQUIRED", decision.reason)
        }
        val click = Approval("p-1", argsHash(args), "local", "owner", "tap", now.plusSeconds(60))
        assertTrue(authorize(proposal, AuthState(now, click), registry).allowed)
    }

    @Test fun nothing_forbidden_exists_and_the_loader_refuses_to_register_it() {
        for (prefix in registry.forbiddenPrefixes) {
            assertTrue("no capability starts with $prefix", registry.names.none { it.lowercase().startsWith(prefix) })
        }
        for (name in listOf("finance.pay", "finance.transfer", "finance.purchase", "finance.bank_login", "health.dose", "shell.run", "files.delete", "email.send")) {
            val decision = authorize(Proposal("p", name, emptyMap()), AuthState(now), registry)
            assertEquals(name, "FORBIDDEN_CAPABILITY", decision.reason)
        }
        val doc = JSONObject(File(contracts(), "capability-registry.v2.json").readText())
        doc.getJSONArray("capabilities").put(
            JSONObject().put("capability", "shell.run").put("device", "any").put("tier", "T0").put("confirm_on", JSONObject.NULL)
                .put("idempotent", true).put("evidence_kind", "none")
                .put("args_schema", JSONObject().put("type", "object")),
        )
        try {
            Registry(doc)
            fail("a forbidden capability must not load")
        } catch (e: IllegalArgumentException) {
            assertTrue(e.message!!.contains("forbidden"))
        }
    }

    @Test fun every_t2_capability_says_where_it_is_confirmed() {
        for (name in registry.names) {
            val c = registry[name]!!
            if (c.tier == Tier.T2) assertTrue(name, c.confirmOn == "origin" || c.confirmOn == "target")
        }
        assertNotNull(registry["finance.add_transaction"])
        assertNull(registry["finance.pay"])
    }

    @Test fun a_schema_keyword_the_validator_does_not_enforce_is_a_load_error() {
        val doc = JSONObject(File(contracts(), "capability-registry.v2.json").readText())
        doc.getJSONArray("capabilities").getJSONObject(0).getJSONObject("args_schema").put("oneOf", JSONArray())
        try {
            Registry(doc)
            fail("an unsupported keyword must not load")
        } catch (e: IllegalArgumentException) {
            assertTrue(e.message!!.contains("not supported"))
        }
    }
}
