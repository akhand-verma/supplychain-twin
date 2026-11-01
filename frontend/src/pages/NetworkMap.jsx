import { useEffect, useState } from 'react'
import { Alert, Badge, Card, Col, Row, Spinner } from 'react-bootstrap'
import { api } from '../api.js'

const COLORS = { green: '#2e9e5b', yellow: '#f0ad00', red: '#d9363e' }
const TYPE_LABEL = { supplier: 'Supplier', warehouse: 'Warehouse', store: 'Store' }

export default function NetworkMap() {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [selected, setSelected] = useState(null)

  useEffect(() => {
    api.network().then(setData).catch((e) => setError(e.message))
  }, [])

  if (error) {
    return (
      <Alert variant="danger">
        Could not load the network: {error}. Is the backend running on port 8000?
      </Alert>
    )
  }
  if (!data) return <Spinner animation="border" />

  const byId = Object.fromEntries(data.nodes.map((n) => [n.id, n]))
  const counts = { green: 0, yellow: 0, red: 0 }
  data.nodes.forEach((n) => { counts[n.health] += 1 })

  return (
    <Row className="g-4">
      <Col lg={8}>
        <Card>
          <Card.Header className="d-flex justify-content-between align-items-center">
            <strong>Network state</strong>
            <span className="small text-muted">as of {data.as_of}</span>
          </Card.Header>
          <Card.Body>
            <svg viewBox="0 0 100 100" style={{ width: '100%', height: 560 }}>
              {data.edges.map((e) => {
                const a = byId[e.src]
                const b = byId[e.dst]
                if (!a || !b) return null
                return (
                  <line key={e.id} x1={a.x} y1={a.y} x2={b.x} y2={b.y}
                        stroke="#b8bec9" strokeWidth="0.25" />
                )
              })}
              {data.nodes.map((n) => (
                <g key={n.id} onClick={() => setSelected(n)} style={{ cursor: 'pointer' }}>
                  <circle cx={n.x} cy={n.y} r={n.type === 'store' ? 2.6 : 3.6}
                          fill={COLORS[n.health]}
                          stroke={selected?.id === n.id ? '#111' : '#fff'}
                          strokeWidth="0.6" />
                  <text x={n.x} y={n.y + (n.type === 'store' ? 5.4 : 6.6)}
                        textAnchor="middle" fontSize="2.3" fill="#333">
                    {n.name}
                  </text>
                </g>
              ))}
              <text x="8" y="3" textAnchor="middle" fontSize="2.4" fontWeight="bold" fill="#666">Suppliers</text>
              <text x="45" y="3" textAnchor="middle" fontSize="2.4" fontWeight="bold" fill="#666">Warehouses</text>
              <text x="88" y="3" textAnchor="middle" fontSize="2.4" fontWeight="bold" fill="#666">Stores</text>
            </svg>
            <div className="d-flex gap-3 small mt-2">
              <span><span style={{ color: COLORS.green }}>●</span> Healthy ({counts.green})</span>
              <span><span style={{ color: COLORS.yellow }}>●</span> Low stock ({counts.yellow})</span>
              <span><span style={{ color: COLORS.red }}>●</span> Stockout risk ({counts.red})</span>
            </div>
          </Card.Body>
        </Card>
      </Col>

      <Col lg={4}>
        <Card>
          <Card.Header><strong>Details</strong></Card.Header>
          <Card.Body>
            {!selected && <p className="text-muted mb-0">Click a node on the map.</p>}
            {selected && (
              <>
                <h5>{selected.name}</h5>
                <p className="text-muted">{TYPE_LABEL[selected.type]}</p>
                <Badge bg={selected.health === 'green' ? 'success' : selected.health === 'yellow' ? 'warning' : 'danger'}>
                  {selected.health === 'green' ? 'Healthy' : selected.health === 'yellow' ? 'Low stock' : 'Stockout risk'}
                </Badge>
                <hr />
                <div>Total units on hand: <strong>{selected.total_on_hand.toLocaleString()}</strong></div>
                <div>Products out of stock: <strong>{selected.stockouts}</strong></div>
                <div>Products below 3 days cover: <strong>{selected.low_stock_items}</strong></div>
              </>
            )}
          </Card.Body>
        </Card>
      </Col>
    </Row>
  )
}