/**
 * Ambient landing background.
 *
 * A fixed, full-viewport aurora — three slowly drifting light pools in the brand
 * triad over a fine engineered grid. Pure CSS (transform/opacity keyframes defined
 * in globals.css), so it costs almost nothing and freezes cleanly under
 * prefers-reduced-motion via the global motion guard. It is purely decorative, so
 * it is hidden from assistive tech and never intercepts pointer events.
 */
export function LandingBackground() {
  return (
    <div aria-hidden="true" className="aurora-field">
      <div className="aurora-blob aurora-indigo" />
      <div className="aurora-blob aurora-cyan" />
      <div className="aurora-blob aurora-amber" />
      <div className="aurora-grid" />
    </div>
  );
}
