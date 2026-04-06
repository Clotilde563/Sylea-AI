// Couleurs des agents Sylea -- source unique de verite

export const AGENT_COLORS = {
  agent1: {
    primary: '#d4a017',
    secondary: '#f59e0b',
    light: '#fbbf24',
    label: 'Compagnon',
  },
  agent2: {
    primary: '#ef4444',
    secondary: '#f87171',
    light: '#fca5a5',
    label: 'Assistant',
  },
  agent3: {
    primary: '#2563eb',
    secondary: '#3b82f6',
    light: '#60a5fa',
    label: 'OpenClaw',
  },
  agent4: {
    primary: '#10b981',
    secondary: '#34d399',
    light: '#6ee7b7',
    label: 'Agent 4',
  },
  coaching: {
    primary: '#7c3aed',
    secondary: '#8b5cf6',
    light: '#a78bfa',
    label: 'Coaching',
  },
} as const

export type AgentId = keyof typeof AGENT_COLORS
