"use client";

/**
 * Motivation vs Logic
 * Motivation: Playback is a field of the graph. A citation seek has to land on
 * start_ms for original, burned-in, and sidecar media.
 * Logic: Imperative seek sets currentTime to start_ms / 1000. quotient://
 * sources are read through resources/read. Missing media keeps the chrome.
 * Bugs vs Fixes
 * Bug: A recording with no picture (black frames) showed a black rectangle and
 * read as a broken player. Each reload() also rebuilt the playback object, which
 * re-resolved the URL and remounted the video, losing the position.
 * Fix: Sample three frames through a separate CORS-enabled probe; when every
 * sampled frame is black the player collapses to an audio-only bar with a note.
 * Effects depend on the three locator strings, not the object identity.
 */
import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from "react";
import { mcp } from "@/lib/mcp/client";
import type { Playback } from "@/lib/types";

export type PlayerHandle = { seek: (startMs: number) => void };

type Mode = "original" | "burned" | "sidecar";

export const Player = forwardRef<PlayerHandle, { playback: Playback; loading?: boolean; status?: string }>(function Player({ playback, loading = false, status = "" }, ref) {
  const mediaRef = useRef<HTMLVideoElement>(null);
  const timeRef = useRef(0);
  const [mode, setMode] = useState<Mode>("original");
  const [src, setSrc] = useState("");
  const [caption, setCaption] = useState("");
  const [note, setNote] = useState("");
  const [blank, setBlank] = useState(false);
  const renewalAttempted = useRef(false);
  const source = mode === "burned" ? playback.burned : playback.original;

  useImperativeHandle(ref, () => ({
    seek(startMs: number) {
      timeRef.current = startMs / 1000;
      const node = mediaRef.current;
      if (!node) return;
      const apply = () => {
        node.currentTime = startMs / 1000;
      };
      if (node.readyState >= 1) apply();
      else node.addEventListener("loadedmetadata", apply, { once: true });
    },
  }));

  useEffect(() => {
    let cancel = false;
    const created: string[] = [];
    const track = mode === "sidecar" ? playback.sidecar : "";
    renewalAttempted.current = false;
    async function resolve(url: string): Promise<string> {
      if (!url) return "";
      if (!url.startsWith("quotient://")) return url;
      const body = await mcp.readResource(url);
      if (body.href) return body.href;
      if (!body.blob) return "";
      const objectUrl = URL.createObjectURL(body.blob);
      created.push(objectUrl);
      return objectUrl;
    }
    void (async () => {
      try {
        const next = await resolve(source);
        const nextCaption = track ? await resolve(track) : "";
        if (cancel) {
          for (const url of created) URL.revokeObjectURL(url);
          return;
        }
        setSrc(next);
        setCaption(nextCaption);
        setNote(next ? "" : "The recording isn't available for playback.");
      } catch (error) {
        if (!cancel) setNote("The recording could not be loaded.");
      }
    })();
    return () => {
      cancel = true;
      for (const url of created) URL.revokeObjectURL(url);
    };
  }, [mode, playback.original, playback.burned, playback.sidecar]);

  useEffect(() => {
    const available = mode === "original"
      ? playback.original
      : mode === "burned"
        ? playback.burned
        : playback.sidecar;
    if (available) return;
    setMode(playback.original ? "original" : playback.burned ? "burned" : "sidecar");
  }, [mode, playback.original, playback.burned, playback.sidecar]);

  useEffect(() => {
    setBlank(false);
    if (!src || mode === "sidecar") return;
    let cancel = false;
    const probe = document.createElement("video");
    probe.crossOrigin = "anonymous";
    probe.muted = true;
    probe.preload = "auto";
    const finish = (value: boolean) => {
      if (!cancel) {
        // Switching element type remounts the media; keep the listener's place.
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
      probe.load(); // aborts the in-flight download
    };
  }, [src, mode]);

  // A recording with no picture plays in a native audio control, not a black frame.
  const Media = (blank ? "audio" : "video") as "video";

  const modes: Mode[] = [
    ...(playback.original ? ["original" as const] : []),
    ...(playback.burned ? ["burned" as const] : []),
    ...(playback.sidecar ? ["sidecar" as const] : []),
  ];

  return (
    <div>
      {modes.length > 1 ? (
        <div className="q-modes" role="group" aria-label="Playback version">
          {modes.map((item) => (
            <button key={item} className={item === mode ? "q-btn" : "q-btn-ghost"} type="button" aria-pressed={item === mode} onClick={() => setMode(item)}>
              {item === "burned" ? "With captions" : item === "sidecar" ? "Subtitles" : "Original"}
            </button>
          ))}
        </div>
      ) : null}
      {src ? (
        <Media
          key={`${blank ? "audio" : "video"}:${mode}:${src}`}
          ref={mediaRef}
          className={blank ? "q-video is-audio" : "q-video"}
          src={src}
          aria-label={blank ? "Meeting audio" : "Meeting video"}
          controls
          playsInline
          onLoadedMetadata={(event) => {
            if (timeRef.current > 0) event.currentTarget.currentTime = timeRef.current;
          }}
          onError={(event) => {
            if (renewalAttempted.current || !source.startsWith("quotient://")) {
              setNote("This recording can't be played right now. Reload the page to try again.");
              return;
            }
            renewalAttempted.current = true;
            timeRef.current = event.currentTarget.currentTime;
            void mcp.readResource(source).then((body) => {
              if (body.href) {
                setSrc(body.href);
                setNote("");
              } else {
                setNote("This recording can't be played right now. Reload the page to try again.");
              }
            }).catch((error: unknown) => {
              setNote("The recording could not be loaded.");
            });
          }}
        >
          {caption ? <track kind="subtitles" src={caption} srcLang="en" label="Subtitles" default /> : null}
        </Media>
      ) : (
        <div className="q-player-empty" role="status"><p>{loading
            ? "Loading the recording…"
            : status === "queued" || status === "working"
              ? "The recording can be played once the analysis has finished."
              : status === "failed" || status === "cancelled"
                ? "There is no playable recording for this meeting."
                : note || "Loading the recording…"}</p></div>
      )}
      {blank ? <p className="q-muted q-player-note">This recording appears to have no picture, so only the audio plays.</p> : null}
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
    // Limited-range black decodes to about 16; anything above 40 is real picture.
    if (peak > 40) return false;
  }
  return true;
}
