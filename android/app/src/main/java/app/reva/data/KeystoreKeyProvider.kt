package app.reva.data

import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.security.keystore.StrongBoxUnavailableException
import java.io.File
import java.io.FileOutputStream
import java.security.GeneralSecurityException
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec
import uniffi.reva_kernel.KeyProvider
import uniffi.reva_kernel.KeyProviderException

/** Wraps and unwraps a small secret with a key that never leaves secure hardware or the OS key store. */
interface KeyWrapper {
    /** Returns IV + ciphertext. */
    fun wrap(domain: String, secret: ByteArray): ByteArray

    /** Throws [GeneralSecurityException] if the wrapping key is gone or the blob does not authenticate. */
    fun unwrap(domain: String, blob: ByteArray): ByteArray
}

/**
 * The Kernel's [KeyProvider] on Android. The Kernel generates a random 256-bit database key on a fresh
 * install and hands it to [storeKey]; this class wraps it with an Android Keystore AES-GCM key (StrongBox when
 * the phone has it) and keeps only the wrapped blob, in [directory], which must be under noBackupFilesDir.
 *
 * Fail closed: a missing or unusable wrapping key is an error, never "no key", and an existing blob is never
 * overwritten, so data cannot silently be orphaned by a fresh key.
 */
class KeystoreKeyProvider(
    private val directory: File,
    private val wrapper: KeyWrapper = AndroidKeystoreWrapper(),
) : KeyProvider {

    override fun loadKey(domain: String): ByteArray? {
        val file = fileFor(domain)
        if (!file.exists()) return null
        val blob = try {
            file.readBytes()
        } catch (e: java.io.IOException) {
            throw KeyProviderException.Unavailable("the wrapped key could not be read")
        }
        return try {
            wrapper.unwrap(domain, blob)
        } catch (e: GeneralSecurityException) {
            throw KeyProviderException.Unavailable("the Keystore key no longer opens the stored key")
        }
    }

    override fun storeKey(domain: String, key: ByteArray) {
        val file = fileFor(domain)
        if (file.exists()) throw KeyProviderException.Unavailable("a key is already stored; refusing to replace it")
        val blob = try {
            wrapper.wrap(domain, key)
        } catch (e: GeneralSecurityException) {
            throw KeyProviderException.Unavailable("the Keystore could not wrap the key")
        }
        directory.mkdirs()
        val temp = File(directory, "$domain.key.tmp")
        try {
            FileOutputStream(temp).use {
                it.write(blob)
                it.fd.sync()
            }
            if (!temp.renameTo(file)) throw java.io.IOException("rename failed")
        } catch (e: java.io.IOException) {
            temp.delete()
            throw KeyProviderException.Unavailable("the wrapped key could not be saved")
        }
    }

    private fun fileFor(domain: String): File {
        require(domain.isNotEmpty() && domain.all { it in 'a'..'z' || it in '0'..'9' || it == '_' }) { "bad domain name" }
        return File(directory, "$domain.key")
    }
}

class AndroidKeystoreWrapper : KeyWrapper {
    private val keyStore: KeyStore = KeyStore.getInstance(PROVIDER).apply { load(null) }

    override fun wrap(domain: String, secret: ByteArray): ByteArray {
        val cipher = Cipher.getInstance(TRANSFORMATION)
        cipher.init(Cipher.ENCRYPT_MODE, existingOrNewKey(domain))
        return cipher.iv + cipher.doFinal(secret)
    }

    override fun unwrap(domain: String, blob: ByteArray): ByteArray {
        if (blob.size <= IV_BYTES) throw GeneralSecurityException("stored blob is too short")
        val key = keyStore.getKey(alias(domain), null) as? SecretKey
            ?: throw GeneralSecurityException("Keystore key is missing")
        val cipher = Cipher.getInstance(TRANSFORMATION)
        cipher.init(Cipher.DECRYPT_MODE, key, GCMParameterSpec(TAG_BITS, blob, 0, IV_BYTES))
        return cipher.doFinal(blob, IV_BYTES, blob.size - IV_BYTES)
    }

    private fun existingOrNewKey(domain: String): SecretKey {
        (keyStore.getKey(alias(domain), null) as? SecretKey)?.let { return it }
        return try {
            generate(domain, strongBox = true)
        } catch (_: StrongBoxUnavailableException) {
            generate(domain, strongBox = false)
        }
    }

    private fun generate(domain: String, strongBox: Boolean): SecretKey {
        val spec = KeyGenParameterSpec.Builder(alias(domain), KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
            .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
            .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
            .setKeySize(256)
            .setRandomizedEncryptionRequired(true)
            .setIsStrongBoxBacked(strongBox)
            .build()
        return KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, PROVIDER).apply { init(spec) }.generateKey()
    }

    private fun alias(domain: String) = "reva.domain.$domain"

    private companion object {
        const val PROVIDER = "AndroidKeyStore"
        const val TRANSFORMATION = "AES/GCM/NoPadding"
        const val IV_BYTES = 12
        const val TAG_BITS = 128
    }
}
