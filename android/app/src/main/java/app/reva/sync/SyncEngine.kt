package app.reva.sync

import java.io.File
import java.io.IOException
import java.security.SecureRandom
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import uniffi.reva_kernel.DeviceSigner
import uniffi.reva_kernel.DomainException
import uniffi.reva_kernel.DomainHandle
import uniffi.reva_kernel.SignerException
import uniffi.reva_kernel.SyncBatch

/** The PC this phone is paired with. Public material only: no private key and no secret is kept here. */
data class PairedPc(
    val host: String,
    val port: Int,
    val tlsSha256: String,
    /** The id the PC gave this phone; sent with every request. */
    val deviceId: String,
    val pcSigningKey: ByteArray,
    val pcKernelId: String,
    val lastSyncAtSeconds: Long? = null,
)

enum class SyncFailure { Unauthorized, Unreachable, BadAnswer, Rejected, SyncOff, Other }

/** A refusal or failure with words that are safe to show: never keys, signatures or record contents. */
class SyncException(val failure: SyncFailure, override val message: String) : Exception(message)

data class PairingStart(val target: GatewayTarget, val sessionId: String, val fingerprint: String)

sealed interface PairPoll {
    data object Pending : PairPoll
    data class Approved(val pc: PairedPc) : PairPoll
    data object Denied : PairPoll
    data object Expired : PairPoll
}

data class SyncReport(
    val sentEvents: Long,
    val receivedEvents: Long,
    val applied: Long,
    val duplicates: Long,
    val conflicts: Int,
    val withheld: Long,
)

/** What the Devices screen needs. The real implementation is [SyncEngine]; tests use fakes. */
interface SyncService {
    suspend fun paired(): PairedPc?

    /** Reads a scanned or typed pairing code, contacts the PC and returns the digits to compare. */
    suspend fun startPairing(qrText: String): PairingStart

    suspend fun pollPairing(): PairPoll

    fun cancelPairing()

    suspend fun syncNow(): SyncReport

    /** Stops syncing with the PC on this phone. The PC's own list is changed on the PC. */
    suspend fun forget()
}

/** Remembers the paired PC in one small JSON file in noBackupFilesDir. */
class PairedPcStore(private val file: File) {
    fun load(): PairedPc? = try {
        val json = JSONObject(file.readText())
        PairedPc(
            host = json.getString("host"),
            port = json.getInt("port"),
            tlsSha256 = json.getString("tls_sha256"),
            deviceId = json.getString("device_id"),
            pcSigningKey = GatewayProtocol.b64uDecode(json.getString("pc_signing_key")),
            pcKernelId = json.getString("pc_kernel_id"),
            lastSyncAtSeconds = if (json.has("last_sync_at")) json.getLong("last_sync_at") else null,
        )
    } catch (e: Exception) {
        null // missing or damaged: treated as not paired; pairing again rewrites it
    }

    fun save(pc: PairedPc) {
        val json = JSONObject()
            .put("host", pc.host)
            .put("port", pc.port)
            .put("tls_sha256", pc.tlsSha256)
            .put("device_id", pc.deviceId)
            .put("pc_signing_key", GatewayProtocol.b64u(pc.pcSigningKey))
            .put("pc_kernel_id", pc.pcKernelId)
        pc.lastSyncAtSeconds?.let { json.put("last_sync_at", it) }
        file.parentFile?.mkdirs()
        val temp = File(file.parentFile, file.name + ".tmp")
        temp.writeText(json.toString())
        if (!temp.renameTo(file)) {
            file.delete()
            check(temp.renameTo(file)) { "could not save the paired PC" }
        }
    }

    fun clear() {
        file.delete()
    }
}

/**
 * Pairing and LAN sync with the PC gateway (docs/architecture/pairing-gateway.md). Blocking network and
 * Kernel calls run on [dispatcher]. Every request is signed with the Keystore device key; every answer is
 * checked against the PC's signing key; the TLS key is pinned from the QR code.
 */
class SyncEngine(
    private val kernel: () -> DomainHandle,
    private val signer: DeviceSigner,
    private val store: PairedPcStore,
    private val transport: GatewayTransport,
    private val deviceName: String,
    private val clockSeconds: () -> Long = { System.currentTimeMillis() / 1000 },
    private val dispatcher: CoroutineDispatcher = Dispatchers.IO,
    /** Called once after a sync that applied events from the PC, so open screens reload (SYNC-1e). */
    private val onApplied: () -> Unit = {},
) : SyncService {

    private class Pending(val target: GatewayTarget, val sessionId: String, val phoneKey: ByteArray)

    /** One sync at a time: a manual tap and the automatic sync never run over each other. */
    private val syncLock = Mutex()
    private val random = SecureRandom()
    private val lock = Any()
    private var pending: Pending? = null

    override suspend fun paired(): PairedPc? = withContext(dispatcher) { store.load() }

    override fun cancelPairing() {
        synchronized(lock) { pending = null }
    }

    override suspend fun startPairing(qrText: String): PairingStart = withContext(dispatcher) {
        val qr = try {
            GatewayProtocol.parseQr(qrText.trim())
        } catch (e: GatewayProtocol.BadQr) {
            throw SyncException(SyncFailure.Other, e.message ?: "This is not a REVA pairing code.")
        }
        if (qr.expiresAt <= clockSeconds()) {
            throw SyncException(SyncFailure.Other, "This pairing code has expired. Show a new one on the PC.")
        }
        if (!GatewayProtocol.isLocalNetworkHost(qr.host)) {
            throw SyncException(SyncFailure.Other, "This pairing code points outside your home network, so REVA will not connect to it.")
        }
        val target = GatewayTarget(qr.host, qr.port, qr.gatewaySha256)
        val handle = prepared()
        val phoneKey = publicKeyOrFail()
        val body = JSONObject()
            .put("code", qr.code)
            .put("name", deviceName.take(80).ifBlank { "Android phone" })
            .put("platform", "android")
            .put("public_key", GatewayProtocol.b64u(phoneKey))
            .put("kernel_devices", JSONObject().put("finance", handle.deviceId()))
            .put("proof", GatewayProtocol.b64u(signOrFail(GatewayProtocol.pairStartMessage(qr.code, qr.gatewaySha256))))
        val reply = send(target, "/pair/start", emptyMap(), body.toString().toByteArray())
        val json = jsonOrFail(reply)
        if (reply.status != 200) throw pairingRefusal(json.optString("error"))
        val sessionId = json.optString("session_id")
        if (sessionId.isEmpty()) throw SyncException(SyncFailure.BadAnswer, "The PC gave an answer REVA does not understand.")
        synchronized(lock) { pending = Pending(target, sessionId, phoneKey) }
        PairingStart(target, sessionId, GatewayProtocol.fingerprint(target.tlsSha256, phoneKey, sessionId))
    }

    override suspend fun pollPairing(): PairPoll = withContext(dispatcher) {
        val current = synchronized(lock) { pending } ?: throw SyncException(SyncFailure.Other, "No pairing is in progress.")
        val nonce = randomToken()
        val proof = signOrFail(GatewayProtocol.pairCompleteMessage(current.sessionId, nonce, current.target.tlsSha256))
        val body = JSONObject()
            .put("session_id", current.sessionId)
            .put("nonce", nonce)
            .put("proof", GatewayProtocol.b64u(proof))
        val reply = send(current.target, "/pair/complete", emptyMap(), body.toString().toByteArray())
        val json = jsonOrFail(reply)
        when (reply.status) {
            202 -> PairPoll.Pending
            200 -> {
                val pc = approvedPc(current, json)
                registerPc(pc)
                store.save(pc)
                synchronized(lock) { pending = null }
                PairPoll.Approved(pc)
            }
            403 -> if (json.optString("error") == "denied") {
                synchronized(lock) { pending = null }
                PairPoll.Denied
            } else {
                throw pairingRefusal(json.optString("error"))
            }
            410 -> {
                synchronized(lock) { pending = null }
                PairPoll.Expired
            }
            else -> throw pairingRefusal(json.optString("error"))
        }
    }

    private fun approvedPc(current: Pending, json: JSONObject): PairedPc {
        try {
            val gateway = json.getJSONObject("gateway")
            if (gateway.getString("tls_sha256") != current.target.tlsSha256) {
                throw SyncException(SyncFailure.BadAnswer, "The PC's key changed during pairing. Nothing was saved.")
            }
            return PairedPc(
                host = current.target.host,
                port = current.target.port,
                tlsSha256 = current.target.tlsSha256,
                deviceId = json.getString("device_id"),
                pcSigningKey = GatewayProtocol.b64uDecode(gateway.getString("signing_public_key")),
                pcKernelId = gateway.getJSONObject("kernel_devices").getString("finance"),
            )
        } catch (e: org.json.JSONException) {
            throw SyncException(SyncFailure.BadAnswer, "The PC gave an answer REVA does not understand.")
        } catch (e: IllegalArgumentException) {
            throw SyncException(SyncFailure.BadAnswer, "The PC gave an answer REVA does not understand.")
        }
    }

    /** Registers the PC as this phone's only Kernel peer. A re-pair revokes first, so the cursors restart at zero. */
    private fun registerPc(pc: PairedPc) {
        val handle = kernel()
        try {
            val existing = handle.listPeers().firstOrNull { it.deviceId == pc.pcKernelId }
            if (existing != null && existing.status == "active") handle.revokePeer(pc.pcKernelId)
            handle.registerPeer(pc.pcKernelId, pc.pcSigningKey, "Windows PC", listOf("finance"))
        } catch (e: DomainException) {
            throw SyncException(SyncFailure.Rejected, "REVA could not register your PC on this phone.")
        }
    }

    override suspend fun syncNow(): SyncReport = syncLock.withLock { syncLocked() }

    private suspend fun syncLocked(): SyncReport = withContext(dispatcher) {
        val pc = store.load() ?: throw SyncException(SyncFailure.Other, "This phone is not paired with a PC.")
        val handle = prepared()
        var sent = 0L
        var received = 0L
        var applied = 0L
        var duplicates = 0L
        var conflicts = 0
        var withheld = 0L
        try {
            for (round in 0 until MAX_ROUNDS) {
                val batch = handle.syncExport(pc.pcKernelId, BATCH.toUInt())
                if (batch.count == 0UL && batch.cursorTo == batch.cursorFrom) break
                val body = JSONObject()
                    .put("domain", DOMAIN)
                    .put("events_json", batch.eventsJson)
                    .put("cursor_from", batch.cursorFrom)
                    .put("cursor_to", batch.cursorTo)
                    .put("count", batch.count.toLong())
                val answer = signed(pc, "/sync/push", body)
                handle.syncAck(pc.pcKernelId, answer.getLong("ack_cursor"))
                sent += batch.count.toLong()
                conflicts += answer.optJSONArray("conflicts")?.length() ?: 0
                if (batch.count == 0UL) break
            }
            for (round in 0 until MAX_ROUNDS) {
                val answer = signed(pc, "/sync/pull", JSONObject().put("domain", DOMAIN).put("limit", BATCH))
                val directory = answer.optJSONArray("directory") ?: JSONArray()
                for (i in 0 until directory.length()) {
                    val entry = directory.getJSONObject(i)
                    handle.registerPeer(
                        entry.getString("device_id"),
                        GatewayProtocol.b64uDecode(entry.getString("public_key")),
                        entry.optString("label", "Another phone").take(80).ifBlank { "Another phone" },
                        listOf("finance"),
                    )
                }
                val cursorFrom = answer.getLong("cursor_from")
                val cursorTo = answer.getLong("cursor_to")
                val count = answer.getLong("count")
                withheld += answer.optLong("withheld", 0)
                if (count == 0L && cursorTo == cursorFrom) break
                val report = handle.syncApply(
                    pc.pcKernelId,
                    SyncBatch(answer.getString("events_json"), cursorFrom, cursorTo, count.toULong()),
                )
                signed(pc, "/sync/ack", JSONObject().put("domain", DOMAIN).put("cursor", cursorTo))
                received += count
                applied += report.applied.toLong()
                duplicates += report.duplicates.toLong()
                conflicts += report.conflicts.size
                if (count == 0L) break
            }
        } catch (e: DomainException) {
            throw SyncException(SyncFailure.Rejected, "The events from the PC were refused: they did not check out.")
        }
        store.save(pc.copy(lastSyncAtSeconds = clockSeconds()))
        // Open screens reload when events from the PC were applied (SYNC-1e).
        if (applied > 0 || conflicts > 0) onApplied()
        SyncReport(sent, received, applied, duplicates, conflicts, withheld)
    }

    override suspend fun forget() {
        withContext(dispatcher) {
            val pc = store.load()
            if (pc != null) {
                try {
                    kernel().revokePeer(pc.pcKernelId)
                } catch (_: DomainException) {
                    // already gone from the Kernel: forgetting is still complete
                }
            }
            store.clear()
            synchronized(lock) { pending = null }
        }
    }

    // ---- requests ---------------------------------------------------------------------------------------

    private fun prepared(): DomainHandle = kernel().also { it.setSigner(signer) }

    private fun publicKeyOrFail(): ByteArray = try {
        signer.publicKey()
    } catch (e: SignerException) {
        throw SyncException(SyncFailure.Other, "This phone's device key is not available.")
    }

    private fun signOrFail(message: ByteArray): ByteArray = try {
        signer.sign(message)
    } catch (e: SignerException) {
        throw SyncException(SyncFailure.Other, "This phone's device key is not available.")
    }

    private fun send(target: GatewayTarget, path: String, headers: Map<String, String>, body: ByteArray): HttpReply = try {
        transport.post(target, path, headers, body)
    } catch (e: IOException) {
        val pinned = e is javax.net.ssl.SSLException
        throw SyncException(
            SyncFailure.Unreachable,
            if (pinned) {
                "That is not the PC in the pairing code (its security key does not match). Nothing was sent."
            } else {
                "Could not reach your PC. Is it on, on the same Wi-Fi, with the gateway switched on?"
            },
        )
    }

    private fun jsonOrFail(reply: HttpReply): JSONObject = try {
        JSONObject(String(reply.body, Charsets.UTF_8))
    } catch (e: org.json.JSONException) {
        throw SyncException(SyncFailure.BadAnswer, "The PC gave an answer REVA does not understand.")
    }

    /** A signed request; returns the PC's JSON answer after checking its signature. */
    private fun signed(pc: PairedPc, path: String, json: JSONObject): JSONObject {
        val body = json.toString().toByteArray()
        val nonce = randomToken()
        val timestamp = clockSeconds()
        val signature = signOrFail(GatewayProtocol.requestMessage("POST", path, timestamp, nonce, body, pc.tlsSha256))
        val headers = mapOf(
            GatewayProtocol.HEADER_DEVICE to pc.deviceId,
            GatewayProtocol.HEADER_TIMESTAMP to timestamp.toString(),
            GatewayProtocol.HEADER_NONCE to nonce,
            GatewayProtocol.HEADER_SIGNATURE to GatewayProtocol.b64u(signature),
        )
        val reply = send(GatewayTarget(pc.host, pc.port, pc.tlsSha256), path, headers, body)
        if (reply.status != 200) throw refusal(reply)
        val answerSignature = reply.headers[GatewayProtocol.HEADER_RESPONSE_SIGNATURE.lowercase()]
        val genuine = answerSignature != null && try {
            GatewayProtocol.verify(pc.pcSigningKey, GatewayProtocol.responseMessage(nonce, reply.status, reply.body), GatewayProtocol.b64uDecode(answerSignature))
        } catch (e: IllegalArgumentException) {
            false
        }
        if (!genuine) throw SyncException(SyncFailure.BadAnswer, "The answer did not come from your paired PC. Nothing was applied.")
        return jsonOrFail(reply)
    }

    private fun refusal(reply: HttpReply): SyncException {
        val code = try {
            JSONObject(String(reply.body, Charsets.UTF_8)).optString("error")
        } catch (e: org.json.JSONException) {
            ""
        }
        return when {
            reply.status == 401 -> SyncException(
                SyncFailure.Unauthorized,
                "Your PC no longer accepts this phone. It may have been removed on the PC. Pair again to sync.",
            )
            code == "sync_disabled" -> SyncException(SyncFailure.SyncOff, "Finance sync is switched off on the PC.")
            reply.status == 429 -> SyncException(SyncFailure.Other, "The PC is busy. Try again in a minute.")
            reply.status == 403 -> SyncException(SyncFailure.Rejected, "The PC refused this sync.")
            else -> SyncException(SyncFailure.Other, "The PC could not complete the sync (code ${reply.status}).")
        }
    }

    private fun pairingRefusal(code: String): SyncException = SyncException(
        SyncFailure.Rejected,
        when (code) {
            "code_expired" -> "This pairing code has expired. Show a new one on the PC."
            "code_used" -> "This pairing code was already used. Show a new one on the PC."
            "code_invalid" -> "The pairing code was not accepted. Show a new one on the PC."
            "locked" -> "Too many wrong codes. Open pairing again on the PC."
            "no_open_pairing" -> "The PC is not waiting for a phone. Open pairing on the PC first."
            "denied" -> "The PC said no."
            "rate_limited" -> "The PC is busy. Try again in a minute."
            else -> "The PC did not accept the pairing."
        },
    )

    private fun randomToken(): String = GatewayProtocol.b64u(ByteArray(16).also(random::nextBytes))

    private companion object {
        const val DOMAIN = "finance"
        const val BATCH = 500
        const val MAX_ROUNDS = 20
    }
}
