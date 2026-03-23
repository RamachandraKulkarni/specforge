import type { Config } from '../types'

const ENDPOINTS = [
  { method: 'get',  path: '/api/config' },
  { method: 'post', path: '/api/pipeline/start' },
  { method: 'post', path: '/api/pipeline/stop' },
  { method: 'sse',  path: '/api/pipeline/progress' },
  { method: 'get',  path: '/api/runs' },
]

interface Props {
  config: Config | null
  configLoading: boolean
  screens: number | null
  tables: number | null
  interactions: number | null
  elapsed: string | null
  credentials: string
  onCredentialsChange: (v: string) => void
}

export default function Sidebar({
  config, configLoading, screens, tables, interactions, elapsed,
  credentials, onCredentialsChange,
}: Props) {
  return (
    <aside className="left" aria-label="Configuration">

      {/* Target config */}
      <div className="panel-section">
        <div className="section-title">Target Config</div>
        {configLoading ? (
          <>
            <div className="shimmer" style={{ height: 11, width: '80%', marginBottom: 7 }} />
            <div className="shimmer" style={{ height: 11, width: '60%', marginBottom: 7 }} />
            <div className="shimmer" style={{ height: 11, width: '72%' }} />
          </>
        ) : config ? (
          <>
            {config.iso         && <CfgRow k="ISO"         v={config.iso} />}
            {config.module      && <CfgRow k="Module"      v={config.module} />}
            {config.base_url    && <CfgRow k="Base URL"    v={config.base_url} />}
            {config.max_budget  && <CfgRow k="Budget"      v={'$' + config.max_budget} />}
            {config.max_screens && <CfgRow k="Max screens" v={String(config.max_screens)} />}
          </>
        ) : (
          <div className="offline-banner">
            Server offline — run{' '}
            <code>python -m specforge</code>
          </div>
        )}
      </div>

      {/* Credentials — AI parses any format */}
      <div className="panel-section">
        <div className="section-title">
          Credentials
          <span className="section-badge">AI-parsed</span>
        </div>
        <textarea
          className="creds-input"
          placeholder={`Type in any format — Haiku will figure it out:\n\nuser: john@example.com\npass: MyPassword123\n\nor just: john / pass123`}
          value={credentials}
          onChange={e => onCredentialsChange(e.target.value)}
          rows={5}
          aria-label="Login credentials — any format accepted"
          spellCheck={false}
          autoComplete="off"
        />
        {credentials && (
          <div className="creds-hint">
            <svg width="10" height="10" viewBox="0 0 10 10" fill="none">
              <circle cx="5" cy="5" r="4.5" stroke="var(--success)" strokeWidth="1"/>
              <path d="M3 5l1.5 1.5L7 3.5" stroke="var(--success)" strokeWidth="1" strokeLinecap="round"/>
            </svg>
            Haiku will parse before login
          </div>
        )}
      </div>

      {/* Session stats */}
      <div className="panel-section">
        <div className="section-title">Session</div>
        <StatRow k="Screens"      v={screens      !== null ? String(screens)      : '—'} />
        <StatRow k="Tables"       v={tables       !== null ? String(tables)       : '—'} />
        <StatRow k="Interactions" v={interactions !== null ? String(interactions) : '—'} />
        <StatRow k="Elapsed"      v={elapsed      ?? '—'} />
      </div>

      {/* Endpoints */}
      <div className="panel-section">
        <div className="section-title">Endpoints</div>
        {ENDPOINTS.map(ep => (
          <div className="ep-row" key={ep.path}>
            <span className={`ep-method ${ep.method}`}>{ep.method.toUpperCase()}</span>
            <span className="ep-path">{ep.path}</span>
          </div>
        ))}
      </div>

    </aside>
  )
}

function CfgRow({ k, v }: { k: string; v: string }) {
  return (
    <div className="cfg-row">
      <span className="cfg-key">{k}</span>
      <span className="cfg-val" title={v}>{v}</span>
    </div>
  )
}

function StatRow({ k, v }: { k: string; v: string }) {
  return (
    <div className="stat-row">
      <span className="stat-key">{k}</span>
      <span className="stat-val">{v}</span>
    </div>
  )
}
