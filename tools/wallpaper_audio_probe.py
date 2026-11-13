#!/usr/bin/env python3
"""Real video/scene/Web PCM, mute and volume checks on a private null sink."""
from array import array
import json
import math
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
PRIVATE = Path(os.environ.get("XDG_STATE_HOME", ""))
if os.environ.get("SELANDIA_PRIVATE_PROBE") != "1" or not PRIVATE.name.startswith("selandia-smoke-"):
    raise SystemExit("Run only through the isolated tools/smoke.py session")
BASE = Path(os.environ["XDG_CONFIG_HOME"]) / "niri"
sys.path.insert(0, str(BASE / "shell"))
import wallpaper
import wallpaper_audio
import audio_backend


def main():
    artifacts = ROOT / ".validation/wallpaper-audio"
    artifacts.mkdir(parents=True, exist_ok=True)
    runtime = PRIVATE / "audio-runtime"
    runtime.mkdir(mode=0o700)
    display = Path(os.environ["WAYLAND_DISPLAY"])
    if not display.is_absolute():
        display = Path(os.environ["XDG_RUNTIME_DIR"]) / display
    environment = dict(os.environ, XDG_RUNTIME_DIR=str(runtime), PIPEWIRE_RUNTIME_DIR=str(runtime),
                       PULSE_RUNTIME_PATH=str(runtime / "pulse"), PULSE_SERVER=f"unix:{runtime}/pulse/native",
                       PIPEWIRE_REMOTE="pipewire-0", PIPEWIRE_CONFIG_DIR="/usr/share/pipewire",
                       WAYLAND_DISPLAY=str(display), DBUS_SYSTEM_BUS_ADDRESS=f"unix:path={runtime}/no-system-bus")
    local = ROOT / ".local/wallpaper-engine"
    if local.is_dir():
        environment["SELANDIA_ENGINE_COMPAT_DIR"] = str(local)
    # This process too must use the private renderer record and private audio
    # server when calling set_audio()/read_state(), not just its children.
    os.environ.update(environment)
    children, logs, results = [], [], []
    def start(name, command, *, env=None):
        log = (artifacts / (name + ".log")).open("w")
        logs.append(log)
        child = subprocess.Popen(command, env=env or environment, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        children.append(child)
        return child
    def command(*args):
        return subprocess.check_output(args, env=environment, text=True, stderr=subprocess.PIPE, timeout=5)
    def stop(child):
        if child.poll() is None:
            os.killpg(child.pid, signal.SIGTERM)
            try:
                child.wait(timeout=4)
            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGKILL)
                child.wait(timeout=3)
    try:
        start("pipewire", ["pipewire"])
        start("pulse", ["pipewire-pulse"])
        # The policy profile manages software links only. Hardware monitors,
        # Bluetooth and camera services are absent from this profile.
        start("policy", ["wireplumber", "--profile", "policy"])
        for _ in range(60):
            try:
                command("pactl", "info")
                break
            except subprocess.SubprocessError:
                time.sleep(.1)
        else:
            raise RuntimeError("Private audio server did not start")
        command("pactl", "load-module", "module-null-sink", "sink_name=wallpaper-probe", "channels=2",
                "sink_properties=node.driver=true node.always-process=true")
        for _ in range(30):
            try:
                command("pactl", "set-default-sink", "wallpaper-probe")
                break
            except subprocess.SubprocessError:
                time.sleep(.1)
        else:
            raise RuntimeError("Private null sink did not become ready")
        fixture = PRIVATE / "audio-fixtures"
        fixture.mkdir()
        tone = fixture / "tone.wav"
        command("ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=4", "-ar", "48000", str(tone))
        video = fixture / "video.mp4"
        command("ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=teal:s=320x180:r=15:d=4", "-i", str(tone), "-c:v", "libx264", "-c:a", "aac", "-shortest", str(video))
        assets = wallpaper.discover()["assets"]
        if not assets:
            raise RuntimeError("Original engine assets required for scene audio probe")
        scene = fixture / "scene"
        shutil.copytree(Path(assets).parent / "projects/defaultprojects/eagleflag", scene)
        shutil.copy2(tone, scene / "tone.wav")
        scene_data = json.loads((scene / "scene.json").read_text())
        scene_data["objects"].append({"id": 999999, "name": "Private audio fixture", "sound": ["tone.wav"], "playbackmode": "loop"})
        (scene / "scene.json").write_text(json.dumps(scene_data))
        web = fixture / "web"
        web.mkdir()
        shutil.copy2(tone, web / "tone.wav")
        shutil.copy2(BASE / "assets/selandia-glass.svg", web / "preview.svg")
        (web / "project.json").write_text(json.dumps({"type": "web", "title": "Private Web audio fixture", "file": "index.html", "preview": "preview.svg"}))
        # A relative media file exercises the engine's resource response length;
        # a data URL or oscillator would hide the upstream format-error bug.
        (web / "index.html").write_text('<!doctype html><body style="background:teal"><audio src="tone.wav" autoplay loop></audio></body>')
        def pcm(name):
            path = artifacts / (name + ".pcm")
            with path.open("wb") as data, (artifacts / (name + "-record.log")).open("w") as log:
                recorder = subprocess.Popen(["parec", "--device=wallpaper-probe.monitor", "--raw", "--format=s16le", "--rate=48000", "--channels=2", "--latency-msec=20"],
                                            env=environment, stdout=data, stderr=log)
                time.sleep(2)
                (artifacts / (name + "-sinks.json")).write_text(command("pactl", "--format=json", "list", "sinks"))
                (artifacts / (name + "-streams.json")).write_text(command("pactl", "--format=json", "list", "sink-inputs"))
                (artifacts / (name + "-links.txt")).write_text(command("pw-link", "-l"))
                recorder.terminate()
                recorder.wait(timeout=3)
            samples = array("h", path.read_bytes())
            if len(samples) < 12000:
                raise RuntimeError("No PCM frames captured from the private sink")
            return math.sqrt(sum(sample * sample for sample in samples) / len(samples))
        for kind, path in (("video", video), ("scene", scene), ("web", web)):
            values = []
            selection = {"path": str(path), "mode": "live", "fallback": str(BASE / "assets/selandia-glass.svg")}
            wallpaper.save_settings({"assets": assets, "audio": {"muted": False, "volume": 50}, "selection": selection})
            child = start(kind, [sys.executable, "-B", str(BASE / "shell/wallpaper.py"), "run"])
            for _ in range(50):
                record = wallpaper_audio.current_renderer(selection)
                if record:
                    break
                time.sleep(.1)
            else:
                raise RuntimeError(kind + " renderer ownership record was not created")
            time.sleep(2)
            for muted, volume in ((False, 50), (False, 25), (True, 25)):
                name = f"{kind}-{'muted' if muted else volume}"
                changed = wallpaper.set_audio({"muted": muted, "volume": volume})
                if changed["restarted"] or wallpaper_audio.current_renderer(selection) != record or child.poll() is not None:
                    raise RuntimeError(name + " restarted or replaced the playing renderer")
                time.sleep(.6)
                rms = pcm(name)
                values.append(rms)
                print(f"PCM {name}: rms={rms:.2f}", flush=True)
            # mpv/PulseAudio use a perceptual (cubic) volume curve; SDL is linear.
            if values[0] < 100 or not .06 < values[1] / values[0] < .75 or values[2] > 2:
                raise RuntimeError(f"{kind} audio/mute/volume check failed: {values}")
            wallpaper.set_audio({"muted": False, "volume": 25})
            owned = [stream for stream in audio_backend.read_state()["streams"] if stream["kind"] == "sink-input" and
                     os.getpgid(int(stream["identity"][2])) == record["renderer"]["pid"]]
            if not owned:
                raise RuntimeError(kind + " has no owned audio stream")
            for stream in owned:
                command("pactl", "set-sink-input-volume", str(stream["index"]), "60%")
            wallpaper.set_audio({"muted": True, "volume": 25})
            time.sleep(1.2)
            current = {stream["index"]: stream for stream in audio_backend.read_state()["streams"]}
            if any(abs(current[stream["index"]]["volume"] - 60) > 1 or not current[stream["index"]]["mute"] for stream in owned):
                raise RuntimeError(kind + " mute reset another mixer's volume")
            wallpaper.set_audio({"muted": False, "volume": 25})
            for stream in owned:
                command("pactl", "set-sink-input-mute", str(stream["index"]), "1")
            wallpaper.set_audio({"muted": False, "volume": 30})
            time.sleep(1.2)
            current = {stream["index"]: stream for stream in audio_backend.read_state()["streams"]}
            if any(not current[stream["index"]]["mute"] or abs(current[stream["index"]]["volume"] - 30) > 1 for stream in owned):
                raise RuntimeError(kind + " volume reset another mixer's mute")
            if wallpaper_audio.current_renderer(selection) != record:
                raise RuntimeError(kind + " renderer identity changed during live mixing")
            # Reject one explicit setter after a real volume command succeeded.
            # Rollback must restore the actual PulseAudio state, which differs
            # from the saved preferences because another mixer muted the stream.
            before_settings = wallpaper.load_settings()
            before_streams = {stream["index"]: stream for stream in audio_backend.read_state()["streams"]}
            original_run = subprocess.run
            rejected = []
            def reject_one(command, **kwargs):
                if command[:2] == ["pactl", "set-sink-input-mute"] and not rejected:
                    rejected.append(command)
                    raise subprocess.CalledProcessError(1, command, stderr=b"injected setter failure")
                return original_run(command, **kwargs)
            try:
                with patch.object(wallpaper_audio.subprocess, "run", side_effect=reject_one):
                    wallpaper.set_audio({"muted": True, "volume": 45})
            except RuntimeError:
                pass
            else:
                raise RuntimeError(kind + " swallowed the rejected audio update")
            after_streams = {stream["index"]: stream for stream in audio_backend.read_state()["streams"]}
            if (wallpaper.load_settings() != before_settings or wallpaper_audio.current_renderer(selection) != record or
                    child.poll() is not None or any(after_streams[stream["index"]][key] != before_streams[stream["index"]][key]
                    for stream in owned for key in ("volume", "mute"))):
                raise RuntimeError(kind + " failed to recover actual mixing without replaying")
            print("PASS " + kind + ": rejected live update restores actual mixer and preferences without replay", flush=True)
            results.append({"kind": kind, "rms_50": round(values[0], 2), "rms_25": round(values[1], 2),
                "rms_muted": round(values[2], 2), "renderer_pid": record["renderer"]["pid"],
                "continuous_playback": "same supervisor and renderer start times", "external_mixer_preserved": "passed",
                "rejected_update_recovery": "passed", "result": "passed"})
            stop(child)
            time.sleep(.3)
        unavailable = dict(environment, PULSE_SERVER=f"unix:{runtime}/absent-audio-server")
        for kind, path in (("video", video), ("scene", scene), ("web", web)):
            wallpaper.save_settings({"assets": assets, "audio": {"muted": False, "volume": 50},
                                     "selection": {"path": str(path), "mode": "live", "fallback": str(BASE / "assets/selandia-glass.svg")}})
            name = kind + "-no-audio-server"
            child = start(name, [sys.executable, "-B", str(BASE / "shell/wallpaper.py"), "run"], env=unavailable)
            time.sleep(3)
            if child.poll() is not None or "using static fallback" in (artifacts / (name + ".log")).read_text():
                raise RuntimeError(name + " did not continue rendering")
            stop(child)
            print("PASS " + kind + ": renderer continues without an audio server", flush=True)
            next(result for result in results if result["kind"] == kind)["no_audio_server"] = "passed"
        # Two playback applications and one recording stream exercise the real
        # per-application backend without touching hardware or stopping players.
        long_tone = fixture / "application-tone.wav"
        command("ffmpeg", "-hide_banner", "-loglevel", "error", "-stream_loop", "20", "-i", str(tone), str(long_tone))
        apps = [start(name, ["paplay", "--client-name=" + name, "--property=application.name=" + name, str(long_tone)])
                for name in ("Probe Music", "Probe Browser")]
        recorder = start("application-recorder", ["parec", "--device=wallpaper-probe.monitor", "--client-name=Probe Recorder",
                         "--property=application.name=Probe Recorder"])
        for _ in range(30):
            streams = audio_backend.read_state()["streams"]
            found = {stream["name"]: stream for stream in streams if stream["name"] in ("Probe Music", "Probe Browser", "Probe Recorder")}
            if len(found) == 3:
                break
            time.sleep(.1)
        else:
            raise RuntimeError("Application playback/recording fixtures did not appear")
        # Policy initially restores a stream's remembered volume asynchronously.
        # Establish and let the untouched client's baseline settle first.
        command("pactl", "set-sink-input-volume", str(found["Probe Browser"]["index"]), "61%")
        time.sleep(1)
        found = {stream["name"]: stream for stream in audio_backend.read_state()["streams"]}
        untouched = dict(found["Probe Browser"])
        audio_backend.set_stream_audio(found["Probe Music"], volume=37)
        audio_backend.set_stream_audio(found["Probe Music"], muted=True)
        audio_backend.set_stream_audio(found["Probe Recorder"], volume=43, muted=True)
        current = {stream["name"]: stream for stream in audio_backend.read_state()["streams"]}
        if (abs(current["Probe Music"]["volume"] - 37) > 1 or not current["Probe Music"]["mute"] or
            abs(current["Probe Recorder"]["volume"] - 43) > 1 or not current["Probe Recorder"]["mute"] or
            current["Probe Browser"]["volume"] != untouched["volume"] or current["Probe Browser"]["mute"] != untouched["mute"] or
            any(child.poll() is not None for child in [*apps, recorder])):
            raise RuntimeError("Live application volume/mute was not scoped or interrupted a client: " +
                json.dumps({"streams": current, "untouched": untouched, "clients": [child.poll() for child in [*apps, recorder]]}))
        results.append({"kind": "application_audio", "playback_and_recording": "passed", "other_application_untouched": "passed", "clients_continue": "passed"})
        (artifacts / "results.json").write_text(json.dumps(results, indent=2) + "\n")
        print("PASS: continuous video/scene/Web PCM, live volume/mute, external mixer preservation and separate application playback/recording", flush=True)
    finally:
        for child in reversed(children):
            stop(child)
        for log in logs:
            log.close()


if __name__ == "__main__":
    main()
