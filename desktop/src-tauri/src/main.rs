#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::fs;
use std::path::PathBuf;

/// Ecrit un fichier sur le disque local de l'utilisateur.
#[tauri::command]
fn write_file(path: String, content: String) -> Result<String, String> {
    let file_path = PathBuf::from(&path);
    // Creer les dossiers parents si necessaire
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
    // Decode base64 manuellement (pas de dep supplementaire)
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
    // Encode as base64
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

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_fs::init())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_shell::init())
        .invoke_handler(tauri::generate_handler![
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
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
