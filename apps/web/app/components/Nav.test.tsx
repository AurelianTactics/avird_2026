import { describe, expect, it } from 'vitest';
import { render } from '@testing-library/react';
import Nav from './Nav';

describe('Nav', () => {
  it('renders Incidents, Groupings, and About links with correct hrefs', () => {
    const { container } = render(<Nav />);
    expect(container.querySelector('a[href="/"]')?.textContent).toBe('Incidents');
    expect(container.querySelector('a[href="/groupings"]')?.textContent).toBe('Groupings');
    expect(container.querySelector('a[href="/about"]')?.textContent).toBe('About');
  });
});
