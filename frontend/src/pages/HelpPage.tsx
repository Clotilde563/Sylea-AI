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
          placeholder="Decrivez votre question ou probleme..."
          value={message} onChange={e => setMessage(e.target.value)} required
          style={{ resize: 'vertical', minHeight: 80, fontFamily: 'var(--font-sans)' }} />
      </div>
      <button type="submit" className="btn btn-primary" disabled={sent}
        style={{ alignSelf: 'flex-start', padding: '0.55rem 1.5rem' }}>
        {sent ? 'Message envoye !' : 'Envoyer'}
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
          Tout ce que vous devez savoir pour utiliser Sylea.AI
        </p>
      </div>

      {/* ── Premiers pas ────────────────────────────────────────────── */}
      <CategorySection icon="&#x1F4F1;" title="Premiers pas">
        <Accordion title="Comment creer un profil" defaultOpen>
          <ol style={{ paddingLeft: '1.25rem', margin: '0.25rem 0' }}>
            <li>Depuis le tableau de bord, cliquez sur "Creer mon profil" dans le menu deroulant</li>
            <li>Remplissez l'etape 1 (Identite) : nom, age, profession, ville, objectif de vie</li>
            <li>Repondez aux questions personnalisees generees par l'IA (etape 2)</li>
            <li>Completez vos scores de bien-etre et votre emploi du temps (etape 3)</li>
            <li>Cliquez sur "Creer mon profil" pour finaliser</li>
          </ol>
        </Accordion>
        <Accordion title="Comment analyser un choix">
          <ol style={{ paddingLeft: '1.25rem', margin: '0.25rem 0' }}>
            <li>Cliquez sur "Analyser un choix" dans la barre de navigation</li>
            <li>Selectionnez l'impact temporel de votre decision (1 jour, 1 semaine, etc.)</li>
            <li>Entrez vos differentes options (minimum 2, maximum 5)</li>
            <li>Cliquez sur "Analyser avec Sylea.AI"</li>
            <li>Consultez le verdict : avantages, inconvenients et recommandation pour chaque option</li>
            <li>Choisissez une option pour mettre a jour votre probabilite</li>
          </ol>
        </Accordion>
        <Accordion title="Comment enregistrer un evenement">
          <ol style={{ paddingLeft: '1.25rem', margin: '0.25rem 0' }}>
            <li>Depuis le tableau de bord, cliquez sur "Enregistrer un evenement"</li>
            <li>Decrivez l'evenement (vous pouvez aussi utiliser la saisie vocale)</li>
            <li>L'IA analysera automatiquement l'impact sur votre objectif</li>
            <li>Confirmez l'evenement pour mettre a jour votre probabilite</li>
          </ol>
        </Accordion>
        <Accordion title="Comment utiliser le bilan quotidien">
          <ol style={{ paddingLeft: '1.25rem', margin: '0.25rem 0' }}>
            <li>Cliquez sur "Bilan du jour" depuis le tableau de bord</li>
            <li>Renseignez vos scores de bien-etre (sante, stress, energie, bonheur)</li>
            <li>Ajustez votre repartition du temps quotidien</li>
            <li>Optionnel : decrivez votre journee et l'IA remplira les scores automatiquement</li>
            <li>Enregistrez votre bilan (un seul par jour)</li>
          </ol>
        </Accordion>
      </CategorySection>

      {/* ── Fonctionnalites ─────────────────────────────────────────── */}
      <CategorySection icon="&#x1F4CA;" title="Fonctionnalites">
        <Accordion title="Comprendre la probabilite de reussite">
          <p>
            La probabilite de reussite est calculee par un moteur deterministe combine a une analyse IA.
            Elle prend en compte votre profil, vos competences, votre bien-etre, le temps restant
            avant votre deadline et l'historique de vos decisions. Chaque decision ou evenement
            peut faire varier cette probabilite.
          </p>
        </Accordion>
        <Accordion title="Les sous-objectifs et leur progression">
          <p>
            Sylea.AI genere automatiquement 4 sous-objectifs strategiques lies a votre objectif de vie.
            Leur progression est sequentielle : completez le premier avant de passer au suivant.
            Le sous-objectif actif est marque "a prioriser". La duree estimee de chaque sous-objectif
            est proportionnelle a la duree totale de votre objectif.
          </p>
        </Accordion>
        <Accordion title='Le plan d&apos;action "Que faire"'>
          <p>
            Cliquez sur "Que faire ?" depuis le tableau de bord pour generer un plan d'action quotidien.
            L'IA propose des taches concretes liees a votre objectif, accompagnees de ressources
            (videos, formations, articles). Completer une tache augmente votre probabilite et
            fait progresser vos sous-objectifs.
          </p>
        </Accordion>
        <Accordion title="Les statistiques et graphiques">
          <p>
            La page Statistiques propose deux graphiques principaux :
          </p>
          <ul style={{ paddingLeft: '1.25rem', margin: '0.25rem 0' }}>
            <li><strong>Courbe theorique</strong> : evolution de la probabilite en fonction du temps restant</li>
            <li><strong>Progression reelle</strong> : historique de vos decisions et leur impact cumule</li>
          </ul>
          <p>
            Des cartes de statistiques affichent le nombre de decisions, le gain de probabilite total,
            le temps economise et le temps restant estime.
          </p>
        </Accordion>
      </CategorySection>

      {/* ── Agent Sylea 1 ───────────────────────────────────────────── */}
      <CategorySection icon="&#x1F916;" title="Agent Sylea 1">
        <Accordion title="Comment activer l'agent">
          <p>
            Rendez-vous sur "Mes agents Sylea" dans la barre de navigation. Cliquez sur
            "Activer cet agent" et confirmez. Une fois actif, l'agent vous contactera
            regulierement pour prendre de vos nouvelles.
          </p>
        </Accordion>
        <Accordion title="Les messages vocaux">
          <p>
            Maintenez le bouton microphone pour enregistrer un message vocal. L'agent
            comprend le francais et peut repondre par synthese vocale. Les messages vocaux
            sont transcrits automatiquement.
          </p>
        </Accordion>
        <Accordion title="Les appels vocaux">
          <p>
            L'agent peut initier des appels vocaux pour des conversations plus naturelles.
            Vous pouvez repondre par la voix et l'agent adaptera ses reponses en temps reel.
          </p>
        </Accordion>
        <Accordion title="Les messages proactifs">
          <p>
            L'agent prend de vos nouvelles tous les 3 jours environ. Il sauvegarde automatiquement
            les informations partagees pour enrichir vos analyses futures. Vous recevez une
            notification (point rouge) quand un nouveau message est disponible.
          </p>
        </Accordion>
      </CategorySection>

      {/* ── Parametres ──────────────────────────────────────────────── */}
      <CategorySection icon="&#x2699;&#xFE0F;" title="Parametres">
        <Accordion title="Changer la langue">
          <p>
            Allez dans Parametres {">"} Langue. 13 langues sont disponibles. La langue
            selectionnee s'applique a l'ensemble de l'interface.
          </p>
        </Accordion>
        <Accordion title="Modifier la securite">
          <p>
            Dans Parametres {">"} Securite, vous pouvez ajouter un mot de passe ou un schema
            de verrouillage pour proteger l'acces a votre application. Vous pouvez egalement
            supprimer le verrouillage existant.
          </p>
        </Accordion>
        <Accordion title="Modifier mon profil">
          <p>
            Depuis le menu deroulant, cliquez sur "Modifier mon profil". Attention : modifier
            votre objectif de vie reinitialise tout votre historique (decisions, sous-objectifs, taches).
          </p>
        </Accordion>
      </CategorySection>

      {/* ── FAQ ──────────────────────────────────────────────────────── */}
      <CategorySection icon="&#x2753;" title="FAQ">
        <Accordion title="L'application est-elle gratuite ?">
          <p>
            Oui, Sylea.AI est gratuite dans sa version web avec l'Agent 1 inclus.
            Des fonctionnalites avancees pourront etre proposees dans des versions futures.
          </p>
        </Accordion>
        <Accordion title="Mes donnees sont-elles securisees ?">
          <p>
            Vos donnees sont chiffrees et stockees de maniere securisee. Nous respectons
            le RGPD et vous avez un droit d'acces, de rectification et de suppression
            de vos donnees a tout moment. Consultez notre{' '}
            <Link to="/privacy" style={{ color: 'var(--accent-violet-light)' }}>
              Politique de confidentialite
            </Link>{' '}
            pour plus de details.
          </p>
        </Accordion>
        <Accordion title="Comment supprimer mon compte ?">
          <p>
            Pour supprimer votre compte et toutes vos donnees, contactez-nous par email
            a sylea.ai.assistance@gmail.com ou via le formulaire de contact ci-dessous. La suppression
            sera effective dans un delai de 30 jours.
          </p>
        </Accordion>
        <Accordion title="L'IA est-elle fiable a 100% ?">
          <p>
            L'IA donne des estimations basees sur les donnees que vous fournissez et sur
            des modeles statistiques avances. Cependant, elle ne garantit pas les resultats.
            Les recommandations sont des outils d'aide a la decision, pas des certitudes.
            Vous restez maitre de vos choix.
          </p>
        </Accordion>
        <Accordion title="Puis-je utiliser l'app sur mobile ?">
          <p>
            L'application est actuellement optimisee pour les navigateurs desktop.
            Le responsive mobile est en cours de developpement pour offrir une experience
            optimale sur tous les appareils.
          </p>
        </Accordion>
      </CategorySection>

      {/* ── Contact ─────────────────────────────────────────────────── */}
      <CategorySection icon="&#x1F4E7;" title="Contact">
        <p style={{ fontSize: '0.82rem', color: 'var(--text-secondary)', marginBottom: '0.75rem' }}>
          Une question ? Un probleme ? Contactez-nous par email a <strong>sylea.ai.assistance@gmail.com</strong> ou
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
