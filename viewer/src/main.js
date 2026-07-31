import * as THREE from 'three'
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js'
import { STLLoader } from 'three/examples/jsm/loaders/STLLoader.js'
import { ThreeMFLoader } from 'three/examples/jsm/loaders/3MFLoader.js'

const WS_URL = `ws://${location.hostname}:5274`
const status = document.getElementById('status')
const canvas = document.getElementById('canvas')

let plate = { width: 256, depth: 256 }
let modelDir = 'benchmarks/bearing-holder/out'
let part = null
let clipPlane = new THREE.Plane(new THREE.Vector3(0, 0, -1), Infinity)

const scene = new THREE.Scene()
scene.background = new THREE.Color(0x14171f)

const camera = new THREE.PerspectiveCamera(45, 1, 0.1, 5000)
camera.up.set(0, 0, 1)
camera.position.set(90, -90, 70)

const renderer = new THREE.WebGLRenderer({ canvas, antialias: true })
renderer.localClippingEnabled = true

const controls = new OrbitControls(camera, renderer.domElement)
controls.enableDamping = true

scene.add(new THREE.AmbientLight(0xffffff, 0.55))
const key = new THREE.DirectionalLight(0xffffff, 1.1)
key.position.set(1, -1, 1.4)
scene.add(key)
const fill = new THREE.DirectionalLight(0xbfd4ff, 0.45)
fill.position.set(-1.2, 0.6, 0.4)
scene.add(fill)
const back = new THREE.DirectionalLight(0xffffff, 0.35)
back.position.set(-0.4, 1.4, -0.6)
scene.add(back)

const material = new THREE.MeshPhongMaterial({
  color: 0x4a8fd9,
  specular: 0x333333,
  shininess: 28,
  side: THREE.DoubleSide,
  clippingPlanes: [clipPlane],
})

let plateGroup = new THREE.Group()
scene.add(plateGroup)

function buildPlate() {
  plateGroup.clear()
  // Plate dimensions come from profiles/printer-p1s.json. Never hardcode 256 -- the whole point
  // of profiles/ is that hardware values live in configuration from day one.
  const grid = new THREE.GridHelper(plate.width, Math.round(plate.width / 10), 0x8a94a8, 0x323a4a)
  grid.rotation.x = Math.PI / 2
  plateGroup.add(grid)
  const outline = new THREE.LineSegments(
    new THREE.EdgesGeometry(new THREE.PlaneGeometry(plate.width, plate.depth)),
    new THREE.LineBasicMaterial({ color: 0xd98c40 }),
  )
  plateGroup.add(outline)
}

function frame(object) {
  const box = new THREE.Box3().setFromObject(object)
  const size = box.getSize(new THREE.Vector3())
  const center = box.getCenter(new THREE.Vector3())
  const radius = Math.max(size.length() / 2, 1)
  controls.target.copy(center)
  camera.position.copy(center).add(new THREE.Vector3(1, -1.1, 0.85).setLength(radius * 3.2))
  camera.near = radius / 100
  camera.far = radius * 100
  camera.updateProjectionMatrix()
  controls.update()
  return { box, size }
}

let bounds = null

function setPart(geometry, label) {
  // Camera is preserved across reloads on purpose: the user is iterating on a dimension and
  // must be able to see what changed without re-finding their viewpoint.
  const first = part === null
  if (part) {
    scene.remove(part)
    part.geometry.dispose()
  }
  geometry.computeVertexNormals()
  part = new THREE.Mesh(geometry, material)
  scene.add(part)
  bounds = new THREE.Box3().setFromObject(part)
  if (first) frame(part)
  applySection()
  const size = bounds.getSize(new THREE.Vector3())
  status.textContent =
    `${label}\n${size.x.toFixed(2)} x ${size.y.toFixed(2)} x ${size.z.toFixed(2)} mm  ` +
    `(${geometry.attributes.position.count / 3} triangles)\n` +
    `channel, not a gate - verify with lril3d-inspect`
  status.className = ''
}

function applySection() {
  if (!bounds) return
  const t = Number(document.getElementById('section').value)
  const zMin = bounds.min.z
  const zMax = bounds.max.z
  const z = zMin + (zMax - zMin) * t
  clipPlane.constant = t >= 1 ? Infinity : z
}

// Vite serves files outside the project root under /@fs/<absolute path>, and the path must use
// forward slashes with a single leading slash. A native Windows path is 'D:\repos\...', which
// 404s verbatim.
function fsUrl(nativePath) {
  const posix = String(nativePath).replace(/\\/g, '/')
  return '/@fs' + (posix.startsWith('/') ? posix : '/' + posix)
}

async function loadProfile() {
  try {
    const res = await fetch(fsUrl(PROFILE_PATH))
    if (res.ok) {
      const data = await res.json()
      const p = data.plate || data.build_volume || {}
      plate = { width: p.width ?? p.x ?? 256, depth: p.depth ?? p.y ?? 256 }
    }
  } catch {
    /* fall back to the declared default and say so */
    status.textContent = 'printer profile unreadable; using 256x256 plate'
    status.className = 'warn'
  }
  buildPlate()
}

const PROFILE_PATH = new URL('../../profiles/printer-p1s.json', import.meta.url).pathname

async function loadModel(file) {
  const url = `${fsUrl(file)}?t=${Date.now()}`
  const res = await fetch(url)
  if (!res.ok) throw new Error(`${res.status} loading ${file}`)
  const buffer = await res.arrayBuffer()
  const name = file.toLowerCase()
  if (name.endsWith('.stl')) {
    setPart(new STLLoader().parse(buffer), file.split(/[\\/]/).pop())
  } else if (name.endsWith('.3mf')) {
    const group = new ThreeMFLoader().parse(buffer)
    let geometry = null
    group.traverse((child) => {
      if (child.isMesh && !geometry) geometry = child.geometry
    })
    if (!geometry) throw new Error('3MF contained no mesh')
    setPart(geometry, file.split(/[\\/]/).pop())
  } else {
    throw new Error(`unsupported file ${file}`)
  }
}

function connect() {
  const socket = new WebSocket(WS_URL)
  socket.addEventListener('message', async (event) => {
    const message = JSON.parse(event.data)
    if (message.type === 'hello') {
      modelDir = message.dir
      if (message.file) await loadModel(message.file).catch(showError)
      else {
        status.textContent = `watching ${modelDir}\nno part.stl or part.3mf yet - export one`
        status.className = 'warn'
      }
    } else if (message.type === 'change') {
      console.log('[lril3d] reloading', message.file)
      await loadModel(message.file).catch(showError)
    }
  })
  socket.addEventListener('close', () => {
    status.textContent = 'watcher disconnected - retrying'
    status.className = 'warn'
    setTimeout(connect, 1500)
  })
  socket.addEventListener('error', () => socket.close())
}

function showError(err) {
  console.error('[lril3d]', err)
  status.textContent = String(err.message || err)
  status.className = 'err'
}

document.getElementById('wireframe').addEventListener('change', (e) => {
  material.wireframe = e.target.checked
})
document.getElementById('grid').addEventListener('change', (e) => {
  plateGroup.visible = e.target.checked
})
document.getElementById('section').addEventListener('input', applySection)

function resize() {
  const { clientWidth: w, clientHeight: h } = document.documentElement
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2))
  renderer.setSize(w, h, false)
  camera.aspect = w / h
  camera.updateProjectionMatrix()
}
addEventListener('resize', resize)
resize()

function tick() {
  requestAnimationFrame(tick)
  controls.update()
  renderer.render(scene, camera)
}

await loadProfile()
connect()
tick()
