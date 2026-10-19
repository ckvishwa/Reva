//! One module per life domain. Only Finance exists in this slice; the other domains
//! follow the same shape (schema, commands, projections, queries) in later slices.

pub mod finance;
pub mod health;
