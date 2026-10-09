/**
 * Motivation vs Logic
 * Motivation: The page shown while a meeting is analysed had no title, so the browser tab just said
 * "Quotient" and several open tabs could not be told apart.
 * Logic: A segment layout that only sets the document title.
 */
import type { Metadata } from "next";
import type { ReactNode } from "react";

export const metadata: Metadata = { title: "Analysing a meeting · Quotient" };

export default function TaskLayout({ children }: { children: ReactNode }) {
  return children;
}
