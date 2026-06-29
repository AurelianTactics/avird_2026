"use client";

// Top-down car schematic that highlights which area(s) made contact, for both
// the subject vehicle and the other party — the "show what parts collided"
// view. Two cars are drawn nose-up so "Front" is always the top edge; the
// highlighted zone(s) light up in the brand accent.
//
// Works for both groupings: fine per-direction areas (e.g. "Front Left") and
// the coarse Front / Rear / Side / Other buckets the contact view folds into.

type Mode = "fine" | "coarse";

// Nine zones laid over the car body, addressed by a short key.
const ZONES: Record<string, { x: number; y: number; w: number; h: number }> = {
  FL: { x: 6, y: 6, w: 26, h: 34 },
  F: { x: 34, y: 6, w: 26, h: 34 },
  FR: { x: 62, y: 6, w: 26, h: 34 },
  L: { x: 6, y: 42, w: 26, h: 70 },
  C: { x: 34, y: 42, w: 26, h: 70 },
  R: { x: 62, y: 42, w: 26, h: 70 },
  RL: { x: 6, y: 114, w: 26, h: 34 },
  Re: { x: 34, y: 114, w: 26, h: 34 },
  RR: { x: 62, y: 114, w: 26, h: 34 },
};

const FINE_TO_ZONES: Record<string, (keyof typeof ZONES)[]> = {
  "Front Left": ["FL"],
  Front: ["F"],
  "Front Right": ["FR"],
  Left: ["L"],
  Right: ["R"],
  "Rear Left": ["RL"],
  Rear: ["Re"],
  "Rear Right": ["RR"],
  Top: ["C"],
  Bottom: ["C"],
  Unknown: ["C"],
  Other: ["C"],
};

const COARSE_TO_ZONES: Record<string, (keyof typeof ZONES)[]> = {
  Front: ["FL", "F", "FR"],
  Rear: ["RL", "Re", "RR"],
  Side: ["L", "R"],
  Other: ["C"],
};

function zonesFor(area: string, mode: Mode): Set<string> {
  const map = mode === "coarse" ? COARSE_TO_ZONES : FINE_TO_ZONES;
  return new Set(map[area] ?? FINE_TO_ZONES[area] ?? ["C"]);
}

function Car({
  area,
  mode,
  title,
  variant,
}: {
  area: string;
  mode: Mode;
  title: string;
  variant: "sv" | "cp";
}) {
  const hot = zonesFor(area, mode);
  const accent = variant === "sv" ? "var(--accent)" : "#c0552b";
  return (
    <figure className="cardiag">
      <svg
        viewBox="0 0 94 154"
        className="cardiag__svg"
        role="img"
        aria-label={`${title}: contact at ${area}`}
      >
        {/* Highlighted zones first, so the body outline reads on top. */}
        {Object.entries(ZONES).map(([key, z]) =>
          hot.has(key) ? (
            <rect
              key={key}
              x={z.x}
              y={z.y}
              width={z.w}
              height={z.h}
              rx={4}
              fill={accent}
              opacity={0.85}
            />
          ) : null,
        )}
        {/* Car body. */}
        <rect
          x={4}
          y={4}
          width={86}
          height={146}
          rx={16}
          fill="none"
          stroke="var(--ink)"
          strokeWidth={2}
        />
        {/* Windshield hints orientation (front = top). */}
        <path
          d="M22 40 L72 40 L64 56 L30 56 Z"
          fill="none"
          stroke="var(--muted)"
          strokeWidth={1.5}
        />
        <text x={47} y={16} className="cardiag__front">
          FRONT
        </text>
      </svg>
      <figcaption className="cardiag__cap">
        {title}
        <span className="cardiag__area">{area}</span>
      </figcaption>
    </figure>
  );
}

export default function ContactDiagram({
  sv,
  cp,
  mode,
}: {
  sv: string;
  cp: string;
  mode: Mode;
}) {
  return (
    <div className="collision">
      <Car area={sv} mode={mode} title="Subject vehicle" variant="sv" />
      <span className="collision__bolt" aria-hidden="true">
        ⟷
      </span>
      <Car area={cp} mode={mode} title="Other party" variant="cp" />
    </div>
  );
}
