"""GYM-02.1 end-to-end: the real Android Health backup and restore workflow, through the real system UI.

    python tools/android/gym_backup_e2e.py --serial emulator-5554 --out <evidence dir>

    Gym tab: plan -> Day 2 Pull A -> 55 lb x 10, 9, 8 -> pause/resume -> notes -> Finish -> plan edit (v2)
    Health tab: Share a Health backup -> the SYSTEM share sheet -> a share target saves it to Downloads
    pm clear (a fresh install: new encrypted store, new key)
    Health tab: Restore from a backup file -> the SYSTEM document picker -> preview -> confirm
    Gym tab: Training Plan (v2) -> Recent workouts -> Session Details, compared with what was logged
    Repeat the restore (zero new), then cancel, invalid JSON, wrong format and a tampered file.

Everything is driven by adb and uiautomator dumps: real taps on real system UI, no mocked storage. The
share target is the test-only "Reva test: save to Downloads" activity in the androidTest APK; it reads the
content:// stream through the grant the app attached to the share, which is what is being proven.

Safety: this runs `pm clear` and writes to Downloads, so it REFUSES any serial that is not an emulator.
Exit code 0 only if every check passed. Prints one JSON summary line at the end.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
APP = "app.reva.android"
TEST = "app.reva.android.test"
DOCS = "com.google.android.documentsui"
RECEIVER_LABEL = "Reva test: save to Downloads"
APK_DIR = ROOT / "android" / "app" / "build" / "outputs" / "apk"


def _adb() -> str:
    home = os.environ.get("ANDROID_HOME") or os.environ.get("ANDROID_SDK_ROOT")
    if not home:
        raise SystemExit("set ANDROID_HOME")
    return str(Path(home) / "platform-tools" / "adb.exe")


@dataclass
class Node:
    text: str
    desc: str
    cls: str
    pkg: str
    left: int
    top: int
    right: int
    bottom: int
    clickable: bool
    enabled: bool

    @property
    def center(self) -> tuple[int, int]:
        return (self.left + self.right) // 2, (self.top + self.bottom) // 2


class Abort(Exception):
    pass


def text_is(value: str):
    return lambda n: n.text == value


def text_re(pattern: str):
    rx = re.compile(pattern)
    return lambda n: bool(rx.search(n.text))


def desc_is(value: str):
    return lambda n: n.desc == value


class Phone:
    def __init__(self, serial: str, out: Path) -> None:
        if not serial.startswith("emulator-"):
            raise SystemExit(
                f"refusing {serial!r}: this script runs `pm clear` and writes to Downloads, so it only runs on an emulator"
            )
        self.serial, self.out, self.adb_exe = serial, out, _adb()
        self.out.mkdir(parents=True, exist_ok=True)
        self.shots = 0
        self.checks: list[dict[str, object]] = []
        size = self.sh("wm", "size")
        m = re.search(r"(\d+)x(\d+)", size)
        self.width, self.height = (int(m.group(1)), int(m.group(2))) if m else (1080, 2400)

    # --- adb -------------------------------------------------------------------------------------------------
    def adb(self, *args: str, check: bool = True, binary: bool = False, merge: bool = False, timeout: int = 120):
        result = subprocess.run(
            [self.adb_exe, "-s", self.serial, *args],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT if merge else subprocess.PIPE,
            timeout=timeout,
        )
        if check and result.returncode != 0:
            raise RuntimeError(f"adb {' '.join(args)} failed: {result.stderr.decode('utf-8', 'replace')[:300]}")
        return result.stdout if binary else result.stdout.decode("utf-8", "replace")

    def sh(self, *args: str, **kw):
        return self.adb("shell", *args, **kw)

    # --- what is on screen -----------------------------------------------------------------------------------
    def nodes(self) -> list[Node]:
        for _ in range(5):
            raw = self.adb("exec-out", "uiautomator", "dump", "/dev/tty", binary=True, check=False).decode("utf-8", "replace")
            start, end = raw.find("<?xml"), raw.rfind("</hierarchy>")
            if start >= 0 and end > start:
                root = ET.fromstring(raw[start : end + len("</hierarchy>")])
                out = []
                for e in root.iter("node"):
                    m = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", e.get("bounds", ""))
                    if not m:
                        continue
                    l, t, r, b = map(int, m.groups())
                    out.append(
                        Node(
                            e.get("text", ""), e.get("content-desc", ""), e.get("class", ""), e.get("package", ""),
                            l, t, r, b, e.get("clickable") == "true", e.get("enabled") == "true",
                        )
                    )
                return out
            time.sleep(1)
        raise RuntimeError("uiautomator could not dump the screen")

    def find(self, pred, pkg: str | None = None, visible: bool = True) -> Node | None:
        for n in self.nodes():
            if pkg is not None and n.pkg != pkg:
                continue
            if not pred(n):
                continue
            if visible and not (100 <= n.top and n.bottom <= self.height - 260):
                continue
            return n
        return None

    def wait(self, pred, timeout: float = 25, pkg: str | None = None, what: str = "", visible: bool = True) -> Node:
        end = time.time() + timeout
        while time.time() < end:
            n = self.find(pred, pkg, visible)
            if n:
                return n
            time.sleep(0.6)
        self.fail_shot(what or "wait")
        raise Abort(f"timed out waiting for {what or 'the screen to show it'}")

    def tap(self, n: Node) -> None:
        self.sh("input", "tap", str(n.center[0]), str(n.center[1]))
        time.sleep(1.0)

    def type(self, text: str) -> None:
        self.sh("input", "text", text.replace(" ", "%s"))
        time.sleep(0.5)

    def hide_keyboard(self) -> None:
        if "mInputShown=true" in self.sh("dumpsys", "input_method", check=False):
            self.sh("input", "keyevent", "4")
            time.sleep(0.8)

    def swipe(self, up: bool = True) -> None:
        a, b = (1750, 750) if up else (750, 1750)
        self.sh("input", "swipe", "540", str(a), "540", str(b), "350")
        time.sleep(0.7)

    def scroll_to(self, pred, what: str, max_swipes: int = 12, pkg: str | None = APP) -> Node:
        for i in range(max_swipes):
            n = self.find(pred, pkg)
            if n:
                return n
            self.swipe(up=True)
        self.fail_shot(what)
        raise Abort(f"could not scroll to {what}")

    def scroll_top(self) -> None:
        for _ in range(8):
            self.swipe(up=False)

    def shot(self, name: str) -> str:
        self.shots += 1
        path = self.out / f"{self.shots:02d}-{name}.png"
        path.write_bytes(self.adb("exec-out", "screencap", "-p", binary=True))
        return path.name

    def fail_shot(self, name: str) -> None:
        try:
            self.shot("FAILED-" + re.sub(r"[^a-z0-9]+", "-", name.lower())[:40])
            raw = self.adb("exec-out", "uiautomator", "dump", "/dev/tty", binary=True, check=False)
            (self.out / f"FAILED-{self.shots:02d}.xml").write_bytes(raw)
        except Exception:
            pass

    # --- results ---------------------------------------------------------------------------------------------
    def check(self, name: str, ok: bool, detail: object = "") -> bool:
        self.checks.append({"check": name, "pass": bool(ok), "detail": detail})
        print(("PASS  " if ok else "FAIL  ") + name + (f"   [{detail}]" if detail != "" else ""), flush=True)
        return bool(ok)

    def must(self, name: str, ok: bool, detail: object = "") -> None:
        if not self.check(name, ok, detail):
            self.fail_shot(name)
            raise Abort(name)

    # --- app -------------------------------------------------------------------------------------------------
    def launch(self) -> None:
        self.sh("am", "start", "-n", f"{APP}/app.reva.MainActivity")
        self.wait(text_is("Today"), 40, APP, "the app to open")

    def tab(self, name: str) -> None:
        deadline = time.time() + 20
        while time.time() < deadline:
            hits = [n for n in self.nodes() if n.pkg == APP and n.text == name and n.top > self.height - 330]
            if hits:
                self.tap(hits[-1])
                time.sleep(1.5)
                return
            time.sleep(0.6)
        raise Abort(f"no {name} tab")

    def stat_pairs(self, ns: list[Node]) -> dict[str, str]:
        labels = ("ACTIVE", "ELAPSED", "PAUSED", "EXERCISES", "WORKING SETS", "PLANNED")
        return {n.text: ns[i - 1].text for i, n in enumerate(ns) if n.text in labels and i > 0}

    def read_receipt(self) -> dict[str, object]:
        """What Session Details shows, scrolled top to bottom, as plain values."""
        self.scroll_top()
        r: dict[str, object] = {"stats": {}, "sets": {}, "notes": []}
        notes: set[str] = set()
        for _ in range(7):
            ns = [n for n in self.nodes() if n.pkg == APP]
            r["stats"].update(self.stat_pairs(ns))  # type: ignore[union-attr]
            for i, n in enumerate(ns):
                tx = n.text
                if re.fullmatch(r"Workout receipt · plan v\d+", tx):
                    r["header"] = tx
                elif re.fullmatch(r"\d{4}-\d\d-\d\d", tx) and "date" not in r:
                    r["date"] = tx
                elif re.fullmatch(r"\d\d:\d\d - \d\d:\d\d UTC", tx):
                    r["range"] = tx
                elif re.fullmatch(r"[\d.]+ lb", tx):
                    r["volume"] = tx
                elif re.fullmatch(r"Set \d", tx) and i + 2 < len(ns):
                    r["sets"][tx] = (ns[i + 1].text, ns[i + 2].text)  # type: ignore[index]
                elif n.cls.endswith("EditText") and tx and tx not in ("Session note", "Effort or recovery"):
                    notes.add(tx)
            self.swipe(up=True)
        r["notes"] = sorted(notes)
        return r

    # --- fixture, through the Gym UI --------------------------------------------------------------------------
    def log_set(self, load: str, reps: str, n: int) -> None:
        self.tap(self.wait(text_is("Weight (lb)"), 15, APP, "the weight field"))
        self.type(load)
        self.tap(self.wait(text_is("Reps"), 15, APP, "the reps field"))
        self.type(reps)
        self.hide_keyboard()
        self.tap(self.wait(text_is("Log set"), 15, APP, "Log set"))
        # The Kernel's own count of completed working sets, in the header. (The set row itself sits below the
        # fold in a lazy list; the exact values are checked on the receipt.)
        self.wait(text_is(f"{n}/16"), 15, APP, f"the working-set counter to read {n}/16")
        self.wait(text_is("Set saved"), 10, APP, "the saved notice", visible=False)

    def build_workout(self) -> None:
        self.launch()
        self.tab("Gym")
        self.wait(text_is("No plan on this device yet"), 20, APP, "the empty Training Plan")
        self.shot("gym-empty-fresh-install")
        self.tap(self.wait(text_is("Create training plan"), 10, APP))
        self.wait(text_is("Training plan created"), 15, APP)
        self.tap(self.wait(text_is("D2"), 10, APP))
        self.wait(text_is("Pull A: Lat Width + Biceps"), 10, APP)
        self.tap(self.scroll_to(text_is("Start workout"), "Start workout"))
        self.wait(text_is("LOG A SET"), 15, APP, "the Live Workout")
        for n, reps in enumerate(("10", "9", "8"), start=1):
            self.log_set("55", reps, n)
        self.shot("live-workout-three-sets")
        # Pause and resume: the receipt must carry the break.
        self.scroll_top()
        self.tap(self.wait(desc_is("Pause workout"), 10, APP))
        self.wait(desc_is("Resume workout"), 10, APP)
        time.sleep(2)
        self.tap(self.wait(desc_is("Resume workout"), 10, APP))
        self.wait(desc_is("Pause workout"), 10, APP)
        # Notes.
        self.tap(self.scroll_to(text_is("What happened"), "the session note"))
        self.type("Right elbow tight")
        self.tap(self.scroll_to(text_is("Effort or recovery"), "the effort note"))
        self.type("Felt strong")
        self.hide_keyboard()
        self.tap(self.scroll_to(text_is("Save notes"), "Save notes"))
        self.wait(text_is("Note saved"), 10, APP, "the note to be saved", visible=False)
        # Finish, once, after confirming.
        self.tap(self.scroll_to(text_is("Finish workout"), "Finish workout"))
        self.wait(text_is("Finish this workout?"), 10, APP)
        self.shot("finish-dialog")
        self.tap(self.wait(text_is("Finish"), 10, APP))
        self.wait(text_is("completed"), 20, APP, "Session Details")

    def edit_plan_to_v2(self) -> None:
        self.tap(self.scroll_to(text_is("Back to Gym"), "Back to Gym"))
        self.tap(self.wait(text_is("Edit plan"), 15, APP))
        field = self.wait(lambda n: n.cls.endswith("EditText") and n.text.startswith("Pull A"), 15, APP, "the workout name field")
        self.tap(field)
        self.sh("input", "keyevent", "123")  # move to the end
        self.type(" edited")
        self.hide_keyboard()
        self.tap(self.scroll_to(text_is("Save plan"), "Save plan"))
        # The notice sits at the top of the list, which is scrolled away by now; the header carries the version.
        self.scroll_top()
        self.wait(text_re(r"plan v2$"), 15, APP, "the plan header to read plan v2")

    # --- share, through the real share sheet ----------------------------------------------------------------
    def today(self) -> str:
        return self.sh("date", "+%F").strip()

    def share_backup(self) -> str:
        self.tab("Health")
        self.tap(self.scroll_to(text_is("Share a Health backup"), "Share a Health backup"))
        self.wait(text_is("Share a Health backup?"), 10, APP)
        self.shot("share-confirm-dialog")
        self.tap(self.wait(text_is("Share"), 10, APP))
        target = self.wait(text_is(RECEIVER_LABEL), 25, None, "the share sheet to list the test receiver", visible=False)
        self.shot("system-share-sheet")
        name = f"reva-health-{self.today()}.json"
        # Nothing but the grant on the share lets another app read it: the provider is not exported.
        denied = self.sh("content", "read", "--uri", f"content://{APP}.exports/exports/{name}", check=False, merge=True)
        self.check(
            "the export provider is not readable by another process without the share's grant",
            "Permission Denial" in denied or "not exported" in denied.lower() or "SecurityException" in denied,
            denied.strip()[:140],
        )
        self.tap(target)
        end = time.time() + 25
        while time.time() < end and name not in self.sh("ls", "/sdcard/Download", check=False):
            time.sleep(1)
        return name

    # --- restore, through the real document picker ----------------------------------------------------------
    def open_picker(self) -> None:
        self.tab("Health")
        self.tap(self.scroll_to(text_is("Restore from a backup file"), "Restore from a backup file"))
        self.wait(lambda n: n.pkg == DOCS, 25, None, "the system document picker", visible=False)

    def pick(self, filename: str) -> None:
        end = time.time() + 40
        tried_roots = False
        while time.time() < end:
            hit = self.find(lambda n: n.text == filename, DOCS, visible=False)
            if hit:
                self.tap(hit)
                return
            if not tried_roots:
                roots = self.find(desc_is("Show roots"), DOCS, visible=False)
                if roots:
                    self.tap(roots)
                    downloads = self.find(text_is("Downloads"), DOCS, visible=False)
                    if downloads:
                        self.tap(downloads)
                    tried_roots = True
                    continue
            time.sleep(0.8)
        self.fail_shot("picker-file")
        raise Abort(f"the picker never listed {filename}")

    def control_enabled(self, label: str) -> bool:
        """Whether the button labelled [label] is enabled. The label is a child TextView (always enabled); the
        button is the smallest clickable node around it, and that node carries the real state."""
        ns = self.nodes()
        text = next(n for n in ns if n.pkg == APP and n.text == label)
        cx, cy = text.center
        holders = [n for n in ns if n.clickable and n.left <= cx <= n.right and n.top <= cy <= n.bottom]
        holder = min(holders, key=lambda n: (n.right - n.left) * (n.bottom - n.top)) if holders else text
        return holder.enabled

    def preview(self) -> str:
        n = self.wait(text_re(r"^This file has "), 25, APP, "the restore preview", visible=False)
        return n.text

    def message(self) -> str:
        return self.wait(
            lambda n: n.text.startswith(("Restored ", "That file", "file:", "records:", "gym:")) or "not valid JSON" in n.text,
            20, APP, "a result line", visible=False,
        ).text


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--serial", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--app-apk", type=Path, default=APK_DIR / "debug" / "app-debug.apk")
    parser.add_argument("--test-apk", type=Path, default=APK_DIR / "androidTest" / "debug" / "app-debug-androidTest.apk")
    args = parser.parse_args()

    p = Phone(args.serial, args.out)
    summary: dict[str, object] = {"serial": args.serial}
    try:
        for apk in (args.app_apk, args.test_apk):
            if not apk.is_file():
                raise SystemExit(f"missing {apk}")
        for apk, flags in ((args.app_apk, ["-r"]), (args.test_apk, ["-r", "-t"])):
            p.adb("install", *flags, str(apk), merge=True)
        for scale in ("window_animation_scale", "transition_animation_scale", "animator_duration_scale"):
            p.sh("settings", "put", "global", scale, "0")
        p.sh("rm -f /sdcard/Download/reva-*.json /sdcard/Download/reva-*.json.*")  # one string: the device shell expands the glob
        p.sh("run-as", TEST, "rm", "-f", "files/receiver.log", check=False)
        p.sh("am", "force-stop", APP)
        p.sh("pm", "clear", APP)  # a fresh install: a new encrypted store and key
        p.check("airplane mode is irrelevant: nothing here touches the network",
                "app.reva.android" in p.sh("pm", "list", "packages", APP))

        # 1. The fixture, through the real Gym screens.
        p.build_workout()
        before = p.read_receipt()
        p.shot("session-details-before-backup")
        summary["receipt_before"] = before
        p.must("fixture: three sets 55 lb x 10, 9, 8", [v[0] for k, v in sorted(before["sets"].items())] == ["55 lb x 10", "55 lb x 9", "55 lb x 8"], before["sets"])  # type: ignore[union-attr]
        p.must("fixture: volume is 1485 lb", before.get("volume") == "1485 lb", before.get("volume"))
        p.must("fixture: notes recorded", before["notes"] == ["Felt strong", "Right elbow tight"], before["notes"])
        p.must("fixture: pause recorded", before["stats"].get("PAUSED") not in (None, "00:00"), before["stats"])  # type: ignore[union-attr]
        p.must("fixture: session is on plan v1", before.get("header") == "Workout receipt · plan v1", before.get("header"))
        p.edit_plan_to_v2()
        p.must("fixture: the program is now plan v2", p.find(text_re(r"plan v2$"), APP) is not None)
        p.shot("training-plan-v2-before-backup")

        # 2. Share through the real share sheet.
        name = p.share_backup()
        p.must("the share target saved the backup to Downloads", name in p.sh("ls", "/sdcard/Download"), name)
        log = p.sh("run-as", TEST, "cat", "files/receiver.log", check=False, merge=True).strip()
        p.check("the receiver read the stream through the share's grant", log.startswith("OK"), log[:160])
        backup = args.out / "health-backup.json"
        p.adb("pull", f"/sdcard/Download/{name}", str(backup), merge=True)
        data = json.loads(backup.read_text(encoding="utf-8"))
        gym = data.get("gym", {})
        p.must("backup format is reva-health-v2", data.get("format") == "reva-health-v2", data.get("format"))
        p.must("backup holds 1 program, 1 session, 3 sets, no deletions",
               (len(gym["programs"]), len(gym["sessions"]), len(gym["sets"]), len(gym["deleted"])) == (1, 1, 3, 0),
               {k: len(v) for k, v in gym.items()})
        p.check("backup: program is plan v2, session is plan v1",
                (gym["programs"][0]["plan_version"], gym["sessions"][0]["plan_version"]) == (2, 1))
        p.check("backup: sets are 55000 milli-lb x 10, 9, 8",
                [(s["load_milli"], s["reps"], s["weight_unit"]) for s in sorted(gym["sets"], key=lambda s: s["set_order"])]
                == [(55000, 10, "lb"), (55000, 9, "lb"), (55000, 8, "lb")])
        p.check("backup: notes and pause interval", gym["sessions"][0]["notes"] == "Right elbow tight" and len(gym["sessions"][0]["pauses"]) == 1)
        summary["backup_bytes"] = backup.stat().st_size

        # 3. A fresh install, then restore through the real picker.
        p.sh("am", "force-stop", APP)
        p.sh("pm", "clear", APP)
        p.launch()
        p.tab("Gym")
        p.must("fresh store: no plan, no workouts", p.find(text_is("No plan on this device yet"), APP) is not None)
        p.shot("fresh-store-empty-gym")
        p.open_picker()
        p.shot("system-file-picker")
        p.pick(name)
        text = p.preview()
        p.shot("restore-preview")
        p.must("preview: 5 new records, nothing else", text == "This file has 5 new records, 0 already here and 0 that cannot be restored.", text)
        p.must("no success line before confirming", p.find(text_re(r"^Restored "), APP, visible=False) is None)
        p.tap(p.wait(text_is("Restore 5 new records"), 10, APP))
        result = p.message()
        p.shot("restore-result")
        p.must("result reports the Kernel's commit", result == "Restored 5 records; 0 were already here; 0 skipped.", result)

        # 4. Reopen the session through the real Gym UI.
        p.tab("Gym")
        plan_header = p.wait(text_re(r"plan v\d+$"), 20, APP, "the restored plan header", visible=False).text
        p.must("restored plan is v2", plan_header.endswith("plan v2"), plan_header)
        # The plan opens on Day 1; select Day 2 to read its (edited) name.
        p.scroll_top()
        p.tap(p.wait(text_is("D2"), 10, APP, "the Day 2 tile"))
        label = p.wait(text_re(r"^Pull A: Lat Width \+ Biceps"), 10, APP, "Day 2's name").text
        p.must("restored Day 2 keeps the edited name", label == "Pull A: Lat Width + Biceps edited", label)
        p.shot("restored-training-plan")
        p.tap(p.scroll_to(text_re(r"^\d{4}-\d\d-\d\d · 3 working sets$"), "the restored workout in Recent workouts"))
        p.wait(text_is("completed"), 20, APP, "Session Details")
        after = p.read_receipt()
        p.shot("session-details-after-restore")
        summary["receipt_after"] = after
        for key in ("header", "date", "range", "volume", "notes", "sets", "stats"):
            p.check(f"restored receipt matches: {key}", before.get(key) == after.get(key), after.get(key))

        # 5. Repeat the same restore through the picker: zero new, nothing to confirm.
        p.open_picker()
        p.pick(name)
        text = p.preview()
        p.shot("repeat-restore-preview")
        p.must("repeat: 0 new records, 5 already here", text == "This file has 0 new records, 5 already here and 0 that cannot be restored.", text)
        p.wait(text_is("Restore 0 new records"), 10, APP, "the confirm button")
        p.must("repeat: confirm is disabled", not p.control_enabled("Restore 0 new records"))
        p.tap(p.wait(text_is("Cancel"), 10, APP))

        # 6. Cancel, invalid JSON, wrong format, a tampered file: nothing changes.
        p.open_picker()
        p.sh("input", "keyevent", "4")  # back out of the picker
        time.sleep(2)
        p.check("cancelled picker: no preview and no result line",
                p.find(text_re(r"^This file has "), APP, visible=False) is None and p.find(text_re(r"^Restored "), APP, visible=False) is None)
        p.shot("picker-cancelled")

        tampered = json.loads(json.dumps(data))
        tampered["gym"]["sets"][0]["load_milli"] = 9_000_000
        cases = {
            "reva-bad-json.json": ("{not json", "not valid JSON"),
            "reva-wrong-format.json": ('{"format":"other","records":[]}', "not a REVA Health backup"),
            "reva-tampered.json": (json.dumps(tampered), None),
        }
        for fname, (content, expected) in cases.items():
            local = args.out / fname
            local.write_text(content, encoding="utf-8")
            p.adb("push", str(local), f"/sdcard/Download/{fname}", merge=True)
            time.sleep(2)
            p.open_picker()
            p.pick(fname)
            if expected is not None:
                msg = p.wait(text_re(re.escape(expected)), 20, APP, f"{fname} to be refused", visible=False).text
                p.check(f"{fname}: refused with a reason", expected in msg, msg)
                p.check(f"{fname}: nothing to confirm", p.find(text_re(r"^Restore \d+ new"), APP, visible=False) is None)
            else:
                text = p.preview()
                p.check("tampered: the altered set cannot be restored, the rest are already here",
                        text == "This file has 0 new records, 4 already here and 1 that cannot be restored.", text)
                p.wait(text_is("Restore 0 new records"), 10, APP, "the confirm button")
                p.check("tampered: confirm is disabled", not p.control_enabled("Restore 0 new records"))
                p.tap(p.wait(text_is("Cancel"), 10, APP))
            p.shot("negative-" + fname.replace(".json", ""))

        # 7. After all of that the restored workout is exactly as it was.
        p.tab("Gym")
        p.tap(p.scroll_to(text_re(r"^\d{4}-\d\d-\d\d · 3 working sets$"), "the workout in Recent workouts"))
        p.wait(text_is("completed"), 20, APP, "Session Details")
        final = p.read_receipt()
        p.check("after repeat, cancel, invalid and tampered files the receipt is unchanged", final == before, final == before)
        p.tab("Gym")
        p.tap(p.scroll_to(text_is("Back to Gym"), "Back to Gym")) if p.find(text_is("Back to Gym"), APP) else None
        recents = [n for n in p.nodes() if n.pkg == APP and re.fullmatch(r"\d{4}-\d\d-\d\d · \d+ working sets", n.text)]
        p.check("exactly one workout in Recent workouts", len(recents) <= 1, len(recents))
    except Abort as exc:
        summary["aborted"] = str(exc)
    finally:
        for scale in ("window_animation_scale", "transition_animation_scale", "animator_duration_scale"):
            p.sh("settings", "put", "global", scale, "1", check=False)
        p.sh("rm -f /sdcard/Download/reva-*.json /sdcard/Download/reva-*.json.*", check=False)

    failed = [c for c in p.checks if not c["pass"]]
    summary.update(passed=len(p.checks) - len(failed), failed=len(failed), checks=p.checks, screenshots=p.shots)
    (args.out / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps({k: summary[k] for k in summary if k not in ("checks", "receipt_before", "receipt_after")}))
    return 0 if not failed and "aborted" not in summary else 1


if __name__ == "__main__":
    sys.exit(main())
