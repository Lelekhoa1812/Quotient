import { TaskScreen } from "@/components/task-screen";

export default async function TaskPage({ params }: { params: Promise<{ taskId: string }> }) {
  const { taskId } = await params;
  return <TaskScreen taskId={taskId} />;
}
