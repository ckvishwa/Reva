//! AR-DOM-014: the Kernel never performs network I/O. Build-time check of the dependency
//! tree plus a scan of the source for network APIs.

use std::fs;
use std::path::{Path, PathBuf};
use std::process::Command;

use serde_json::Value;

/// Crates that exist to speak to the network. None may appear in the Kernel's normal
/// (non-dev, non-build) dependency tree. `openssl` is allowed only as SQLCipher's crypto
/// provider: the Kernel never links its TLS client API (checked in the source scan below).
const DENIED_CRATES: &[&str] = &[
    "reqwest",
    "hyper",
    "hyper-util",
    "hyper-tls",
    "hyper-rustls",
    "ureq",
    "isahc",
    "surf",
    "curl",
    "curl-sys",
    "attohttpc",
    "minreq",
    "h2",
    "http",
    "tungstenite",
    "tokio-tungstenite",
    "websocket",
    "native-tls",
    "rustls",
    "tokio-rustls",
    "tonic",
    "mio",
    "socket2",
    "tokio",
    "async-std",
    "smol",
    "trust-dns-resolver",
    "hickory-resolver",
    "quinn",
    "libp2p",
    "zeromq",
    "nng",
    "rumqttc",
    "paho-mqtt",
    "lettre",
    "imap",
    "ssh2",
    "suppaftp",
    "openssh",
];

fn normal_dependency_names() -> Vec<String> {
    let cargo = std::env::var("CARGO").unwrap_or_else(|_| "cargo".to_string());
    let out = Command::new(cargo)
        .args(["tree", "-p", "reva-kernel", "-e", "normal", "--prefix", "none", "--format", "{p}"])
        .current_dir(env!("CARGO_MANIFEST_DIR"))
        .output()
        .expect("cargo tree runs");
    assert!(out.status.success(), "cargo tree failed: {}", String::from_utf8_lossy(&out.stderr));
    String::from_utf8_lossy(&out.stdout)
        .lines()
        .filter_map(|l| l.split_whitespace().next())
        .map(str::to_string)
        .collect()
}

#[test]
fn dependency_tree_has_no_network_crates() {
    let deps = normal_dependency_names();
    assert!(deps.iter().any(|d| d == "rusqlite"), "sanity: cargo tree output parsed: {deps:?}");
    let offenders: Vec<_> = deps.iter().filter(|d| DENIED_CRATES.contains(&d.as_str())).collect();
    assert!(offenders.is_empty(), "network-capable crates in the Kernel dependency tree: {offenders:?}");
}

#[test]
fn cargo_metadata_agrees_for_the_direct_dependencies() {
    let cargo = std::env::var("CARGO").unwrap_or_else(|_| "cargo".to_string());
    let out = Command::new(cargo)
        .args(["metadata", "--format-version", "1", "--no-deps"])
        .current_dir(env!("CARGO_MANIFEST_DIR"))
        .output()
        .unwrap();
    let meta: Value = serde_json::from_slice(&out.stdout).unwrap();
    let pkg = meta["packages"].as_array().unwrap().iter().find(|p| p["name"] == "reva-kernel").unwrap();
    for dep in pkg["dependencies"].as_array().unwrap() {
        let name = dep["name"].as_str().unwrap();
        assert!(!DENIED_CRATES.contains(&name), "direct dependency {name} is a network crate");
    }
}

fn sources(dir: &Path, out: &mut Vec<PathBuf>) {
    for entry in fs::read_dir(dir).unwrap() {
        let path = entry.unwrap().path();
        if path.is_dir() {
            sources(&path, out);
        } else if path.extension().map(|e| e == "rs").unwrap_or(false) {
            out.push(path);
        }
    }
}

#[test]
fn source_uses_no_network_apis() {
    let mut files = Vec::new();
    sources(&Path::new(env!("CARGO_MANIFEST_DIR")).join("src"), &mut files);
    assert!(files.len() > 10);
    for file in files {
        let text = fs::read_to_string(&file).unwrap();
        for needle in [
            "std::net",
            "TcpStream",
            "TcpListener",
            "UdpSocket",
            "http://",
            "https://",
            "openssl::ssl",
            "ToSocketAddrs",
        ] {
            assert!(!text.contains(needle), "{} contains {needle:?}", file.display());
        }
    }
}
