//! Finance: accounts, transactions, categories (with aliases), budgets, bills/recurring,
//! net-worth snapshots. Hard limit (ARD-700 §3): no money movement, purchases or bank
//! credentials exist anywhere in this module or its command registry.

pub mod commands;
pub mod money;
pub mod project;
pub mod queries;
pub mod schema;

use crate::store::Migration;

pub const DOMAIN: &str = "finance";

pub fn migrations() -> Vec<Migration> {
    vec![schema::MIGRATION_V2, schema::MIGRATION_V3]
}
