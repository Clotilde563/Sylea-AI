// Conditions Generales d'Utilisation — CGU

import { useState } from 'react'
import { Link } from 'react-router-dom'

interface SectionProps {
  title: string
  children: React.ReactNode
  defaultOpen?: boolean
}

function Section({ title, children, defaultOpen = false }: SectionProps) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <div style={{
      background: 'var(--bg-surface)',
      border: '1px solid var(--border)',
      borderRadius: 'var(--radius-lg)',
      overflow: 'hidden',
      marginBottom: '0.75rem',
    }}>
      <button
        onClick={() => setOpen(!open)}
        style={{
          width: '100%', display: 'flex', alignItems: 'center',
          justifyContent: 'space-between',
          padding: '1rem 1.25rem',
          background: 'transparent', border: 'none',
          cursor: 'pointer', color: 'var(--text-primary)',
          fontSize: '0.9rem', fontWeight: 600, textAlign: 'left',
          fontFamily: 'var(--font-sans)',
        }}
      >
        <span>{title}</span>
        <svg width={16} height={16} viewBox="0 0 24 24" fill="none"
          stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round"
          style={{ transition: 'transform 0.25s', transform: open ? 'rotate(180deg)' : 'rotate(0deg)', flexShrink: 0 }}>
          <polyline points="6 9 12 15 18 9" />
        </svg>
      </button>
      {open && (
        <div style={{
          padding: '0 1.25rem 1.25rem',
          fontSize: '0.82rem', color: 'var(--text-secondary)',
          lineHeight: 1.75,
        }}>
          {children}
        </div>
      )}
    </div>
  )
}

export default function TermsPage() {
  return (
    <div className="container" style={{ maxWidth: 780, margin: '0 auto', padding: '2rem 1.5rem 4rem' }}>
      {/* Header */}
      <div style={{ textAlign: 'center', marginBottom: '2rem' }}>
        <div style={{ fontSize: '2rem', marginBottom: '0.5rem' }}>&#x1F4DC;</div>
        <h1 style={{
          fontSize: '1.6rem', fontWeight: 700,
          color: 'var(--text-primary)', letterSpacing: '0.02em',
          margin: '0 0 0.5rem',
        }}>
          Conditions Generales d'Utilisation
        </h1>
        <p style={{ color: 'var(--text-muted)', fontSize: '0.82rem' }}>
          Derniere mise a jour : 26 mars 2026
        </p>
      </div>

      <Section title="1. Objet" defaultOpen>
        <p>
          Les presentes Conditions Generales d'Utilisation (CGU) regissent l'acces et l'utilisation
          de l'application Sylea.AI, un service de coaching de vie augmente par intelligence artificielle.
          En utilisant le service, vous acceptez l'integralite des presentes conditions.
        </p>
      </Section>

      <Section title="2. Acces au service">
        <p>
          Le service Sylea.AI est accessible via un navigateur web. L'acces necessite une connexion
          internet et un navigateur compatible (Chrome, Firefox, Safari, Edge dans leurs versions recentes).
          Le service est disponible 24h/24, 7j/7, sous reserve des periodes de maintenance.
        </p>
      </Section>

      <Section title="3. Inscription">
        <p>
          L'utilisation du service necessite la creation d'un compte utilisateur. L'utilisateur
          s'engage a fournir des informations exactes et a maintenir la confidentialite de ses
          identifiants de connexion. Chaque utilisateur est responsable de l'activite realisee
          sous son compte.
        </p>
      </Section>

      <Section title="4. Obligations de l'utilisateur">
        <p>L'utilisateur s'engage a :</p>
        <ul style={{ paddingLeft: '1.25rem', margin: '0.5rem 0' }}>
          <li>Utiliser le service de maniere loyale et conforme a sa destination</li>
          <li>Ne pas tenter de compromettre la securite ou le fonctionnement du service</li>
          <li>Ne pas utiliser le service a des fins illicites ou contraires aux bonnes moeurs</li>
          <li>Ne pas usurper l'identite d'un tiers</li>
          <li>Respecter les droits de propriete intellectuelle</li>
        </ul>
      </Section>

      <Section title="5. Propriete intellectuelle">
        <p>
          L'ensemble des elements constituant le service Sylea.AI (logiciel, interface, algorithmes,
          bases de donnees, marques, logos) sont la propriete exclusive de Sylea.AI SAS et sont
          proteges par le droit de la propriete intellectuelle. Toute reproduction, representation
          ou exploitation non autorisee est interdite.
        </p>
        <p style={{ marginTop: '0.5rem' }}>
          Les contenus generes par l'IA dans le cadre de l'utilisation du service restent la propriete
          de l'utilisateur. Sylea.AI conserve un droit d'utilisation anonymise a des fins d'amelioration
          du service.
        </p>
      </Section>

      <Section title="6. Limitation de responsabilite">
        <p>
          Sylea.AI est un outil d'aide a la decision fonde sur l'intelligence artificielle.
          Les analyses, recommandations et probabilites fournies sont des estimations basees
          sur les donnees communiquees par l'utilisateur et ne constituent en aucun cas :
        </p>
        <ul style={{ paddingLeft: '1.25rem', margin: '0.5rem 0' }}>
          <li>Un conseil professionnel (juridique, medical, financier)</li>
          <li>Une garantie de resultat</li>
          <li>Un engagement contractuel sur la realisation d'un objectif</li>
        </ul>
        <p style={{ marginTop: '0.5rem' }}>
          L'utilisateur reste seul responsable de ses decisions. Sylea.AI ne saurait etre tenu
          responsable des consequences directes ou indirectes liees a l'utilisation du service.
        </p>
      </Section>

      <Section title="7. Donnees personnelles">
        <p>
          Le traitement des donnees personnelles est regi par notre{' '}
          <Link to="/privacy" style={{ color: 'var(--accent-violet-light)' }}>
            Politique de confidentialite
          </Link>
          , qui fait partie integrante des presentes CGU.
        </p>
      </Section>

      <Section title="8. Resiliation">
        <p>
          L'utilisateur peut supprimer son compte a tout moment en contactant le service client.
          Sylea.AI se reserve le droit de suspendre ou supprimer un compte en cas de violation
          des presentes CGU, apres notification prealable sauf en cas d'urgence.
        </p>
        <p style={{ marginTop: '0.5rem' }}>
          En cas de suppression du compte, les donnees personnelles seront effacees dans un delai
          de 30 jours conformement a la politique de confidentialite.
        </p>
      </Section>

      <Section title="9. Droit applicable">
        <p>
          Les presentes CGU sont regies par le droit francais. Tout litige relatif a leur
          interpretation ou a leur execution sera soumis aux tribunaux competents de Paris,
          sous reserve des dispositions legales imperatives applicables au consommateur.
        </p>
      </Section>

      <Section title="10. Contact">
        <p>
          Pour toute question relative aux presentes CGU :
        </p>
        <ul style={{ paddingLeft: '1.25rem', margin: '0.5rem 0' }}>
          <li><strong>Email :</strong> sylea.ai.assistance@gmail.com</li>
          <li><strong>Formulaire :</strong> disponible dans la section <Link to="/help" style={{ color: 'var(--accent-violet-light)' }}>Aide et ressources</Link></li>
        </ul>
      </Section>

      {/* Back link */}
      <div style={{ textAlign: 'center', marginTop: '1.5rem' }}>
        <Link to="/" style={{
          color: 'var(--text-muted)', fontSize: '0.82rem',
          textDecoration: 'none',
        }}>
          &#8592; Retour a l'accueil
        </Link>
      </div>
    </div>
  )
}
