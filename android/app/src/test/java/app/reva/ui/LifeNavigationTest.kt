package app.reva.ui

import app.reva.ui.life.LifeArea
import app.reva.ui.life.LifePins
import app.reva.ui.life.MemoryLifePinStore
import app.reva.ui.life.PinRules
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** APK-01: the five-destination model of ARD-210 section 4 and the pin rules of the Life hub (AR-APK-001). */
class LifeNavigationTest {
    @Test fun the_five_destinations_are_today_plan_talk_life_more_in_that_order() {
        assertEquals(listOf("Today", "Plan", "Talk", "Life", "More"), Tab.entries.map { it.label })
        assertEquals(Tab.entries.size, Tab.entries.map { it.tag }.toSet().size)
    }

    @Test fun plan_is_not_shown_until_it_is_built_and_every_other_destination_is() {
        assertEquals(listOf(Tab.Today, Tab.Talk, Tab.Life, Tab.More), Tab.visible)
        assertFalse(Tab.Plan.built)
    }

    @Test fun a_saved_tab_that_no_longer_exists_or_is_hidden_restores_to_today() {
        // Older builds saved a tab index, and had Finance, Health and Gym as tabs.
        for (old in listOf(null, "", "Finance", "Health", "Gym", "1", "Plan")) assertEquals(Tab.Today, Tab.restore(old))
        for (tab in Tab.visible) assertEquals(tab, Tab.restore(tab.name))
    }

    @Test fun every_domain_that_used_to_be_a_tab_is_a_life_entry() {
        assertEquals(listOf("Finance", "Health", "Gym"), LifeArea.entries.map { it.label })
        assertEquals(listOf("life_finance", "life_health", "life_gym"), LifeArea.entries.map { it.tag })
    }

    @Test fun stored_keys_are_stable_and_unknown_keys_are_ignored() {
        assertEquals(listOf("finance", "health", "gym"), LifeArea.entries.map { it.key })
        assertNull(LifeArea.fromKey("coach"))
        assertNull(LifeArea.fromKey(null))
        val pins = LifePins(MemoryLifePinStore(listOf("gym", "coach", "gym", "finance")))
        assertEquals(listOf(LifeArea.Gym, LifeArea.Finance), pins.pinned())
    }

    @Test fun finance_health_and_gym_are_pinned_until_the_owner_changes_it() {
        val pins = LifePins(MemoryLifePinStore())
        assertEquals(listOf(LifeArea.Finance, LifeArea.Health, LifeArea.Gym), pins.pinned())
        assertEquals(LifeArea.entries.toList(), pins.ordered())
    }

    @Test fun pinned_entries_come_first_in_pin_order_and_the_rest_keep_catalogue_order() {
        val store = MemoryLifePinStore()
        val pins = LifePins(store)
        assertTrue(pins.toggle(LifeArea.Finance)) // unpin
        assertEquals(listOf(LifeArea.Health, LifeArea.Gym, LifeArea.Finance), pins.ordered())
        assertFalse(pins.isPinned(LifeArea.Finance))
        assertTrue(pins.toggle(LifeArea.Finance)) // pin again: goes to the end of the pinned list
        assertEquals(listOf(LifeArea.Health, LifeArea.Gym, LifeArea.Finance), pins.pinned())
    }

    @Test fun pins_survive_a_restart_because_they_are_read_back_from_the_store() {
        val store = MemoryLifePinStore()
        LifePins(store).toggle(LifeArea.Health)
        assertEquals(listOf(LifeArea.Finance, LifeArea.Gym), LifePins(store).pinned())
        assertEquals(listOf("finance", "gym"), store.load())
    }

    @Test fun unpinning_everything_is_remembered_as_an_empty_list_not_as_the_default() {
        val store = MemoryLifePinStore()
        val pins = LifePins(store)
        LifeArea.entries.forEach { assertTrue(pins.toggle(it)) }
        assertEquals(emptyList<LifeArea>(), LifePins(store).pinned())
        assertEquals(LifeArea.entries.toList(), LifePins(store).ordered())
    }

    @Test fun at_most_four_entries_can_be_pinned() {
        assertEquals(4, LifePins.MAX_PINS)
        assertTrue(LifePins.DEFAULT.size <= LifePins.MAX_PINS)
    }

    /**
     * The fifth-pin rejection runs against the real [PinRules] with synthetic keys, because only three real
     * domains exist and no production or test-only entry may be invented to reach it on a device.
     */
    @Test fun a_fifth_pin_is_rejected_the_first_four_are_unchanged_and_nothing_over_four_is_stored() {
        val keys = listOf("synthetic-1", "synthetic-2", "synthetic-3", "synthetic-4", "synthetic-5")
        val store = MemoryLifePinStore()
        val rules = PinRules(catalogue = keys, default = emptyList(), max = LifePins.MAX_PINS, store = store)

        keys.take(4).forEach { assertTrue("$it should be accepted", rules.toggle(it)) }
        assertEquals(keys.take(4), rules.pinned())
        assertEquals(keys.take(4), store.load())

        assertFalse(rules.toggle(keys[4]))
        assertEquals(keys.take(4), rules.pinned())
        assertEquals(keys.take(4), store.load())
        assertEquals(keys.take(4) + keys[4], rules.ordered())

        // Unpinning frees a slot, and only then is the fifth accepted.
        assertTrue(rules.toggle(keys[0]))
        assertTrue(rules.toggle(keys[4]))
        assertEquals(listOf(keys[1], keys[2], keys[3], keys[4]), store.load())
        assertTrue(store.load().orEmpty().size <= LifePins.MAX_PINS)
    }

    @Test fun a_stored_list_longer_than_four_is_never_read_back_or_extended_past_four() {
        val keys = listOf("a", "b", "c", "d", "e", "f")
        val store = MemoryLifePinStore(keys)
        val rules = PinRules(keys, emptyList(), LifePins.MAX_PINS, store)
        assertEquals(keys.take(4), rules.pinned())
        assertFalse(rules.toggle("e"))
        assertTrue(rules.toggle("a"))
        assertTrue(store.load().orEmpty().size <= LifePins.MAX_PINS)
    }
}
