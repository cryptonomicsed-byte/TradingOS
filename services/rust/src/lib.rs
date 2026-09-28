pub mod models;
pub mod audit;

pub use models::{Tick, OHLCV};
pub use audit::AuditLogger;

use std::ffi::CStr;
use libc::c_char;

#[no_mangle]
pub extern "C" fn process_tick_ffi(tick: *const Tick) {
    if tick.is_null() { return; }
    let tick = unsafe { &*tick };
    let ticker = unsafe { CStr::from_ptr(tick.ticker).to_string_lossy() };
    println!("🦀 Rust Core processing tick for {}: price={}", ticker, tick.price);
}

#[no_mangle]
pub extern "C" fn log_audit_event_ffi(logger: *mut AuditLogger, payload: *const c_char) -> *const c_char {
    if logger.is_null() || payload.is_null() { return std::ptr::null(); }
    let logger = unsafe { &mut *logger };
    let payload = unsafe { CStr::from_ptr(payload).to_string_lossy() };
    
    match logger.log_event(&payload) {
        Ok(hash) => {
            // In a real implementation, we'd return a C-compatible string.
            // For now, we print and return a dummy.
            println!("🔒 Audit Logged: {}", hash);
            std::ptr::null()
        },
        Err(_) => std::ptr::null()
    }
}
