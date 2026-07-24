/**
 * Applies the saved theme before first paint.
 *
 * Runs synchronously in <head> so the correct `data-theme` is on <html> before
 * anything renders — without it a saved light preference flashes dark on every
 * load. Reads localStorage, falls back to "system", and never throws (private
 * mode can refuse storage). Inline by necessity: it must run before paint.
 */
export function ThemeScript() {
  const js = `(function(){try{var t=localStorage.getItem('agoreum-theme');if(t!=='light'&&t!=='dark'&&t!=='system')t='system';document.documentElement.dataset.theme=t;}catch(e){document.documentElement.dataset.theme='system';}})();`;
  return <script dangerouslySetInnerHTML={{ __html: js }} />;
}
