/**
 * Agent3PlanMode — UI pour Plan Mode, Permissions et Cost Tracker d'Agent 3.
 *
 * Inspire ethiquement de l'experience Claude Code :
 *  - PlanPreview : affiche les etapes d'un plan genere, permet review / approve / reject
 *  - PermissionPrompt : modale bloquante quand l'agent demande autorisation
 *  - CostBadge : indicateur tokens/USD de la session en cours
 *  - PermissionModeSwitcher : bouton segmente pour changer de mode
 */

import { useEffect, useState } from 'react'
import { api } from '../api/client'

// ── Types ────────────────────────────────────────────────────────────────────

// Seuls 'default' et 'bypass' sont utilises. 'plan' et 'auto_safe' ont ete retires.
export type PermissionMode = 'default' | 'bypass'

export interface PlanStep {
  id: number
  description: string
  action_hint: string
  risk: 'safe' | 'caution' | 'destructive'
  estimated_seconds: number
  requires_user: boolean
  status: 'pending' | 'running' | 'done' | 'skipped' | 'failed'
  depends_on: number[]
  notes?: string
}

export interface ExecutionPlan {
  id: string
  task: string
  goal: string
  url?: string
  has_code: boolean
  code_length: number
  steps: PlanStep[]
  status: 'draft' | 'approved' | 'executing' | 'completed' | 'failed' | 'aborted'
  estimated_total_seconds: number
  num_steps: number
  num_destructive: number
}

export interface PermissionRequest {
  prompt: string
  action: string
  params: Record<string, any>
  risk: 'safe' | 'caution' | 'destructive'
}

// ── Constantes de style ──────────────────────────────────────────────────────

const RISK_COLORS: Record<string, { bg: string; border: string; text: string; label: string }> = {
  safe:        { bg: '#dcfce7', border: '#16a34a', text: '#14532d', label: 'SUR' },
  caution:     { bg: '#fef3c7', border: '#ca8a04', text: '#713f12', label: 'PRUDENCE' },
  destructive: { bg: '#fee2e2', border: '#dc2626', text: '#7f1d1d', label: 'DESTRUCTIF' },
}

const ACTION_ICONS: Record<string, string> = {
  goto: '->',
  click: '*',
  type: 'T',
  select_all_and_type: 'T+',
  press: 'K',
  scroll: 'v',
  wait: 't',
  verify: '?',
  compile: '>>',
  need_user: '!',
}

// ── PlanPreview ──────────────────────────────────────────────────────────────

interface PlanPreviewProps {
  plan: ExecutionPlan
  onApprove: (planId: string) => void
  onReject: (planId: string) => void
  onEditStep?: (planId: string, stepId: number, changes: { description?: string; risk?: string }) => void
  onStartExecution: (planId: string) => void
}

export function PlanPreview({ plan, onApprove, onReject, onEditStep, onStartExecution }: PlanPreviewProps) {
  const [editingStep, setEditingStep] = useState<number | null>(null)
  const [editDraft, setEditDraft] = useState<string>('')
  const [localPlan, setLocalPlan] = useState<ExecutionPlan>(plan)

  useEffect(() => setLocalPlan(plan), [plan])

  const totalMin = Math.max(1, Math.round(plan.estimated_total_seconds / 60))
  const hasDestructive = plan.num_destructive > 0
  const isApproved = localPlan.status === 'approved' || localPlan.status === 'executing'

  const handleSaveEdit = async (stepId: number) => {
    if (onEditStep && editDraft.trim()) {
      await onEditStep(plan.id, stepId, { description: editDraft.trim() })
      const updated = {
        ...localPlan,
        steps: localPlan.steps.map(s => s.id === stepId ? { ...s, description: editDraft.trim() } : s),
      }
      setLocalPlan(updated)
    }
    setEditingStep(null)
  }

  return (
    <div style={{
      background: 'white', borderRadius: 12, padding: 20, boxShadow: '0 4px 14px rgba(0,0,0,0.08)',
      maxWidth: 680, margin: '12px 0',
    }}>
      {/* Header */}
      <div style={{ borderBottom: '1px solid #e5e7eb', paddingBottom: 12, marginBottom: 12 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 12 }}>
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 12, color: '#6b7280', fontWeight: 600, letterSpacing: 0.5 }}>
              PLAN D'EXECUTION (Plan Mode)
            </div>
            <div style={{ fontSize: 17, fontWeight: 600, color: '#111827', marginTop: 4 }}>
              {plan.goal}
            </div>
          </div>
          <div style={{
            padding: '4px 10px', borderRadius: 999, fontSize: 11, fontWeight: 700,
            background: isApproved ? '#dcfce7' : '#e5e7eb',
            color: isApproved ? '#14532d' : '#4b5563',
          }}>
            {localPlan.status.toUpperCase()}
          </div>
        </div>

        <div style={{ display: 'flex', gap: 16, marginTop: 10, fontSize: 12, color: '#4b5563', flexWrap: 'wrap' }}>
          <span><b>{plan.num_steps}</b> etapes</span>
          <span>~<b>{totalMin} min</b> estime</span>
          {hasDestructive && (
            <span style={{ color: '#dc2626', fontWeight: 600 }}>
              {plan.num_destructive} action{plan.num_destructive > 1 ? 's' : ''} destructive{plan.num_destructive > 1 ? 's' : ''}
            </span>
          )}
          {plan.has_code && <span>code: {plan.code_length} chars</span>}
        </div>
      </div>

      {/* Steps */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginBottom: 16 }}>
        {localPlan.steps.map((step) => {
          const color = RISK_COLORS[step.risk] || RISK_COLORS.safe
          const icon = ACTION_ICONS[step.action_hint] || '-'
          const isEditing = editingStep === step.id

          return (
            <div key={step.id} style={{
              display: 'flex', gap: 10, alignItems: 'flex-start',
              padding: 10, borderRadius: 8,
              background: color.bg, borderLeft: `4px solid ${color.border}`,
            }}>
              <div style={{
                flexShrink: 0, width: 26, height: 26, borderRadius: 6,
                background: color.border, color: 'white',
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                fontSize: 11, fontWeight: 700, fontFamily: 'monospace',
              }}>
                {step.id}
              </div>

              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                  <span style={{ fontSize: 14, color: '#6b7280', fontFamily: 'monospace' }}>{icon}</span>
                  {isEditing ? (
                    <input
                      autoFocus
                      value={editDraft}
                      onChange={(e) => setEditDraft(e.target.value)}
                      onBlur={() => handleSaveEdit(step.id)}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') handleSaveEdit(step.id)
                        if (e.key === 'Escape') setEditingStep(null)
                      }}
                      style={{
                        flex: 1, padding: '4px 8px', borderRadius: 4,
                        border: `1px solid ${color.border}`, fontSize: 14,
                      }}
                    />
                  ) : (
                    <span style={{ fontSize: 14, color: color.text, fontWeight: 500 }}>
                      {step.description}
                    </span>
                  )}
                </div>
                <div style={{ display: 'flex', gap: 8, marginTop: 4, fontSize: 11, color: color.text, opacity: 0.8 }}>
                  <span style={{ fontWeight: 700 }}>{color.label}</span>
                  <span>{step.action_hint}</span>
                  <span>~{step.estimated_seconds}s</span>
                  {step.requires_user && <span style={{ fontWeight: 700 }}>user</span>}
                </div>
                {step.notes && (
                  <div style={{ fontSize: 11, color: color.text, opacity: 0.7, marginTop: 4, fontStyle: 'italic' }}>
                    {step.notes}
                  </div>
                )}
              </div>

              {!isApproved && onEditStep && !isEditing && (
                <button
                  onClick={() => { setEditingStep(step.id); setEditDraft(step.description) }}
                  style={{
                    padding: '2px 8px', borderRadius: 4, border: 'none',
                    background: 'rgba(255,255,255,0.6)', cursor: 'pointer', fontSize: 11,
                  }}
                >
                  edit
                </button>
              )}
            </div>
          )
        })}
      </div>

      {/* Actions */}
      {!isApproved ? (
        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
          <button
            onClick={() => onReject(plan.id)}
            style={{
              padding: '8px 16px', borderRadius: 8, border: '1px solid #d1d5db',
              background: 'white', color: '#4b5563', cursor: 'pointer', fontSize: 14, fontWeight: 600,
            }}
          >
            Rejeter
          </button>
          <button
            onClick={async () => {
              await onApprove(plan.id)
              onStartExecution(plan.id)
            }}
            style={{
              padding: '8px 16px', borderRadius: 8, border: 'none',
              background: hasDestructive ? '#dc2626' : '#059669', color: 'white',
              cursor: 'pointer', fontSize: 14, fontWeight: 600,
            }}
          >
            {hasDestructive ? 'Approuver et lancer (risque)' : 'Approuver et lancer'}
          </button>
        </div>
      ) : (
        <div style={{ textAlign: 'center', fontSize: 13, color: '#059669', fontWeight: 600 }}>
          Plan approuve - execution en cours
        </div>
      )}
    </div>
  )
}

// ── PermissionPrompt ─────────────────────────────────────────────────────────

interface PermissionPromptProps {
  request: PermissionRequest | null
  onAllow: () => void
  onDeny: () => void
}

export function PermissionPrompt({ request, onAllow, onDeny }: PermissionPromptProps) {
  if (!request) return null
  const color = RISK_COLORS[request.risk] || RISK_COLORS.safe

  return (
    <div style={{
      position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.5)',
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      zIndex: 9999, backdropFilter: 'blur(2px)',
    }}>
      <div style={{
        background: 'white', borderRadius: 12, padding: 24, maxWidth: 480,
        boxShadow: '0 10px 40px rgba(0,0,0,0.2)',
        borderTop: `6px solid ${color.border}`,
      }}>
        <div style={{ fontSize: 12, color: color.text, fontWeight: 700, letterSpacing: 1 }}>
          PERMISSION REQUISE - {color.label}
        </div>
        <div style={{ fontSize: 16, color: '#111827', marginTop: 8, lineHeight: 1.5 }}>
          {request.prompt}
        </div>
        <div style={{
          marginTop: 12, padding: 10, borderRadius: 6,
          background: '#f3f4f6', fontSize: 12, fontFamily: 'monospace', color: '#4b5563',
        }}>
          Action: <b>{request.action}</b>{Object.keys(request.params || {}).length ? (
            <div style={{ marginTop: 4 }}>
              {Object.entries(request.params)
                .filter(([k]) => !['x', 'y'].includes(k) || true)
                .slice(0, 4)
                .map(([k, v]) => (
                  <div key={k}>{k}: {String(v).slice(0, 80)}</div>
                ))}
            </div>
          ) : null}
        </div>
        <div style={{ display: 'flex', gap: 8, marginTop: 18, justifyContent: 'flex-end' }}>
          <button
            onClick={onDeny}
            style={{
              padding: '8px 16px', borderRadius: 8, border: '1px solid #d1d5db',
              background: 'white', color: '#4b5563', cursor: 'pointer', fontWeight: 600,
            }}
          >
            Refuser
          </button>
          <button
            onClick={onAllow}
            style={{
              padding: '8px 16px', borderRadius: 8, border: 'none',
              background: color.border, color: 'white', cursor: 'pointer', fontWeight: 600,
            }}
          >
            Autoriser
          </button>
        </div>
      </div>
    </div>
  )
}

// ── CostBadge ────────────────────────────────────────────────────────────────

interface CostBadgeProps {
  usd: number
  calls: number
  inputTokens?: number
  outputTokens?: number
  warning?: boolean
  exhausted?: boolean
  onReset?: () => void
}

export function CostBadge({ usd, calls, inputTokens, outputTokens, warning, exhausted, onReset }: CostBadgeProps) {
  const bg = exhausted ? '#fee2e2' : warning ? '#fef3c7' : '#f3f4f6'
  const color = exhausted ? '#7f1d1d' : warning ? '#713f12' : '#374151'

  return (
    <div
      title={`Appels: ${calls} | Input: ${inputTokens ?? 0} | Output: ${outputTokens ?? 0}`}
      style={{
        display: 'inline-flex', alignItems: 'center', gap: 6,
        padding: '4px 10px', borderRadius: 999,
        background: bg, color, fontSize: 12, fontFamily: 'monospace',
        border: exhausted ? '1px solid #dc2626' : 'none',
      }}
    >
      <span style={{ fontWeight: 700 }}>$ {usd.toFixed(4)}</span>
      <span style={{ opacity: 0.7 }}>| {calls} appels</span>
      {exhausted && <span style={{ fontWeight: 700 }}>EPUISE</span>}
      {onReset && (
        <button
          onClick={onReset}
          title="Reset compteur de session"
          style={{
            background: 'transparent', border: 'none', color, cursor: 'pointer',
            fontSize: 11, padding: 0, marginLeft: 4, opacity: 0.6,
          }}
        >
          reset
        </button>
      )}
    </div>
  )
}

// ── PermissionModeSwitcher ───────────────────────────────────────────────────

interface PermissionModeSwitcherProps {
  mode: PermissionMode
  onChange: (mode: PermissionMode) => void
  disabled?: boolean
}

export function PermissionModeSwitcher({ mode, onChange, disabled }: PermissionModeSwitcherProps) {
  const modes: { v: PermissionMode; label: string; hint: string }[] = [
    { v: 'default',   label: 'Defaut', hint: 'Mode standard — demande confirmation pour les actions sensibles' },
    { v: 'bypass',    label: 'Bypass', hint: 'Execute tout sans demander (DANGER)' },
  ]

  return (
    <div style={{
      display: 'inline-flex', gap: 2, padding: 3, background: 'rgba(255,255,255,0.06)',
      borderRadius: 8, border: '1px solid rgba(255,255,255,0.08)',
    }}>
      {modes.map(m => {
        const isActive = mode === m.v
        const isBypass = m.v === 'bypass'
        return (
          <button
            key={m.v}
            disabled={disabled}
            onClick={() => onChange(m.v)}
            title={m.hint}
            style={{
              padding: '5px 14px', fontSize: 12, fontWeight: 600, letterSpacing: '0.01em',
              background: isActive
                ? isBypass ? 'rgba(220, 38, 38, 0.15)' : 'rgba(255,255,255,0.12)'
                : 'transparent',
              color: isActive
                ? isBypass ? '#f87171' : '#e5e7eb'
                : 'rgba(255,255,255,0.35)',
              border: isActive
                ? isBypass ? '1px solid rgba(220, 38, 38, 0.3)' : '1px solid rgba(255,255,255,0.15)'
                : '1px solid transparent',
              borderRadius: 6, cursor: disabled ? 'not-allowed' : 'pointer',
              transition: 'all 0.15s ease',
              opacity: disabled ? 0.4 : 1,
            }}
          >
            {isBypass && isActive ? '\u26a0 ' : ''}{m.label}
          </button>
        )
      })}
    </div>
  )
}

// ── Hook : useAgent3Policy ──────────────────────────────────────────────────

export function useAgent3Policy() {
  const [mode, setMode] = useState<PermissionMode>('default')
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api.browserAgentGetPolicy()
      .then((p: any) => { if (p?.mode) setMode(p.mode) })
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [])

  const updateMode = async (newMode: PermissionMode) => {
    setMode(newMode)
    try {
      await api.browserAgentSetPolicy({ mode: newMode })
    } catch {}
  }

  return { mode, setMode: updateMode, loading }
}
