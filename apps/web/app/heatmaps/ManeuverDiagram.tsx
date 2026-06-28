"use client";

// A static "diagram equivalent" of a pre-crash maneuver pairing (the calmer
// alternative to an animation). Each vehicle gets a small top-down road tile
// with a directional arrow that classifies its movement — go straight, turn,
// back up, change lanes, U-turn, stop, etc. The raw movement text is shown
// verbatim underneath so nothing is lost in the classification.

type Kind =
  | "straight"
  | "accel"
  | "decel"
  | "backing"
  | "left"
  | "right"
  | "lane"
  | "merge"
  | "uturn"
  | "curve"
  | "stopped"
  | "parked"
  | "other";

// Order matters: more specific phrasings are tested first.
function classify(text: string): Kind {
  const t = (text || "").toLowerCase();
  if (!t) return "other";
  if (t.includes("u-turn") || t.includes("u turn") || t.includes("uturn"))
    return "uturn";
  if (t.includes("back")) return "backing";
  if (t.includes("park")) return "parked";
  if (t.includes("stop") || t.includes("stationary") || t.includes("standing"))
    return "stopped";
  if (t.includes("left")) return "left";
  if (t.includes("right")) return "right";
  if (t.includes("lane") || t.includes("passing") || t.includes("overtak"))
    return "lane";
  if (t.includes("merg") || t.includes("enter") || t.includes("leav"))
    return "merge";
  if (t.includes("curve") || t.includes("negotiat")) return "curve";
  if (t.includes("decel") || t.includes("slow") || t.includes("brak"))
    return "decel";
  if (t.includes("accel")) return "accel";
  if (t.includes("straight") || t.includes("proceed") || t.includes("going"))
    return "straight";
  return "other";
}

const KIND_LABEL: Record<Kind, string> = {
  straight: "Going straight",
  accel: "Accelerating",
  decel: "Slowing / braking",
  backing: "Backing up",
  left: "Turning left",
  right: "Turning right",
  lane: "Changing lanes",
  merge: "Merging / entering",
  uturn: "Making a U-turn",
  curve: "Negotiating a curve",
  stopped: "Stopped",
  parked: "Parked",
  other: "Other / unknown",
};

function Glyph({ kind, color }: { kind: Kind; color: string }) {
  const stroke = { stroke: color, strokeWidth: 4, fill: "none" } as const;
  const head = `url(#arrow-${color === "var(--accent)" ? "sv" : "cp"})`;
  switch (kind) {
    case "straight":
      return (
        <line x1={40} y1={58} x2={40} y2={14} {...stroke} markerEnd={head} />
      );
    case "accel":
      return (
        <line
          x1={40}
          y1={60}
          x2={40}
          y2={12}
          {...stroke}
          strokeWidth={6}
          markerEnd={head}
        />
      );
    case "decel":
      return (
        <g>
          <line x1={40} y1={56} x2={40} y2={16} {...stroke} markerEnd={head} />
          <line
            x1={30}
            y1={62}
            x2={50}
            y2={62}
            stroke={color}
            strokeWidth={3}
          />
          <line
            x1={30}
            y1={68}
            x2={50}
            y2={68}
            stroke={color}
            strokeWidth={3}
          />
        </g>
      );
    case "backing":
      return (
        <line x1={40} y1={44} x2={40} y2={90} {...stroke} markerEnd={head} />
      );
    case "left":
      return <path d="M40 60 Q40 30 16 28" {...stroke} markerEnd={head} />;
    case "right":
      return <path d="M40 60 Q40 30 64 28" {...stroke} markerEnd={head} />;
    case "lane":
      return (
        <line x1={34} y1={64} x2={62} y2={16} {...stroke} markerEnd={head} />
      );
    case "merge":
      return <path d="M26 70 Q40 44 58 18" {...stroke} markerEnd={head} />;
    case "uturn":
      return (
        <path d="M30 66 C30 18 66 18 66 60" {...stroke} markerEnd={head} />
      );
    case "curve":
      return <path d="M40 64 Q56 42 42 14" {...stroke} markerEnd={head} />;
    case "stopped":
      return (
        <g>
          <line
            x1={26}
            y1={40}
            x2={54}
            y2={40}
            stroke="#c0552b"
            strokeWidth={5}
          />
          <text x={40} y={62} className="maneuver__tag" fill="#c0552b">
            STOP
          </text>
        </g>
      );
    case "parked":
      return (
        <text x={40} y={48} className="maneuver__big" fill={color}>
          P
        </text>
      );
    default:
      return (
        <g>
          <line
            x1={40}
            y1={58}
            x2={40}
            y2={18}
            {...stroke}
            strokeDasharray="5 5"
            markerEnd={head}
          />
          <text x={40} y={78} className="maneuver__big" fill={color}>
            ?
          </text>
        </g>
      );
  }
}

function Vehicle({
  movement,
  title,
  variant,
}: {
  movement: string;
  title: string;
  variant: "sv" | "cp";
}) {
  const kind = classify(movement);
  const color = variant === "sv" ? "var(--accent)" : "#c0552b";
  return (
    <figure className="maneuver">
      <svg
        viewBox="0 0 80 104"
        className="maneuver__svg"
        role="img"
        aria-label={`${title}: ${KIND_LABEL[kind]}`}
      >
        <defs>
          <marker
            id={`arrow-${variant}`}
            viewBox="0 0 10 10"
            refX={6}
            refY={5}
            markerWidth={5}
            markerHeight={5}
            orient="auto-start-reverse"
          >
            <path d="M0 0 L10 5 L0 10 z" fill={color} />
          </marker>
        </defs>
        {/* Road tile + dashed centre line. */}
        <rect
          x={8}
          y={4}
          width={64}
          height={96}
          rx={6}
          fill="var(--bg-soft)"
          stroke="var(--line)"
        />
        <line
          x1={40}
          y1={6}
          x2={40}
          y2={98}
          stroke="var(--line)"
          strokeWidth={2}
          strokeDasharray="6 6"
        />
        <Glyph kind={kind} color={color} />
      </svg>
      <figcaption className="maneuver__cap">
        {title}
        <span className="maneuver__move">{movement || "—"}</span>
      </figcaption>
    </figure>
  );
}

export default function ManeuverDiagram({
  sv,
  cp,
}: {
  sv: string;
  cp: string;
}) {
  return (
    <div className="maneuver-pair">
      <Vehicle movement={sv} title="Subject vehicle" variant="sv" />
      <Vehicle movement={cp} title="Other party" variant="cp" />
    </div>
  );
}
