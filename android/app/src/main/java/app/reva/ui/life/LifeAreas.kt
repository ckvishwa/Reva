package app.reva.ui.life

import android.content.SharedPreferences

/**
 * The domain screens reachable from the Life tab (ARD-210 section 4). Only built domains are listed here;
 * a domain that is not built on the phone has no entry, so the hub never shows a dead row.
 *
 * [key] is what gets stored, so it must never change once shipped. [tag] is the test tag of the hub entry.
 */
enum class LifeArea(val key: String, val label: String, val summary: String) {
    Finance("finance", "Finance", "Accounts, budgets, bills and transactions"),
    Health("health", "Health", "Daily records and Health Connect"),
    Gym("gym", "Gym", "Training plan, live workout and session details");

    val tag: String get() = "life_$key"

    companion object {
        fun fromKey(key: String?): LifeArea? = entries.firstOrNull { it.key == key }
    }
}

/** Where the pinned list is kept. Returns null until the owner has changed a pin. */
interface LifePinStore {
    fun load(): List<String>?
    fun save(keys: List<String>)
}

class MemoryLifePinStore(private var keys: List<String>? = null) : LifePinStore {
    override fun load(): List<String>? = keys
    override fun save(keys: List<String>) { this.keys = keys }
}

/** Pins live in ordinary preferences: they are a layout choice, not domain data. */
class SharedPrefsLifePinStore(private val prefs: SharedPreferences) : LifePinStore {
    override fun load(): List<String>? =
        prefs.getString(KEY, null)?.split(',')?.filter { it.isNotEmpty() }

    override fun save(keys: List<String>) {
        prefs.edit().putString(KEY, keys.joinToString(",")).apply()
    }

    private companion object { const val KEY = "pinned" }
}

/**
 * The pin rules, independent of which domains exist: at most [max] pinned keys, in the order they were
 * pinned, drawn only from [catalogue]. Keys outside the catalogue are ignored when read back. [LifePins]
 * binds this to [LifeArea]; it is a separate class so the limit can be tested without inventing domains.
 */
internal class PinRules(
    private val catalogue: List<String>,
    private val default: List<String>,
    private val max: Int,
    private val store: LifePinStore,
) {
    fun pinned(): List<String> {
        val stored = store.load() ?: return default.take(max)
        return stored.filter { it in catalogue }.distinct().take(max)
    }

    fun ordered(): List<String> {
        val pins = pinned()
        return pins + catalogue.filterNot { it in pins }
    }

    /** Returns false, and changes nothing, when [key] is not pinned and [max] are already pinned. */
    fun toggle(key: String): Boolean {
        val pins = pinned()
        val next = when {
            key in pins -> pins - key
            pins.size >= max -> return false
            else -> pins + key
        }
        store.save(next)
        return true
    }
}

/**
 * Pin rules: at most [MAX_PINS] pinned entries, shown first in the order they were pinned; the rest follow
 * in catalogue order. Finance, Health and Gym are pinned until the owner changes that, so nothing that had
 * its own tab before moves more than one tap. Stored keys this build does not know are ignored.
 */
class LifePins(store: LifePinStore) {
    private val rules = PinRules(
        catalogue = LifeArea.entries.map { it.key },
        default = DEFAULT.map { it.key },
        max = MAX_PINS,
        store = store,
    )

    fun pinned(): List<LifeArea> = rules.pinned().mapNotNull(LifeArea::fromKey)

    fun ordered(): List<LifeArea> = rules.ordered().mapNotNull(LifeArea::fromKey)

    fun isPinned(area: LifeArea): Boolean = area in pinned()

    /** Returns false when the area could not be pinned because [MAX_PINS] are already pinned. */
    fun toggle(area: LifeArea): Boolean = rules.toggle(area.key)

    companion object {
        const val MAX_PINS = 4
        val DEFAULT: List<LifeArea> = listOf(LifeArea.Finance, LifeArea.Health, LifeArea.Gym)
    }
}
