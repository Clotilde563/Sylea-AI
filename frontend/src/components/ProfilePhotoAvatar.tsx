/**
 * Avatar de profil cliquable.
 *
 * - Affiche la photo si presente, sinon les initiales du nom
 * - Clic → ouvre modal upload (file picker + preview + valider/annuler)
 * - Bouton "Supprimer" si photo deja presente
 *
 * Utilise sur DashboardPage (en-tete) + accessible ailleurs si besoin.
 */
import React, { useRef, useState } from 'react'
import { api } from '../api/client'

interface Props {
  photoUrl?: string | null
  nom: string
  size?: number
  onUpdated?: (newUrl: string | null) => void
}

function getInitials(nom: string): string {
  if (!nom) return '?'
  const parts = nom.trim().split(/\s+/).filter(Boolean)
  if (parts.length === 0) return '?'
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase()
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase()
}

export default function ProfilePhotoAvatar({
  photoUrl,
  nom,
  size = 64,
  onUpdated,
}: Props) {
  const [showModal, setShowModal] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const initials = getInitials(nom)

  const onPick = () => fileInputRef.current?.click()

  const onFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    if (!/^image\//.test(file.type)) {
      setError('Le fichier doit être une image')
      return
    }
    if (file.size > 5 * 1024 * 1024) {
      setError('Image trop volumineuse (max 5 MB)')
      return
    }
    setError(null)
    setLoading(true)
    try {
      const r = await api.uploadProfilPhoto(file)
      onUpdated?.(r.photo_url)
      setShowModal(false)
    } catch (err: any) {
      setError(err?.message || 'Erreur upload')
    } finally {
      setLoading(false)
      if (fileInputRef.current) fileInputRef.current.value = ''
    }
  }

  const onDelete = async () => {
    if (!confirm('Supprimer ta photo de profil ?')) return
    setLoading(true)
    try {
      await api.deleteProfilPhoto()
      onUpdated?.(null)
      setShowModal(false)
    } catch (err: any) {
      setError(err?.message || 'Erreur suppression')
    } finally {
      setLoading(false)
    }
  }

  return (
    <>
      <button
        type="button"
        onClick={() => setShowModal(true)}
        title="Modifier ma photo"
        style={{
          width: size,
          height: size,
          borderRadius: '50%',
          border: '2px solid var(--accent-violet-light)',
          background: photoUrl
            ? `url(${photoUrl}) center/cover no-repeat`
            : 'linear-gradient(135deg, var(--accent-violet-light), var(--accent-gold))',
          cursor: 'pointer',
          padding: 0,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          color: '#fff',
          fontWeight: 700,
          fontSize: size * 0.36,
          letterSpacing: '0.05em',
          flexShrink: 0,
          transition: 'transform 0.2s, box-shadow 0.2s',
          boxShadow: '0 4px 12px rgba(139,92,246,0.25)',
        }}
        onMouseEnter={(e) => {
          ;(e.currentTarget as HTMLElement).style.transform = 'scale(1.05)'
          ;(e.currentTarget as HTMLElement).style.boxShadow = '0 6px 18px rgba(139,92,246,0.4)'
        }}
        onMouseLeave={(e) => {
          ;(e.currentTarget as HTMLElement).style.transform = 'scale(1)'
          ;(e.currentTarget as HTMLElement).style.boxShadow = '0 4px 12px rgba(139,92,246,0.25)'
        }}
      >
        {!photoUrl && initials}
      </button>

      {showModal && (
        <div
          style={{
            position: 'fixed',
            inset: 0,
            background: 'rgba(0,0,0,0.7)',
            backdropFilter: 'blur(8px)',
            zIndex: 5000,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            padding: '1rem',
          }}
          onClick={(e) => {
            if (e.target === e.currentTarget) setShowModal(false)
          }}
        >
          <div
            style={{
              background: 'var(--bg-surface)',
              borderRadius: 'var(--radius-lg)',
              border: '1px solid rgba(139,92,246,0.3)',
              maxWidth: 420,
              width: '100%',
              padding: '1.5rem',
            }}
          >
            <h3
              style={{
                fontSize: '1.1rem',
                fontWeight: 700,
                color: 'var(--accent-violet-light)',
                marginBottom: '1rem',
              }}
            >
              Photo de profil
            </h3>

            <div
              style={{
                display: 'flex',
                justifyContent: 'center',
                marginBottom: '1.25rem',
              }}
            >
              <div
                style={{
                  width: 140,
                  height: 140,
                  borderRadius: '50%',
                  border: '3px solid var(--accent-violet-light)',
                  background: photoUrl
                    ? `url(${photoUrl}) center/cover no-repeat`
                    : 'linear-gradient(135deg, var(--accent-violet-light), var(--accent-gold))',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  color: '#fff',
                  fontSize: 48,
                  fontWeight: 700,
                  boxShadow: '0 8px 24px rgba(139,92,246,0.4)',
                }}
              >
                {!photoUrl && initials}
              </div>
            </div>

            {error && (
              <div
                style={{
                  background: 'rgba(239,68,68,0.1)',
                  border: '1px solid rgba(239,68,68,0.4)',
                  color: '#f87171',
                  padding: '0.5rem 0.75rem',
                  borderRadius: 'var(--radius-md)',
                  fontSize: '0.8rem',
                  marginBottom: '0.75rem',
                }}
              >
                {error}
              </div>
            )}

            <p
              style={{
                fontSize: '0.78rem',
                color: 'var(--text-muted)',
                marginBottom: '1rem',
                textAlign: 'center',
              }}
            >
              Formats acceptés : JPG, PNG, WebP, GIF — max 5 MB
            </p>

            <input
              ref={fileInputRef}
              type="file"
              accept="image/jpeg,image/png,image/webp,image/gif"
              onChange={onFile}
              style={{ display: 'none' }}
            />

            <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
              <button
                type="button"
                onClick={onPick}
                disabled={loading}
                style={{
                  flex: '1 1 auto',
                  padding: '0.6rem 1rem',
                  background:
                    'linear-gradient(135deg, var(--accent-violet-light), var(--accent-gold))',
                  border: 'none',
                  borderRadius: 'var(--radius-md)',
                  color: '#fff',
                  fontWeight: 600,
                  cursor: loading ? 'wait' : 'pointer',
                  opacity: loading ? 0.6 : 1,
                }}
              >
                {loading ? '⌛ Upload…' : photoUrl ? '↻ Changer la photo' : '📷 Choisir une photo'}
              </button>

              {photoUrl && (
                <button
                  type="button"
                  onClick={onDelete}
                  disabled={loading}
                  style={{
                    padding: '0.6rem 1rem',
                    background: 'transparent',
                    border: '1px solid rgba(239,68,68,0.4)',
                    color: '#f87171',
                    borderRadius: 'var(--radius-md)',
                    cursor: loading ? 'wait' : 'pointer',
                    fontWeight: 600,
                  }}
                >
                  🗑 Supprimer
                </button>
              )}
            </div>

            <button
              type="button"
              onClick={() => setShowModal(false)}
              style={{
                marginTop: '0.75rem',
                width: '100%',
                padding: '0.5rem',
                background: 'transparent',
                border: '1px solid var(--border)',
                color: 'var(--text-muted)',
                borderRadius: 'var(--radius-md)',
                cursor: 'pointer',
                fontSize: '0.85rem',
              }}
            >
              Fermer
            </button>
          </div>
        </div>
      )}
    </>
  )
}
