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
const DEBOUNCE_MS = 250
const CANDIDATES = ['part.stl', 'part.3mf']

function parseArgs(argv) {
  let dir = 'benchmarks/bearing-holder/out'
  for (let i = 0; i < argv.length; i += 1) {
    if (argv[i] === '--model' && argv[i + 1]) dir = argv[i + 1]
  }
  return resolve(REPO_ROOT, dir)
}

const modelDir = parseArgs(process.argv.slice(2))

function currentFile() {
  for (const name of CANDIDATES) {
    const candidate = join(modelDir, name)
    if (existsSync(candidate)) return candidate
  }
  return null
}

const server = new WebSocketServer({ port: PORT })
const clients = new Set()

server.on('connection', (socket) => {
  clients.add(socket)
  socket.on('close', () => clients.delete(socket))
  socket.send(JSON.stringify({ type: 'hello', dir: modelDir, file: currentFile() }))
})

function broadcast(payload) {
  const message = JSON.stringify(payload)
  for (const socket of clients) {
    if (socket.readyState === socket.OPEN) socket.send(message)
  }
}

let timer = null
let lastSize = -1

function announce(file) {
  const size = existsSync(file) ? statSync(file).size : -1
  if (size !== lastSize) {
    // still growing - wait another interval rather than shipping a half-written mesh
    lastSize = size
    timer = setTimeout(() => announce(file), DEBOUNCE_MS)
    return
  }
  timer = null
  lastSize = -1
  console.log(`[watch] ${file} (${size} bytes)`)
  broadcast({ type: 'change', file })
}

function schedule(file) {
  if (timer) clearTimeout(timer)
  lastSize = -1
  timer = setTimeout(() => announce(file), DEBOUNCE_MS)
}

const watcher = chokidar.watch(modelDir, { ignoreInitial: true, depth: 0 })
watcher.on('all', (event, path) => {
  if (!CANDIDATES.some((name) => path.endsWith(name))) return
  if (event === 'unlink') return
  schedule(path)
})

console.log(`[watch] ws://localhost:${PORT}  watching ${modelDir}`)

for (const signal of ['SIGINT', 'SIGTERM']) {
  process.on(signal, () => {
    watcher.close()
    server.close()
    process.exit(0)
  })
}
