// Particle connections adapted from DongWu's setupHeroNetwork. No fake market data.
import {
  $
} from './dom.js';
export function setupBackground() {
  const canvas = $('#hero-network'),
    hero = $('#home'),
    ctx = canvas.getContext('2d'),
    media = matchMedia('(prefers-reduced-motion: reduce)');
  let width = 0,
    height = 0,
    points = [],
    frame = 0,
    visible = true,
    paused = false,
    pointer = {
      x: -1000,
      y: -1000
    },
    last = 0;
  const allowed = () => !paused && !media.matches && !document.hidden && visible && document.body.dataset
    .page === 'landing';

  function draw(time = 0) {
    frame = 0;
    const delta = Math.min(2, (time - last) / 16.7 || 1);
    last = time;
    ctx.clearRect(0, 0, width, height);
    points.forEach((point, index) => {
      if (allowed()) {
        point.x += point.vx * delta;
        point.y += point.vy * delta;
        if (point.x < width * .32 || point.x > width + 12) point.vx *= -1;
        if (point.y < 0 || point.y > height) point.vy *= -1;
        const dx = pointer.x - point.x,
          dy = pointer.y - point.y;
        if (Math.hypot(dx, dy) < 130) {
          point.x -= dx * .0015;
          point.y -= dy * .0015;
        }
      }
      for (let i = index + 1; i < points.length; i++) {
        const next = points[i],
          distance = Math.hypot(point.x - next.x, point.y - next.y);
        if (distance < 150) {
          ctx.strokeStyle = `rgba(88,117,255,${.35*(1-distance/150)})`;
          ctx.lineWidth = .7;
          ctx.beginPath();
          ctx.moveTo(point.x, point.y);
          ctx.lineTo(next.x, next.y);
          ctx.stroke();
        }
      }
      ctx.fillStyle = point.radius > 2 ? '#8ce8ff' : 'rgba(112,125,255,.78)';
      ctx.beginPath();
      ctx.arc(point.x, point.y, point.radius, 0, Math.PI * 2);
      ctx.fill();
    });
    if (allowed()) frame = requestAnimationFrame(draw);
  }

  function sync() {
    cancelAnimationFrame(frame);
    frame = 0;
    hero.classList.toggle('motion-paused', !allowed());
    $$pauseSvg(!allowed());
    if (allowed()) frame = requestAnimationFrame(draw);
    else if (visible) draw();
  }

  function $$pauseSvg(stop) {
    const svg = hero.querySelector('svg');
    if (stop) svg.pauseAnimations?.();
    else svg.unpauseAnimations?.();
  }

  function resize() {
    if (!hero.clientWidth || !hero.clientHeight) {
      sync();
      return;
    }
    const ratio = Math.min(devicePixelRatio || 1, 1.5);
    width = hero.clientWidth;
    height = hero.clientHeight;
    canvas.width = width * ratio;
    canvas.height = height * ratio;
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    const count = width < 600 ? 30 : Math.min(72, Math.max(34, Math.floor(width / 22)));
    points = Array.from({
      length: count
    }, (_, i) => ({
      x: width * .35 + Math.random() * width * .7,
      y: Math.random() * height,
      vx: (Math.random() - .5) * .22,
      vy: (Math.random() - .5) * .22,
      radius: i % 11 === 0 ? 2.2 : 1
    }));
    sync();
  }
  hero.addEventListener('pointermove', event => {
    const rect = hero.getBoundingClientRect();
    pointer = {
      x: event.clientX - rect.left,
      y: event.clientY - rect.top
    };
  }, {
    passive: true
  });
  hero.addEventListener('pointerleave', () => pointer = {
    x: -1000,
    y: -1000
  });
  new ResizeObserver(resize).observe(hero);
  new IntersectionObserver(entries => {
    visible = entries[0].isIntersecting;
    sync();
  }).observe(hero);
  document.addEventListener('visibilitychange', sync);
  window.addEventListener('pagevisibilitychange', sync);
  media.addEventListener('change', sync);
  $('#motion-toggle').addEventListener('click', () => {
    paused = !paused;
    $('#motion-toggle').setAttribute('aria-pressed', String(paused));
    $('#motion-toggle').textContent = paused ? '恢复背景动效' : '暂停背景动效';
    sync();
  });
  resize();
}
