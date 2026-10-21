import {
  setupLanding
} from './landing.js';
import {
  setupRouter
} from './router.js';

let plotlyPromise;

function loadPlotly() {
  if (window.Plotly) return Promise.resolve();
  if (!plotlyPromise) {
    plotlyPromise = new Promise((resolve, reject) => {
      const script = document.createElement('script');
      script.src = '/assets/vendor/plotly.min.js';
      script.onload = resolve;
      script.onerror = () => {
        script.remove();
        plotlyPromise = null;
        reject(new Error('图表组件加载失败，请重试'));
      };
      document.head.append(script);
    });
  }
  return plotlyPromise;
}
setupLanding();
setupRouter(async () => {
  await loadPlotly();
  const {
    initWorkspace
  } = await import('./workspace.js');
  await initWorkspace();
});
