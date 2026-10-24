# Two-minute demonstration script

Status: storyboard only, not a recorded or verified demonstration. Record against a
specific commit after [live acceptance](milestones/live-verification.md). Use a test
invitation without revealing it. Hide credentials and private browser tabs.

| Time | Action / narration | Visible evidence |
|---|---|---|
| 0:00–0:15 | “A voice conversation with a separate worker for slower tasks.” Start and ask a short factual question. | Connected status, audible response |
| 0:15–0:35 | Ask the worker to find and explain the documented recovery limits. | Delegation begins; voice has only delegate_task |
| 0:35–0:55 | Continue speaking: “While you look that up, tell me what you can help with.” | Same worker task remains running |
| 0:55–1:20 | Finish speaking and leave silence for delivery. | Result arrives with a preamble and cited sources |
| 1:20–1:40 | Start another slow task, then press Cancel task. | Cancelled state; no late result narration |
| 1:40–2:00 | Show audio timing, stop the call, state verification limits. | Browser measurement label, released microphone, verification link |

The middle two scenes depend on the pending cancellation redesign. The current
implementation can cancel work on speech or a replacement delegation. Do not splice
recordings to imply that this behavior already works. Capture them only after the
redesign is merged and verified. If the worker finishes too quickly, use a clearly
labelled deterministic offline slow-worker demonstration rather than hiding a delay
in a live provider call. Do not publish measured latency from the offline demonstration.
