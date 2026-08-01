// Watches a model's out/ directory and tells the page to reload the mesh in place.
//
// PRD 11 asks for reload within ~1s of a file write. Two things make that work in practice:
//
//   * **Debounce.** Exporters write an STL or 3MF in several chunks and fire multiple watcher
//     events for one logical save. Reloading mid-write yields a truncated mesh, which looks
//     exactly like a geometry defect -- the worst possible false signal for this project.
//   * **Size settling.** A debounce alone still fires while a large file is growing, so the
//     file's size must stop changing before it is announced.

import { WebSocketServer } from 'ws'
import chokidar from 'chokidar'
import { existsSync, statSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = dirname(fileURLToPath(import.meta.url))
const REPO_ROOT = resolve(HERE, '..', '..')
const PORT = 5274
// Matches Vite's own default bind (vite.config.js sets no `host`, so it serves on 127.0.0.1),
// which is what `location.hostname` in the page will therefore be. Override only if you have
// deliberately changed Vite's host -- setting this to 0.0.0.0 exposes the paths below to the LAN.
const HOST = process.env.THREEDP_WATCH_HOST || '127.0.0.1'
const DEBOUNCE_MS = 250
const CANDIDATES = ['part.stl', 'part.3mf']
// The g-code preview is watched alongside the mesh, and kept in its OWN list. It is a different
// load path in the page and a different claim about the part -- the mesh is the current export,
// the preview is the last slice -- so a re-slice must not be announced as a model change.
const PREVIEW_CANDIDATES = ['part.preview.json']
const WATCHED = [...CANDIDATES, ...PREVIEW_CANDIDATES]

function parseArgs(argv) {
  let dir = 'benchmarks/bearing-holder/out'
  for (let i = 0; i < argv.length; i += 1) {
    if (argv[i] === '--model' && argv[i + 1]) dir = argv[i + 1]
  }
  return resolve(REPO_ROOT, dir)
}

const modelDir = parseArgs(process.argv.slice(2))

function firstPresent(names) {
  for (const name of names) {
    const candidate = join(modelDir, name)
    if (existsSync(candidate)) return candidate
  }
  return null
}

const currentFile = () => firstPresent(CANDIDATES)
const currentPreview = () => firstPresent(PREVIEW_CANDIDATES)

// Loopback only. The viewer is a localhost dev workflow, and the hello frame below carries
// absolute filesystem paths -- there is no reason for those to be reachable from the LAN.
const server = new WebSocketServer({ host: HOST, port: PORT })
const clients = new Set()

server.on('connection', (socket) => {
  clients.add(socket)
  socket.on('close', () => clients.delete(socket))
  socket.send(
    JSON.stringify({
      type: 'hello',
      dir: modelDir,
      file: currentFile(),
      preview: currentPreview(),
    }),
  )
})

function broadcast(payload) {
  const message = JSON.stringify(payload)
  for (const socket of clients) {
    if (socket.readyState === socket.OPEN) socket.send(message)
  }
}

// Debounce state is per FILE, not global. With one shared timer, two files changing inside the
// same window announced only the last one and dropped the other silently -- and the natural slice
// workflow does exactly that, writing the mesh and then part.preview.json moments later. The
// dropped announcement leaves the page showing stale geometry with nothing saying so.
const pending = new Map() // file -> { timer, lastSize }

function announce(file) {
  const state = pending.get(file)
  if (!state) return
  const size = existsSync(file) ? statSync(file).size : -1
  if (size !== state.lastSize) {
    // still growing - wait another interval rather than shipping a half-written mesh
    state.lastSize = size
    state.timer = setTimeout(() => announce(file), DEBOUNCE_MS)
    return
  }
  pending.delete(file)
  console.log(`[watch] ${file} (${size} bytes)`)
  broadcast({ type: 'change', file })
}

function schedule(file) {
  const state = pending.get(file)
  if (state) clearTimeout(state.timer)
  pending.set(file, { timer: setTimeout(() => announce(file), DEBOUNCE_MS), lastSize: -1 })
}

const watcher = chokidar.watch(modelDir, { ignoreInitial: true, depth: 0 })
watcher.on('all', (event, path) => {
  if (!WATCHED.some((name) => path.endsWith(name))) return
  if (event === 'unlink') return
  schedule(path)
})

console.log(`[watch] ws://${HOST}:${PORT}  watching ${modelDir}  (${WATCHED.join(', ')})`)

for (const signal of ['SIGINT', 'SIGTERM']) {
  process.on(signal, () => {
    for (const { timer } of pending.values()) clearTimeout(timer)
    pending.clear()
    watcher.close()
    server.close()
    process.exit(0)
  })
}
