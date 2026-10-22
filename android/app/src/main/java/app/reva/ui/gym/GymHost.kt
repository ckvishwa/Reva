package app.reva.ui.gym

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewmodel.compose.viewModel
import app.reva.data.GymRepository
import app.reva.ui.theme.RevaColors
import androidx.compose.foundation.background

/**
 * The Gym tab: Training Plan, Live Workout and Session Details over one ViewModel, so the Back
 * action always has somewhere to go and an unfinished workout is picked up again on open.
 */
@Composable
fun GymHost(repository: GymRepository, modifier: Modifier = Modifier) {
    val factory = remember(repository) {
        object : ViewModelProvider.Factory {
            @Suppress("UNCHECKED_CAST")
            override fun <T : ViewModel> create(modelClass: Class<T>): T = GymViewModel(repository) as T
        }
    }
    val vm: GymViewModel = viewModel(factory = factory)
    val state by vm.state.collectAsState()

    // Opening the tab reads the plan from the Kernel and recovers a workout left in progress.
    LaunchedEffect(repository) {
        vm.load()
        vm.recoverActiveWorkout()
    }

    Box(
        modifier
            .fillMaxSize()
            .background(RevaColors.GymCanvas)
            .testTag("gym_host"),
    ) {
        when (state.screen) {
            GymScreen.TrainingPlan -> TrainingPlanScreen(state, vm)
            GymScreen.LiveWorkout -> LiveWorkoutScreen(state, vm)
            GymScreen.SessionDetails -> SessionDetailsScreen(state, vm)
        }
    }
}
