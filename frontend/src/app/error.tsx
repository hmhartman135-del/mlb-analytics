"use client";
export default function Error({ reset }: { error: Error; reset: () => void }) {
  return (
    <div className="flex flex-col items-center justify-center h-full gap-4">
      <p className="text-red-400 text-sm">Something went wrong loading this page.</p>
      <button onClick={reset} className="px-4 py-2 bg-blue-600 rounded-lg text-sm">Try again</button>
    </div>
  );
}
