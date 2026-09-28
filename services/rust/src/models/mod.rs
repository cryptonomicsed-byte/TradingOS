use serde::{Deserialize, Serialize};
use libc::{c_char, c_double, int64_t};

#[repr(C)]
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Tick {
    pub ticker: *const c_char,
    pub price: c_double,
    pub size: c_double,
    pub timestamp: int64_t, // Unix timestamp in nanoseconds
}

#[repr(C)]
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct OHLCV {
    pub ticker: *const c_char,
    pub open: c_double,
    pub high: c_double,
    pub low: c_double,
    pub close: c_double,
    pub volume: c_double,
    pub timestamp: int64_t, // Unix timestamp in nanoseconds
}
