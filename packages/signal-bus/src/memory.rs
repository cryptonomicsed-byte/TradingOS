use crate::types::SignalGenome;
use uuid::Uuid;
use std::collections::VecDeque;

// ═══════════════════════════════════════════════════════════════
// SIGNAL MEMORY — In-process cache + vector store bridge
// ═══════════════════════════════════════════════════════════════

/// Local ring buffer for recent signals (fast path).
/// Historical similarity search delegates to Qdrant.
pub struct SignalMemory {
    recent: VecDeque<SignalGenome>,
    capacity: usize,
}

impl SignalMemory {
    pub fn new(capacity: usize) -> Self {
        Self {
            recent: VecDeque::with_capacity(capacity),
            capacity,
        }
    }

    pub fn record(&mut self, signal: SignalGenome) {
        if self.recent.len() >= self.capacity {
            self.recent.pop_front();
        }
        self.recent.push_back(signal);
    }

    pub fn find_similar_recent(&self, embedding: &[f32], top_k: usize) -> Vec<(f32, &SignalGenome)> {
        let mut scored: Vec<(f32, &SignalGenome)> = self
            .recent
            .iter()
            .filter_map(|s| {
                s.temporal_embedding
                    .as_ref()
                    .map(|emb| (cosine_similarity(embedding, emb), s))
            })
            .collect();

        scored.sort_by(|a, b| b.0.partial_cmp(&a.0).unwrap());
        scored.truncate(top_k);
        scored
    }
}

fn cosine_similarity(a: &[f32], b: &[f32]) -> f32 {
    if a.len() != b.len() {
        return 0.0;
    }

    let dot: f32 = a.iter().zip(b.iter()).map(|(x, y)| x * y).sum();
    let norm_a: f32 = a.iter().map(|x| x * x).sum::<f32>().sqrt();
    let norm_b: f32 = b.iter().map(|x| x * x).sum::<f32>().sqrt();

    if norm_a == 0.0 || norm_b == 0.0 {
        0.0
    } else {
        dot / (norm_a * norm_b)
    }
}
