/**
 * Polybot Forensics Dashboard Module
 *
 * Fetches from http://localhost:8888/api/... endpoints and renders
 * execution analysis, TTL rescue curves, cost waterfalls, blocked
 * order breakdowns, round-trips, and decision context heatmaps.
 */

const FORENSICS_API = 'http://localhost:8888/api';
let _forensicsData = null;
let _forensicsSSE = null;
let _forensicsError = null;

// ── Data fetching ──

async function fetchForensicsData() {
  try {
    const r = await fetch(FORENSICS_API + '/forensics?t=' + Date.now());
    if (r.ok) {
      _forensicsData = await r.json();
      _forensicsError = null;
    } else {
      _forensicsError = `Server returned ${r.status}`;
    }
  } catch (e) {
    _forensicsError = 'Server not running — start with: polybot-server';
  }
}

function startForensicsSSE() {
  if (_forensicsSSE) return;
  try {
    _forensicsSSE = new EventSource(FORENSICS_API + '/sse');
    _forensicsSSE.onmessage = (e) => {
      try {
        const data = JSON.parse(e.data);
        if (!data.error) {
          _forensicsData = data;
          _forensicsError = null;
          if (selectedView === 'forensics') renderForensicsView();
        }
      } catch (_) {}
    };
    _forensicsSSE.onerror = () => {
      _forensicsSSE.close();
      _forensicsSSE = null;
    };
  } catch (_) {}
}

// ── Main renderer ──

function renderForensicsView() {
  const grid = document.getElementById('contentGrid');
  if (!grid) return;

  if (!_forensicsData) {
    grid.innerHTML = `<div class="panel panel-full" style="padding:3rem;text-align:center">
      <div style="font:600 1.1rem/1 var(--display);color:var(--text-secondary);margin-bottom:0.75rem">
        ${_forensicsError || 'Loading forensics data...'}
      </div>
      <div style="color:var(--text-tertiary);font-size:0.8rem">
        Run <code style="background:var(--bg-inset);padding:0.2rem 0.5rem;border-radius:4px">polybot-server --db logs/polybot.db</code> to start the forensics API
      </div>
    </div>`;
    return;
  }

  const d = _forensicsData;
  let h = '';

  // ── A: Execution Overview ──
  h += renderExecutionSection(d);

  // ── B: TTL Rescue Curve ──
  h += renderTTLSection(d);

  // ── C: Cost Waterfall ──
  h += renderCostsSection(d);

  // ── D: Blocked Orders ──
  h += renderBlockedSection(d);

  // ── E: Round-Trips ──
  h += renderRoundtripsSection(d);

  // ── F: Decision Context ──
  h += renderContextSection(d);

  grid.innerHTML = h;
}

// ── Section Renderers ──

function renderExecutionSection(d) {
  const agg = d.aggregate_metrics || {};
  const orders = d.order_metrics || [];
  const fillRate = ((agg.fill_rate || 0) * 100).toFixed(0);
  const total = agg.total_orders || 0;
  const filled = agg.filled_count || 0;

  let h = `<div class="panel panel-full">
    <div class="panel-header">A: Execution Overview</div>
    <div class="metrics-row" style="margin-bottom:0.75rem">
      <div class="metric"><div class="metric-label">Fill Rate</div>
        <div class="metric-value ${fillRate >= 50 ? 'v-green' : 'v-red'}">${fillRate}%</div>
        <div class="metric-sub">${filled}/${total} orders</div></div>
      <div class="metric"><div class="metric-label">P50 Latency</div>
        <div class="metric-value v-cyan">${fmtMs(agg.p50_latency_ms)}</div>
        <div class="metric-sub">submit → fill</div></div>
      <div class="metric"><div class="metric-label">P95 Latency</div>
        <div class="metric-value v-amber">${fmtMs(agg.p95_latency_ms)}</div>
        <div class="metric-sub">worst case</div></div>
      <div class="metric"><div class="metric-label">P50 Drift</div>
        <div class="metric-value">${agg.p50_drift_bps != null ? agg.p50_drift_bps.toFixed(1) + 'bps' : '--'}</div>
        <div class="metric-sub">ask movement</div></div>
    </div>`;

  // Fill source breakdown bar
  const sources = agg.by_fill_source || {};
  const srcEntries = Object.entries(sources).sort((a, b) => b[1] - a[1]);
  if (srcEntries.length > 0) {
    h += '<div style="display:flex;gap:0.5rem;margin-bottom:0.75rem;flex-wrap:wrap">';
    const colors = { status_poll: 'var(--green)', size_matched: 'var(--cyan)', post_cancel: 'var(--amber)', stealth_balance: 'var(--purple)', timeout: 'var(--red)' };
    for (const [src, cnt] of srcEntries) {
      const pct = total > 0 ? (cnt / total * 100).toFixed(0) : 0;
      const color = colors[src] || 'var(--text-muted)';
      h += `<div style="background:var(--bg-inset);border:1px solid var(--border-subtle);border-radius:var(--radius-sm);padding:0.35rem 0.6rem;font-size:0.75rem">
        <span style="color:${color};font-weight:600">${src}</span>
        <span style="color:var(--text-tertiary);margin-left:0.3rem">${cnt} (${pct}%)</span>
      </div>`;
    }
    h += '</div>';
  }

  // Orders table
  if (orders.length > 0) {
    h += `<div style="overflow-x:auto"><table class="iv-res-table">
      <thead><tr><th>Order</th><th>Side</th><th>Candle</th><th>D→S ms</th><th>Drift bps</th><th>Filled</th><th>Source</th><th>Latency ms</th><th>TTL</th></tr></thead><tbody>`;
    for (const o of orders) {
      const sc = o.side === 'BUY' ? 'var(--green)' : 'var(--red)';
      const fc = o.filled ? 'var(--green)' : 'var(--red)';
      h += `<tr>
        <td style="font-size:0.7rem;color:var(--text-muted)">${(o.order_id || '').slice(0, 12)}</td>
        <td style="color:${sc};font-weight:600">${o.side}</td>
        <td>${o.candle_id}</td>
        <td>${o.decision_to_submit_ms?.toFixed(0) ?? '--'}</td>
        <td>${o.ask_drift_bps != null ? o.ask_drift_bps.toFixed(1) : '--'}</td>
        <td style="color:${fc};font-weight:600">${o.filled ? 'YES' : 'NO'}</td>
        <td>${o.fill_source || 'timeout'}</td>
        <td>${o.fill_latency_ms != null ? o.fill_latency_ms.toFixed(0) : '--'}</td>
        <td>${o.ttl_used}</td>
      </tr>`;
    }
    h += '</tbody></table></div>';
  }
  h += '</div>';
  return h;
}

function renderTTLSection(d) {
  const agg = d.ttl_aggregate || {};
  const cfs = d.ttl_counterfactuals || [];
  const grid = agg.grid_ttls || [];
  const rescued = agg.rescued_at || {};
  const total = agg.total_timeouts || 0;

  let h = `<div class="panel panel-full">
    <div class="panel-header">B: TTL Rescue Curve</div>
    <div style="color:var(--text-secondary);font-size:0.8rem;margin-bottom:0.75rem">${total} timed-out orders analyzed</div>`;

  if (grid.length > 0 && total > 0) {
    // Bar chart
    const maxRescued = Math.max(...Object.values(rescued), 1);
    h += '<div style="display:flex;align-items:flex-end;gap:0.5rem;height:120px;margin-bottom:0.75rem;padding:0 0.5rem">';
    for (const ttl of grid) {
      const cnt = rescued[ttl] || 0;
      const pct = cnt / total * 100;
      const barH = Math.max(cnt / maxRescued * 100, 4);
      h += `<div style="flex:1;display:flex;flex-direction:column;align-items:center;gap:0.3rem">
        <span style="font-size:0.65rem;color:var(--text-tertiary)">${cnt}</span>
        <div style="width:100%;height:${barH}%;background:var(--amber);border-radius:3px 3px 0 0;min-height:3px"></div>
        <span style="font-size:0.65rem;color:var(--text-muted)">${ttl}s</span>
      </div>`;
    }
    h += '</div>';

    // Table
    h += '<table class="iv-res-table"><thead><tr><th>TTL (s)</th><th>Rescued</th><th>Cumulative %</th></tr></thead><tbody>';
    for (const ttl of grid) {
      const cnt = rescued[ttl] || 0;
      const pct = total > 0 ? (cnt / total * 100).toFixed(0) : '--';
      h += `<tr><td style="font-weight:600">${ttl}</td><td>${cnt}</td><td>${pct}%</td></tr>`;
    }
    h += '</tbody></table>';
  } else {
    h += '<div style="color:var(--text-muted);font-size:0.8rem;padding:1rem;text-align:center">No timeout data</div>';
  }

  h += '</div>';
  return h;
}

function renderCostsSection(d) {
  const agg = d.cost_aggregate || {};
  const bds = d.cost_breakdowns || [];

  let h = `<div class="panel panel-full">
    <div class="panel-header">C: Cost Breakdown</div>
    <div class="metrics-row" style="margin-bottom:0.75rem">
      <div class="metric"><div class="metric-label">Total Fees</div>
        <div class="metric-value">${fmtDollar(agg.total_fees)}</div></div>
      <div class="metric"><div class="metric-label">Slippage Cost</div>
        <div class="metric-value">${fmtDollar(agg.total_slippage_cost)}</div></div>
      <div class="metric"><div class="metric-label">Drift Cost</div>
        <div class="metric-value">${fmtDollar(agg.total_drift_cost)}</div></div>
    </div>`;

  // Stacked bar: fees vs slippage vs drift
  const totalAll = (agg.total_fees || 0) + (agg.total_slippage_cost || 0) + (agg.total_drift_cost || 0);
  if (totalAll > 0) {
    const fp = (agg.total_fees || 0) / totalAll * 100;
    const sp = (agg.total_slippage_cost || 0) / totalAll * 100;
    const dp = (agg.total_drift_cost || 0) / totalAll * 100;
    h += `<div style="display:flex;height:24px;border-radius:4px;overflow:hidden;margin-bottom:0.75rem">
      <div style="width:${fp}%;background:var(--cyan)" title="Fees: ${fp.toFixed(0)}%"></div>
      <div style="width:${sp}%;background:var(--amber)" title="Slippage: ${sp.toFixed(0)}%"></div>
      <div style="width:${dp}%;background:var(--red)" title="Drift: ${dp.toFixed(0)}%"></div>
    </div>
    <div style="display:flex;gap:1rem;font-size:0.7rem;color:var(--text-tertiary);margin-bottom:0.75rem">
      <span><span style="color:var(--cyan)">&#9632;</span> Fees</span>
      <span><span style="color:var(--amber)">&#9632;</span> Slippage</span>
      <span><span style="color:var(--red)">&#9632;</span> Drift</span>
    </div>`;
  }

  // By outcome / by side
  const byOutcome = agg.by_outcome || {};
  const bySide = agg.by_side || {};
  if (Object.keys(byOutcome).length || Object.keys(bySide).length) {
    h += '<div style="display:flex;gap:1.5rem;font-size:0.8rem;margin-bottom:0.75rem">';
    if (Object.keys(byOutcome).length) {
      h += '<div><span style="color:var(--text-muted)">By outcome:</span> ';
      h += Object.entries(byOutcome).map(([k, v]) => `<span style="color:${k === 'win' ? 'var(--green)' : k === 'loss' ? 'var(--red)' : 'var(--text-secondary)'}">${k}: ${fmtDollar(v)}</span>`).join(' | ');
      h += '</div>';
    }
    if (Object.keys(bySide).length) {
      h += '<div><span style="color:var(--text-muted)">By side:</span> ';
      h += Object.entries(bySide).map(([k, v]) => `<span>${k}: ${fmtDollar(v)}</span>`).join(' | ');
      h += '</div>';
    }
    h += '</div>';
  }

  if (bds.length > 0) {
    h += `<table class="iv-res-table"><thead><tr><th>Order</th><th>Fee</th><th>Slippage bps</th><th>Drift $</th><th>Total $</th></tr></thead><tbody>`;
    for (const b of bds) {
      h += `<tr>
        <td style="font-size:0.7rem;color:var(--text-muted)">${(b.order_id || '').slice(0, 12)}</td>
        <td>${fmtDollar(b.fee_amount)}</td>
        <td>${b.slippage_bps?.toFixed(1) ?? '--'}</td>
        <td>${fmtDollar(b.drift_cost, true)}</td>
        <td style="font-weight:600">${fmtDollar(b.total_cost)}</td>
      </tr>`;
    }
    h += '</tbody></table>';
  }
  h += '</div>';
  return h;
}

function renderBlockedSection(d) {
  const agg = d.blocked_aggregate || {};
  const blocked = d.blocked_orders || [];

  let h = `<div class="panel panel-full">
    <div class="panel-header">D: Blocked Orders</div>
    <div class="metrics-row" style="margin-bottom:0.75rem">
      <div class="metric"><div class="metric-label">Total Blocked</div>
        <div class="metric-value v-red">${agg.total_blocked || 0}</div></div>
      <div class="metric"><div class="metric-label">TTL Rescuable</div>
        <div class="metric-value v-green">${agg.rescuable_ttl || 0}</div></div>
      <div class="metric"><div class="metric-label">Reprice Rescuable</div>
        <div class="metric-value v-green">${agg.rescuable_reprice || 0}</div></div>
    </div>`;

  // Category donut (simplified as horizontal bar)
  const cats = agg.by_category || {};
  const catEntries = Object.entries(cats).sort((a, b) => b[1] - a[1]);
  const totalBlocked = agg.total_blocked || 1;
  if (catEntries.length > 0) {
    const catColors = {
      kill_switch: 'var(--red)', timeout: 'var(--amber)', no_book: 'var(--cyan)',
      max_size: 'var(--blue)', low_balance: 'var(--purple)', no_token_balance: 'var(--text-muted)',
      no_token_id: 'var(--text-tertiary)', error: 'var(--red)', dry_run: 'var(--text-muted)', other: 'var(--text-tertiary)'
    };
    h += '<div style="display:flex;height:24px;border-radius:4px;overflow:hidden;margin-bottom:0.5rem">';
    for (const [cat, cnt] of catEntries) {
      const pct = cnt / totalBlocked * 100;
      h += `<div style="width:${pct}%;background:${catColors[cat] || 'var(--text-muted)'}" title="${cat}: ${cnt}"></div>`;
    }
    h += '</div>';
    h += '<div style="display:flex;gap:0.75rem;flex-wrap:wrap;font-size:0.7rem;color:var(--text-tertiary);margin-bottom:0.75rem">';
    for (const [cat, cnt] of catEntries) {
      h += `<span><span style="color:${catColors[cat] || 'var(--text-muted)'}">&#9632;</span> ${cat} (${cnt})</span>`;
    }
    h += '</div>';
  }

  if (blocked.length > 0) {
    h += `<table class="iv-res-table"><thead><tr><th>Candle</th><th>Action</th><th>Category</th><th>Reason</th><th>TTL?</th><th>Reprice?</th></tr></thead><tbody>`;
    for (const b of blocked) {
      h += `<tr>
        <td>${b.candle_id}</td>
        <td>${b.action}</td>
        <td style="font-weight:600">${b.category}</td>
        <td style="font-size:0.7rem;color:var(--text-muted);max-width:200px;overflow:hidden;text-overflow:ellipsis">${escH(b.risk_reason)}</td>
        <td style="color:${b.ttl_rescuable ? 'var(--green)' : 'var(--text-muted)'}">${b.ttl_rescuable ? 'Y' : '.'}</td>
        <td style="color:${b.reprice_rescuable ? 'var(--green)' : 'var(--text-muted)'}">${b.reprice_rescuable ? 'Y' : '.'}</td>
      </tr>`;
    }
    h += '</tbody></table>';
  }
  h += '</div>';
  return h;
}

function renderRoundtripsSection(d) {
  const trips = d.round_trips || [];

  let h = `<div class="panel panel-full">
    <div class="panel-header">E: Round-Trips</div>`;

  if (trips.length === 0) {
    h += '<div style="color:var(--text-muted);font-size:0.8rem;padding:1rem;text-align:center">No round-trips found</div>';
  } else {
    const totalPnl = trips.reduce((s, t) => s + (t.realized_pnl || 0), 0);
    const avgEff = trips.reduce((s, t) => s + (t.exit_efficiency || 0), 0) / trips.length;

    h += `<div class="metrics-row" style="margin-bottom:0.75rem">
      <div class="metric"><div class="metric-label">Round-Trips</div>
        <div class="metric-value">${trips.length}</div></div>
      <div class="metric"><div class="metric-label">Total PnL</div>
        <div class="metric-value ${totalPnl >= 0 ? 'v-green' : 'v-red'}">${fmtDollar(totalPnl, true)}</div></div>
      <div class="metric"><div class="metric-label">Avg Exit Eff.</div>
        <div class="metric-value v-cyan">${(avgEff * 100).toFixed(0)}%</div></div>
    </div>`;

    h += `<div style="overflow-x:auto"><table class="iv-res-table">
      <thead><tr><th>Side</th><th>Entry C#</th><th>Exit C#</th><th>Entry $</th><th>Exit $</th><th>Size</th><th>Hold (s)</th><th>PnL $</th><th>MFE</th><th>MAE</th><th>Eff %</th></tr></thead><tbody>`;
    for (const t of trips) {
      const pc = t.realized_pnl >= 0 ? 'var(--green)' : 'var(--red)';
      h += `<tr>
        <td>${t.side}</td>
        <td>${t.entry_candle_id}</td>
        <td>${t.exit_candle_id}</td>
        <td>${t.entry_price?.toFixed(4) ?? '--'}</td>
        <td>${t.exit_price?.toFixed(4) ?? '--'}</td>
        <td>${t.size?.toFixed(1) ?? '--'}</td>
        <td>${t.hold_duration_s?.toFixed(0) ?? '--'}</td>
        <td style="color:${pc};font-weight:600">${fmtDollar(t.realized_pnl, true)}</td>
        <td>${t.mfe?.toFixed(4) ?? '--'}</td>
        <td>${t.mae?.toFixed(4) ?? '--'}</td>
        <td>${t.exit_efficiency != null ? (t.exit_efficiency * 100).toFixed(0) + '%' : '--'}</td>
      </tr>`;
    }
    h += '</tbody></table></div>';
  }
  h += '</div>';
  return h;
}

function renderContextSection(d) {
  const contexts = d.decision_contexts || [];

  let h = `<div class="panel panel-full">
    <div class="panel-header">F: Decision Context</div>`;

  if (contexts.length === 0) {
    h += '<div style="color:var(--text-muted);font-size:0.8rem;padding:1rem;text-align:center">No decision contexts</div>';
  } else {
    const wins = contexts.filter(c => c.outcome === 'win').length;
    const losses = contexts.filter(c => c.outcome === 'loss').length;

    h += `<div style="color:var(--text-secondary);font-size:0.8rem;margin-bottom:0.75rem">
      ${contexts.length} decisions | <span style="color:var(--green)">${wins}W</span> / <span style="color:var(--red)">${losses}L</span>
    </div>`;

    // Confidence vs outcome heatmap (simplified)
    const confBins = [
      { label: '0.9+', min: 0.9, max: 1.1 },
      { label: '0.8-0.9', min: 0.8, max: 0.9 },
      { label: '0.7-0.8', min: 0.7, max: 0.8 },
      { label: '0.6-0.7', min: 0.6, max: 0.7 },
      { label: '<0.6', min: 0, max: 0.6 },
    ];
    h += '<div style="margin-bottom:0.75rem"><div style="font-size:0.7rem;color:var(--text-muted);margin-bottom:0.3rem;text-transform:uppercase;letter-spacing:0.05em">Confidence vs Outcome</div>';
    h += '<div style="display:grid;grid-template-columns:80px 1fr 1fr;gap:2px;font-size:0.75rem">';
    h += '<div style="color:var(--text-muted)"></div><div style="color:var(--green);text-align:center;font-weight:600">Win</div><div style="color:var(--red);text-align:center;font-weight:600">Loss</div>';
    for (const bin of confBins) {
      const inBin = contexts.filter(c => c.confidence >= bin.min && c.confidence < bin.max);
      const w = inBin.filter(c => c.outcome === 'win').length;
      const l = inBin.filter(c => c.outcome === 'loss').length;
      const wInt = Math.min(w * 40, 255);
      const lInt = Math.min(l * 40, 255);
      h += `<div style="color:var(--text-secondary);padding:0.2rem 0.4rem">${bin.label}</div>`;
      h += `<div style="background:rgba(34,197,94,${w ? 0.1 + w * 0.15 : 0.03});text-align:center;padding:0.2rem;border-radius:3px">${w || '.'}</div>`;
      h += `<div style="background:rgba(239,68,68,${l ? 0.1 + l * 0.15 : 0.03});text-align:center;padding:0.2rem;border-radius:3px">${l || '.'}</div>`;
    }
    h += '</div></div>';

    // Table
    h += `<div style="overflow-x:auto"><table class="iv-res-table">
      <thead><tr><th>Candle</th><th>Action</th><th>Conf</th><th>R/R</th><th>ML</th><th>Outcome</th><th>Key Indicators</th></tr></thead><tbody>`;
    for (const c of contexts) {
      const oc = c.outcome === 'win' ? 'var(--green)' : c.outcome === 'loss' ? 'var(--red)' : 'var(--text-muted)';
      const ac = c.action === 'BUY' ? 'var(--green)' : 'var(--red)';
      // Top 3 indicators
      const inds = Object.entries(c.indicators || {}).sort((a, b) => Math.abs(b[1]) - Math.abs(a[1])).slice(0, 3);
      const indStr = inds.length > 0 ? inds.map(([k, v]) => `${k}=${v.toFixed(2)}`).join(', ') : '--';
      h += `<tr>
        <td>${c.candle_id}</td>
        <td style="color:${ac};font-weight:600">${c.action}</td>
        <td>${c.confidence?.toFixed(2) ?? '--'}</td>
        <td>${c.rr_ratio?.toFixed(2) ?? '--'}</td>
        <td>${c.ml_score != null ? c.ml_score.toFixed(3) : '--'}</td>
        <td style="color:${oc};font-weight:600">${c.outcome || '--'}</td>
        <td style="font-size:0.7rem;color:var(--text-muted)">${escH(indStr)}</td>
      </tr>`;
    }
    h += '</tbody></table></div>';
  }
  h += '</div>';
  return h;
}

// ── Helpers ──

function fmtMs(v) {
  if (v == null) return '--';
  return v.toFixed(0) + 'ms';
}

function fmtDollar(v, signed) {
  if (v == null) return '--';
  const n = Number(v);
  if (signed) {
    return (n < 0 ? '-$' : '$') + Math.abs(n).toFixed(4);
  }
  return '$' + n.toFixed(4);
}

function escH(s) {
  if (!s) return '';
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}
