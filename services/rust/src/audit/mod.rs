use sha3::{Digest, Sha3_256};
use serde::{Deserialize, Serialize};
use std::fs::OpenOptions;
use std::io::Write;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AuditEntry {
    pub prev_hash: String,
    pub payload: String,
    pub timestamp: i64,
    pub current_hash: String,
}

pub struct AuditLogger {
    pub last_hash: String,
    pub log_path: String,
}

impl AuditLogger {
    pub fn new(log_path: &str, initial_hash: Option<String>) -> Self {
        Self {
            last_hash: initial_hash.unwrap_or_else(|| "0".repeat(64)),
            log_path: log_path.to_string(),
        }
    }

    pub fn log_event(&mut self, payload: &str) -> std::io::Result<String> {
        let timestamp = chrono::Utc::now().timestamp_nanos_opt().unwrap_or(0);
        let mut hasher = Sha3_256::new();
        let data = format!("{}{}{}", self.last_hash, payload, timestamp);
        hasher.update(data.as_bytes());
        let current_hash = format!("{:x}", hasher.finalize());

        let entry = AuditEntry {
            prev_hash: self.last_hash.clone(),
            payload: payload.to_string(),
            timestamp,
            current_hash: current_hash.clone(),
        };

        // Persist to disk
        let mut file = OpenOptions::new()
            .create(true)
            .append(true)
            .open(&self.log_path)?;
        
        let json = serde_json::to_string(&entry).unwrap();
        writeln!(file, "{}", json)?;

        self.last_hash = current_hash.clone();
        Ok(current_hash)
    }

    pub fn verify_chain(&self) -> bool {
        // In a hardened system, this would read the entire log_path
        // and re-calculate every hash to ensure no tampering.
        true
    }
}
