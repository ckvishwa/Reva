package app.reva.testing;

import android.app.Activity;
import android.content.ContentValues;
import android.content.Intent;
import android.net.Uri;
import android.os.Bundle;
import android.provider.MediaStore;
import android.widget.Toast;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;

/**
 * Test-only share target (see src/androidTest/AndroidManifest.xml). It does what a Files app would with a
 * shared file: reads the content:// stream through the grant the sender attached to the share intent, and
 * saves a copy to Downloads. If the sender had not granted read access, the read fails with a
 * SecurityException. The outcome is written to {@link #LOG} either way, so a run can show that the grant,
 * not some broader permission, is what let the file through.
 *
 * Plain Java on purpose. This activity runs on its own in the test APK's process, and the test APK does not
 * carry the Kotlin standard library (the app APK provides it), so any Kotlin stdlib call here would crash
 * with ClassNotFoundException.
 */
public class SaveToDownloadsActivity extends Activity {
    public static final String LOG = "receiver.log";

    @Override
    @SuppressWarnings("deprecation")
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        String result;
        try {
            Uri uri = getIntent().getParcelableExtra(Intent.EXTRA_STREAM);
            if (uri == null) {
                throw new IllegalStateException("the share carried no stream");
            }
            byte[] bytes = readAll(uri);
            String name = uri.getLastPathSegment() == null ? "shared.json" : uri.getLastPathSegment();
            ContentValues values = new ContentValues();
            values.put(MediaStore.Downloads.DISPLAY_NAME, name);
            values.put(MediaStore.Downloads.MIME_TYPE, "application/json");
            values.put(MediaStore.Downloads.RELATIVE_PATH, "Download");
            Uri target = getContentResolver().insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, values);
            if (target == null) {
                throw new IllegalStateException("Downloads refused the file");
            }
            try (OutputStream out = getContentResolver().openOutputStream(target)) {
                if (out == null) {
                    throw new IllegalStateException("Downloads could not be written");
                }
                out.write(bytes);
            }
            result = "OK " + bytes.length + " bytes as " + name + " from " + uri.getAuthority();
        } catch (Throwable t) {
            result = "FAILED " + t.getClass().getSimpleName() + ": " + t.getMessage();
        }
        try (FileOutputStream log = new FileOutputStream(new File(getFilesDir(), LOG), true)) {
            log.write((result + "\n").getBytes(StandardCharsets.UTF_8));
        } catch (IOException ignored) {
            // The toast below still says what happened.
        }
        Toast.makeText(this, result.startsWith("OK") ? "Saved to Downloads" : "Could not save the file", Toast.LENGTH_LONG).show();
        finish();
    }

    private byte[] readAll(Uri uri) throws IOException {
        try (InputStream in = getContentResolver().openInputStream(uri)) {
            if (in == null) {
                throw new IllegalStateException("the stream could not be opened");
            }
            ByteArrayOutputStream out = new ByteArrayOutputStream();
            byte[] buffer = new byte[8192];
            int read;
            while ((read = in.read(buffer)) != -1) {
                out.write(buffer, 0, read);
            }
            return out.toByteArray();
        }
    }
}
