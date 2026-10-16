package app.reva.policy

import org.json.JSONArray
import org.json.JSONObject
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.OffsetDateTime
import java.time.format.DateTimeParseException

enum class Tier { T0, T1, T2, T3 }

class Capability(
    val name: String,
    val device: String,
    val tier: Tier,
    /** "origin" or "target" for T2, else null. */
    val confirmOn: String?,
    val idempotent: Boolean,
    val evidenceKind: String,
    val argsSchema: Map<String, Any?>,
) {
    /** The life domain the capability belongs to (`finance`, `health`, ...), if any. */
    val domain: String? get() = name.substringBefore('.').takeIf { it in DOMAINS }

    companion object {
        val DOMAINS = setOf("memory", "finance", "health", "coach", "career", "learn", "cyber", "personal")
    }
}

/**
 * The capability registry (ARD-600 section 2, ADR-033), ported from `reva_core/policy/registry.py`. It loads the
 * same `contracts/capability-registry.v2.json` the PC does (copied into the APK at build time). The tier of a
 * capability comes only from here, never from a model, a network hint or an argument. Names that start with a
 * forbidden prefix (payments, transfers, shell, file deletion, sending email, ...) are refused by name even
 * though they are not in the registry, and the loader refuses a registry that tries to contain one.
 */
class Registry(document: JSONObject) {
    val revision: Int = document.getInt("registry_revision")
    val forbiddenPrefixes: List<String> = strings(document.getJSONArray("forbidden_capability_prefixes"))
    private val capabilities = LinkedHashMap<String, Capability>()

    init {
        val entries = document.getJSONArray("capabilities")
        for (i in 0 until entries.length()) {
            val entry = entries.getJSONObject(i)
            val schema = Json.toMap(entry.getJSONObject("args_schema"))
            Schema.checkSupported(schema)
            val capability = Capability(
                name = entry.getString("capability"),
                device = entry.getString("device"),
                tier = Tier.valueOf(entry.getString("tier")),
                confirmOn = if (entry.isNull("confirm_on")) null else entry.getString("confirm_on"),
                idempotent = entry.getBoolean("idempotent"),
                evidenceKind = entry.getString("evidence_kind"),
                argsSchema = schema,
            )
            require(capability.name !in capabilities) { "duplicate capability ${capability.name}" }
            require(!isForbidden(capability.name)) { "${capability.name} is a forbidden capability and cannot be registered" }
            require(capability.tier != Tier.T2 || capability.confirmOn in setOf("origin", "target")) {
                "${capability.name}: a T2 capability must say where it is confirmed"
            }
            capabilities[capability.name] = capability
        }
    }

    operator fun get(name: String): Capability? = capabilities[name]
    val names: List<String> get() = capabilities.keys.toList()
    operator fun contains(name: String) = name in capabilities

    fun isForbidden(name: String): Boolean {
        val lowered = name.lowercase()
        return forbiddenPrefixes.any { lowered.startsWith(it) }
    }

    fun validateArgs(capability: Capability, args: Any?): List<String> {
        if (args !is Map<*, *>) return listOf("$: arguments must be an object")
        return Schema.validate(args, capability.argsSchema)
    }

    private fun strings(array: JSONArray) = (0 until array.length()).map { array.getString(it) }
}

/** org.json to plain Kotlin maps and lists, so the rest of the policy code does not depend on org.json. */
object Json {
    fun toMap(o: JSONObject): Map<String, Any?> = o.keys().asSequence().associateWith { toValue(o.get(it)) }

    fun toValue(v: Any?): Any? = when (v) {
        is JSONObject -> toMap(v)
        is JSONArray -> (0 until v.length()).map { toValue(v.get(it)) }
        JSONObject.NULL -> null
        // Newer org.json parses decimals as BigDecimal and big integers as BigInteger; keep plain Kotlin numbers.
        is java.math.BigDecimal -> v.toDouble()
        is java.math.BigInteger -> if (v.bitLength() < 63) v.toLong() else v.toDouble()
        else -> v
    }
}

/**
 * A small, strict JSON Schema subset for capability arguments (AR-AGT-002), ported from `schema.py`. Only the
 * keywords the registry uses are supported; anything else is a load-time error, never silently ignored.
 */
object Schema {
    private val supported = setOf(
        "type", "properties", "required", "additionalProperties", "enum", "maxLength", "minLength",
        "pattern", "minimum", "maximum", "format",
    )
    private const val MAX_DEPTH = 8

    fun checkSupported(schema: Any?, path: String = "$") {
        require(schema is Map<*, *>) { "$path: a schema must be an object" }
        for ((key, value) in schema) {
            require(key in supported) { "$path: keyword '$key' is not supported" }
            if (key == "properties") {
                require(value is Map<*, *>) { "$path.properties must be an object" }
                for ((name, sub) in value) checkSupported(sub, "$path.properties.$name")
            }
            if (key == "additionalProperties") require(value == false) { "$path: only additionalProperties: false is supported" }
        }
    }

    fun validate(value: Any?, schema: Map<*, *>, path: String = "$", depth: Int = 0): List<String> {
        if (depth > MAX_DEPTH) return listOf("$path: nested too deeply")
        val problems = mutableListOf<String>()
        val expected = schema["type"]
        if (expected != null && !typeOk(value, expected)) return listOf("$path: expected ${typeName(expected)}")
        val allowed = schema["enum"]
        if (allowed is List<*> && allowed.none { sameValue(it, value) }) problems += "$path: not one of the allowed values"
        if (value is String) problems += stringProblems(value, schema, path)
        else if (isNumber(value)) {
            val number = (value as Number).toDouble()
            (schema["minimum"] as? Number)?.let { if (number < it.toDouble()) problems += "$path: below the minimum" }
            (schema["maximum"] as? Number)?.let { if (number > it.toDouble()) problems += "$path: above the maximum" }
        }
        if (value is Map<*, *> && (schema["type"] == "object" || "properties" in schema)) {
            val properties = (schema["properties"] as? Map<*, *>) ?: emptyMap<Any?, Any?>()
            for (name in (schema["required"] as? List<*>).orEmpty()) {
                if (name !in value) problems += "$path.$name: required"
            }
            for ((name, item) in value) {
                val sub = properties[name]
                if (sub is Map<*, *>) problems += validate(item, sub, "$path.$name", depth + 1)
                else if (schema["additionalProperties"] == false) problems += "$path.$name: not allowed"
            }
        }
        return problems
    }

    private fun typeName(expected: Any?) = if (expected is List<*>) expected.joinToString(",", "[", "]") else expected.toString()

    private fun stringProblems(value: String, schema: Map<*, *>, path: String): List<String> {
        val problems = mutableListOf<String>()
        (schema["maxLength"] as? Number)?.let { if (codePoints(value) > it.toInt()) problems += "$path: too long" }
        (schema["minLength"] as? Number)?.let { if (codePoints(value) < it.toInt()) problems += "$path: too short" }
        (schema["pattern"] as? String)?.let { if (!Regex(it).containsMatchIn(value)) problems += "$path: wrong format" }
        if (schema["format"] == "date-time") {
            if (!isDateTime(value)) problems += "$path: not a date and time"
        }
        return problems
    }

    /** The common ISO 8601 spellings Python's fromisoformat accepts: with an offset or Z, without one, or a date. */
    private fun isDateTime(value: String): Boolean {
        val text = value.replace("Z", "+00:00")
        return listOf<(String) -> Unit>(
            { OffsetDateTime.parse(it) }, { LocalDateTime.parse(it) }, { LocalDate.parse(it) },
        ).any { parse ->
            try {
                parse(text)
                true
            } catch (_: DateTimeParseException) {
                false
            }
        }
    }

    /** Python's len() counts code points, not UTF-16 units. */
    private fun codePoints(s: String) = s.codePointCount(0, s.length)

    private fun isNumber(v: Any?) = v is Number && v !is Boolean

    private fun sameValue(a: Any?, b: Any?): Boolean =
        if (a is Number && b is Number) a.toDouble() == b.toDouble() else a == b

    private fun typeOk(value: Any?, expected: Any?): Boolean {
        val options = if (expected is List<*>) expected else listOf(expected)
        return options.any { oneTypeOk(value, it as String) }
    }

    private fun oneTypeOk(value: Any?, expected: String): Boolean = when (expected) {
        "object" -> value is Map<*, *>
        "string" -> value is String
        "number" -> isNumber(value) && (value as Number).toDouble().let { !it.isNaN() && !it.isInfinite() }
        "integer" -> value is Int || value is Long || value is Short || value is Byte
        "boolean" -> value is Boolean
        else -> false
    }
}
