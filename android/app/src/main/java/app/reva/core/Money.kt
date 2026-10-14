package app.reva.core

import java.util.Locale

/**
 * Money as integer minor units plus an ISO 4217 code, formatted the same way on every device
 * (point decimals, comma thousands, locale-independent). Parsing refuses to round.
 * Mirrors the Windows app's MoneyFormat so both show the same text for the same number.
 */
object Money {
    const val MAX_ABS_MINOR: Long = 1_000_000_000_000_000L // 10^15, same bound as the Kernel

    private val ZERO_DECIMALS = setOf(
        "BIF", "CLP", "DJF", "GNF", "ISK", "JPY", "KMF", "KRW", "PYG", "RWF", "UGX", "UYI", "VND", "VUV", "XAF", "XOF", "XPF",
    )
    private val THREE_DECIMALS = setOf("BHD", "IQD", "JOD", "KWD", "LYD", "OMR", "TND")
    private val SYMBOLS = mapOf("USD" to "$", "EUR" to "€", "GBP" to "£", "INR" to "₹", "JPY" to "¥")

    fun exponent(currency: String): Int = when (currency) {
        in ZERO_DECIMALS -> 0
        in THREE_DECIMALS -> 3
        else -> 2
    }

    fun symbol(currency: String): String = SYMBOLS[currency] ?: "$currency "

    /** "$1,234.56", "-$12.00". With [showPlus], positive values start with "+". */
    fun format(minor: Long, currency: String, showPlus: Boolean = false): String {
        val exponent = exponent(currency)
        val negative = minor < 0
        // Magnitude as an unsigned value so Long.MIN_VALUE cannot overflow.
        val magnitude = if (negative) (-(minor + 1)).toULong() + 1UL else minor.toULong()
        var divisor = 1UL
        repeat(exponent) { divisor *= 10UL }
        val whole = if (exponent == 0) magnitude else magnitude / divisor
        val fraction = if (exponent == 0) 0UL else magnitude % divisor
        val sign = if (negative) "-" else if (showPlus && minor > 0) "+" else ""
        val grouped = String.format(Locale.ROOT, "%,d", whole.toLong())
        val tail = if (exponent > 0) "." + fraction.toString().padStart(exponent, '0') else ""
        return sign + symbol(currency) + grouped + tail
    }

    sealed interface Parsed {
        data class Ok(val minor: Long) : Parsed
        data class Error(val message: String) : Parsed
    }

    /**
     * Parse what a person types: "12", "12.5", "-12.50", "$1,234.50". Anything ambiguous or lossy is
     * refused with a short message rather than guessed.
     */
    fun parse(text: String?, currency: String): Parsed {
        var value = (text ?: "").trim()
        if (value.isEmpty()) return Parsed.Error("Enter an amount.")

        var negative = false
        if (value.startsWith("(") && value.endsWith(")")) {
            negative = true
            value = value.substring(1, value.length - 1).trim()
        }
        if (value.startsWith("-")) {
            negative = !negative
            value = value.substring(1).trim()
        } else if (value.startsWith("+")) {
            value = value.substring(1).trim()
        }

        value = value.replace(symbol(currency).trim(), "").trim()
        for (s in listOf("$", "€", "£", "₹", "¥")) value = value.replace(s, "")

        if (Regex("^\\d+,\\d{1,2}$").matches(value)) return Parsed.Error("Use a point for decimals, for example 12.50.")

        value = value.replace(",", "").replace(" ", "")
        if (value.isEmpty() || value.count { it == '.' } > 1 || value.any { it !in '0'..'9' && it != '.' }) {
            return Parsed.Error("That is not a valid amount.")
        }

        val parts = value.split('.')
        val whole = parts[0].ifEmpty { "0" }
        var fraction = if (parts.size > 1) parts[1] else ""
        val exponent = exponent(currency)
        if (fraction.length > exponent && fraction.substring(exponent).any { it != '0' }) {
            return Parsed.Error(
                if (exponent == 0) "$currency has no decimal places." else "At most $exponent decimal places for $currency.",
            )
        }
        fraction = if (fraction.length > exponent) fraction.substring(0, exponent) else fraction.padEnd(exponent, '0')
        val digits = (whole + fraction).trimStart('0')
        if (digits.isEmpty()) return Parsed.Ok(0)
        val magnitude = digits.takeIf { it.length <= 16 }?.toLongOrNull()
        if (magnitude == null || magnitude > MAX_ABS_MINOR) return Parsed.Error("That amount is too large.")
        return Parsed.Ok(if (negative) -magnitude else magnitude)
    }
}
