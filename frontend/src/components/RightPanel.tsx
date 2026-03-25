import { useRef, useState, useEffect, useCallback } from 'react'
import type { Usage } from '../types'

const URL_RE = /^https?:\/\/[^\s]+$/i

function fmtTokens(n: number): string {
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(2) + 'M'
  if (n >= 1_000)     return (n / 1_000).toFixed(1) + 'K'
  return String(n)
}

interface Props {
  usage: Usage
  targetUrl: string
  previewAttached: boolean
  onAttach: () => void
  onDetach: () => void
  liveFrame?: string | null
}

type PvStatus = 'detached' | 'loading' | 'live' | 'blocked'

export default function RightPanel({ usage, targetUrl, previewAttached, onAttach: _onAttach, onDetach, liveFrame }: Props) {
  const tokenPct = (t: number) => usage.total_tokens > 0 ? Math.min(100, (t / usage.total_tokens) * 100).toFixed(1) + '%' : '0%'
  const callPct  = (c: number) => usage.total_calls  > 0 ? Math.min(100, (c / usage.total_calls)  * 100).toFixed(1) + '%' : '0%'

  /* ── Preview logic ─────────────────────────────────── */
  const iframeRef = useRef<HTMLIFrameElement>(null)
  const timerRef  = useRef<ReturnType<typeof setTimeout> | null>(null)
  const [pvStatus, setPvStatus] = useState<PvStatus>('detached')
  const [pvDomain, setPvDomain] = useState('')

  const checkBlocked = useCallback(() => {
    const iframe = iframeRef.current
    if (!iframe) return
    try {
      const d = iframe.contentDocument || iframe.contentWindow?.document
      if (!d || d.URL === 'about:blank') {
        setPvStatus('blocked')
      } else {
        setPvStatus('live')
      }
    } catch {
      // Cross-origin means it loaded fine
      setPvStatus('live')
    }
  }, [])

  useEffect(() => {
    const iframe = iframeRef.current
    if (!iframe) return

    if (!previewAttached) {
      if (timerRef.current) clearTimeout(timerRef.current)
      iframe.src = 'about:blank'
      setPvStatus('detached')
      setPvDomain('')
      return
    }

    if (!targetUrl || !URL_RE.test(targetUrl)) {
      // Shake would be handled in Header; just detach
      onDetach()
      return
    }

    setPvStatus('loading')
    try { setPvDomain(new URL(targetUrl).hostname) } catch { setPvDomain(targetUrl) }
    iframe.src = targetUrl

    timerRef.current = setTimeout(checkBlocked, 3500)

    iframe.onload = () => {
      if (timerRef.current) clearTimeout(timerRef.current)
      checkBlocked()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [previewAttached, targetUrl])

  const refresh = () => {
    if (!targetUrl || !iframeRef.current) return
    setPvStatus('loading')
    if (timerRef.current) clearTimeout(timerRef.current)
    iframeRef.current.src = targetUrl
    timerRef.current = setTimeout(checkBlocked, 3500)
  }

  const openTab = () => {
    if (targetUrl) window.open(targetUrl, '_blank', 'noopener,noreferrer')
  }

  const pvStatusColor =
    pvStatus === 'live'    ? 'var(--success)' :
    pvStatus === 'loading' ? 'var(--warn)'    :
    pvStatus === 'blocked' ? 'var(--warn)'    :
    'var(--text-3)'

  return (
    <aside className="right" aria-label="Cost and preview">

      {/* Usage stats */}
      <div className="right-section">
        <div className="section-title">Usage</div>

        {/* Totals row */}
        <div style={{ display: 'flex', gap: 16, marginBottom: 14 }}>
          <div>
            <div className="cost-total" style={{ fontSize: 20 }}>{usage.total_calls}</div>
            <div className="cost-sub">API calls</div>
          </div>
          <div style={{ width: 1, background: 'var(--border)', flexShrink: 0 }} />
          <div>
            <div className="cost-total" style={{ fontSize: 20 }}>{fmtTokens(usage.total_tokens)}</div>
            <div className="cost-sub">tokens used</div>
          </div>
        </div>

        {/* Per-model breakdown */}
        <TierRow
          label="Haiku · decisions"
          color="var(--haiku)"
          calls={usage.haiku_calls}
          tokens={fmtTokens(usage.haiku_tokens)}
          tokenWidth={tokenPct(usage.haiku_tokens)}
          callWidth={callPct(usage.haiku_calls)}
        />
        <TierRow
          label="Sonnet · analysis"
          color="var(--sonnet)"
          calls={usage.sonnet_calls}
          tokens={fmtTokens(usage.sonnet_tokens)}
          tokenWidth={tokenPct(usage.sonnet_tokens)}
          callWidth={callPct(usage.sonnet_calls)}
        />
        <TierRow
          label="Opus · assembly"
          color="var(--opus)"
          calls={usage.opus_calls}
          tokens={fmtTokens(usage.opus_tokens)}
          tokenWidth={tokenPct(usage.opus_tokens)}
          callWidth={callPct(usage.opus_calls)}
        />
      </div>

      {/* Live preview */}
      <div className="preview-section">
        <div className="preview-head">
          <span className="preview-title">Live Preview</span>
          <span className="preview-status" style={{ color: pvStatusColor }} aria-live="polite">{pvStatus}</span>
        </div>

        {/* Empty state */}
        {!previewAttached && (
          <div className="preview-empty-state">
            <svg width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true">
              <rect x="2" y="3" width="20" height="14" rx="2"/>
              <path d="M8 21h8M12 17v4"/>
            </svg>
            <p>Paste a URL above, then click <strong>Preview</strong> to attach a live view of the target app.</p>
          </div>
        )}

        {/* Live frame */}
        {previewAttached && (
          <div style={{ display: 'flex', flexDirection: 'column', flex: 1, overflow: 'hidden', minHeight: 0 }}>
            {/* Toolbar */}
            <div className="preview-toolbar">
              <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
                style={{ flexShrink: 0, color: 'var(--accent)' }} aria-hidden="true">
                <circle cx="12" cy="12" r="10"/>
              </svg>
              <span className="preview-domain">{pvDomain || '—'}</span>
              <button className="preview-action" onClick={refresh} aria-label="Reload preview">
                <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" aria-hidden="true">
                  <path d="M1 4v6h6"/><path d="M3.51 15a9 9 0 1 0 .49-4.31"/>
                </svg>
              </button>
              <button className="preview-action" onClick={openTab} aria-label="Open in new tab">
                <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" aria-hidden="true">
                  <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/>
                  <polyline points="15 3 21 3 21 9"/>
                  <line x1="10" y1="14" x2="21" y2="3"/>
                </svg>
              </button>
              <button className="preview-action" onClick={onDetach} aria-label="Detach preview">
                <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" aria-hidden="true">
                  <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
                </svg>
              </button>
            </div>

            {/* Frame area */}
            <div className="preview-frame-wrap">
              {liveFrame ? (
                <img src={liveFrame} alt="Live Preview" style={{ width: '100%', height: '100%', objectFit: 'contain', background: 'var(--bg)' }} />
              ) : (
                <>
                  {pvStatus === 'blocked' && (
                    <div className="preview-blocked">
                      <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"
                        style={{ opacity: .25, color: 'var(--text-3)' }} aria-hidden="true">
                        <rect x="2" y="3" width="20" height="14" rx="2"/>
                        <path d="M8 21h8M12 17v4"/>
                      </svg>
                      <div>
                        <strong>Embed blocked</strong>
                        <p>This site uses <code style={{ color: 'var(--accent)', fontSize: 11 }}>X-Frame-Options</code> to prevent embedding. Open it directly instead.</p>
                      </div>
                      <button className="btn-open-tab" onClick={openTab}>
                        <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" aria-hidden="true">
                          <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/>
                          <polyline points="15 3 21 3 21 9"/>
                          <line x1="10" y1="14" x2="21" y2="3"/>
                        </svg>
                        Open in new tab
                      </button>
                    </div>
                  )}
                  <iframe
                    ref={iframeRef}
                    className="preview-iframe"
                    sandbox="allow-same-origin allow-scripts allow-forms allow-popups allow-popups-to-escape-sandbox"
                    referrerPolicy="no-referrer"
                    title="Live preview of target application"
                    style={{ display: pvStatus === 'blocked' ? 'none' : 'block' }}
                  />
                </>
              )}
            </div>
          </div>
        )}
      </div>

    </aside>
  )
}

function TierRow({ label, color, calls, tokens, tokenWidth, callWidth }: {
  label: string; color: string
  calls: number; tokens: string
  tokenWidth: string; callWidth: string
}) {
  return (
    <div className="tier-row">
      <div className="tier-header">
        <span className="tier-label">
          <span className="tier-dot" style={{ background: color }} />
          {label}
        </span>
        <span style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <span style={{ fontSize: 10.5, color: 'var(--text-3)', fontFamily: 'var(--mono)' }}>{calls} calls</span>
          <span className="tier-amount">{tokens}</span>
        </span>
      </div>
      {/* Token bar */}
      <div className="tier-track">
        <div className="tier-fill" style={{ width: tokenWidth, background: color }} />
      </div>
      {/* Call bar (lighter) */}
      <div className="tier-track" style={{ marginTop: 2 }}>
        <div className="tier-fill" style={{ width: callWidth, background: color, opacity: 0.4 }} />
      </div>
    </div>
  )
}
