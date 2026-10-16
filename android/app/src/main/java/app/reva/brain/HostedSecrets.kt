package app.reva.brain

import android.util.AtomicFile
import app.reva.data.AndroidKeystoreWrapper
import app.reva.data.KeyWrapper
import java.io.File

interface SecretBlobStore {
    fun read(): ByteArray?
    fun write(blob: ByteArray)
    fun clear()
}

/** Ciphertext lives in noBackupFilesDir; Android Keystore holds the non-exportable wrapping key. */
class AndroidSecretBlobStore(file: File) : SecretBlobStore {
    private val atomic = AtomicFile(file)

    override fun read(): ByteArray? = try {
        if (!atomic.baseFile.exists()) null else atomic.openRead().use { it.readBytes() }
    } catch (_: Exception) {
        null
    }

    override fun write(blob: ByteArray) {
        atomic.baseFile.parentFile?.mkdirs()
        val output = atomic.startWrite()
        try {
            output.write(blob)
            atomic.finishWrite(output)
        } catch (e: Exception) {
            atomic.failWrite(output)
            throw e
        }
    }

    override fun clear() = atomic.delete()
}

class HostedSecrets(
    private val blobs: SecretBlobStore,
    wrapper: KeyWrapper? = null,
) {
    private val wrapper: KeyWrapper by lazy { wrapper ?: AndroidKeystoreWrapper() }
    /** Reads only when preparing an opted-in request; failures mean no usable key. */
    fun read(): String? = try {
        val blob = blobs.read() ?: return null
        wrapper.unwrap(ALIAS, blob).toString(Charsets.UTF_8).takeIf { it.isNotBlank() }
    } catch (_: Exception) {
        null
    }

    fun configured(): Boolean = read() != null

    fun save(key: String) {
        require(key.isNotBlank() && key.length <= 512) { "Enter a provider API key." }
        val bytes = key.trim().toByteArray(Charsets.UTF_8)
        try {
            blobs.write(wrapper.wrap(ALIAS, bytes))
        } finally {
            bytes.fill(0)
        }
    }

    fun clear() = blobs.clear()

    private companion object { const val ALIAS = "hosted_anthropic" }
}
