---
name: pulse-check
description: >
  Prove a long-running job is ACTUALLY alive with independent evidence, not
  a status field. Invoke whenever the user asks "is it running / is it
  stuck / make sure it's working", whenever you are about to report a
  long job as in-progress, whenever a progress number has not changed
  between two looks, and after starting any background process you plan to
  walk away from.
---

# Pulse check (is it really running?)

A status field that says "running" only proves the record was written once.
This repo has real scar tissue here: the 2026-07-10 re-voice pass died
silently because the server ran as a background child of Claude Code, and
"the button seems stuck" incidents are why the Queue page exists. Liveness
is proven by CHANGE plus a PHYSICAL signal, never by a label.

## The check (two samples, ~20-30 s apart, then judge)

Collect at least TWO independent signals, one from each group:

**Group A, forward motion (sample twice, compare):**
- The job's progress/stage via its API: `GET /api/gatherer`,
  `GET /api/jobs/{id}`, `GET /api/projects/{pid}/produce`,
  `GET /api/autopilot/{aid}`, `GET /api/queue`.
- The artifact itself growing: output file size, frames appearing in the
  job dir, log line count.

**Group B, physical evidence (one sample is fine):**
- Record persistence: `gather.json` / `study.json` / `job.json` mtime is
  recent (the gatherer persists every ~2 s while working).
- `nvidia-smi --query-gpu=utilization.gpu,memory.used --format=csv,noheader`
  during GPU stages (transcribe/images/animate load the GPU; frames/motion
  stages are CPU+disk, so LOW GPU there is normal, not stuck).
- `data/server.log` tail advancing; the uvicorn process existing at all
  (`netstat -ano | findstr :8000`).

**Verdict rules:**
- Progress delta > 0 between samples = alive. Say so with the numbers
  ("22.0% → 29.7% in 25 s").
- No delta but the stage is one of the known slow-silent spans (model
  download, ComfyUI first-load, moviepy encode inside assemble, one-take
  TTS synthesis) = sample again with a longer gap before judging; say which
  span it is.
- No delta twice AND stale mtimes AND idle GPU/CPU = stuck. Report WHERE
  (job, stage, last-change time), then the unstick path: cancel via
  `POST /api/jobs/{id}/cancel` (stops at next checkpoint), check
  `data/server.log` tail for the exception, never taskkill a process
  mid-GPU-job as the first move.

## Monitoring economics (user, 2026-07-12)

The cheapest monitor is a LOCAL script, not a model. A background Python
loop polling an API costs zero tokens; the model should wake only when the
watcher window ends (~10 min, the background cap) or the state changes.
Never spawn a subagent (any size) just to poll: a spawn starts cold and
costs more than the wakeup it replaces. Make watchers print only on state
CHANGE so each wakeup reads a handful of lines.

## Auto-remediation (user, 2026-07-12: "if it detects that, immediately fix")

A stuck or failed verdict is a TRIGGER, not a report. Fix first, tell the
user what happened after (they should read "it broke at X, I did Y, it is
moving again", not a question). The ladder for this studio:

1. **Read the actual error**: the job record's `error`/`msg`, then the tail
   of `data/server.log` for the traceback. Diagnose before touching.
2. **Download failures** (gatherer/study): retry once; yt-dlp
   signature/extractor errors → `pip install -U yt-dlp` then retry;
   age/members gate → needs `data/gatherer/cookies.txt` (tell the user,
   this one is theirs); video gone → substitute the next ranked candidate
   via `POST /api/studies/{sid}/gather` and say so.
3. **GPU OOM**: `POST /api/gpu/release`, kill the ACE sidecar if listening,
   retry; still OOM → step the model down (large-v3 → distil-large-v3) and
   note the substitution honestly in the record.
4. **Stage exception in pure-logic code**: fix the bug, hot-reload the
   module (`POST /api/dev/reload`), resubmit the job. Route/engine changes
   need the restart discipline (queue idle first).
5. **Stall with no exception**: cancel at the checkpoint
   (`POST /api/jobs/{id}/cancel`), inspect what stage it froze in, fix,
   resubmit. Never leave a zombie occupying the single-worker queue.
6. **Server down** (port 8000 dead): restart detached per CLAUDE.md, then
   resubmit interrupted work (records marked "interrupted" list exactly
   what died).
7. After any fix: pulse-check again to PROVE the restart took (delta +
   physical signal), then continue the original task.

## Standing rules

- Never tell the user something is running based on one static read.
- When starting a background monitor/process, verify it produced its FIRST
  output before walking away (a watcher that dies instantly looks identical
  to a quiet one).
- Report liveness with the evidence, not adjectives: numbers, timestamps,
  deltas.
