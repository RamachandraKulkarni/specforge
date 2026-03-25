import { useState, useEffect, useRef, useCallback } from 'react'
import type { Theme, PipelineStatus, Phase, LogEntry, Usage, Run, Config, SSEEventData } from './types'
import Header from './components/Header'
import Sidebar from './components/Sidebar'
import MainPanel from './components/MainPanel'
import RightPanel from './components/RightPanel'

const THEMES: Theme[] = ['linear-dark', 'linear-light', 'claude-dark', 'claude-light']
const URL_RE = /^https?:\/\/[^\s]+$/i
const LOG_MAX = 20

const INITIAL_PHASES: Phase[] = [
  { id: 'navigation',     label: 'Navigation',           state: 'pending', count: null },
  { id: 'classification', label: 'Classification',        state: 'pending', count: null },
  { id: 'table_analysis', label: 'Table Analysis',        state: 'pending', count: null },
  { id: 'interaction',    label: 'Interaction Analysis',  state: 'pending', count: null },
  { id: 'assembly',       label: 'Spec Assembly',         state: 'pending', count: null },
]

const INITIAL_USAGE: Usage = {
  total_tokens: 0, total_calls: 0,
  haiku_tokens: 0, haiku_calls: 0,
  sonnet_tokens: 0, sonnet_calls: 0,
  opus_tokens: 0, opus_calls: 0,
}

function ts() { return new Date().toTimeString().slice(0, 8) }

export default function App() {
  /* ── Theme ───────────────────────────────────────────── */
  const [theme, setThemeState] = useState<Theme>(() => {
    const saved = localStorage.getItem('sf2-theme') as Theme | null
    return saved && THEMES.includes(saved) ? saved : 'linear-dark'
  })

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme)
    localStorage.setItem('sf2-theme', theme)
  }, [theme])

  const applyTheme = useCallback((t: Theme) => setThemeState(t), [])

  /* ── URL input ───────────────────────────────────────── */
  const [targetUrl, setTargetUrl] = useState('')
  const urlValid = URL_RE.test(targetUrl)
  const urlState = targetUrl === '' ? '' : urlValid ? 'valid' : 'invalid'

  const [aiProvider, setAiProvider] = useState('anthropic')

  /* ── Credentials (natural language, Haiku parses it) ─ */
  const [credentials, setCredentials] = useState('')

  /* ── Pipeline state ──────────────────────────────────── */
  const [status, setStatus] = useState<PipelineStatus>('idle')
  const [phases, setPhases] = useState<Phase[]>(INITIAL_PHASES)
  const [logs, setLogs] = useState<LogEntry[]>([{ ts: '--:--:--', type: 'idle', msg: 'Waiting for pipeline…' }])
  const [usage, setUsage] = useState<Usage>(INITIAL_USAGE)
  const [runs, setRuns] = useState<Run[]>([])
  const [config, setConfig] = useState<Config | null>(null)
  const [configLoading, setConfigLoading] = useState(true)

  /* ── Session stats ───────────────────────────────────── */
  const [screens, setScreens] = useState<number | null>(null)
  const [tables, setTables] = useState<number | null>(null)
  const [interactions, setInteractions] = useState<number | null>(null)
  const [elapsed, setElapsed] = useState<string | null>(null)
  const [liveFrame, setLiveFrame] = useState<string | null>(null)

  /* ── Timer ───────────────────────────────────────────── */
  const t0Ref = useRef<number | null>(null)
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const [phaseTimer, setPhaseTimer] = useState('')

  const startTimer = useCallback(() => {
    t0Ref.current = Date.now()
    timerRef.current = setInterval(() => {
      const s  = Math.floor((Date.now() - t0Ref.current!) / 1000)
      const mm = String(Math.floor(s / 60)).padStart(2, '0')
      const ss = String(s % 60).padStart(2, '0')
      const t  = mm + ':' + ss
      setPhaseTimer(t)
      setElapsed(t)
    }, 1000)
  }, [])

  const stopTimer = useCallback(() => {
    if (timerRef.current) { clearInterval(timerRef.current); timerRef.current = null }
  }, [])

  /* ── SSE ref ─────────────────────────────────────────── */
  const esRef = useRef<EventSource | null>(null)

  /* ── Helpers ─────────────────────────────────────────── */
  const addLog = useCallback((type: string, msg: string) => {
    setLogs(prev => {
      const next = [...prev, { ts: ts(), type, msg }]
      return next.length > LOG_MAX ? next.slice(-LOG_MAX) : next
    })
  }, [])

  const updateUsage = useCallback((u: SSEEventData['usage']) => {
    if (!u) return
    setUsage(prev => ({
      total_tokens:  u.total_tokens  ?? prev.total_tokens,
      total_calls:   u.total_calls   ?? prev.total_calls,
      haiku_tokens:  u.haiku_tokens  ?? prev.haiku_tokens,
      haiku_calls:   u.haiku_calls   ?? prev.haiku_calls,
      sonnet_tokens: u.sonnet_tokens ?? prev.sonnet_tokens,
      sonnet_calls:  u.sonnet_calls  ?? prev.sonnet_calls,
      opus_tokens:   u.opus_tokens   ?? prev.opus_tokens,
      opus_calls:    u.opus_calls    ?? prev.opus_calls,
    }))
  }, [])

  const resetSession = useCallback(() => {
    setPhases(INITIAL_PHASES.map(p => ({ ...p })))
    setLogs([])
    setScreens(null)
    setTables(null)
    setInteractions(null)
    setElapsed(null)
    setLiveFrame(null)
    setPhaseTimer('')
    setUsage(INITIAL_USAGE)
  }, [])

  /* ── SSE event handler ───────────────────────────────── */
  const handleSSEEvent = useCallback((e: MessageEvent) => {
    let d: any
    try { d = JSON.parse(e.data) } catch { return }
    const type = e.type || d.type || 'message'
    
    // Some events might pass usage as a nested object, or the whole payload for usage_update
    if (d.usage) updateUsage(d.usage)
    if (type === 'usage_update') updateUsage(d)

    switch (type) {
      case 'pipeline_start':
        setPhases(INITIAL_PHASES.map(p => ({ ...p })))
        addLog('phase_start', d.message ?? 'Pipeline started')
        break

      case 'phase_start':
        if (d.phase) {
          setPhases(prev => {
            const idx = prev.findIndex(p => p.id === d.phase)
            if (idx < 0) return prev
            return prev.map((p, i) => ({
              ...p,
              state: i < idx ? 'done' : i === idx ? 'active' : p.state,
            }))
          })
        }
        addLog('phase_start', d.message ?? d.phase ?? '')
        break

      case 'phase_complete':
        if (d.phase) {
          setPhases(prev => prev.map(p =>
            p.id === d.phase ? { ...p, state: 'done', count: d.count ?? p.count } : p
          ))
          if (d.phase === 'navigation')    setScreens(d.count ?? null)
          if (d.phase === 'table_analysis') setTables(d.count ?? null)
          if (d.phase === 'interaction')   setInteractions(d.count ?? null)
        }
        addLog('phase_complete', d.message ?? (d.phase ?? '') + ' done')
        break

      case 'screen_discovered':
        setScreens(prev => (prev ?? 0) + 1)
        addLog('screen_found', d.url ?? d.message ?? 'screen discovered')
        break

      case 'duplicate_skipped':
        addLog('duplicate_skip', d.url ?? 'duplicate skipped')
        break

      case 'pipeline_complete':
        setStatus('complete')
        setPhases(prev => prev.map(p => ({ ...p, state: 'done' })))
        stopTimer()
        addLog('complete', d.message ?? 'Pipeline complete')
        if (esRef.current) { esRef.current.close(); esRef.current = null }
        loadRuns()
        break

      case 'preview_frame':
        if (d.frame) setLiveFrame(d.frame)
        break

      case 'pipeline_error':
      case 'budget_exceeded':
        setPhases(prev => {
          const idx = prev.findIndex(p => p.state === 'active')
          if (idx < 0) return prev
          return prev.map((p, i) => i === idx ? { ...p, state: 'error' } : p)
        })
        setStatus('error')
        stopTimer()
        addLog('error', d.message ?? type)
        if (esRef.current) { esRef.current.close(); esRef.current = null }
        break

      default:
        if (d.message) addLog('message', d.message)
    }
  }, [addLog, updateUsage, stopTimer])

  /* ── Pipeline start / stop ───────────────────────────── */
  const startPipeline = useCallback(async () => {
    if (status === 'running') return
    resetSession()

    const body: Record<string, any> = {}
    if (targetUrl && urlValid) body.base_url = targetUrl
    if (credentials.trim())   body.credentials = credentials.trim()
    
    body.config_override = { ai: { provider: aiProvider } }

    try {
      const res = await fetch('/api/pipeline/start', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }))
        addLog('error', (err as { detail: string }).detail ?? 'Failed to start')
        setStatus('error')
        return
      }
    } catch (err) {
      addLog('error', 'Cannot reach server — is specforge running? ' + (err as Error).message)
      setStatus('error')
      return
    }

    setStatus('running')
    startTimer()

    const es = new EventSource('/api/pipeline/progress')
    esRef.current = es
    const evts = ['pipeline_start','phase_start','phase_complete','screen_discovered',
                  'duplicate_skipped','usage_update','pipeline_complete','pipeline_error',
                  'budget_exceeded','message','preview_frame']
    evts.forEach(ev => es.addEventListener(ev, handleSSEEvent as EventListener))

    es.onerror = () => {
      setStatus(prev => {
        if (prev === 'running') {
          stopTimer()
          addLog('error', 'SSE connection lost')
          return 'error'
        }
        return prev
      })
    }
  }, [status, targetUrl, urlValid, resetSession, startTimer, stopTimer, addLog, handleSSEEvent])

  const stopPipeline = useCallback(async () => {
    setStatus('stopping')
    try {
      await fetch('/api/pipeline/stop', { method: 'POST' })
      addLog('phase_start', 'Stop signal sent')
    } catch (e) {
      addLog('error', 'Stop failed: ' + (e as Error).message)
    }
  }, [addLog])

  /* ── Data loaders ────────────────────────────────────── */
  const loadRuns = useCallback(async () => {
    try {
      const res = await fetch('/api/runs')
      if (res.ok) setRuns(await res.json())
    } catch { /* server offline */ }
  }, [])

  const loadConfig = useCallback(async () => {
    setConfigLoading(true)
    try {
      const res = await fetch('/api/config')
      if (res.ok) setConfig(await res.json())
    } catch { /* server offline */ }
    finally { setConfigLoading(false) }
  }, [])

  const downloadSpec = useCallback(async (runId: string) => {
    try {
      const res = await fetch(`/api/runs/${encodeURIComponent(runId)}/spec`)
      if (!res.ok) return
      const blob = await res.blob()
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url; a.download = runId + '_spec.json'; a.click()
      URL.revokeObjectURL(url)
    } catch (e) { alert('Download failed: ' + (e as Error).message) }
  }, [])

  /* ── Init ────────────────────────────────────────────── */
  useEffect(() => {
    loadConfig()
    loadRuns()
  }, [loadConfig, loadRuns])

  /* ── Preview state ───────────────────────────────────── */
  const [previewAttached, setPreviewAttached] = useState(false)

  /* ── Render ──────────────────────────────────────────── */
  return (
    <div className="layout">
      <Header
        theme={theme}
        onThemeChange={applyTheme}
        targetUrl={targetUrl}
        urlState={urlState}
        onUrlChange={setTargetUrl}
        status={status}
        previewAttached={previewAttached}
        onTogglePreview={() => setPreviewAttached(v => !v)}
        aiProvider={aiProvider}
        onAiProviderChange={setAiProvider}
      />
      <Sidebar
        config={config}
        configLoading={configLoading}
        screens={screens}
        tables={tables}
        interactions={interactions}
        elapsed={elapsed}
        credentials={credentials}
        onCredentialsChange={setCredentials}
      />
      <MainPanel
        status={status}
        phases={phases}
        logs={logs}
        usage={usage}
        runs={runs}
        phaseTimer={phaseTimer}
        onRun={startPipeline}
        onStop={stopPipeline}
        onRefreshRuns={loadRuns}
        onDownloadSpec={downloadSpec}
      />
      <RightPanel
        usage={usage}
        targetUrl={targetUrl}
        previewAttached={previewAttached}
        onAttach={() => setPreviewAttached(true)}
        onDetach={() => setPreviewAttached(false)}
        liveFrame={liveFrame}
      />
    </div>
  )
}
