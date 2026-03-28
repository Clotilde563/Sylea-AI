# Configuration du domaine sylea.ai

## 1. Acheter le domaine

Rendez-vous sur l'un de ces registrars :
- [Namecheap](https://namecheap.com) — ~15€/an pour .ai
- [Google Domains](https://domains.google) — ~25€/an pour .ai
- [GoDaddy](https://godaddy.com) — ~20€/an pour .ai
- [OVH](https://ovh.com) — registrar français

Recherchez "sylea.ai" et achetez-le.

## 2. Configurer Vercel

1. Allez sur [vercel.com](https://vercel.com) → votre projet sylea-ai
2. Settings → Domains
3. Ajoutez "sylea.ai"
4. Vercel vous donne les enregistrements DNS à configurer :
   - Type A : 76.76.21.21
   - Type CNAME : cname.vercel-dns.com (pour www.sylea.ai)

## 3. Configurer les DNS chez votre registrar

Dans le panneau DNS de votre registrar, ajoutez :

| Type | Nom | Valeur | TTL |
|------|-----|--------|-----|
| A | @ | 76.76.21.21 | 3600 |
| CNAME | www | cname.vercel-dns.com | 3600 |

## 4. Attendre la propagation

La propagation DNS prend 5 minutes à 48 heures. Vercel configurera automatiquement le certificat SSL (HTTPS).

## 5. Mettre à jour le CORS

Ajoutez "https://sylea.ai" dans les variables Railway :
```
CORS_ORIGINS=https://sylea.ai,https://www.sylea.ai
```
