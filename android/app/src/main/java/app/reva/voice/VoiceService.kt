package app.reva.voice

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.IBinder
import androidx.core.app.NotificationCompat
import androidx.core.app.ServiceCompat
import androidx.core.content.ContextCompat
import app.reva.MainActivity
import app.reva.R
import app.reva.RevaApp

/**
 * Foreground service of type `microphone`. It exists only while the microphone is open, is started only by
 * [AndroidServiceLauncher] from a tap on the mic button, and shows a notification with a Stop action. It does
 * no work itself: the recognizer lives in [VoiceController].
 */
class VoiceService : Service() {
    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val voice = (application as RevaApp).container.voice
        if (intent?.action == ACTION_STOP) {
            voice.onStopTapped()
            stopSelf()
            return START_NOT_STICKY
        }
        try {
            ServiceCompat.startForeground(
                this, NOTIFICATION_ID, notification(this), ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE,
            )
        } catch (_: RuntimeException) {
            // Android refused (permission missing or app not in front): no service means no listening.
            voice.onStopTapped()
            stopSelf()
        }
        return START_NOT_STICKY // never restarted behind the owner's back
    }

    companion object {
        const val ACTION_STOP = "app.reva.android.voice.STOP"
        const val NOTIFICATION_ID = 7101
        const val CHANNEL_ID = "voice_session"

        fun notification(context: Context): Notification {
            val manager = context.getSystemService(NotificationManager::class.java)
            manager.createNotificationChannel(
                NotificationChannel(CHANNEL_ID, context.getString(R.string.voice_channel_name), NotificationManager.IMPORTANCE_LOW),
            )
            val open = PendingIntent.getActivity(
                context, 0, Intent(context, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE,
            )
            val stop = PendingIntent.getService(
                context, 1, Intent(context, VoiceService::class.java).setAction(ACTION_STOP), PendingIntent.FLAG_IMMUTABLE,
            )
            return NotificationCompat.Builder(context, CHANNEL_ID)
                .setSmallIcon(R.mipmap.ic_launcher)
                .setContentTitle(context.getString(R.string.voice_notification_title))
                .setContentText(context.getString(R.string.voice_notification_text))
                .setContentIntent(open)
                .addAction(0, context.getString(R.string.voice_notification_stop), stop)
                .setOngoing(true)
                .setCategory(NotificationCompat.CATEGORY_SERVICE)
                .build()
        }
    }
}

class AndroidServiceLauncher(private val context: Context) : ServiceLauncher {
    override fun start(): Boolean = try {
        ContextCompat.startForegroundService(context, Intent(context, VoiceService::class.java))
        true
    } catch (_: RuntimeException) {
        false
    }

    override fun stop() {
        context.stopService(Intent(context, VoiceService::class.java))
    }
}
