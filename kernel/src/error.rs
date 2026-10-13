//! Typed errors exposed through the UniFFI boundary (ARD-700 §2.1).

#[derive(Debug, thiserror::Error, uniffi::Error)]
pub enum DomainError {
    /// The host has no key for this domain. The data file is never touched.
    #[error("no key available for this domain")]
    Locked,
    /// A key exists but does not open this domain file. The file is never touched.
    #[error("the key does not open this domain file")]
    WrongKey,
    /// The file is damaged, truncated, or not an encrypted REVA domain file.
    #[error("the domain file is corrupt")]
    Corrupt,
    #[error("migration failed: {detail}")]
    MigrationFailed { detail: String },
    #[error("invalid {field}: {reason}")]
    Validation { field: String, reason: String },
    #[error("conflict: {detail}")]
    Conflict { detail: String },
    #[error("not found: {detail}")]
    NotFound { detail: String },
    #[error("deleted: {detail}")]
    Deleted { detail: String },
    #[error("internal error: {detail}")]
    Internal { detail: String },
}

pub type DomainResult<T> = Result<T, DomainError>;

impl DomainError {
    pub fn validation(field: impl Into<String>, reason: impl Into<String>) -> Self {
        DomainError::Validation { field: field.into(), reason: reason.into() }
    }

    pub fn not_found(message: impl Into<String>) -> Self {
        DomainError::NotFound { detail: message.into() }
    }

    pub fn conflict(message: impl Into<String>) -> Self {
        DomainError::Conflict { detail: message.into() }
    }

    pub fn internal(message: impl Into<String>) -> Self {
        DomainError::Internal { detail: message.into() }
    }

    /// Stable machine-readable code, used by the conformance suite in every binding.
    pub fn code(&self) -> &'static str {
        match self {
            DomainError::Locked => "locked",
            DomainError::WrongKey => "wrong_key",
            DomainError::Corrupt => "corrupt",
            DomainError::MigrationFailed { .. } => "migration_failed",
            DomainError::Validation { .. } => "validation",
            DomainError::Conflict { .. } => "conflict",
            DomainError::NotFound { .. } => "not_found",
            DomainError::Deleted { .. } => "deleted",
            DomainError::Internal { .. } => "internal",
        }
    }
}

impl From<rusqlite::Error> for DomainError {
    fn from(error: rusqlite::Error) -> Self {
        // The message is for logs; it never carries record contents.
        DomainError::Internal { detail: format!("storage: {error}") }
    }
}

impl From<serde_json::Error> for DomainError {
    fn from(error: serde_json::Error) -> Self {
        DomainError::Validation { field: "payload".to_string(), reason: error.to_string() }
    }
}

impl From<std::io::Error> for DomainError {
    fn from(error: std::io::Error) -> Self {
        DomainError::Internal { detail: format!("io: {error}") }
    }
}
