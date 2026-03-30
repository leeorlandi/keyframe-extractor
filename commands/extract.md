Run the keyframe extractor on a video file, then read and display all results inline.

Steps:
1. The video path is: $ARGUMENTS
   - If the path has spaces, handle them correctly when passing to the script.
   - If no path was provided, ask the user to drop a video file into the chat.

2. Run the extractor:
   ```
   python3 REPO_PATH/extract.py '<video_path>'
   ```

3. The output lands in `.keyframes/` inside the current working directory (the project you're in).
   After extraction completes, read: `.keyframes/context.md` (relative to cwd)

4. Read every image in `.keyframes/frames/` (relative to cwd, sorted by filename).

5. Present everything inline:
   - Show the timeline from context.md
   - Display each keyframe image in sequence with its timestamp
   - After showing all frames, describe what you observe happening in the recording — note any state changes, errors, loading behavior, or interactions visible across the sequence
