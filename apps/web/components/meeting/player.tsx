"use client";

/**
 * Motivation vs Logic
 * Motivation: The recording is the evidence behind everything on the page. It has to be large
 * enough to watch, captioned by default, navigable by topic, and in sync with the transcript.
 * Logic:
 * - The media plays at its true aspect ratio (set from videoWidth/videoHeight), as big as the
 *   stage allows. A recording with no picture plays in a native audio control with a note.
 * - Captions: the graph's captions URI (WebVTT) is read through resources/read and attached as a
 *   same-origin blob track, shown by default; the CC button toggles textTracks without remounting.
 * - Speed, keyboard shortcuts (space/k, j/l, arrows, c, m; ignored while typing) and a chapter
 *   strip under the video. Current time is reported (about 4 times a second) for transcript sync.
 * - quotient:// media is resolved through resources/read; one renewal on a playback error.
 * Bugs vs Fixes
 * Bug: Captions were only attached in a "sidecar" mode the server never produced, so the player
 * never showed subtitles. Fix: captions come from their own graph field and load by default.
 */
import type React from "react";
import { forwardRef, useCallback, useEffect, useImperativeHandle, useRef, useState } from "react";
import { Captions, CaptionsOff, Gauge } from "lucide-react";
import { formatMs } from "@/lib/format";
import type { Chapter } from "@/lib/digest";
import { mcp } from "@/lib/mcp/client";
import type { Playback } from "@/lib/types";

/** `play` starts playback after the jump. A person's click or key press passes it; a `?t=` link does not, so opening a shared link never plays audio by itself. */
export type PlayerHandle = { seek: (startMs: number, play?: boolean) => void };

const SPEEDS = [0.75, 1, 1.25, 1.5, 2];

type Props = {
  playback: Playback;
  captions: string;
  chapters: Chapter[];
  loading?: boolean;
  status?: string;
  onTime?: (ms: number) => void;
};

export const Player = forwardRef<PlayerHandle, Props>(function Player(
  { playback, captions, chapters, loading = false, status = "", onTime },
  ref,
) {
  const mediaRef = useRef<HTMLVideoElement>(null);
  const timeRef = useRef(0);
  const lastReport = useRef(0);
  const [src, setSrc] = useState("");
  const [track, setTrack] = useState("");
  const [note, setNote] = useState("");
  const [blank, setBlank] = useState(false);
  const [ratio, setRatio] = useState(16 / 9);
  const [showCaptions, setShowCaptions] = useState(true);
  const [speed, setSpeed] = useState(1);
  const [now, setNow] = useState(0);
  const [duration, setDuration] = useState(0);
  const renewalAttempted = useRef(false);
  const source = playback.original || playback.burned;

  const seekTo = useCallback((startMs: number, play = false) => {
    timeRef.current = startMs / 1000;
    const node = mediaRef.current;
    if (!node) return;
    const apply = () => {
      node.currentTime = startMs / 1000;
      if (play) node.play().catch(() => undefined); // the browser may refuse; the jump has still happened
    };
    if (node.readyState >= 1) apply();
    else node.addEventListener("loadedmetadata", apply, { once: true });
  }, []);

  useImperativeHandle(ref, () => ({ seek: seekTo }), [seekTo]);

  // Media URL.
  useEffect(() => {
    let cancel = false;
    renewalAttempted.current = false;
    void (async () => {
      try {
        if (!source) {
          setSrc("");
          setNote("The recording isn't available for playback.");
          return;
        }
        const next = source.startsWith("quotient://") ? (await mcp.readResource(source)).href ?? "" : source;
        if (cancel) return;
        setSrc(next);
        setNote(next ? "" : "The recording isn't available for playback.");
      } catch {
        if (!cancel) setNote("The recording could not be loaded.");
      }
    })();
    return () => {
      cancel = true;
    };
  }, [source]);

  // Captions track (same-origin blob, so no CORS is needed on the media host).
  useEffect(() => {
    let cancel = false;
    let created = "";
    void (async () => {
      if (!captions) {
        setTrack("");
        return;
      }
      try {
        const body = await mcp.readResource(captions);
        if (cancel) return;
        if (body.blob) {
          created = URL.createObjectURL(body.blob);
          setTrack(created);
        } else if (body.href) setTrack(body.href);
      } catch {
        if (!cancel) setTrack("");
      }
    })();
    return () => {
      cancel = true;
      if (created) URL.revokeObjectURL(created);
    };
  }, [captions]);

  // Toggle captions without remounting the media element.
  useEffect(() => {
    const node = mediaRef.current;
    if (!node) return;
    for (const textTrack of Array.from(node.textTracks)) textTrack.mode = showCaptions ? "showing" : "hidden";
  }, [showCaptions, track, src]);

  useEffect(() => {
    if (mediaRef.current) mediaRef.current.playbackRate = speed;
  }, [speed, src]);

  // Blank-picture probe.
  useEffect(() => {
    setBlank(false);
    if (!src) return;
    let cancel = false;
    const probe = document.createElement("video");
    probe.crossOrigin = "anonymous";
    probe.muted = true;
    probe.preload = "auto";
    const finish = (value: boolean) => {
      if (!cancel) {
        const live = mediaRef.current;
        if (live && value && Number.isFinite(live.currentTime)) timeRef.current = live.currentTime;
        setBlank(value);
      }
      probe.removeAttribute("src");
      probe.load();
    };
    probe.addEventListener("error", () => finish(false), { once: true });
    probe.addEventListener(
      "loadedmetadata",
      () => {
        if (probe.videoWidth === 0 || probe.videoHeight === 0) {
          finish(true);
          return;
        }
        void sampleBlank(probe).then(finish, () => finish(false));
      },
      { once: true },
    );
    probe.src = src;
    return () => {
      cancel = true;
      probe.removeAttribute("src");
      probe.load();
    };
  }, [src]);

  // Keyboard shortcuts for the whole meeting page; typing in a field is never intercepted.
  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      const target = event.target as HTMLElement | null;
      if (event.metaKey || event.ctrlKey || event.altKey) return;
      if (target && (target.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName))) return;
      const key = event.key.toLowerCase();
      // On a focused button or summary, Space and Enter belong to that control; the other shortcuts
      // keep working, so clicking a timestamp does not switch the keyboard off.
      if (target && /^(BUTTON|SUMMARY|A)$/.test(target.tagName) && (key === " " || key === "enter")) return;
      const node = mediaRef.current;
      if (!node) return;
      const jump = (seconds: number) => {
        node.currentTime = Math.max(0, Math.min(node.duration || Infinity, node.currentTime + seconds));
      };
      if (key === " " || key === "k") (node.paused ? node.play() : (node.pause(), Promise.resolve())).catch(() => undefined);
      else if (key === "j") jump(-10);
      else if (key === "l") jump(10);
      else if (key === "arrowleft" || key === "arrowright") {
        // Arrow keys keep scrolling and moving through lists unless the player (or nothing) has focus.
        if (target && target !== document.body && !/^(VIDEO|AUDIO)$/.test(target.tagName) && !target.closest(".q-stage")) return;
        jump(key === "arrowleft" ? -5 : 5);
      }
      else if (key === "c") setShowCaptions((value) => !value);
      else if (key === "m") node.muted = !node.muted;
      else return;
      event.preventDefault();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const Media = (blank ? "audio" : "video") as "video";
  const total = duration || Math.max(1, ...chapters.map((chapter) => chapter.endMs)) / 1000;

  return (
    <div className="q-stage-player">
      {src ? (
        <div className={blank ? "q-frame is-audio" : "q-frame"} style={blank ? undefined : ({ "--ratio": String(ratio) } as React.CSSProperties)}>
          <Media
            key={`${blank ? "audio" : "video"}:${src}`}
            ref={mediaRef}
            src={src}
            aria-label={blank ? "Meeting audio" : "Meeting video"}
            controls
            playsInline
            preload="metadata"
            onLoadedMetadata={(event) => {
              const node = event.currentTarget;
              if (node.videoWidth && node.videoHeight) setRatio(node.videoWidth / node.videoHeight);
              setDuration(Number.isFinite(node.duration) ? node.duration : 0);
              node.playbackRate = speed;
              // preload="metadata" paints no frame; nudging the playhead makes the first picture show.
              node.currentTime = timeRef.current > 0 ? timeRef.current : 0.05;
              for (const textTrack of Array.from(node.textTracks)) textTrack.mode = showCaptions ? "showing" : "hidden";
            }}
            onTimeUpdate={(event) => {
              const ms = event.currentTarget.currentTime * 1000;
              setNow(ms);
              if (onTime && Math.abs(ms - lastReport.current) > 240) {
                lastReport.current = ms;
                onTime(ms);
              }
            }}
            onError={(event) => {
              if (renewalAttempted.current || !source.startsWith("quotient://")) {
                setNote("This recording can't be played right now. Reload the page to try again.");
                return;
              }
              renewalAttempted.current = true;
              timeRef.current = event.currentTarget.currentTime;
              void mcp
                .readResource(source)
                .then((body) => {
                  if (body.href) {
                    setSrc(body.href);
                    setNote("");
                  } else setNote("This recording can't be played right now. Reload the page to try again.");
                })
                .catch(() => setNote("The recording could not be loaded."));
            }}
          >
            {track ? <track kind="subtitles" src={track} srcLang="en" label="English" default /> : null}
          </Media>
          {note ? <p className="q-player-note" role="alert">{note}</p> : null}
        </div>
      ) : (
        <div className="q-player-empty" role="status">
          <p>
            {loading
              ? "Loading the recording…"
              : status === "queued" || status === "working"
                ? "The recording can be played once the analysis has finished."
                : status === "failed" || status === "cancelled"
                  ? "There is no playable recording for this meeting."
                  : note || "Loading the recording…"}
          </p>
        </div>
      )}
      {src ? (
        <div className="q-player-bar">
          {chapters.length > 0 ? (
            <div className="q-chapters" role="group" aria-label="Topics">
              {chapters.map((chapter) => {
                const width = ((chapter.endMs - chapter.startMs) / 1000 / total) * 100;
                const on = now >= chapter.startMs && now < chapter.endMs;
                return (
                  <button
                    key={`${chapter.startMs}:${chapter.title}`}
                    type="button"
                    className={on ? "q-chapter is-on" : "q-chapter"}
                    style={{ flexGrow: Math.max(0.5, width) }}
                    title={`${formatMs(chapter.startMs)} · ${chapter.title}`}
                    aria-label={`Play topic ${chapter.title} from ${formatMs(chapter.startMs)}`}
                    onClick={() => seekTo(chapter.startMs, true)}
                  >
                    <span>{chapter.title}</span>
                  </button>
                );
              })}
            </div>
          ) : (
            <span />
          )}
          <div className="q-player-tools">
            {track ? (
              <button
                type="button"
                className={showCaptions ? "q-icon-btn is-on" : "q-icon-btn"}
                aria-pressed={showCaptions}
                aria-label="Captions"
                title={showCaptions ? "Hide captions (C)" : "Show captions (C)"}
                onClick={() => setShowCaptions((value) => !value)}
              >
                {showCaptions ? <Captions size={16} aria-hidden="true" /> : <CaptionsOff size={16} aria-hidden="true" />}
              </button>
            ) : null}
            <label className="q-speed" title="Playback speed">
              <Gauge size={14} aria-hidden="true" />
              <span className="q-speed-label">Speed</span>
              <select value={speed} onChange={(event) => setSpeed(Number(event.target.value))}>
                {SPEEDS.map((value) => (
                  <option key={value} value={value}>{value}×</option>
                ))}
              </select>
            </label>
          </div>
        </div>
      ) : null}
      {blank ? <p className="q-muted q-player-note is-info">This recording appears to have no picture, so only the audio plays.</p> : null}
    </div>
  );
});

async function sampleBlank(probe: HTMLVideoElement): Promise<boolean> {
  const duration = Number.isFinite(probe.duration) ? probe.duration : 0;
  const points = duration > 3 ? [0.1, 0.5, 0.9].map((share) => duration * share) : [0];
  const canvas = document.createElement("canvas");
  canvas.width = 32;
  canvas.height = 18;
  const context = canvas.getContext("2d", { willReadFrequently: true });
  if (!context) return false;
  for (const at of points) {
    await new Promise<void>((resolve, reject) => {
      const timer = window.setTimeout(() => reject(new Error("seek timeout")), 4000);
      probe.addEventListener(
        "seeked",
        () => {
          window.clearTimeout(timer);
          resolve();
        },
        { once: true },
      );
      probe.currentTime = at;
    });
    context.drawImage(probe, 0, 0, canvas.width, canvas.height);
    const data = context.getImageData(0, 0, canvas.width, canvas.height).data;
    let peak = 0;
    for (let index = 0; index < data.length; index += 4) {
      peak = Math.max(peak, data[index], data[index + 1], data[index + 2]);
    }
    if (peak > 40) return false;
  }
  return true;
}
