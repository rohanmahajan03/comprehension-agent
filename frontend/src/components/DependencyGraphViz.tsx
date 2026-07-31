import type { Concept, DependencyGraph } from '../types'

interface Props {
  graph: DependencyGraph
  selectedId?: string | null
  onSelect?: (concept: Concept) => void
}

interface NodePosition {
  x: number
  y: number
}

const NODE_WIDTH = 170
const NODE_HEIGHT = 48
const COLUMN_GAP = 70
const ROW_GAP = 28
const PADDING = 20

// Layered layout: a concept's column is one past its deepest prerequisite.
function layout(graph: DependencyGraph): Map<string, NodePosition> {
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

  const positions = new Map<string, NodePosition>()
  for (const [depth, ids] of columns) {
    ids.forEach((id, row) => {
      positions.set(id, {
        x: PADDING + depth * (NODE_WIDTH + COLUMN_GAP),
        y: PADDING + row * (NODE_HEIGHT + ROW_GAP),
      })
    })
  }
  return positions
}

export function DependencyGraphViz({ graph, selectedId, onSelect }: Props) {
  const positions = layout(graph)
  // Trailing `0` keeps Math.max from returning -Infinity when the graph is empty.
  const width =
    Math.max(...[...positions.values()].map((p) => p.x + NODE_WIDTH), 0) + PADDING
  const height =
    Math.max(...[...positions.values()].map((p) => p.y + NODE_HEIGHT), 0) + PADDING

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
              x1={from.x + NODE_WIDTH}
              y1={from.y + NODE_HEIGHT / 2}
              x2={to.x - 2}
              y2={to.y + NODE_HEIGHT / 2}
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
        return (
          <g
            key={concept.id}
            transform={`translate(${pos.x}, ${pos.y})`}
            onClick={() => onSelect?.(concept)}
            style={{ cursor: onSelect ? 'pointer' : 'default' }}
          >
            <rect
              width={NODE_WIDTH}
              height={NODE_HEIGHT}
              rx={10}
              fill={selected ? '#4b5bd7' : 'white'}
              stroke={selected ? '#4b5bd7' : '#b8bede'}
              strokeWidth={1.5}
            />
            <text
              x={NODE_WIDTH / 2}
              y={NODE_HEIGHT / 2}
              dominantBaseline="middle"
              textAnchor="middle"
              fontSize={13}
              fill={selected ? 'white' : '#1a1a2e'}
            >
              {concept.name}
            </text>
          </g>
        )
      })}
    </svg>
  )
}
