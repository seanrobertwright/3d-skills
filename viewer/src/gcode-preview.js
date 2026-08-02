// G-code toolpath preview.
//
// The parsing is NOT here (ADR-11). `threedp.gcode` reads the file in Python and writes a compact
// preview JSON; this module only draws it. Parsing is the part with the traps -- Bambu's markers
// are `; FEATURE:` and `; CHANGE_LAYER`, not PrusaSlicer's `;TYPE:` and `;LAYER_CHANGE`, and the
// header labels a millimetres-cubed volume as cm^3 -- and the browser is the one place in this
// project with no tests.
//
// **The preview is a channel, not a gate**, the same rule as renders and the model view. Nothing
// here reaches a verdict.
//
// Every extruding move is one segment of a SINGLE indexed LineSegments. A 15,000-move plate is
// 15,000 segments and one draw call; making it 15,000 objects would be one draw call each.

import * as THREE from 'three'

// Distinct enough to read at a glance, and deliberately not the model's blue -- the preview must
// never be mistaken for the mesh. Unknown feature names fall through to FALLBACK rather than
// being dropped, so a Bambu update that adds a feature type shows up instead of vanishing.
const FEATURE_COLORS = {
  'Outer wall': 0xf5a623,
  'Inner wall': 0xe2604f,
  'Top surface': 0x4a8fd9,
  'Bottom surface': 0x3f6fa8,
  'Internal solid infill': 0x7a68c8,
  'Sparse infill': 0x4c8f6e,
  'Bridge': 0x2fb5c4,
  'Overhang wall': 0xd94f8a,
  'Gap infill': 0x9aa4b8,
  'Support': 0x6b7280,
  'Custom': 0x555f70,
  'Travel': 0x2b3242,
  'Undefined': 0x8a94a8,
}
const FALLBACK = 0xc0c6d4

export class Preview {
  constructor() {
    this.object = null
    this.layers = []
    this.counts = {}
    this.meta = {}
    this.truncated = false
    this.note = ''
    this.markersFound = true
    this._layerOf = null
    this._segmentCount = 0
  }

  get layerCount() {
    return this.layers.length
  }

  dispose(scene) {
    if (!this.object) return
    scene.remove(this.object)
    this.object.geometry.dispose()
    this.object.material.dispose()
    this.object = null
  }

  // Show layers [0, upTo] inclusive. Implemented with the draw range over a layer-sorted index
  // buffer, so scrubbing costs no reallocation and no re-upload.
  showUpTo(upTo) {
    if (!this.object || !this._layerOf) return
    const limit = Math.max(0, Math.min(upTo, this.layerCount - 1))
    let visible = 0
    while (visible < this._segmentCount && this._layerOf[this._order[visible]] <= limit) visible += 1
    this.object.geometry.setDrawRange(0, visible * 2)
    return visible
  }
}

export async function loadPreview(url) {
  const res = await fetch(`${url}?t=${Date.now()}`)
  if (!res.ok) throw new Error(`${res.status} loading ${url}`)
  const data = await res.json()

  const preview = new Preview()
  preview.layers = data.layers || []
  preview.counts = data.counts || {}
  preview.meta = data.meta || {}
  preview.truncated = Boolean(data.truncated)
  preview.note = data.note || ''
  preview.markersFound = data.markers_found !== false

  const positions = new Float32Array(data.segments?.positions || [])
  const layerOf = data.segments?.layer || []
  const featureOf = data.segments?.feature || []
  const names = data.features || []
  const count = positions.length / 6

  const colors = new Float32Array(count * 6)
  const scratch = new THREE.Color()
  for (let i = 0; i < count; i += 1) {
    const name = names[featureOf[i]] ?? ''
    scratch.setHex(FEATURE_COLORS[name] ?? FALLBACK)
    for (let end = 0; end < 2; end += 1) {
      colors[i * 6 + end * 3 + 0] = scratch.r
      colors[i * 6 + end * 3 + 1] = scratch.g
      colors[i * 6 + end * 3 + 2] = scratch.b
    }
  }

  // Sort segment indices by layer so the layer slider is a draw-range change rather than a
  // rebuild. Stable order within a layer keeps the drawing sequence deterministic.
  const order = Array.from({ length: count }, (_, i) => i)
  order.sort((a, b) => layerOf[a] - layerOf[b] || a - b)

  const index = new Uint32Array(count * 2)
  for (let i = 0; i < count; i += 1) {
    index[i * 2] = order[i] * 2
    index[i * 2 + 1] = order[i] * 2 + 1
  }

  const geometry = new THREE.BufferGeometry()
  geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3))
  geometry.setAttribute('color', new THREE.BufferAttribute(colors, 3))
  geometry.setIndex(new THREE.BufferAttribute(index, 1))
  geometry.computeBoundingSphere()

  preview.object = new THREE.LineSegments(
    geometry,
    new THREE.LineBasicMaterial({ vertexColors: true }),
  )
  preview._layerOf = layerOf
  preview._order = order
  preview._segmentCount = count
  preview.showUpTo(preview.layerCount - 1)
  return preview
}

// The status text. Every number the preview knows about is stated, including the ones that mean
// "this is not the whole picture": a truncated preview that looks complete is the viewer's
// version of a silent partial render, and a zero density means the mass beside it is not a mass.
export function describe(preview, label) {
  const lines = [label]
  const m = preview.meta || {}
  const counts = preview.counts || {}

  if (m.time_hm) {
    const mass =
      m.density_is_usable === false
        ? `${(m.weight_g ?? 0).toFixed(2)} g  <- computed from filament_density 0; NOT a mass`
        : `${(m.weight_g ?? 0).toFixed(2)} g`
    lines.push(`${m.time_hm}   ${m.layers ?? preview.layerCount} layers   ${mass}`)
  }
  lines.push(`${counts.emitted ?? 0} extruding moves, ${preview.layerCount} layers drawn`)
  // The mesh is modelled about the origin; the slicer places it on the plate. Those are two
  // different coordinate systems and the preview really is somewhere else, so the panel says so
  // rather than leaving the user to wonder why the camera moved.
  lines.push('drawn in PLATE coordinates - the mesh is drawn about the origin')
  if (preview.truncated) {
    lines.push(
      `TRUNCATED: ${counts.dropped} of ${counts.extruding} moves dropped at the ` +
        `${counts.max_segments} segment cap - this is not the whole toolpath`,
    )
  }
  if (!preview.markersFound) {
    lines.push('no "; FEATURE:" markers found - feature colours are unavailable for this file')
  }
  lines.push('channel, not a gate - verify with lril3d-inspect')
  return lines.join('\n')
}
