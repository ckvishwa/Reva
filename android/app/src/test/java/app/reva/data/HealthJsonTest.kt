package app.reva.data

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class HealthJsonTest {
    @Test fun parses_weekly_totals_and_keeps_missing_sleep_distinct_from_zero() {
        val result = HealthJson.weekly("2026-10-18",
            """[{"start_date":"2026-10-12","end_date":"2026-10-18","workout_minutes":30,"workout_count":1,"sleep_minutes":900,"sleep_count":2,"meal_count":3,"medication_expected":7,"medication_taken":5,"steps_total":0,"steps_days":0,"heart_rate_count":0,"heart_rate_min_bpm":null,"heart_rate_max_bpm":null}]""",
            listOf("sleep-1", "sleep-2", "sleep-2"))
        assertEquals(900L, result.sleepMinutes)
        assertEquals(2, result.sleepCount)
        assertEquals(5, result.medicationTaken)
        assertEquals(7, result.medicationExpected)
        assertEquals(2, result.sourceCount)
    }
    @Test fun parses_exact_kernel_daily_values_and_deduplicates_sources() {
        val result = HealthJson.daily("2026-10-16",
            """[{"date":"2026-10-16","workout_minutes":35,"workout_count":1,"sleep_minutes":440,"sleep_count":1,"meal_count":1,"weight_grams":72500,"medications_scheduled":1,"medications_taken":1,"steps":null,"steps_count":0,"heart_rate_count":0,"heart_rate_min_bpm":null,"heart_rate_max_bpm":null}]""",
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
            """[{"date":"2026-10-16","workout_minutes":0,"workout_count":0,"sleep_minutes":0,"sleep_count":0,"meal_count":0,"weight_grams":null,"medications_scheduled":0,"medications_taken":0,"steps":null,"steps_count":0,"heart_rate_count":0,"heart_rate_min_bpm":null,"heart_rate_max_bpm":null}]""",
            emptyList())
        assertNull(result.weightGrams)
        assertEquals(0, result.sleepCount)
    }

    @Test fun recorded_zero_steps_is_distinct_from_no_step_record_and_heart_rate_is_a_range() {
        val result = HealthJson.daily("2026-10-18",
            """[{"date":"2026-10-18","workout_minutes":0,"workout_count":0,"sleep_minutes":0,"sleep_count":0,"meal_count":0,"weight_grams":null,"medications_scheduled":0,"medications_taken":0,"steps":0,"steps_count":1,"heart_rate_count":2,"heart_rate_min_bpm":62,"heart_rate_max_bpm":88}]""",
            listOf("steps-1", "hr-1", "hr-2"))
        assertEquals(0L, result.steps)
        assertEquals(1, result.stepsCount)
        assertEquals(2, result.heartRateCount)
        assertEquals(62L, result.heartRateMinBpm)
        assertEquals(88L, result.heartRateMaxBpm)
    }

    @Test fun parses_same_day_steps_conflict_without_adding_the_two_sources() {
        val result = HealthJson.daily("2026-10-18",
            """[{"date":"2026-10-18","workout_minutes":0,"workout_count":0,"sleep_minutes":0,"sleep_count":0,"meal_count":0,"weight_grams":null,"medications_scheduled":0,"medications_taken":0,"steps":5000,"steps_source":"manual","steps_count":2,"steps_conflict":true,"steps_manual":5000,"steps_health_connect":7000,"heart_rate_count":0,"heart_rate_min_bpm":null,"heart_rate_max_bpm":null}]""",
            listOf("steps-1", "hc-steps-2026-10-18"))
        assertEquals(5000L, result.steps)
        assertEquals("manual", result.stepsSource)
        assertEquals(true, result.stepsConflict)
        assertEquals(5000L, result.stepsManual)
        assertEquals(7000L, result.stepsHealthConnect)
        val week = HealthJson.weekly("2026-10-18",
            """[{"start_date":"2026-10-12","end_date":"2026-10-18","workout_minutes":0,"workout_count":0,"sleep_minutes":0,"sleep_count":0,"meal_count":0,"medication_expected":0,"medication_taken":0,"steps_total":5000,"steps_days":1,"steps_conflict_dates":["2026-10-18"],"heart_rate_count":0,"heart_rate_min_bpm":null,"heart_rate_max_bpm":null}]""",
            emptyList())
        assertEquals(listOf("2026-10-18"), week.stepsConflictDates)
        assertEquals(5000L, week.stepsTotal)
    }

    @Test fun import_report_counts_every_row_once_and_keeps_reasons() {
        val report = HealthJson.importReport(
            """[{"row":1,"status":"accepted","raw":"{}"},{"row":2,"status":"updated","raw":"{}"},{"row":3,"status":"duplicate","raw":"{}"},{"row":4,"status":"rejected","reason":"deleted on this device; not restored","raw":"{}"}]""",
            dryRun = true,
        )
        assertEquals(1, report.added)
        assertEquals(1, report.updated)
        assertEquals(1, report.duplicates)
        assertEquals(listOf("Row 4: deleted on this device; not restored"), report.rejected)
        assertEquals(true, report.dryRun)
    }
}
