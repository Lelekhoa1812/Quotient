import { Suspense } from "react";
import type { Metadata } from "next";
import { Workspace } from "@/components/meeting/workspace";

export async function generateMetadata(): Promise<Metadata> {
  return { title: "Meeting" };
}

export default async function MeetingPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return (
    <Suspense fallback={<main className="q-main"><h1>Opening this meeting</h1></main>}>
      <Workspace meetingId={id} />
    </Suspense>
  );
}
