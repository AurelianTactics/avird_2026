import type { ReactNode } from 'react';
import './globals.css';
import Nav from './components/Nav';

export const metadata = {
  title: 'AVIRD',
  description: 'NHTSA AV crash data website',
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>
        <Nav />
        {children}
      </body>
    </html>
  );
}
