// Politique de confidentialite — RGPD

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

export default function PrivacyPolicyPage() {
  return (
    <div className="container" style={{ maxWidth: 780, margin: '0 auto', padding: '2rem 1.5rem 4rem' }}>
      {/* Header */}
      <div style={{ textAlign: 'center', marginBottom: '2rem' }}>
        <div style={{ fontSize: '2rem', marginBottom: '0.5rem' }}>&#x1F512;</div>
        <h1 style={{
          fontSize: '1.6rem', fontWeight: 700,
          color: 'var(--text-primary)', letterSpacing: '0.02em',
          margin: '0 0 0.5rem',
        }}>
          Politique de confidentialite
        </h1>
        <p style={{ color: 'var(--text-muted)', fontSize: '0.82rem' }}>
          Derniere mise a jour : 26 mars 2026
        </p>
      </div>

      <Section title="1. Introduction" defaultOpen>
        <p>
          Sylea.AI est une application de coaching de vie augmente par intelligence artificielle.
          Cette politique de confidentialite explique comment nous collectons, utilisons et protegeons
          vos donnees personnelles conformement au Reglement General sur la Protection des Donnees (RGPD)
          et a la loi Informatique et Libertes.
        </p>
      </Section>

      <Section title="2. Responsable du traitement">
        <p>
          <strong>Responsable :</strong> Sylea.AI SAS<br />
          <strong>Adresse :</strong> Paris, France<br />
          <strong>Contact :</strong> contact@sylea.ai<br />
          <strong>Delegue a la protection des donnees (DPO) :</strong> dpo@sylea.ai
        </p>
      </Section>

      <Section title="3. Donnees collectees">
        <ul style={{ paddingLeft: '1.25rem', margin: '0.5rem 0' }}>
          <li><strong>Donnees d'identification :</strong> nom, email, age, genre, ville</li>
          <li><strong>Donnees de profil :</strong> profession, situation familiale, objectif de vie, competences, diplomes, langues</li>
          <li><strong>Donnees de bien-etre :</strong> scores sante, stress, energie, bonheur</li>
          <li><strong>Donnees de decision :</strong> choix formules, evenements enregistres, impact temporel</li>
          <li><strong>Donnees de conversation :</strong> messages echanges avec les agents IA</li>
          <li><strong>Donnees techniques :</strong> geolocalisation, navigateur, heure locale, adresse IP</li>
          <li><strong>Donnees vocales :</strong> enregistrements audio des messages vocaux</li>
        </ul>
      </Section>

      <Section title="4. Base legale du traitement">
        <p>
          Le traitement de vos donnees repose sur les bases legales suivantes :
        </p>
        <ul style={{ paddingLeft: '1.25rem', margin: '0.5rem 0' }}>
          <li><strong>Consentement (art. 6.1.a RGPD)</strong> pour les donnees de profil, de bien-etre et de conversation</li>
          <li><strong>Execution du contrat (art. 6.1.b RGPD)</strong> pour la fourniture du service</li>
          <li><strong>Interet legitime (art. 6.1.f RGPD)</strong> pour les donnees techniques necessaires au fonctionnement et a la securite</li>
        </ul>
      </Section>

      <Section title="5. Finalites du traitement">
        <ul style={{ paddingLeft: '1.25rem', margin: '0.5rem 0' }}>
          <li>Fourniture du service : analyses IA, suivi d'objectif, recommandations personnalisees</li>
          <li>Personnalisation de l'experience utilisateur</li>
          <li>Amelioration continue du service et de la precision des analyses</li>
          <li>Communications relatives au compte et au service</li>
          <li>Securite et prevention des abus</li>
        </ul>
      </Section>

      <Section title="6. Destinataires des donnees">
        <p>Vos donnees peuvent etre partagees avec les prestataires suivants, dans le cadre strict de la fourniture du service :</p>
        <ul style={{ paddingLeft: '1.25rem', margin: '0.5rem 0' }}>
          <li><strong>Anthropic (Claude API)</strong> — analyses IA et generation de contenu</li>
          <li><strong>OpenAI</strong> — synthese vocale (TTS)</li>
          <li><strong>Open-Meteo</strong> — donnees meteorologiques</li>
        </ul>
        <p style={{ marginTop: '0.75rem', fontWeight: 600 }}>
          Aucune vente de donnees a des tiers. Aucune utilisation publicitaire.
        </p>
      </Section>

      <Section title="7. Duree de conservation">
        <p>
          Vos donnees sont conservees tant que votre compte est actif. En cas de demande de suppression,
          vos donnees seront effacees dans un delai de 30 jours. Les donnees techniques (logs)
          sont conservees 12 mois maximum.
        </p>
      </Section>

      <Section title="8. Vos droits (RGPD art. 15-21)">
        <p>Conformement au RGPD, vous disposez des droits suivants :</p>
        <ul style={{ paddingLeft: '1.25rem', margin: '0.5rem 0' }}>
          <li><strong>Droit d'acces</strong> — obtenir une copie de vos donnees personnelles</li>
          <li><strong>Droit de rectification</strong> — corriger vos donnees inexactes</li>
          <li><strong>Droit a l'effacement</strong> (droit a l'oubli) — supprimer vos donnees</li>
          <li><strong>Droit a la portabilite</strong> — recevoir vos donnees dans un format structure</li>
          <li><strong>Droit d'opposition</strong> — vous opposer au traitement de vos donnees</li>
          <li><strong>Droit de retrait du consentement</strong> — retirer votre consentement a tout moment</li>
          <li><strong>Droit a la limitation</strong> — limiter le traitement de vos donnees</li>
        </ul>
        <p style={{ marginTop: '0.75rem' }}>
          Pour exercer vos droits, contactez-nous a : <strong>dpo@sylea.ai</strong>
        </p>
        <p>
          Vous disposez egalement du droit d'introduire une reclamation aupres de la CNIL
          (Commission nationale de l'informatique et des libertes).
        </p>
      </Section>

      <Section title="9. Transferts hors UE">
        <p>
          Les donnees peuvent etre traitees par Anthropic (USA) et OpenAI (USA) dans le cadre
          de la fourniture du service. Ces transferts sont encadres par les clauses contractuelles
          types (CCT) approuvees par la Commission europeenne, garantissant un niveau de
          protection adequat de vos donnees.
        </p>
      </Section>

      <Section title="10. Cookies">
        <p>
          L'application utilise differents types de cookies :
        </p>
        <ul style={{ paddingLeft: '1.25rem', margin: '0.5rem 0' }}>
          <li><strong>Cookies essentiels</strong> — necessaires au fonctionnement (authentification, preferences)</li>
          <li><strong>Cookies analytiques</strong> — mesure d'audience et amelioration du service</li>
          <li><strong>Cookies de personnalisation</strong> — adaptation de l'experience utilisateur</li>
        </ul>
        <p>
          Vous pouvez gerer vos preferences de cookies a tout moment via le bandeau de consentement.
        </p>
      </Section>

      <Section title="11. Modifications">
        <p>
          Cette politique peut etre modifiee a tout moment. En cas de modification substantielle,
          vous serez informe(e) par email ou par notification dans l'application.
          La date de derniere mise a jour est indiquee en haut de cette page.
        </p>
      </Section>

      <Section title="12. Contact">
        <p>
          Pour toute question relative a cette politique de confidentialite ou a vos donnees personnelles :
        </p>
        <ul style={{ paddingLeft: '1.25rem', margin: '0.5rem 0' }}>
          <li><strong>Email :</strong> contact@sylea.ai</li>
          <li><strong>DPO :</strong> dpo@sylea.ai</li>
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
