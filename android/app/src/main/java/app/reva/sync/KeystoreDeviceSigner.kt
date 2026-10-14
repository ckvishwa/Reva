package app.reva.sync

import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.security.keystore.StrongBoxUnavailableException
import java.security.GeneralSecurityException
import java.security.KeyPairGenerator
import java.security.KeyStore
import java.security.PrivateKey
import java.security.ProviderException
import java.security.Signature
import java.security.spec.ECGenParameterSpec
import uniffi.reva_kernel.DeviceSigner
import uniffi.reva_kernel.SignerException

/**
 * This phone's device key: a P-256 key pair in the Android Keystore (StrongBox when the phone has it). The
 * private key never leaves the Keystore; the Kernel only asks it to sign. EC is used because the Keystore
 * supports Ed25519 only from API 33 and this app supports API 31.
 *
 * [publicKey] is X.509 SubjectPublicKeyInfo DER; [sign] is ECDSA over SHA-256, DER encoded: exactly what the
 * Kernel's verifier and the PC gateway expect.
 */
class KeystoreDeviceSigner(private val alias: String = ALIAS) : DeviceSigner {
    private val keyStore: KeyStore = KeyStore.getInstance(PROVIDER).apply { load(null) }

    @Synchronized
    override fun publicKey(): ByteArray = try {
        ensureKey()
        keyStore.getCertificate(alias).publicKey.encoded
    } catch (e: GeneralSecurityException) {
        throw SignerException.Unavailable("the device key could not be read")
    }

    @Synchronized
    override fun sign(message: ByteArray): ByteArray = try {
        ensureKey()
        val key = keyStore.getKey(alias, null) as? PrivateKey ?: throw GeneralSecurityException("device key missing")
        Signature.getInstance("SHA256withECDSA").run {
            initSign(key)
            update(message)
            sign()
        }
    } catch (e: GeneralSecurityException) {
        throw SignerException.Unavailable("the device key could not sign")
    }

    /** Removes the key (used by tests and when all pairing is forgotten). */
    @Synchronized
    fun delete() {
        if (keyStore.containsAlias(alias)) keyStore.deleteEntry(alias)
    }

    private fun ensureKey() {
        if (keyStore.containsAlias(alias)) return
        try {
            generate(strongBox = true)
        } catch (_: StrongBoxUnavailableException) {
            generate(strongBox = false)
        } catch (_: ProviderException) {
            generate(strongBox = false) // some phones report a missing StrongBox this way
        }
    }

    private fun generate(strongBox: Boolean) {
        val spec = KeyGenParameterSpec.Builder(alias, KeyProperties.PURPOSE_SIGN)
            .setAlgorithmParameterSpec(ECGenParameterSpec("secp256r1"))
            .setDigests(KeyProperties.DIGEST_SHA256)
            .setIsStrongBoxBacked(strongBox)
            .build()
        KeyPairGenerator.getInstance(KeyProperties.KEY_ALGORITHM_EC, PROVIDER).apply { initialize(spec) }.generateKeyPair()
    }

    companion object {
        const val ALIAS = "reva.device.signing"
        private const val PROVIDER = "AndroidKeyStore"
    }
}
