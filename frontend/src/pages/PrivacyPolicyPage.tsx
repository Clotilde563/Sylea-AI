// Politique de confidentialité — RGPD (réécriture 2026-05-17, texte dense)

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
      marginBottom: '0.5rem',
    }}>
      <button
        onClick={() => setOpen(!open)}
        style={{
          width: '100%', display: 'flex', alignItems: 'center',
          justifyContent: 'space-between',
          padding: '0.75rem 1rem',
          background: 'transparent', border: 'none',
          cursor: 'pointer', color: 'var(--text-primary)',
          fontSize: '0.82rem', fontWeight: 600, textAlign: 'left',
        }}
      >
        <span>{title}</span>
        <span style={{ transform: open ? 'rotate(90deg)' : 'rotate(0deg)', transition: 'transform 0.2s' }}>›</span>
      </button>
      {open && (
        <div style={{
          padding: '0 1rem 0.85rem',
          color: 'var(--text-secondary)',
          fontSize: '0.72rem',
          lineHeight: 1.55,
          textAlign: 'justify',
        }}>
          {children}
        </div>
      )}
    </div>
  )
}

export default function PrivacyPolicyPage() {
  return (
    <div className="container" style={{ maxWidth: 820, margin: '0 auto', padding: '1.5rem 1.25rem 3rem' }}>
      <div style={{ textAlign: 'center', marginBottom: '1.5rem' }}>
        <div style={{ fontSize: '1.7rem', marginBottom: '0.4rem' }}>&#x1F512;</div>
        <h1 style={{ fontSize: '1.35rem', fontWeight: 700, color: 'var(--text-primary)', margin: '0 0 0.3rem' }}>
          Politique de confidentialité
        </h1>
        <p style={{ color: 'var(--text-muted)', fontSize: '0.7rem', margin: 0 }}>
          Version 3.0 · Dernière mise à jour : 17 mai 2026 · Conforme RGPD (UE 2016/679), Loi Informatique et Libertés (78-17), CCPA (USA)
        </p>
      </div>

      <Section title="Préambule et acceptation" defaultOpen>
        <p>
          La présente politique de confidentialité (« Politique ») régit le traitement des données à caractère personnel
          effectué par Syléa.AI SAS (« Syléa », « nous », « notre », « nos ») dans le cadre de l'utilisation de l'application
          web, du logiciel desktop, de l'application mobile et de tout service connexe (ensemble, le « Service ») accessibles
          via le domaine sylea-ai.vercel.app et tout sous-domaine ou domaine de remplacement.
        </p>
        <p>
          En créant un compte, en accédant au Service ou en l'utilisant de quelque manière que ce soit, l'utilisateur (« vous »,
          « votre », « vos ») reconnaît avoir lu, compris et accepté sans réserve l'intégralité des dispositions de la présente
          Politique. Si vous n'acceptez pas ces dispositions, vous devez immédiatement cesser d'utiliser le Service et procéder
          à la suppression de votre compte conformément aux modalités prévues à la section consacrée à vos droits.
        </p>
        <p>
          La présente Politique doit être lue conjointement avec les Conditions Générales d'Utilisation (CGU) et la Charte
          Cookies, qui en font partie intégrante. En cas de divergence d'interprétation, les dispositions les plus protectrices
          des droits de l'utilisateur prévaudront, dans la stricte mesure des prescriptions légales applicables.
        </p>
      </Section>

      <Section title="1. Responsable du traitement et coordonnées">
        <p>
          Le responsable du traitement, au sens de l'article 4-7 du RGPD, est : <strong>Syléa.AI SAS</strong>, société par
          actions simplifiée immatriculée au Registre du Commerce et des Sociétés (RCS) en cours d'enregistrement, ayant
          son siège social à Paris (France). Toute correspondance peut être adressée à l'adresse électronique de contact
          unique : <strong>sylea.ai.assistance@gmail.com</strong>.
        </p>
        <p>
          Un Délégué à la Protection des Données (DPO) est désigné conformément à l'article 37 du RGPD et joignable à la
          même adresse électronique. L'utilisateur dispose à tout moment du droit de saisir directement le DPO pour toute
          question relative au traitement de ses données à caractère personnel, indépendamment des autres canaux de
          communication mis à sa disposition.
        </p>
      </Section>

      <Section title="2. Données collectées et catégories">
        <p>
          Syléa collecte différentes catégories de données à caractère personnel, à savoir, sans que cette énumération soit
          limitative :
        </p>
        <ul style={{ paddingLeft: '1rem', margin: '0.4rem 0' }}>
          <li><strong>Données d'identification</strong> : nom, prénom, adresse électronique, âge, genre, ville de résidence, photographie de profil (le cas échéant).</li>
          <li><strong>Données de profil professionnel et personnel</strong> : profession, situation familiale, objectif de vie déclaré, compétences, diplômes, langues parlées, revenu annuel déclaré, patrimoine estimé déclaré, charges mensuelles déclarées.</li>
          <li><strong>Données de bien-être déclarées</strong> : scores auto-évalués de santé, stress, énergie, bonheur (échelle de 1 à 10), volumes horaires quotidiens déclarés (travail, sommeil, loisirs, transport, objectif).</li>
          <li><strong>Données comportementales et décisionnelles</strong> : choix soumis à analyse, événements enregistrés, options sélectionnées, impact temporel calculé, bilans quotidiens, sous-objectifs créés.</li>
          <li><strong>Données conversationnelles</strong> : intégralité des messages textuels échangés avec les agents conversationnels intégrés au Service (Agent Syléa 1 — Compagnon, Agent Syléa 2 — Assistant), incluant le contenu des conversations et les métadonnées associées (horodatage, contexte).</li>
          <li><strong>Données techniques</strong> : adresse IP, identifiants de session, user-agent du navigateur, type d'appareil, système d'exploitation, fuseau horaire, langue préférée, géolocalisation approximative (ville uniquement, sur la base du consentement explicite ou de l'adresse IP), données de météo locale (fournies par un tiers).</li>
          <li><strong>Données financières (paiements)</strong> : montants payés, identifiants d'abonnement, historique de facturation. Les données de carte bancaire ne sont jamais collectées ni stockées par Syléa : elles sont traitées exclusivement par notre prestataire Stripe, certifié PCI-DSS niveau 1.</li>
          <li><strong>Données d'intégration tierce</strong> : jetons d'accès OAuth (Google, GitHub, et autres fournisseurs au fur et à mesure de leur déploiement), chiffrés par algorithme Fernet (AES-128-CBC + HMAC-SHA256) avant stockage en base de données.</li>
        </ul>
        <p>
          L'utilisateur est seul responsable de l'exactitude des données qu'il déclare. Syléa ne procède à aucune vérification
          automatique ni manuelle de la véracité des informations déclaratives. Toute donnée fausse, trompeuse ou incomplète
          relève de la responsabilité exclusive de l'utilisateur, et Syléa ne saurait être tenue responsable des conséquences
          qui en découleraient sur la qualité des analyses produites.
        </p>
      </Section>

      <Section title="3. Bases légales du traitement (art. 6 RGPD)">
        <p>
          Le traitement de vos données repose sur les bases légales suivantes, lesquelles peuvent se cumuler selon les
          finalités spécifiquement poursuivies :
        </p>
        <ul style={{ paddingLeft: '1rem', margin: '0.4rem 0' }}>
          <li><strong>Consentement libre, éclairé, spécifique et univoque (art. 6.1.a RGPD)</strong> pour l'ensemble des données de profil étendu, données de bien-être, données conversationnelles et données de géolocalisation précise. Ce consentement peut être retiré à tout moment sans porter atteinte à la licéité du traitement effectué avant retrait.</li>
          <li><strong>Exécution du contrat (art. 6.1.b RGPD)</strong> pour la fourniture effective du Service auquel l'utilisateur a souscrit, y compris la création et la maintenance du compte, l'exécution des analyses demandées, la facturation des prestations.</li>
          <li><strong>Intérêt légitime (art. 6.1.f RGPD)</strong> pour les données techniques nécessaires au fonctionnement, à la sécurité, à la prévention des fraudes et abus, à l'amélioration du Service, ainsi que pour les communications opérationnelles non promotionnelles.</li>
          <li><strong>Obligation légale (art. 6.1.c RGPD)</strong> pour la conservation des données comptables et fiscales conformément aux durées légales (10 ans pour les pièces comptables, code de commerce art. L.123-22).</li>
        </ul>
      </Section>

      <Section title="4. Finalités du traitement">
        <p>
          Vos données à caractère personnel sont traitées exclusivement aux fins suivantes, lesquelles sont strictement
          nécessaires et proportionnées :
        </p>
        <ul style={{ paddingLeft: '1rem', margin: '0.4rem 0' }}>
          <li>Fourniture du Service : analyses par intelligence artificielle, calcul de la probabilité de réussite des objectifs, génération de recommandations personnalisées, suivi temporel des objectifs et sous-objectifs, gestion des dilemmes et événements de vie.</li>
          <li>Personnalisation de l'expérience utilisateur : adaptation du ton conversationnel selon le niveau de familiarité, suggestions contextuelles, recommandations basées sur l'historique.</li>
          <li>Amélioration continue du Service : analyse statistique agrégée et anonymisée des usages, détection des erreurs et incidents, optimisation des performances et de la pertinence des analyses.</li>
          <li>Communications relatives au compte : confirmations d'inscription, codes de vérification, alertes de sécurité, notifications opérationnelles, rappels d'objectifs (sur consentement séparé).</li>
          <li>Sécurité et prévention des abus : détection des tentatives d'intrusion, blocage des comptes frauduleux, journalisation des accès, application des limites d'usage (rate limiting) et plafonds financiers.</li>
          <li>Obligations comptables, fiscales et légales : conservation des factures, réponse aux réquisitions judiciaires émanant d'une autorité compétente.</li>
        </ul>
      </Section>

      <Section title="5. Destinataires et sous-traitants">
        <p>
          Vos données peuvent être transmises aux catégories de destinataires suivantes, exclusivement dans le cadre et la
          mesure stricts de la fourniture du Service :
        </p>
        <ul style={{ paddingLeft: '1rem', margin: '0.4rem 0' }}>
          <li><strong>Anthropic, Inc.</strong> (Claude API) — analyses par modèles de langage, génération de réponses conversationnelles. Hébergement aux États-Unis. Garanties : Data Processing Addendum signé, conformité SOC 2 Type II, clauses contractuelles types (CCT) UE-USA.</li>
          <li><strong>OpenAI, L.L.C.</strong> — fonctionnalités complémentaires d'intelligence artificielle. Hébergement aux États-Unis. Mêmes garanties contractuelles que pour Anthropic.</li>
          <li><strong>Stripe Payments Europe Ltd.</strong> — traitement des paiements par carte bancaire. Conformité PCI-DSS niveau 1. Aucune donnée bancaire ne transite par les serveurs de Syléa.</li>
          <li><strong>Open-Meteo GmbH</strong> — données météorologiques publiques basées sur la géolocalisation approximative déclarée.</li>
          <li><strong>Hébergeurs techniques</strong> : Railway Corp (États-Unis), Vercel Inc. (États-Unis), Supabase Inc. (Singapour/USA) ou tout autre fournisseur équivalent. Tous nos hébergeurs sont liés par des accords de traitement (DPA) et fournissent des garanties contractuelles strictes.</li>
          <li><strong>Autorités administratives et judiciaires</strong> : exclusivement sur réquisition légale et après vérification de la compétence et de la régularité formelle de la demande.</li>
        </ul>
        <p>
          <strong>Engagement formel :</strong> Syléa ne vend, ne loue, ni n'échange aucune donnée à caractère personnel avec
          des tiers à des fins commerciales ou publicitaires. Aucune donnée n'est utilisée pour entraîner des modèles
          d'intelligence artificielle généraux. Aucun profilage publicitaire n'est effectué.
        </p>
      </Section>

      <Section title="6. Transferts hors Union européenne">
        <p>
          Certains des prestataires mentionnés ci-dessus étant établis en dehors de l'Espace économique européen (EEE),
          notamment aux États-Unis, vos données peuvent faire l'objet de transferts internationaux. Ces transferts sont
          encadrés par les mécanismes suivants, garantissant un niveau de protection adéquat :
        </p>
        <ul style={{ paddingLeft: '1rem', margin: '0.4rem 0' }}>
          <li>Clauses contractuelles types (CCT) approuvées par la Commission européenne (décision 2021/914 du 4 juin 2021).</li>
          <li>Évaluations d'impact des transferts (Transfer Impact Assessment) menées conformément aux recommandations 01/2020 du Comité européen de la protection des données (CEPD).</li>
          <li>Mesures techniques complémentaires : chiffrement en transit (TLS 1.3) et au repos (AES-256), pseudonymisation lorsque techniquement réalisable.</li>
          <li>Pour les transferts vers les États-Unis, application du Data Privacy Framework (DPF) UE-USA lorsque les prestataires y sont certifiés.</li>
        </ul>
        <p>
          L'utilisateur reconnaît expressément avoir été informé de ces transferts et y consentir dans la mesure strictement
          nécessaire à la fourniture du Service. Il est rappelé que la législation américaine peut, dans certains cas
          limitativement énumérés, permettre l'accès aux données par les autorités fédérales (FISA 702, Executive Order 12333),
          Syléa ne disposant pas du pouvoir matériel de s'y opposer.
        </p>
      </Section>

      <Section title="7. Durée de conservation">
        <p>
          Les données à caractère personnel sont conservées pendant les durées strictement nécessaires aux finalités
          poursuivies, à savoir :
        </p>
        <ul style={{ paddingLeft: '1rem', margin: '0.4rem 0' }}>
          <li>Données de compte et de profil : tant que le compte est actif, augmenté d'un délai de 30 jours après la
            demande de clôture pour permettre l'exécution effective de l'effacement et la résolution d'éventuels litiges
            relatifs aux dernières opérations.</li>
          <li>Données conversationnelles avec les agents : 180 jours glissants à compter de leur création, sauf demande
            expresse de prolongation par l'utilisateur ou suppression anticipée à sa demande.</li>
          <li>Données techniques (logs de connexion, logs applicatifs) : 12 mois maximum, conformément aux recommandations
            de la CNIL et aux obligations issues du décret n° 2011-219 relatif à la conservation des données.</li>
          <li>Données comptables, fiscales et de facturation : 10 ans à compter de la clôture de l'exercice comptable,
            conformément à l'article L.123-22 du code de commerce.</li>
          <li>Données de cookies analytiques : 13 mois maximum (recommandation CNIL).</li>
          <li>Sauvegardes chiffrées : 90 jours glissants avant rotation et effacement définitif.</li>
        </ul>
      </Section>

      <Section title="8. Vos droits (art. 15 à 22 RGPD)">
        <p>
          Conformément aux dispositions du RGPD et de la loi Informatique et Libertés, vous disposez à tout moment des droits
          suivants, exerçables auprès de notre DPO à l'adresse <strong>sylea.ai.assistance@gmail.com</strong> :
        </p>
        <ul style={{ paddingLeft: '1rem', margin: '0.4rem 0' }}>
          <li><strong>Droit d'accès (art. 15)</strong> : obtenir confirmation que vos données sont traitées et en recevoir une copie.</li>
          <li><strong>Droit de rectification (art. 16)</strong> : faire corriger toute donnée inexacte ou incomplète.</li>
          <li><strong>Droit à l'effacement, dit « droit à l'oubli » (art. 17)</strong> : obtenir l'effacement de vos données dans les conditions prévues par le RGPD.</li>
          <li><strong>Droit à la limitation du traitement (art. 18)</strong> : suspendre temporairement le traitement.</li>
          <li><strong>Droit à la portabilité (art. 20)</strong> : récupérer vos données dans un format structuré (JSON), couramment utilisé et lisible par machine, via la fonctionnalité <em>Exporter mes données</em>.</li>
          <li><strong>Droit d'opposition (art. 21)</strong> : vous opposer pour des motifs tenant à votre situation particulière, sauf motif légitime impérieux ou défense d'un droit en justice.</li>
          <li><strong>Droit de retrait du consentement</strong> : à tout moment, sans affecter la licéité des traitements antérieurs.</li>
          <li><strong>Droit de définir des directives post-mortem</strong> (art. 85 loi 78-17) : indiquer le sort de vos données après votre décès.</li>
        </ul>
        <p>
          Toute demande d'exercice de droits sera traitée dans un délai d'un mois, prorogeable de deux mois en cas de
          complexité ou de multiplicité des demandes. La vérification de l'identité du demandeur pourra être requise par
          tout moyen approprié. Vous disposez par ailleurs du droit d'introduire une réclamation auprès de la Commission
          Nationale de l'Informatique et des Libertés (CNIL — 3 place de Fontenoy, 75007 Paris, www.cnil.fr) si vous estimez
          que le traitement n'est pas conforme à la réglementation.
        </p>
      </Section>

      <Section title="9. Sécurité technique et organisationnelle">
        <p>
          Syléa met en œuvre des mesures techniques et organisationnelles appropriées pour assurer la sécurité du traitement
          (art. 32 RGPD), notamment :
        </p>
        <ul style={{ paddingLeft: '1rem', margin: '0.4rem 0' }}>
          <li>Chiffrement en transit (TLS 1.3) et au repos (AES-256 pour les credentials tiers via algorithme Fernet).</li>
          <li>Authentification par jetons JWT signés (HMAC-SHA256) avec rotation périodique et expiration sous 7 jours.</li>
          <li>Mots de passe stockés exclusivement sous forme de condensats bcrypt (12 tours) — jamais en clair.</li>
          <li>Authentification OAuth multi-fournisseurs (Google, GitHub) avec validation stricte des scopes.</li>
          <li>Isolation stricte multi-utilisateur : toute requête est filtrée par identifiant d'authentification, empêchant tout accès croisé entre comptes.</li>
          <li>Sauvegardes automatiques chiffrées avec rotation 90 jours.</li>
          <li>Journalisation des accès et opérations sensibles, conservée 12 mois.</li>
          <li>Tests d'intrusion et audits de sécurité périodiques.</li>
          <li>Politique stricte de moindre privilège pour les accès administrateurs.</li>
        </ul>
        <p>
          <strong>Avertissement :</strong> Aucun système informatique ne pouvant garantir une sécurité absolue, Syléa met en
          œuvre une <em>obligation de moyens</em> renforcée et non une obligation de résultat en matière de sécurité.
          En cas de violation de données à caractère personnel susceptible d'engendrer un risque pour les droits et libertés
          des personnes concernées, Syléa procédera à la notification à la CNIL dans le délai de 72 heures (art. 33 RGPD)
          et, le cas échéant, à l'information individuelle des personnes concernées (art. 34 RGPD).
        </p>
      </Section>

      <Section title="10. Mineurs">
        <p>
          Le Service est strictement réservé aux personnes âgées de 15 ans révolus, conformément à l'article 8 du RGPD et
          à l'article 7-1 de la loi 78-17 modifiée par l'ordonnance n° 2018-1125. L'inscription d'un mineur de moins de
          15 ans est interdite. Pour les mineurs âgés de 15 à 18 ans, l'utilisation du Service requiert l'autorisation
          conjointe des titulaires de l'autorité parentale.
        </p>
        <p>
          Syléa ne procède à aucune vérification automatique de l'âge réel des utilisateurs. La déclaration d'âge effectuée
          lors de l'inscription est réputée exacte et engage la responsabilité exclusive du déclarant ou, le cas échéant,
          de ses représentants légaux. Toute fausse déclaration d'âge constituera une violation des CGU justifiant la
          résiliation immédiate du compte sans préavis ni indemnité.
        </p>
      </Section>

      <Section title="11. Cookies et traceurs">
        <p>
          L'utilisation du Service implique le dépôt de différentes catégories de cookies et traceurs sur votre terminal,
          conformément à la directive 2002/58/CE (ePrivacy) et à la recommandation cookies de la CNIL du 17 septembre 2020 :
        </p>
        <ul style={{ paddingLeft: '1rem', margin: '0.4rem 0' }}>
          <li><strong>Cookies strictement nécessaires</strong> : authentification (jeton JWT), préférences linguistiques, état de session. Dépôt sans consentement préalable conformément à l'exception de l'article 82 alinéa 2 de la loi 78-17.</li>
          <li><strong>Cookies analytiques</strong> : mesure d'audience, statistiques d'usage anonymisées. Dépôt sur consentement explicite.</li>
          <li><strong>Cookies de personnalisation</strong> : préférences utilisateur, adaptation de l'interface. Dépôt sur consentement explicite.</li>
        </ul>
        <p>
          Aucun cookie publicitaire n'est utilisé. Vous pouvez à tout moment modifier vos préférences via le bandeau de
          consentement accessible en pied de page ou directement via les paramètres de votre navigateur. Le refus des
          cookies non strictement nécessaires n'affecte pas la fourniture du Service mais peut réduire la qualité de
          certaines fonctionnalités de personnalisation.
        </p>
      </Section>

      <Section title="12. Décisions automatisées et profilage">
        <p>
          Le Service utilise des algorithmes d'intelligence artificielle pour produire des analyses, recommandations et
          calculs de probabilité de réussite. Ces traitements ne constituent pas, au sens de l'article 22 du RGPD, des
          décisions automatisées produisant des effets juridiques ou affectant significativement la personne concernée :
          les analyses fournies par le Service sont des <em>aides à la décision</em>, non des décisions par elles-mêmes.
          L'utilisateur conserve à tout moment la maîtrise pleine et entière de ses choix.
        </p>
        <p>
          Aucune décision juridique, médicale, financière, professionnelle ou personnelle ne saurait être valablement prise
          sur la seule base des recommandations produites par le Service. L'utilisateur reconnaît que les analyses sont
          fournies à titre purement informatif et indicatif, et qu'il lui appartient de consulter, le cas échéant, des
          professionnels qualifiés (médecin, avocat, conseiller financier, etc.) avant toute décision substantielle.
        </p>
      </Section>

      <Section title="13. Sources des données">
        <p>
          L'intégralité des données collectées proviennent directement de l'utilisateur lui-même, à l'exception des données
          suivantes obtenues auprès de tiers : (i) données météorologiques (Open-Meteo, sur la base de la géolocalisation
          approximative ville), (ii) informations de profil fournies par les fournisseurs OAuth (Google, GitHub) lors de
          l'authentification par leur intermédiaire, dans la limite des scopes acceptés par l'utilisateur.
        </p>
      </Section>

      <Section title="14. Modifications de la politique">
        <p>
          La présente Politique peut être modifiée à tout moment afin de tenir compte de l'évolution réglementaire,
          jurisprudentielle, technique ou opérationnelle. Toute modification substantielle sera portée à la connaissance
          des utilisateurs par notification dans l'application et/ou par envoi d'un courrier électronique, au moins 15 jours
          avant son entrée en vigueur. La poursuite de l'utilisation du Service au-delà de cette date vaudra acceptation
          tacite des nouvelles dispositions. L'utilisateur ayant accepté la Politique demeure libre de cesser d'utiliser
          le Service à tout moment s'il n'accepte pas les modifications.
        </p>
      </Section>

      <Section title="15. Loi applicable et juridiction">
        <p>
          La présente Politique est soumise à la loi française. Tout litige relatif à son interprétation, son exécution ou
          sa validité relèvera de la compétence exclusive des juridictions du ressort de la Cour d'appel de Paris, sous
          réserve des règles impératives applicables aux consommateurs (art. R.631-3 du code de la consommation pour les
          litiges transfrontaliers intra-UE). Aucune disposition de la présente Politique ne saurait priver le consommateur
          du bénéfice des dispositions impératives de la loi du pays dans lequel il a sa résidence habituelle.
        </p>
      </Section>

      <Section title="16. Contact et support">
        <p>
          Pour toute question, demande d'exercice de droits ou réclamation : <strong>sylea.ai.assistance@gmail.com</strong>.
          Une page dédiée d'assistance et de résolution des incidents est également accessible à l'adresse
          <Link to="/support" style={{ color: 'var(--accent-violet-light)', marginLeft: 4 }}>/support</Link>, couvrant
          l'intégralité des problèmes techniques susceptibles d'être rencontrés et leur résolution étape par étape.
        </p>
      </Section>

      <div style={{ textAlign: 'center', marginTop: '1.25rem' }}>
        <Link to="/" style={{ color: 'var(--text-muted)', fontSize: '0.72rem', textDecoration: 'none' }}>
          ← Retour à l'accueil
        </Link>
      </div>
    </div>
  )
}

export { PrivacyPolicyPage }
