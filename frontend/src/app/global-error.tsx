"use client";
export default function GlobalError({ reset }: { error: Error; reset: () => void }) {
  return (
    <html><body className="bg-gray-950 text-gray-100 flex items-center justify-center h-screen">
      <div className="text-center gap-4 flex flex-col">
        <p className="text-red-400">Something went wrong.</p>
        <button onClick={reset} className="px-4 py-2 bg-blue-600 rounded-lg text-sm">Try again</button>
      </div>
    </body></html>
  );
}
