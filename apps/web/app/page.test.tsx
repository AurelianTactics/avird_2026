import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render } from '@testing-library/react';
import HomePage from './page';

const realFetch = global.fetch;

function mockFetch(impl: () => Promise<Response> | Response) {
  global.fetch = vi.fn(impl) as unknown as typeof fetch;
}

describe('HomePage', () => {
  beforeEach(() => {
    process.env.API_URL = 'http://api.test';
  });

  afterEach(() => {
    global.fetch = realFetch;
    vi.restoreAllMocks();
  });

  it('renders "API: ok" when /health reports db: ok', async () => {
    mockFetch(async () =>
      ({
        ok: true,
        json: async () => ({ status: 'ok', db: 'ok' }),
      }) as unknown as Response,
    );
    const ui = await HomePage();
    const { container } = render(ui);
    expect(container.textContent).toContain('API: ok');
  });

  it('renders "API: down" when /health reports db: down (still 200)', async () => {
    mockFetch(async () =>
      ({
        ok: true,
        json: async () => ({ status: 'ok', db: 'down' }),
      }) as unknown as Response,
    );
    const ui = await HomePage();
    const { container } = render(ui);
    expect(container.textContent).toContain('API: down');
  });

  it('renders "API: unreachable" when fetch rejects', async () => {
    mockFetch(async () => {
      throw new Error('network');
    });
    const ui = await HomePage();
    const { container } = render(ui);
    expect(container.textContent).toContain('API: unreachable');
  });

  it('renders "API: unreachable" when /health returns non-2xx', async () => {
    mockFetch(async () =>
      ({
        ok: false,
        json: async () => ({}),
      }) as unknown as Response,
    );
    const ui = await HomePage();
    const { container } = render(ui);
    expect(container.textContent).toContain('API: unreachable');
  });
});
