// api.js - the only place that talks to the PrivaSight server.
// Only gate-approved payloads reach this function; it adds one more guard by
// refusing to send anything that was not marked as passed.

export async function planStep(serverUrl, request, gateResult) {
  if (!gateResult || gateResult.ok !== true) {
    throw new Error('Refusing to send: privacy gate did not approve this payload');
  }
  const res = await fetch(serverUrl.replace(/\/$/, '') + '/plan', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  });
  if (res.status === 422) {
    // The server's own validator found raw PII (defence in depth).
    const body = await res.json().catch(() => ({}));
    const err = new Error('Server rejected the payload as containing PII');
    err.code = 'PII_REJECTED';
    err.detail = body.detail;
    throw err;
  }
  if (!res.ok) throw new Error(`Server error ${res.status}`);
  return res.json();
}

export async function health(serverUrl) {
  const res = await fetch(serverUrl.replace(/\/$/, '') + '/health');
  return res.json();
}
