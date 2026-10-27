// The narrative and full-demo links remain available without JavaScript.
const sectionLinks = [...document.querySelectorAll('nav a[href^="#"]')];
if ('IntersectionObserver' in window) {
  const observer = new IntersectionObserver((entries) => {
    for (const entry of entries) {
      const link = sectionLinks.find((item) => item.hash === `#${entry.target.id}`);
      if (link) {
        if (entry.isIntersecting) link.setAttribute('aria-current', 'location');
        else link.removeAttribute('aria-current');
      }
    }
  }, { rootMargin: '-15% 0px -60% 0px' });
  for (const link of sectionLinks) {
    const section = document.getElementById(link.hash.slice(1));
    if (section) observer.observe(section);
  }
}

// Reuse the actual demo viewer. The frame starts inert so scrolling the page
// cannot accidentally zoom its canvas; interaction is an explicit choice.
const viewer = document.getElementById('memory-viewer');
const viewerFrame = document.getElementById('viewer-frame');
const viewerToggle = document.getElementById('viewer-toggle');
const viewerLoading = document.getElementById('viewer-loading');
const viewerInstructions = document.getElementById('viewer-instructions');
if (viewer && viewerFrame && viewerToggle && viewerLoading && viewerInstructions) {
  let ready = false;
  let frameObserver;
  let loadTimer;
  const setInteraction = (active) => {
    viewer.inert = !active;
    viewer.tabIndex = active ? 0 : -1;
    viewerFrame.classList.toggle('is-interactive', active);
    viewerToggle.setAttribute('aria-pressed', String(active));
    viewerToggle.textContent = active ? 'Return to page ↓' : 'Interact with graph ↗';
    viewerInstructions.textContent = active
      ? 'Select a node to inspect its connections. Choose “Return to page” or press Escape to resume page scrolling.'
      : 'Scroll to continue the page. Choose “Interact with graph” to select nodes and follow relationships.';
  };
  const showFallback = (message) => {
    ready = false;
    setInteraction(false);
    viewerToggle.hidden = true;
    viewerLoading.replaceChildren(document.createTextNode(message));
    const link = document.createElement('a');
    link.href = 'demo/';
    link.textContent = 'Open the demo directly ↗';
    viewerLoading.append(link);
    viewerLoading.hidden = false;
  };
  const checkViewer = () => {
    try {
      const doc = viewer.contentDocument;
      const snapshotState = doc?.documentElement.dataset.publicSnapshotState;
      const error = doc?.getElementById('error');
      // The adapter marks ready only after source validation and graph draw.
      // A canvas and the UI status alone can exist before data has loaded.
      if (snapshotState === 'error' || (error && !error.classList.contains('hidden') && error.textContent.trim())) {
        clearTimeout(loadTimer);
        showFallback('The graph could not be loaded here.');
      } else if (snapshotState === 'ready' && doc?.querySelector('#cy canvas')) {
        ready = true;
        clearTimeout(loadTimer);
        viewerLoading.hidden = true;
        viewerToggle.hidden = false;
      }
    } catch {
      showFallback('The embedded viewer is unavailable.');
    }
  };
  const observeViewer = () => {
    frameObserver?.disconnect();
    try {
      const doc = viewer.contentDocument;
      if (doc?.body) {
        frameObserver = new MutationObserver(checkViewer);
        frameObserver.observe(doc.documentElement, { childList: true, subtree: true, attributes: true });
        doc.addEventListener('keydown', (event) => {
          if (event.key === 'Escape') {
            setInteraction(false);
            viewerToggle.focus({ preventScroll: true });
          }
        });
      }
      checkViewer();
    } catch {
      showFallback('The embedded viewer is unavailable.');
    }
  };
  viewer.addEventListener('load', observeViewer);
  viewer.addEventListener('error', () => showFallback('The embedded viewer is unavailable.'));
  viewerToggle.addEventListener('click', () => {
    if (!ready) return;
    const active = viewerToggle.getAttribute('aria-pressed') !== 'true';
    setInteraction(active);
    if (active) viewer.focus({ preventScroll: true });
  });
  loadTimer = setTimeout(() => {
    if (!ready) showFallback('The graph is taking longer to load.');
  }, 20000);
  // Covers a cached iframe that finished before this deferred script ran.
  if (viewer.contentDocument?.readyState === 'complete') observeViewer();
}
