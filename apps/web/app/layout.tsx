import type { ReactNode } from 'react';

export const metadata = {
  title: 'avird-2026',
  description: 'NHTSA AV crash data portfolio',
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
