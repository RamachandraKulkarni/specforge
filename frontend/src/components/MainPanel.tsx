import { useRef, useEffect } from 'react'
import type { PipelineStatus, Phase, LogEntry, Usage, Run } from '../types'

function fmtTokens(n: number): string {
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M'
  if (n >= 1_000)     return (n / 1_000).toFixed(1) + 'K'
  return String(n)
}

interface Props {
  status: PipelineStatus
  phases: Phase[]
  logs: LogEntry[]
  usage: Usage
  runs: Run[]
  phaseTimer: string
  onRun: () => void
  onStop: () => void
  onRefreshRuns: () => void
  onDownloadSpec: (runId: string) => void
}

export default function MainPanel({
  status, phases, logs, usage, runs, phaseTimer,
  onRun, onStop, onRefreshRuns, onDownloadSpec,
}: Props) {
  const running  = status === 'running'
  const stopping = status === 'stopping'

  const logEndRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    logEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [logs.length])

  return (
    <main className="main" aria-label="Pipeline control">

      {/* Control bar */}
      <div className="ctrl-bar">
        <button
          className="btn-run"
          onClick={onRun}
          disabled={running || stopping}
          aria-label="Run pipeline"
        >
          <svg width="11" height="11" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
            <path d="M5 3l14 9L5 21V3z"/>
          </svg>
          Run Pipeline
        </button>

        <button
          className="btn-stop"
          onClick={onStop}
          disabled={!running}
          aria-label="Stop pipeline"
        >
          <svg width="9" height="9" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
            <rect x="4" y="4" width="16" height="16" rx="2"/>
          </svg>
          Stop
        </button>

        <div className="ctrl-divider" aria-hidden="true" />

        <div className="ctrl-cost-wrap">
          <div className="ctrl-cost-label">API Calls</div>
          <div className="ctrl-cost" aria-live="polite">{usage.total_calls}</div>
        </div>

        <div className="ctrl-divider" aria-hidden="true" />

        <div className="ctrl-cost-wrap">
          <div className="ctrl-cost-label">Tokens</div>
          <div className="ctrl-cost" aria-live="polite">{fmtTokens(usage.total_tokens)}</div>
        </div>
      </div>

      {/* Phase timeline + log */}
      <div className="card">
        <div className="card-head">
          <span className="card-title">Pipeline Phases</span>
          <span style={{ fontSize: 11, color: 'var(--text-3)', fontFamily: 'var(--mono)' }}>{phaseTimer}</span>
        </div>
        <div className="phase-list" role="list" aria-label="Pipeline phases">
          {phases.map(p => (
            <div
              key={p.id}
              className={`phase-row ${p.state}`}
              role="listitem"
              aria-label={`${p.label}: ${p.state}`}
            >
              <div className="phase-indicator">
                <PhaseIcon state={p.state} />
              </div>
              <span className="phase-name">{p.label}</span>
              {p.count != null
                ? <span className="phase-count">{p.count}</span>
                : p.state === 'active'
                  ? <span className="phase-running-label">running</span>
                  : null}
            </div>
          ))}
        </div>
        <div className="event-log" aria-live="polite" aria-label="Pipeline event log">
          {logs.map((l, i) => (
            <div className="el-line" key={i}>
              <span className="el-ts">{l.ts}</span>
              {l.type !== 'idle' && <span className={`el-type ${l.type}`}>{l.type}</span>}
              <span className="el-msg">{l.msg}</span>
            </div>
          ))}
          <div ref={logEndRef} />
        </div>
      </div>

      {/* Run history */}
      <div className="card">
        <div className="card-head">
          <span className="card-title">Run History</span>
          <button className="card-action" onClick={onRefreshRuns} aria-label="Refresh runs">
            ↻ Refresh
          </button>
        </div>
        <div className="card-body-flush">
          {runs.length === 0 ? (
            <div className="empty">
              <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true">
                <rect x="3" y="3" width="18" height="18" rx="2"/>
                <path d="M3 9h18M9 21V9"/>
              </svg>
              <span>No runs yet — start the pipeline to generate a spec</span>
            </div>
          ) : (
            <table className="runs-tbl" aria-label="Run history">
              <thead>
                <tr>
                  <th scope="col">Run ID</th>
                  <th scope="col">ISO / Module</th>
                  <th scope="col" style={{ textAlign: 'right' }}>Cost</th>
                  <th scope="col">Spec</th>
                  <th scope="col"></th>
                </tr>
              </thead>
              <tbody>
                {runs.map(r => (
                  <tr key={r.run_id}>
                    <td className="mono">{r.run_id}</td>
                    <td>
                      <span style={{ fontFamily: 'var(--mono)', fontSize: '11.5px' }}>
                        {r.iso ?? '—'} / {r.module ?? '—'}
                      </span>
                    </td>
                    <td style={{ textAlign: 'right', fontFamily: 'var(--mono)', color: 'var(--accent)' }}>
                      {r.cost_usd != null ? '$' + Number(r.cost_usd).toFixed(4) : '—'}
                    </td>
                    <td>
                      {r.has_spec
                        ? <span className="chip chip-spec">spec</span>
                        : <span className="chip chip-none">none</span>}
                    </td>
                    <td>
                      {r.has_spec && (
                        <button
                          className="btn-dl"
                          onClick={() => onDownloadSpec(r.run_id)}
                          aria-label={`Download spec for run ${r.run_id}`}
                        >
                          ↓ JSON
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>

    </main>
  )
}

function PhaseIcon({ state }: { state: Phase['state'] }) {
  if (state === 'pending') return <span className="pi-pending" aria-hidden="true" />
  if (state === 'active') return (
    <svg className="spin" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" aria-hidden="true">
      <path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83"/>
    </svg>
  )
  if (state === 'done') return (
    <svg className="pi-done" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" aria-hidden="true">
      <polyline points="20 6 9 17 4 12"/>
    </svg>
  )
  return (
    <svg className="pi-error" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" aria-hidden="true">
      <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
    </svg>
  )
}
