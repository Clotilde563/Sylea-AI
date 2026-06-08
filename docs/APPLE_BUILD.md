# Build & distribution macOS — Syléa Desktop

Procédure complète pour construire, **signer**, **notariser** et distribuer
l'application desktop Syléa sur macOS Intel (x86_64) et Apple Silicon (arm64).

## 0. Pré-requis

| Élément | Coût | Où |
|---------|------|-----|
| Apple Developer Program | **99 USD / an** | https://developer.apple.com/programs/ |
| Mac (Intel ou ARM) | — | nécessaire pour signer et notariser |
| Xcode Command Line Tools | gratuit | `xcode-select --install` |
| Rust + Cargo | gratuit | https://rustup.rs |
| Node.js 20+ | gratuit | https://nodejs.org |
| Tauri CLI | gratuit | `cargo install tauri-cli` |

Sans Apple Developer Program, l'app peut être buildée et tournera localement,
mais Gatekeeper (sécurité macOS) **bloquera** son lancement chez les
utilisateurs finaux ("App not from a verified developer").

---

## 1. Setup Apple Developer

### 1.1 Identifiants techniques

Après inscription :

- **Team ID** : 10 chars sur https://developer.apple.com/account → Membership
- **Bundle ID** : à enregistrer sur https://developer.apple.com/account/resources/identifiers
  - Identifier : `com.sylea.agent` (doit matcher `identifier` dans `tauri.conf.json`)
  - Capability : cocher **"Sign in with Apple"**
- **Service ID** (pour Sign in with Apple côté web) :
  - Identifier : `com.sylea.ai` (différent du Bundle ID !)
  - Domain : `api.sylea.ai`
  - Return URLs : `https://api.sylea.ai/api/auth/oauth/apple/callback`

### 1.2 Certificats de signature

```bash
# 1. Générer une CSR (Certificate Signing Request)
# Keychain Access → Certificate Assistant → Request from CA → save to file

# 2. Sur developer.apple.com/account/resources/certificates :
#    - "Developer ID Application" → upload CSR → download .cer
#    - "Developer ID Installer" (si vous distribuez via .pkg) → idem

# 3. Double-clic sur les .cer pour les importer dans Keychain
# 4. Vérifier dans le terminal :
security find-identity -v -p codesigning
# Doit afficher : "Developer ID Application: Sylea SAS (TEAMID12345)"
```

### 1.3 Clé pour Notarization

Notarization = Apple scanne votre app pour les malwares, signe son verdict
et permet à Gatekeeper de l'accepter sans warning.

```bash
# Créer une App-Specific Password :
# https://appleid.apple.com → Sign-In and Security → App-Specific Passwords
# Nom : "Sylea notarytool" — note le mot de passe généré

# Tester la connexion (sans rien soumettre) :
xcrun notarytool store-credentials "sylea-notarytool" \
    --apple-id "your@email.com" \
    --team-id "TEAMID12345" \
    --password "xxxx-xxxx-xxxx-xxxx"
```

### 1.4 Clé Sign in with Apple (.p8)

Pour générer le `client_secret` JWT côté backend :

1. https://developer.apple.com/account/resources/authkeys/list
2. **Create a Key** → cocher "Sign in with Apple" → configurer avec ton Service ID
3. **Download** le fichier `AuthKey_XXXXXXXXXX.p8` (UNIQUE téléchargement, garde-le précieusement)
4. Le **Key ID** (10 chars) est dans le nom du fichier
5. Le **Team ID** (10 chars) est sur ton dashboard developer

Ces 3 valeurs + le contenu du `.p8` vont dans les env vars du backend :

```bash
export APPLE_CLIENT_ID=com.sylea.ai      # Service ID (web)
export APPLE_TEAM_ID=ABCDEF1234
export APPLE_KEY_ID=ZYXWVU9876
export APPLE_PRIVATE_KEY="$(cat AuthKey_ZYXWVU9876.p8)"
```

---

## 2. Build local (dev)

```bash
cd desktop

# Installer les dépendances JS
npm install

# Mode dev (hot reload front, app native lance Vite)
npm run tauri dev
```

---

## 3. Build de release (sans signature)

```bash
cd desktop

# Build universel (Intel + Apple Silicon)
npm run tauri build -- --target universal-apple-darwin

# Build Intel uniquement
npm run tauri build -- --target x86_64-apple-darwin

# Build Apple Silicon uniquement
npm run tauri build -- --target aarch64-apple-darwin
```

Output : `src-tauri/target/{target}/release/bundle/`
- `macos/Sylea Agent.app` — bundle
- `dmg/Sylea Agent_1.0.0_universal.dmg` — image disque distribuable

⚠️ Sans signature, l'app génère un warning Gatekeeper. Continuer §4.

---

## 4. Signature + Notarization (release publique)

### 4.1 Config Tauri pour signature auto

Ajouter à `desktop/src-tauri/tauri.conf.json` :

```json
{
  "bundle": {
    "macOS": {
      "minimumSystemVersion": "10.15",
      "signingIdentity": "Developer ID Application: Sylea SAS (TEAMID12345)",
      "providerShortName": "TEAMID12345",
      "entitlements": "entitlements.plist",
      "frameworks": []
    }
  }
}
```

OU via env vars (préférable pour CI) :

```bash
export APPLE_SIGNING_IDENTITY="Developer ID Application: Sylea SAS (TEAMID12345)"
export APPLE_CERTIFICATE="$(base64 -i DeveloperIDApplication.p12)"  # CI uniquement
export APPLE_CERTIFICATE_PASSWORD="..."
```

### 4.2 Build + sign

```bash
cd desktop
npm run tauri build -- --target universal-apple-darwin
```

Tauri appelle automatiquement `codesign` avec l'identité configurée. Vérifier :

```bash
codesign --verify --verbose=4 "src-tauri/target/universal-apple-darwin/release/bundle/macos/Sylea Agent.app"
# Doit afficher : "satisfies its Designated Requirement"
```

### 4.3 Notarization

```bash
cd src-tauri/target/universal-apple-darwin/release/bundle

# 1. Soumettre le .dmg à Apple Notary Service
xcrun notarytool submit "dmg/Sylea Agent_1.0.0_universal.dmg" \
    --keychain-profile "sylea-notarytool" \
    --wait

# 2. Le retour prend ~5-15 min. Output attendu :
# status: Accepted
# id: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx

# 3. Si rejeté, voir les logs :
xcrun notarytool log <ID> --keychain-profile "sylea-notarytool"

# 4. Stapler le ticket dans le .dmg pour qu'il marche offline
xcrun stapler staple "dmg/Sylea Agent_1.0.0_universal.dmg"

# 5. Valider que tout est en ordre
spctl --assess --type install --verbose=4 "dmg/Sylea Agent_1.0.0_universal.dmg"
# Doit afficher : "source=Notarized Developer ID"
```

### 4.4 Test sur une autre machine

```bash
# Sur un autre Mac (sans Apple Dev Tools) :
# 1. Télécharger le .dmg
# 2. Double-clic → Gatekeeper doit accepter sans warning
# 3. Drag vers Applications, lancer
# 4. Vérifier : Préférences Système → Sécurité = pas de warning
```

---

## 5. CI/CD GitHub Actions

`.github/workflows/release-mac.yml` :

```yaml
name: Release macOS
on:
  release:
    types: [published]

jobs:
  build-mac:
    runs-on: macos-14   # Apple Silicon (gratuit pour public repo)
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-node@v4
        with:
          node-version: 20

      - uses: dtolnay/rust-toolchain@stable
        with:
          targets: aarch64-apple-darwin,x86_64-apple-darwin

      - name: Install deps
        working-directory: desktop
        run: npm ci

      - name: Import signing certificate
        env:
          APPLE_CERTIFICATE: ${{ secrets.APPLE_CERTIFICATE }}
          APPLE_CERTIFICATE_PASSWORD: ${{ secrets.APPLE_CERTIFICATE_PASSWORD }}
          KEYCHAIN_PASSWORD: ${{ secrets.KEYCHAIN_PASSWORD }}
        run: |
          security create-keychain -p "$KEYCHAIN_PASSWORD" build.keychain
          security default-keychain -s build.keychain
          security unlock-keychain -p "$KEYCHAIN_PASSWORD" build.keychain
          echo "$APPLE_CERTIFICATE" | base64 --decode > cert.p12
          security import cert.p12 -k build.keychain -P "$APPLE_CERTIFICATE_PASSWORD" -T /usr/bin/codesign
          security set-key-partition-list -S apple-tool:,apple:,codesign: -s -k "$KEYCHAIN_PASSWORD" build.keychain
          rm cert.p12

      - name: Build + sign + notarize
        working-directory: desktop
        env:
          APPLE_SIGNING_IDENTITY: ${{ secrets.APPLE_SIGNING_IDENTITY }}
          APPLE_ID: ${{ secrets.APPLE_ID }}
          APPLE_PASSWORD: ${{ secrets.APPLE_APP_SPECIFIC_PASSWORD }}
          APPLE_TEAM_ID: ${{ secrets.APPLE_TEAM_ID }}
        run: |
          npm run tauri build -- --target universal-apple-darwin

      - name: Upload to release
        uses: softprops/action-gh-release@v2
        with:
          files: |
            desktop/src-tauri/target/universal-apple-darwin/release/bundle/dmg/*.dmg
```

GitHub Secrets requis :
- `APPLE_CERTIFICATE` : base64 du .p12 export depuis Keychain
- `APPLE_CERTIFICATE_PASSWORD` : password du .p12
- `KEYCHAIN_PASSWORD` : random string utilisée par le job
- `APPLE_SIGNING_IDENTITY` : "Developer ID Application: Sylea SAS (TEAMID12345)"
- `APPLE_ID` : email Apple Developer
- `APPLE_APP_SPECIFIC_PASSWORD` : app-specific password
- `APPLE_TEAM_ID` : 10 chars Team ID

---

## 6. Sign in with Apple (flux complet)

### 6.1 Côté backend (Python)

Variables d'env à définir (Vault ou .env prod) :

```bash
export APPLE_CLIENT_ID=com.sylea.ai
export APPLE_TEAM_ID=TEAMID12345
export APPLE_KEY_ID=ZYXWVU9876
export APPLE_PRIVATE_KEY="-----BEGIN PRIVATE KEY-----
MIGTAgEAMBMGByqGSM49AgEGCCqGSM49AwEHBHkwdwIBAQQg...
-----END PRIVATE KEY-----"
export APPLE_REDIRECT_URI=https://api.sylea.ai/api/auth/oauth/apple/callback
export FRONTEND_BASE_URL=https://sylea.ai
```

Routes actives :
- `GET /api/auth/oauth/apple/url` → renvoie l'URL d'autorisation Apple
- `POST /api/auth/oauth/apple/callback` → Apple form_post, redirige vers frontend
- `POST /api/auth/oauth/apple` → échange final code → JWT Syléa

### 6.2 Côté frontend web

Le bouton "Continuer avec Apple" est déjà intégré dans `LoginPage.tsx`.
Au clic :
1. Appel `api.authAppleUrl()` → reçoit l'URL `https://appleid.apple.com/auth/authorize?...`
2. Redirection navigateur
3. Apple authentifie (modal ou login)
4. Apple POST vers `https://api.sylea.ai/api/auth/oauth/apple/callback`
5. Backend convertit en GET vers `https://sylea.ai/auth/callback?code=...&state=apple_login`
6. Frontend `AuthCallbackPage` appelle `api.authOAuthApple(code, ...)` → reçoit JWT
7. Connecté.

### 6.3 Côté desktop (Tauri) — flux deep-link

L'app desktop ne peut pas afficher Apple Sign-In dans une webview intégrée
(Apple le bloque par politique). On utilise le **navigateur système** + un
**deep-link** `sylea://` pour récupérer le callback :

1. User clique "Sign in with Apple" dans Syléa Desktop
2. App ouvre le navigateur sur `https://sylea.ai/auth/apple-desktop?state=desktop_apple_<NONCE>`
3. Le navigateur fait le Sign-In avec Apple
4. Apple POST → backend → 302 vers `sylea://auth/callback?token=<JWT>&state=desktop_apple_<NONCE>`
5. Le navigateur reconnaît le scheme `sylea://` (enregistré via `tauri.conf.json` deep-link)
6. macOS lance Syléa Desktop avec le token en argument
7. L'app stocke le JWT, ferme le navigateur, affiche le dashboard

Le code Rust pour gérer le deep-link est dans `desktop/src-tauri/src/lib.rs`
(handler `tauri::deep_link::OnNewUrl`).

### 6.4 Côté natif (macOS / iOS app native, futur)

Si on développe une app SwiftUI native (pas Tauri), utiliser `ASAuthorization`
qui passe par le système d'auth Apple natif (Touch ID / Face ID). On reçoit
directement un `id_token` JWT signé Apple → POST `/api/auth/oauth/apple`
avec `id_token` (pas de `code` requis).

---

## 7. Troubleshooting

### "Sylea Agent.app" can't be opened because Apple cannot check it for malicious software

→ Notarization échouée ou non-staplée.
```bash
xcrun stapler validate "Sylea Agent.app"
```

### "code object is not signed at all"

→ Build sans signature. Vérifier `APPLE_SIGNING_IDENTITY`.

### Sign in with Apple : "invalid_grant"

→ Le `client_secret` JWT est expiré ou mal signé. Vérifier que `APPLE_PRIVATE_KEY`
est le bon `.p8` (les \n doivent être préservés).

### Sign in with Apple : "invalid_client"

→ Le `client_id` ne correspond pas à un Service ID enregistré sur developer.apple.com
avec le bon "Return URL".

### App fonctionne sur Apple Silicon mais pas Intel (ou inverse)

→ Build avec `--target universal-apple-darwin` au lieu d'une target spécifique.

### Notarization rejected : "The signature does not include a secure timestamp"

→ Ajouter `--timestamp` aux flags codesign (Tauri le fait par défaut, mais
custom scripts peuvent l'oublier).
