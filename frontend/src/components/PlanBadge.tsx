import { useState, useEffect } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client'

const COLORS: Record<string, string> = {
  free: '#6888aa',
  pro: '#1a6fd8',
  team: '#c8dff4',
}

export default function PlanBadge() {
  const [plan, setPlan] = useState<string | null>(null)

  useEffect(() => {
    api.getPlan()
      .then(d => setPlan(d.plan.name))
      .catch(() => {/* silent */})
  }, [])

  if (!plan) return null

  const color = COLORS[plan] || COLORS.free
  return (
    <Link
      to="/quotas"
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 4,
        padding: '2px 8px',
        borderRadius: 12,
        fontSize: '0.7rem',
        fontWeight: 600,
        textDecoration: 'none',
        background: `${color}22`,
        color,
        border: `1px solid ${color}55`,
        textTransform: 'uppercase',
        letterSpacing: 0.5,
      }}
      title="Mon plan"
    >
      {plan}
    </Link>
  )
}
