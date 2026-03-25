export type Theme = 'linear-dark' | 'linear-light' | 'claude-dark' | 'claude-light'
export type PipelineStatus = 'idle' | 'running' | 'complete' | 'error' | 'stopping'
export type PhaseState = 'pending' | 'active' | 'done' | 'error'

export interface Phase {
  id: string
  label: string
  state: PhaseState
  count: number | null
}

export interface LogEntry {
  ts: string
  type: string
  msg: string
}

export interface Usage {
  total_tokens: number
  total_calls: number
  haiku_tokens: number
  haiku_calls: number
  sonnet_tokens: number
  sonnet_calls: number
  opus_tokens: number
  opus_calls: number
}

export interface Run {
  run_id: string
  iso?: string
  module?: string
  cost_usd?: number
  has_spec: boolean
}

export interface Config {
  iso?: string
  module?: string
  base_url?: string
  max_budget?: number
  max_screens?: number
}

export interface SSEUsagePayload {
  total_tokens?: number
  total_calls?: number
  haiku_tokens?: number
  haiku_calls?: number
  sonnet_tokens?: number
  sonnet_calls?: number
  opus_tokens?: number
  opus_calls?: number
}

export interface SSEEventData {
  type?: string
  phase?: string
  message?: string
  url?: string
  frame?: string
  count?: number
  usage?: SSEUsagePayload
}
