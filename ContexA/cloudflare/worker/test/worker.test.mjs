import test from 'node:test';
import assert from 'node:assert/strict';
import worker from '../src/index.js';

const allowedOrigin = 'https://contexa-studio.pages.dev';

test('edge health reports configuration and attaches edge headers', async () => {
  const request = new Request('https://edge.example.workers.dev/edge-health', {
    headers: { Origin: allowedOrigin },
  });
  const response = await worker.fetch(request, {
    API_ORIGIN: 'https://origin.example.test',
    ALLOWED_ORIGINS: allowedOrigin,
    EDGE_VERSION: 'test-version',
  }, {});
  assert.equal(response.status, 200);
  assert.equal(response.headers.get('X-ContexA-Edge'), 'Cloudflare Workers');
  assert.equal(response.headers.get('Access-Control-Allow-Origin'), allowedOrigin);
  const body = await response.json();
  assert.equal(body.status, 'ok');
  assert.equal(body.origin_configured, true);
  assert.equal(body.version, 'test-version');
});

test('edge rejects an unlisted browser origin', async () => {
  const request = new Request('https://edge.example.workers.dev/api/health', {
    headers: { Origin: 'https://attacker.example' },
  });
  const response = await worker.fetch(request, {
    API_ORIGIN: 'https://origin.example.test',
    ALLOWED_ORIGINS: allowedOrigin,
  }, {});
  assert.equal(response.status, 403);
});

test('edge does not proxy non-API paths', async () => {
  const request = new Request('https://edge.example.workers.dev/admin');
  const response = await worker.fetch(request, {
    API_ORIGIN: 'https://origin.example.test',
    ALLOWED_ORIGINS: allowedOrigin,
  }, {});
  assert.equal(response.status, 404);
});

test('edge proxies the API path and forwards a request ID', async (t) => {
  const originalFetch = globalThis.fetch;
  let captured;
  globalThis.fetch = async (request) => {
    captured = request;
    return new Response(JSON.stringify({ status: 'ok' }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    });
  };
  t.after(() => { globalThis.fetch = originalFetch; });

  const request = new Request('https://edge.example.workers.dev/api/health?detail=1', {
    headers: { Origin: allowedOrigin, 'X-Request-ID': 'judge-demo-123' },
  });
  const response = await worker.fetch(request, {
    API_ORIGIN: 'https://origin.example.test',
    ALLOWED_ORIGINS: allowedOrigin,
    ORIGIN_SHARED_SECRET: 'edge-origin-test-secret',
  }, {});
  assert.equal(response.status, 200);
  assert.equal(captured.url, 'https://origin.example.test/api/health?detail=1');
  assert.equal(captured.headers.get('X-Request-ID'), 'judge-demo-123');
  assert.equal(captured.headers.get('X-ContexA-Origin-Secret'), 'edge-origin-test-secret');
  assert.equal(response.headers.get('X-Request-ID'), 'judge-demo-123');
});


test('edge upload limiter also covers multimodal inspection', async () => {
  let limitCalls = 0;
  const request = new Request('https://edge.example.workers.dev/api/multimodal/inspect', {
    method: 'POST', headers: { Origin: allowedOrigin, 'Content-Type': 'application/octet-stream' }, body: 'synthetic-file'
  });
  const response = await worker.fetch(request, {
    API_ORIGIN: 'https://origin.example.test',
    ALLOWED_ORIGINS: allowedOrigin,
    UPLOAD_LIMITER: { limit: async () => { limitCalls += 1; return { success: false }; } },
  }, {});
  assert.equal(response.status, 429);
  assert.equal(limitCalls, 1);
});

test('scheduled trigger calls the protected Truth Drift due-scan endpoint', async (t) => {
  const originalFetch = globalThis.fetch;
  let captured;
  globalThis.fetch = async (request, options) => {
    captured = { url: String(request), ...options };
    return new Response(JSON.stringify({ scanned: 2, drift_events: 1 }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    });
  };
  t.after(() => { globalThis.fetch = originalFetch; });

  let scheduledPromise;
  worker.scheduled({ cron: '0 */6 * * *' }, {
    API_ORIGIN: 'https://origin.example.test',
    TRUTH_DRIFT_CRON_TOKEN: 'test-cron-token',
    ORIGIN_SHARED_SECRET: 'test-origin-secret',
  }, { waitUntil: (promise) => { scheduledPromise = promise; } });
  await scheduledPromise;

  assert.equal(captured.url, 'https://origin.example.test/api/internal/truth-drift/scan-due');
  assert.equal(captured.method, 'POST');
  const headers = new Headers(captured.headers);
  assert.equal(headers.get('Authorization'), 'Bearer test-cron-token');
  assert.equal(headers.get('X-ContexA-Origin-Secret'), 'test-origin-secret');
  assert.equal(captured.body, '{}');
});
