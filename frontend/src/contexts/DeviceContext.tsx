// DeviceContext — Collecte automatique heure, geoloc, meteo pour enrichir les appels IA
import { createContext, useContext, useState, useEffect, useCallback, type ReactNode } from 'react'
import { useStore } from '../store/useStore'

// ── Types ────────────────────────────────────────────────────────────────────

export interface DeviceContextData {
  heure: number
  minute: number
  fuseau_horaire: string
  latitude: number
  longitude: number
  ville: string
  temperature: number
  meteo: string
}

interface DeviceContextState {
  ctx: DeviceContextData | null
  ready: boolean
  geoDenied: boolean
  loading: boolean
  retryGeo: () => void
  useFallbackCity: (city: string) => void
}

const DeviceCtx = createContext<DeviceContextState>({
  ctx: null,
  ready: false,
  geoDenied: false,
  loading: true,
  retryGeo: () => {},
  useFallbackCity: () => {},
})

export const useDeviceContext = () => useContext(DeviceCtx)

// ── WMO weather code → label ─────────────────────────────────────────────────

function wmoToLabel(code: number): string {
  if (code === 0) return 'Ciel degage'
  if (code <= 3) return 'Partiellement nuageux'
  if (code <= 48) return 'Brouillard'
  if (code <= 55) return 'Bruine'
  if (code <= 57) return 'Bruine verglacante'
  if (code <= 65) return 'Pluie'
  if (code <= 67) return 'Pluie verglacante'
  if (code <= 77) return 'Neige'
  if (code <= 82) return 'Averses'
  if (code <= 86) return 'Averses de neige'
  if (code <= 99) return 'Orage'
  return 'Inconnu'
}

// ── Fetch weather from Open-Meteo ────────────────────────────────────────────

async function fetchWeather(lat: number, lon: number): Promise<{ temperature: number; meteo: string }> {
  try {
    const url = `https://api.open-meteo.com/v1/forecast?latitude=${lat.toFixed(4)}&longitude=${lon.toFixed(4)}&current_weather=true`
    const resp = await fetch(url)
    if (!resp.ok) return { temperature: 0, meteo: 'Inconnu' }
    const data = await resp.json()
    const cw = data.current_weather
    return {
      temperature: Math.round(cw.temperature),
      meteo: wmoToLabel(cw.weathercode),
    }
  } catch {
    return { temperature: 0, meteo: 'Inconnu' }
  }
}

// ── Reverse geocode (Nominatim) ──────────────────────────────────────────────

async function reverseGeocode(lat: number, lon: number): Promise<string> {
  try {
    const url = `https://nominatim.openstreetmap.org/reverse?lat=${lat}&lon=${lon}&format=json&accept-language=fr`
    const resp = await fetch(url, { headers: { 'User-Agent': 'SyleaAI/1.0' } })
    if (!resp.ok) return ''
    const data = await resp.json()
    return data.address?.city || data.address?.town || data.address?.village || data.address?.municipality || ''
  } catch {
    return ''
  }
}

// ── Geocode city name → lat/lon (Open-Meteo) ────────────────────────────────

async function geocodeCity(city: string): Promise<{ lat: number; lon: number } | null> {
  try {
    const url = `https://geocoding-api.open-meteo.com/v1/search?name=${encodeURIComponent(city)}&count=1&language=fr`
    const resp = await fetch(url)
    if (!resp.ok) return null
    const data = await resp.json()
    if (!data.results?.length) return null
    return { lat: data.results[0].latitude, lon: data.results[0].longitude }
  } catch {
    return null
  }
}

// ── Provider ─────────────────────────────────────────────────────────────────

const CACHE_MS = 30 * 60 * 1000 // 30 minutes

export function DeviceContextProvider({ children }: { children: ReactNode }) {
  const [ctx, setCtx] = useState<DeviceContextData | null>(null)
  const [geoDenied, setGeoDenied] = useState(false)
  const [loading, setLoading] = useState(true)
  const profil = useStore(s => s.profil)

  const buildContext = useCallback(async (lat: number, lon: number, cityOverride?: string) => {
    const now = new Date()
    const [weather, city] = await Promise.all([
      fetchWeather(lat, lon),
      cityOverride ? Promise.resolve(cityOverride) : reverseGeocode(lat, lon),
    ])
    setCtx({
      heure: now.getHours(),
      minute: now.getMinutes(),
      fuseau_horaire: Intl.DateTimeFormat().resolvedOptions().timeZone,
      latitude: lat,
      longitude: lon,
      ville: city || 'Inconnu',
      temperature: weather.temperature,
      meteo: weather.meteo,
    })
    setLoading(false)
    setGeoDenied(false)
  }, [])

  const requestGeo = useCallback(() => {
    setLoading(true)
    if (!navigator.geolocation) {
      setGeoDenied(true)
      setLoading(false)
      return
    }
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        buildContext(pos.coords.latitude, pos.coords.longitude)
      },
      (err) => {
        if (err.code === 1) {
          // Permission denied — try fallback city from profil
          if (profil?.ville) {
            geocodeCity(profil.ville).then(coords => {
              if (coords) {
                buildContext(coords.lat, coords.lon, profil.ville)
              } else {
                setGeoDenied(true)
                setLoading(false)
              }
            })
          } else {
            setGeoDenied(true)
            setLoading(false)
          }
        } else {
          // Timeout or other error — try again later
          setGeoDenied(true)
          setLoading(false)
        }
      },
      { enableHighAccuracy: false, timeout: 10000, maximumAge: CACHE_MS }
    )
  }, [buildContext, profil?.ville])

  const useFallbackCity = useCallback((city: string) => {
    setLoading(true)
    geocodeCity(city).then(coords => {
      if (coords) {
        buildContext(coords.lat, coords.lon, city)
      } else {
        setLoading(false)
      }
    })
  }, [buildContext])

  // Initial load + refresh every 30 min
  useEffect(() => {
    requestGeo()
    const interval = setInterval(requestGeo, CACHE_MS)
    return () => clearInterval(interval)
  }, [requestGeo])

  return (
    <DeviceCtx.Provider value={{
      ctx,
      ready: ctx !== null,
      geoDenied,
      loading,
      retryGeo: requestGeo,
      useFallbackCity,
    }}>
      {children}
    </DeviceCtx.Provider>
  )
}
