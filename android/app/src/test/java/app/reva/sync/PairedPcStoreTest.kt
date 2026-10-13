package app.reva.sync

import java.io.File
import java.nio.file.Files
import org.junit.After
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

class PairedPcStoreTest {
    private lateinit var dir: File
    private lateinit var store: PairedPcStore
    private val pc = PairedPc("192.168.1.20", 47821, "ab".repeat(32), "01a13324-acf9", byteArrayOf(1, 2, 3, 4), "kernel-pc-1", 1_800_000_000)

    @Before fun setUp() {
        dir = Files.createTempDirectory("reva-sync-store-").toFile()
        store = PairedPcStore(File(dir, "sync/paired_pc.json"))
    }

    @After fun tearDown() {
        dir.deleteRecursively()
    }

    @Test fun nothing_saved_means_not_paired() = assertNull(store.load())

    @Test fun a_saved_pc_comes_back_whole() {
        store.save(pc)
        val loaded = store.load()!!
        assertEquals(pc.host, loaded.host)
        assertEquals(pc.port, loaded.port)
        assertEquals(pc.tlsSha256, loaded.tlsSha256)
        assertEquals(pc.deviceId, loaded.deviceId)
        assertArrayEquals(pc.pcSigningKey, loaded.pcSigningKey)
        assertEquals(pc.pcKernelId, loaded.pcKernelId)
        assertEquals(pc.lastSyncAtSeconds, loaded.lastSyncAtSeconds)
    }

    @Test fun updating_the_last_sync_replaces_the_record() {
        store.save(pc)
        store.save(pc.copy(lastSyncAtSeconds = 1_800_000_999))
        assertEquals(1_800_000_999L, store.load()!!.lastSyncAtSeconds)
        assertFalse("no temp file is left behind", File(dir, "sync/paired_pc.json.tmp").exists())
    }

    @Test fun a_damaged_file_reads_as_not_paired_instead_of_crashing() {
        store.save(pc)
        File(dir, "sync/paired_pc.json").writeText("{ not json")
        assertNull(store.load())
    }

    @Test fun clearing_forgets_the_pc() {
        store.save(pc)
        store.clear()
        assertNull(store.load())
    }

    @Test fun the_record_holds_public_material_only() {
        store.save(pc)
        val text = File(dir, "sync/paired_pc.json").readText()
        for (secret in listOf("private", "secret", "password", "token", "bearer")) {
            assertFalse("the file must not mention '$secret'", text.lowercase().contains(secret))
        }
        assertTrue(text.contains("tls_sha256") && text.contains("pc_signing_key"))
    }
}
