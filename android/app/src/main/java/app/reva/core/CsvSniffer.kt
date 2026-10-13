package app.reva.core

import java.nio.ByteBuffer
import java.nio.charset.CharacterCodingException
import java.nio.charset.CodingErrorAction
import java.nio.charset.StandardCharsets
import java.time.LocalDate
import java.time.format.DateTimeFormatter
import java.time.format.DateTimeParseException
import java.util.Locale

data class CsvProbe(val delimiter: String, val headers: List<String>, val sampleRows: List<List<String>>)

data class CsvGuess(
    val date: String?,
    val description: String?,
    val amount: String?,
    val debit: String?,
    val credit: String?,
    val category: String?,
    val dateFormat: String,
    val dateFormatIsAmbiguous: Boolean,
    val decimalSeparator: String,
)

/**
 * Looks at the first lines of a bank CSV on the phone to propose a column mapping. It only proposes: the
 * person can change every choice, and the dry run shows how every row is read.
 */
object CsvSniffer {
    // (Kernel strftime format, java.time pattern)
    private val dateFormats = listOf(
        "%Y-%m-%d" to "uuuu-MM-dd",
        "%d/%m/%Y" to "d/M/uuuu",
        "%m/%d/%Y" to "M/d/uuuu",
        "%d-%m-%Y" to "d-M-uuuu",
        "%d.%m.%Y" to "d.M.uuuu",
        "%Y/%m/%d" to "uuuu/M/d",
        "%d %b %Y" to "d MMM uuuu",
        "%d/%m/%y" to "d/M/uu",
        "%m/%d/%y" to "M/d/uu",
    )

    val kernelDateFormats: List<String> = dateFormats.map { it.first }

    fun decodeText(data: ByteArray): String {
        var bytes = data
        if (bytes.size >= 3 && bytes[0] == 0xEF.toByte() && bytes[1] == 0xBB.toByte() && bytes[2] == 0xBF.toByte()) {
            bytes = bytes.copyOfRange(3, bytes.size)
        }
        return try {
            StandardCharsets.UTF_8.newDecoder()
                .onMalformedInput(CodingErrorAction.REPORT)
                .onUnmappableCharacter(CodingErrorAction.REPORT)
                .decode(ByteBuffer.wrap(bytes)).toString()
        } catch (_: CharacterCodingException) {
            String(bytes, StandardCharsets.ISO_8859_1)
        }
    }

    fun probe(data: ByteArray, sampleRows: Int = 8): CsvProbe? {
        val lines = decodeText(data).split('\n').map { it.trimEnd('\r') }.filter { it.isNotBlank() }.take(sampleRows + 1)
        if (lines.isEmpty()) return null
        val delimiter = listOf(',', ';', '\t', '|').maxByOrNull { countOutsideQuotes(lines[0], it) }!!
        if (countOutsideQuotes(lines[0], delimiter) == 0) return null
        val parsed = lines.map { splitLine(it, delimiter) }
        return CsvProbe(delimiter.toString(), parsed[0], parsed.drop(1))
    }

    fun guess(probe: CsvProbe): CsvGuess {
        fun find(match: (String) -> Boolean): String? = probe.headers.firstOrNull { match(it.trim().lowercase(Locale.ROOT)) }

        val date = find { "posted" in it && "date" in it } ?: find { "date" in it }
        val description = find { it in setOf("description", "memo", "payee", "details", "narrative", "name", "merchant") }
            ?: find { "descr" in it || "memo" in it || "payee" in it || "detail" in it }
        var debit = find { "debit" in it || "withdrawal" in it || "money out" in it || "paid out" in it }
        var credit = find { "credit" in it || "deposit" in it || "money in" in it || "paid in" in it }
        val amount = find { "amount" in it && "debit" !in it && "credit" !in it }
        val category = find { "category" in it }
        if (amount != null) {
            debit = null
            credit = null
        }
        val (format, ambiguous) = guessDateFormat(probe, date)
        return CsvGuess(date, description, amount, debit, credit, category, format, ambiguous, guessDecimalSeparator(probe, amount ?: debit))
    }

    private fun guessDateFormat(probe: CsvProbe, dateColumn: String?): Pair<String, Boolean> {
        val index = if (dateColumn == null) -1 else probe.headers.indexOf(dateColumn)
        val samples = if (index < 0) emptyList() else probe.sampleRows.filter { index < it.size }.map { it[index].trim() }.filter { it.isNotEmpty() }
        if (samples.isEmpty()) return "%Y-%m-%d" to false
        val fits = dateFormats.filter { (_, pattern) ->
            val formatter = DateTimeFormatter.ofPattern(pattern, Locale.ENGLISH)
            samples.all {
                try {
                    LocalDate.parse(it, formatter)
                    true
                } catch (_: DateTimeParseException) {
                    false
                }
            }
        }.map { it.first }
        if (fits.isEmpty()) return "%Y-%m-%d" to false
        return fits[0] to ("%d/%m/%Y" in fits && "%m/%d/%Y" in fits)
    }

    private fun guessDecimalSeparator(probe: CsvProbe, amountColumn: String?): String {
        val index = if (amountColumn == null) -1 else probe.headers.indexOf(amountColumn)
        if (index < 0) return "."
        val commaDecimal = probe.sampleRows.filter { index < it.size }.map { it[index].trim() }
            .count { Regex("\\d,\\d{1,2}$").containsMatchIn(it) && '.' !in it }
        return if (commaDecimal > 0) "," else "."
    }

    private fun countOutsideQuotes(line: String, delimiter: Char): Int {
        var inQuotes = false
        var count = 0
        for (ch in line) {
            if (ch == '"') inQuotes = !inQuotes else if (ch == delimiter && !inQuotes) count++
        }
        return count
    }

    private fun splitLine(line: String, delimiter: Char): List<String> {
        val fields = mutableListOf<String>()
        val current = StringBuilder()
        var inQuotes = false
        var i = 0
        while (i < line.length) {
            val ch = line[i]
            when {
                inQuotes && ch == '"' && i + 1 < line.length && line[i + 1] == '"' -> {
                    current.append('"')
                    i++
                }
                inQuotes && ch == '"' -> inQuotes = false
                inQuotes -> current.append(ch)
                ch == '"' -> inQuotes = true
                ch == delimiter -> {
                    fields.add(current.toString())
                    current.clear()
                }
                else -> current.append(ch)
            }
            i++
        }
        fields.add(current.toString())
        return fields
    }
}
