#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod audio_capture;

use std::fs;
use std::io::{BufRead, BufReader};
use std::path::PathBuf;
use std::process::{Command, Stdio};
use std::sync::Mutex;
use tauri::{AppHandle, Emitter, Manager, WebviewWindow};
use tauri::tray::{TrayIconBuilder, TrayIconEvent};
use tauri_plugin_global_shortcut::{Code, GlobalShortcutExt, Modifiers, Shortcut, ShortcutState};

// Cache du dernier deep-link URL recu. Quand le desktop est lance via un
// deep-link (cold start), le handler Rust fire AVANT que le JS soit pret.
// On stocke alors l'URL ici, et le JS la consomme via la commande Tauri
// `take_pending_deep_link()` au boot. C'est un Option<String> derriere Mutex
// (pas async, pas de contention car set tres rare).
lazy_static::lazy_static! {
    static ref PENDING_DEEP_LINK: Mutex<Option<String>> = Mutex::new(None);
}

/// Recupere et consomme le dernier deep-link en attente. Appelle au boot
/// par le listener JS pour rattraper un eventuel cold-start via sylea://.
/// Retourne None si rien en attente.
#[tauri::command]
fn take_pending_deep_link() -> Option<String> {
    PENDING_DEEP_LINK.lock().ok().and_then(|mut g| g.take())
}

// ═══════════════════════════════════════════════════════════════════════════
//  Systeme de fichiers — Commandes v1 (inchangees)
// ═══════════════════════════════════════════════════════════════════════════

/// Ecrit un fichier sur le disque local de l'utilisateur.
#[tauri::command]
fn write_file(path: String, content: String) -> Result<String, String> {
    let file_path = PathBuf::from(&path);
    if let Some(parent) = file_path.parent() {
        fs::create_dir_all(parent).map_err(|e| format!("Erreur creation dossier: {}", e))?;
    }
    fs::write(&file_path, content.as_bytes())
        .map_err(|e| format!("Erreur ecriture: {}", e))?;
    Ok(format!("Fichier cree: {}", path))
}

/// Ecrit des donnees binaires (base64) sur le disque local.
#[tauri::command]
fn write_file_binary(path: String, data_base64: String) -> Result<String, String> {
    let file_path = PathBuf::from(&path);
    if let Some(parent) = file_path.parent() {
        fs::create_dir_all(parent).map_err(|e| format!("Erreur creation dossier: {}", e))?;
    }
    let bytes = decode_base64(&data_base64)
        .map_err(|e| format!("Erreur decodage base64: {}", e))?;
    fs::write(&file_path, &bytes)
        .map_err(|e| format!("Erreur ecriture binaire: {}", e))?;
    Ok(format!("Fichier binaire cree: {}", path))
}

/// Lit un fichier texte depuis le disque local.
#[tauri::command]
fn read_file(path: String) -> Result<String, String> {
    fs::read_to_string(&path)
        .map_err(|e| format!("Erreur lecture: {}", e))
}

/// Lit un fichier en binaire et retourne son contenu en base64.
#[tauri::command]
fn read_file_binary(path: String) -> Result<String, String> {
    let bytes = fs::read(&path)
        .map_err(|e| format!("Erreur lecture binaire: {}", e))?;
    let table: &[u8] = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    let mut result = String::new();
    let mut i = 0;
    while i < bytes.len() {
        let b0 = bytes[i] as u32;
        let b1 = if i + 1 < bytes.len() { bytes[i + 1] as u32 } else { 0 };
        let b2 = if i + 2 < bytes.len() { bytes[i + 2] as u32 } else { 0 };
        let triple = (b0 << 16) | (b1 << 8) | b2;
        result.push(table[((triple >> 18) & 0x3F) as usize] as char);
        result.push(table[((triple >> 12) & 0x3F) as usize] as char);
        if i + 1 < bytes.len() {
            result.push(table[((triple >> 6) & 0x3F) as usize] as char);
        } else {
            result.push('=');
        }
        if i + 2 < bytes.len() {
            result.push(table[(triple & 0x3F) as usize] as char);
        } else {
            result.push('=');
        }
        i += 3;
    }
    Ok(result)
}

/// Retourne les metadonnees d'un fichier (taille, type).
#[tauri::command]
fn get_file_info(path: String) -> Result<String, String> {
    let metadata = fs::metadata(&path)
        .map_err(|e| format!("Erreur metadata: {}", e))?;
    let size = metadata.len();
    let is_dir = metadata.is_dir();
    Ok(format!("{{\"size\":{},\"is_dir\":{}}}", size, is_dir))
}

/// Liste les fichiers d'un dossier.
#[tauri::command]
fn list_directory(path: String) -> Result<Vec<String>, String> {
    let entries = fs::read_dir(&path)
        .map_err(|e| format!("Erreur lecture dossier: {}", e))?;
    let mut files = Vec::new();
    for entry in entries {
        if let Ok(entry) = entry {
            files.push(entry.path().display().to_string());
        }
    }
    Ok(files)
}

/// Verifie si un fichier/dossier existe.
#[tauri::command]
fn file_exists(path: String) -> bool {
    PathBuf::from(&path).exists()
}

/// Cree un dossier (et ses parents).
#[tauri::command]
fn create_directory(path: String) -> Result<String, String> {
    fs::create_dir_all(&path)
        .map_err(|e| format!("Erreur creation dossier: {}", e))?;
    Ok(format!("Dossier cree: {}", path))
}

/// Supprime un fichier.
#[tauri::command]
fn delete_file(path: String) -> Result<String, String> {
    fs::remove_file(&path)
        .map_err(|e| format!("Erreur suppression: {}", e))?;
    Ok(format!("Fichier supprime: {}", path))
}

/// Retourne le chemin du dossier Documents de l'utilisateur.
#[tauri::command]
fn get_documents_dir() -> Result<String, String> {
    dirs::document_dir()
        .map(|p| p.display().to_string())
        .ok_or_else(|| "Impossible de trouver le dossier Documents".to_string())
}

/// Retourne le chemin du dossier Desktop de l'utilisateur.
#[tauri::command]
fn get_desktop_dir() -> Result<String, String> {
    dirs::desktop_dir()
        .map(|p| p.display().to_string())
        .ok_or_else(|| "Impossible de trouver le dossier Bureau".to_string())
}

/// Retourne le chemin du dossier Downloads de l'utilisateur.
#[tauri::command]
fn get_downloads_dir() -> Result<String, String> {
    dirs::download_dir()
        .map(|p| p.display().to_string())
        .ok_or_else(|| "Impossible de trouver le dossier Telechargements".to_string())
}

// ═══════════════════════════════════════════════════════════════════════════
//  Phase 2b — Bundler OpenClaw & onboarding ClawHub
// ═══════════════════════════════════════════════════════════════════════════
//
//  Objectif : friction zero pour installer OpenClaw (moteur AI sous licence
//  MIT qui propulse les 38 outils de l'agent) et pre-selectionner les 5
//  skills ClawHub les plus utiles a un nouvel utilisateur.
//
//  Strategie :
//    1. On verifie que Node.js est installe (pre-requis, pas bundle pour
//       rester sous 400 Mo).
//    2. On installe OpenClaw via `npm install -g openclaw@latest` (la CLI
//       ecrit alors son binaire dans le PATH global de l'utilisateur).
//    3. Au 1er boot, on genere un token gateway aleatoire (32 hex chars)
//       qu'on enregistre dans ~/.openclaw/openclaw.json.
//    4. On propose 5 skills pre-coches : calendar, gmail, notion, slack,
//       todoist — installation en un clic via la CLI `openclaw clawhub
//       install <slug>`.
//
//  Evenements Tauri emis vers la UI :
//    - "openclaw:install:log"   → ligne stdout/stderr
//    - "openclaw:install:done"  → succes (code=0)
//    - "openclaw:install:error" → erreur (code != 0)
//    - "clawhub:install:log"    → progression installation d'un skill

/// Verifie si Node.js est present et retourne sa version (sinon Err).
#[tauri::command]
fn check_node_installed() -> Result<String, String> {
    let output = Command::new(npm_bin("node"))
        .arg("--version")
        .output()
        .map_err(|e| format!("Node.js introuvable: {}", e))?;
    if !output.status.success() {
        return Err("Node.js n'a pas pu s'executer".to_string());
    }
    let version = String::from_utf8_lossy(&output.stdout).trim().to_string();
    Ok(version)
}

/// Verifie si npm est present et retourne sa version (sinon Err).
#[tauri::command]
fn check_npm_installed() -> Result<String, String> {
    let output = Command::new(npm_bin("npm"))
        .arg("--version")
        .output()
        .map_err(|e| format!("npm introuvable: {}", e))?;
    if !output.status.success() {
        return Err("npm n'a pas pu s'executer".to_string());
    }
    let version = String::from_utf8_lossy(&output.stdout).trim().to_string();
    Ok(version)
}

/// Verifie si la CLI OpenClaw est installee globalement.
/// Retourne la version si presente, Err sinon.
#[tauri::command]
fn check_openclaw_installed() -> Result<String, String> {
    let output = Command::new(npm_bin("openclaw"))
        .arg("--version")
        .output()
        .map_err(|e| format!("OpenClaw introuvable: {}", e))?;
    if !output.status.success() {
        return Err("OpenClaw n'a pas pu s'executer".to_string());
    }
    let version = String::from_utf8_lossy(&output.stdout).trim().to_string();
    Ok(version)
}

/// Lance l'installation globale d'OpenClaw via npm, en streamant la sortie
/// vers la UI via les evenements "openclaw:install:log" / ":done" / ":error".
#[tauri::command]
fn install_openclaw(app: AppHandle) -> Result<(), String> {
    std::thread::spawn(move || {
        let emit_log = |line: &str| {
            let _ = app.emit("openclaw:install:log", line.to_string());
        };

        emit_log("▶ Lancement : npm install -g openclaw@latest");

        let mut child = match Command::new(npm_bin("npm"))
            .args(["install", "-g", "openclaw@latest", "--loglevel=info"])
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()
        {
            Ok(c) => c,
            Err(e) => {
                let _ = app.emit(
                    "openclaw:install:error",
                    format!("Impossible de lancer npm : {}", e),
                );
                return;
            }
        };

        // Stream stdout
        if let Some(stdout) = child.stdout.take() {
            let app_clone = app.clone();
            std::thread::spawn(move || {
                let reader = BufReader::new(stdout);
                for line in reader.lines().flatten() {
                    let _ = app_clone.emit("openclaw:install:log", line);
                }
            });
        }

        // Stream stderr (npm ecrit ses progres sur stderr par defaut)
        if let Some(stderr) = child.stderr.take() {
            let app_clone = app.clone();
            std::thread::spawn(move || {
                let reader = BufReader::new(stderr);
                for line in reader.lines().flatten() {
                    let _ = app_clone.emit("openclaw:install:log", line);
                }
            });
        }

        match child.wait() {
            Ok(status) if status.success() => {
                let _ = app.emit(
                    "openclaw:install:done",
                    "OpenClaw installe avec succes".to_string(),
                );
            }
            Ok(status) => {
                let _ = app.emit(
                    "openclaw:install:error",
                    format!("npm a retourne le code {}", status.code().unwrap_or(-1)),
                );
            }
            Err(e) => {
                let _ = app.emit(
                    "openclaw:install:error",
                    format!("Erreur execution npm : {}", e),
                );
            }
        }
    });
    Ok(())
}

/// Genere un token gateway securise (48 hex chars = 24 bytes) et l'enregistre
/// dans ~/.openclaw/openclaw.json a la cle `gateway.auth.token`. Preserve un
/// token existant (si l'utilisateur a deja configure son gateway via
/// `openclaw configure`) pour ne pas invalider sa session.
///
/// Structure resultante (conforme a la convention OpenClaw 2026.3.x) :
///   {
///     "gateway": {
///       "port": 18789,      // prefere l'existant, sinon 18789 par defaut
///       "mode": "local",    // prefere l'existant, sinon "local"
///       "auth": {
///         "mode": "token",
///         "token": "<48 hex>"
///       }
///     }
///   }
#[tauri::command]
fn generate_gateway_token() -> Result<String, String> {
    let config_path = openclaw_config_path()?;
    if let Some(parent) = config_path.parent() {
        fs::create_dir_all(parent).map_err(|e| format!("Erreur creation ~/.openclaw: {}", e))?;
    }

    // Charger config existante ou creer un squelette
    let mut config: serde_json::Value = if config_path.exists() {
        let content = fs::read_to_string(&config_path)
            .map_err(|e| format!("Erreur lecture openclaw.json: {}", e))?;
        serde_json::from_str(&content).unwrap_or_else(|_| serde_json::json!({}))
    } else {
        serde_json::json!({})
    };
    if !config.is_object() {
        config = serde_json::json!({});
    }

    // Si un token existe deja, on le reutilise : l'onboarding ne casse pas
    // une configuration manuelle ou precedente. Utile aussi pour la
    // re-ouverture du wizard apres suppression du flag onboarded.
    let existing_token = config
        .get("gateway")
        .and_then(|g| g.get("auth"))
        .and_then(|a| a.get("token"))
        .and_then(|t| t.as_str())
        .filter(|s| !s.is_empty())
        .map(String::from);

    let token = existing_token.unwrap_or_else(|| random_hex_token(48));

    // S'assurer que gateway + gateway.auth existent
    let obj = config.as_object_mut().unwrap();
    let gateway = obj
        .entry("gateway")
        .or_insert_with(|| serde_json::json!({}));
    if let Some(g) = gateway.as_object_mut() {
        // Preserve les valeurs existantes pour port/mode/bind
        g.entry("port").or_insert_with(|| serde_json::json!(18789));
        g.entry("mode").or_insert_with(|| serde_json::json!("local"));
        g.entry("bind").or_insert_with(|| serde_json::json!("loopback"));
        let auth = g.entry("auth").or_insert_with(|| serde_json::json!({}));
        if let Some(a) = auth.as_object_mut() {
            a.insert("mode".to_string(), serde_json::json!("token"));
            a.insert("token".to_string(), serde_json::json!(token));
        }
    }

    let serialized = serde_json::to_string_pretty(&config)
        .map_err(|e| format!("Erreur serialisation: {}", e))?;
    fs::write(&config_path, serialized).map_err(|e| format!("Erreur ecriture: {}", e))?;

    Ok(token)
}

/// Retourne le chemin du fichier de config OpenClaw (~/.openclaw/openclaw.json).
fn openclaw_config_path() -> Result<PathBuf, String> {
    let home = dirs::home_dir().ok_or_else(|| "HOME introuvable".to_string())?;
    Ok(home.join(".openclaw").join("openclaw.json"))
}

/// Retourne le chemin du flag d'onboarding (~/.sylea-agent/onboarded.json).
fn onboarding_flag_path() -> Result<PathBuf, String> {
    let home = dirs::home_dir().ok_or_else(|| "HOME introuvable".to_string())?;
    Ok(home.join(".sylea-agent").join("onboarded.json"))
}

/// Verifie si l'onboarding a deja ete complete par l'utilisateur.
#[tauri::command]
fn is_onboarded() -> Result<bool, String> {
    let path = onboarding_flag_path()?;
    Ok(path.exists())
}

/// Enregistre l'onboarding comme complete, avec la liste des skills choisis.
#[tauri::command]
fn mark_onboarded(skills: Vec<String>) -> Result<(), String> {
    let path = onboarding_flag_path()?;
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent)
            .map_err(|e| format!("Erreur creation dossier: {}", e))?;
    }
    let payload = serde_json::json!({
        "onboarded_at": chrono_like_timestamp(),
        "version": "1.0.0",
        "skills_installed": skills,
    });
    let serialized = serde_json::to_string_pretty(&payload)
        .map_err(|e| format!("Erreur serialisation: {}", e))?;
    fs::write(&path, serialized).map_err(|e| format!("Erreur ecriture: {}", e))?;
    Ok(())
}

/// Installe un skill ClawHub via la CLI OpenClaw. Stream le log via
/// les evenements "clawhub:install:log" / ":done:<slug>" / ":error:<slug>".
///
/// Note : la sous-commande est `openclaw skills install <slug>` (et non
/// `openclaw clawhub install` qui n'existe pas — le binaire `clawhub`
/// autonome est publie separement mais l'install d'un skill passe par
/// l'alias `skills` de l'OpenClaw CLI qui reifie le registre ClawHub).
#[tauri::command]
fn install_clawhub_skill(app: AppHandle, slug: String) -> Result<(), String> {
    let slug_for_events = slug.clone();
    std::thread::spawn(move || {
        let emit_log = |line: String| {
            let _ = app.emit("clawhub:install:log", line);
        };

        emit_log(format!("▶ openclaw skills install {}", slug));

        let mut child = match Command::new(npm_bin("openclaw"))
            .args(["skills", "install", &slug])
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()
        {
            Ok(c) => c,
            Err(e) => {
                let _ = app.emit(
                    "clawhub:install:error",
                    serde_json::json!({
                        "slug": slug_for_events,
                        "error": format!("Impossible de lancer openclaw : {}", e),
                    }),
                );
                return;
            }
        };

        if let Some(stdout) = child.stdout.take() {
            let app_clone = app.clone();
            std::thread::spawn(move || {
                let reader = BufReader::new(stdout);
                for line in reader.lines().flatten() {
                    let _ = app_clone.emit("clawhub:install:log", line);
                }
            });
        }
        if let Some(stderr) = child.stderr.take() {
            let app_clone = app.clone();
            std::thread::spawn(move || {
                let reader = BufReader::new(stderr);
                for line in reader.lines().flatten() {
                    let _ = app_clone.emit("clawhub:install:log", line);
                }
            });
        }

        match child.wait() {
            Ok(status) if status.success() => {
                let _ = app.emit(
                    "clawhub:install:done",
                    serde_json::json!({ "slug": slug_for_events }),
                );
            }
            Ok(status) => {
                let _ = app.emit(
                    "clawhub:install:error",
                    serde_json::json!({
                        "slug": slug_for_events,
                        "error": format!("Code {}", status.code().unwrap_or(-1)),
                    }),
                );
            }
            Err(e) => {
                let _ = app.emit(
                    "clawhub:install:error",
                    serde_json::json!({
                        "slug": slug_for_events,
                        "error": format!("Erreur execution : {}", e),
                    }),
                );
            }
        }
    });
    Ok(())
}

/// Liste les slugs des skills declares/installes via `openclaw skills list --json`.
///
/// Parse le JSON retourne : `{ workspaceDir, managedSkillsDir, skills: [{ name, ... }] }`
/// et renvoie uniquement les `name` (= slugs).
#[tauri::command]
fn list_installed_clawhub_skills() -> Result<Vec<String>, String> {
    let output = Command::new(npm_bin("openclaw"))
        .args(["skills", "list", "--json"])
        .output()
        .map_err(|e| format!("OpenClaw echoue: {}", e))?;
    if !output.status.success() {
        return Err(format!(
            "Code {}: {}",
            output.status.code().unwrap_or(-1),
            String::from_utf8_lossy(&output.stderr)
        ));
    }
    let text = String::from_utf8_lossy(&output.stdout).to_string();
    let parsed: serde_json::Value = serde_json::from_str(&text)
        .map_err(|e| format!("Parse JSON openclaw skills list: {}", e))?;
    let arr = parsed
        .get("skills")
        .and_then(|v| v.as_array())
        .ok_or_else(|| "Champ skills[] absent du JSON".to_string())?;
    let slugs: Vec<String> = arr
        .iter()
        .filter_map(|s| s.get("name").and_then(|n| n.as_str()).map(String::from))
        .collect();
    Ok(slugs)
}

// ═══════════════════════════════════════════════════════════════════════════
//  Helpers
// ═══════════════════════════════════════════════════════════════════════════

/// Resout le binaire npm/openclaw selon la plateforme (sous Windows les
/// binaires npm globaux ont l'extension .cmd).
fn npm_bin(name: &str) -> String {
    if cfg!(target_os = "windows") {
        // npm/openclaw sont des .cmd sous Windows. Si PATH ne les trouve
        // pas, on fait confiance au shell qui resolvera via PATHEXT.
        match name {
            "npm" => "npm.cmd".to_string(),
            "openclaw" => "openclaw.cmd".to_string(),
            other => other.to_string(),
        }
    } else {
        name.to_string()
    }
}

/// Genere N caracteres hex aleatoires via des sources OS-level.
fn random_hex_token(n: usize) -> String {
    // Source randomness : /dev/urandom sous Unix, BCryptGenRandom sous Windows.
    // Pour rester sans dependance supplementaire, on utilise fs::read sur
    // /dev/urandom et un fallback sur le temps + pid pour Windows (moins
    // cryptographiquement sur mais suffisant pour un token local gateway).
    #[cfg(unix)]
    {
        if let Ok(bytes) = fs::read("/dev/urandom") {
            let mut out = String::with_capacity(n);
            for &b in bytes.iter().take((n + 1) / 2) {
                out.push_str(&format!("{:02x}", b));
            }
            return out[..n].to_string();
        }
    }

    // Fallback/Windows : mix temps nano + pid, hache simplement par xor
    let now = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_nanos())
        .unwrap_or(0);
    let pid = std::process::id() as u128;
    let seed = now ^ (pid.wrapping_mul(2654435761));

    let mut out = String::with_capacity(n);
    let mut s = seed;
    while out.len() < n {
        s = s.wrapping_mul(6364136223846793005).wrapping_add(1442695040888963407);
        out.push_str(&format!("{:016x}", (s >> 64) as u64));
    }
    out[..n].to_string()
}

/// Timestamp au format ISO8601 minimal (utilise chrono-like sans la dep).
fn chrono_like_timestamp() -> String {
    // Format : 2026-04-20T14:30:00Z — sans lib externe, approximation epoch
    let now = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0);
    // Conversion epoch → date humaine (algo simplifie UTC)
    let (year, month, day, hour, minute, second) = epoch_to_ymdhms(now);
    format!(
        "{:04}-{:02}-{:02}T{:02}:{:02}:{:02}Z",
        year, month, day, hour, minute, second
    )
}

/// Convertit un epoch (secondes) en (year, month, day, hour, min, sec) UTC.
fn epoch_to_ymdhms(epoch: u64) -> (u32, u32, u32, u32, u32, u32) {
    let second = (epoch % 60) as u32;
    let minute = ((epoch / 60) % 60) as u32;
    let hour = ((epoch / 3600) % 24) as u32;
    let mut days = epoch / 86400;

    let mut year: u32 = 1970;
    loop {
        let year_days: u64 = if is_leap_year(year) { 366 } else { 365 };
        if days < year_days {
            break;
        }
        days -= year_days;
        year += 1;
    }

    let month_days = [31u32, if is_leap_year(year) { 29 } else { 28 }, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
    let mut month: u32 = 1;
    let mut remaining = days as u32;
    for (i, &md) in month_days.iter().enumerate() {
        if remaining < md {
            month = (i + 1) as u32;
            break;
        }
        remaining -= md;
    }
    let day = remaining + 1;
    (year, month, day, hour, minute, second)
}

fn is_leap_year(y: u32) -> bool {
    (y % 4 == 0 && y % 100 != 0) || y % 400 == 0
}

/// Decodage base64 simple sans dependance externe.
fn decode_base64(input: &str) -> Result<Vec<u8>, String> {
    let input = input.trim();
    let table: Vec<u8> = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
        .iter().copied().collect();
    let mut output = Vec::new();
    let mut buf: u32 = 0;
    let mut bits: u32 = 0;
    for &byte in input.as_bytes() {
        if byte == b'=' { break; }
        if byte == b'\n' || byte == b'\r' || byte == b' ' { continue; }
        let val = table.iter().position(|&b| b == byte)
            .ok_or_else(|| format!("Caractere base64 invalide: {}", byte as char))? as u32;
        buf = (buf << 6) | val;
        bits += 6;
        if bits >= 8 {
            bits -= 8;
            output.push((buf >> bits) as u8);
            buf &= (1 << bits) - 1;
        }
    }
    Ok(output)
}

// ═══════════════════════════════════════════════════════════════════════════
//  Phase 2c — Ouverture d'URL dans le navigateur par defaut
// ═══════════════════════════════════════════════════════════════════════════

/// Ouvre une URL dans le navigateur par defaut de l'utilisateur.
///
/// Utilise par le wizard pour amener l'utilisateur sur sylea-ai.com
/// une fois l'onboarding OpenClaw termine : il trouve alors son compte,
/// voit le statut "Desktop connecte" en vert, et peut commencer a
/// deleguer des actions.
#[tauri::command]
fn open_url(url: String) -> Result<(), String> {
    // Garde-fou : on n'ouvre que http(s)
    if !url.starts_with("http://") && !url.starts_with("https://") {
        return Err(format!("URL non supportee : {}", url));
    }

    #[cfg(target_os = "windows")]
    {
        // "start" est une commande interne de cmd, pas un executable.
        // L'argument vide "" est le titre de la fenetre (requis par start).
        Command::new("cmd")
            .args(["/c", "start", "", &url])
            .spawn()
            .map_err(|e| format!("Impossible d'ouvrir le navigateur : {}", e))?;
    }
    #[cfg(target_os = "macos")]
    {
        Command::new("open")
            .arg(&url)
            .spawn()
            .map_err(|e| format!("Impossible d'ouvrir le navigateur : {}", e))?;
    }
    #[cfg(target_os = "linux")]
    {
        Command::new("xdg-open")
            .arg(&url)
            .spawn()
            .map_err(|e| format!("Impossible d'ouvrir le navigateur : {}", e))?;
    }

    Ok(())
}

// ═══════════════════════════════════════════════════════════════════════════
//  Sprint 1 — Commandes window/pill/autostart/updater
// ═══════════════════════════════════════════════════════════════════════════

/// Bascule entre la fenetre normale (720x820) et le mode "pill" compact
/// (240x80, always-on-top, en bas a droite). Idéal pour presence ambiante
/// type Spotify mini-player.
#[tauri::command]
async fn toggle_pill_mode(window: WebviewWindow, pill: bool) -> Result<(), String> {
    use tauri::{LogicalSize, PhysicalPosition};
    if pill {
        // Place pill en bas a droite (offset 16px)
        let monitor = window.current_monitor().map_err(|e| e.to_string())?;
        let (mw, mh, scale) = if let Some(m) = monitor {
            let s = m.size();
            (s.width as i32, s.height as i32, m.scale_factor())
        } else {
            (1920, 1080, 1.0)
        };
        let pill_w_logical = 240.0_f64;
        let pill_h_logical = 80.0_f64;
        let pill_w_phys = (pill_w_logical * scale) as i32;
        let pill_h_phys = (pill_h_logical * scale) as i32;
        let margin = (16.0 * scale) as i32;
        let x = mw - pill_w_phys - margin;
        let y = mh - pill_h_phys - margin;
        window.set_decorations(false).map_err(|e| e.to_string())?;
        window
            .set_size(LogicalSize::new(pill_w_logical, pill_h_logical))
            .map_err(|e| e.to_string())?;
        window
            .set_position(PhysicalPosition::new(x as f64, y as f64))
            .map_err(|e| e.to_string())?;
        window.set_always_on_top(true).map_err(|e| e.to_string())?;
    } else {
        // Mode normal — taille initiale, centre, AOT off
        window.set_decorations(false).map_err(|e| e.to_string())?;
        window
            .set_size(LogicalSize::new(720.0, 820.0))
            .map_err(|e| e.to_string())?;
        window.center().map_err(|e| e.to_string())?;
        window.set_always_on_top(false).map_err(|e| e.to_string())?;
    }
    Ok(())
}

/// Affiche/cache la fenetre principale (utilise par tray + hotkey global)
#[tauri::command]
fn toggle_main_window(app: AppHandle) -> Result<(), String> {
    if let Some(win) = app.get_webview_window("main") {
        let visible = win.is_visible().unwrap_or(false);
        if visible {
            win.hide().map_err(|e| e.to_string())?;
        } else {
            win.show().map_err(|e| e.to_string())?;
            win.set_focus().map_err(|e| e.to_string())?;
        }
    }
    Ok(())
}

/// Quit propre (utilise par tray menu)
#[tauri::command]
fn quit_app(app: AppHandle) {
    app.exit(0);
}

// ═══════════════════════════════════════════════════════════════════════════
//  Tray icon — barre systeme Windows / macOS
// ═══════════════════════════════════════════════════════════════════════════

fn build_tray(app: &AppHandle) -> tauri::Result<()> {
    use tauri::menu::MenuBuilder;
    let menu = MenuBuilder::new(app)
        .text("show", "Ouvrir Sylea Agent")
        .separator()
        .text("pause_notif", "Mettre les notifs en pause")
        .text("resume_notif", "Reprendre les notifs")
        .separator()
        .text("quit", "Quitter")
        .build()?;

    let _ = TrayIconBuilder::with_id("main")
        .tooltip("Sylea Agent — assistant local")
        .icon(app.default_window_icon().unwrap().clone())
        .menu(&menu)
        .show_menu_on_left_click(false)
        .on_menu_event(|app, event| match event.id.as_ref() {
            "show" => {
                if let Some(w) = app.get_webview_window("main") {
                    let _ = w.show();
                    let _ = w.set_focus();
                }
            }
            "pause_notif" => {
                let _ = app.emit("tray:notifs", false);
            }
            "resume_notif" => {
                let _ = app.emit("tray:notifs", true);
            }
            "quit" => app.exit(0),
            _ => {}
        })
        .on_tray_icon_event(|tray, event| {
            // Double-click -> toggle window visibility
            if let TrayIconEvent::DoubleClick { .. } = event {
                let app = tray.app_handle();
                if let Some(w) = app.get_webview_window("main") {
                    let visible = w.is_visible().unwrap_or(false);
                    if visible {
                        let _ = w.hide();
                    } else {
                        let _ = w.show();
                        let _ = w.set_focus();
                    }
                }
            }
        })
        .build(app)?;
    Ok(())
}

// ═══════════════════════════════════════════════════════════════════════════
//  Main — Enregistrement des commandes Tauri + plugins Sprint 1
// ═══════════════════════════════════════════════════════════════════════════

fn main() {
    // Hotkey global : Ctrl+Shift+S (Windows) / Cmd+Shift+S (macOS via Modifiers::SUPER)
    let toggle_shortcut = Shortcut::new(Some(Modifiers::CONTROL | Modifiers::SHIFT), Code::KeyS);
    let toggle_shortcut_handler = toggle_shortcut.clone();
    let toggle_shortcut_setup = toggle_shortcut.clone();

    let mut builder = tauri::Builder::default();

    // Single-instance : Windows/Linux uniquement. Quand une 2e instance se
    // lance (par exemple via deep-link sylea://), elle envoie ses arguments
    // a la 1ere instance puis quitte. La 1ere instance recoit le callback,
    // ramene sa fenetre au premier plan, et reemet le deep-link au handler
    // tauri-plugin-deep-link (via plugin-side feature "deep-link").
    #[cfg(any(target_os = "windows", target_os = "linux"))]
    {
        builder = builder.plugin(tauri_plugin_single_instance::init(|app, args, _cwd| {
            eprintln!("[single-instance] new launch args: {:?}", args);
            // Bring main window to front
            use tauri::Manager;
            if let Some(w) = app.get_webview_window("main") {
                let _ = w.show();
                let _ = w.unminimize();
                let _ = w.set_focus();
            }
            // Note : avec la feature "deep-link" du plugin single-instance,
            // l'URL deep-link contenue dans `args` est automatiquement
            // forwardee au plugin deep-link (qui declenche on_open_url).
            // On n'a donc rien d'autre a faire ici.
        }));
    }

    builder
        .plugin(tauri_plugin_fs::init())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_window_state::Builder::default().build())
        .plugin(tauri_plugin_updater::Builder::new().build())
        // Deep-link : permet a sylea://auth/callback?token=... d'arriver dans
        // l'app (utilise par Sign in with Google + Apple via navigateur
        // systeme). Sur Windows/Linux, fonctionne en tandem avec single-instance
        // : les schemes sont forwardes a l'instance courante au lieu de spawner
        // une nouvelle fenetre.
        .plugin(tauri_plugin_deep_link::init())
        .plugin({
            // macos_launcher est gate par cfg(target_os = "macos")
            #[cfg(target_os = "macos")]
            {
                tauri_plugin_autostart::Builder::new()
                    .app_name("Sylea Agent")
                    .args(vec!["--minimized"])
                    .macos_launcher(tauri_plugin_autostart::MacosLauncher::LaunchAgent)
                    .build()
            }
            #[cfg(not(target_os = "macos"))]
            {
                tauri_plugin_autostart::Builder::new()
                    .app_name("Sylea Agent")
                    .args(vec!["--minimized"])
                    .build()
            }
        })
        .plugin(
            tauri_plugin_global_shortcut::Builder::new()
                .with_handler(move |app, shortcut, event| {
                    if shortcut == &toggle_shortcut_handler && event.state == ShortcutState::Pressed {
                        if let Some(w) = app.get_webview_window("main") {
                            let visible = w.is_visible().unwrap_or(false);
                            if visible {
                                let _ = w.hide();
                            } else {
                                let _ = w.show();
                                let _ = w.set_focus();
                            }
                        }
                    }
                })
                .build(),
        )
        .setup(move |app| {
            // Tray icon
            if let Err(e) = build_tray(app.handle()) {
                eprintln!("Tray init failed: {}", e);
            }
            // Register global shortcut Ctrl+Shift+S
            if let Err(e) = app.global_shortcut().register(toggle_shortcut_setup) {
                eprintln!("Global shortcut register failed: {}", e);
            }

            // Deep-link handler : sylea://auth/callback?token=...&...
            // Utilise pour ramener l'utilisateur sur le desktop apres un OAuth
            // Google/Apple effectue dans le navigateur systeme.
            //
            // Enregistrement du scheme sur Windows : en release build sans MSI
            // installer, le scheme n'est pas enregistre automatiquement dans le
            // registre. On force l'enregistrement au demarrage via register_all()
            // (cree HKCU\Software\Classes\sylea\shell\open\command). C'est idempotent.
            // Sur macOS le scheme est dans Info.plist, sur Linux dans .desktop file
            // — l'appel register_all() est un no-op gracieux sur ces plateformes.
            use tauri_plugin_deep_link::DeepLinkExt;
            #[cfg(any(target_os = "windows", target_os = "linux"))]
            {
                if let Err(e) = app.deep_link().register_all() {
                    eprintln!("[deep-link] register_all failed (non-fatal): {}", e);
                } else {
                    eprintln!("[deep-link] sylea:// scheme registered");
                }
            }
            let app_handle_for_dl = app.handle().clone();
            app.deep_link().on_open_url(move |event| {
                for url in event.urls() {
                    let url_str = url.to_string();
                    // On NE log JAMAIS le token, mais on log le scheme + path
                    eprintln!("[deep-link] received: {} {}", url.scheme(), url.path());
                    // Cache pour cold-start (le JS appelle take_pending_deep_link()
                    // au boot pour recuperer si l'event a fire avant qu'il soit pret)
                    if let Ok(mut pending) = PENDING_DEEP_LINK.lock() {
                        *pending = Some(url_str.clone());
                    }
                    // Emit vers la UI pour traitement immediat (si JS deja pret)
                    let _ = app_handle_for_dl.emit("deep-link:received", url_str);
                    // Focus la fenetre principale pour que l'utilisateur voie
                    // le resultat (au lieu de rester sur le navigateur)
                    if let Some(w) = app_handle_for_dl.get_webview_window("main") {
                        let _ = w.show();
                        let _ = w.set_focus();
                    }
                }
            });

            // If launched with --minimized (autostart), hide window at boot
            let args: Vec<String> = std::env::args().collect();
            if args.iter().any(|a| a == "--minimized") {
                if let Some(w) = app.get_webview_window("main") {
                    let _ = w.hide();
                }
            }

            // Debug hook : --test-set-nonce <NONCE> injecte un nonce en
            // localStorage avant que le JS soit pret. Utilisé pour tester le
            // flow deep-link OAuth sans avoir besoin de cliquer sur le bouton.
            // Effet : localStorage.setItem('sylea_desktop_oauth_nonce', <NONCE>)
            // PAS de garde release/debug — c'est explicit opt-in via CLI flag,
            // pas un security hole car le nonce ne donne aucun pouvoir seul
            // (faut aussi un JWT valide signe par le backend pour s'auth).
            if let Some(idx) = args.iter().position(|a| a == "--test-set-nonce") {
                if let Some(nonce) = args.get(idx + 1).cloned() {
                    if let Some(w) = app.get_webview_window("main") {
                        let safe_nonce = nonce.replace('\\', "").replace('\'', "");
                        let js = format!(
                            "setTimeout(() => {{ localStorage.setItem('sylea_desktop_oauth_nonce', '{}'); console.log('[test] nonce injected'); }}, 200)",
                            safe_nonce
                        );
                        let _ = w.eval(&js);
                        eprintln!("[test] --test-set-nonce scheduled (nonce length {})", safe_nonce.len());
                    }
                }
            }

            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            // Systeme de fichiers (v1)
            write_file,
            write_file_binary,
            read_file,
            read_file_binary,
            get_file_info,
            list_directory,
            file_exists,
            create_directory,
            delete_file,
            get_documents_dir,
            get_desktop_dir,
            get_downloads_dir,
            // Phase 2b — OpenClaw bundler & ClawHub onboarding
            check_node_installed,
            check_npm_installed,
            check_openclaw_installed,
            install_openclaw,
            generate_gateway_token,
            is_onboarded,
            mark_onboarded,
            install_clawhub_skill,
            list_installed_clawhub_skills,
            // Phase 2c — Bridge desktop -> web
            open_url,
            // Deep-link cold-start consumer (recupere URL stockee si JS pas pret)
            take_pending_deep_link,
            // Sprint 1 — Window/pill/quit
            toggle_pill_mode,
            toggle_main_window,
            quit_app,
            // Sprint dev — Ecoute active (cours universite/prepa)
            audio_capture::start_recording,
            audio_capture::stop_recording,
            audio_capture::pause_recording,
            audio_capture::resume_recording,
            audio_capture::get_recording_status,
            audio_capture::list_audio_input_devices,
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
