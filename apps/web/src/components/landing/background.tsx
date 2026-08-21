/**
 * The ambient landing background.
 *
 * What was here before was three blurred colour blobs drifting over a grid. It
 * was competent and it was also the default: the same aurora ships on most
 * developer-tool landing pages, and nothing in it was Agoreum's. A background
 * that could carry any other company's name is not an identity.
 *
 * This is built from the mark instead. The Agoreum mark is a loop, so the field
 * is concentric loop geometry: two counter-rotating ring groups, struck as thin
 * arcs rather than filled shapes, converging on a held centre. That reads as
 * what the product actually is. Two parties, value turning between them, and a
 * centre where it rests until the contract says otherwise.
 *
 * Restraint is the point. The rings sit at very low opacity and the whole field
 * is masked to fade well before the text column, so this is something you feel
 * rather than something you look at. Nothing here competes with the headline.
 *
 * Everything animates on `transform` and `opacity` only, so it stays on the
 * compositor and costs effectively nothing. The rotations are 150 and 190
 * seconds, slow enough to read as drift rather than as motion. The global
 * reduced-motion guard freezes them.
 *
 * Deliberately not a canvas and not WebGL. This is decoration behind text; it
 * has no business shipping a renderer, blocking the main thread, or spending a
 * phone's battery. Inline SVG stays crisp at any density and costs one paint.
 *
 * **Depth, added 2026-08-18, without reversing that decision.** The field now
 * sits on a perspective stage with a small rotateX, so the loops read as a plane
 * receding rather than as flat circles printed on the page. That is genuine
 * dimensionality from one CSS transform: no renderer, no main-thread cost, and
 * it also breaks the perfect-circle read the original comment worried about,
 * since a tilted ring is no longer a target symbol.
 *
 * **The travellers are the only motion here that says anything.** Short bright
 * arcs ride the ring radii at their own periods, appearing, crossing, and fading
 * out again. They are what the product does: value moving between two parties,
 * and stopping. Each is a head and a dimmer tail in one rotating group, which is
 * a comet built from two dashes and a rotation rather than from a filter, so it
 * stays on the compositor like everything else.
 *
 * They are deliberately sparse and slow, and they fade rather than looping
 * visibly, because a light that circles forever is an ornament. One that arrives
 * and settles is a description.
 *
 * **The core is where value rests.** A soft centre breathing on opacity alone,
 * at the point both ring groups turn around. Escrow is the still part of this
 * product and it should be the still part of the picture.
 */
export function LandingBackground() {
  return (
    <div aria-hidden="true" className="brand-field">
      {/* A single warm-cool wash rather than three competing pools. One light
          source is calmer, and calm is the whole register we are aiming at. */}
      <div className="brand-wash" />

      <div className="brand-stage">
      <svg
        className="brand-rings"
        viewBox="0 0 1200 1200"
        fill="none"
        preserveAspectRatio="xMidYMid slice"
      >
        <defs>
          {/* The stroke fades around each ring so the circles never close into
              hard outlines. Rings you can trace all the way round read as
              clip art; rings that dissolve read as light. */}
          <linearGradient id="ring-indigo" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stopColor="var(--color-brand-400)" stopOpacity="0" />
            <stop offset="42%" stopColor="var(--color-brand-400)" stopOpacity="0.55" />
            <stop offset="72%" stopColor="var(--color-brand-500)" stopOpacity="0.14" />
            <stop offset="100%" stopColor="var(--color-brand-500)" stopOpacity="0" />
          </linearGradient>
          <linearGradient id="ring-signal" x1="1" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="var(--color-signal-400)" stopOpacity="0" />
            <stop offset="38%" stopColor="var(--color-signal-400)" stopOpacity="0.4" />
            <stop offset="70%" stopColor="var(--color-signal-500)" stopOpacity="0.1" />
            <stop offset="100%" stopColor="var(--color-signal-500)" stopOpacity="0" />
          </linearGradient>
        </defs>

        {/* Clockwise group. Struck as dashed arcs of uneven length so the
            geometry reads as engineered rather than as a target symbol. */}
        <g className="ring-group ring-group--cw">
          <circle cx="600" cy="600" r="560" stroke="url(#ring-indigo)" strokeWidth="1" />
          <circle
            cx="600"
            cy="600"
            r="452"
            stroke="url(#ring-indigo)"
            strokeWidth="1.25"
            strokeDasharray="180 90 40 120"
          />
          <circle
            cx="600"
            cy="600"
            r="318"
            stroke="url(#ring-signal)"
            strokeWidth="1"
            strokeDasharray="60 200"
          />
        </g>

        {/* Counter-clockwise group. Two groups turning against each other is the
            one piece of motion here that means something: it is the only reason
            the field is never quite the same shape twice. */}
        <g className="ring-group ring-group--ccw">
          <circle
            cx="600"
            cy="600"
            r="506"
            stroke="url(#ring-signal)"
            strokeWidth="1"
            strokeDasharray="240 400"
          />
          <circle
            cx="600"
            cy="600"
            r="386"
            stroke="url(#ring-indigo)"
            strokeWidth="1"
            strokeDasharray="30 60 140 40"
          />
          <circle cx="600" cy="600" r="238" stroke="url(#ring-indigo)" strokeWidth="1.5" />
        </g>
        {/* Settlement travellers. Each group turns at its own period so they
            never line up, and each arc is a bright head with a dimmer tail
            behind it, which is what makes it read as something moving along the
            path rather than a dash that happens to be there. The opacity
            animation is what turns a loop into an arrival. */}
        <g className="ring-traveller ring-traveller--outer">
          <circle
            cx="600"
            cy="600"
            r="452"
            className="traveller-tail"
            stroke="var(--color-brand-400)"
            strokeWidth="1.5"
            strokeLinecap="round"
            strokeDasharray="300 2540"
          />
          <circle
            cx="600"
            cy="600"
            r="452"
            className="traveller-head"
            stroke="var(--color-brand-300)"
            strokeWidth="2.5"
            strokeLinecap="round"
            strokeDasharray="90 2750"
          />
        </g>

        <g className="ring-traveller ring-traveller--mid">
          <circle
            cx="600"
            cy="600"
            r="318"
            className="traveller-tail"
            stroke="var(--color-signal-400)"
            strokeWidth="1.25"
            strokeLinecap="round"
            strokeDasharray="220 1778"
          />
          <circle
            cx="600"
            cy="600"
            r="318"
            className="traveller-head"
            stroke="var(--color-signal-300)"
            strokeWidth="2"
            strokeLinecap="round"
            strokeDasharray="70 1928"
          />
        </g>

        <g className="ring-traveller ring-traveller--inner">
          <circle
            cx="600"
            cy="600"
            r="238"
            className="traveller-tail"
            stroke="var(--color-brand-400)"
            strokeWidth="1.25"
            strokeLinecap="round"
            strokeDasharray="160 1335"
          />
          <circle
            cx="600"
            cy="600"
            r="238"
            className="traveller-head"
            stroke="var(--color-brand-300)"
            strokeWidth="2"
            strokeLinecap="round"
            strokeDasharray="56 1439"
          />
        </g>
      </svg>

      </div>

      {/* Where value rests. Both ring groups turn around this point, so it is
          already the centre of the geometry; it just was not lit. */}
      <div className="brand-core" />

      {/* The engineered grid stays. It was the one part of the old field that
          was doing real work: it reads as precision scaffolding and it gives
          the loops something rectilinear to sit against. */}
      <div className="brand-grid" />
    </div>
  );
}
