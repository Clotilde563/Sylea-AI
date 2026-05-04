/**
 * Hook drag & drop fichiers depuis l'OS (Sprint 1 — feature 1.6)
 *
 * Ecoute l'event Tauri "tauri://drag-drop" et lit le contenu des fichiers
 * via la commande Rust `read_file_binary` puis les uploade a l'API Sylea
 * pour analyse Agent 3.
 */
import { useEffect, useState } from 'react'
import { invoke } from '@tauri-apps/api/core'
import { listen } from '@tauri-apps/api/event'

export interface DroppedFile {
  path: string
  name: string
  size: number
  type: string
}

interface DropPayload {
  paths: string[]
  position: { x: number; y: number }
}

export function useDragDrop(onDrop: (files: DroppedFile[]) => void) {
  const [hovering, setHovering] = useState(false)

  useEffect(() => {
    let unListenDrop: (() => void) | undefined
    let unListenHover: (() => void) | undefined
    let unListenLeave: (() => void) | undefined

    const setup = async () => {
      try {
        unListenHover = await listen<DropPayload>('tauri://drag-enter', () => {
          setHovering(true)
        })
        unListenLeave = await listen('tauri://drag-leave', () => {
          setHovering(false)
        })
        unListenDrop = await listen<DropPayload>('tauri://drag-drop', async (event) => {
          setHovering(false)
          const paths = event.payload?.paths || []
          const files: DroppedFile[] = []
          for (const p of paths) {
            try {
              const info = await invoke<string>('get_file_info', { path: p })
              const meta = JSON.parse(info)
              files.push({
                path: p,
                name: p.split(/[\\/]/).pop() || p,
                size: meta.size || 0,
                type: meta.is_dir ? 'directory' : 'file',
              })
            } catch {
              files.push({
                path: p,
                name: p.split(/[\\/]/).pop() || p,
                size: 0,
                type: 'unknown',
              })
            }
          }
          if (files.length > 0) onDrop(files)
        })
      } catch {
        // Tauri unavailable (web mode)
      }
    }
    setup()
    return () => {
      try { unListenDrop?.() } catch {}
      try { unListenHover?.() } catch {}
      try { unListenLeave?.() } catch {}
    }
  }, [onDrop])

  return { hovering }
}
