"use client";

export default function ErrorPage({ reset }: { error: Error; reset: () => void }) {
  return (
    <main className="q-main">
      <h1>This page could not be shown</h1>
      <p className="q-muted">Try again. Your other meetings are still available.</p>
      <button className="q-btn" type="button" onClick={reset}>Try again</button>
    </main>
  );
}
