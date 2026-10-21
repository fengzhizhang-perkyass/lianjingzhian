const pending = new Map(),
  rendered = new Set();
let queue = [];
const observer = new IntersectionObserver(entries => entries.forEach(entry => {
  if (entry.isIntersecting && pending.has(entry.target)) {
    const options = pending.get(entry.target);
    pending.delete(entry.target);
    observer.unobserve(entry.target);
    draw(entry.target, ...options);
  }
}), {
  rootMargin: '100px'
});
const displayed = target => target.isConnected && target.getBoundingClientRect().width > 0 && target
  .getBoundingClientRect().height > 0;
const resizeObserver = new ResizeObserver(entries => {
  for (const {
      target
    }
    of entries)
    if (rendered.has(target) && displayed(target)) requestAnimationFrame(() => {
      if (rendered.has(target) && displayed(target) && target._fullLayout) window.Plotly.Plots.resize(
        target).catch(error => {
        if (displayed(target)) throw error;
      });
    });
});

function draw(element, figure, dark = false) {
  if (!window.Plotly) {
    queue.push([element, figure, dark]);
    return;
  }
  const layout = {
    ...figure.layout,
    autosize: true,
    width: undefined
  };
  if (innerWidth < 520) {
    layout.height = Math.min(layout.height || 320, dark ? 410 : 340);
    layout.font = {
      ...layout.font,
      size: 11
    };
    layout.margin = {
      l: 16,
      r: 16,
      t: 36,
      b: 52
    };
  }
  window.Plotly.react(element, figure.data, layout, {
    responsive: true,
    displaylogo: false,
    scrollZoom: dark,
    displayModeBar: 'hover',
    modeBarButtonsToRemove: ['select2d', 'lasso2d']
  });
  rendered.add(element);
  resizeObserver.observe(element);
}
export function plot(element, figure, dark = false) {
  if (typeof element === 'string') element = document.querySelector(element);
  if (!element) return;
  pending.set(element, [figure, dark]);
  observer.observe(element);
}
window.addEventListener('load', () => {
  for (const args of queue) draw(...args);
  queue = [];
});
export function clearPlot(element) {
  if (typeof element === 'string') element = document.querySelector(element);
  observer.unobserve(element);
  pending.delete(element);
  if (rendered.has(element)) {
    window.Plotly?.purge(element);
    rendered.delete(element);
    resizeObserver.unobserve(element);
  }
  element.replaceChildren();
}
export function clearPlots(root) {
  if (typeof root === 'string') root = document.querySelector(root);
  for (const element of new Set([...pending.keys(), ...rendered]))
    if (root.contains(element)) clearPlot(element);
}
export function basicFigure(data, title = '', dark = false) {
  return {
    data,
    layout: {
      title: {
        text: title,
        font: {
          size: 15
        }
      },
      height: 320,
      margin: {
        l: 35,
        r: 25,
        t: 45,
        b: 50
      },
      paper_bgcolor: dark ? '#10172C' : '#FFF',
      plot_bgcolor: dark ? '#10172C' : '#FFF',
      font: {
        family: 'PingFang SC, Microsoft YaHei, sans-serif',
        color: dark ? '#BBC8E2' : '#334155',
        size: 12
      },
      colorway: ['#4E65F5', '#61B8D9', '#B91C1C', '#D19839', '#7569FF']
    }
  };
}
export function pathFigure(path, threshold) {
  const fig = basicFigure([{
    x: path.nodes.map((_, i) => i),
    y: path.node_risks,
    type: 'scatter',
    mode: 'lines+markers',
    line: {
      color: '#4E65F5',
      width: 2
    },
    marker: {
      size: 8
    },
    customdata: path.nodes,
    hovertemplate: '第 %{x} 跳<br>%{customdata}<br>原始风险 %{y:.2f}<extra></extra>'
  }]);
  fig.layout.xaxis = {
    title: {
      text: '关系跳数（不是交易时间）'
    },
    dtick: Math.max(1, Math.floor(path.hop_count / 8))
  };
  fig.layout.yaxis = {
    range: [0, 100],
    title: {
      text: '原始地址风险'
    }
  };
  fig.layout.shapes = [{
    type: 'line',
    xref: 'paper',
    x0: 0,
    x1: 1,
    y0: threshold,
    y1: threshold,
    line: {
      dash: 'dash',
      color: '#B45309',
      width: 1
    }
  }];
  return fig;
}
export function highlightGraph(chart, path, selectedEdges = null, selectedNodes = []) {
  const keys = new Set((selectedEdges || path.nodes.slice(1).map((node, i) => [path.nodes[i], node])).map(
    edge => JSON.stringify(edge)));
  const fig = structuredClone(chart.figure);
  chart.edge_keys.forEach((edge, i) => {
    const active = keys.has(JSON.stringify(edge));
    fig.data[i].line = {
      color: active ? '#61D8FF' : '#536584',
      width: active ? 3 : 1.3
    };
    fig.layout.annotations[i].arrowcolor = active ? '#61D8FF' : '#536584';
  });
  fig.data.slice(chart.edge_keys.length).forEach(trace => {
    if (trace.customdata) trace.marker.line = {
      color: trace.customdata.map(([address]) => selectedNodes.includes(address) ? '#61D8FF' :
        '#AAB4CA'),
      width: trace.customdata.map(([address]) => selectedNodes.includes(address) ? 4 : 1.5)
    };
  });
  return fig;
}
export function evidencePathFigure(path, edges = null, nodes = []) {
  const count = path.nodes.length,
    cols = Math.min(count, 6),
    coords = path.nodes.map((_, i) => [i % cols * (Math.floor(i / cols) % 2 ? -1 : 1) + (Math.floor(i /
      cols) % 2 ? cols - 1 : 0), -Math.floor(i / cols)]),
    chosen = new Set((edges || path.nodes.slice(1).map((n, i) => [path.nodes[i], n])).map(edge => JSON
      .stringify(edge))),
    data = [],
    annotations = [];
  for (let i = 0; i < count - 1; i++) {
    const active = chosen.has(JSON.stringify([path.nodes[i], path.nodes[i + 1]]));
    const color = active ? '#4E65F5' : '#C3CCDD';
    data.push({
      x: [coords[i][0], coords[i + 1][0]],
      y: [coords[i][1], coords[i + 1][1]],
      mode: 'lines',
      line: {
        color,
        width: active ? 3 : 1
      },
      hoverinfo: 'skip',
      showlegend: false
    });
    annotations.push({
      x: coords[i][0] * .2 + coords[i + 1][0] * .8,
      y: coords[i][1] * .2 + coords[i + 1][1] * .8,
      ax: coords[i][0] * .45 + coords[i + 1][0] * .55,
      ay: coords[i][1] * .45 + coords[i + 1][1] * .55,
      xref: 'x',
      yref: 'y',
      axref: 'x',
      ayref: 'y',
      showarrow: true,
      arrowhead: 3,
      arrowcolor: color,
      arrowwidth: 1.5
    });
  }
  data.push({
    x: coords.map(c => c[0]),
    y: coords.map(c => c[1]),
    mode: 'markers+text',
    text: path.nodes.map((_, i) => i + '跳'),
    textposition: 'top center',
    showlegend: false,
    customdata: path.nodes.map((a, i) => [a, path.node_risks[i]]),
    hovertemplate: '%{customdata[0]}<br>风险 %{customdata[1]:.2f}<extra></extra>',
    marker: {
      size: path.nodes.map(a => nodes.includes(a) ? 22 : 16),
      color: path.node_risks.map(v => v >= 80 ? '#B91C1C' : v >= 60 ? '#C2410C' : v >= 30 ? '#B45309' :
        '#657794'),
      line: {
        color: path.nodes.map(a => nodes.includes(a) ? '#61D8FF' : '#fff'),
        width: 3
      }
    }
  });
  const fig = basicFigure(data);
  fig.layout = {
    ...fig.layout,
    height: 300,
    xaxis: {
      visible: false
    },
    yaxis: {
      visible: false
    },
    annotations
  };
  return fig;
}
