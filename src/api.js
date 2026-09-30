async function req(path, opts = {}) {
  const res = await fetch(path, {
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    ...opts,
  })
  const data = await res.json().catch(() => ({}))
  if (!res.ok) throw new Error(data.error || 'Request failed')
  return data
}

export const api = {
  me: () => req('/api/auth/me'),
  signup: (body) => req('/api/auth/signup', { method: 'POST', body: JSON.stringify(body) }),
  login: (body) => req('/api/auth/login', { method: 'POST', body: JSON.stringify(body) }),
  logout: () => req('/api/auth/logout', { method: 'POST' }),
  resetAccount: () => req('/api/account/reset', { method: 'POST' }),

  markets: () => req('/api/markets'),
  market: (slug) => req(`/api/markets/${slug}`),
  createMarket: (body) => req('/api/markets', { method: 'POST', body: JSON.stringify(body) }),
  order: (slug, body) =>
    req(`/api/markets/${slug}/orders`, { method: 'POST', body: JSON.stringify(body) }),
  resolve: (slug, outcome) =>
    req(`/api/markets/${slug}/resolve`, { method: 'POST', body: JSON.stringify({ outcome }) }),
}
