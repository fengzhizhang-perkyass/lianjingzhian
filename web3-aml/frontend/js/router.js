import {
  $,
  $$
} from './dom.js';
import {
  state
} from './state.js';

export const modules = [
  ['queue', '调查优先队列'],
  ['risk', '地址风险分析'],
  ['trace', '关系链追踪'],
  ['report', 'AI分析报告']
];
let initializeWorkspace;
let workspacePromise;
let transition = 0;

function routeFromUrl() {
  if (location.pathname.startsWith('/workspace')) {
    const module = location.pathname.split('/')[2];
    return {
      page: 'workspace',
      module: modules.some(([key]) => key === module) ? module : state.lastModule
    };
  }
  return {
    page: 'landing',
    hash: ['#home', '#background', '#path', '#evidence'].includes(location.hash) ? location.hash : '#home'
  };
}

function headerHeight() {
  const header = document.querySelector(state.page === 'workspace' ? '.workspace-header' : '.landing-header');
  const height = header.getBoundingClientRect().height;
  if (height) document.documentElement.style.setProperty('--nav-height', height + 'px');
}

async function display(route, historyMode = 'push', focus = true) {
  const token = ++transition;
  const workspace = route.page === 'workspace';
  state.page = route.page;
  if (workspace) {
    state.module = route.module;
    state.lastModule = route.module;
    state.hasWorkspace = true;
  }
  $('#landing-view').hidden = workspace;
  $('#workspace-view').hidden = !workspace;
  if (!workspace) $('#toast').hidden = true;
  document.body.dataset.page = route.page;
  document.body.classList.toggle('workspace-mode', workspace);
  document.body.classList.toggle('landing-mode', !workspace);
  const index = modules.findIndex(([key]) => key === state.module);
  $$('[data-module-panel]').forEach(panel => panel.hidden = panel.dataset.modulePanel !== state.module);
  $$('.module-link').forEach(link => {
    if (link.dataset.module === state.module) link.setAttribute('aria-current', 'page');
    else link.removeAttribute('aria-current');
  });
  $('#module-position').style.width = (index + 1) * 25 + '%';
  $('#module-position-text').textContent = `当前模块 ${index+1}/4：${modules[index][1]}`;
  document.title = workspace ? modules[index][1] + ' · 链境智安' : '链境智安——基于多维证据融合的链上反洗钱与可解释研判系统';
  $('.skip-link').href = workspace ? '/workspace/' + state.module : '/#path';
  $('.skip-link').textContent = workspace ? '跳到当前分析模块' : '跳到主要内容';
  const url = workspace ? '/workspace/' + state.module : '/' + route.hash;
  if (historyMode !== 'none' && location.pathname + location.hash !== url) {
    history[historyMode === 'replace' ? 'replaceState' : 'pushState'](null, '', url);
  }
  headerHeight();
  if (workspace) {
    window.scrollTo({
      top: 0,
      behavior: 'instant'
    });
    if (focus) $('h2', $(`[data-module-panel="${state.module}"]`))?.focus({
      preventScroll: true
    });
  } else {
    const target = $(route.hash);
    target.scrollIntoView({
      block: 'start',
      behavior: focus && !matchMedia('(prefers-reduced-motion: reduce)').matches ? 'smooth' : 'instant'
    });
    if (focus) $('h1,h2', target)?.focus({
      preventScroll: true
    });
  }
  window.dispatchEvent(new CustomEvent('pagevisibilitychange'));
  if (workspace) {
    try {
      workspacePromise ||= initializeWorkspace().catch(error => {
        workspacePromise = null;
        throw error;
      });
      await workspacePromise;
      $('#reconnect').onclick = null;
    } catch (error) {
      if (token !== transition) return;
      $('#service-state').textContent = '工作台加载失败';
      $('#reconnect').hidden = false;
      $('#reconnect').onclick = () => display(route, 'none');
      $('#workspace-model').textContent = error.message;
      return;
    }
  }
  if (token !== transition) return;
  window.dispatchEvent(new CustomEvent('routechange', {
    detail: {
      ...route,
      module: state.module
    }
  }));
}

export function goWorkspace(module) {
  const key = module || (state.hasWorkspace ? state.lastModule : 'queue');
  return display({
    page: 'workspace',
    module: modules.some(([name]) => name === key) ? key : 'queue'
  });
}
export function goLanding(hash = '#home') {
  return display({
    page: 'landing',
    hash
  });
}

export function setupRouter(loader) {
  initializeWorkspace = loader;
  new ResizeObserver(headerHeight).observe($('.landing-header'));
  new ResizeObserver(headerHeight).observe($('.workspace-header'));
  document.addEventListener('click', event => {
    const link = event.target.closest('a');
    if (!link || event.defaultPrevented || event.metaKey || event.ctrlKey || event.shiftKey || event
      .altKey || event.button !== 0 || link.hasAttribute('download')) return;
    const url = new URL(link.href, location.href);
    if (url.origin !== location.origin) return;
    if (link.classList.contains('skip-link') && state.page === 'workspace') {
      event.preventDefault();
      $('h2', $(`[data-module-panel="${state.module}"]`))?.focus();
      return;
    }
    if (link.hasAttribute('data-start-analysis')) {
      event.preventDefault();
      goWorkspace();
    } else if (url.pathname.startsWith('/workspace')) {
      event.preventDefault();
      goWorkspace(url.pathname.split('/')[2]);
    } else if (url.pathname === '/' && ['#home', '#background', '#path', '#evidence'].includes(url.hash)) {
      event.preventDefault();
      goLanding(url.hash);
    }
  });
  window.addEventListener('popstate', () => display(routeFromUrl(), 'none'));
  display(routeFromUrl(), 'replace', false);
}
