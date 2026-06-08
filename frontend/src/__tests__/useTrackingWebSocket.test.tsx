// Tests du hook useTrackingWebSocket : connexion, reception event,
// reconnect avec backoff, cleanup.

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { renderHook } from '@testing-library/react'
import { useTrackingWebSocket } from '../hooks/useTrackingWebSocket'

// Mock WebSocket
class MockWebSocket {
  static instances: MockWebSocket[] = []
  url: string
  readyState = 0  // CONNECTING
  onopen: (() => void) | null = null
  onmessage: ((e: { data: string }) => void) | null = null
  onerror: ((e: Event) => void) | null = null
  onclose: ((e: { code: number; reason: string }) => void) | null = null
  send = vi.fn()
  close = vi.fn(() => {
    this.readyState = 3 // CLOSED
    this.onclose?.({ code: 1000, reason: 'normal' })
  })

  constructor(url: string) {
    this.url = url
    MockWebSocket.instances.push(this)
  }

  // Helpers pour les tests
  simulateOpen() {
    this.readyState = 1 // OPEN
    this.onopen?.()
  }

  simulateMessage(data: object | string) {
    const d = typeof data === 'string' ? data : JSON.stringify(data)
    this.onmessage?.({ data: d })
  }

  simulateClose(code = 1006, reason = 'lost') {
    this.readyState = 3 // CLOSED
    this.onclose?.({ code, reason })
  }
}

describe('useTrackingWebSocket', () => {
  const originalWebSocket = globalThis.WebSocket

  beforeEach(() => {
    // @ts-expect-error replace global
    globalThis.WebSocket = MockWebSocket
    MockWebSocket.instances = []
    vi.useFakeTimers()
    // Mock window.location pour buildWsUrl
    Object.defineProperty(window, 'location', {
      value: { protocol: 'http:', host: 'localhost:5173' },
      writable: true,
    })
  })

  afterEach(() => {
    globalThis.WebSocket = originalWebSocket
    vi.useRealTimers()
  })

  it('does not connect if token is null', () => {
    renderHook(() => useTrackingWebSocket({ token: null, onEvent: vi.fn() }))
    expect(MockWebSocket.instances).toHaveLength(0)
  })

  it('connects to /ws/agent with token', () => {
    renderHook(() => useTrackingWebSocket({ token: 'abc123', onEvent: vi.fn() }))
    expect(MockWebSocket.instances).toHaveLength(1)
    expect(MockWebSocket.instances[0].url).toBe('ws://localhost:5173/ws/agent?token=abc123')
  })

  it('uses wss:// when page is https', () => {
    Object.defineProperty(window, 'location', {
      value: { protocol: 'https:', host: 'app.sylea.ai' },
      writable: true,
    })
    renderHook(() => useTrackingWebSocket({ token: 'xyz', onEvent: vi.fn() }))
    expect(MockWebSocket.instances[0].url).toBe('wss://app.sylea.ai/ws/agent?token=xyz')
  })

  it('calls onEvent when receiving a tracking_period event', () => {
    const onEvent = vi.fn()
    renderHook(() => useTrackingWebSocket({ token: 't', onEvent }))
    const ws = MockWebSocket.instances[0]
    ws.simulateOpen()
    ws.simulateMessage({
      type: 'dilemme_tracking_period',
      tracking_id: 'abc',
      periode_idx: 0,
      question: 'Q?',
      actions: [],
      is_retry: false,
      nb_periodes: 3,
      timestamp: '2026-05-28T15:00:00Z',
    })
    expect(onEvent).toHaveBeenCalledOnce()
    expect(onEvent.mock.calls[0][0].type).toBe('dilemme_tracking_period')
  })

  it('ignores "pong" messages', () => {
    const onEvent = vi.fn()
    renderHook(() => useTrackingWebSocket({ token: 't', onEvent }))
    const ws = MockWebSocket.instances[0]
    ws.simulateOpen()
    ws.simulateMessage('pong')
    expect(onEvent).not.toHaveBeenCalled()
  })

  it('does not crash on malformed JSON', () => {
    const onEvent = vi.fn()
    renderHook(() => useTrackingWebSocket({ token: 't', onEvent }))
    const ws = MockWebSocket.instances[0]
    ws.simulateOpen()
    expect(() => ws.simulateMessage('{not json')).not.toThrow()
    expect(onEvent).not.toHaveBeenCalled()
  })

  it('reconnects on close with backoff', () => {
    renderHook(() => useTrackingWebSocket({ token: 't', onEvent: vi.fn() }))
    expect(MockWebSocket.instances).toHaveLength(1)
    MockWebSocket.instances[0].simulateClose(1006)
    // Pas de reconnect immediat — attend 1s
    expect(MockWebSocket.instances).toHaveLength(1)
    vi.advanceTimersByTime(1000)
    expect(MockWebSocket.instances).toHaveLength(2)
    // 2eme close → 2s
    MockWebSocket.instances[1].simulateClose(1006)
    vi.advanceTimersByTime(1000)
    expect(MockWebSocket.instances).toHaveLength(2) // pas encore
    vi.advanceTimersByTime(1000)
    expect(MockWebSocket.instances).toHaveLength(3)
  })

  it('does NOT reconnect on auth failure (code 4001)', () => {
    renderHook(() => useTrackingWebSocket({ token: 'bad', onEvent: vi.fn() }))
    MockWebSocket.instances[0].simulateClose(4001, 'invalid token')
    vi.advanceTimersByTime(60_000)
    expect(MockWebSocket.instances).toHaveLength(1)
  })

  it('closes connection on unmount', () => {
    const { unmount } = renderHook(() => useTrackingWebSocket({ token: 't', onEvent: vi.fn() }))
    const ws = MockWebSocket.instances[0]
    unmount()
    expect(ws.close).toHaveBeenCalled()
  })

  it('sends ping at interval', () => {
    renderHook(() => useTrackingWebSocket({ token: 't', onEvent: vi.fn() }))
    const ws = MockWebSocket.instances[0]
    ws.simulateOpen()
    expect(ws.send).not.toHaveBeenCalled()
    vi.advanceTimersByTime(25_000)
    expect(ws.send).toHaveBeenCalledWith('ping')
    vi.advanceTimersByTime(25_000)
    expect(ws.send).toHaveBeenCalledTimes(2)
  })
})
