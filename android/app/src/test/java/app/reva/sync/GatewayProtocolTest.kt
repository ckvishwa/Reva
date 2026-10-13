package app.reva.sync

import org.json.JSONObject
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test

/**
 * The phone's wire format against vectors written by the Python reference (reva_core/gateway/protocol.py) via
 * tools/android/gen_protocol_vectors.py. If either side changes a byte of a signed string, this fails.
 */
class GatewayProtocolTest {
    private val vectors: JSONObject = JSONObject(
        checkNotNull(javaClass.getResourceAsStream("/protocol_vectors.json")) { "protocol_vectors.json missing" }
            .readBytes().toString(Charsets.UTF_8),
    )

    private fun text(bytes: ByteArray) = String(bytes, Charsets.UTF_8)

    @Test fun base64url_matches_python_with_no_padding() {
        val rows = vectors.getJSONArray("b64u")
        for (i in 0 until rows.length()) {
            val row = rows.getJSONObject(i)
            val bytes = GatewayProtocol.hexBytes(row.getString("hex"))
            assertEquals(row.getString("b64u"), GatewayProtocol.b64u(bytes))
            assertArrayEquals(bytes, GatewayProtocol.b64uDecode(row.getString("b64u")))
        }
        try {
            GatewayProtocol.b64uDecode("not base64 !!")
            fail("expected a refusal")
        } catch (_: IllegalArgumentException) {
        }
    }

    @Test fun the_key_hash_matches() {
        val spki = vectors.getJSONObject("spki")
        assertEquals(spki.getString("sha256"), GatewayProtocol.spkiSha256(GatewayProtocol.b64uDecode(spki.getString("b64u"))))
    }

    @Test fun the_six_digit_fingerprint_matches_python() {
        val rows = vectors.getJSONArray("fingerprint")
        for (i in 0 until rows.length()) {
            val row = rows.getJSONObject(i)
            val digits = GatewayProtocol.fingerprint(
                row.getString("gw"),
                GatewayProtocol.b64uDecode(row.getString("spki_b64u")),
                row.getString("session"),
            )
            assertEquals(row.getString("expected"), digits)
            assertEquals(6, digits.length)
        }
        assertTrue(
            "another session gives other digits",
            rows.getJSONObject(0).getString("expected") != rows.getJSONObject(1).getString("expected"),
        )
    }

    @Test fun every_signed_string_is_byte_identical_to_python() {
        val m = vectors.getJSONObject("messages")
        val gw = m.getString("gateway")
        assertEquals(m.getString("pair_start"), text(GatewayProtocol.pairStartMessage(m.getString("code"), gw)))
        assertEquals(
            m.getString("pair_complete"),
            text(GatewayProtocol.pairCompleteMessage(m.getString("session"), m.getString("nonce"), gw)),
        )
        val request = m.getJSONObject("request")
        assertEquals(
            request.getString("text"),
            text(
                GatewayProtocol.requestMessage(
                    request.getString("method"),
                    request.getString("path"),
                    request.getLong("timestamp"),
                    m.getString("nonce"),
                    request.getString("body").toByteArray(),
                    gw,
                ),
            ),
        )
        val response = m.getJSONObject("response")
        assertEquals(
            response.getString("text"),
            text(GatewayProtocol.responseMessage(m.getString("nonce"), response.getInt("status"), response.getString("body").toByteArray())),
        )
    }

    @Test fun a_signature_made_by_python_verifies_and_any_change_breaks_it() {
        val s = vectors.getJSONObject("signature")
        val key = GatewayProtocol.b64uDecode(s.getString("public_b64u"))
        val message = s.getString("message").toByteArray()
        val signature = GatewayProtocol.b64uDecode(s.getString("signature_b64u"))
        assertTrue(GatewayProtocol.verify(key, message, signature))
        assertFalse(GatewayProtocol.verify(key, message + 1, signature))
        val flipped = signature.copyOf().also { it[it.size - 1] = (it[it.size - 1].toInt() xor 1).toByte() }
        assertFalse(GatewayProtocol.verify(key, message, flipped))
        assertFalse(GatewayProtocol.verify(key, message, byteArrayOf(1, 2, 3)))
        assertFalse(GatewayProtocol.verify(byteArrayOf(1, 2, 3), message, signature))
    }

    @Test fun the_qr_text_parses_to_what_python_wrote() {
        val qr = vectors.getJSONObject("qr")
        val payload = qr.getJSONObject("payload")
        val parsed = GatewayProtocol.parseQr(qr.getString("text"))
        assertEquals(payload.getString("host"), parsed.host)
        assertEquals(payload.getInt("port"), parsed.port)
        assertEquals(payload.getString("code"), parsed.code)
        assertEquals(payload.getString("gw"), parsed.gatewaySha256)
        assertEquals(payload.getLong("exp"), parsed.expiresAt)
    }

    @Test fun only_addresses_on_the_local_network_are_accepted_for_pairing() {
        for (ok in listOf("192.168.1.20", "10.0.0.5", "172.16.0.1", "172.31.255.254", "169.254.3.4", "127.0.0.1", "localhost", "my-pc.local", "::1", "fd12:3456:789a::1", "fe80::1")) {
            assertTrue("$ok should be local", GatewayProtocol.isLocalNetworkHost(ok))
        }
        for (bad in listOf("8.8.8.8", "172.32.0.1", "172.15.0.1", "192.169.1.1", "11.0.0.1", "300.1.1.1", "example.com", "evil.local.example.com", ".local", "2001:4860:4860::8888", "", "192.168.1", "192.168.1.1.1", "http://192.168.1.2")) {
            assertFalse("$bad must be refused", GatewayProtocol.isLocalNetworkHost(bad))
        }
    }

    @Test fun malformed_qr_texts_are_refused() {
        val bad = vectors.getJSONObject("qr").getJSONArray("bad_texts")
        for (i in 0 until bad.length()) {
            try {
                GatewayProtocol.parseQr(bad.getString(i))
                fail("accepted ${bad.getString(i)}")
            } catch (_: GatewayProtocol.BadQr) {
            }
        }
        fun encode(json: String) = GatewayProtocol.QR_PREFIX + GatewayProtocol.b64u(json.toByteArray())
        val code = "a".repeat(22)
        val gw = "0".repeat(64)
        val good = """{"v":1,"host":"192.168.1.5","port":47821,"code":"$code","gw":"$gw","exp":5}"""
        GatewayProtocol.parseQr(encode(good))
        val broken = listOf(
            good.replace("\"v\":1", "\"v\":2"),
            good.replace("47821", "70000"),
            good.replace("47821", "0"),
            good.replace(code, "short"),
            good.replace(gw, "G".repeat(64)),
            good.replace(",\"exp\":5", ""),
            good.replace("}", ",\"extra\":1}"),
            good.replace("\"host\":\"192.168.1.5\"", "\"host\":\"\""),
        )
        for (candidate in broken) {
            try {
                GatewayProtocol.parseQr(encode(candidate))
                fail("accepted $candidate")
            } catch (_: GatewayProtocol.BadQr) {
            }
        }
    }
}
