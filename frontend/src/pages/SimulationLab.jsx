import { useEffect, useRef, useState } from 'react'
import { Alert, Badge, Button, Card, Col, Form, Row, Spinner, Table } from 'react-bootstrap'
import {
  CartesianGrid, Legend, Line, LineChart, ReferenceArea,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts'
import { api } from '../api.js'

const COLORS = ['#0d6efd', '#f0ad00']

const KPI_ROWS = [
  { key: 'total_cost', label: 'Total cost', better: 'low', fmt: (v) => Math.round(v).toLocaleString() },
  { key: 'fill_rate', label: 'Fill rate', better: 'high', fmt: (v) => (v * 100).toFixed(1) + '%' },
  { key: 'service_level', label: 'Service level (days at 90%+)', better: 'high', fmt: (v) => (v * 100).toFixed(1) + '%' },
  { key: 'unmet_units', label: 'Unmet demand (units)', better: 'low', fmt: (v) => Math.round(v).toLocaleString() },
  { key: 'recovery_days', label: 'Recovery time', better: 'low', fmt: (v) => `${v} days` },
]

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

async function waitForJob(id) {
  const started = Date.now()
  while (Date.now() - started < 90000) {
    const job = await api.getJob(id)
    if (job.status === 'done') return job
    if (job.status === 'failed') throw new Error(job.error || 'Simulation failed')
    await sleep(700)
  }
  throw new Error('Simulation timed out')
}

function buildRows(runs) {
  const days = runs[0].result.timeseries.day
  return days.map((d, i) => {
    const row = { day: d }
    runs.forEach((r, k) => {
      row[`service_${k}`] = r.result.timeseries.service[i]
      row[`unmet_${k}`] = r.result.timeseries.unmet[i]
    })
    return row
  })
}

export default function SimulationLab() {
  const [policies, setPolicies] = useState([])
  const [scenarios, setScenarios] = useState([])
  const [policyKey, setPolicyKey] = useState('')
  const [compareKey, setCompareKey] = useState('')
  const [scenarioKey, setScenarioKey] = useState('')
  const [seed, setSeed] = useState(1)
  const [running, setRunning] = useState(false)
  const [error, setError] = useState(null)
  const [runs, setRuns] = useState(null)
  const mounted = useRef(true)

  useEffect(() => {
    mounted.current = true
    Promise.all([api.policies(), api.scenarios()])
      .then(([p, s]) => {
        if (!mounted.current) return
        setPolicies(p)
        setScenarios(s)
        const keys = p.map((x) => x.key)
        setPolicyKey(keys.includes('newsvendor_milp') ? 'newsvendor_milp' : keys[0])
        setCompareKey(keys.includes('fixed_order') ? 'fixed_order' : '')
        const sk = s.map((x) => x.key)
        setScenarioKey(sk.includes('supplier_outage') ? 'supplier_outage' : sk[0])
      })
      .catch((e) => setError(e.message))
    return () => { mounted.current = false }
  }, [])

  const nameOf = (key) => policies.find((p) => p.key === key)?.name || key
  const scenario = scenarios.find((s) => s.key === scenarioKey)

  async function run() {
    setError(null)
    setRunning(true)
    setRuns(null)
    try {
      const keys = compareKey && compareKey !== policyKey ? [policyKey, compareKey] : [policyKey]
      const jobs = await Promise.all(
        keys.map((k) => api.simulate({ policy: k, scenario: scenarioKey, seed: Number(seed) || 0 }))
      )
      const done = await Promise.all(jobs.map((j) => waitForJob(j.id)))
      if (mounted.current) setRuns(done.map((j, i) => ({ key: keys[i], result: j.result })))
    } catch (e) {
      if (mounted.current) setError(e.message)
    } finally {
      if (mounted.current) setRunning(false)
    }
  }

  let rows = null
  let startDay = null
  let endDay = null
  if (runs) {
    rows = buildRows(runs)
    const ev = runs[0].result.events || []
    startDay = ev.find((e) => e.type === 'disruption_start')?.day ?? null
    endDay = ev.find((e) => e.type === 'disruption_end')?.day ?? null
  }

  const shade = startDay != null && endDay != null && (
    <ReferenceArea x1={startDay} x2={endDay} fill="#d9363e" fillOpacity={0.08}
                   label={{ value: 'Disruption', fontSize: 12, position: 'insideTop' }} />
  )

  return (
    <>
      <Card className="mb-4">
        <Card.Body>
          <Row className="g-3 align-items-end">
            <Col md={3}>
              <Form.Label className="small text-muted mb-1">Policy</Form.Label>
              <Form.Select value={policyKey} onChange={(e) => setPolicyKey(e.target.value)}>
                {policies.map((p) => <option key={p.key} value={p.key}>{p.name}</option>)}
              </Form.Select>
            </Col>
            <Col md={3}>
              <Form.Label className="small text-muted mb-1">Compare with (same seed)</Form.Label>
              <Form.Select value={compareKey} onChange={(e) => setCompareKey(e.target.value)}>
                <option value="">None</option>
                {policies.filter((p) => p.key !== policyKey).map((p) => (
                  <option key={p.key} value={p.key}>{p.name}</option>
                ))}
              </Form.Select>
            </Col>
            <Col md={3}>
              <Form.Label className="small text-muted mb-1">Disruption</Form.Label>
              <Form.Select value={scenarioKey} onChange={(e) => setScenarioKey(e.target.value)}>
                {scenarios.map((s) => <option key={s.key} value={s.key}>{s.name}</option>)}
              </Form.Select>
            </Col>
            <Col md={1}>
              <Form.Label className="small text-muted mb-1">Seed</Form.Label>
              <Form.Control type="number" min={0} value={seed} onChange={(e) => setSeed(e.target.value)} />
            </Col>
            <Col md={2}>
              <Button className="w-100" onClick={run} disabled={running || !policyKey || !scenarioKey}>
                {running ? (<><Spinner size="sm" animation="border" /> Running...</>) : 'Run simulation'}
              </Button>
            </Col>
          </Row>
          {scenario && <div className="small text-muted mt-3">{scenario.description}</div>}
        </Card.Body>
      </Card>

      {error && <Alert variant="danger">{error}</Alert>}

      {!runs && !running && !error && (
        <div className="text-center text-muted py-5">Choose a policy and a disruption, then press Run.</div>
      )}

      {runs && (
        <>
          <Row className="g-4 mb-4">
            <Col lg={7}>
              <Card className="h-100">
                <Card.Header><strong>Service level over time (recovery curve)</strong></Card.Header>
                <Card.Body>
                  <ResponsiveContainer width="100%" height={340}>
                    <LineChart data={rows} margin={{ top: 10, right: 20, left: 0, bottom: 0 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
                      <XAxis dataKey="day" label={{ value: 'Day', position: 'insideBottomRight', offset: -4 }} />
                      <YAxis domain={[0.5, 1]} tickFormatter={(v) => `${Math.round(v * 100)}%`} />
                      <Tooltip formatter={(v) => `${(v * 100).toFixed(1)}%`} labelFormatter={(d) => `Day ${d}`} />
                      <Legend />
                      {shade}
                      {runs.map((r, k) => (
                        <Line key={r.key} dataKey={`service_${k}`} name={nameOf(r.key)}
                              stroke={COLORS[k]} strokeWidth={2.5} dot={false} isAnimationActive={false} />
                      ))}
                    </LineChart>
                  </ResponsiveContainer>
                </Card.Body>
              </Card>
            </Col>
            <Col lg={5}>
              <Card className="h-100">
                <Card.Header><strong>Unmet demand per day (units)</strong></Card.Header>
                <Card.Body>
                  <ResponsiveContainer width="100%" height={340}>
                    <LineChart data={rows} margin={{ top: 10, right: 20, left: 0, bottom: 0 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
                      <XAxis dataKey="day" />
                      <YAxis />
                      <Tooltip formatter={(v) => Math.round(v)} labelFormatter={(d) => `Day ${d}`} />
                      <Legend />
                      {shade}
                      {runs.map((r, k) => (
                        <Line key={r.key} dataKey={`unmet_${k}`} name={nameOf(r.key)}
                              stroke={COLORS[k]} strokeWidth={2} dot={false} isAnimationActive={false} />
                      ))}
                    </LineChart>
                  </ResponsiveContainer>
                </Card.Body>
              </Card>
            </Col>
          </Row>

          <Row className="g-4">
            <Col lg={8}>
              <Card>
                <Card.Header><strong>Results for this run</strong></Card.Header>
                <Table responsive className="mb-0 align-middle">
                  <thead>
                    <tr>
                      <th>Metric</th>
                      {runs.map((r, k) => (
                        <th key={r.key}><span style={{ color: COLORS[k] }}>●</span> {nameOf(r.key)}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {KPI_ROWS.map((row) => {
                      const vals = runs.map((r) => r.result.kpis[row.key])
                      const best = row.better === 'low' ? Math.min(...vals) : Math.max(...vals)
                      return (
                        <tr key={row.key}>
                          <td>{row.label}</td>
                          {vals.map((v, i) => (
                            <td key={i} className={runs.length > 1 && v === best ? 'fw-bold text-success' : ''}>
                              {row.fmt(v)}
                            </td>
                          ))}
                        </tr>
                      )
                    })}
                  </tbody>
                </Table>
              </Card>
            </Col>
            <Col lg={4}>
              <Card>
                <Card.Header><strong>Event log</strong></Card.Header>
                <Card.Body>
                  {(runs[0].result.events || []).length === 0 && <div className="text-muted">No disruption events.</div>}
                  {(runs[0].result.events || []).map((e, i) => (
                    <div key={i} className="mb-2">
                      <Badge bg={e.type === 'disruption_start' ? 'danger' : 'success'} className="me-2">Day {e.day}</Badge>
                      {e.text}
                    </div>
                  ))}
                  <hr />
                  <div className="small text-muted">
                    One run with seed {runs[0].result.seed}. The Strategy Comparison page averages many runs
                    to give confidence intervals.
                  </div>
                </Card.Body>
              </Card>
            </Col>
          </Row>
        </>
      )}
    </>
  )
}