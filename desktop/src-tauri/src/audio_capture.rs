// ════════════════════════════════════════════════════════════════════════════
//  Sprint dev — Module "Ecoute active" pour cours universite/prepa.
//
//  Capture le microphone via cpal (cross-platform) et serialise en WAV PCM
//  16-bit mono 16 kHz (format consume nativement par faster-whisper).
//  L'audio est decoupe en chunks de 30 secondes sauvegardes a la volee dans
//  un dossier de session — permet la transcription incrementale et evite
//  les soucis memoire pour les cours longs (4h+).
//
//  Architecture :
//    - Une instance globale de RecordingState (Mutex<Option<...>>)
//    - cpal::Stream tourne dans son propre thread (cree par cpal)
//    - Le callback de capture pousse les samples dans un Arc<Mutex<Vec<i16>>>
//    - Un thread "writer" reveille toutes les 100 ms, vide le buffer dans le
//      WAV writer courant ; quand le chunk atteint 30s, ferme le WAV et en
//      ouvre un nouveau (chunk_NNN.wav)
//    - Le niveau audio (RMS) est expose pour la waveform UI (get_audio_level)
//
//  Wake lock : sous Windows, on appelle SetThreadExecutionState au start
//  pour empecher veille systeme + ecran (cours de 4h sans interaction
//  laptop = veille par defaut).
// ════════════════════════════════════════════════════════════════════════════

use chrono::Utc;
use cpal::traits::{DeviceTrait, HostTrait, StreamTrait};
use cpal::{SampleFormat, SampleRate, StreamConfig};
use hound::{SampleFormat as HoundFmt, WavSpec, WavWriter};
use serde::{Deserialize, Serialize};
use std::fs;
use std::io::BufWriter;
use std::path::PathBuf;
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::{Duration, Instant};

// Cible : 16 kHz mono 16-bit PCM. C'est le format optimal pour Whisper et
// reduit drastiquement la taille des fichiers (1 MB/min vs 10 MB/min en CD).
const TARGET_SAMPLE_RATE: u32 = 16_000;
const CHUNK_DURATION_S: u64 = 30;
const CHUNK_SAMPLES: usize = (TARGET_SAMPLE_RATE as usize) * (CHUNK_DURATION_S as usize);

// ── Etat de la session ──────────────────────────────────────────────────────

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RecordingMeta {
    pub session_id: String,
    pub started_at_iso: String,
    pub matiere: Option<String>,
    pub titre: Option<String>,
    pub formation: Option<String>, // ex "MPSI", "ECG1", "hypokhagne"
    pub session_dir: String,
}

struct RecordingState {
    meta: RecordingMeta,
    // Buffer de samples en attente d'ecriture sur disque ; partage avec le
    // thread writer (callback cpal -> push, writer -> drain). Reste declare
    // ici pour conserver une reference vivante meme si l'API ne le lit pas
    // directement (cleanup automatique au drop de la state).
    #[allow(dead_code)]
    sample_buffer: Arc<Mutex<Vec<i16>>>,
    is_paused: Arc<Mutex<bool>>,
    stop_signal: Arc<Mutex<bool>>,
    level_rms: Arc<Mutex<f32>>, // 0.0 .. 1.0 — pour la waveform UI
    chunks_count: Arc<Mutex<u32>>,
    started_at: Instant,
    paused_total_ms: Arc<Mutex<u64>>,
    paused_at: Arc<Mutex<Option<Instant>>>,
    // On garde un handle sur le stream pour qu'il vive ; cpal::Stream est !Send,
    // donc on le wrappe dans une Mutex<Option<>>. Il est cree dans le thread
    // de capture (qui appelle stream.play() et le garde en vie via le scope).
    // Ici on ne stocke que le drop sentinel.
    _writer_thread: Option<thread::JoinHandle<()>>,
}

impl RecordingState {
    fn elapsed_ms(&self) -> u64 {
        let total = self.started_at.elapsed().as_millis() as u64;
        let paused = *self.paused_total_ms.lock().unwrap();
        let current_pause = self
            .paused_at
            .lock()
            .unwrap()
            .map(|t| t.elapsed().as_millis() as u64)
            .unwrap_or(0);
        total.saturating_sub(paused + current_pause)
    }
}

// Singleton global — une seule session de recording a la fois.
lazy_static::lazy_static! {
    static ref STATE: Mutex<Option<RecordingState>> = Mutex::new(None);
}

// ── Wake lock (Windows only pour l'instant) ─────────────────────────────────

#[cfg(windows)]
fn enable_wake_lock() {
    use windows::Win32::System::Power::{
        SetThreadExecutionState, ES_CONTINUOUS, ES_DISPLAY_REQUIRED, ES_SYSTEM_REQUIRED,
    };
    unsafe {
        SetThreadExecutionState(ES_CONTINUOUS | ES_DISPLAY_REQUIRED | ES_SYSTEM_REQUIRED);
    }
}

#[cfg(windows)]
fn disable_wake_lock() {
    use windows::Win32::System::Power::{SetThreadExecutionState, ES_CONTINUOUS};
    unsafe {
        SetThreadExecutionState(ES_CONTINUOUS);
    }
}

#[cfg(not(windows))]
fn enable_wake_lock() {} // no-op sur autres plateformes en sprint 1
#[cfg(not(windows))]
fn disable_wake_lock() {}

// ── Helpers WAV writer ──────────────────────────────────────────────────────

fn wav_spec() -> WavSpec {
    WavSpec {
        channels: 1,
        sample_rate: TARGET_SAMPLE_RATE,
        bits_per_sample: 16,
        sample_format: HoundFmt::Int,
    }
}

fn open_chunk_writer(session_dir: &PathBuf, chunk_idx: u32) -> Result<WavWriter<BufWriter<std::fs::File>>, String> {
    let chunk_path = session_dir.join(format!("chunk_{:04}.wav", chunk_idx));
    WavWriter::create(&chunk_path, wav_spec()).map_err(|e| format!("WAV create error: {}", e))
}

// ── Resampling lineaire simple (pour 44.1k/48k -> 16k) ──────────────────────

fn linear_resample_to_target(samples: &[f32], src_rate: u32) -> Vec<i16> {
    if src_rate == TARGET_SAMPLE_RATE {
        return samples.iter().map(|&s| (s.clamp(-1.0, 1.0) * 32767.0) as i16).collect();
    }
    let ratio = TARGET_SAMPLE_RATE as f64 / src_rate as f64;
    let out_len = (samples.len() as f64 * ratio) as usize;
    let mut out = Vec::with_capacity(out_len);
    for i in 0..out_len {
        let src_pos = i as f64 / ratio;
        let i0 = src_pos.floor() as usize;
        let i1 = (i0 + 1).min(samples.len().saturating_sub(1));
        let frac = src_pos - i0 as f64;
        let v = samples[i0] as f64 * (1.0 - frac) + samples[i1] as f64 * frac;
        out.push((v.clamp(-1.0, 1.0) * 32767.0) as i16);
    }
    out
}

// ── Mix multi-canal -> mono (moyenne) ───────────────────────────────────────

fn downmix_to_mono(samples: &[f32], channels: u16) -> Vec<f32> {
    if channels <= 1 {
        return samples.to_vec();
    }
    let n = channels as usize;
    // chunks_exact() pour ignorer les frames partielles au bord du buffer
    // (cpal peut delivrer un nombre de samples non multiple du channel count
    // selon la latence ; un sample orphelin moyenne avec /n donne un click).
    samples
        .chunks_exact(n)
        .map(|frame| frame.iter().sum::<f32>() / n as f32)
        .collect()
}

// ── Demarrage / arret du recording ──────────────────────────────────────────

#[tauri::command]
pub fn start_recording(
    session_id: String,
    matiere: Option<String>,
    titre: Option<String>,
    formation: Option<String>,
) -> Result<RecordingMeta, String> {
    // Refuse si une session est deja active.
    {
        let guard = STATE.lock().unwrap();
        if guard.is_some() {
            return Err("Une session est deja en cours".into());
        }
    }

    // Cree le dossier de session : ~/Documents/Sylea/cours/<session_id>/
    let docs = dirs::document_dir().ok_or("Impossible de trouver Documents")?;
    let session_dir = docs.join("Sylea").join("cours").join(&session_id);
    fs::create_dir_all(&session_dir).map_err(|e| format!("mkdir: {}", e))?;

    let meta = RecordingMeta {
        session_id: session_id.clone(),
        started_at_iso: Utc::now().to_rfc3339(),
        matiere,
        titre,
        formation,
        session_dir: session_dir.to_string_lossy().to_string(),
    };

    // Sauvegarde meta.json a cote du WAV.
    let meta_path = session_dir.join("meta.json");
    let meta_json = serde_json::to_string_pretty(&meta).map_err(|e| e.to_string())?;
    fs::write(&meta_path, meta_json).map_err(|e| e.to_string())?;

    // Buffers partages.
    let sample_buffer: Arc<Mutex<Vec<i16>>> = Arc::new(Mutex::new(Vec::with_capacity(CHUNK_SAMPLES * 2)));
    let is_paused = Arc::new(Mutex::new(false));
    let stop_signal = Arc::new(Mutex::new(false));
    let level_rms = Arc::new(Mutex::new(0.0_f32));
    let chunks_count = Arc::new(Mutex::new(0_u32));
    let paused_total_ms = Arc::new(Mutex::new(0_u64));
    let paused_at: Arc<Mutex<Option<Instant>>> = Arc::new(Mutex::new(None));

    // Wake lock pour eviter que la machine s'endorme pendant 4h.
    enable_wake_lock();

    // ─── Thread audio + writer (cpal::Stream est !Send, donc tout dans un thread) ───
    let buf_clone = sample_buffer.clone();
    let pause_clone = is_paused.clone();
    let stop_clone = stop_signal.clone();
    let level_clone = level_rms.clone();
    let chunks_clone = chunks_count.clone();
    let session_dir_clone = session_dir.clone();

    let writer_thread = thread::spawn(move || {
        // Setup cpal dans le thread (le Stream non-Send vit ici).
        let host = cpal::default_host();
        let device = match host.default_input_device() {
            Some(d) => d,
            None => {
                eprintln!("[audio] Aucun micro detecte");
                return;
            }
        };

        let supported_config = match device.default_input_config() {
            Ok(c) => c,
            Err(e) => {
                eprintln!("[audio] Config defaut indisponible: {}", e);
                return;
            }
        };
        let src_rate = supported_config.sample_rate().0;
        let src_channels = supported_config.channels();
        let sample_format = supported_config.sample_format();
        let cfg = StreamConfig {
            channels: src_channels,
            sample_rate: SampleRate(src_rate),
            buffer_size: cpal::BufferSize::Default,
        };

        // Capture callback : convertit selon le format puis pousse samples
        // resamples 16k mono i16 dans le buffer partage.
        let buf_for_callback = buf_clone.clone();
        let pause_for_callback = pause_clone.clone();
        let level_for_callback = level_clone.clone();

        let err_fn = |e| eprintln!("[audio] Stream error: {}", e);

        let push_samples = move |raw_f32: Vec<f32>| {
            if *pause_for_callback.lock().unwrap() {
                return;
            }
            // Mono + resample
            let mono = downmix_to_mono(&raw_f32, src_channels);
            let i16_samples = linear_resample_to_target(&mono, src_rate);

            // RMS pour le level meter (UI waveform)
            if !i16_samples.is_empty() {
                let sum_sq: f64 = i16_samples
                    .iter()
                    .map(|&s| {
                        let v = s as f64 / 32767.0;
                        v * v
                    })
                    .sum();
                let rms = (sum_sq / i16_samples.len() as f64).sqrt() as f32;
                *level_for_callback.lock().unwrap() = rms.min(1.0);
            }

            // Ajoute au buffer
            buf_for_callback.lock().unwrap().extend_from_slice(&i16_samples);
        };

        let stream_result = match sample_format {
            SampleFormat::F32 => {
                let push = push_samples.clone();
                device.build_input_stream(
                    &cfg,
                    move |data: &[f32], _| push(data.to_vec()),
                    err_fn,
                    None,
                )
            }
            SampleFormat::I16 => {
                let push = push_samples.clone();
                device.build_input_stream(
                    &cfg,
                    move |data: &[i16], _| {
                        let f32_data: Vec<f32> = data.iter().map(|&s| s as f32 / 32768.0).collect();
                        push(f32_data);
                    },
                    err_fn,
                    None,
                )
            }
            SampleFormat::U16 => {
                let push = push_samples.clone();
                device.build_input_stream(
                    &cfg,
                    move |data: &[u16], _| {
                        let f32_data: Vec<f32> = data
                            .iter()
                            .map(|&s| (s as f32 - 32768.0) / 32768.0)
                            .collect();
                        push(f32_data);
                    },
                    err_fn,
                    None,
                )
            }
            _ => {
                eprintln!("[audio] Format non supporte");
                return;
            }
        };

        let stream = match stream_result {
            Ok(s) => s,
            Err(e) => {
                eprintln!("[audio] build_input_stream: {}", e);
                return;
            }
        };

        if let Err(e) = stream.play() {
            eprintln!("[audio] stream.play(): {}", e);
            return;
        }

        // ─── Boucle writer : ecrit chunks 30s sur disque ───
        let mut chunk_idx: u32 = 0;
        let mut writer = match open_chunk_writer(&session_dir_clone, chunk_idx) {
            Ok(w) => Some(w),
            Err(e) => {
                eprintln!("[audio] open chunk 0: {}", e);
                None
            }
        };

        loop {
            if *stop_clone.lock().unwrap() {
                break;
            }
            thread::sleep(Duration::from_millis(100));

            // Vide le buffer dans le writer
            let drained: Vec<i16> = {
                let mut b = buf_clone.lock().unwrap();
                std::mem::take(&mut *b)
            };
            if let Some(w) = writer.as_mut() {
                for s in &drained {
                    let _ = w.write_sample(*s);
                }
            }

            // Si on a depasse CHUNK_SAMPLES dans le chunk courant, on roule.
            if let Some(w) = writer.as_mut() {
                if w.duration() >= CHUNK_SAMPLES as u32 {
                    if let Some(old) = writer.take() {
                        let _ = old.finalize();
                    }
                    chunk_idx += 1;
                    *chunks_clone.lock().unwrap() = chunk_idx;
                    writer = open_chunk_writer(&session_dir_clone, chunk_idx).ok();
                }
            }
        }

        // Cleanup : finalize derner chunk
        if let Some(w) = writer.take() {
            let _ = w.finalize();
        }
        drop(stream);
    });

    let state = RecordingState {
        meta: meta.clone(),
        sample_buffer,
        is_paused,
        stop_signal,
        level_rms,
        chunks_count,
        started_at: Instant::now(),
        paused_total_ms,
        paused_at,
        _writer_thread: Some(writer_thread),
    };

    *STATE.lock().unwrap() = Some(state);

    Ok(meta)
}

#[tauri::command]
pub fn pause_recording() -> Result<(), String> {
    let guard = STATE.lock().unwrap();
    let state = guard.as_ref().ok_or("Aucune session active")?;
    let mut paused = state.is_paused.lock().unwrap();
    if !*paused {
        *paused = true;
        *state.paused_at.lock().unwrap() = Some(Instant::now());
    }
    Ok(())
}

#[tauri::command]
pub fn resume_recording() -> Result<(), String> {
    let guard = STATE.lock().unwrap();
    let state = guard.as_ref().ok_or("Aucune session active")?;
    let mut paused = state.is_paused.lock().unwrap();
    if *paused {
        *paused = false;
        if let Some(t) = state.paused_at.lock().unwrap().take() {
            let mut total = state.paused_total_ms.lock().unwrap();
            *total += t.elapsed().as_millis() as u64;
        }
    }
    Ok(())
}

#[derive(Serialize)]
pub struct RecordingStatus {
    pub is_active: bool,
    pub is_paused: bool,
    pub elapsed_ms: u64,
    pub chunks_count: u32,
    pub level_rms: f32,
    pub session_id: Option<String>,
    pub session_dir: Option<String>,
}

#[tauri::command]
pub fn get_recording_status() -> RecordingStatus {
    let guard = STATE.lock().unwrap();
    match guard.as_ref() {
        None => RecordingStatus {
            is_active: false,
            is_paused: false,
            elapsed_ms: 0,
            chunks_count: 0,
            level_rms: 0.0,
            session_id: None,
            session_dir: None,
        },
        Some(state) => RecordingStatus {
            is_active: true,
            is_paused: *state.is_paused.lock().unwrap(),
            elapsed_ms: state.elapsed_ms(),
            chunks_count: *state.chunks_count.lock().unwrap(),
            level_rms: *state.level_rms.lock().unwrap(),
            session_id: Some(state.meta.session_id.clone()),
            session_dir: Some(state.meta.session_dir.clone()),
        },
    }
}

#[derive(Serialize)]
pub struct StopResult {
    pub session_id: String,
    pub session_dir: String,
    pub duration_ms: u64,
    pub chunks_count: u32,
}

#[tauri::command]
pub fn stop_recording() -> Result<StopResult, String> {
    let mut guard = STATE.lock().unwrap();
    let mut state = guard.take().ok_or("Aucune session active")?;
    *state.stop_signal.lock().unwrap() = true;

    // Capture les valeurs avant de move le JoinHandle (sinon partial move).
    let duration_ms = state.elapsed_ms();
    let chunks_count = *state.chunks_count.lock().unwrap();
    let session_id = state.meta.session_id.clone();
    let session_dir = state.meta.session_dir.clone();

    // Attend la fin du writer thread (max 5s pour eviter blocage UI).
    if let Some(handle) = state._writer_thread.take() {
        let _ = handle.join();
    }

    disable_wake_lock();

    Ok(StopResult {
        session_id,
        session_dir,
        duration_ms,
        chunks_count,
    })
}

// Liste les peripheriques d'entree disponibles (selecteur de micro UI).
#[derive(Serialize)]
pub struct AudioDevice {
    pub name: String,
    pub is_default: bool,
}

#[tauri::command]
pub fn list_audio_input_devices() -> Result<Vec<AudioDevice>, String> {
    let host = cpal::default_host();
    let default_name = host
        .default_input_device()
        .and_then(|d| d.name().ok())
        .unwrap_or_default();

    let devices = host.input_devices().map_err(|e| e.to_string())?;
    let mut result = Vec::new();
    for d in devices {
        if let Ok(name) = d.name() {
            let is_default = name == default_name;
            result.push(AudioDevice { name, is_default });
        }
    }
    Ok(result)
}

// ════════════════════════════════════════════════════════════════════════════
//  Tests unitaires (cargo test) — fonctions pures uniquement.
//
//  On ne teste PAS le recording lui-meme (cpal a besoin d'un micro reel,
//  CI sans hardware → flaky). Les fonctions deterministes (resample,
//  downmix, wav_spec) couvrent la logique critique du pipeline audio.
// ════════════════════════════════════════════════════════════════════════════

#[cfg(test)]
mod tests {
    use super::*;

    // ── linear_resample_to_target ─────────────────────────────────────────────

    #[test]
    fn resample_identity_when_rates_match() {
        // 16k → 16k : convertit f32 -> i16 PCM sans changer la longueur.
        let input = vec![0.0_f32, 0.5, -0.5, 1.0, -1.0];
        let out = linear_resample_to_target(&input, TARGET_SAMPLE_RATE);
        assert_eq!(out.len(), input.len());
        // 0.0 -> 0, 0.5 -> ~16383, -0.5 -> ~-16383, 1.0 -> 32767, -1.0 -> -32767
        assert_eq!(out[0], 0);
        assert!((out[1] - 16383).abs() <= 1);
        assert!((out[2] + 16383).abs() <= 1);
        assert_eq!(out[3], 32767);
        assert_eq!(out[4], -32767);
    }

    #[test]
    fn resample_downsample_48k_to_16k_third_length() {
        // 300 samples a 48 kHz -> ~100 samples a 16 kHz (ratio 1/3).
        let input = vec![0.5_f32; 300];
        let out = linear_resample_to_target(&input, 48_000);
        assert!(
            (out.len() as i32 - 100).abs() <= 1,
            "expected ~100 samples, got {}",
            out.len()
        );
        // Toutes les valeurs etant 0.5, l'interpolation lineaire reste plate.
        for &s in &out {
            assert!((s - 16383).abs() <= 1, "expected ~16383, got {}", s);
        }
    }

    #[test]
    fn resample_upsample_8k_to_16k_double_length() {
        // 100 samples a 8 kHz -> ~200 samples a 16 kHz (ratio 2).
        let input = vec![0.25_f32; 100];
        let out = linear_resample_to_target(&input, 8_000);
        assert!(
            (out.len() as i32 - 200).abs() <= 2,
            "expected ~200 samples, got {}",
            out.len()
        );
    }

    #[test]
    fn resample_clamps_overflow_values() {
        // Valeurs > 1.0 ou < -1.0 doivent etre clampees a +/-32767, pas wrap.
        let input = vec![5.0_f32, -5.0, 100.0, -100.0];
        let out = linear_resample_to_target(&input, TARGET_SAMPLE_RATE);
        assert_eq!(out[0], 32767);
        assert_eq!(out[1], -32767);
        assert_eq!(out[2], 32767);
        assert_eq!(out[3], -32767);
    }

    #[test]
    fn resample_empty_input_returns_empty() {
        let out = linear_resample_to_target(&[], 48_000);
        assert!(out.is_empty());
    }

    // ── downmix_to_mono ───────────────────────────────────────────────────────

    #[test]
    fn downmix_mono_passes_through_unchanged() {
        let input = vec![0.1_f32, 0.2, 0.3, 0.4];
        let out = downmix_to_mono(&input, 1);
        assert_eq!(out, input);
    }

    #[test]
    fn downmix_zero_channels_passes_through() {
        // Cas defensif : si channels == 0, on ne crash pas, on retourne tel quel.
        let input = vec![0.5_f32; 4];
        let out = downmix_to_mono(&input, 0);
        assert_eq!(out, input);
    }

    #[test]
    fn downmix_stereo_averages_left_right() {
        // [L=0.4, R=0.6, L=-0.2, R=0.4] -> [0.5, 0.1]
        let input = vec![0.4_f32, 0.6, -0.2, 0.4];
        let out = downmix_to_mono(&input, 2);
        assert_eq!(out.len(), 2);
        assert!((out[0] - 0.5).abs() < 1e-6, "got {}", out[0]);
        assert!((out[1] - 0.1).abs() < 1e-6, "got {}", out[1]);
    }

    #[test]
    fn downmix_5_channels_averages_all() {
        // 5 canaux, tous a 0.5 -> mono 0.5
        let input = vec![0.5_f32; 10]; // 2 frames de 5 canaux
        let out = downmix_to_mono(&input, 5);
        assert_eq!(out.len(), 2);
        assert!((out[0] - 0.5).abs() < 1e-6);
        assert!((out[1] - 0.5).abs() < 1e-6);
    }

    #[test]
    fn downmix_partial_frame_dropped() {
        // 5 samples avec 2 canaux : la derniere demi-frame est ignoree
        // (chunks(2) ne yield pas le sample orphelin).
        let input = vec![0.4_f32, 0.6, 0.0, 0.0, 0.9];
        let out = downmix_to_mono(&input, 2);
        assert_eq!(out.len(), 2); // [0.5, 0.0], le 0.9 isole est drop
    }

    // ── wav_spec ──────────────────────────────────────────────────────────────

    #[test]
    fn wav_spec_targets_whisper_format() {
        let spec = wav_spec();
        assert_eq!(spec.channels, 1, "must be mono");
        assert_eq!(spec.sample_rate, 16_000, "must be 16 kHz (Whisper native)");
        assert_eq!(spec.bits_per_sample, 16);
        assert!(matches!(spec.sample_format, HoundFmt::Int));
    }

    // ── Constantes ────────────────────────────────────────────────────────────

    #[test]
    fn chunk_samples_matches_30s_at_16k() {
        // 30s × 16 000 Hz = 480 000 samples par chunk.
        assert_eq!(CHUNK_SAMPLES, 480_000);
        assert_eq!(CHUNK_DURATION_S, 30);
        assert_eq!(TARGET_SAMPLE_RATE, 16_000);
    }
}
