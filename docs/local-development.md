# Local development

Run `scripts/start-local.sh` for the portal and MCP server. When MinIO is
available in the Docker container `engine-minio-1`, use
`scripts/start-local-minio.sh` to start the same app with bucket
`axion-meeting-local` at `http://127.0.0.1:9000`. It creates the bucket when
it does not exist.

The MinIO launcher reads its credentials from the container and passes them to
the media upload subprocess only. Keep `QUOTIENT_S3_ACCESS_KEY_ID` and
`QUOTIENT_S3_SECRET_ACCESS_KEY` separate from the normal `AWS_*` credential
chain; the worker uses that chain for Bedrock. The endpoint, bucket, and
credential variable names can be overridden through the corresponding
`QUOTIENT_*` environment variables.

With `QUOTIENT_S3_ENDPOINT_URL` set, the worker uploads the media to that local
endpoint and runs audio transcription. It records a note that visual analysis
was skipped, because Bedrock cannot fetch media from a developer's MinIO
instance. Sonic streaming also needs an AWS identity authorized for the Sonic
model; a Bedrock API key alone is not sufficient for the bidirectional stream.

In local mode, meeting projections are saved atomically in
`.local/run/meetings.json` so they survive an app restart. An analysis interrupted
by a restart is automatically queued again from its source media; binary export
bytes are not stored in this JSON file. Playback uses a one-hour MinIO presigned
URL and supports browser byte-range requests for seeking.

During analysis, task progress messages report the active pipeline phase. The
progress bar stays indeterminate while model work is in progress because the
number of model calls depends on transcript length and evidence.

## Behaviour to know about

**Auth bypass.** `QUOTIENT_AUTH_BYPASS=1` is honoured only when `QUOTIENT_ENVIRONMENT=local`
(`scripts/start-local.sh` sets both). With the environment unset or anything else, it is ignored
and requests need a real token. Staging and production always ignore it.

**Playback.** In local MinIO mode the worker uploads a playback copy to
`derivatives/<meeting_id>-0.mp4` and the player signs that key; the submitted `object_key` is only
a fallback. A recording with no picture plays in an audio control. A meeting that never ingested
anything gets no playback URL.

**Failures.** `failure_message` is a plain sentence ("This file is not a readable audio or video
recording."), never a path or command. The full exception is written to the API log
(`.local/run/api.log`, line starting `analysis failed:`).

**Cancel and restart.** Cancelling stops the audio stream and every later model call. After an API
restart, unfinished meetings resume from their source, at most twice (`MAX_RESUMES`); a third
interruption fails the meeting.

**Transcription recovery.** A transcription segment the provider rejects is retried once, then
re-run in 90-second windows; only windows that still fail are marked "Not transcribed" and listed
as coverage gaps. Configuration failures (no model access, HTTP 401/403) fail the meeting instead.
If nothing at all could be transcribed the meeting fails.

**Timeouts.** ffmpeg and ffprobe calls time out after `QUOTIENT_MEDIA_TIMEOUT_SECONDS` (default
3600; ffprobe 120) and uploads after `QUOTIENT_UPLOAD_TIMEOUT_SECONDS` (default 1800).

**Settings page.** Only the two API keys are writable; the model and region values are fixed by
the release and shown read-only. Changing settings requires a same-origin JSON request.

**Downloads.** `brief.pdf` and `brief.html` of a meeting that needs review carry the confirmed
sentences under a "Partial brief" notice. The `quotient://meetings/{id}/brief` resource still
reports `withheld: true`; that MCP contract is unchanged.

**Benchmark harness.** `.venv/bin/python scripts/bench_meeting.py <object_key> <label>` submits a file under
`derivatives/` and writes `submitted/result/summary/graph` JSON to `.local/run/bench/`. See
`docs/quality-ledger.md` for results.

**Long recordings and sign-in.** Transcription streams in real time (about 6 minutes per segment,
so an 84-minute recording takes 84+ minutes) and needs valid AWS credentials the whole time. An
HTTP 401/403 re-reads the credentials once; if the sign-in has lapsed the meeting fails with
"Sign in to AWS again, then start the analysis again." Finished segments are saved to
`.local/run/transcripts/` (private, keyed by owner, exact audio, model, prompt version and context
names; pruned after 7 days or past 25 files), so starting the analysis again streams only the
missing segments. Set `QUOTIENT_TRANSCRIPT_CACHE_DIR=off` to disable it or to a directory to enable
it outside local mode. Segments that lost a window to the provider are not saved.
