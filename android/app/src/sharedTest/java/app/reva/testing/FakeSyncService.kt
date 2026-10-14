package app.reva.testing

import app.reva.sync.GatewayTarget
import app.reva.sync.PairPoll
import app.reva.sync.PairedPc
import app.reva.sync.PairingStart
import app.reva.sync.SyncException
import app.reva.sync.SyncReport
import app.reva.sync.SyncService

/** A scripted [SyncService] for view-model and Compose tests. It never touches a network, a key or the Kernel. */
class FakeSyncService : SyncService {
    var pc: PairedPc? = null
    var startError: SyncException? = null

    /** Each entry is a [PairPoll] to return or a [SyncException] to throw; an empty queue means Pending. */
    var polls = ArrayDeque<Any>()
    var syncResult: Any = SyncReport(1, 2, 2, 0, 0, 0)
    var started = 0
    var syncs = 0
    var cancelled = 0
    var forgotten = 0
    var lastQr: String? = null

    /** What "now" is when a sync succeeds; the paired PC's last-sync time is set to it. */
    var nowSeconds: () -> Long = { 1_000_000 }

    override suspend fun paired() = pc

    override suspend fun startPairing(qrText: String): PairingStart {
        started++
        lastQr = qrText
        startError?.let { throw it }
        return PairingStart(GatewayTarget("h", 1, "ab".repeat(32)), "session-1", "123456")
    }

    override suspend fun pollPairing(): PairPoll {
        val next = polls.removeFirstOrNull() ?: PairPoll.Pending
        if (next is SyncException) throw next
        if (next is PairPoll.Approved) pc = next.pc
        return next as PairPoll
    }

    override fun cancelPairing() {
        cancelled++
    }

    override suspend fun syncNow(): SyncReport {
        syncs++
        val result = syncResult
        if (result is SyncException) throw result
        pc = pc?.copy(lastSyncAtSeconds = nowSeconds())
        return result as SyncReport
    }

    override suspend fun forget() {
        forgotten++
        pc = null
    }

    companion object {
        val PC = PairedPc("192.168.1.20", 47821, "ab".repeat(32), "device-1", ByteArray(3), "kernel-pc-1", null)
    }
}
