# keyframe-extractor

A Claude Code skill that turns screen recordings into structured agent context.

Drop a `.mp4` or `.mov` into your chat, run `/extract`, and get back a set of keyframes and a timeline you can reason about directly in Claude Code.

---

## How it works

1. Samples frames from the video at a set interval
2. Filters out redundant frames using pixel-difference detection
3. Tags each kept frame with a timestamp and change score
4. Produces a `context.md` and `frames/` folder
5. Reads everything back into the conversation so Claude can analyze it inline

---

## Requirements

- Python 3
- ffmpeg

```bash
# macOS
brew install ffmpeg
```

---

## Install

```bash
git clone https://github.com/leeorlandi/keyframe-extractor
cd keyframe-extractor
./install.sh
```

This adds `/extract` as a slash command in Claude Code.

---

## Usage

In Claude Code, drop a screen recording into the chat and run:

```
/extract /path/to/recording.mov
```

Claude will extract keyframes, display them in sequence, and describe what's happening in the recording.

### Options

Pass flags directly to the extractor:

| Flag | Default | Description |
|---|---|---|
| `--threshold` | `0.04` | Change sensitivity (lower = more frames) |
| `--interval` | `0.5` | Seconds between candidate samples |
| `--output` | `./output` | Output directory |
| `--scale` | `320` | Frame width in pixels |

---

## Output

```
output/
  frames/         — selected keyframe images
  timeline.md     — timestamped change table
  context.md      — ready-to-paste agent prompt
```
