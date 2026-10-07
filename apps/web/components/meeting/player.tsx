"use client";

/**
 * Motivation vs Logic
 * Motivation: Playback is a field of the graph. A citation seek has to land on
 * start_ms for original, burned-in, and sidecar media.
 * Logic: Imperative seek sets currentTime to start_ms / 1000. quotient://
 * sources are read through resources/read. Missing media keeps the chrome.
 */
import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from "react";
import { mcp } from "@/lib/mcp/client";
import type { Playback } from "@/lib/types";
import { formatMs } from "@/lib/format";

export type PlayerHandle = { seek: (startMs: number) => void };

type Mode = "original" | "burned" | "sidecar";

export const Player = forwardRef<PlayerHandle, { playback: Playback }>(function Player({ playback }, ref) {
  const mediaRef = useRef<HTMLVideoElement>(null);
  const timeRef = useRef(0);
  const [mode, setMode] = useState<Mode>("original");
  const [src, setSrc] = useState("");
  const [caption, setCaption] = useState("");
  const [note, setNote] = useState("");
  const [seekLabel, setSeekLabel] = useState<number | null>(null);

  useImperativeHandle(ref, () => ({
    seek(startMs: number) {
      timeRef.current = startMs / 1000;
      setSeekLabel(startMs);
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
    const source = mode === "burned" ? playback.burned : playback.original;
    const track = mode === "sidecar" ? playback.sidecar : "";
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
        setNote(next ? "" : "Playback starts when the graph includes a media URL.");
      } catch (error) {
        if (!cancel) setNote(error instanceof Error ? error.message : "Playback is unavailable");
      }
    })();
    return () => {
      cancel = true;
      for (const url of created) URL.revokeObjectURL(url);
    };
  }, [mode, playback]);

  return (
    <div>
      <div className="q-modes">
        {(["original", "burned", "sidecar"] as const).map((item) => (
          <button key={item} className={item === mode ? "q-btn" : "q-btn-ghost"} type="button" onClick={() => setMode(item)}>
            {item === "burned" ? "Text in video" : item === "sidecar" ? "Subtitles" : "Video only"}
          </button>
        ))}
        {seekLabel !== null ? <span className="q-meta">Seek {formatMs(seekLabel)}</span> : null}
      </div>
      {src ? (
        <video
          key={`${mode}:${src}`}
          ref={mediaRef}
          className="q-video"
          src={src}
          controls
          playsInline
          onLoadedMetadata={(event) => {
            if (timeRef.current > 0) event.currentTarget.currentTime = timeRef.current;
          }}
        >
          {caption ? <track kind="subtitles" src={caption} srcLang="en" label="Subtitles" default /> : null}
        </video>
      ) : (
        <div className="q-player-empty"><p>{note || "Playback starts when the graph includes a media URL."}</p></div>
      )}
    </div>
  );
});
