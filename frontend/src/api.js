const BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000'

async function request(path, options) {
  const res = await fetch(BASE + path, options)
  if (!res.ok) {
    let msg = res.statusText
    try {
      const body = await res.json()
      if (body.detail) msg = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail)
    } catch {
      /* ignore */
    }
    throw new Error(`${res.status}: ${msg}`)
  }
  return res.json()
}

const post = (path, body) =>
  request(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })

export const api = {
  products: () => request('/products'),
  locations: (type) => request('/locations' + (type ? `?type=${type}` : '')),
  policies: () => request('/policies'),
  scenarios: () => request('/scenarios'),
  network: () => request('/network'),
  inventory: (loc, prod) => request(`/inventory/${loc}/${prod}`),
  forecast: (loc, prod) => request(`/forecast/${loc}/${prod}`),
  alerts: () => request('/alerts'),
  explain: (loc, prod) => request(`/explain/${loc}/${prod}`),
  compare: (scenario) => request(`/compare?scenario=${scenario}`),
  simulate: (body) => post('/simulate', body),
  getJob: (id) => request(`/simulate/${id}`),
  monteCarlo: (body) => post('/montecarlo', body),
  getMcJob: (id) => request(`/montecarlo/${id}`),
}