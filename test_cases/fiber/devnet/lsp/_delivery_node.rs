// Test-only normal-start wrapper. The upstream entry point is included byte-for-byte.
// No payment state machine, settlement logic, or production source is copied here.
mod upstream {
    include!(env!("LSP_UPSTREAM_MAIN"));

    pub async fn delivery_run() -> Result<(), ExitMessage> {
        let config = Config::parse();
        if config.check_validate || config.restore.is_some() {
            return Err(ExitMessage(
                "delivery adapter supports normal startup only".into(),
            ));
        }
        let fiber = config
            .parsed_fiber()
            .ok_or_else(|| ExitMessage("fiber configuration required".into()))?;
        let network_public_key = fiber.public_key();
        let network_actor_name = format!("Network {:?}", network_public_key);
        let public_key = fnn::fiber::types::pubkey_from_tentacle(network_public_key);
        let rpc_addr = config
            .rpc
            .as_ref()
            .and_then(|r| r.listening_addr.clone())
            .ok_or_else(|| ExitMessage("RPC listening address required".into()))?;
        let mut store = open_store_with_migration(
            fiber.store_path(),
            fiber.store_sync_writes(),
            Box::new(cli_confirm),
            Box::new(cli_progress),
        )
        .map_err(|e| ExitMessage(e.to_string()))?;
        let port = Arc::new(OutputPort::default());
        let changes = port.clone();
        store.set_watcher(Arc::new(move |change| {
            crate::event("store_change", serde_json::json!({"change":change}));
            changes.send(change)
        }));
        let control_store = store.clone();
        let control = tokio::spawn(async move {
            if let Err(error) =
                crate::control(control_store, public_key, network_actor_name, rpc_addr).await
            {
                crate::event("control_failed", serde_json::json!({"error":error}));
                eprintln!("delivery control failed: {error}");
                std::process::exit(2);
            }
        });
        let result = run_node(store, Some(port), config).await;
        control.abort();
        let _ = control.await;
        result
    }
}

use fnn::{
    fiber::{
        channel::ChannelActorStateStore,
        graph::NetworkGraphStateStore,
        network::{NetworkActorMessage, PublicNetworkCommand},
    },
    fiber_types::{Hash256, Pubkey},
    lsp::{
        LspDeliveryDecision, LspPaymentDeliveryKey, LspPaymentDeliveryStore, LspServiceMessage,
        TrampolineForwardingRequest,
    },
    store::{NodeNamespace, Store},
};
use ractor::{Actor, ActorProcessingErr, ActorRef, RpcReplyPort};
use serde_json::{json, Value};
use std::{
    io::Write,
    sync::{Arc, Mutex, OnceLock},
    time::{Duration, Instant},
};
use tokio::io::{AsyncBufReadExt, AsyncWriteExt, BufReader};
use tracing_subscriber::{layer::SubscriberExt, util::SubscriberInitExt, Layer};

type Reply = Result<LspDeliveryDecision, String>;
static STATE: OnceLock<Arc<Mutex<State>>> = OnceLock::new();
static STORE: OnceLock<Store> = OnceLock::new();
static START: OnceLock<Instant> = OnceLock::new();
static EVENTS: OnceLock<Mutex<std::fs::File>> = OnceLock::new();
fn ms() -> u64 {
    START.get().unwrap().elapsed().as_millis() as u64
}
fn event(name: &str, data: Value) {
    let mut row = data;
    row["event"] = json!(name);
    row["monotonic_ms"] = json!(ms());
    if let Some(file) = EVENTS.get() {
        let mut f = file.lock().unwrap();
        writeln!(f, "{row}").expect("event write");
        f.flush().expect("event flush");
    }
}
struct Capture {
    request: TrampolineForwardingRequest,
    mode: String,
    captured_ms: u64,
    original: Option<RpcReplyPort<Reply>>,
    forwarded: bool,
    reply: Option<String>,
    timeout: bool,
}
#[derive(Default)]
struct State {
    ready: bool,
    replayed: bool,
    arm: Option<(String, Hash256)>,
    captures: Vec<Capture>,
    fault: Option<usize>,
    real: Option<ActorRef<LspServiceMessage>>,
}
struct TimeoutLayer;
impl<S: tracing::Subscriber> Layer<S> for TimeoutLayer {
    fn on_event(&self, e: &tracing::Event<'_>, _: tracing_subscriber::layer::Context<'_, S>) {
        struct Fields(String);
        impl tracing::field::Visit for Fields {
            fn record_debug(&mut self, _: &tracing::field::Field, v: &dyn std::fmt::Debug) {
                self.0.push_str(&format!("{v:?}"));
            }
        }
        let mut fields = Fields(String::new());
        e.record(&mut fields);
        if e.metadata().target() != "fnn::fiber::network"
            || !fields
                .0
                .contains("Failed to consult LSP delivery service: timeout")
        {
            return;
        }
        let Some(shared) = STATE.get() else {
            return;
        };
        let mut s = shared.lock().unwrap();
        let Some(i) = s.fault else {
            event("unattributed_timeout", json!({"log":fields.0}));
            return;
        };
        let real = s.real.clone().unwrap();
        let c = &mut s.captures[i];
        if c.timeout {
            event("duplicate_timeout", json!({"log":fields.0}));
            return;
        }
        c.timeout = true;
        event(
            "caller_timeout",
            json!({"key":LspPaymentDeliveryKey::from_request(&c.request),"elapsed_ms":ms()-c.captured_ms,
            "original_port_closed":c.original.as_ref().map(|p|p.is_closed()),"log":fields.0}),
        );
        // This is the actual NetworkActor timeout log, not an adapter timer.
        c.original.take();
        if c.mode == "delay_accept" {
            c.forwarded = true;
            let request = c.request.clone();
            tokio::spawn(forward_observed(real, request, i, None));
        }
    }
}
struct Proxy;
#[ractor::async_trait]
impl Actor for Proxy {
    type Msg = LspServiceMessage;
    type State = ActorRef<LspServiceMessage>;
    type Arguments = ActorRef<LspServiceMessage>;
    async fn pre_start(
        &self,
        _: ActorRef<Self::Msg>,
        real: Self::Arguments,
    ) -> Result<Self::State, ActorProcessingErr> {
        Ok(real)
    }
    async fn handle(
        &self,
        _: ActorRef<Self::Msg>,
        msg: Self::Msg,
        real: &mut Self::State,
    ) -> Result<(), ActorProcessingErr> {
        match msg {
            LspServiceMessage::AcceptTrampolineDelivery(request, reply) => {
                let shared = STATE.get().unwrap();
                let mut s = shared.lock().unwrap();
                let mode = match &s.arm {
                    Some((mode, hash)) if *hash == request.payment_hash => {
                        let m = mode.clone();
                        s.arm = None;
                        m
                    }
                    _ => "passthrough".into(),
                };
                let i = s.captures.len();
                let persisted = STORE
                    .get()
                    .unwrap()
                    .namespaced(NodeNamespace::lsp_metadata())
                    .get_lsp_payment_delivery(&LspPaymentDeliveryKey::from_request(&request));
                let (delivery, store_error) = match persisted {
                    Ok(delivery) => (delivery, None),
                    Err(error) => (None, Some(error)),
                };
                event(
                    "captured",
                    json!({"key":LspPaymentDeliveryKey::from_request(&request),"request":request,"mode":mode,"original_port_closed":reply.is_closed(),"delivery":delivery,"store_error":store_error,"timeout_ms":reply.get_timeout().map(|d|d.as_millis() as u64)}),
                );
                let hold = mode == "delay_accept" || mode == "drop_reply";
                s.captures.push(Capture {
                    request: request.clone(),
                    mode: mode.clone(),
                    captured_ms: ms(),
                    original: None,
                    forwarded: mode != "delay_accept",
                    reply: None,
                    timeout: false,
                });
                let mut original = Some(reply);
                if hold {
                    s.fault = Some(i);
                    s.captures[i].original = original.take();
                }
                drop(s);
                if mode != "delay_accept" {
                    tokio::spawn(forward_observed(real.clone(), request, i, original));
                }
            }
            other => {
                real.send_message(other)?;
            }
        }
        Ok(())
    }
}
async fn forward_observed(
    real: ActorRef<LspServiceMessage>,
    request: TrampolineForwardingRequest,
    i: usize,
    original: Option<RpcReplyPort<Reply>>,
) {
    event(
        "forwarded",
        json!({"key":LspPaymentDeliveryKey::from_request(&request),"request":request}),
    );
    let result = ractor::call_t!(
        real,
        |p| LspServiceMessage::AcceptTrampolineDelivery(request.clone(), p),
        15_000
    );
    let reply = format!("{result:?}");
    let persisted = STORE
        .get()
        .unwrap()
        .namespaced(NodeNamespace::lsp_metadata())
        .get_lsp_payment_delivery(&LspPaymentDeliveryKey::from_request(&request));
    let mut s = STATE.get().unwrap().lock().unwrap();
    s.captures[i].reply = Some(reply.clone());
    event(
        if matches!(&result, Ok(Ok(LspDeliveryDecision::Buffered))) {
            "buffered"
        } else {
            "service_reply"
        },
        json!({"key":LspPaymentDeliveryKey::from_request(&request),"reply":reply,
        "original_port_closed":s.captures[i].original.as_ref().map(|p|p.is_closed()),"captured_ms":s.captures[i].captured_ms,"delivery":persisted.as_ref().ok().and_then(|d|d.as_ref()),"store_error":persisted.as_ref().err()}),
    );
    drop(s);
    if let (Some(port), Ok(reply)) = (original, result) {
        let _ = port.send(reply);
    }
}
fn snapshot(store: &Store) -> Result<Value, String> {
    let captures = STATE.get().unwrap().lock().unwrap().captures.iter().map(|c|json!({
        "key":LspPaymentDeliveryKey::from_request(&c.request),"request":c.request,"mode":c.mode,
        "captured_ms":c.captured_ms,"original_port_closed":c.original.as_ref().map(|p|p.is_closed()),
        "forwarded":c.forwarded,"reply":c.reply,"timeout":c.timeout,
        "upstream_tlc":store.get_channel_actor_state(&c.request.previous_tlc.prev_channel_id)
            .and_then(|ch|ch.get_all_received_tlcs().find(|t|t.id()==c.request.previous_tlc.prev_tlc_id).cloned())})).collect::<Vec<_>>();
    let deliveries = store
        .namespaced(NodeNamespace::lsp_metadata())
        .list_lsp_payment_deliveries()?
        .into_iter()
        .map(|d| {
            let mut value = serde_json::to_value(&d).expect("delivery serialization");
            value["key"] = json!(d.key());
            value
        })
        .collect::<Vec<_>>();
    // The persisted actor state contains non-string map keys and signer material.
    // Export only the channel and TLC facts needed to audit this payment path.
    let channels = store
        .get_all_channel_states()
        .into_iter()
        .map(|channel| {
            let offered = channel
                .get_offered_tlc_balance()
                .map_err(|e| e.to_string())?;
            let received = channel
                .get_received_tlc_balance()
                .map_err(|e| e.to_string())?;
            let tlcs = channel
                .tlc_state
                .all_tlcs()
                .map(|tlc| {
                    json!({
                        "id": tlc.id(),
                        "direction": if tlc.is_received() { "received" } else { "offered" },
                        "payment_hash": tlc.payment_hash,
                        "amount": tlc.amount.to_string(),
                        "status": &tlc.status,
                        "expiry": tlc.expiry,
                        "removed": tlc.removed_reason.as_ref().map(|reason| format!("{reason:?}")),
                        "forwarding_tlc": &tlc.forwarding_tlc,
                        "removed_confirmed_at": tlc.removed_confirmed_at,
                    })
                })
                .collect::<Vec<_>>();
            Ok(json!({
                "id": channel.get_id(),
                "state": &channel.state,
                "local_pubkey": &channel.local_pubkey,
                "remote_pubkey": &channel.remote_pubkey,
                "local_balance": channel.get_local_balance().to_string(),
                "remote_balance": channel.get_remote_balance().to_string(),
                "offered_tlc_balance": offered.to_string(),
                "received_tlc_balance": received.to_string(),
                "tlcs": tlcs,
            }))
        })
        .collect::<Result<Vec<Value>, String>>()?;
    let sessions = store
        .get_all_payment_sessions()
        .into_iter()
        .map(|session| {
            let attempts = store.get_attempts(session.payment_hash());
            let previous_keys = session
                .request
                .trampoline_context
                .as_ref()
                .map(|c| {
                    c.previous_tlcs
                        .iter()
                        .map(|p| LspPaymentDeliveryKey {
                            incoming_channel_id: p.prev_channel_id,
                            incoming_tlc_id: p.prev_tlc_id,
                        })
                        .collect::<Vec<_>>()
                })
                .unwrap_or_default();
            json!({"session":session,"attempts":attempts,"previous_keys":previous_keys})
        })
        .collect::<Vec<_>>();
    Ok(json!({"captures":captures,"deliveries":deliveries,"channels":channels,"sessions":sessions}))
}
async fn command(v: Value, store: &Store) -> Result<Value, String> {
    match v["command"]
        .as_str()
        .or_else(|| v["cmd"].as_str())
        .unwrap_or("")
    {
        "status" => {
            let s = STATE.get().unwrap().lock().unwrap();
            Ok(json!({"ready":s.ready,"armed":s.arm.is_some(),"capture_count":s.captures.len()}))
        }
        "snapshot" => snapshot(store),
        "arm" => {
            let mode = v["mode"].as_str().ok_or("mode required")?;
            if !["observe", "delay_accept", "drop_reply"].contains(&mode) {
                return Err("unknown mode".into());
            }
            let hash: Hash256 =
                serde_json::from_value(v["payment_hash"].clone()).map_err(|e| e.to_string())?;
            let mut s = STATE.get().unwrap().lock().unwrap();
            if !s.ready || s.arm.is_some() || s.fault.is_some() {
                return Err("not ready or already armed".into());
            }
            s.arm = Some((mode.into(), hash));
            event("armed", v);
            Ok(json!({"armed":true}))
        }
        "release" => {
            let s = STATE.get().unwrap().lock().unwrap();
            let i = s.fault.ok_or("no fault")?;
            if !s.captures[i].timeout {
                return Err("real caller timeout has not been observed; release prohibited".into());
            }
            Ok(json!({"released":true,"automatic":true}))
        }
        "replay" => {
            let (real, mut request) = {
                let mut s = STATE.get().unwrap().lock().unwrap();
                if s.replayed {
                    return Err("one replay per node is permitted".into());
                }
                s.replayed = true;
                let i = v["capture_index"].as_u64().unwrap_or(0) as usize;
                (
                    s.real.clone().ok_or("not ready")?,
                    s.captures.get(i).ok_or("capture missing")?.request.clone(),
                )
            };
            match v["variant"].as_str().unwrap_or("same") {
                "same" => {}
                "amount" => {
                    request.amount_to_forward = v["amount_to_forward"]
                        .as_str()
                        .map(|s| s.parse::<u128>())
                        .transpose()
                        .map_err(|e| e.to_string())?
                        .or_else(|| v["amount_to_forward"].as_u64().map(|x| x as u128))
                        .unwrap_or(request.amount_to_forward + 1)
                }
                "hash" => {
                    request.payment_hash = serde_json::from_value(v["payment_hash"].clone())
                        .map_err(|e| e.to_string())?
                }
                _ => return Err("unknown replay variant".into()),
            }
            event("replay_request", json!({"request":request}));
            let result = ractor::call_t!(
                real,
                |p| LspServiceMessage::AcceptTrampolineDelivery(request.clone(), p),
                5_000
            );
            let reply = format!("{result:?}");
            event("replay_reply", json!({"request":request,"reply":reply}));
            Ok(json!({"request":request,"reply":reply}))
        }
        _ => Err("unknown command".into()),
    }
}
async fn control(
    store: Store,
    public_key: Pubkey,
    network_actor_name: String,
    rpc_addr: String,
) -> Result<(), String> {
    use jsonrpsee::core::client::ClientT;
    use jsonrpsee::ws_client::{HeaderMap, HeaderValue};
    STORE.set(store.clone()).ok().expect("one control store");
    let path = std::env::var("LSP_DELIVERY_CONTROL").map_err(|e| e.to_string())?;
    // Refuse a stale endpoint rather than unlinking another process's socket.
    let listener = tokio::net::UnixListener::bind(&path).map_err(|e| e.to_string())?;
    let url = if rpc_addr.starts_with("http") {
        rpc_addr
    } else {
        format!("http://{rpc_addr}")
    };
    let token_path =
        std::env::var("LSP_DELIVERY_OPERATOR_TOKEN_PATH").map_err(|e| e.to_string())?;
    let token = std::fs::read_to_string(token_path).map_err(|e| e.to_string())?;
    let mut headers = HeaderMap::new();
    headers.insert(
        "Authorization",
        HeaderValue::from_str(&format!("Bearer {}", token.trim())).map_err(|e| e.to_string())?,
    );
    let client = jsonrpsee::http_client::HttpClientBuilder::default()
        .set_headers(headers)
        .request_timeout(Duration::from_secs(1))
        .build(&url)
        .map_err(|e| e.to_string())?;
    let deadline = Instant::now() + Duration::from_secs(90);
    loop {
        if Instant::now() > deadline {
            return Err("RPC readiness timeout".into());
        }
        if client
            .request::<Value, _>("node_info", jsonrpsee::rpc_params![])
            .await
            .is_ok()
        {
            break;
        }
        tokio::time::sleep(Duration::from_millis(100)).await;
    }
    let real = ActorRef::<LspServiceMessage>::where_is("lsp service".into())
        .ok_or("real LSP not registered")?;
    let network = ActorRef::<NetworkActorMessage>::where_is(network_actor_name)
        .ok_or("real Network not registered")?;
    let (proxy, _) = Actor::spawn(Some("delivery test proxy".into()), Proxy, real.clone())
        .await
        .map_err(|e| e.to_string())?;
    STATE.get().unwrap().lock().unwrap().real = Some(real);
    network
        .send_message(NetworkActorMessage::new_command(
            PublicNetworkCommand::SetLspService(proxy.clone()),
        ))
        .map_err(|e| e.to_string())?;
    let info = ractor::call_t!(
        network,
        |reply| NetworkActorMessage::new_command(PublicNetworkCommand::NodeInfo((), reply)),
        5_000
    )
    .map_err(|e| e.to_string())?
    .map_err(|e| e.to_string())?;
    if info.node_id != public_key {
        return Err("mailbox barrier identity mismatch".into());
    }
    STATE.get().unwrap().lock().unwrap().ready = true;
    event(
        "ready",
        json!({"node_id":public_key,"rpc_url":url,"barrier":"NodeInfo","store":"shared original Store clone"}),
    );
    let observation_store = store.clone();
    let observations = tokio::spawn(async move {
        let mut previous = Value::Null;
        loop {
            match snapshot(&observation_store) {
                Ok(current) => {
                    // Captures include the original K's TLC, so compare those and
                    // delivery/session changes for 100 ms events. Each direct
                    // snapshot also returns the projected channel facts.
                    let mut fingerprint = current.clone();
                    fingerprint.as_object_mut().unwrap().remove("channels");
                    if fingerprint != previous {
                        event("snapshot", current);
                        previous = fingerprint;
                    }
                }
                Err(error) => event("snapshot_failed", json!({"error":error})),
            }
            tokio::time::sleep(Duration::from_millis(100)).await;
        }
    });
    struct AbortOnDrop(tokio::task::JoinHandle<()>);
    impl Drop for AbortOnDrop {
        fn drop(&mut self) {
            self.0.abort();
        }
    }
    let _observations = AbortOnDrop(observations);
    loop {
        let (stream, _) = listener.accept().await.map_err(|e| e.to_string())?;
        let store = store.clone();
        tokio::spawn(async move {
            let (reader, mut writer) = stream.into_split();
            let mut reader = BufReader::new(reader);
            let mut line = String::new();
            let result =
                match tokio::time::timeout(Duration::from_secs(10), reader.read_line(&mut line))
                    .await
                {
                    Ok(Ok(n)) if n > 0 && line.len() < 65536 => match serde_json::from_str(&line) {
                        Ok(v) => command(v, &store).await,
                        Err(e) => Err(e.to_string()),
                    },
                    _ => Err("control read timeout or invalid size".into()),
                };
            let response = match result {
                Ok(result) => json!({"ok":true,"result":result}),
                Err(error) => json!({"ok":false,"error":error}),
            };
            let _ = writer.write_all(format!("{response}\n").as_bytes()).await;
        });
    }
}
fn main() -> Result<(), fnn::ExitMessage> {
    #[cfg(unix)]
    {
        use nix::sys::stat::{umask, Mode};
        umask(Mode::from_bits_truncate(0o077));
    }
    START.set(Instant::now()).unwrap();
    let file = std::fs::OpenOptions::new()
        .create_new(true)
        .write(true)
        .open(std::env::var("LSP_DELIVERY_EVENTS").expect("LSP_DELIVERY_EVENTS required"))
        .expect("new event file required");
    EVENTS.set(Mutex::new(file)).unwrap();
    STATE
        .set(Arc::new(Mutex::new(State::default())))
        .ok()
        .unwrap();
    tracing_subscriber::registry()
        .with(tracing_subscriber::EnvFilter::from_default_env())
        .with(tracing_subscriber::fmt::layer().pretty())
        .with(TimeoutLayer)
        .try_init()
        .map_err(|e| fnn::ExitMessage(e.to_string()))?;
    let runtime = tokio::runtime::Builder::new_multi_thread()
        .enable_all()
        .build()
        .map_err(|e| fnn::ExitMessage(e.to_string()))?;
    if std::env::var_os("LSP_DELIVERY_SELF_CHECK").is_some() {
        runtime.block_on(async {
            // A pure transport check: no product node, Store, payment, or Buffered result.
            let (sender, receiver) = tokio::sync::oneshot::channel::<Reply>();
            let original = RpcReplyPort::from((sender, Duration::from_millis(40)));
            assert!(!original.is_closed(), "original port starts live");
            let wait = tokio::spawn(async move {
                tokio::time::timeout(Duration::from_millis(40), receiver).await
            });
            tokio::time::sleep(Duration::from_millis(10)).await;
            assert!(
                !original.is_closed(),
                "holding sender does not close receiver"
            );
            assert!(
                wait.await.expect("selfcheck task").is_err(),
                "actual receiver timeout"
            );
            assert!(original.is_closed(), "receiver closes only after timeout");
            drop(original);
            event(
                "transport_selfcheck",
                json!({"scope":"in-memory reply port lifecycle only","product_passed":false}),
            );
        });
        Ok(())
    } else {
        runtime.block_on(upstream::delivery_run())
    }
}
