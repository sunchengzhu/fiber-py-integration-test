//! Local test controls around the unmodified, checked SDK agent.
#[path = "_watchtower_chain.rs"]
mod watchtower_chain;
use anyhow::{anyhow, ensure, Context, Result};
use ckb_types::{core::TransactionBuilder, packed::*, prelude::*};
use clap::Parser;
use fiber_lsp_sdk::{
    ChannelSigningContent, CloseAuthorization, CommitmentParameters, Musig2SignableContent,
    OpeningNetwork, PaymentAuthorization,
};
use fiber_lsp_sdk_agent::{Agent, AgentConfig, EventStream, FileSignerStore, HttpFiberRpc};
use fiber_types::{ChannelActorData, Hash256};
use serde::Deserialize;
use serde_json::{json, Value};
use std::{io::Read, path::PathBuf};
use tokio::{
    io::{AsyncBufReadExt, AsyncWriteExt, BufReader},
    net::TcpListener,
};

#[derive(Parser)]
struct Args {
    #[arg(long)]
    rpc: String,
    /// Dedicated WebSocket RPC URL for signing subscriptions.
    #[arg(long)]
    ws_rpc: String,
    #[arg(long)]
    store: PathBuf,
    #[arg(long)]
    status_file: PathBuf,
    #[arg(long)]
    control_addr: String,
    #[arg(long)]
    operator_token: String,
    /// Tests save real signatures for explicit submission by Python.
    #[arg(long)]
    ack_held_events: bool,
    #[arg(long)]
    watchtower_check_only: bool,
}

#[derive(Deserialize)]
#[serde(rename_all = "kebab-case")]
enum MissingPermission {
    SubscriptionsWrite,
    ChannelSigningRead,
    None,
}

#[derive(Deserialize)]
struct SubscriptionToken {
    token: String,
    private_key_file: PathBuf,
    missing_permission: MissingPermission,
}

fn subscription_token() -> Result<()> {
    use biscuit_auth::{
        builder::{Fact, Term},
        AuthorizerBuilder, Biscuit, KeyPair, PrivateKey,
    };
    use std::str::FromStr;

    let input: SubscriptionToken = serde_json::from_reader(std::io::stdin())?;
    // This is the public devnet test key, never a production signing identity.
    let private_key = std::fs::read_to_string(input.private_key_file)?;
    let root = KeyPair::from(&PrivateKey::from_str(private_key.trim())?);
    let original = Biscuit::from_base64(&input.token, root.public())?;
    let mut authorizer = AuthorizerBuilder::new().build(&original)?;
    // Default queries trust authority facts only, matching FNN's scope routing.
    let tenants: Vec<(String,)> = authorizer.query("data($id) <- tenant($id)")?;
    let nodes: Vec<(String,)> = authorizer.query("data($id) <- node($id)")?;
    ensure!(
        tenants.len() == 1 && nodes.len() == 1,
        "expected tenant token"
    );
    let builder = Biscuit::builder()
        .fact(Fact::new(
            "tenant".into(),
            &[Term::Str(tenants[0].0.clone())],
        ))?
        .fact(Fact::new("node".into(), &[Term::Str(nodes[0].0.clone())]))?;
    if matches!(input.missing_permission, MissingPermission::None) {
        // Read-only browser fixture: preserve the verified tenant/node identity.
        // A neutral fact gives three consecutive serialized lengths; require
        // actual base64 padding rather than accepting a vacuous padding check.
        let builder = builder
            .fact("read(\"channels\")")?
            .fact("write(\"subscriptions\")")?;
        for length in 1..=3 {
            let token = builder.clone()
                .fact(Fact::new(
                    "lsp_test_encoding_pad".into(),
                    &[Term::Str("x".repeat(length))],
                ))?
                .build(&root)?
                .to_base64()?;
            if token.ends_with('=') {
                println!("{}", json!({"token": token}));
                return Ok(());
            }
        }
        anyhow::bail!("could not produce a valid padded browser test credential");
    }
    let builder = match input.missing_permission {
        MissingPermission::SubscriptionsWrite => builder.fact("read(\"channels\")")?,
        MissingPermission::ChannelSigningRead => builder.fact("write(\"subscriptions\")")?,
        MissingPermission::None => unreachable!(),
    };
    println!("{}", json!({"token": builder.build(&root)?.to_base64()?}));
    Ok(())
}

fn operator_subscription_token() -> Result<()> {
    use biscuit_auth::{Biscuit, KeyPair, PrivateKey};
    use std::str::FromStr;

    #[derive(Deserialize)]
    struct Input {
        private_key_file: PathBuf,
    }
    let input: Input = serde_json::from_reader(std::io::stdin())?;
    // The upstream Bruno operator fixture predates subscriptions. Issue only
    // the two required capabilities from the same public devnet test key.
    // No tenant or node fact: this credential must resolve to the host scope.
    let private_key = std::fs::read_to_string(input.private_key_file)?;
    let root = KeyPair::from(&PrivateKey::from_str(private_key.trim())?);
    let token = Biscuit::builder()
        .fact("write(\"subscriptions\")")?
        .fact("read(\"channels\")")?
        .build(&root)?
        .to_base64()?;
    println!("{}", json!({"token": token}));
    Ok(())
}

// The fee template is fixed by the devnet contracts, not a signing response.
fn transaction_size(lock: Script, close: Option<Script>, dep_count: usize) -> u64 {
    let mut builder = TransactionBuilder::default()
        .cell_deps(vec![CellDep::default(); dep_count].pack())
        .input(CellInput::default())
        .output(CellOutput::new_builder().lock(lock).build())
        .output_data(Bytes::default())
        .witness(vec![0u8; 16 + 32 + 64].pack());
    if let Some(lock) = close {
        builder = builder
            .output(CellOutput::new_builder().lock(lock).build())
            .output_data(Bytes::default());
    }
    builder.build().data().serialized_size_in_block() as u64
}

fn opening() -> Result<()> {
    use rocksdb::{prelude::*, ReadOnlyDB};
    let mut input = String::new();
    std::io::stdin().read_to_string(&mut input)?;
    let value: Value = serde_json::from_str(&input)?;
    let id: Hash256 = value["channel_id"]
        .as_str()
        .context("channel id")?
        .parse()?;
    let db = ReadOnlyDB::open(
        &Options::default(),
        value["database"].as_str().context("database")?,
    )?;
    // Public T's independently persisted side of the negotiated channel.
    let key = [
        &[fiber_types::schema::CHANNEL_ACTOR_STATE_PREFIX],
        id.as_ref(),
    ]
    .concat();
    let bytes = db
        .get(&key)?
        .context("public peer has not persisted the channel")?;
    let state: ChannelActorData = fiber_types::deserialize(&bytes)?;
    ensure!(
        state.id == id && state.is_acceptor,
        "expected public acceptor"
    );
    ensure!(state.funding_udt_type_script.is_none(), "CKB fixture only");
    let local_script: Script =
        serde_json::from_value::<ckb_jsonrpc_types::Script>(value["shutdown_script"].clone())?
            .into();
    ensure!(
        state.remote_shutdown_script.as_ref() == Some(&local_script),
        "local shutdown mismatch"
    );
    let material: fiber_json_types::ChannelOpenSignerMaterial =
        serde_json::from_value(value["signer_material"].clone())?;
    let actual = state
        .remote_channel_public_keys
        .clone()
        .context("remote keys")?;
    ensure!(
        material.base_public_keys.funding_pubkey == actual.funding_pubkey.into()
            && material.base_public_keys.tlc_base_key == actual.tlc_base_key.into(),
        "SDK keys do not match negotiated peer"
    );
    let amount = 500u128 * 100_000_000;
    ensure!(
        state.to_local_amount + u128::from(state.local_reserved_ckb_amount) == amount,
        "public contribution mismatch"
    );
    ensure!(
        state.to_remote_amount + u128::from(state.remote_reserved_ckb_amount) == amount,
        "tenant contribution mismatch"
    );
    ensure!(
        state.commitment_delay_epoch == 0x10000000001 && state.commitment_fee_rate == 1000,
        "unexpected negotiated delay or fee"
    );
    let lock: Script =
        serde_json::from_value::<ckb_jsonrpc_types::Script>(value["commitment_lock"].clone())?
            .into();
    let deps = value["funding_dep_count"]
        .as_u64()
        .context("funding deps")? as usize;
    let parameters = CommitmentParameters {
        remote_funding_key: state.local_channel_public_keys.funding_pubkey,
        remote_settlement_key: state.local_channel_public_keys.tlc_base_key,
        remote_shutdown_script: state.local_shutdown_script.clone(),
        commitment_fee: transaction_size(
            lock.clone().as_builder()
                .args(vec![0u8; state.commitment_contract_features.lock_args_len()].pack())
                .build(),
            None, deps,
        ),
        commitment_lock: lock,
        delay_epoch: (state.commitment_delay_epoch | 0xa000000000000000).to_le_bytes(),
        epoch_duration_ms: 2000,
        local_amount: amount,
        remote_amount: amount,
        local_reserved_ckb_amount: state.remote_reserved_ckb_amount,
        remote_reserved_ckb_amount: state.local_reserved_ckb_amount,
    };
    let close_fee = transaction_size(
        local_script,
        Some(state.local_shutdown_script.clone()),
        deps,
    );
    println!(
        "{}",
        json!({"parameters": parameters, "close_fee": close_fee,
        "remote_shutdown_script": ckb_jsonrpc_types::Script::from(state.local_shutdown_script)})
    );
    Ok(())
}

#[derive(Deserialize)]
struct Open {
    params: fiber_json_types::OpenChannelWithExternalFundingParams,
    funding_lock: ckb_jsonrpc_types::Script,
    commitment_lock: ckb_jsonrpc_types::Script,
    commitment_cell_deps: usize,
    ckb_rpc_url: String,
}

async fn control(
    agent: &mut Agent<HttpFiberRpc, FileSignerStore>,
    rpc: &HttpFiberRpc,
    store: &std::path::Path,
    chain: &mut Option<watchtower_chain::Chain>,
    value: Value,
) -> Result<Value> {
    let operation = value["operation"].as_str().context("operation")?;
    if operation == "open" {
        let open: Open = serde_json::from_value(value)?;
        // Contracts come from the local devnet deployment, not the LSP response.
        let network = OpeningNetwork {
            funding_lock: open.funding_lock.into(),
            commitment_lock: open.commitment_lock.into(),
            commitment_cell_deps: open.commitment_cell_deps,
            epoch_duration_ms: 2000,
            minimum_shutdown_fee: 100_000_000,
        };
        let opened = agent
            .open_tenant_channel(open.params, &network, &open.ckb_rpc_url)
            .await?;
        return Ok(serde_json::to_value(opened)?);
    }
    if operation == "watchtower-configure" {
        *chain = Some(
            watchtower_chain::Chain::new(serde_json::from_value(value["config"].clone())?).await?,
        );
        let configured = chain.as_ref().unwrap();
        return Ok(json!({"configured":true,
            "funding_deps":configured.funding_deps.iter().cloned().map(ckb_jsonrpc_types::CellDep::from).collect::<Vec<_>>(),
            "settlement_deps":configured.deps.iter().cloned().map(ckb_jsonrpc_types::CellDep::from).collect::<Vec<_>>()
        }));
    }
    let channel: Hash256 = value["channel_id"]
        .as_str()
        .context("channel id")?
        .parse()?;
    if operation == "watchtower-authorize" {
        agent
            .authorize(fiber_lsp_sdk_agent::FixtureAuthorization::Watchtower {
                channel_id: channel,
                destination: serde_json::from_value(value["destination"].clone())?,
                max_fee: value["max_fee"].as_u64().context("fee cap")?,
            })
            .await?;
        return Ok(json!({"saved":true}));
    }
    if operation == "watchtower-process" || operation == "watchtower-check" {
        return watchtower_chain::process(
            agent,
            rpc,
            store,
            chain.as_ref().context("adapter not configured")?,
            channel,
            operation == "watchtower-check",
        )
        .await;
    }
    let signer = agent
        .open_channel(agent.binding(channel).context("unbound channel")?)
        .await?;
    match operation {
        "invoice" => {
            let terms: PaymentAuthorization =
                serde_json::from_value(value["authorization"].clone())?;
            let preimage: Hash256 = value["preimage"].as_str().context("preimage")?.parse()?;
            signer.authorize_invoice(terms, preimage).await?;
        }
        "fulfill" => {
            let hash: Hash256 = value["payment_hash"].as_str().context("hash")?.parse()?;
            let preimage: Hash256 = value["preimage"].as_str().context("preimage")?.parse()?;
            ensure!(
                signer.recovery_records().await?.iter().any(|r| r
                    .settlement
                    .data
                    .tlcs
                    .iter()
                    .any(|t| t.payment_hash == hash)),
                "TLC must be verified before fulfillment"
            );
            signer.authorize_fulfillment(hash, preimage).await?;
        }
        "close" => {
            let fee = value["fee"].as_u64().context("fee")?;
            signer
                .authorize_close(CloseAuthorization {
                    fee,
                    local_fee_share: 0,
                    remote_fee_share: fee,
                })
                .await?;
        }
        "watchtower-records" => {
            let mut result = vec![];
            for r in signer.recovery_records().await? {
                ensure!(
                    r.settlement.data.tlcs.is_empty(),
                    "watchtower fixture requires no TLCs"
                );
                result.push(json!({
                    "reference":r.reference, "complete":r.complete_signature.is_some(),
                    "transaction":ckb_jsonrpc_types::Transaction::from(r.transaction.clone()),
                    "local_amount":r.settlement.data.local_amount.to_string(),
                    "remote_amount":r.settlement.data.remote_amount.to_string(),
                    "local_key":format!("0x{}",hex::encode(r.settlement.local_settlement_key.serialize())),
                    "remote_key":format!("0x{}",hex::encode(r.settlement.remote_settlement_key.serialize())),
                    "witness":format!("0x{}", hex::encode(fiber_types::settlement_data_to_witness(&r.settlement.data, r.reference.for_remote, fiber_types::CommitmentContractFeatures::from_lock_args(&r.transaction.raw().outputs().get(0).context("output")?.lock().args().raw_data()).map_err(anyhow::Error::msg)?, r.settlement.local_settlement_key, r.settlement.remote_settlement_key))),
                }));
            }
            return Ok(json!(result));
        }
        "records" => {
            return Ok(json!(signer.recovery_records().await?.iter().map(|r| json!({
                "version": r.reference.version, "for_remote": r.reference.for_remote,
                "complete": r.complete_signature.is_some(),
                "nonce_slot": r.content.nonce_slot(),
                "commitment_counter": r.content.commitment_counter(),
                "signing_message": format!("{:#x}", Hash256::from(r.content.signing_message())),
                "transaction_hash": match &r.content {
                    ChannelSigningContent::Musig2(content) => match &content.content {
                        Musig2SignableContent::CommitmentTransaction(tx) =>
                            Some(format!("{:#x}", tx.clone().into_view().hash())),
                        _ => None,
                    },
                    _ => None,
                },
                "tlcs": r.settlement.data.tlcs.iter().map(|t| json!({"payment_hash": format!("{:#x}", t.payment_hash), "expiry": t.expiry})).collect::<Vec<_>>()
            })).collect::<Vec<_>>()));
        }
        _ => return Err(anyhow!("unknown control operation")),
    }
    Ok(json!({"saved": true}))
}

#[tokio::main]
async fn main() -> Result<()> {
    if std::env::args().nth(1).as_deref() == Some("subscription-token") {
        return subscription_token();
    }
    if std::env::args().nth(1).as_deref() == Some("operator-subscription-token") {
        return operator_subscription_token();
    }
    if std::env::args().nth(1).as_deref() == Some("inspect-onchain") {
        let value: Value = serde_json::from_reader(std::io::stdin())?;
        let tx: Transaction =
            serde_json::from_value::<ckb_jsonrpc_types::Transaction>(value["transaction"].clone())?
                .into();
        let message = fiber_types::compute_tx_message(&tx);
        let mut result = json!({"tx_hash":format!("{:#x}",tx.calc_tx_hash()),
            "request_id":format!("0x{}",hex::encode(fiber_types::blake2b_hash_with_salt(tx.as_slice(), &[]))),
            "size":tx.serialized_size_in_block()});
        if let Some(s) = value["signature"].as_str() {
            let sig = hex::decode(s.trim_start_matches("0x"))?;
            ensure!(sig.len() == 65, "signature length");
            let sig = secp256k1::ecdsa::RecoverableSignature::from_compact(
                &sig[..64],
                secp256k1::ecdsa::RecoveryId::try_from(sig[64] as i32)?,
            )?;
            let key = secp256k1::SECP256K1
                .recover_ecdsa(&secp256k1::Message::from_digest(message), &sig)?;
            result["recovered_key"] = json!(format!("0x{}", hex::encode(key.serialize())));
        }
        println!("{result}");
        return Ok(());
    }
    if std::env::args().nth(1).as_deref() == Some("commitment-message") {
        let transaction: ckb_jsonrpc_types::Transaction =
            serde_json::from_reader(std::io::stdin())?;
        let transaction: Transaction = transaction.into();
        println!(
            "{:#x}",
            Hash256::from(fiber_types::compute_tx_message(&transaction))
        );
        return Ok(());
    }
    if std::env::args().nth(1).as_deref() == Some("opening") {
        return opening();
    }
    let args = Args::parse();
    let store = args.store.clone();
    let mut chain = None;
    let rpc = HttpFiberRpc::new(&args.rpc, args.operator_token)?;
    let mut agent = Agent::open(
        rpc.clone(),
        AgentConfig {
            store_dir: args.store,
            status_file: Some(args.status_file),
        },
    )
    .await?;
    agent.initialize().await?;
    let mut events = EventStream::connect(&args.ws_rpc, agent.tenant_token()?)?;
    let listener = TcpListener::bind(&args.control_addr).await?;
    loop {
        tokio::select! {
            accepted = listener.accept() => {
                let (stream, _) = accepted?;
                let mut stream = BufReader::new(stream);
                let mut line = String::new();
                stream.read_line(&mut line).await?;
                let response = match serde_json::from_str::<Value>(&line) {
                    Ok(value) => {
                        let watchtower = value["operation"].as_str().is_some_and(|op| op.starts_with("watchtower-"));
                        let action = control(&mut agent, &rpc, &store, &mut chain, value);
                        let result = if watchtower {
                            tokio::time::timeout(std::time::Duration::from_secs(9), action).await
                                .unwrap_or_else(|_| Err(anyhow!("watchtower control deadline exceeded")))
                        } else { action.await };
                        match result {
                            Ok(result) => json!({"result": result}),
                            Err(error) => json!({"error": format!("{error:#}")}),
                        }
                    },
                    Err(error) => json!({"error": error.to_string()}),
                };
                stream.get_mut().write_all(format!("{response}\n").as_bytes()).await?;
            }
            delivery = events.next() => {
                let delivery = delivery.context("tenant event reader stopped")?;
                let event = delivery.event;
                let event_evidence=serde_json::to_value(&event)?;
                let approved_channel = if let fiber_json_types::SubscriptionEvent::WatchtowerSigning(ref work) = event {
                    let id: Hash256 = work.channel_id.into();
                    let policies: Value = std::fs::read(store.join("watchtower-approvals.json")).ok()
                        .and_then(|b| serde_json::from_slice(&b).ok()).unwrap_or(Value::Null);
                    (chain.is_some() && policies.get(format!("{id:#x}")).is_some()).then_some(id)
                } else { None };
                let result = if let Some(id) = approved_channel {
                    tokio::time::timeout(std::time::Duration::from_secs(9), watchtower_chain::process(&agent, &rpc, &store, chain.as_ref().unwrap(), id, args.watchtower_check_only)).await.unwrap_or_else(|_| Err(anyhow!("watchtower event deadline exceeded"))).map(|_| ())
                } else { agent.handle_event(event).await };
                // A deliberately held, already saved signature is a test
                // checkpoint, not a broken subscription. Real RPC/SDK errors
                // still use the upstream reconnect path, including HTTP timeout.
                let held_by_test = args.ack_held_events && result.as_ref().err()
                    .is_some_and(|error| format!("{error:#}") == "test driver pauses this submission");
                if event_evidence["type"]=="watchtower_signing" {
                    eprintln!("watchtower-event: {}",json!({"event":event_evidence,"error":result.as_ref().err().map(|e|format!("{e:#}")),"adapted":approved_channel.is_some()}));
                }
                let _ = delivery.processed.send(result.is_ok() || held_by_test);
                if held_by_test {
                    eprintln!("event: saved signature held by test; subscription stays connected");
                } else if let Err(error) = result {
                    eprintln!("event: {error:#}");
                }
            }
        }
    }
}
