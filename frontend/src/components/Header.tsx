import { useState, useRef, useEffect, useCallback } from 'react'
import type { Theme, PipelineStatus } from '../types'

const THEMES: { id: Theme; name: string; mode: string; swatches: [string, string, string]; border: string }[] = [
  { id: 'linear-dark',  name: 'Linear', mode: 'Dark',  swatches: ['#09090b','#18181b','#6366f1'], border: '#27272a' },
  { id: 'linear-light', name: 'Linear', mode: 'Light', swatches: ['#ffffff','#f4f4f5','#6366f1'], border: '#e4e4e7' },
  { id: 'claude-dark',  name: 'Claude', mode: 'Dark',  swatches: ['#1c1917','#292524','#f59e0b'], border: '#3c3735' },
  { id: 'claude-light', name: 'Claude', mode: 'Light', swatches: ['#faf9f7','#f5f3f0','#d97706'], border: '#e7e5e4' },
]

interface Props {
  theme: Theme
  onThemeChange: (t: Theme) => void
  targetUrl: string
  urlState: '' | 'valid' | 'invalid'
  onUrlChange: (v: string) => void
  status: PipelineStatus
  previewAttached: boolean
  onTogglePreview: () => void
}

export default function Header({
  theme, onThemeChange,
  targetUrl, urlState, onUrlChange,
  status, previewAttached, onTogglePreview,
}: Props) {
  const [menuOpen, setMenuOpen] = useState(false)
  const [menuPos, setMenuPos] = useState({ top: 0, right: 0 })
  const btnRef = useRef<HTMLButtonElement>(null)
  const menuRef = useRef<HTMLDivElement>(null)

  const openMenu = useCallback(() => {
    if (menuOpen) { setMenuOpen(false); return }
    if (btnRef.current) {
      const r = btnRef.current.getBoundingClientRect()
      setMenuPos({ top: r.bottom + 6, right: window.innerWidth - r.right })
    }
    setMenuOpen(true)
  }, [menuOpen])

  // Close on outside click
  useEffect(() => {
    if (!menuOpen) return
    const handler = (e: MouseEvent) => {
      if (
        menuRef.current && !menuRef.current.contains(e.target as Node) &&
        btnRef.current  && !btnRef.current.contains(e.target as Node)
      ) setMenuOpen(false)
    }
    document.addEventListener('click', handler)
    return () => document.removeEventListener('click', handler)
  }, [menuOpen])

  // Escape key
  useEffect(() => {
    if (!menuOpen) return
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') setMenuOpen(false) }
    document.addEventListener('keydown', handler)
    return () => document.removeEventListener('keydown', handler)
  }, [menuOpen])

  return (
    <>
      <header className="hdr" role="banner">
        {/* Logo */}
        <div className="logo" aria-label="SpecForge v2">
          <div className="logo-mark" aria-hidden="true">
            <svg width="13" height="13" viewBox="0 0 16 16" fill="none">
              <path d="M8 2L14 5.5V10.5L8 14L2 10.5V5.5L8 2Z" fill="white" opacity=".9"/>
              <circle cx="8" cy="8" r="2" fill="rgba(0,0,0,.4)"/>
            </svg>
          </div>
          SpecForge
          <span style={{ color: 'var(--text-3)', fontWeight: 400 }}>v2</span>
        </div>

        <div className="logo-sep" aria-hidden="true" />

        {/* URL input */}
        <div className={`url-wrap ${urlState}`} role="search">
          <span className="url-icon" aria-hidden="true">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <circle cx="12" cy="12" r="10"/>
              <path d="M2 12h20M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/>
            </svg>
          </span>
          <input
            className="url-input"
            type="url"
            placeholder="https://target-app.com — URL to crawl"
            value={targetUrl}
            onChange={e => onUrlChange(e.target.value)}
            autoComplete="off"
            spellCheck={false}
            aria-label="Target URL to crawl"
          />
          <span className={`url-dot ${urlState === 'valid' ? 'v' : urlState === 'invalid' ? 'e' : ''}`} aria-hidden="true" />
          <button
            className={`btn-attach ${previewAttached ? 'on' : ''}`}
            onClick={onTogglePreview}
            aria-label={previewAttached ? 'Detach live preview' : 'Attach live preview'}
          >
            {previewAttached ? (
              <>
                <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
                  <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
                </svg>
                Detach
              </>
            ) : (
              <>
                <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
                  <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/>
                  <circle cx="12" cy="12" r="3"/>
                </svg>
                Preview
              </>
            )}
          </button>
        </div>

        {/* Right cluster */}
        <div className="hdr-right">
          <div className={`status-pill ${status}`} role="status" aria-live="polite">
            <span className="status-dot" aria-hidden="true" />
            <span>{status}</span>
          </div>

          <button
            ref={btnRef}
            className="icon-btn"
            onClick={openMenu}
            aria-label="Switch theme"
            aria-haspopup="true"
            aria-expanded={menuOpen}
          >
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
              <circle cx="12" cy="12" r="4"/>
              <path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41"/>
            </svg>
          </button>
        </div>
      </header>

      {/* Theme menu portal */}
      {menuOpen && (
        <div
          ref={menuRef}
          className="theme-menu"
          style={{ top: menuPos.top, right: menuPos.right }}
          role="menu"
          aria-label="Theme options"
        >
          {THEMES.map(t => (
            <div
              key={t.id}
              className={`theme-opt ${theme === t.id ? 'active' : ''}`}
              role="menuitem"
              tabIndex={0}
              onClick={() => { onThemeChange(t.id); setMenuOpen(false) }}
              onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { onThemeChange(t.id); setMenuOpen(false) } }}
            >
              <div className="swatch" aria-hidden="true">
                <div className="sw" style={{ background: t.swatches[0], border: `1px solid ${t.border}` }} />
                <div className="sw" style={{ background: t.swatches[1] }} />
                <div className="sw" style={{ background: t.swatches[2] }} />
              </div>
              <span className="theme-name">{t.name}</span>
              <span className="theme-mode">{t.mode}</span>
              <span className="theme-tick" style={{ visibility: theme === t.id ? 'visible' : 'hidden' }}>✓</span>
            </div>
          ))}
        </div>
      )}
    </>
  )
}
