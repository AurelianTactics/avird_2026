import Link from "next/link";

// Top-nav shell. Adding a later page is a one-line edit to this array — no
// routing framework, no active-state lib (YAGNI, plan R22). Server component.
const LINKS: { label: string; href: string }[] = [
  { label: "Incidents", href: "/" },
  { label: "Groupings", href: "/groupings" },
  { label: "Ontology", href: "/ontology" },
  { label: "About", href: "/about" },
];

export default function Nav() {
  return (
    <nav className="site-nav" aria-label="Primary">
      <div className="site-nav__inner">
        <span className="site-nav__brand">avird-2026</span>
        <span className="site-nav__links">
          {LINKS.map((l) => (
            <Link key={l.href} href={l.href}>
              {l.label}
            </Link>
          ))}
        </span>
      </div>
    </nav>
  );
}
