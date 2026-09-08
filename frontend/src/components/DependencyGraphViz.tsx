import type { Concept, DependencyGraph } from '../types'

interface Props {
  graph: DependencyGraph
  selectedId?: string | null
  onSelect?: (concept: Concept) => void
}

interface NodeLayout {
  x: number
  y: number
  width: number
  height: number
  lines: string[]
}

const NODE_WIDTH = 170
const HORIZONTAL_PADDING = 14 // each side, inside the bubble
const VERTICAL_PADDING = 14 // total (top + bottom), inside the bubble
const MIN_NODE_HEIGHT = 48
const MAX_LINES = 3
const LINE_HEIGHT = 16
const FONT_SIZE = 13
const FONT_FAMILY = "system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif"
const COLUMN_GAP = 70
const ROW_GAP = 20
const PADDING = 20

// Concept titles are short (a few words), so bubbles wrap onto up to MAX_LINES
// rather than truncate, and grow taller to fit rather than overflow their edges.
let measureCtx: CanvasRenderingContext2D | null | undefined
function getMeasureContext(): CanvasRenderingContext2D | null {
  if (measureCtx !== undefined) return measureCtx
  if (typeof document === 'undefined') {
    measureCtx = null
    return measureCtx
  }
  measureCtx = document.createElement('canvas').getContext('2d')
  if (measureCtx) measureCtx.font = `${FONT_SIZE}px ${FONT_FAMILY}`
  return measureCtx
}

function measureWidth(text: string): number {
  const ctx = getMeasureContext()
  // Heuristic fallback keeps layout working even without a canvas (e.g. SSR/tests).
  return ctx ? ctx.measureText(text).width : text.length * FONT_SIZE * 0.55
}

function wrapLabel(label: string, maxWidth: number): string[] {
  const words = label.split(' ')
  const lines: string[] = []
  let current = ''
  for (const word of words) {
    const candidate = current ? `${current} ${word}` : word
    if (!current || measureWidth(candidate) <= maxWidth) {
      current = candidate
    } else {
      lines.push(current)
      current = word
    }
  }
  if (current) lines.push(current)

  if (lines.length > MAX_LINES) {
    const kept = lines.slice(0, MAX_LINES)
    kept[MAX_LINES - 1] = `${kept[MAX_LINES - 1].trimEnd()}…`
    return kept
  }
  return lines
}

function nodeHeight(lineCount: number): number {
  return Math.max(MIN_NODE_HEIGHT, lineCount * LINE_HEIGHT + VERTICAL_PADDING)
}

// Layered layout: a concept's column is one past its deepest prerequisite.
function layout(graph: DependencyGraph): Map<string, NodeLayout> {
  const depths = new Map<string, number>()
  const depthOf = (id: string, seen: Set<string>): number => {
    const cached = depths.get(id)
    if (cached !== undefined) return cached
    if (seen.has(id)) return 0 // cycle guard; real graphs should be DAGs
    seen.add(id)
    const concept = graph.concepts.find((c) => c.id === id)
    const depth = concept?.depends_on.length
      ? Math.max(...concept.depends_on.map((dep) => depthOf(dep, seen))) + 1
      : 0
    depths.set(id, depth)
    return depth
  }
  graph.concepts.forEach((c) => depthOf(c.id, new Set()))

  const columns = new Map<number, string[]>()
  for (const concept of graph.concepts) {
    const depth = depths.get(concept.id) ?? 0
    columns.set(depth, [...(columns.get(depth) ?? []), concept.id])
  }

  const maxTextWidth = NODE_WIDTH - HORIZONTAL_PADDING * 2
  const positions = new Map<string, NodeLayout>()
  for (const [depth, ids] of columns) {
    let y = PADDING
    for (const id of ids) {
      const concept = graph.concepts.find((c) => c.id === id)
      const lines = wrapLabel(concept?.name ?? '', maxTextWidth)
      const height = nodeHeight(lines.length)
      positions.set(id, {
        x: PADDING + depth * (NODE_WIDTH + COLUMN_GAP),
        y,
        width: NODE_WIDTH,
        height,
        lines,
      })
      y += height + ROW_GAP
    }
  }
  return positions
}

export function DependencyGraphViz({ graph, selectedId, onSelect }: Props) {
  const positions = layout(graph)
  // Trailing `0` keeps Math.max from returning -Infinity when the graph is empty.
  const width =
    Math.max(...[...positions.values()].map((p) => p.x + p.width), 0) + PADDING
  const height =
    Math.max(...[...positions.values()].map((p) => p.y + p.height), 0) + PADDING

  return (
    // viewBox is sized to the content (not a fixed constant) so the graph scales
    // to fit its container regardless of how many concepts/columns it has.
    <svg width="100%" viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Concept dependency graph">
      <defs>
        <marker id="arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto">
          <path d="M0,0 L8,4 L0,8 z" fill="#8890c9" />
        </marker>
      </defs>
      {graph.concepts.flatMap((concept) =>
        concept.depends_on.map((depId) => {
          const from = positions.get(depId)
          const to = positions.get(concept.id)
          if (!from || !to) return null
          return (
            <line
              key={`${depId}->${concept.id}`}
              x1={from.x + from.width}
              y1={from.y + from.height / 2}
              x2={to.x - 2}
              y2={to.y + to.height / 2}
              stroke="#8890c9"
              strokeWidth={1.5}
              markerEnd="url(#arrow)"
            />
          )
        }),
      )}
      {graph.concepts.map((concept) => {
        const pos = positions.get(concept.id)
        if (!pos) return null
        const selected = concept.id === selectedId
        const textBlockHeight = pos.lines.length * LINE_HEIGHT
        const firstLineY = (pos.height - textBlockHeight) / 2 + LINE_HEIGHT / 2
        return (
          <g
            key={concept.id}
            transform={`translate(${pos.x}, ${pos.y})`}
            onClick={() => onSelect?.(concept)}
            style={{ cursor: onSelect ? 'pointer' : 'default' }}
          >
            <rect
              width={pos.width}
              height={pos.height}
              rx={10}
              fill={selected ? '#eef0fd' : 'white'}
              stroke={selected ? '#4b5bd7' : '#b8bede'}
              strokeWidth={selected ? 2 : 1.5}
            />
            <text
              textAnchor="middle"
              dominantBaseline="middle"
              fontSize={FONT_SIZE}
              fontFamily={FONT_FAMILY}
              fill="#1a1a2e"
            >
              {pos.lines.map((line, i) => (
                <tspan key={i} x={pos.width / 2} y={firstLineY + i * LINE_HEIGHT}>
                  {line}
                </tspan>
              ))}
            </text>
          </g>
        )
      })}
    </svg>
  )
}
