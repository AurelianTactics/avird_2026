import type { ReactNode } from "react";
import "./globals.css";
import Nav from "./components/Nav";

export const metadata = {
  title: "avird",
  description: "NHTSA AV crash data website",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>
        <Nav />
        {children}
        <footer className="site-footer">
          © 2026 avird · MIT License · Data: NHTSA Standing General Order crash
          reports
        </footer>
      </body>
    </html>
  );
}
