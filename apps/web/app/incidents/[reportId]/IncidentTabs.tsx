"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import { isTabId, type TabId } from "./tabs";

// Three views over one incident. The crash facts + narrative live in a
// persistent header above this component; these tabs only switch the
// "reasoning surface" beneath it.
//   verdict — the AI fault verdict (the showcase, hence the default)
//   debate  — argue the fault yourself against an AI advocate + judge
//   report  — the raw reported fields + other reports of the same crash
const TABS: { id: TabId; label: string }[] = [
  { id: "verdict", label: "AI Verdict" },
  { id: "debate", label: "Argue it yourself" },
  { id: "report", label: "Full report" },
];

export default function IncidentTabs({
  initialView,
  verdict,
  debate,
  report,
}: {
  initialView: TabId;
  verdict: ReactNode;
  debate: ReactNode;
  report: ReactNode;
}) {
  const [active, setActive] = useState<TabId>(initialView);
  const tabRefs = useRef<(HTMLButtonElement | null)[]>([]);

  // Keep the active tab in the URL (?view=) so a debate or verdict is
  // shareable and the back button restores the prior tab. pushState is the
  // App-Router-blessed way to update searchParams without a server round-trip,
  // which matters here: a refetch would unmount DebatePanel and wipe an
  // in-progress argument.
  function select(id: TabId) {
    if (id === active) return;
    setActive(id);
    const url = new URL(window.location.href);
    url.searchParams.set("view", id);
    window.history.pushState(null, "", url);
  }

  // Sync when the user navigates history (back/forward).
  useEffect(() => {
    function onPop() {
      const v = new URLSearchParams(window.location.search).get("view");
      setActive(isTabId(v ?? undefined) ? (v as TabId) : "verdict");
    }
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  // Roving-tabindex keyboard nav across the tablist (WAI-ARIA tabs pattern).
  function onKeyDown(e: React.KeyboardEvent, index: number) {
    const last = TABS.length - 1;
    let next: number | null = null;
    if (e.key === "ArrowRight") next = index === last ? 0 : index + 1;
    else if (e.key === "ArrowLeft") next = index === 0 ? last : index - 1;
    else if (e.key === "Home") next = 0;
    else if (e.key === "End") next = last;
    if (next === null) return;
    e.preventDefault();
    select(TABS[next].id);
    tabRefs.current[next]?.focus();
  }

  const panels: { id: TabId; node: ReactNode }[] = [
    { id: "verdict", node: verdict },
    { id: "debate", node: debate },
    { id: "report", node: report },
  ];

  return (
    <div className="incident-tabs">
      <div role="tablist" aria-label="Incident views" className="tablist">
        {TABS.map((t, i) => {
          const selected = active === t.id;
          return (
            <button
              key={t.id}
              ref={(el) => {
                tabRefs.current[i] = el;
              }}
              type="button"
              role="tab"
              id={`tab-${t.id}`}
              aria-controls={`panel-${t.id}`}
              aria-selected={selected}
              tabIndex={selected ? 0 : -1}
              className={`tablist__tab${selected ? " is-active" : ""}`}
              onClick={() => select(t.id)}
              onKeyDown={(e) => onKeyDown(e, i)}
            >
              {t.label}
            </button>
          );
        })}
      </div>

      {panels.map((p) => (
        <div
          key={p.id}
          role="tabpanel"
          id={`panel-${p.id}`}
          aria-labelledby={`tab-${p.id}`}
          hidden={active !== p.id}
          tabIndex={0}
        >
          {p.node}
        </div>
      ))}
    </div>
  );
}
