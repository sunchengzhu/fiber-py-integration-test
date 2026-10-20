//! Local test controls around the unmodified, checked SDK agent.
use anyhow::{anyhow, ensure, Context, Result};
use ckb_types::{core::TransactionBuilder, packed::*, prelude::*};
use clap::Parser;
use fiber_lsp_sdk::{
    ChannelSigningContent, CloseAuthorization, CommitmentParameters, Musig2SignableContent,
    OpeningNetwork, PaymentAuthorization,
};
use fiber_lsp_sdk_agent::{Agent, AgentConfig, FileSignerStore, HttpFiberRpc};
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
    #[arg(long)]
    store: PathBuf,
    #[arg(long)]
    status_file: PathBuf,
    #[arg(long)]
    control_addr: String,
    #[arg(long)]
    operator_token: String,
    /// Deadline tests save real signatures for explicit submission by Python.
    #[arg(long)]
    ack_held_events: bool,
}

// The fee template is fixed by the devnet contracts, not a signing response.
fn transaction_size(lock: Script, close: Option<Script>, dep_count: usize) -> u64 {
    let first_lock = if close.is_some() {
        lock
    } else {
        lock.as_builder().args(vec![0u8; 57].pack()).build()
    };
    let mut builder = TransactionBuilder::default()
        .cell_deps(vec![CellDep::default(); dep_count].pack())
        .input(CellInput::default())
        .output(CellOutput::new_builder().lock(first_lock).build())
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
        commitment_fee: transaction_size(lock.clone(), None, deps),
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

async fn control(agent: &mut Agent<HttpFiberRpc, FileSignerStore>, value: Value) -> Result<Value> {
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
    let channel: Hash256 = value["channel_id"]
        .as_str()
        .context("channel id")?
        .parse()?;
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
    let mut events = rpc.subscribe_events(agent.tenant_token()?)?;
    let listener = TcpListener::bind(&args.control_addr).await?;
    loop {
        tokio::select! {
            accepted = listener.accept() => {
                let (stream, _) = accepted?;
                let mut stream = BufReader::new(stream);
                let mut line = String::new();
                stream.read_line(&mut line).await?;
                let response = match serde_json::from_str(&line) {
                    Ok(value) => match control(&mut agent, value).await {
                        Ok(result) => json!({"result": result}),
                        Err(error) => json!({"error": format!("{error:#}")}),
                    },
                    Err(error) => json!({"error": error.to_string()}),
                };
                stream.get_mut().write_all(format!("{response}\n").as_bytes()).await?;
            }
            delivery = events.next() => {
                let delivery = delivery.context("tenant event reader stopped")?;
                let result = agent.handle_event(delivery.event).await;
                // A deliberately held, already saved signature is a test
                // checkpoint, not a broken SSE connection. Real RPC/SDK errors
                // still use the upstream reconnect path, including HTTP timeout.
                let held_by_test = args.ack_held_events && result.as_ref().err()
                    .is_some_and(|error| format!("{error:#}") == "test driver pauses this submission");
                let _ = delivery.processed.send(result.is_ok() || held_by_test);
                if held_by_test {
                    eprintln!("event: saved signature held by test; SSE stays connected");
                } else if let Err(error) = result {
                    eprintln!("event: {error:#}");
                }
            }
        }
    }
}
