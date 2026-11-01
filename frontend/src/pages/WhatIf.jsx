import { useState } from 'react'
import { Alert, Badge, Button, Card, Col, Form, Row, Spinner, Table } from 'react-bootstrap'
import ReactMarkdown from 'react-markdown'
import {
  CartesianGrid, Legend, Line, LineChart,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts'
import { api } from '../api.js'

const POLICY_COLORS = {
  fixed_order: '#9aa0a6',
  s_S: '#f0ad00',
  newsvendor: '#0d6efd',
  newsvendor_milp: '#2e9e5b',
}

const EXAMPLES = [
  'What if supplier A fails for two weeks?',
  'What happens if transport is delayed during a festival week?',
  'What if demand spikes 60% at all stores?',
  'What if a warehouse goes offline and a supplier also fails?',
]

const KPIS = [
  { key: 'total_cost', label: 'Total cost', fmt: (v) => Math.round(v).toLocaleString() },
  { key: 'fill_rate', label: 'Fill rate', fmt: (v) => (v * 100).toFixed(1) + '%' },
  { key: 'unmet_units', label: 'Unmet demand', fmt: (v) => Math.round(v).toLocaleString() },
  { key: 'recovery_days', label: 'Recovery time', fmt: (v) => v.toFixed(1) + ' days' },
]

function downloadText(name, text) {
  const blob = new Blob([text], { type: 'text/markdown;charset=utf-8;' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = name
  a.click()
  URL.revokeObjectURL(url)
}

function PoweredBy({ value }) {
  return value === 'claude'
    ? <Badge bg="dark">Written by Claude</Badge>
    : <Badge bg="secondary">Offline mode (no API key)</Badge>
}

export default function WhatIf() {
  const [question, setQuestion] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [answer, setAnswer] = useState(null)

  const [report, setReport] = useState(null)
  const [reportLoading, setReportLoading] = useState(false)
  const [reportError, setReportError] = useState(null)

  async function ask(text) {
    const q = (text ?? question).trim()
    if (q.length < 3) return
    setQuestion(q)
    setLoading(true)
    setError(null)
    try {
      setAnswer(await api.whatIf(q))
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  async function makeReport() {
    setReportLoading(true)
    setReportError(null)
    try {
      setReport(await api.report())
    } catch (e) {
      setReportError(e.message)
    } finally {
      setReportLoading(false)
    }
  }

  let rows = null
  if (answer) {
    const days = answer.results[0].curve.day
    rows = days.map((d, i) => {
      const row = { day: d }
      answer.results.forEach((r) => { row[r.policy] = r.curve.service[i] })
      return row
    })
  }

  return (
    <>
      <Card className="mb-4">
        <Card.Body>
          <Form.Label className="fw-semibold">Ask a what-if question</Form.Label>
          <Form.Control
            as="textarea" rows={2} maxLength={500} value={question}
            placeholder="e.g. What if supplier A fails for two weeks?"
            onChange={(e) => setQuestion(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); ask() } }}
          />
          <div className="d-flex flex-wrap gap-2 mt-3 align-items-center">
            <Button onClick={() => ask()} disabled={loading || question.trim().length < 3}>
              {loading ? (<><Spinner size="sm" animation="border" /> Thinking...</>) : 'Ask'}
            </Button>
            <span className="text-muted small ms-2">Try:</span>
            {EXAMPLES.map((ex) => (
              <Button key={ex} size="sm" variant="outline-secondary" disabled={loading} onClick={() => ask(ex)}>
                {ex}
              </Button>
            ))}
          </div>
        </Card.Body>
      </Card>

      {error && <Alert variant="danger">{error}</Alert>}

      {answer && (
        <>
          <Card className="mb-4">
            <Card.Body>
              <div className="d-flex justify-content-between flex-wrap gap-2 mb-2">
                <div>
                  <Badge bg="danger" className="me-2">{answer.scenario_name}</Badge>
                  <span className="text-muted small">{answer.interpretation}</span>
                </div>
                <PoweredBy value={answer.powered_by} />
              </div>
              <p className="fs-5 mb-2">{answer.summary}</p>
              <div className="small text-muted">{answer.scenario_note}</div>
            </Card.Body>
          </Card>

          <Row className="g-4 mb-4">
            <Col lg={7}>
              <Card className="h-100">
                <Card.Header><strong>Service level over time</strong></Card.Header>
                <Card.Body>
                  <ResponsiveContainer width="100%" height={320}>
                    <LineChart data={rows} margin={{ top: 10, right: 20, left: 0, bottom: 0 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
                      <XAxis dataKey="day" />
                      <YAxis domain={[0.5, 1]} tickFormatter={(v) => `${Math.round(v * 100)}%`} />
                      <Tooltip formatter={(v) => `${(v * 100).toFixed(1)}%`} labelFormatter={(d) => `Day ${d}`} />
                      <Legend />
                      {answer.results.map((r) => (
                        <Line key={r.policy} dataKey={r.policy} name={r.name}
                              stroke={POLICY_COLORS[r.policy] || '#6c757d'} strokeWidth={2.5}
                              dot={false} isAnimationActive={false} />
                      ))}
                    </LineChart>
                  </ResponsiveContainer>
                </Card.Body>
              </Card>
            </Col>
            <Col lg={5}>
              <Card className="h-100">
                <Card.Header>
                  <strong>Monte Carlo averages</strong>
                  <span className="text-muted small ms-2">{answer.results[0].n_runs} runs</span>
                </Card.Header>
                <Table responsive className="mb-0 small align-middle">
                  <thead>
                    <tr>
                      <th>Metric</th>
                      {answer.results.map((r) => (
                        <th key={r.policy}><span style={{ color: POLICY_COLORS[r.policy] }}>●</span> {r.name}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {KPIS.map((k) => (
                      <tr key={k.key}>
                        <td>{k.label}</td>
                        {answer.results.map((r) => (
                          <td key={r.policy}>
                            {k.fmt(r.kpi_mean[k.key])}
                            <div className="text-muted" style={{ fontSize: 11 }}>
                              {k.fmt(r.kpi_ci[k.key][0])} to {k.fmt(r.kpi_ci[k.key][1])}
                            </div>
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </Table>
              </Card>
            </Col>
          </Row>
        </>
      )}

      <Card>
        <Card.Header className="d-flex justify-content-between align-items-center flex-wrap gap-2">
          <strong>Planner report</strong>
          <div className="d-flex gap-2 align-items-center">
            {report && <PoweredBy value={report.powered_by} />}
            {report && (
              <Button size="sm" variant="outline-secondary"
                      onClick={() => downloadText('planner_report.md', report.markdown)}>
                Download .md
              </Button>
            )}
            <Button size="sm" onClick={makeReport} disabled={reportLoading}>
              {reportLoading ? (<><Spinner size="sm" animation="border" /> Writing...</>) : 'Generate report'}
            </Button>
          </div>
        </Card.Header>
        <Card.Body>
          {reportError && <Alert variant="danger">{reportError}</Alert>}
          {!report && !reportLoading && (
            <p className="text-muted mb-0">
              Builds a one-page summary from the current alerts and the supplier-outage simulation results.
            </p>
          )}
          {report && <ReactMarkdown>{report.markdown}</ReactMarkdown>}
        </Card.Body>
      </Card>
    </>
  )
}