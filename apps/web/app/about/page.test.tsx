import { describe, expect, it } from 'vitest';
import { render } from '@testing-library/react';
import AboutPage from './page';

describe('AboutPage', () => {
  it('renders the expected heading', () => {
    const { container } = render(<AboutPage />);
    expect(container.textContent).toContain('About this project');
  });

  it('links back to home', () => {
    const { container } = render(<AboutPage />);
    const homeLink = container.querySelector('a[href="/"]');
    expect(homeLink).not.toBeNull();
  });
});
