#!/usr/bin/env python3
"""
extract.py — Video to Keyframe Context

Usage:
    python3 extract.py <video_file> [--threshold 0.04] [--interval 0.5] [--output ./output]

Extracts keyframes from a screen recording and produces:
  output/frames/   — selected keyframe images
  output/timeline.md — structured timeline for agent context
  output/context.md  — ready-to-paste agent prompt bundle
"""

import argparse
import json
import math
import os
import shutil
import struct
import subprocess
import sys
import zlib
from pathlib import Path


# ── PNG pixel difference (no numpy required) ──────────────────────────────────

def read_png_pixels(path: str) -> list[int]:
    """Read PNG and return flat list of grayscale pixel values (0-255)."""
    with open(path, "rb") as f:
        sig = f.read(8)
        if sig != b"\x89PNG\r\n\x1a\n":
            raise ValueError(f"Not a valid PNG: {path}")
        pixels = []
        idat_chunks = []
        width = height = 0
        bit_depth = color_type = 0
        while True:
            length_bytes = f.read(4)
            if not length_bytes:
                break
            length = struct.unpack(">I", length_bytes)[0]
            chunk_type = f.read(4).decode("ascii", errors="replace")
            data = f.read(length)
            f.read(4)  # CRC
            if chunk_type == "IHDR":
                width, height = struct.unpack(">II", data[:8])
                bit_depth, color_type = data[8], data[9]
            elif chunk_type == "IDAT":
                idat_chunks.append(data)
            elif chunk_type == "IEND":
                break
        raw = zlib.decompress(b"".join(idat_chunks))
        # Channels per pixel
        ch = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}.get(color_type, 3)
        stride = width * ch + 1  # +1 for filter byte
        gray_vals = []
        prev_row = [0] * (width * ch)
        for y in range(height):
            row_data = raw[y * stride: y * stride + stride]
            filt = row_data[0]
            raw_row = list(row_data[1:])
            # Reconstruct filter
            recon = []
            for i, byte in enumerate(raw_row):
                a = recon[i - ch] if i >= ch else 0
                b = prev_row[i]
                c = prev_row[i - ch] if i >= ch else 0
                if filt == 0:
                    recon.append(byte)
                elif filt == 1:
                    recon.append((byte + a) & 0xFF)
                elif filt == 2:
                    recon.append((byte + b) & 0xFF)
                elif filt == 3:
                    recon.append((byte + (a + b) // 2) & 0xFF)
                elif filt == 4:
                    p = a + b - c
                    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                    pr = a if pa <= pb and pa <= pc else (b if pb <= pc else c)
                    recon.append((byte + pr) & 0xFF)
                else:
                    recon.append(byte)
            prev_row = recon
            # Convert to grayscale
            for x in range(width):
                base = x * ch
                if color_type in (0, 1):  # grayscale
                    gray_vals.append(recon[base])
                elif color_type == 2:  # RGB
                    r, g, b = recon[base], recon[base+1], recon[base+2]
                    gray_vals.append(int(0.299*r + 0.587*g + 0.114*b))
                elif color_type == 6:  # RGBA
                    r, g, b = recon[base], recon[base+1], recon[base+2]
                    gray_vals.append(int(0.299*r + 0.587*g + 0.114*b))
                else:
                    gray_vals.append(recon[base])
        return gray_vals, width, height


def frame_diff(pixels_a: list[int], pixels_b: list[int]) -> float:
    """Mean absolute difference between two grayscale pixel arrays, normalized 0-1."""
    if len(pixels_a) != len(pixels_b) or not pixels_a:
        return 1.0
    total = sum(abs(a - b) for a, b in zip(pixels_a, pixels_b))
    return total / (len(pixels_a) * 255)


# ── Video utilities ────────────────────────────────────────────────────────────

def get_video_duration(video_path: str) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json",
         "-show_format", video_path],
        capture_output=True, text=True
    )
    info = json.loads(result.stdout)
    return float(info["format"]["duration"])


def extract_frame(video_path: str, timestamp: float, out_path: str, scale: int = 320) -> bool:
    """Extract a single frame at timestamp, scaled to width=scale."""
    result = subprocess.run(
        ["ffmpeg", "-ss", str(timestamp), "-i", video_path,
         "-vframes", "1", "-vf", f"scale={scale}:-1",
         "-y", out_path],
        capture_output=True
    )
    return result.returncode == 0 and os.path.exists(out_path)


# ── Core pipeline ──────────────────────────────────────────────────────────────

def extract_keyframes(
    video_path: str,
    output_dir: str,
    threshold: float = 0.02,
    interval: float = 0.5,
    scale: int = 320,
    min_frames: int = 5,
) -> list[dict]:
    """
    Extract keyframes from video.
    Returns list of {index, timestamp, path, diff_score} dicts.
    """
    frames_dir = os.path.join(output_dir, "frames")
    tmp_dir = os.path.join(output_dir, "_tmp")
    os.makedirs(frames_dir, exist_ok=True)
    os.makedirs(tmp_dir, exist_ok=True)

    duration = get_video_duration(video_path)
    timestamps = [round(t * interval, 3)
                  for t in range(int(duration / interval) + 1)
                  if t * interval <= duration]

    print(f"  Video duration: {duration:.1f}s")
    print(f"  Sampling {len(timestamps)} candidate frames at {interval}s intervals...")

    # Extract all candidate frames to tmp
    candidates = []
    for i, ts in enumerate(timestamps):
        tmp_path = os.path.join(tmp_dir, f"frame_{i:04d}.png")
        if extract_frame(video_path, ts, tmp_path, scale=scale):
            candidates.append({"timestamp": ts, "path": tmp_path, "index": i})

    print(f"  Extracted {len(candidates)} candidate frames, running diff filter...")

    # Score all candidates using diff filter
    selected = []
    prev_pixels = None
    readable = []  # all candidates we could read, for fallback
    for cand in candidates:
        try:
            pixels, w, h = read_png_pixels(cand["path"])
        except Exception:
            continue
        diff = 0.0 if prev_pixels is None else frame_diff(prev_pixels, pixels)
        entry = {**cand, "diff_score": round(diff, 4)}
        readable.append(entry)
        if prev_pixels is None or diff >= threshold:
            selected.append(entry)
            prev_pixels = pixels

    print(f"  {len(readable)} frames readable, {len(selected)} above threshold.")

    # If too few frames selected, fall back to evenly-spaced picks from all readable frames
    if len(selected) < min_frames and len(readable) >= min_frames:
        step = len(readable) / min_frames
        selected = [readable[int(i * step)] for i in range(min_frames)]
        print(f"  Falling back to {min_frames} evenly-spaced frames.")
    elif len(selected) < min_frames and readable:
        # Fewer readable frames than min_frames — just use all of them
        selected = readable

    keyframes = []
    for kf_index, cand in enumerate(selected, start=1):
        dest = os.path.join(frames_dir, f"{kf_index:04d}_t{cand['timestamp']:.2f}s.png")
        shutil.copy2(cand["path"], dest)
        keyframes.append({
            "index": kf_index,
            "timestamp": cand["timestamp"],
            "path": dest,
            "filename": os.path.basename(dest),
            "diff_score": cand["diff_score"],
        })

    # Cleanup tmp
    shutil.rmtree(tmp_dir, ignore_errors=True)
    return keyframes


def build_timeline(keyframes: list[dict], video_name: str) -> str:
    lines = [
        f"## Keyframe Timeline — `{video_name}`\n",
        f"**Total keyframes:** {len(keyframes)}\n",
        "| # | Timestamp | Change Score | Frame |",
        "|---|-----------|--------------|-------|",
    ]
    for kf in keyframes:
        score = "—" if kf["diff_score"] == 0.0 else f"{kf['diff_score']:.3f}"
        note = "Initial state" if kf["index"] == 1 else "Visual change"
        lines.append(
            f"| {kf['index']} | {kf['timestamp']:.2f}s | {score} | `{kf['filename']}` |"
        )
    return "\n".join(lines)


def build_context_prompt(keyframes: list[dict], video_name: str, timeline: str) -> str:
    frame_list = "\n".join(
        f"  - [{kf['filename']}](frames/{kf['filename']}) at {kf['timestamp']:.2f}s"
        for kf in keyframes
    )
    return f"""# Screen Recording Analysis: `{video_name}`

The following keyframes were automatically extracted from a screen recording.
Each frame represents a moment of meaningful visual change.

## Frames
{frame_list}

{timeline}

## Instructions for Agent
Review the keyframes in sequence. Use the timestamps and change scores to understand
the progression of events. Describe what behavior you observe, identify any anomalies,
and suggest relevant code areas to investigate.
"""


# ── CLI ────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Extract keyframes from a screen recording for agent context."
    )
    parser.add_argument("video", help="Path to input video file (.mp4, .mov, etc.)")
    parser.add_argument("--threshold", type=float, default=0.04,
                        help="Change detection threshold 0-1 (default: 0.04)")
    parser.add_argument("--interval", type=float, default=0.5,
                        help="Sampling interval in seconds (default: 0.5)")
    parser.add_argument("--output", default=None,
                        help="Output directory (default: .keyframes/ next to the video)")
    parser.add_argument("--scale", type=int, default=320,
                        help="Frame width in pixels (default: 320)")
    parser.add_argument("--min-frames", type=int, default=5,
                        help="Minimum keyframes to extract regardless of threshold (default: 5)")
    args = parser.parse_args()

    video_path = os.path.abspath(args.video)
    if not os.path.exists(video_path):
        # macOS screen recording filenames use U+202F (narrow no-break space) before AM/PM.
        # When the path is typed or pasted it often comes through as a regular space.
        # Try swapping regular spaces → U+202F to find the actual file.
        candidate = video_path.replace(" ", "\u202f")
        if os.path.exists(candidate):
            video_path = candidate
        else:
            print(f"Error: file not found: {video_path}", file=sys.stderr)
            sys.exit(1)

    video_name = Path(video_path).name
    output_dir = os.path.abspath(args.output) if args.output else os.path.join(os.getcwd(), ".keyframes")
    os.makedirs(output_dir, exist_ok=True)

    print(f"\nKeyframe Extractor")
    print(f"  Input:     {video_name}")
    print(f"  Output:    {output_dir}")
    print(f"  Threshold: {args.threshold}")
    print(f"  Interval:  {args.interval}s\n")

    keyframes = extract_keyframes(
        video_path, output_dir,
        threshold=args.threshold,
        interval=args.interval,
        scale=args.scale,
        min_frames=args.min_frames,
    )

    if not keyframes:
        print("No keyframes extracted. Try lowering --threshold.")
        sys.exit(1)

    print(f"\n  Selected {len(keyframes)} keyframes.\n")

    video_name_clean = Path(video_path).stem
    timeline = build_timeline(keyframes, video_name)
    context = build_context_prompt(keyframes, video_name, timeline)

    timeline_path = os.path.join(output_dir, "timeline.md")
    context_path = os.path.join(output_dir, "context.md")

    with open(timeline_path, "w") as f:
        f.write(timeline)
    with open(context_path, "w") as f:
        f.write(context)

    print(f"Output written to: {output_dir}/")
    print(f"  frames/       — {len(keyframes)} keyframe images")
    print(f"  timeline.md   — structured timeline")
    print(f"  context.md    — ready-to-paste agent prompt\n")
    print(f"To use with Claude Code:")
    print(f"  Paste the contents of context.md into your prompt,")
    print(f"  then attach the keyframe images from frames/\n")


if __name__ == "__main__":
    main()
