// LandingPage — page d'introduction publique de Syléa.AI
//
// Objectif : convertir un clic en "Prendre en main mon objectif de vie".
// Style : dark + gradient signature Syléa (cyan -> bleu -> violet), très
// interactif (glow qui suit la souris, jauge de probabilité animée, démo au
// curseur en direct, reveal au scroll, FAQ accordéon). 100% autonome (aucune
// dépendance externe) -> performant et facile à maintenir.
//
// Le CTA central + le header "Se connecter" pointent vers /login.

import { useEffect, useRef, useState } from 'react'

export default function LandingPage() {
  // Ouvre la page de connexion dans un NOUVEL onglet (demande produit) —
  // noopener/noreferrer pour la sécurité (pas d'accès window.opener).
  const goLogin = () => window.open('/login', '_blank', 'noopener,noreferrer')

  // ── Glow qui suit la souris (effet "tech vivant") ─────────────────────────
  const rootRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const el = rootRef.current
    if (!el) return
    const onMove = (e: MouseEvent) => {
      el.style.setProperty('--mx', `${e.clientX}px`)
      el.style.setProperty('--my', `${e.clientY}px`)
    }
    window.addEventListener('mousemove', onMove)
    return () => window.removeEventListener('mousemove', onMove)
  }, [])

  // ── Reveal au scroll ──────────────────────────────────────────────────────
  useEffect(() => {
    const els = Array.from(document.querySelectorAll<HTMLElement>('.lp-reveal'))
    const io = new IntersectionObserver(
      (entries) => {
        entries.forEach((en) => {
          if (en.isIntersecting) {
            en.target.classList.add('lp-in')
            io.unobserve(en.target)
          }
        })
      },
      { threshold: 0.12 },
    )
    els.forEach((el) => io.observe(el))
    return () => io.disconnect()
  }, [])

  // ── Jauge de probabilité animée (compteur qui monte) ─────────────────────
  const TARGET = 87
  const [gauge, setGauge] = useState(0)
  useEffect(() => {
    let raf = 0
    const t0 = performance.now()
    const dur = 1600
    const tick = (now: number) => {
      const p = Math.min(1, (now - t0) / dur)
      const eased = 1 - Math.pow(1 - p, 3) // easeOutCubic
      setGauge(Math.round(eased * TARGET))
      if (p < 1) raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [])
  const R = 78
  const C = 2 * Math.PI * R
  const dash = C * (gauge / 100)

  // ── Démo interactive : heures/jour -> probabilité + temps estimé ─────────
  const [heures, setHeures] = useState(2)
  const probaDemo = Math.round(Math.min(96, 38 + heures * 7.2))
  const joursDemo = Math.round(1460 / (heures + 0.6)) // illustratif
  const tempsDemo = (() => {
    const a = Math.floor(joursDemo / 365)
    const m = Math.round((joursDemo % 365) / 30)
    if (a >= 1) return `${a} an${a > 1 ? 's' : ''}${m > 0 ? ` ${m} mois` : ''}`
    return `${m} mois`
  })()

  // ── FAQ accordéon ─────────────────────────────────────────────────────────
  const [faqOpen, setFaqOpen] = useState<number | null>(0)
  const faq = [
    {
      q: 'Comment Syléa peut "calculer" un choix de vie ?',
      r: "Tu décris ta situation et ton objectif. Syléa croise ta préparation, ton temps disponible et l'échéance pour estimer ta probabilité d'y arriver et le temps que ça prendra. Ce n'est pas une boule de cristal : c'est une trajectoire claire, mise à jour à chaque décision.",
    },
    {
      q: "C'est fait pour qui ?",
      r: "Pour celles et ceux qui ont le plus de grands choix à faire et le moins d'outils pour les faire : étudiants en fac, en prépa, jeunes actifs. Orientation, école, partir ou rester, se lancer ou attendre.",
    },
    {
      q: 'Mes données sont-elles privées ?',
      r: 'Oui. Tes décisions et ton profil sont à toi. Syléa est conçue dans le respect du RGPD, avec un contrôle clair sur tes informations.',
    },
    {
      q: "Combien ça coûte pour commencer ?",
      r: 'Tu peux prendre en main ton premier objectif gratuitement. Tu montes en gamme seulement si tu veux aller plus loin.',
    },
  ]

  return (
    <div className="lp-root" ref={rootRef}>
      <style>{CSS}</style>

      {/* Fonds animés */}
      <div className="lp-aurora" aria-hidden />
      <div className="lp-grid" aria-hidden />
      <div className="lp-cursor-glow" aria-hidden />

      {/* ── Header ─────────────────────────────────────────────────────────── */}
      <header className="lp-header">
        <a href="#top" className="lp-logo">
          <span className="lp-logo-text">SYLÉA<span className="lp-logo-ai">.AI</span></span>
        </a>
        <nav className="lp-nav">
          <a href="#concept">Concept</a>
          <a href="#etapes">Comment ça marche</a>
          <a href="#features">Fonctionnalités</a>
          <a href="#faq">FAQ</a>
        </nav>
        <div className="lp-header-cta">
          <button className="lp-link-btn" onClick={goLogin}>Se connecter</button>
          <button className="lp-btn lp-btn-mini" onClick={goLogin}>Commencer</button>
        </div>
      </header>

      {/* ── Hero ───────────────────────────────────────────────────────────── */}
      <section className="lp-hero" id="top">
        <div className="lp-hero-copy lp-reveal">
          <span className="lp-badge"><span className="lp-dot" /> L'assistant de décision de vie · propulsé par l'IA</span>
          <h1 className="lp-h1">
            Décide de ta vie.<br />
            <span className="lp-grad">Plus au feeling — avec des chiffres.</span>
          </h1>
          <p className="lp-sub">
            Syléa transforme tes grands choix — études, carrière, relations — en
            <strong> probabilité d'atteindre ton objectif</strong> et en
            <strong> temps estimé</strong>. Tu vois enfin où tu vas, et chaque
            décision te montre si tu t'en rapproches.
          </p>
          <div className="lp-cta-row">
            <button className="lp-btn lp-btn-hero" onClick={goLogin}>
              Prendre en main mon objectif de vie
              <span className="lp-arrow">→</span>
            </button>
            <a className="lp-btn-ghost" href="#etapes">Voir comment ça marche</a>
          </div>
          <div className="lp-trust">
            <span>✦ Pensé pour les étudiants</span>
            <span>✦ Privé & RGPD</span>
            <span>✦ Web + Desktop</span>
          </div>
        </div>

        {/* Jauge interactive */}
        <div className="lp-hero-visual lp-reveal">
          <div className="lp-card lp-gauge-card">
            <div className="lp-gauge-label">Probabilité d'atteindre ton objectif</div>
            <div className="lp-gauge-wrap">
              <svg viewBox="0 0 180 180" className="lp-gauge-svg">
                <defs>
                  <linearGradient id="lpGaugeGrad" x1="0" y1="0" x2="1" y2="1">
                    <stop offset="0%" stopColor="#22d3ee" />
                    <stop offset="50%" stopColor="#3b82f6" />
                    <stop offset="100%" stopColor="#8b5cf6" />
                  </linearGradient>
                </defs>
                <circle cx="90" cy="90" r={R} className="lp-gauge-track" />
                <circle
                  cx="90" cy="90" r={R}
                  className="lp-gauge-fill"
                  stroke="url(#lpGaugeGrad)"
                  strokeDasharray={`${dash} ${C}`}
                  transform="rotate(-90 90 90)"
                />
              </svg>
              <div className="lp-gauge-center">
                <div className="lp-gauge-num">{gauge}<span>%</span></div>
              </div>
            </div>
            <div className="lp-gauge-time">≈ 2 ans 4 mois restants</div>
            <div className="lp-gauge-foot">
              <span className="lp-chip">Objectif : 3 000 €/mois en freelance</span>
            </div>
          </div>
        </div>
      </section>

      {/* ── Concept ────────────────────────────────────────────────────────── */}
      <section className="lp-section" id="concept">
        <div className="lp-reveal lp-center">
          <h2 className="lp-h2">On t'a appris à résoudre des équations.<br /><span className="lp-grad">Personne ne t'a appris à choisir entre deux vies.</span></h2>
          <p className="lp-section-sub">
            Pourtant ce sont 3 ou 4 grands choix qui dessinent toute une vie. Et
            on les prend le dimanche soir, seul, sans aucune donnée. Syléa change ça.
          </p>
        </div>
      </section>

      {/* ── Étapes ─────────────────────────────────────────────────────────── */}
      <section className="lp-section" id="etapes">
        <h2 className="lp-h2 lp-center lp-reveal">Comment ça marche</h2>
        <div className="lp-steps">
          {[
            { n: '01', t: 'Décris ton objectif', d: "Ta situation, ton but, ton échéance. En quelques minutes, guidé par l'IA." },
            { n: '02', t: 'Syléa calcule ta trajectoire', d: 'Probabilité de réussite + temps estimé, découpés en sous-objectifs clairs.' },
            { n: '03', t: 'Chaque décision, mesurée', d: 'Tu tranches un dilemme ? Syléa te montre, chiffres à l\'appui, si tu te rapproches.' },
          ].map((s, i) => (
            <div className="lp-card lp-step lp-reveal" key={i} style={{ transitionDelay: `${i * 90}ms` }}>
              <div className="lp-step-n">{s.n}</div>
              <h3 className="lp-step-t">{s.t}</h3>
              <p className="lp-step-d">{s.d}</p>
            </div>
          ))}
        </div>
      </section>

      {/* ── Démo interactive ───────────────────────────────────────────────── */}
      <section className="lp-section" id="demo">
        <div className="lp-card lp-demo lp-reveal">
          <div className="lp-demo-left">
            <span className="lp-eyebrow">Démo en direct</span>
            <h2 className="lp-h2">Bouge un curseur. Vois ta vie bouger.</h2>
            <p className="lp-section-sub">
              Combien d'heures par jour consacres-tu à ton objectif ? Regarde
              l'impact sur ta probabilité et ton temps estimé, en temps réel.
            </p>
            <label className="lp-slider-label">
              <span>Heures / jour</span>
              <strong>{heures} h</strong>
            </label>
            <input
              type="range" min={1} max={8} step={1} value={heures}
              onChange={(e) => setHeures(Number(e.target.value))}
              className="lp-slider"
              aria-label="Heures par jour consacrées à l'objectif"
            />
            <p className="lp-demo-hint">* estimation illustrative — l'app utilise ton vrai profil</p>
          </div>
          <div className="lp-demo-right">
            <div className="lp-stat">
              <div className="lp-stat-num lp-grad">{probaDemo}%</div>
              <div className="lp-stat-lbl">probabilité d'y arriver</div>
            </div>
            <div className="lp-stat">
              <div className="lp-stat-num lp-grad">{tempsDemo}</div>
              <div className="lp-stat-lbl">temps estimé</div>
            </div>
            <div className="lp-bar"><div className="lp-bar-fill" style={{ width: `${probaDemo}%` }} /></div>
          </div>
        </div>
      </section>

      {/* ── Fonctionnalités / Documentation ────────────────────────────────── */}
      <section className="lp-section" id="features">
        <h2 className="lp-h2 lp-center lp-reveal">Tout pour piloter ta vie, au même endroit</h2>
        <div className="lp-features">
          {[
            { ic: '◈', t: 'Moteur de probabilité', d: 'Une trajectoire chiffrée, déterministe, mise à jour à chaque décision.' },
            { ic: '⚖', t: 'Analyse de dilemme', d: 'Option A vs option B (ou aucune). Syléa te dit laquelle te rapproche le plus.' },
            { ic: '◎', t: 'Sous-objectifs', d: 'Ton grand objectif découpé en étapes concrètes, avec leur temps propre.' },
            { ic: '📈', t: 'Statistiques & historique', d: 'Vois ta progression réelle dans le temps, décision après décision.' },
            { ic: '🤖', t: 'Agents IA', d: 'Un compagnon qui t\'accompagne et agit (email, agenda, notes, tâches).' },
            { ic: '🖥', t: 'Web + Desktop', d: 'Sur ton navigateur, et une app desktop qui agit concrètement pour toi.' },
          ].map((f, i) => (
            <div className="lp-card lp-feature lp-reveal" key={i} style={{ transitionDelay: `${(i % 3) * 80}ms` }}>
              <div className="lp-feature-ic">{f.ic}</div>
              <h3 className="lp-feature-t">{f.t}</h3>
              <p className="lp-feature-d">{f.d}</p>
            </div>
          ))}
        </div>
      </section>

      {/* ── FAQ ────────────────────────────────────────────────────────────── */}
      <section className="lp-section" id="faq">
        <h2 className="lp-h2 lp-center lp-reveal">Questions fréquentes</h2>
        <div className="lp-faq">
          {faq.map((item, i) => (
            <div className="lp-reveal" key={i}>
              <div className={`lp-faq-item ${faqOpen === i ? 'open' : ''}`}>
                <button className="lp-faq-q" onClick={() => setFaqOpen(faqOpen === i ? null : i)}>
                  <span>{item.q}</span>
                  <span className="lp-faq-plus">{faqOpen === i ? '−' : '+'}</span>
                </button>
                <div className="lp-faq-a"><p>{item.r}</p></div>
              </div>
            </div>
          ))}
        </div>
      </section>

      {/* ── CTA final ──────────────────────────────────────────────────────── */}
      <section className="lp-final lp-reveal">
        <h2 className="lp-h2">Ton avenir ne devrait pas être une question de chance.</h2>
        <p className="lp-section-sub">Arrête de subir tes choix. Commence à les piloter.</p>
        <button className="lp-btn lp-btn-hero" onClick={goLogin}>
          Prendre en main mon objectif de vie
          <span className="lp-arrow">→</span>
        </button>
      </section>

      {/* ── Footer ─────────────────────────────────────────────────────────── */}
      <footer className="lp-footer">
        <span className="lp-logo-text" style={{ fontSize: '0.85rem' }}>SYLÉA<span className="lp-logo-ai">.AI</span></span>
        <div className="lp-footer-links">
          <a href="/privacy">Confidentialité</a>
          <a href="/terms">CGU</a>
          <a href="/support">Support &amp; aide</a>
        </div>
      </footer>
    </div>
  )
}

// ── Styles (scopés .lp-*) ────────────────────────────────────────────────────
const CSS = `
.lp-root{position:relative;min-height:100vh;background:#08090c;color:#e6e9ef;
  font-family:'Inter',system-ui,-apple-system,sans-serif;overflow-x:hidden;
  --mx:50vw;--my:0px;}
.lp-root *{box-sizing:border-box;}

/* Fonds */
.lp-aurora{position:fixed;inset:-20% -20% auto -20%;height:80vh;z-index:0;pointer-events:none;
  background:
   radial-gradient(40% 50% at 20% 20%, rgba(34,211,238,.18), transparent 70%),
   radial-gradient(45% 55% at 80% 10%, rgba(139,92,246,.20), transparent 70%),
   radial-gradient(40% 45% at 55% 35%, rgba(59,130,246,.16), transparent 70%);
  filter:blur(20px);animation:lpAurora 18s ease-in-out infinite alternate;}
@keyframes lpAurora{0%{transform:translate3d(-3%,0,0) scale(1)}100%{transform:translate3d(4%,4%,0) scale(1.15)}}
.lp-grid{position:fixed;inset:0;z-index:0;pointer-events:none;opacity:.4;
  background-image:linear-gradient(rgba(255,255,255,.025) 1px,transparent 1px),
   linear-gradient(90deg,rgba(255,255,255,.025) 1px,transparent 1px);
  background-size:48px 48px;mask-image:radial-gradient(circle at 50% 0%,#000,transparent 75%);}
.lp-cursor-glow{position:fixed;left:0;top:0;width:520px;height:520px;z-index:0;pointer-events:none;
  transform:translate(calc(var(--mx) - 260px),calc(var(--my) - 260px));
  background:radial-gradient(circle,rgba(59,130,246,.10),transparent 60%);transition:transform .08s linear;}

.lp-root > *:not(.lp-aurora):not(.lp-grid):not(.lp-cursor-glow){position:relative;z-index:1;}

/* Header */
.lp-header{position:sticky;top:0;z-index:50;display:flex;align-items:center;gap:1.5rem;
  padding:.85rem clamp(1rem,4vw,3rem);backdrop-filter:blur(14px);
  background:rgba(8,9,12,.6);border-bottom:1px solid rgba(255,255,255,.06);}
.lp-logo{display:flex;align-items:center;gap:.6rem;text-decoration:none;}
.lp-logo-mark{width:22px;height:22px;border-radius:7px;
  background:linear-gradient(135deg,#22d3ee,#3b82f6,#8b5cf6);box-shadow:0 0 16px rgba(59,130,246,.6);}
.lp-logo-text{font-weight:800;letter-spacing:.14em;color:#cbd5e1;font-size:1rem;}
.lp-logo-ai{background:linear-gradient(135deg,#22d3ee,#8b5cf6);-webkit-background-clip:text;background-clip:text;color:transparent;}
.lp-nav{display:flex;gap:1.4rem;margin-left:1rem;}
.lp-nav a{color:#9ca3af;text-decoration:none;font-size:.9rem;transition:color .2s;}
.lp-nav a:hover{color:#e6e9ef;}
.lp-header-cta{margin-left:auto;display:flex;align-items:center;gap:.75rem;}
.lp-link-btn{background:none;border:none;color:#cbd5e1;cursor:pointer;font-size:.9rem;font-weight:600;}
.lp-link-btn:hover{color:#fff;}

/* Boutons */
.lp-btn{border:none;cursor:pointer;font-weight:700;color:#fff;border-radius:12px;
  background:linear-gradient(135deg,#22d3ee,#3b82f6,#8b5cf6);background-size:200% 200%;
  transition:transform .15s,box-shadow .25s,background-position .6s;
  box-shadow:0 6px 24px rgba(59,130,246,.35);}
.lp-btn:hover{transform:translateY(-2px);background-position:100% 0;box-shadow:0 10px 36px rgba(139,92,246,.5);}
.lp-btn-mini{padding:.5rem 1rem;font-size:.85rem;border-radius:10px;}
.lp-btn-hero{display:inline-flex;align-items:center;gap:.6rem;padding:1rem 1.8rem;font-size:1.05rem;
  position:relative;animation:lpPulse 2.6s ease-in-out infinite;}
@keyframes lpPulse{0%,100%{box-shadow:0 6px 24px rgba(59,130,246,.35)}50%{box-shadow:0 10px 40px rgba(139,92,246,.55)}}
.lp-arrow{transition:transform .2s;}
.lp-btn-hero:hover .lp-arrow{transform:translateX(4px);}
.lp-btn-ghost{display:inline-flex;align-items:center;padding:1rem 1.4rem;border-radius:12px;
  border:1px solid rgba(255,255,255,.12);color:#cbd5e1;text-decoration:none;font-weight:600;transition:all .2s;}
.lp-btn-ghost:hover{border-color:rgba(255,255,255,.3);color:#fff;background:rgba(255,255,255,.03);}

/* Hero */
.lp-hero{display:grid;grid-template-columns:1.1fr .9fr;gap:clamp(1.5rem,4vw,4rem);align-items:center;
  padding:clamp(2.5rem,7vw,6rem) clamp(1rem,5vw,4rem) clamp(2rem,5vw,4rem);max-width:1280px;margin:0 auto;}
.lp-badge{display:inline-flex;align-items:center;gap:.5rem;padding:.4rem .9rem;border-radius:999px;
  border:1px solid rgba(34,211,238,.25);background:rgba(34,211,238,.06);color:#9ca3af;font-size:.78rem;margin-bottom:1.4rem;}
.lp-dot{width:7px;height:7px;border-radius:50%;background:#22d3ee;box-shadow:0 0 8px #22d3ee;animation:lpBlink 1.8s infinite;}
@keyframes lpBlink{0%,100%{opacity:1}50%{opacity:.3}}
.lp-h1{font-size:clamp(2.2rem,5.2vw,4rem);line-height:1.05;font-weight:800;letter-spacing:-.02em;margin:0 0 1.2rem;}
.lp-grad{background:linear-gradient(135deg,#22d3ee 0%,#3b82f6 45%,#8b5cf6 100%);
  -webkit-background-clip:text;background-clip:text;color:transparent;}
.lp-sub{font-size:clamp(1rem,1.6vw,1.18rem);line-height:1.65;color:#9ca3af;max-width:560px;margin:0 0 2rem;}
.lp-sub strong{color:#e6e9ef;font-weight:600;}
.lp-cta-row{display:flex;flex-wrap:wrap;gap:1rem;align-items:center;}
.lp-trust{display:flex;flex-wrap:wrap;gap:1.2rem;margin-top:2rem;color:#5b6170;font-size:.82rem;}

/* Gauge */
.lp-hero-visual{display:flex;justify-content:center;}
.lp-card{background:linear-gradient(180deg,rgba(20,23,28,.9),rgba(14,16,20,.9));
  border:1px solid rgba(255,255,255,.07);border-radius:20px;backdrop-filter:blur(8px);}
.lp-gauge-card{padding:1.8rem;width:min(360px,90vw);text-align:center;
  box-shadow:0 30px 80px rgba(0,0,0,.5);position:relative;overflow:hidden;}
.lp-gauge-card::before{content:'';position:absolute;inset:0;border-radius:20px;padding:1px;
  background:linear-gradient(135deg,rgba(34,211,238,.5),transparent 40%,rgba(139,92,246,.5));
  -webkit-mask:linear-gradient(#000 0 0) content-box,linear-gradient(#000 0 0);
  -webkit-mask-composite:xor;mask-composite:exclude;pointer-events:none;}
.lp-gauge-label{font-size:.8rem;color:#9ca3af;margin-bottom:1rem;}
.lp-gauge-wrap{position:relative;width:180px;height:180px;margin:0 auto;}
.lp-gauge-svg{width:180px;height:180px;}
.lp-gauge-track{fill:none;stroke:rgba(255,255,255,.07);stroke-width:12;}
.lp-gauge-fill{fill:none;stroke-width:12;stroke-linecap:round;transition:stroke-dasharray .1s linear;
  filter:drop-shadow(0 0 6px rgba(59,130,246,.6));}
.lp-gauge-center{position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center;}
.lp-gauge-num{font-size:2.6rem;font-weight:800;
  background:linear-gradient(135deg,#22d3ee,#8b5cf6);-webkit-background-clip:text;background-clip:text;color:transparent;}
.lp-gauge-num span{font-size:1.2rem;}
.lp-gauge-time{font-size:.82rem;color:#9ca3af;margin-top:.9rem;}
.lp-gauge-foot{margin-top:1.4rem;}
.lp-chip{display:inline-block;padding:.4rem .8rem;border-radius:10px;font-size:.78rem;color:#cbd5e1;
  background:rgba(255,255,255,.04);border:1px solid rgba(255,255,255,.07);}

/* Sections */
.lp-section{max-width:1180px;margin:0 auto;padding:clamp(3rem,7vw,6rem) clamp(1rem,5vw,3rem);}
.lp-center{text-align:center;}
.lp-h2{font-size:clamp(1.6rem,3.4vw,2.6rem);font-weight:800;line-height:1.15;letter-spacing:-.02em;margin:0 0 1rem;}
.lp-section-sub{font-size:clamp(1rem,1.5vw,1.12rem);line-height:1.6;color:#9ca3af;max-width:680px;margin:0 auto;}
.lp-eyebrow{display:inline-block;font-size:.78rem;letter-spacing:.12em;text-transform:uppercase;color:#22d3ee;margin-bottom:.8rem;}

/* Steps */
.lp-steps{display:grid;grid-template-columns:repeat(3,1fr);gap:1.2rem;margin-top:2.5rem;}
.lp-step{padding:1.8rem;}
.lp-step-n{font-size:1rem;font-weight:800;letter-spacing:.1em;
  background:linear-gradient(135deg,#22d3ee,#8b5cf6);-webkit-background-clip:text;background-clip:text;color:transparent;margin-bottom:.8rem;}
.lp-step-t{font-size:1.15rem;font-weight:700;margin:0 0 .5rem;}
.lp-step-d{color:#9ca3af;line-height:1.55;margin:0;font-size:.95rem;}

/* Démo */
.lp-demo{display:grid;grid-template-columns:1.1fr .9fr;gap:clamp(1.5rem,4vw,3rem);padding:clamp(1.8rem,4vw,3rem);align-items:center;}
.lp-slider-label{display:flex;justify-content:space-between;align-items:baseline;margin:1.5rem 0 .6rem;color:#9ca3af;font-size:.9rem;}
.lp-slider-label strong{font-size:1.3rem;color:#22d3ee;}
.lp-slider{-webkit-appearance:none;appearance:none;width:100%;height:8px;border-radius:99px;outline:none;
  background:linear-gradient(90deg,#22d3ee,#3b82f6,#8b5cf6);cursor:pointer;}
.lp-slider::-webkit-slider-thumb{-webkit-appearance:none;width:24px;height:24px;border-radius:50%;background:#fff;
  border:3px solid #3b82f6;box-shadow:0 0 14px rgba(59,130,246,.7);cursor:pointer;}
.lp-slider::-moz-range-thumb{width:22px;height:22px;border-radius:50%;background:#fff;border:3px solid #3b82f6;cursor:pointer;}
.lp-demo-hint{font-size:.72rem;color:#5b6170;margin-top:.8rem;}
.lp-demo-right{display:flex;flex-direction:column;gap:1.2rem;}
.lp-stat{text-align:center;}
.lp-stat-num{font-size:clamp(2rem,5vw,3rem);font-weight:800;line-height:1;}
.lp-stat-lbl{color:#9ca3af;font-size:.85rem;margin-top:.3rem;}
.lp-bar{height:10px;border-radius:99px;background:rgba(255,255,255,.06);overflow:hidden;}
.lp-bar-fill{height:100%;border-radius:99px;background:linear-gradient(90deg,#22d3ee,#3b82f6,#8b5cf6);transition:width .25s ease;}

/* Features */
.lp-features{display:grid;grid-template-columns:repeat(3,1fr);gap:1.2rem;margin-top:2.5rem;}
.lp-feature{padding:1.6rem;transition:transform .2s,border-color .2s,box-shadow .2s;}
.lp-feature:hover{transform:translateY(-4px);border-color:rgba(59,130,246,.4);box-shadow:0 16px 44px rgba(0,0,0,.45);}
.lp-feature-ic{font-size:1.6rem;margin-bottom:.7rem;}
.lp-feature-t{font-size:1.08rem;font-weight:700;margin:0 0 .4rem;}
.lp-feature-d{color:#9ca3af;line-height:1.55;margin:0;font-size:.92rem;}

/* FAQ */
.lp-faq{max-width:760px;margin:2.5rem auto 0;display:flex;flex-direction:column;gap:.8rem;}
.lp-faq-item{border:1px solid rgba(255,255,255,.07);border-radius:14px;background:rgba(20,23,28,.5);overflow:hidden;transition:border-color .2s;}
.lp-faq-item.open{border-color:rgba(59,130,246,.4);}
.lp-faq-q{width:100%;display:flex;justify-content:space-between;align-items:center;gap:1rem;
  padding:1.1rem 1.3rem;background:none;border:none;color:#e6e9ef;cursor:pointer;font-size:1rem;font-weight:600;text-align:left;}
.lp-faq-plus{font-size:1.4rem;color:#22d3ee;flex-shrink:0;}
.lp-faq-a{max-height:0;overflow:hidden;transition:max-height .35s ease;}
.lp-faq-item.open .lp-faq-a{max-height:240px;}
.lp-faq-a p{margin:0;padding:0 1.3rem 1.2rem;color:#9ca3af;line-height:1.6;font-size:.94rem;}

/* CTA final */
.lp-final{text-align:center;max-width:760px;margin:0 auto;padding:clamp(3rem,8vw,7rem) 1.5rem;}
.lp-final .lp-btn-hero{margin-top:1.6rem;}

/* Footer */
.lp-footer{display:flex;flex-wrap:wrap;gap:1rem;justify-content:space-between;align-items:center;
  max-width:1180px;margin:0 auto;padding:2rem clamp(1rem,5vw,3rem);border-top:1px solid rgba(255,255,255,.06);color:#5b6170;}
.lp-footer-links{display:flex;gap:1.4rem;}
.lp-footer-links a{color:#9ca3af;text-decoration:none;font-size:.85rem;}
.lp-footer-links a:hover{color:#e6e9ef;}

/* Reveal au scroll */
.lp-reveal{opacity:0;transform:translateY(24px);transition:opacity .7s ease,transform .7s ease;}
.lp-reveal.lp-in{opacity:1;transform:none;}

/* Responsive */
@media(max-width:860px){
  .lp-hero{grid-template-columns:1fr;text-align:center;}
  .lp-hero-copy{display:flex;flex-direction:column;align-items:center;}
  .lp-cta-row{justify-content:center;}
  .lp-trust{justify-content:center;}
  .lp-steps,.lp-features{grid-template-columns:1fr;}
  .lp-demo{grid-template-columns:1fr;}
  .lp-nav{display:none;}
}
@media(prefers-reduced-motion:reduce){
  .lp-aurora,.lp-dot,.lp-btn-hero{animation:none;}
  .lp-reveal{opacity:1;transform:none;transition:none;}
}
`
