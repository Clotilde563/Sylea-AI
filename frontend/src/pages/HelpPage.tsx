// Page Aide et ressources — documentation utilisateur

import { useState } from 'react'
import { Link } from 'react-router-dom'

// ── Accordion Section ────────────────────────────────────────────────────────

interface AccordionProps {
  title: string
  children: React.ReactNode
  defaultOpen?: boolean
}

function Accordion({ title, children, defaultOpen = false }: AccordionProps) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <div style={{
      background: 'var(--bg-surface)',
      border: '1px solid var(--border)',
      borderRadius: 'var(--radius-lg)',
      overflow: 'hidden',
      marginBottom: '0.5rem',
    }}>
      <button
        onClick={() => setOpen(!open)}
        style={{
          width: '100%', display: 'flex', alignItems: 'center',
          justifyContent: 'space-between',
          padding: '0.85rem 1.1rem',
          background: 'transparent', border: 'none',
          cursor: 'pointer', color: 'var(--text-primary)',
          fontSize: '0.85rem', fontWeight: 500, textAlign: 'left',
          fontFamily: 'var(--font-sans)',
        }}
      >
        <span>{title}</span>
        <svg width={14} height={14} viewBox="0 0 24 24" fill="none"
          stroke="currentColor" strokeWidth={2.5} strokeLinecap="round" strokeLinejoin="round"
          style={{ transition: 'transform 0.25s', transform: open ? 'rotate(180deg)' : 'rotate(0deg)', flexShrink: 0, color: 'var(--text-muted)' }}>
          <polyline points="6 9 12 15 18 9" />
        </svg>
      </button>
      {open && (
        <div style={{
          padding: '0 1.1rem 1rem',
          fontSize: '0.8rem', color: 'var(--text-secondary)',
          lineHeight: 1.7,
        }}>
          {children}
        </div>
      )}
    </div>
  )
}

// ── Category Section ─────────────────────────────────────────────────────────

function CategorySection({ icon, title, children }: {
  icon: string; title: string; children: React.ReactNode
}) {
  return (
    <div style={{ marginBottom: '1.5rem' }}>
      <h2 style={{
        fontSize: '1.05rem', fontWeight: 700,
        color: 'var(--text-primary)',
        marginBottom: '0.75rem',
        display: 'flex', alignItems: 'center', gap: '0.5rem',
      }}>
        <span>{icon}</span> {title}
      </h2>
      {children}
    </div>
  )
}

// ── Contact Form ─────────────────────────────────────────────────────────────

function ContactForm() {
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [message, setMessage] = useState('')
  const [sent, setSent] = useState(false)

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    // Simulate sending
    setSent(true)
    setTimeout(() => {
      setName(''); setEmail(''); setMessage(''); setSent(false)
    }, 3000)
  }

  return (
    <form onSubmit={handleSubmit} style={{
      display: 'flex', flexDirection: 'column', gap: '0.85rem',
      background: 'var(--bg-surface)',
      border: '1px solid var(--border)',
      borderRadius: 'var(--radius-lg)',
      padding: '1.25rem',
    }}>
      <div className="input-group">
        <label className="input-label" htmlFor="help-name">Nom</label>
        <input id="help-name" className="input" placeholder="Votre nom"
          value={name} onChange={e => setName(e.target.value)} required />
      </div>
      <div className="input-group">
        <label className="input-label" htmlFor="help-email">Email</label>
        <input id="help-email" className="input" type="email" placeholder="votre@email.com"
          value={email} onChange={e => setEmail(e.target.value)} required />
      </div>
      <div className="input-group">
        <label className="input-label" htmlFor="help-msg">Message</label>
        <textarea id="help-msg" className="input" rows={4}
          placeholder="Décrivez votre question ou problème..."
          value={message} onChange={e => setMessage(e.target.value)} required
          style={{ resize: 'vertical', minHeight: 80, fontFamily: 'var(--font-sans)' }} />
      </div>
      <button type="submit" className="btn btn-primary" disabled={sent}
        style={{ alignSelf: 'flex-start', padding: '0.55rem 1.5rem' }}>
        {sent ? 'Message envoyé !' : 'Envoyer'}
      </button>
    </form>
  )
}

// ── Main Page ────────────────────────────────────────────────────────────────

export default function HelpPage() {
  return (
    <div className="container" style={{ maxWidth: 780, margin: '0 auto', padding: '2rem 1.5rem 4rem' }}>
      {/* Header */}
      <div style={{ textAlign: 'center', marginBottom: '2rem' }}>
        <div style={{ fontSize: '2rem', marginBottom: '0.5rem' }}>&#x2753;</div>
        <h1 style={{
          fontSize: '1.6rem', fontWeight: 700,
          color: 'var(--text-primary)', letterSpacing: '0.02em',
          margin: '0 0 0.5rem',
        }}>
          Aide et ressources
        </h1>
        <p style={{ color: 'var(--text-muted)', fontSize: '0.82rem' }}>
          Tout ce que vous devez savoir pour utiliser Syléa.AI
        </p>
      </div>

      {/* ── Bandeau Support détaillé ───────────────────────────────────── */}
      <section style={{
        background: 'linear-gradient(135deg, rgba(139,92,246,0.10), rgba(99,102,241,0.10))',
        border: '1px solid rgba(139,92,246,0.30)',
        borderRadius: 14,
        padding: '1rem 1.25rem',
        marginBottom: '2rem',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        gap: '1rem',
        flexWrap: 'wrap',
      }}>
        <div style={{ flex: 1, minWidth: 220 }}>
          <div style={{
            fontSize: '0.92rem',
            fontWeight: 600,
            color: 'var(--text-primary)',
            marginBottom: '0.25rem',
          }}>
            Besoin d'aide détaillée ?
          </div>
          <div style={{
            fontSize: '0.76rem',
            color: 'var(--text-secondary)',
            lineHeight: 1.5,
          }}>
            Consultez notre centre de support complet avec plus de 20 problèmes
            fréquents et leurs solutions étape par étape.
          </div>
        </div>
        <Link
          to="/support"
          style={{
            background: 'var(--accent-violet)',
            color: '#fff',
            padding: '0.55rem 1.1rem',
            borderRadius: 8,
            textDecoration: 'none',
            fontSize: '0.82rem',
            fontWeight: 600,
            whiteSpace: 'nowrap',
          }}
        >
          Ouvrir le centre de support →
        </Link>
      </section>

      {/* ── Télécharger Syléa Desktop (cible de l'ancre #telecharger-desktop) ── */}
      <section id="telecharger-desktop" style={{
        background: 'linear-gradient(135deg, rgba(6,182,212,0.08), rgba(139,92,246,0.08))',
        border: '1px solid rgba(99,102,241,0.28)',
        borderRadius: 16,
        padding: '1.5rem 1.5rem 1.25rem',
        marginBottom: '2rem',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginBottom: '0.75rem' }}>
          <div style={{ fontSize: '1.75rem' }}>&#x1F4BB;</div>
          <h2 style={{
            margin: 0,
            fontSize: '1.1rem',
            fontWeight: 700,
            color: 'var(--text-primary)',
            letterSpacing: '0.01em',
          }}>
            Installer Syléa Desktop
          </h2>
        </div>
        <p style={{
          fontSize: '0.85rem',
          color: 'var(--text-secondary)',
          lineHeight: 1.6,
          margin: '0 0 1rem',
        }}>
          L'application desktop est ce qui permet à Syléa d'agir concrètement :
          écrire vos emails, planifier votre agenda, créer des pages Notion.
          Vos données restent sur votre ordinateur — Syléa les utilise mais ne
          les envoie nulle part. Installation en 2 minutes, sans commande
          à taper.
        </p>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.75rem', marginBottom: '0.75rem' }}>
          <a
            href="https://github.com/Clotilde563/Sylea-AI/releases/latest"
            target="_blank"
            rel="noopener noreferrer"
            style={{
              display: 'flex', flexDirection: 'column', alignItems: 'center',
              background: 'rgba(255,255,255,0.04)',
              border: '1px solid rgba(99,102,241,0.3)',
              borderRadius: 12,
              padding: '1rem',
              textDecoration: 'none',
              color: 'var(--text-primary)',
              fontSize: '0.82rem',
              fontWeight: 600,
              gap: '0.35rem',
              transition: 'background 0.2s',
            }}
          >
            <span style={{ fontSize: '1.5rem' }}>&#x1FA9F;</span>
            <span>Windows</span>
            <span style={{ fontSize: '0.7rem', color: 'var(--text-muted)', fontWeight: 400 }}>
              .exe / .msi
            </span>
          </a>
          <a
            href="https://github.com/Clotilde563/Sylea-AI/releases/latest"
            target="_blank"
            rel="noopener noreferrer"
            style={{
              display: 'flex', flexDirection: 'column', alignItems: 'center',
              background: 'rgba(255,255,255,0.04)',
              border: '1px solid rgba(99,102,241,0.15)',
              borderRadius: 12,
              padding: '1rem',
              textDecoration: 'none',
              color: 'var(--text-muted)',
              fontSize: '0.82rem',
              fontWeight: 600,
              gap: '0.35rem',
            }}
          >
            <span style={{ fontSize: '1.5rem' }}>&#x1F34F;</span>
            <span>Mac / Linux</span>
            <span style={{ fontSize: '0.7rem', fontWeight: 400 }}>
              bientôt
            </span>
          </a>
        </div>
        <div style={{
          fontSize: '0.75rem',
          color: 'var(--text-muted)',
          lineHeight: 1.5,
        }}>
          &#x1F511; <b>Après installation :</b> lancez l'application, laissez le wizard
          installer OpenClaw (1-2 minutes), choisissez vos skills (calendrier,
          email...), puis cliquez sur &laquo; Ouvrir Syléa sur le web &raquo;.
          Vous verrez apparaître un point vert en haut du site &mdash; c'est
          gagné.
        </div>
      </section>

      {/* ── Premiers pas ────────────────────────────────────────────── */}
      <CategorySection icon="&#x1F4F1;" title="Premiers pas">
        <Accordion title="Comment créer un profil" defaultOpen>
          <ol style={{ paddingLeft: '1.25rem', margin: '0.25rem 0' }}>
            <li>Depuis le tableau de bord, cliquez sur «&nbsp;Créer mon profil&nbsp;» dans le menu déroulant</li>
            <li>Remplissez l'étape 1 (Identité) : nom, âge, profession, ville, objectif de vie</li>
            <li>Répondez aux questions personnalisées générées par l'IA (étape 2)</li>
            <li>Complétez vos scores de bien-être et votre emploi du temps (étape 3)</li>
            <li>Cliquez sur «&nbsp;Créer mon profil&nbsp;» pour finaliser</li>
          </ol>
        </Accordion>
        <Accordion title="Comment analyser un choix">
          <ol style={{ paddingLeft: '1.25rem', margin: '0.25rem 0' }}>
            <li>Cliquez sur «&nbsp;Analyser un choix&nbsp;» dans la barre de navigation</li>
            <li>Sélectionnez l'impact temporel de votre décision (1 jour, 1 semaine, etc.)</li>
            <li>Entrez vos différentes options (minimum 2, maximum 5)</li>
            <li>Cliquez sur «&nbsp;Analyser avec Syléa.AI&nbsp;»</li>
            <li>Consultez le verdict : avantages, inconvénients et recommandation pour chaque option</li>
            <li>Choisissez une option pour mettre à jour votre probabilité</li>
          </ol>
        </Accordion>
        <Accordion title="Comment enregistrer un événement">
          <ol style={{ paddingLeft: '1.25rem', margin: '0.25rem 0' }}>
            <li>Depuis le tableau de bord, cliquez sur «&nbsp;Enregistrer un événement&nbsp;»</li>
            <li>Décrivez l'événement au clavier</li>
            <li>L'IA analysera automatiquement l'impact sur votre objectif</li>
            <li>Confirmez l'événement pour mettre à jour votre probabilité</li>
          </ol>
        </Accordion>
        <Accordion title="Comment utiliser le bilan quotidien">
          <ol style={{ paddingLeft: '1.25rem', margin: '0.25rem 0' }}>
            <li>Cliquez sur «&nbsp;Bilan du jour&nbsp;» depuis le tableau de bord</li>
            <li>Renseignez vos scores de bien-être (santé, stress, énergie, bonheur)</li>
            <li>Ajustez votre répartition du temps quotidien</li>
            <li>Optionnel : décrivez votre journée et l'IA remplira les scores automatiquement</li>
            <li>Enregistrez votre bilan (un seul par jour)</li>
          </ol>
        </Accordion>
      </CategorySection>

      {/* ── Fonctionnalités ─────────────────────────────────────────── */}
      <CategorySection icon="&#x1F4CA;" title="Fonctionnalités">
        <Accordion title="Comprendre la probabilité de réussite">
          <p>
            La probabilité de réussite est calculée par un moteur déterministe combiné à une analyse IA.
            Elle prend en compte votre profil, vos compétences, votre bien-être, le temps restant
            avant votre deadline et l'historique de vos décisions. Chaque décision ou événement
            peut faire varier cette probabilité.
          </p>
        </Accordion>
        <Accordion title="Les sous-objectifs et leur progression">
          <p>
            Syléa.AI génère automatiquement 4 sous-objectifs stratégiques liés à votre objectif de vie.
            Leur progression est séquentielle : complétez le premier avant de passer au suivant.
            Le sous-objectif actif est marqué «&nbsp;à prioriser&nbsp;». La durée estimée de chaque sous-objectif
            est proportionnelle à la durée totale de votre objectif.
          </p>
        </Accordion>
        <Accordion title='Le plan d&apos;action « Que faire »'>
          <p>
            Cliquez sur «&nbsp;Que faire ?&nbsp;» depuis le tableau de bord pour générer un plan d'action quotidien.
            L'IA propose des tâches concrètes liées à votre objectif, accompagnées de ressources
            (vidéos, formations, articles). Compléter une tâche augmente votre probabilité et
            fait progresser vos sous-objectifs.
          </p>
        </Accordion>
        <Accordion title="Les statistiques et graphiques">
          <p>
            La page Statistiques propose deux graphiques principaux :
          </p>
          <ul style={{ paddingLeft: '1.25rem', margin: '0.25rem 0' }}>
            <li><strong>Courbe théorique</strong> : évolution de la probabilité en fonction du temps restant</li>
            <li><strong>Progression réelle</strong> : historique de vos décisions et leur impact cumulé</li>
          </ul>
          <p>
            Des cartes de statistiques affichent le nombre de décisions, le gain de probabilité total,
            le temps économisé et le temps restant estimé.
          </p>
        </Accordion>
      </CategorySection>

      {/* ── Agents Syléa ───────────────────────────────────────────── */}
      <CategorySection icon="&#x1F916;" title="Agents Syléa">
        <Accordion title="Agent Syléa 1 — Compagnon">
          <p>
            L'Agent Syléa 1 est un compagnon conversationnel textuel. Il prend
            régulièrement de vos nouvelles, retient le contexte de vos échanges
            et enrichit vos analyses futures. Activez-le depuis la page
            «&nbsp;Mes agents Syléa&nbsp;» dans la barre de navigation.
          </p>
        </Accordion>
        <Accordion title="Agent Syléa 2 — Assistant">
          <p>
            L'Agent Syléa 2 est un assistant exécutant qui peut effectuer des
            actions concrètes via les skills installés sur votre application
            desktop (envoyer un email, créer un événement, prendre des notes,
            etc.). Chaque action exécutée nécessite votre validation explicite.
          </p>
        </Accordion>
        <Accordion title="Comment activer un agent">
          <p>
            Rendez-vous sur «&nbsp;Mes agents Syléa&nbsp;» dans la barre de navigation.
            Cliquez sur «&nbsp;Activer cet agent&nbsp;» et confirmez. Une fois actif,
            l'agent vous contactera régulièrement par message texte pour
            prendre de vos nouvelles.
          </p>
        </Accordion>
        <Accordion title="Les messages proactifs">
          <p>
            L'agent prend de vos nouvelles tous les 3 jours environ par message
            écrit. Il sauvegarde automatiquement les informations partagées
            pour enrichir vos analyses futures. Vous recevez une notification
            (point rouge) quand un nouveau message est disponible.
          </p>
        </Accordion>
      </CategorySection>

      {/* ── Paramètres ──────────────────────────────────────────────── */}
      <CategorySection icon="&#x2699;&#xFE0F;" title="Paramètres">
        <Accordion title="Changer la langue">
          <p>
            Allez dans Paramètres {">"} Langue. Plusieurs langues sont disponibles.
            La langue sélectionnée s'applique à l'ensemble de l'interface.
          </p>
        </Accordion>
        <Accordion title="Modifier la sécurité">
          <p>
            Dans Paramètres {">"} Sécurité, vous pouvez ajouter un mot de passe ou un schéma
            de verrouillage pour protéger l'accès à votre application. Vous pouvez également
            supprimer le verrouillage existant.
          </p>
        </Accordion>
        <Accordion title="Modifier mon profil">
          <p>
            Depuis le menu déroulant, cliquez sur «&nbsp;Modifier mon profil&nbsp;». Attention :
            modifier votre objectif de vie réinitialise tout votre historique (décisions,
            sous-objectifs, tâches).
          </p>
        </Accordion>
      </CategorySection>

      {/* ── FAQ ──────────────────────────────────────────────────────── */}
      <CategorySection icon="&#x2753;" title="FAQ">
        <Accordion title="L'application est-elle gratuite ?">
          <p>
            Oui, Syléa.AI est gratuite dans sa version web avec l'Agent 1 inclus.
            Des fonctionnalités avancées pourront être proposées dans des versions futures.
          </p>
        </Accordion>
        <Accordion title="Mes données sont-elles sécurisées ?">
          <p>
            Vos données sont chiffrées et stockées de manière sécurisée. Nous respectons
            le RGPD et vous avez un droit d'accès, de rectification et de suppression
            de vos données à tout moment. Consultez notre{' '}
            <Link to="/privacy" style={{ color: 'var(--accent-violet-light)' }}>
              Politique de confidentialité
            </Link>{' '}
            pour plus de détails.
          </p>
        </Accordion>
        <Accordion title="Comment supprimer mon compte ?">
          <p>
            Pour supprimer votre compte et toutes vos données, contactez-nous par email
            à sylea.ai.assistance@gmail.com ou via le formulaire de contact ci-dessous. La suppression
            sera effective dans un délai de 30 jours.
          </p>
        </Accordion>
        <Accordion title="L'IA est-elle fiable à 100 % ?">
          <p>
            Non. L'IA donne des estimations basées sur les données que vous fournissez et sur
            des modèles statistiques avancés. Elle ne garantit aucun résultat.
            Les recommandations sont des outils d'aide à la décision, pas des certitudes.
            Vous restez maître de vos choix. Consultez nos{' '}
            <Link to="/terms" style={{ color: 'var(--accent-violet-light)' }}>
              Conditions générales d'utilisation
            </Link>{' '}
            pour le détail de notre obligation de moyens.
          </p>
        </Accordion>
        <Accordion title="Puis-je utiliser l'application sur mobile ?">
          <p>
            L'application est actuellement optimisée pour les navigateurs desktop.
            Le responsive mobile est en cours de développement pour offrir une expérience
            optimale sur tous les appareils.
          </p>
        </Accordion>
      </CategorySection>

      {/* ── Contact ─────────────────────────────────────────────────── */}
      <CategorySection icon="&#x1F4E7;" title="Contact">
        <p style={{ fontSize: '0.82rem', color: 'var(--text-secondary)', marginBottom: '0.75rem' }}>
          Une question ? Un problème ? Contactez-nous par email à <strong>sylea.ai.assistance@gmail.com</strong> ou
          utilisez le formulaire ci-dessous.
        </p>
        <ContactForm />
      </CategorySection>

      {/* Back link */}
      <div style={{ textAlign: 'center', marginTop: '1.5rem' }}>
        <Link to="/" style={{
          color: 'var(--text-muted)', fontSize: '0.82rem',
          textDecoration: 'none',
        }}>
          &#8592; Retour au tableau de bord
        </Link>
      </div>
    </div>
  )
}
