package app.reva.data

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * The Kernel's JSON as the screens read it. The fixtures here are the exact shapes
 * kernel/src/domains/health/gym.rs returns, so a change on either side fails here.
 */
class GymJsonTest {
    private val programJson = """
        [{"id":"program-1","kind":"gym_program","name":"REVA Base Program","status":"active",
          "anchor_date":"2026-10-22","plan_version":1,"created_at":"2026-10-22T10:00:00.000Z",
          "updated_at":"2026-10-22T10:00:00.000Z","days":[
          {"day_id":"day-2","day_index":1,"label":"Pull A: Lat Width + Biceps","day_type":"training","exercises":[
            {"exercise_key":"lat_pulldown","name":"Lat Pulldown","equipment":"Cable","order":1,
             "planned_sets":3,"min_reps":6,"max_reps":10,"rest_seconds":null}]},
          {"day_id":"day-4","day_index":2,"label":"REST","day_type":"rest","exercises":[]}]}]
    """.trimIndent()

    private fun setJson(order: Int, reps: Int, type: String = "working", semantics: String = "external") = """
        {"id":"set-$order","kind":"gym_set","session_id":"session-1","exercise_key":"lat_pulldown",
         "exercise_name":"Lat Pulldown","equipment":"Cable","exercise_order":1,"prescription_order":1,
         "set_order":$order,"set_type":"$type","load_milli":55000,"weight_unit":"lb",
         "load_semantics":"$semantics","reps":$reps,"rir":2,"completed":true,
         "completed_at":"2026-10-22T17:0$order:00Z","notes":null}
    """.trimIndent()

    private fun detailJson(state: String = "completed", ended: String? = "2026-10-22T17:45:00Z") = """
        [{"session":{"id":"session-1","kind":"gym_session","program_id":"program-1","plan_version":1,
           "day_id":"day-2","label":"Pull A: Lat Width + Biceps","state":"$state","date":"2026-10-22",
           "started_at":"2026-10-22T17:00:00Z","ended_at":${ended?.let { "\"$it\"" } ?: "null"},
           "pauses":[{"from":"2026-10-22T17:16:00Z","to":"2026-10-22T17:19:00Z"}],
           "notes":"Right elbow tight","effort_note":null,
           "plan_snapshot":{"day_id":"day-2","day_index":1,"label":"Pull A: Lat Width + Biceps",
             "day_type":"training","exercises":[{"exercise_key":"lat_pulldown","name":"Lat Pulldown",
             "equipment":"Cable","order":1,"planned_sets":3,"min_reps":6,"max_reps":10,"rest_seconds":null}]}},
          "metrics":{"started_at":"2026-10-22T17:00:00Z","ended_at":"2026-10-22T17:45:00Z",
           "elapsed_seconds":2700,"active_seconds":2520,"paused_seconds":180,"exercises_performed":1,
           "planned_working_sets":3,"working_sets_completed":3,"working_sets_pending":0,
           "warmup_sets_completed":0,"volume_excluded_sets":0,
           "volume_by_unit":[{"unit":"lb","volume_milli":1485000,"volume":1485.0,"sets":3}]},
          "exercises":[{"exercise_key":"lat_pulldown","exercise_name":"Lat Pulldown","equipment":"Cable",
           "exercise_order":1,"planned":{"planned_sets":3,"min_reps":6,"max_reps":10},
           "working_sets_logged":3,"working_sets_completed":3,
           "sets":[${setJson(1, 10)},${setJson(2, 9)},${setJson(3, 8)}]}]}]
    """.trimIndent()

    @Test fun `a program parses with its days, rest days and prescriptions`() {
        val program = GymJson.program(programJson)!!
        assertEquals("program-1", program.id)
        assertEquals("REVA Base Program", program.name)
        assertEquals(1, program.planVersion)
        assertEquals(2, program.days.size)
        val pull = program.day("day-2")!!
        assertEquals("Pull A: Lat Width + Biceps", pull.label)
        assertEquals(3, pull.plannedWorkingSets)
        assertEquals("3 x 6-10 reps", pull.exercises.first().target)
        assertEquals("Cable", pull.exercises.first().equipment)
        val rest = program.day("day-4")!!
        assertTrue(rest.isRest)
        assertEquals(0, rest.plannedWorkingSets)
    }

    @Test fun `no program is an absent program, not an error`() {
        assertNull(GymJson.program("[]"))
        assertNull(GymJson.detail("[]"))
        assertNull(GymJson.previous("[]"))
    }

    @Test fun `session details carry the sets, the metrics and the plan snapshot`() {
        val detail = GymJson.detail(detailJson())!!
        assertEquals("completed", detail.session.state)
        assertEquals("2026-10-22", detail.session.date)
        assertEquals("2026-10-22T17:45:00Z", detail.session.endedAt)
        assertEquals("Right elbow tight", detail.session.notes)
        assertEquals(1, detail.session.snapshot?.exercises?.size)
        assertEquals(3, detail.metrics.workingSetsCompleted)
        assertEquals(2520, detail.metrics.activeSeconds)
        assertEquals(180, detail.metrics.pausedSeconds)
        assertEquals("1485 lb", detail.metrics.volumeByUnit.first().text)

        val block = detail.blockFor("lat_pulldown")!!
        assertEquals(3, block.sets.size)
        assertEquals(listOf(10, 9, 8), block.sets.map { it.reps })
        assertEquals(listOf(55_000L, 55_000L, 55_000L), block.sets.map { it.loadMilli })
        assertEquals("55 lb", block.sets.first().load)
        assertEquals(3, block.planned?.plannedSets)
        assertEquals(2, block.sets.first().rir)
    }

    @Test fun `an open session has no end instant`() {
        val detail = GymJson.detail(detailJson(state = "in_progress", ended = null))!!
        assertNull(detail.session.endedAt)
        assertTrue(detail.session.isOpen)
    }

    @Test fun `previous performance reads as what was done, never as a suggestion`() {
        val json = """
            [{"exercise_key":"lat_pulldown","session_id":"session-1","date":"2026-10-15",
              "label":"Pull A","sets":[${setJson(1, 10)},${setJson(2, 9)},${setJson(3, 8)}]}]
        """.trimIndent()
        val previous = GymJson.previous(json)!!
        assertEquals("2026-10-15", previous.date)
        assertEquals("55 lb x 10, 9, 8", previous.summary)
    }

    @Test fun `loads keep their exact value in both directions`() {
        assertEquals(55_000L, parseLoadMilli("55"))
        assertEquals(52_500L, parseLoadMilli("52.5"))
        assertEquals(52_500L, parseLoadMilli("52,5"))
        assertEquals(2_500L, parseLoadMilli(" 2.5 "))
        assertNull(parseLoadMilli(""))
        assertNull(parseLoadMilli("heavy"))
        assertNull("a load nobody can lift is not a load", parseLoadMilli("5000"))
        assertNull(parseLoadMilli("-5"))

        assertEquals("55 lb", formatLoad(55_000, "lb"))
        assertEquals("52.5 kg", formatLoad(52_500, "kg"))
        assertEquals("0 lb", formatLoad(0, "lb"))
        assertNull(formatLoad(null, "lb"))
    }

    @Test fun `durations read as a workout clock`() {
        assertEquals("00:00", formatDuration(0))
        assertEquals("00:45", formatDuration(45))
        assertEquals("42:00", formatDuration(2_520))
        assertEquals("1:00:00", formatDuration(3_600))
        assertEquals("00:00", formatDuration(-5))
    }

    @Test fun `a set payload names only fields the Kernel reviewed`() {
        val payload = GymJson.setPayload(
            "session-1",
            GymSetInput(exerciseKey = "lat_pulldown", loadMilli = 55_000, reps = 10, rir = 2),
        )
        assertEquals("session-1", payload.getString("session_id"))
        assertEquals("working", payload.getString("set_type"))
        assertEquals("lb", payload.getString("weight_unit"))
        assertEquals("external", payload.getString("load_semantics"))
        assertEquals(55_000L, payload.getLong("load_milli"))
        assertEquals(10, payload.getInt("reps"))
        assertEquals(2, payload.getInt("rir"))
        assertTrue(payload.getBoolean("completed"))
        assertEquals(
            setOf("session_id", "exercise_key", "set_type", "weight_unit", "load_semantics", "completed", "load_milli", "reps", "rir"),
            payload.keys().asSequence().toSet(),
        )
    }

    @Test fun `a plan goes back to the Kernel renumbered and whole`() {
        val program = GymJson.program(programJson)!!
        val reordered = program.days.map { day ->
            if (day.dayId == "day-2") {
                day.copy(
                    exercises = day.exercises + GymPrescription("pec_deck", "Pec Deck", null, 9, 2, 10, 15, 60),
                )
            } else {
                day
            }
        }
        val payload = GymJson.daysPayload(reordered)
        assertEquals(2, payload.length())
        val pull = payload.getJSONObject(0)
        assertEquals("training", pull.getString("day_type"))
        assertEquals(1, pull.getInt("day_index"))
        val exercises = pull.getJSONArray("exercises")
        assertEquals(2, exercises.length())
        assertEquals(1, exercises.getJSONObject(0).getInt("order"))
        assertEquals("the added exercise is renumbered, not left at 9", 2, exercises.getJSONObject(1).getInt("order"))
        assertEquals(60, exercises.getJSONObject(1).getInt("rest_seconds"))
        assertEquals(JSONObject.NULL, exercises.getJSONObject(1).get("equipment"))
        val rest = payload.getJSONObject(1)
        assertEquals("rest", rest.getString("day_type"))
        assertEquals(0, rest.getJSONArray("exercises").length())
    }

    @Test fun `a bodyweight or assisted set keeps its load semantics`() {
        val detail = GymJson.detail(
            detailJson().replace("\"load_semantics\":\"external\"", "\"load_semantics\":\"assistance\""),
        )!!
        assertTrue(detail.blockFor("lat_pulldown")!!.sets.all { it.loadSemantics == "assistance" })
    }
}
