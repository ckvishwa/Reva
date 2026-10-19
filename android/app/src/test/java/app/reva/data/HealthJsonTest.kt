package app.reva.data

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class HealthJsonTest {
    @Test fun parses_weekly_totals_and_keeps_missing_sleep_distinct_from_zero() {
        val result = HealthJson.weekly("2026-10-18",
            """[{"start_date":"2026-10-12","end_date":"2026-10-18","workout_minutes":30,"workout_count":1,"sleep_minutes":900,"sleep_count":2,"meal_count":3,"medication_expected":7,"medication_taken":5}]""",
            listOf("sleep-1", "sleep-2", "sleep-2"))
        assertEquals(900L, result.sleepMinutes)
        assertEquals(2, result.sleepCount)
        assertEquals(5, result.medicationTaken)
        assertEquals(7, result.medicationExpected)
        assertEquals(2, result.sourceCount)
    }
    @Test fun parses_exact_kernel_daily_values_and_deduplicates_sources() {
        val result = HealthJson.daily("2026-10-16",
            """[{"date":"2026-10-16","workout_minutes":35,"workout_count":1,"sleep_minutes":440,"sleep_count":1,"meal_count":1,"weight_grams":72500,"medications_scheduled":1,"medications_taken":1}]""",
            listOf("workout-1", "meal-1", "meal-1"))
        assertEquals(35L, result.workoutMinutes)
        assertEquals(440L, result.sleepMinutes)
        assertEquals(1, result.sleepCount)
        assertEquals(1, result.mealCount)
        assertEquals(72500L, result.weightGrams)
        assertEquals(1, result.medicationsScheduled)
        assertEquals(1, result.medicationsTaken)
        assertEquals(2, result.sourceCount)
    }

    @Test fun missing_weight_remains_unknown_not_zero() {
        val result = HealthJson.daily("2026-10-16",
            """[{"date":"2026-10-16","workout_minutes":0,"workout_count":0,"sleep_minutes":0,"sleep_count":0,"meal_count":0,"weight_grams":null,"medications_scheduled":0,"medications_taken":0}]""",
            emptyList())
        assertNull(result.weightGrams)
        assertEquals(0, result.sleepCount)
    }
}
