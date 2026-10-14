//! REVA Domain Kernel.
//!
//! One Rust crate holds every life domain's storage and rules (ADR-027). It runs inside the
//! Windows Core (Python binding) and the Android app (Kotlin binding). It stores, validates
//! and computes; it never performs network I/O, calls a model, or touches the OS beyond its
//! own data files (AR-DOM-014).

mod civil;
pub mod domains;
mod error;
mod events;
mod export;
mod handle;
mod import;
mod key;
mod store;
mod sync;
mod today;

pub use error::{DomainError, DomainResult};
pub use handle::{
    open_domain, ApplyReport, CommitResult, ConflictInfo, DomainHandle, EventBatch, ImportReport, QueryResult,
    RejectedRow,
};
pub use key::{KeyProvider, KeyProviderError};
pub use sync::{DeviceSigner, PeerInfo, SignerError, SyncBatch};
pub use today::today;

/// Internals the integration tests exercise directly.
pub mod internals {
    pub use crate::civil::{now_iso, Date};
    pub use crate::domains::finance::money;
    pub use crate::domains::finance::queries::resolve_period;
    pub use crate::events::{canonical, Event};
    pub use crate::store::domain_file;
}

uniffi::setup_scaffolding!();
