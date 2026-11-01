import { useEffect, useMemo, useState } from 'react'
import { Alert, Badge, Button, Card, Col, Form, ProgressBar, Row, Spinner, Table } from 'react-bootstrap'
import { api } from '../api.js'

function toCsv(rows) {
  const head = ['severity', 'store', 'product', 'date', 'recommended_order_qty', 'situation']
  const esc = (v) => `"${String(v).replace(/"/g, '""')}"`
  const lines = rows.map((a) =>
    [a.severity, a.location, a.product, a.date, a.recommended_qty, a.message].map(esc).join(',')
  )
  return [head.join(','), ...lines].join('\n')
}

function downloadCsv(rows) {
  const blob = new Blob([toCsv(rows)], { type: 'text/csv;charset=utf-8;' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = 'recommended_orders.csv'
  link.click()
  URL.revokeObjectURL(url)
}

function SeverityBadge({ severity }) {
  return severity === 'high'
    ? <Badge bg="danger">High</Badge>
    : <Badge bg="warning" text="dark">Medium</Badge>
}

function Stat({ label, value, sub }) {
  return (
    <Card className="h-100">
      <Card.Body>
        <div className="text-muted small">{label}</div>
        <div className="fs-3 fw-semibold">{value}</div>
        {sub && <div className="small text-muted">{sub}</div>}
      </Card.Body>
    </Card>
  )
}

function Line({ label, value, strong }) {
  return (
    <div className={`d-flex justify-content-between py-1 border-bottom ${strong ? 'fw-bold' : ''}`}>
      <span>{label}</span>
      <span>{value}</span>
    </div>
  )
}

function ExplainPanel({ item }) {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (!item) return
    let cancelled = false
    setLoading(true)
    setError(null)
    setData(null)
    api.explain(item.location_id, item.product_id)
      .then((d) => { if (!cancelled) setData(d) })
      .catch((e) => { if (!cancelled) setError(e.message) })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [item])

  if (!item) {
    return <p className="text-muted mb-0">Select an alert and press Explain to see why this quantity is recommended.</p>
  }
  if (loading) return <Spinner animation="border" />
  if (error) return <Alert variant="danger" className="mb-0">{error}</Alert>
  if (!data) return null

  const total = data.on_hand + data.recommended_order_qty
  const pctHand = total ? (data.on_hand / total) * 100 : 0
  const pctOrder = 100 - pctHand

  return (
    <>
      <h5 className="mb-0">{item.product}</h5>
      <div className="text-muted mb-3">{item.location}</div>

      <div className="text-muted small">Recommended order</div>
      <div className="display-6 fw-semibold text-primary mb-3">{data.recommended_order_qty} units</div>

      <ProgressBar className="mb-1" style={{ height: 22 }}>
        <ProgressBar variant="success" now={pctHand} key={1} label={data.on_hand > 0 ? data.on_hand : ''} />
        <ProgressBar variant="primary" now={pctOrder} key={2} label={data.recommended_order_qty} />
      </ProgressBar>
      <div className="small text-muted mb-3">
        <span style={{ color: '#198754' }}>●</span> already in stock &nbsp;
        <span style={{ color: '#0d6efd' }}>●</span> new order
      </div>

      <Line label="Stock on hand" value={data.on_hand} />
      <Line label="Lead time" value={`${data.lead_time_days} days`} />
      <Line label="Expected demand in lead time (P50)" value={data.expected_demand_over_lead_time} />
      <Line label="Safety stock (P90 minus P50)" value={data.safety_stock} />
      <Line label={`Target stock level (P90, ${Math.round(data.service_target * 100)}% service)`} value={data.p90_demand_over_lead_time} />
      <Line label="Order = target minus stock on hand" value={data.recommended_order_qty} strong />

      <Alert variant="light" className="border mt-3 mb-0 small">{data.reason}</Alert>
    </>
  )
}

export default function AlertsPage() {
  const [alerts, setAlerts] = useState(null)
  const [error, setError] = useState(null)
  const [severity, setSeverity] = useState('all')
  const [query, setQuery] = useState('')
  const [selected, setSelected] = useState(null)

  useEffect(() => {
    api.alerts().then(setAlerts).catch((e) => setError(e.message))
  }, [])

  const filtered = useMemo(() => {
    if (!alerts) return []
    const q = query.trim().toLowerCase()
    return alerts.filter((a) =>
      (severity === 'all' || a.severity === severity) &&
      (!q || a.product.toLowerCase().includes(q) || a.location.toLowerCase().includes(q))
    )
  }, [alerts, severity, query])

  if (error) return <Alert variant="danger">Could not load alerts: {error}</Alert>
  if (!alerts) return <Spinner animation="border" />

  const high = alerts.filter((a) => a.severity === 'high').length
  const medium = alerts.length - high
  const totalUnits = alerts.reduce((sum, a) => sum + a.recommended_qty, 0)

  return (
    <>
      <Row className="g-3 mb-4">
        <Col sm={6} lg={3}><Stat label="Open alerts" value={alerts.length} sub="predicted stockouts" /></Col>
        <Col sm={6} lg={3}><Stat label="High severity" value={high} sub="stock below expected demand" /></Col>
        <Col sm={6} lg={3}><Stat label="Medium severity" value={medium} sub="stock below P90 demand" /></Col>
        <Col sm={6} lg={3}><Stat label="Units to order" value={totalUnits.toLocaleString()} sub="across all alerts" /></Col>
      </Row>

      <Row className="g-4">
        <Col lg={7}>
          <Card>
            <Card.Header>
              <Row className="g-2 align-items-center">
                <Col sm={3}>
                  <Form.Select size="sm" value={severity} onChange={(e) => setSeverity(e.target.value)}>
                    <option value="all">All severities</option>
                    <option value="high">High only</option>
                    <option value="medium">Medium only</option>
                  </Form.Select>
                </Col>
                <Col sm={5}>
                  <Form.Control size="sm" placeholder="Search store or product" value={query}
                                onChange={(e) => setQuery(e.target.value)} />
                </Col>
                <Col sm={4} className="text-sm-end">
                  <Button size="sm" variant="outline-secondary" disabled={!filtered.length}
                          onClick={() => downloadCsv(filtered)}>
                    Export CSV ({filtered.length})
                  </Button>
                </Col>
              </Row>
            </Card.Header>
            <div style={{ maxHeight: 560, overflowY: 'auto' }}>
              <Table hover responsive className="mb-0 align-middle">
                <thead className="table-light" style={{ position: 'sticky', top: 0 }}>
                  <tr>
                    <th>Severity</th>
                    <th>Store</th>
                    <th>Product</th>
                    <th className="text-end">Order</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {filtered.map((a) => (
                    <tr key={a.id} className={selected?.id === a.id ? 'table-active' : ''}>
                      <td><SeverityBadge severity={a.severity} /></td>
                      <td>{a.location}</td>
                      <td>
                        {a.product}
                        <div className="text-muted" style={{ fontSize: 12 }}>{a.message}</div>
                      </td>
                      <td className="text-end fw-semibold">{a.recommended_qty}</td>
                      <td className="text-end">
                        <Button size="sm" variant="outline-primary" onClick={() => setSelected(a)}>Explain</Button>
                      </td>
                    </tr>
                  ))}
                  {filtered.length === 0 && (
                    <tr><td colSpan={5} className="text-center text-muted py-4">No alerts match these filters.</td></tr>
                  )}
                </tbody>
              </Table>
            </div>
          </Card>
        </Col>

        <Col lg={5}>
          <Card>
            <Card.Header><strong>Why this order?</strong></Card.Header>
            <Card.Body>
              <ExplainPanel item={selected} />
            </Card.Body>
          </Card>
        </Col>
      </Row>
    </>
  )
}