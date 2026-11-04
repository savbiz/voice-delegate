# Two-minute demonstration script

Status: the demonstration linked from the README was recorded on 2026-11-04 against the hosted
deployment of v0.5.0 with GPT-Live. It follows scenes 1 to 4 below, then scrolls through the
cited sources, the conversation recap and the connection timings. The Cancel task scene is not
in that recording. Use a test invitation without revealing it. Hide credentials and private
browser tabs.

| Time | Action / narration | Visible evidence |
|---|---|---|
| 0:00–0:15 | “A voice conversation with a separate worker for slower tasks.” Start and ask a short factual question. | Connected status, audible response |
| 0:15–0:35 | Ask the worker to find and explain the documented recovery limits. | Delegation begins; voice has only delegate_task |
| 0:35–0:55 | Continue speaking: “While you look that up, tell me what you can help with.” | Same worker task remains running |
| 0:55–1:20 | Finish speaking and leave silence for delivery. | Result arrives with a preamble and cited sources |
| 1:20–1:40 | Start another slow task, then press Cancel task. | Cancelled state; no late result narration |
| 1:40–2:00 | Show audio timing, stop the call, state verification limits. | Browser measurement label, released microphone, verification link |

The middle two scenes require `VOICE_INTENT_CANCELLATION=true`. The default
mode still cancels work on speech or a replacement delegation. Do not splice
recordings to imply that this behavior already works. Capture them only after the
opt-in path is merged and verified live. If the worker finishes too quickly, use a clearly
labelled deterministic offline slow-worker demonstration rather than hiding a delay
in a live provider call. Do not publish measured latency from the offline demonstration.

## Recording guide

Everything above is the storyboard. This section is how to record it. Nothing here has been
recorded yet; update the status line at the top with the commit and date once a take is
published.

### Before recording

- Use the hosted frontend with a throwaway invitation, or a local stack. Set
  `VOICE_INTENT_CANCELLATION=true` on the backend and start a new session, because scenes 3
  and 4 depend on it.
- Use headphones, so the microphone does not pick up the agent's voice; Cap captures that
  directly as system audio. Close other tabs, hide the bookmarks bar and the extensions you do
  not need, and turn off notifications.
- Never show the invitation code, an API key or a private tab. Type the code before you start
  the recording, or crop it out.
- Size the browser window to 1280 × 720 so the text stays readable after compression.
- Do a full dry run first and read the captions aloud as you go. A take under two minutes
  with no dead air is easier to watch than a long one.

### Recording with Cap

macOS's built-in recorders (Cmd+Shift+5 and QuickTime) record your microphone but not the
computer's own sound, so the agent's voice would be missing. [Cap](https://cap.so) is a free,
open-source screen recorder that can capture both and saves an ordinary mp4 file.

1. Install Cap and allow **Screen Recording** and **Microphone** when macOS asks. If it does
   not pick the permissions up, quit and reopen it.
2. Choose **Studio** mode, which saves the recording on your Mac.
3. Select the Chrome window with the app open, not the whole display.
4. Pick your real microphone by name, not an automatic choice (an iPhone nearby can otherwise
   be selected). Turn **System audio** on.
5. Record a 15-second test: say hello, wait for the answer, stop and play it back. You should
   hear your voice and the agent's.

Cap mixes both sounds into a single audio track, so the recording cannot be edited to adjust
one voice separately. Check the levels in the test before the real take.

### Take-by-take script

Say each line naturally, then wait for the result before moving on. These prompts use only
what the worker supports (a calculator and the bundled project documentation).

| Scene | You say | What should be visible |
|---|---|---|
| 1 | "Hi. What can you help me with?" | Connected status, the agent answering, captions |
| 2 | "What is 1,287 times 43? Work it out for me." | Task state changes, then the calculated answer |
| 3 | "Look up what the documentation says about session limits." | Delegation running, then a cited source panel |
| 4 | While it works: "Meanwhile, tell me what you can do." | The task keeps running; its result waits for a pause |
| 5 | Start another lookup and press **Cancel task** | Cancelled state, no late narration |
| 6 | Press **Stop** | Microphone indicator clears, session closed |

If a scene goes wrong, stop and start again from the top rather than editing two takes
together. The scenes above are the ones the storyboard's evidence column checks.

### Trim and export

Trim dead air at the start and end in Cap's editor. The first connection to a sleeping hosted
backend can take about ten seconds, so open the app once before recording to warm it up.

Export with **File**, **MP4**, **720p**, **30 FPS**, quality **Web** and **Optimize file size**
turned on. GitHub accepts README videos up to 10 MB, and a 90-second recording at these
settings is typically well under that. Check the exported file's size. If it is too large,
re-encode it with [ffmpeg](https://ffmpeg.org/):

```sh
ffmpeg -i demo.mp4 -vf "scale=1280:-2,fps=30" -c:v libx264 -crf 28 -preset slow \
  -c:a aac -b:a 96k -movflags +faststart demo-small.mp4
```

### Putting it in the README

1. On github.com, open README.md and choose **Edit**.
2. Drag `demo.mp4` into the editor at the place you want it. GitHub uploads it and inserts a
   plain URL on its own line; leave it on its own line and GitHub shows it as a video player.
3. Add one sentence above it saying what it shows and which commit it was recorded on,
   then commit through a branch and a pull request as usual.
4. Update the status line at the top of this file and the first item under "Next, for v1.0"
   in [the roadmap](roadmap.md).
