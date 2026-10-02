#!/usr/bin/env python3
"""Bring oversized media under Cloudflare's 25 MiB per-asset limit.

Cloudflare's static-asset uploader rejects any single file over 25 MiB and
fails the ENTIRE deploy, so this has to run before the first push. Oversized
video is re-encoded in place (capped at 720p) with a bitrate solved from the
clip's own duration so the result lands under the cap on the first try.

The untouched download is kept beside it as <name>.orig.<ext> for re-runs and
is excluded from git by .gitignore, so re-encoding is never lossy-on-lossy.
"""
import os
import shlex
import subprocess
import sys

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "site")
LIMIT = 24 * 1024 * 1024          # 1 MiB of headroom under Cloudflare's 25 MiB
TARGET = 20 * 1024 * 1024         # aim here so bitrate-solve overshoot is safe
VIDEO_EXTS = (".mp4", ".mov", ".m4v", ".webm")
MAX_HEIGHT = 720
AUDIO_KBPS = 96


def run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True)


def probe(path, entries):
    r = run(["ffprobe", "-v", "error", "-show_entries", entries,
             "-of", "default=noprint_wrappers=1:nokey=1", path])
    return [l for l in r.stdout.strip().splitlines() if l and l != "N/A"]


def transcode(src, dst, duration, has_audio, height):
    audio_kbps = AUDIO_KBPS if has_audio else 0
    video_kbps = int((TARGET * 8 / duration) / 1000) - audio_kbps
    video_kbps = max(400, video_kbps)
    scale = ["-vf", f"scale=-2:{MAX_HEIGHT}"] if height and height > MAX_HEIGHT else []
    common = ["ffmpeg", "-y", "-loglevel", "error", "-i", src, *scale,
              "-c:v", "libx264", "-preset", "slow", "-b:v", f"{video_kbps}k",
              "-maxrate", f"{int(video_kbps * 1.5)}k", "-bufsize", f"{video_kbps * 2}k",
              "-pix_fmt", "yuv420p", "-movflags", "+faststart"]
    audio = ["-c:a", "aac", "-b:a", f"{audio_kbps}k"] if has_audio else ["-an"]
    log = os.path.join(os.path.dirname(dst), ".x264-passlog")

    # Two-pass: pass 1 measures complexity so pass 2 hits the bitrate target
    # closely. A single pass at this bitrate can overshoot past the cap.
    p1 = run([*common, "-pass", "1", "-passlogfile", log, "-an",
              "-f", "mp4", os.devnull])
    if p1.returncode != 0:
        return False, p1.stderr.strip()
    p2 = run([*common, "-pass", "2", "-passlogfile", log, *audio, dst])
    for leftover in (log + "-0.log", log + "-0.log.mbtree", log + ".log",
                     log + ".log.mbtree"):
        if os.path.exists(leftover):
            os.remove(leftover)
    if p2.returncode != 0:
        return False, p2.stderr.strip()
    return True, None


def main():
    if not run(["ffmpeg", "-version"]).returncode == 0:
        sys.exit("ffmpeg not found on PATH")

    oversized = []
    for root, _, files in os.walk(OUT):
        for fn in files:
            if ".orig." in fn:
                continue
            p = os.path.join(root, fn)
            if os.path.getsize(p) > LIMIT:
                oversized.append(p)

    if not oversized:
        print("No asset over 24 MiB. Nothing to do.")
        return

    failures = []
    for path in sorted(oversized):
        rel = os.path.relpath(path, OUT)
        size = os.path.getsize(path)
        base, ext = os.path.splitext(path)
        if ext.lower() not in VIDEO_EXTS:
            print(f"  ! {rel} is {size / 1048576:.1f} MiB and is not video — "
                  f"handle it by hand (Cloudflare will reject it)")
            failures.append(rel)
            continue

        original = f"{base}.orig{ext}"
        if not os.path.exists(original):
            os.replace(path, original)

        dur = probe(original, "format=duration")
        if not dur:
            print(f"  ! {rel}: could not read duration")
            failures.append(rel)
            continue
        duration = float(dur[0])
        height = probe(original, "stream=height")
        height = int(height[0]) if height else 0
        has_audio = "audio" in run(
            ["ffprobe", "-v", "error", "-select_streams", "a",
             "-show_entries", "stream=codec_type", "-of", "csv=p=0", original]
        ).stdout

        print(f"  transcoding {rel} ({size / 1048576:.1f} MiB, "
              f"{duration:.1f}s, {height}p)...")
        ok, err = transcode(original, path, duration, has_audio, height)
        if not ok:
            os.replace(original, path)
            print(f"  ! {rel}: ffmpeg failed — {err}")
            failures.append(rel)
            continue
        new = os.path.getsize(path)
        flag = "" if new <= LIMIT else "  <-- STILL OVER THE CAP"
        print(f"    -> {new / 1048576:.1f} MiB "
              f"({100 - new * 100 // size}% smaller){flag}")
        if new > LIMIT:
            failures.append(rel)

    print(f"\nOversized assets: {len(oversized)}, unresolved: {len(failures)}")
    if failures:
        sys.exit(1)


if __name__ == "__main__":
    main()
