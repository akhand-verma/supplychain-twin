import { useEffect, useRef, useState } from 'react'
import { Alert, Button, ButtonGroup, Card, Col, Form, Row, Spinner, Table } from 'react-bootstrap'
import {
  Bar, BarChart, CartesianGrid, Cell, ErrorBar, Legend,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts'
import { api } from '../api.js'

const POLICY_COLORS = {
  fixed_order: '#9aa0a6',
  s_S: '#f0ad00',
  newsvendor: '#0d6efd',
  newsvendor_milp: '#2e9e5b',
}

const METRICS = [
  { key: 'total_cost', label: 'Total cost', better: 'low', fmt: (v) => Math.round(v).toLocaleString() },
  { key: 'fill_rate', label: 'Fill rate', better: 'high', fmt: (v) => (v * 100).toFixed(1) + '%' },
  { key: 'service_level', label: 'Service level', better: 'high', fmt: (v) => (v * 100).toFixed(1) + '%' },
  { key: 'unmet_units', label: 'Unmet demand (units)', better: 'low', fmt: (v) => Math.round(v).toLocaleString() },
  { key: 'recovery_days', label: 'Recovery time (days)', better: 'low', fmt: (v) => v.toFixed(1) },
]

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

async function waitForMc(id) {
  const started = Date.now()
  while (Date.now() - started < 120000) {
    const job = await api.getMcJob(id)
    if (job.status === 'done') return job
    if (job.status === 'failed') throw new Error(job.error || 'Monte Carlo run failed')
    await sleep(800)
  }
  throw new Error('Monte Carlo run timed out')
}

function fromCompare(data) {
  const stats = {}
  Object.entries(data.policies).forEach(([key, metrics]) => {
    stats[key] = {}
    Object.entries(metrics).forEach(([m, v]) => {
      stats[key][m] = { mean: v.mean, lo: v.ci_low, hi: v.ci_high }
    })
  })
  return { stats, n: data.n_runs }
}

function fromMonteCarlo(result) {
  const stats = {}
  result.results.forEach((r) => {
    stats[r.policy] = {}
    Object.keys(r.kpi_mean).forEach((m) => {
      stats[r.policy][m] = { mean: r.kpi_mean[m], lo: r.kpi_ci[m][0], hi: r.kpi_ci[m][1] }
    })
  })
  return { stats, n: result.results[0]?.n_runs }
}

function Headline({ label, value, sub, good }) {
  return (
    <Card className="h-100">
      <Card.Body>
        <div className="text-muted small">{label}</div>
        <div className={`fs-2 fw-semibold ${good ? 'text-success' : ''}`}>{value}</div>
        <div className="small text-muted">{sub}</div>
      </Card.Body>
    </Card>
  )
}

function BarTooltip({ active, payload, metric }) {
  if (!active || !payload?.length) return null
  const d = payload[0].payload
  return (
    <div className="bg-white border rounded p-2 small shadow-sm">
      <div><strong>{d.name}</strong></div>
      <div>Mean: {metric.fmt(d.mean)}</div>
      <div>95% CI: {metric.fmt(d.lo)} to {metric.fmt(d.hi)}</div>
    </div>
  )
}

export default function StrategyComparison() {
  const [policies, setPolicies] = useState([])
  const [scenarios, setScenarios] = useState([])
  const [all, setAll] = useState(null)
  const [scenarioKey, setScenarioKey] = useState('')
  const [metricKey, setMetricKey] = useState('total_cost')
  const [source, setSource] = useState('pre')
  const [nRuns, setNRuns] = useState(20)
  const [live, setLive] = useState(null)
  const [running, setRunning] = useState(false)
  const [error, setError] = useState(null)
  const mounted = useRef(true)

  useEffect(() => {
    mounted.current = true
    async function load() {
      try {
        const [p, s] = await Promise.all([api.policies(), api.scenarios()])
        const entries = await Promise.all(
          s.map(async (sc) => [sc.key, fromCompare(await api.compare(sc.key))])
        )
        if (!mounted.current) return
        setPolicies(p)
        setScenarios(s)
        setAll(Object.fromEntries(entries))
        setScenarioKey(s.find((x) => x.key === 'supplier_outage') ? 'supplier_outage' : s[0].key)
      } catch (e) {
        if (mounted.current) setError(e.message)
      }
    }
    load()
    return () => { mounted.current = false }
  }, [])

  async function runLive() {
    setError(null)
    setRunning(true)
    try {
      const job = await api.monteCarlo({
        policies: policies.map((p) => p.key),
        scenario: scenarioKey,
        n_runs: Number(nRuns),
      })
      const done = await waitForMc(job.id)
      if (mounted.current) setLive({ ...fromMonteCarlo(done.result), scenario: scenarioKey })
    } catch (e) {
      if (mounted.current) setError(e.message)
    } finally {
      if (mounted.current) setRunning(false)
    }
  }

  if (error && !all) return <Alert variant="danger">{error}</Alert>
  if (!all) return <Spinner animation="border" />

  const liveValid = live && live.scenario === scenarioKey
  const view = source === 'live' ? (liveValid ? live : null) : all[scenarioKey]
  const metric = METRICS.find((m) => m.key === metricKey)
  const scenario = scenarios.find((s) => s.key === scenarioKey)

  let headline = null
  if (view?.stats.fixed_order && view?.stats.newsvendor_milp) {
    const base = view.stats.fixed_order
    const best = view.stats.newsvendor_milp
    const pct = (a, b) => ((a - b) / a) * 100
    headline = {
      cost: pct(base.total_cost.mean, best.total_cost.mean),
      unmet: pct(base.unmet_units.mean, best.unmet_units.mean),
      recovery: base.recovery_days.mean - best.recovery_days.mean,
    }
  }

  const chartRows = view
    ? policies.filter((p) => view.stats[p.key]).map((p) => {
        const s = view.stats[p.key][metricKey]
        return { key: p.key, name: p.name, mean: s.mean, err: (s.hi - s.lo) / 2, lo: s.lo, hi: s.hi }
      })
    : []

  const robustRows = scenarios.map((s) => {
    const row = { scenario: s.name }
    policies.forEach((p) => { row[p.key] = all[s.key]?.stats[p.key]?.total_cost.mean })
    return row
  })

  return (
    <>
      <Card className="mb-4">
        <Card.Body>
          <Row className="g-3 align-items-end">
            <Col md={3}>
              <Form.Label className="small text-muted mb-1">Disruption scenario</Form.Label>
              <Form.Select value={scenarioKey} onChange={(e) => setScenarioKey(e.target.value)}>
                {scenarios.map((s) => <option key={s.key} value={s.key}>{s.name}</option>)}
              </Form.Select>
            </Col>
            <Col md={3}>
              <Form.Label className="small text-muted mb-1">Metric</Form.Label>
              <Form.Select value={metricKey} onChange={(e) => setMetricKey(e.target.value)}>
                {METRICS.map((m) => <option key={m.key} value={m.key}>{m.label}</option>)}
              </Form.Select>
            </Col>
            <Col md={3}>
              <Form.Label className="small text-muted mb-1 d-block">Results source</Form.Label>
              <ButtonGroup>
                <Button variant={source === 'pre' ? 'primary' : 'outline-primary'} onClick={() => setSource('pre')}>
                  Precomputed
                </Button>
                <Button variant={source === 'live' ? 'primary' : 'outline-primary'} onClick={() => setSource('live')}>
                  Live run
                </Button>
              </ButtonGroup>
            </Col>
            {source === 'live' && (
              <>
                <Col md={1}>
                  <Form.Label className="small text-muted mb-1">Runs</Form.Label>
                  <Form.Control type="number" min={10} max={500} value={nRuns}
                                onChange={(e) => setNRuns(e.target.value)} />
                </Col>
                <Col md={2}>
                  <Button className="w-100" onClick={runLive} disabled={running}>
                    {running ? (<><Spinner size="sm" animation="border" /> Running...</>) : 'Run Monte Carlo'}
                  </Button>
                </Col>
              </>
            )}
          </Row>
          {scenario && <div className="small text-muted mt-3">{scenario.description}</div>}
        </Card.Body>
      </Card>

      {error && <Alert variant="danger">{error}</Alert>}

      {!view && (
        <div className="text-center text-muted py-5">
          Set the number of runs and press <strong>Run Monte Carlo</strong> to compute fresh results for this scenario.
        </div>
      )}

      {view && (
        <>
          {headline && (
            <Row className="g-3 mb-4">
              <Col md={4}>
                <Headline label="Cost saved vs fixed-order baseline"
                          value={`${headline.cost.toFixed(1)}%`} good={headline.cost > 0}
                          sub="Newsvendor + MILP, mean over runs" />
              </Col>
              <Col md={4}>
                <Headline label="Less unmet demand"
                          value={`${headline.unmet.toFixed(1)}%`} good={headline.unmet > 0}
                          sub="Fewer customers turned away" />
              </Col>
              <Col md={4}>
                <Headline label="Faster recovery"
                          value={`${headline.recovery.toFixed(1)} days`} good={headline.recovery > 0}
                          sub="After the disruption ends" />
              </Col>
            </Row>
          )}

          <Row className="g-4 mb-4">
            <Col lg={7}>
              <Card className="h-100">
                <Card.Header>
                  <strong>{metric.label}</strong>
                  <span className="text-muted small ms-2">
                    mean with 95% confidence interval, {view.n} runs, same seeds for every policy
                  </span>
                </Card.Header>
                <Card.Body>
                  <ResponsiveContainer width="100%" height={360}>
                    <BarChart data={chartRows} margin={{ top: 16, right: 20, left: 10, bottom: 0 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" vertical={false} />
                      <XAxis dataKey="name" interval={0} tick={{ fontSize: 12 }} />
                      <YAxis tickFormatter={(v) => metric.fmt(v)} />
                      <Tooltip content={<BarTooltip metric={metric} />} cursor={{ fill: 'rgba(0,0,0,0.04)' }} />
                      <Bar dataKey="mean" isAnimationActive={false}>
                        {chartRows.map((r) => <Cell key={r.key} fill={POLICY_COLORS[r.key] || '#6c757d'} />)}
                        <ErrorBar dataKey="err" width={8} strokeWidth={2} stroke="#222" />
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                  <div className="small text-muted">
                    {metric.better === 'low' ? 'Lower is better.' : 'Higher is better.'} Non-overlapping error bars
                    mean the difference is unlikely to be noise.
                  </div>
                </Card.Body>
              </Card>
            </Col>

            <Col lg={5}>
              <Card className="h-100">
                <Card.Header><strong>All metrics</strong></Card.Header>
                <Table responsive className="mb-0 align-middle small">
                  <thead>
                    <tr>
                      <th>Metric</th>
                      {policies.filter((p) => view.stats[p.key]).map((p) => (
                        <th key={p.key}><span style={{ color: POLICY_COLORS[p.key] }}>●</span> {p.name}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {METRICS.map((m) => {
                      const ps = policies.filter((p) => view.stats[p.key])
                      const means = ps.map((p) => view.stats[p.key][m.key].mean)
                      const best = m.better === 'low' ? Math.min(...means) : Math.max(...means)
                      return (
                        <tr key={m.key}>
                          <td>{m.label}</td>
                          {ps.map((p) => {
                            const s = view.stats[p.key][m.key]
                            return (
                              <td key={p.key} className={s.mean === best ? 'fw-bold text-success' : ''}>
                                {m.fmt(s.mean)}
                                <div className="text-muted fw-normal" style={{ fontSize: 11 }}>
                                  {m.fmt(s.lo)} to {m.fmt(s.hi)}
                                </div>
                              </td>
                            )
                          })}
                        </tr>
                      )
                    })}
                  </tbody>
                </Table>
              </Card>
            </Col>
          </Row>
        </>
      )}

      <Card>
        <Card.Header>
          <strong>Robustness: total cost under every disruption</strong>
          <span className="text-muted small ms-2">precomputed Monte Carlo means, lower is better</span>
        </Card.Header>
        <Card.Body>
          <ResponsiveContainer width="100%" height={360}>
            <BarChart data={robustRows} margin={{ top: 10, right: 20, left: 10, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" vertical={false} />
              <XAxis dataKey="scenario" interval={0} tick={{ fontSize: 11 }} />
              <YAxis tickFormatter={(v) => Math.round(v).toLocaleString()} />
              <Tooltip formatter={(v) => Math.round(v).toLocaleString()} />
              <Legend />
              {policies.map((p) => (
                <Bar key={p.key} dataKey={p.key} name={p.name}
                     fill={POLICY_COLORS[p.key] || '#6c757d'} isAnimationActive={false} />
              ))}
            </BarChart>
          </ResponsiveContainer>
          <div className="small text-muted">
            A robust policy stays low across every scenario, not only the easy one.
          </div>
        </Card.Body>
      </Card>
    </>
  )
}