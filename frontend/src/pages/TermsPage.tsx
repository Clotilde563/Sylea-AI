// Conditions Générales d'Utilisation — Syléa.AI (réécriture 2026-05-17, texte dense + dédouanements max)

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

export default function TermsPage() {
  return (
    <div className="container" style={{ maxWidth: 820, margin: '0 auto', padding: '1.5rem 1.25rem 3rem' }}>
      <div style={{ textAlign: 'center', marginBottom: '1.5rem' }}>
        <div style={{ fontSize: '1.7rem', marginBottom: '0.4rem' }}>&#x1F4DC;</div>
        <h1 style={{ fontSize: '1.35rem', fontWeight: 700, color: 'var(--text-primary)', margin: '0 0 0.3rem' }}>
          Conditions Générales d'Utilisation
        </h1>
        <p style={{ color: 'var(--text-muted)', fontSize: '0.7rem', margin: 0 }}>
          Version 3.0 · Dernière mise à jour : 17 mai 2026 · Document contractuel liant Syléa.AI à l'utilisateur
        </p>
      </div>

      <Section title="Préambule — Importance et portée du présent contrat" defaultOpen>
        <p>
          Les présentes Conditions Générales d'Utilisation (« CGU ») régissent, de manière exclusive et impérative, les
          relations contractuelles entre Syléa.AI SAS (« Syléa », « nous », « l'Éditeur »), société par actions simplifiée
          immatriculée en cours d'enregistrement au RCS de Paris, et toute personne physique majeure ou émancipée
          (« vous », « l'Utilisateur ») accédant aux services proposés via la plateforme web sylea-ai.vercel.app, le
          logiciel desktop, l'application mobile et tout service connexe ou successeur (ensemble, le « Service »).
        </p>
        <p>
          <strong>L'utilisation du Service implique l'acceptation pleine, entière et sans réserve des présentes CGU.</strong>
          Si l'Utilisateur n'accepte pas une ou plusieurs des dispositions des présentes, il doit immédiatement renoncer
          à utiliser le Service et procéder à la clôture de son compte. Aucune utilisation partielle ne saurait être
          considérée comme conforme.
        </p>
        <p>
          Syléa attire expressément l'attention de l'Utilisateur sur la nature et l'importance de certaines clauses
          ci-après, notamment celles relatives à la nature de l'obligation de moyens (et non de résultat), aux limitations
          et exclusions de responsabilité, à la résiliation, et au droit applicable. Il appartient à l'Utilisateur de
          prendre connaissance de l'intégralité du présent document avant toute utilisation.
        </p>
      </Section>

      <Section title="1. Définitions">
        <p>
          Aux fins des présentes CGU, les termes suivants auront la signification qui leur est attribuée ci-après, qu'ils
          soient employés au singulier ou au pluriel :
        </p>
        <ul style={{ paddingLeft: '1rem', margin: '0.4rem 0' }}>
          <li><strong>Service</strong> : ensemble des fonctionnalités logicielles, applicatives et informationnelles fournies par Syléa, en ce compris l'application web, le client desktop Tauri, l'application mobile (à venir), et tout module additionnel.</li>
          <li><strong>Compte</strong> : espace personnel sécurisé créé par l'Utilisateur pour accéder au Service.</li>
          <li><strong>Contenu Utilisateur</strong> : toute donnée, information, texte, image, fichier, audio ou autre élément que l'Utilisateur soumet au Service.</li>
          <li><strong>Contenu Syléa</strong> : interface, code source, algorithmes, modèles, textes, graphismes, structure et toute autre composante propriété de Syléa.</li>
          <li><strong>Analyse</strong> : tout traitement automatisé produit par les algorithmes d'intelligence artificielle (recommandations, calculs de probabilité, suggestions, etc.).</li>
          <li><strong>Plan</strong> : niveau d'abonnement souscrit par l'Utilisateur (Gratuit, Avancé, Team, Enterprise).</li>
        </ul>
      </Section>

      <Section title="2. Inscription et compte utilisateur">
        <p>
          L'accès aux fonctionnalités du Service requiert la création d'un compte personnel. L'inscription implique :
          la fourniture d'informations exactes, à jour et complètes ; le choix d'un mot de passe robuste (12 caractères
          minimum recommandés, incluant majuscules, minuscules, chiffres et caractères spéciaux) ; la vérification de
          l'adresse électronique par code à usage unique transmis par voie automatique. Toute fausse déclaration entraînera
          la résiliation immédiate du compte sans préavis ni remboursement.
        </p>
        <p>
          L'Utilisateur est seul responsable de la confidentialité de ses identifiants de connexion. Toute opération
          effectuée depuis son compte est réputée effectuée par lui-même, sauf preuve contraire qu'il lui appartiendra
          d'apporter. L'Utilisateur s'engage à notifier sans délai à Syléa toute utilisation non autorisée de son compte
          ou toute atteinte à la sécurité de celui-ci.
        </p>
        <p>
          L'inscription est strictement réservée aux personnes physiques âgées de 15 ans révolus disposant de la capacité
          juridique de contracter. Pour les mineurs âgés de 15 à 18 ans, une autorisation conjointe des titulaires de
          l'autorité parentale est requise. Toute personne morale souhaitant utiliser le Service doit souscrire un plan
          adapté (Team, Enterprise) après contact préalable avec Syléa.
        </p>
      </Section>

      <Section title="3. Description du service et fonctionnalités">
        <p>
          Le Service propose, à titre principal, les fonctionnalités suivantes : (i) un moteur déterministe de calcul de
          probabilité de réussite d'un objectif de vie déclaré ; (ii) des analyses générées par intelligence artificielle
          (modèles Claude d'Anthropic, GPT d'OpenAI ou équivalents) portant sur des dilemmes, événements et choix ;
          (iii) trois agents conversationnels intelligents (Agent Syléa 1 — Compagnon, Agent Syléa 2 — Assistant exécutant,
          Agent Syléa 3 — Agent autonome avancé) ; (iv) des outils d'analyse statistique et de suivi temporel des objectifs ;
          (v) des fonctionnalités collaboratives (workspaces partagés, mentorat, défis communautaires) ; (vi) des
          intégrations tierces optionnelles (Google Calendar, Gmail, Drive, GitHub, Notion, Slack, etc.).
        </p>
        <p>
          Syléa se réserve la possibilité, à tout moment et sans préavis, de modifier, suspendre, supprimer ou ajouter
          des fonctionnalités, dans le cadre de l'évolution normale et raisonnable du Service. Aucune fonctionnalité
          particulière n'est garantie de manière pérenne, et l'Utilisateur ne saurait fonder de droits acquis sur la
          présence d'une fonctionnalité à un instant donné.
        </p>
      </Section>

      <Section title="4. Nature de l'obligation — OBLIGATION DE MOYENS" defaultOpen>
        <p style={{ background: 'rgba(255, 200, 50, 0.06)', border: '1px solid rgba(255, 200, 50, 0.2)', padding: '0.6rem', borderRadius: 6 }}>
          <strong>AVERTISSEMENT IMPORTANT.</strong> Syléa souscrit à l'égard de l'Utilisateur une <strong>OBLIGATION DE
          MOYENS</strong> et <strong>EN AUCUN CAS UNE OBLIGATION DE RÉSULTAT</strong>. Cette qualification est essentielle
          et déterminante du consentement des parties au présent contrat.
        </p>
        <p>
          Syléa s'engage à mettre en œuvre tous les moyens raisonnables, conformes à l'état de l'art et aux pratiques
          usuelles du secteur, pour fournir un Service de qualité, fiable et utile. Toutefois, Syléa ne garantit ni ne
          peut garantir :
        </p>
        <ul style={{ paddingLeft: '1rem', margin: '0.4rem 0' }}>
          <li>l'exactitude, la pertinence, la fiabilité ou l'opportunité des Analyses, recommandations, suggestions ou
            calculs produits par les algorithmes d'intelligence artificielle, lesquels peuvent comporter des erreurs,
            biais, imprécisions, hallucinations ou résultats inattendus inhérents à la nature même de cette technologie ;</li>
          <li>la réalisation effective des objectifs personnels, professionnels, financiers ou autres déclarés par
            l'Utilisateur, dont la réussite dépend exclusivement de facteurs sur lesquels Syléa n'a aucune maîtrise
            (volonté, capacités, environnement, opportunités, hasard, santé, contexte économique, etc.) ;</li>
          <li>l'absence totale d'interruption, de bug, d'erreur, de latence, d'indisponibilité ou de
            dysfonctionnement du Service, lesquels peuvent survenir pour des raisons techniques, opérationnelles ou
            indépendantes de la volonté de Syléa ;</li>
          <li>la compatibilité du Service avec tout matériel, logiciel, navigateur ou configuration de l'Utilisateur ;</li>
          <li>la pérennité du Service à long terme, Syléa se réservant le droit de cesser l'exploitation à tout moment
            sous réserve d'un préavis raisonnable et de la mise à disposition d'un export des données conformément au RGPD ;</li>
          <li>l'absence d'interruption causée par les prestataires tiers (Anthropic, OpenAI, hébergeurs, etc.) sur lesquels
            Syléa n'exerce aucune autorité hiérarchique ni de contrôle technique direct.</li>
        </ul>
        <p>
          L'Utilisateur reconnaît expressément avoir été informé de la nature non-déterministe des résultats produits par
          les modèles d'intelligence artificielle et accepte d'en supporter les conséquences en toute connaissance de cause.
          Toute Analyse fournie par le Service constitue une <em>aide à la décision</em> et n'engage en aucun cas Syléa
          quant à sa pertinence pour la situation spécifique de l'Utilisateur. Aucun professionnel qualifié (médecin,
          avocat, expert-comptable, conseiller financier, psychologue, etc.) ne saurait être substitué par le Service.
        </p>
      </Section>

      <Section title="5. Limitations et exclusions de responsabilité">
        <p>
          Dans toute la mesure permise par la loi applicable, et sans préjudice des dispositions impératives protectrices
          du consommateur, la responsabilité de Syléa est strictement limitée selon les modalités suivantes :
        </p>
        <ul style={{ paddingLeft: '1rem', margin: '0.4rem 0' }}>
          <li><strong>Exclusion des dommages indirects.</strong> Syléa ne saurait être tenue responsable d'aucun dommage indirect, immatériel, consécutif ou imprévisible résultant de l'utilisation ou de l'impossibilité d'utiliser le Service, notamment : perte de chance, perte de revenu, perte de gain, manque à gagner, perte de clientèle, perte d'opportunité, perte de données, atteinte à la réputation, préjudice moral.</li>
          <li><strong>Exclusion des décisions de l'Utilisateur.</strong> Syléa ne saurait en aucun cas être tenue responsable des décisions personnelles, professionnelles, financières, médicales, juridiques, familiales ou sentimentales prises par l'Utilisateur, fussent-elles inspirées en tout ou partie par les Analyses produites par le Service. L'Utilisateur demeure seul juge de l'opportunité et de la pertinence de ses propres décisions, dont il assume la responsabilité exclusive.</li>
          <li><strong>Exclusion des contenus tiers.</strong> Syléa décline toute responsabilité quant aux contenus, services, sites et applications de tiers accessibles depuis le Service (liens externes, intégrations OAuth, recherches web). L'Utilisateur agit à ses propres risques et périls lorsqu'il interagit avec ces tiers.</li>
          <li><strong>Plafond de responsabilité.</strong> Sauf disposition impérative contraire, et en cas de manquement avéré de Syléa entraînant un préjudice direct, la responsabilité totale cumulée de Syléa, tous chefs de préjudice confondus, ne saurait excéder un montant équivalent aux sommes effectivement versées par l'Utilisateur au titre de son abonnement durant les douze (12) mois précédant immédiatement le fait générateur, dans la limite absolue de cent (100) euros.</li>
          <li><strong>Force majeure.</strong> Syléa ne saurait être tenue responsable de tout manquement résultant d'un événement de force majeure au sens de l'article 1218 du code civil, en ce compris notamment : pandémies, guerres, troubles civils, catastrophes naturelles, défaillance d'un fournisseur d'accès Internet, défaillance majeure d'un prestataire tiers (Anthropic, OpenAI, hébergeur), cyberattaques de grande ampleur, décisions gouvernementales ou réglementaires imposant des restrictions ou interruptions.</li>
        </ul>
        <p style={{ background: 'rgba(255, 100, 100, 0.06)', border: '1px solid rgba(255, 100, 100, 0.2)', padding: '0.6rem', borderRadius: 6 }}>
          <strong>AVERTISSEMENT SANTÉ MENTALE ET PHYSIQUE.</strong> Le Service n'est en aucun cas un substitut à un avis,
          diagnostic, traitement ou conseil médical, psychologique, psychiatrique ou paramédical. Toute personne en situation
          de détresse psychologique, idéation suicidaire, addiction, trouble mental, problème de santé ou difficulté
          relationnelle doit consulter sans délai un professionnel de santé qualifié ou contacter les services d'urgence
          (15 SAMU, 112 urgences européennes, 3114 numéro national de prévention du suicide en France). Syléa ne saurait
          en aucune manière être tenue responsable des conséquences d'une utilisation inadaptée du Service par une personne
          fragile ou vulnérable.
        </p>
        <p style={{ background: 'rgba(255, 100, 100, 0.06)', border: '1px solid rgba(255, 100, 100, 0.2)', padding: '0.6rem', borderRadius: 6 }}>
          <strong>AVERTISSEMENT FINANCIER.</strong> Aucune recommandation produite par le Service ne constitue un conseil
          en investissement, une recommandation financière personnalisée au sens du Règlement (UE) 2019/2088, ni une
          incitation à acquérir ou céder un instrument financier. L'Utilisateur est invité à consulter un conseiller en
          investissements financiers (CIF) agréé avant toute décision d'investissement.
        </p>
        <p style={{ background: 'rgba(255, 100, 100, 0.06)', border: '1px solid rgba(255, 100, 100, 0.2)', padding: '0.6rem', borderRadius: 6 }}>
          <strong>AVERTISSEMENT JURIDIQUE.</strong> Aucune information délivrée par le Service ne constitue un conseil
          juridique au sens des articles 54 et suivants de la loi n° 71-1130 du 31 décembre 1971. L'Utilisateur doit
          consulter un avocat avant toute décision aux conséquences juridiques significatives.
        </p>
      </Section>

      <Section title="6. Obligations de l'Utilisateur — usages prohibés">
        <p>
          L'Utilisateur s'engage expressément à ne pas utiliser le Service, directement ou indirectement, dans les
          conditions suivantes, qui constituent des manquements graves justifiant la résiliation immédiate du compte sans
          préavis ni remboursement :
        </p>
        <ul style={{ paddingLeft: '1rem', margin: '0.4rem 0' }}>
          <li>Activités illégales, frauduleuses ou contraires à l'ordre public ou aux bonnes mœurs.</li>
          <li>Atteinte aux droits de propriété intellectuelle de tiers (contrefaçon, plagiat, distribution non autorisée).</li>
          <li>Diffamation, injure, propos racistes, sexistes, homophobes, antisémites, négationnistes, apologie du terrorisme.</li>
          <li>Tentative d'intrusion, de rétro-ingénierie, de désassemblage ou de contournement des protections techniques.</li>
          <li>Utilisation automatisée du Service (scripts, bots, scrapers) en dehors du cadre prévu par l'API officielle, sauf autorisation préalable expresse écrite de Syléa.</li>
          <li>Création de comptes multiples, fictifs ou usurpés ; partage de compte avec des tiers en dehors du cadre prévu par le plan Team ou Enterprise.</li>
          <li>Revente, sous-licence, location ou redistribution non autorisée du Service ou de ses composantes.</li>
          <li>Saturation volontaire du Service (déni de service, requêtes massives) ou contournement des limitations techniques.</li>
          <li>Toute action portant atteinte à la sécurité, à l'intégrité ou à la disponibilité du Service.</li>
          <li>Production, diffusion, stockage ou transmission, via le Service, de contenus à caractère pédopornographique, terroriste, incitant à la haine ou à la violence.</li>
        </ul>
        <p>
          Syléa se réserve le droit, à sa seule appréciation et sans avoir à se justifier, de suspendre temporairement ou
          de résilier définitivement le compte de tout Utilisateur soupçonné de manquement, dans le strict respect des
          dispositions impératives applicables. Toute mesure prise par Syléa sera notifiée à l'Utilisateur par voie
          électronique, lequel disposera de la possibilité de faire valoir ses observations.
        </p>
      </Section>

      <Section title="7. Propriété intellectuelle">
        <p>
          Le Contenu Syléa (interface, code source, algorithmes, modèles propriétaires, charte graphique, textes, logo,
          dénomination « Syléa.AI », architecture logicielle, ensemble du back-office) est la propriété exclusive de Syléa.AI
          SAS ou de ses concédants. Toute reproduction, représentation, modification, adaptation, traduction, distribution
          ou exploitation, totale ou partielle, sous quelque forme et par quelque moyen que ce soit, sans l'autorisation
          écrite préalable de Syléa, est strictement interdite et constituerait une contrefaçon sanctionnée par les
          articles L.335-2 et suivants du code de la propriété intellectuelle (jusqu'à 3 ans d'emprisonnement et 300 000 €
          d'amende).
        </p>
        <p>
          L'Utilisateur demeure titulaire de tous ses droits sur le Contenu Utilisateur qu'il soumet au Service. Il concède
          toutefois à Syléa, par les présentes, une licence mondiale, non-exclusive, gratuite, sous-licenciable, pour la
          durée de la conservation des données, aux fins strictes de l'exécution du Service (stockage, traitement, analyse,
          restitution). Cette licence prend fin de plein droit lors de la suppression effective des données.
        </p>
        <p>
          Concernant les Analyses générées par le Service, l'Utilisateur en dispose librement pour son usage personnel.
          Syléa se réserve toutefois la possibilité d'utiliser, sous forme strictement anonymisée et agrégée, les schémas
          d'usage afin d'améliorer le Service. Aucune Analyse ne saurait être revendiquée comme exclusive ou originale au
          sens du droit d'auteur, s'agissant de productions algorithmiques non-déterministes.
        </p>
      </Section>

      <Section title="8. Abonnement, prix, paiement et résiliation">
        <p>
          Le Service est proposé selon plusieurs plans d'abonnement (Gratuit, Avancé, Team, Enterprise) dont les
          fonctionnalités, limitations d'usage et tarifs sont précisés sur la page <Link to="/quotas" style={{ color: 'var(--accent-violet-light)' }}>Tarifs</Link>
          du Service. Les prix indiqués s'entendent toutes taxes comprises (TTC) pour les particuliers résidant dans
          l'Union européenne, hors taxes (HT) pour les professionnels.
        </p>
        <p>
          Le paiement est effectué via le prestataire Stripe, certifié PCI-DSS niveau 1. L'abonnement est renouvelé
          automatiquement à terme échu, sauf résiliation préalable opérée par l'Utilisateur depuis son espace personnel
          au moins 24 heures avant l'échéance. Le défaut de paiement entraînera la suspension immédiate de l'accès aux
          fonctionnalités premium, sans préjudice du droit pour Syléa d'engager toute action en recouvrement.
        </p>
        <p>
          <strong>Droit de rétractation (consommateur).</strong> Conformément à l'article L.221-28 1° du code de la
          consommation, le droit de rétractation ne s'applique pas aux contrats portant sur la fourniture d'un contenu
          numérique non fourni sur support matériel dont l'exécution a commencé après accord préalable exprès du
          consommateur et renoncement exprès à son droit de rétractation. En souscrivant à un plan payant et en demandant
          un accès immédiat aux fonctionnalités, le consommateur reconnaît expressément renoncer à son droit de rétractation
          de 14 jours.
        </p>
        <p>
          La résiliation par l'Utilisateur peut intervenir à tout moment depuis l'espace personnel, sans préavis ni
          indemnité. Elle prend effet à l'échéance de la période d'abonnement en cours, sans remboursement au prorata
          des jours non consommés sauf disposition impérative contraire. Syléa se réserve la possibilité de résilier le
          compte d'un Utilisateur en cas de manquement grave aux présentes CGU, après notification et délai raisonnable
          de mise en conformité lorsque celui-ci est compatible avec la nature du manquement.
        </p>
      </Section>

      <Section title="9. Données à caractère personnel et confidentialité">
        <p>
          Le traitement des données à caractère personnel est régi par la <Link to="/privacy" style={{ color: 'var(--accent-violet-light)' }}>Politique de confidentialité</Link>,
          laquelle fait partie intégrante des présentes CGU. L'Utilisateur reconnaît avoir pris connaissance de cette
          Politique avant toute inscription et y consentir expressément.
        </p>
        <p>
          Syléa met en œuvre les mesures techniques et organisationnelles appropriées pour assurer la confidentialité,
          l'intégrité et la disponibilité des données traitées, conformément à son obligation de moyens en matière de
          sécurité (art. 32 RGPD). Aucune obligation de résultat ne saurait toutefois être souscrite à ce titre, l'état
          de l'art de la sécurité informatique évoluant en permanence et aucun système n'étant inviolable.
        </p>
      </Section>

      <Section title="10. Disponibilité, maintenance et niveaux de service">
        <p>
          Syléa met en œuvre les moyens raisonnables pour assurer une disponibilité de 99 % du Service sur base annuelle,
          étant précisé que cet objectif constitue un engagement de moyens et non un engagement de résultat. Aucun crédit,
          remboursement ou pénalité n'est dû en cas d'indisponibilité du Service, sauf souscription d'un plan Enterprise
          assorti d'un accord de niveau de service (SLA) formalisé.
        </p>
        <p>
          Des opérations de maintenance planifiée pourront intervenir, prioritairement durant les heures creuses, après
          notification raisonnable par voie électronique ou affichage dans l'application. Les interruptions non planifiées
          consécutives à un incident technique seront résolues dans les meilleurs délais en fonction de leur gravité.
        </p>
      </Section>

      <Section title="11. Évolution du Service et des CGU">
        <p>
          Syléa peut modifier le Service et les présentes CGU à tout moment afin de tenir compte de l'évolution technique,
          réglementaire, commerciale ou opérationnelle. Toute modification substantielle des CGU sera portée à la connaissance
          de l'Utilisateur par notification dans l'application et/ou par envoi d'un courrier électronique au moins 15 jours
          avant son entrée en vigueur. La poursuite de l'utilisation au-delà de cette date emporte acceptation tacite des
          nouvelles dispositions. L'Utilisateur ne souhaitant pas accepter les modifications peut résilier son compte sans
          frais avant l'entrée en vigueur.
        </p>
      </Section>

      <Section title="12. Médiation et règlement des litiges">
        <p>
          En cas de différend relatif à l'exécution, l'interprétation ou la validité du présent contrat, les parties
          s'efforceront de résoudre le litige à l'amiable par voie de négociation directe, dans un délai de 30 jours
          courant à compter de la première notification écrite par l'une des parties.
        </p>
        <p>
          À défaut de résolution amiable, et pour les consommateurs résidant dans l'Union européenne, l'Utilisateur dispose
          de la faculté de recourir gratuitement à la médiation de la consommation conformément aux articles L.611-1 et
          suivants du code de la consommation. La plateforme européenne de règlement en ligne des litiges est accessible à
          l'adresse <a href="https://ec.europa.eu/consumers/odr" target="_blank" rel="noopener noreferrer" style={{ color: 'var(--accent-violet-light)' }}>ec.europa.eu/consumers/odr</a>.
        </p>
      </Section>

      <Section title="13. Loi applicable et juridiction compétente">
        <p>
          Les présentes CGU sont régies par le droit français à l'exclusion de tout autre droit. Tout litige qui ne pourrait
          être résolu à l'amiable sera soumis à la compétence exclusive des tribunaux du ressort de la Cour d'appel de Paris,
          sous réserve des règles impératives en matière de consommation (art. R.631-3 du code de la consommation), des
          dispositions du règlement UE Bruxelles I bis pour les litiges transfrontaliers, et de la convention de Rome I sur
          la loi applicable aux obligations contractuelles.
        </p>
      </Section>

      <Section title="14. Divisibilité, intégralité, renonciation">
        <p>
          Si l'une quelconque des stipulations des présentes CGU était déclarée nulle, inopposable ou inapplicable par
          décision juridictionnelle définitive, les autres stipulations conserveraient leur pleine force et effet. Les
          présentes CGU, ensemble la Politique de confidentialité, la Charte cookies et tout document contractuel
          spécifique au plan souscrit, constituent l'intégralité de l'accord entre les parties.
        </p>
        <p>
          Le fait pour Syléa de ne pas se prévaloir d'une stipulation des présentes ne saurait s'interpréter comme une
          renonciation à s'en prévaloir ultérieurement. Aucune tolérance ne saurait créer de droit acquis pour l'Utilisateur.
        </p>
      </Section>

      <Section title="15. Contact, support et signalement">
        <p>
          Toute question, demande, réclamation ou signalement peut être adressé à : <strong>sylea.ai.assistance@gmail.com</strong>.
          Une page dédiée d'assistance et de résolution des incidents est accessible à l'adresse
          <Link to="/support" style={{ color: 'var(--accent-violet-light)', marginLeft: 4 }}>/support</Link>, couvrant
          l'intégralité des problèmes techniques susceptibles d'être rencontrés et leur résolution pas-à-pas. En matière
          de protection des données, le Délégué à la Protection des Données (DPO) peut être contacté à la même adresse
          électronique.
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

export { TermsPage }
