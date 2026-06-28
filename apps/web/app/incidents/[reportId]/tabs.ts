// Shared tab identity, kept out of the "use client" IncidentTabs module so the
// server component (page.tsx) can call isTabId() to resolve ?view= — a function
// exported from a client module cannot be invoked from the server.
export type TabId = "verdict" | "debate" | "report";

export function isTabId(v: string | undefined): v is TabId {
  return v === "verdict" || v === "debate" || v === "report";
}
