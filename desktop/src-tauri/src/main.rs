#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::fs;
use std::io::{BufRead, BufReader};
use std::path::PathBuf;
use std::process::{Command, Stdio};
use tauri::{AppHandle, Emitter};

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

/// Genere un token gateway securise (32 hex chars) et l'enregistre dans
/// ~/.openclaw/openclaw.json. Cree le fichier et le dossier si absents.
#[tauri::command]
fn generate_gateway_token() -> Result<String, String> {
    let token = random_hex_token(32);
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

    // Injecter le token dans gateway.token (et creer la section si absente)
    if !config.is_object() {
        config = serde_json::json!({});
    }
    let obj = config.as_object_mut().unwrap();
    let gateway = obj
        .entry("gateway")
        .or_insert_with(|| serde_json::json!({}));
    if let Some(g) = gateway.as_object_mut() {
        g.insert("token".to_string(), serde_json::json!(token));
        g.insert(
            "url".to_string(),
            serde_json::json!("http://localhost:18789"),
        );
    }

    // Ecrire avec indent pour que l'utilisateur puisse le lire facilement
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
#[tauri::command]
fn install_clawhub_skill(app: AppHandle, slug: String) -> Result<(), String> {
    let slug_for_events = slug.clone();
    std::thread::spawn(move || {
        let emit_log = |line: String| {
            let _ = app.emit("clawhub:install:log", line);
        };

        emit_log(format!("▶ openclaw clawhub install {}", slug));

        let mut child = match Command::new(npm_bin("openclaw"))
            .args(["clawhub", "install", &slug])
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

/// Liste les skills installes localement via `openclaw clawhub list`.
#[tauri::command]
fn list_installed_clawhub_skills() -> Result<Vec<String>, String> {
    let output = Command::new(npm_bin("openclaw"))
        .args(["clawhub", "list", "--format=slugs"])
        .output()
        .map_err(|e| format!("OpenClaw echoue: {}", e))?;
    if !output.status.success() {
        return Err(format!(
            "Code {}: {}",
            output.status.code().unwrap_or(-1),
            String::from_utf8_lossy(&output.stderr)
        ));
    }
    let text = String::from_utf8_lossy(&output.stdout);
    let skills: Vec<String> = text
        .lines()
        .map(|l| l.trim().to_string())
        .filter(|l| !l.is_empty())
        .collect();
    Ok(skills)
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
//  Main — Enregistrement des commandes Tauri
// ═══════════════════════════════════════════════════════════════════════════

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_fs::init())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_shell::init())
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
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
