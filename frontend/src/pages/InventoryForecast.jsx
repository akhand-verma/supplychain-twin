import { useEffect, useState } from 'react'
import { Alert, Card, Col, Form, Row, Spinner } from 'react-bootstrap'
import {
  Area, CartesianGrid, ComposedChart, Legend, Line,
  ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts'
import { api } from '../api.js'

const HISTORY_DAYS_SHOWN = 30

function mergeSeries(inv, fc) {
  const map = new Map()
  inv.forEach((r) => {
    map.set(r.date, { date: r.date, on_hand: r.on_hand, demand: r.demand, stockout: r.stockout })
  })
  fc.forEach((r) => {
    const old = map.get(r.date) || { date: r.date }
    map.set(r.date, {
      ...old,
      p10: r.p10, p50: r.p50, p90: r.p90,
      band_base: r.p10,
      band_size: Math.round((r.p90 - r.p10) * 10) / 10,
    })
  })
  const all = [...map.values()].sort((a, b) => a.date.localeCompare(b.date))
  const lastInv = inv[inv.length - 1].date
  const idx = all.findIndex((r) => r.date === lastInv)
  return { rows: all.slice(Math.max(0, idx - HISTORY_DAYS_SHOWN)), today: lastInv }
}

function ChartTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null
  const d = payload[0].payload
  return (
    <div className="bg-white border rounded p-2 small shadow-sm">
      <div><strong>{label}</strong></div>
      {d.on_hand != null && <div>Stock on hand: {Math.round(d.on_hand)}</div>}
      {d.demand != null && <div>Actual demand: {Math.round(d.demand)}</div>}
      {d.p50 != null && (
        <div>Forecast: {Math.round(d.p50)} (P10 {Math.round(d.p10)} to P90 {Math.round(d.p90)})</div>
      )}
      {d.stockout && <div className="text-danger fw-bold">Stockout</div>}
    </div>
  )
}

const stockoutDot = (props) => {
  const { cx, cy, payload, index } = props
  if (!payload?.stockout || cx == null || cy == null) return <g key={`d-${index}`} />
  return <circle key={`d-${index}`} cx={cx} cy={cy} r={5} fill="#d9363e" stroke="#fff" strokeWidth={1.5} />
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

export default function InventoryForecast() {
  const [stores, setStores] = useState([])
  const [products, setProducts] = useState([])
  const [storeId, setStoreId] = useState('')
  const [productId, setProductId] = useState('')
  const [series, setSeries] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => {
    Promise.all([api.locations('store'), api.products()])
      .then(([s, p]) => {
        setStores(s)
        setProducts(p)
        if (s.length) setStoreId(String(s[0].id))
        if (p.length) setProductId(String(p[0].id))
      })
      .catch((e) => setError(e.message))
  }, [])

  useEffect(() => {
    if (!storeId || !productId) return
    let cancelled = false
    setLoading(true)
    setError(null)
    Promise.all([api.inventory(storeId, productId), api.forecast(storeId, productId)])
      .then(([inv, fc]) => {
        if (!cancelled) setSeries(mergeSeries(inv, fc))
      })
      .catch((e) => {
        if (!cancelled) { setError(e.message); setSeries(null) }
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => { cancelled = true }
  }, [storeId, productId])

  let stats = null
  if (series) {
    const hist = series.rows.filter((r) => r.date <= series.today)
    const future = series.rows.filter((r) => r.date > series.today)
    const last = hist[hist.length - 1]
    const recent = hist.slice(-14)
    const avgDemand = recent.reduce((a, r) => a + (r.demand || 0), 0) / Math.max(1, recent.length)
    stats = {
      onHand: Math.round(last.on_hand),
      cover: avgDemand ? (last.on_hand / avgDemand).toFixed(1) : '-',
      stockouts: hist.filter((r) => r.stockout).length,
      next7: Math.round(future.slice(0, 7).reduce((a, r) => a + (r.p50 || 0), 0)),
    }
  }

  return (
    <>
      <Row className="g-3 mb-4">
        <Col md={4}>
          <Form.Label className="small text-muted mb-1">Store</Form.Label>
          <Form.Select value={storeId} onChange={(e) => setStoreId(e.target.value)}>
            {stores.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
          </Form.Select>
        </Col>
        <Col md={4}>
          <Form.Label className="small text-muted mb-1">Product</Form.Label>
          <Form.Select value={productId} onChange={(e) => setProductId(e.target.value)}>
            {products.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </Form.Select>
        </Col>
      </Row>

      {error && <Alert variant="danger">{error}</Alert>}
      {loading && <Spinner animation="border" />}

      {stats && !loading && (
        <>
          <Row className="g-3 mb-4">
            <Col sm={6} lg={3}><Stat label="Stock on hand" value={stats.onHand} sub="units, latest day" /></Col>
            <Col sm={6} lg={3}><Stat label="Days of cover" value={stats.cover} sub="at recent demand" /></Col>
            <Col sm={6} lg={3}><Stat label="Stockout days" value={stats.stockouts} sub={`last ${HISTORY_DAYS_SHOWN} days`} /></Col>
            <Col sm={6} lg={3}><Stat label="Expected demand" value={stats.next7} sub="next 7 days (forecast P50)" /></Col>
          </Row>

          <Card>
            <Card.Header><strong>Stock, demand and quantile forecast</strong></Card.Header>
            <Card.Body>
              <ResponsiveContainer width="100%" height={420}>
                <ComposedChart data={series.rows} margin={{ top: 10, right: 20, left: 0, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
                  <XAxis dataKey="date" tickFormatter={(d) => d.slice(5)} minTickGap={24} />
                  <YAxis allowDecimals={false} />
                  <Tooltip content={<ChartTooltip />} />
                  <Legend />
                  <Area dataKey="band_base" stackId="band" stroke="none" fill="none"
                        legendType="none" isAnimationActive={false} />
                  <Area dataKey="band_size" stackId="band" stroke="none" fill="#0d6efd"
                        fillOpacity={0.18} name="Forecast range (P10 to P90)" isAnimationActive={false} />
                  <Line dataKey="p50" name="Forecast (P50)" stroke="#0d6efd" strokeDasharray="6 4"
                        dot={false} strokeWidth={2} isAnimationActive={false} />
                  <Line dataKey="demand" name="Actual demand" stroke="#8a8f98"
                        dot={false} strokeWidth={1.5} isAnimationActive={false} />
                  <Line dataKey="on_hand" name="Stock on hand" stroke="#2e9e5b"
                        strokeWidth={2.5} dot={stockoutDot} isAnimationActive={false} />
                  <ReferenceLine x={series.today} stroke="#555" strokeDasharray="3 3"
                                 label={{ value: 'Today', position: 'top', fontSize: 12 }} />
                </ComposedChart>
              </ResponsiveContainer>
              <div className="small text-muted mt-2">
                Red dots mark stockout days. The shaded band is the 80% forecast interval.
                Left of the dashed line is history, right of it is the forecast.
              </div>
            </Card.Body>
          </Card>
        </>
      )}
    </>
  )
}