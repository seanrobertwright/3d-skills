import { defineConfig } from 'vite'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'

const here = dirname(fileURLToPath(import.meta.url))
const repoRoot = resolve(here, '..')

export default defineConfig({
  root: here,
  server: {
    port: 5273,
    // The models and the printer profile live outside viewer/. Vite refuses to serve files
    // above the root unless they are declared, and silently 403s them otherwise.
    fs: { allow: [repoRoot] },
  },
  build: { outDir: 'dist', emptyOutDir: true },
})
