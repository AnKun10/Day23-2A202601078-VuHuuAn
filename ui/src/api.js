// Thin fetch wrapper around the FastAPI backend.
async function request(url, opts) {
  const res = await fetch(url, opts)
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(err.detail || 'Request failed')
  }
  return res.json()
}

const jsonPost = (url, body) =>
  request(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })

export const getRuns = () => request('/api/runs')
export const getExamples = () => request('/api/examples')
export const getGraph = () => request('/api/graph')
export const createRun = (query) => jsonPost('/api/runs', { query })
export const decide = (threadId, decision) =>
  jsonPost(`/api/runs/${threadId}/decision`, decision)
