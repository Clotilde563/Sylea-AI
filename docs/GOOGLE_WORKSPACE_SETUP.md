# Configuration Google Workspace

Google Workspace vous permet d'avoir une adresse email professionnelle (ex: contact@sylea.ai).

## 1. S'inscrire

1. Allez sur [workspace.google.com](https://workspace.google.com)
2. Cliquez "Commencer"
3. Plan "Business Starter" : 7€/mois
4. Entrez votre domaine : sylea.ai (vous devez l'avoir acheté d'abord)

## 2. Vérifier le domaine

Google vous demandera d'ajouter un enregistrement TXT dans vos DNS pour prouver que le domaine vous appartient.

## 3. Configurer les enregistrements MX

Ajoutez ces enregistrements MX chez votre registrar :

| Priorité | Serveur |
|----------|---------|
| 1 | ASPMX.L.GOOGLE.COM |
| 5 | ALT1.ASPMX.L.GOOGLE.COM |
| 5 | ALT2.ASPMX.L.GOOGLE.COM |
| 10 | ALT3.ASPMX.L.GOOGLE.COM |
| 10 | ALT4.ASPMX.L.GOOGLE.COM |

## 4. Créer les adresses email

Une fois vérifié, créez :
- contact@sylea.ai (support client)
- noreply@sylea.ai (envoi automatique)

## 5. Mettre à jour le .env Railway

```
SMTP_EMAIL=noreply@sylea.ai
SMTP_PASSWORD=mot-de-passe-app-google-workspace
```

## 6. Mettre à jour l'application

Chercher-remplacer "sylea.ai.assistance@gmail.com" par "contact@sylea.ai" dans tout le code.
