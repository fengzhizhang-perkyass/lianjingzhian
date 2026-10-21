import {
  $,
  $$
} from './dom.js';
import {
  state
} from './state.js';
import {
  goLanding,
  goWorkspace
} from './router.js';

// Business actions switch modules; marketing links use their section anchors.
export function navigate(hash) {
  const module = {
    '#risk-scoring': 'risk',
    '#relation-tracing': 'trace',
    '#evidence-fusion': 'report',
    '#investigation-queue': 'queue'
  } [hash];
  return module ? goWorkspace(module) : goLanding(hash);
}

export function setupLandingNavigation() {
  let scheduled = false;
  const links = $$('.landing-nav a');

  function mark(hash) {
    links.forEach(link => new URL(link.href).hash === hash ? link.setAttribute('aria-current', 'location') :
      link.removeAttribute('aria-current'));
  }

  function spy() {
    scheduled = false;
    if (state.page !== 'landing') return;
    const offset = $('.landing-header').getBoundingClientRect().height + 90;
    let active = $('#home');
    for (const section of $$('#landing-main>section'))
      if (section.getBoundingClientRect().top <= offset) active = section;
    const hash = '#' + active.id;
    mark(hash);
    if (location.hash !== hash) history.replaceState(null, '', '/' + hash);
  }
  window.addEventListener('scroll', () => {
    if (!scheduled && state.page === 'landing') {
      scheduled = true;
      requestAnimationFrame(spy);
    }
  }, {
    passive: true
  });
  window.addEventListener('routechange', event => {
    if (event.detail.page === 'landing') mark(event.detail.hash);
  });
}
