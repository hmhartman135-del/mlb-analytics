/** @type {import('next').NextConfig} */
const nextConfig = {
  // "standalone" is only needed for the Electron desktop build.
  // Vercel uses its own build pipeline — leave output unset for Vercel.
  ...(process.env.NEXT_STANDALONE === "true" ? { output: "standalone" } : {}),
};

export default nextConfig;
