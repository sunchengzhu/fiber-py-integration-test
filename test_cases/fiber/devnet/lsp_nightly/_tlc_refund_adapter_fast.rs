//! SDK-only G2 sample for LSP-REFUND-F2-02; no node, RPC or on-chain signing.
use anyhow::{ensure, Context, Result};
use ckb_types::{
    core::{EpochNumberWithFraction, TransactionBuilder},
    packed::{Bytes, CellInput, CellOutput, OutPoint, Script, Transaction},
    prelude::*,
};
use fiber_lsp_sdk::{
    ChainVerifier, ChannelSigner, ChannelSigningContent, CommitmentContext, CommitmentCounter,
    CommitmentParameters, MemoryStore, Musig2SignableContent, Musig2SigningContent, NoncePurpose,
    NonceSlot, OnchainKeyPurpose, OnchainSigningContent, OnchainSpendAuthorization,
    OwnedSettlementBinding, PaymentAuthorization, RecoveryRecord, RootKey, RootSigner, SignerError,
    SigningSessionEvidence, VerifiedCell,
};
use fiber_types::{
    blake2b_hash_with_salt, settlement_data_to_witness, settlement_witness_hash,
    try_derive_tlc_pubkey, ChannelSigningTransition, CommitmentContractFeatures, Hash256,
    HashAlgorithm, InMemorySigner, SettlementData, SettlementTlc, TLCId,
};
use musig2::{AggNonce, KeyAggContext};
use serde_json::{json, Value};
use std::{io::Write, sync::Mutex, time::Instant};

const CASE_ID: &str = "LSP-REFUND-F2-SDK";
const AMOUNT: u64 = 100_000_000;
const LOCAL_AMOUNT: u64 = 500 * AMOUNT;
const REMOTE_AMOUNT: u64 = 500 * AMOUNT;
const CLOSE_FEE: u64 = 1_000;
const SPEND_FEE: u64 = 1_000;
const SPONSOR: u64 = 200 * AMOUNT;
const ACCEPTED_AT_MS: u64 = 100;
const EXPIRY_MS: u64 = 20_000;

fn hex_bytes(bytes: &[u8]) -> String {
    format!("0x{}", hex::encode(bytes))
}

fn digest(bytes: &[u8]) -> String {
    hex_bytes(&blake2b_hash_with_salt(bytes, &[]))
}

fn emit(value: Value) -> Result<()> {
    let mut stdout = std::io::stdout().lock();
    serde_json::to_writer(&mut stdout, &value)?;
    writeln!(stdout)?;
    stdout.flush()?;
    Ok(())
}

fn rpc_transaction(tx: &Transaction) -> ckb_jsonrpc_types::Transaction {
    tx.clone().into()
}

fn rpc_point(point: &OutPoint) -> ckb_jsonrpc_types::OutPoint {
    point.clone().into()
}

fn public_cell(cell: &VerifiedCell) -> Value {
    json!({"output":ckb_jsonrpc_types::CellOutput::from(cell.output.clone()),
        "data":hex_bytes(&cell.data)})
}

fn public_content(content: &OnchainSigningContent) -> Value {
    let purpose = match content.key_purpose {
        OnchainKeyPurpose::Settlement => json!({"type":"Settlement"}),
        OnchainKeyPurpose::Tlc { commitment_number } => {
            json!({"type":"Tlc","commitment_number":commitment_number})
        }
    };
    json!({"key_purpose":purpose,"transaction":rpc_transaction(&content.transaction)})
}

fn public_authorization(auth: &OnchainSpendAuthorization) -> Value {
    json!({"source":auth.source,
        "destination":ckb_jsonrpc_types::Script::from(auth.destination.clone()),
        "fee":auth.fee,
        "additional_inputs":auth.additional_inputs.iter().map(rpc_point).collect::<Vec<_>>(),
        "cell_deps":auth.cell_deps.iter().cloned()
            .map(ckb_jsonrpc_types::CellDep::from).collect::<Vec<_>>()})
}

fn invalid(reason: &str) -> SignerError {
    SignerError::InvalidContent(format!("fixed SDK fixture: {reason}"))
}

fn rebuild_transaction(
    tx: &Transaction,
    outputs: Vec<CellOutput>,
    witnesses: Vec<Bytes>,
) -> Transaction {
    let raw = tx.raw();
    TransactionBuilder::default()
        .version(raw.version())
        .cell_deps(raw.cell_deps().into_iter().collect::<Vec<_>>())
        .header_deps(raw.header_deps().into_iter().collect::<Vec<_>>())
        .inputs(raw.inputs().into_iter().collect::<Vec<_>>())
        .outputs(outputs)
        .outputs_data(raw.outputs_data().into_iter().collect::<Vec<_>>())
        .witnesses(witnesses)
        .build()
        .data()
}

fn mutated_witness(
    request: &OnchainSigningContent,
    feature: &str,
    name: &str,
) -> Result<OnchainSigningContent> {
    let hlen = if feature == "legacy" { 20 } else { 32 };
    let mut request = request.clone();
    let witnesses: Vec<Bytes> = request.transaction.witnesses().into_iter().collect();
    let mut witness = witnesses
        .first()
        .context("missing settlement witness")?
        .raw_data()
        .to_vec();
    // witness = 17-byte unlock prefix, then body[0]=TLC count, body[1]=entry.
    let entry = 17 + 1;
    match name {
        "wrong_tlc_hash" => {
            witness[entry + 17 + hlen / 2] ^= 1;
        }
        "wrong_tlc_amount" => {
            let start = entry + 1;
            let mut amount = u128::from_le_bytes(
                witness[start..start + 16]
                    .try_into()
                    .context("TLC amount width")?,
            );
            amount += 1;
            witness[start..start + 16].copy_from_slice(&amount.to_le_bytes());
        }
        "wrong_tlc_direction" => {
            // Preserve the SHA-256 algorithm bits and flip only the direction bit.
            witness[entry] ^= 1;
        }
        _ => anyhow::bail!("unknown witness mutation {name}"),
    }
    let mut updated = witnesses;
    updated[0] = Bytes::from(witness);
    let outputs = request.transaction.raw().outputs().into_iter().collect();
    request.transaction = rebuild_transaction(&request.transaction, outputs, updated);
    Ok(request)
}

fn mutated_residual(request: &OnchainSigningContent) -> Result<OnchainSigningContent> {
    let mut request = request.clone();
    let mut outputs: Vec<CellOutput> = request.transaction.raw().outputs().into_iter().collect();
    let output = outputs.get(0).context("missing refund output")?;
    let lock = output.lock();
    let mut args = lock.args().raw_data().to_vec();
    args[36] ^= 1;
    let lock = lock.as_builder().args(args.pack()).build();
    outputs[0] = output.clone().as_builder().lock(lock).build();
    let witnesses = request.transaction.witnesses().into_iter().collect();
    request.transaction = rebuild_transaction(&request.transaction, outputs, witnesses);
    Ok(request)
}

fn expected_reason(name: &str) -> Option<&'static str> {
    match name {
        "wrong_tlc_index" => Some("commitment validation: wrong TLC signing key"),
        "wrong_tlc_hash" | "wrong_tlc_amount" | "wrong_tlc_direction" => {
            Some("commitment validation: settlement witness is not committed by live input")
        }
        "wrong_tlc_residual" => Some("commitment validation: unapproved on-chain destination"),
        _ => None,
    }
}

/// These are declared in-memory premises, not observations of a live chain.
struct FixtureChain {
    ancestor: Hash256,
    source_point: OutPoint,
    source: VerifiedCell,
    sponsor_point: OutPoint,
    sponsor: VerifiedCell,
    expected_inputs: Vec<CellInput>,
    median_ms: u64,
    commitment_epoch: u64,
    tip_epoch: u64,
    calls: Mutex<Vec<Value>>,
}

impl FixtureChain {
    fn log(&self, method: &str, params: Value, result: Value) -> Result<(), SignerError> {
        self.calls
            .lock()
            .map_err(|_| invalid("audit lock poisoned"))?
            .push(json!({"method":method,"params":params,"result":result}));
        Ok(())
    }

    fn take_calls(&self) -> Result<Vec<Value>> {
        Ok(std::mem::take(&mut *self.calls.lock().map_err(|_| {
            anyhow::anyhow!("fixture audit lock poisoned")
        })?))
    }

    fn public_state(&self) -> Value {
        json!({"ancestor":self.ancestor,
            "source_outpoint":rpc_point(&self.source_point),"source_cell":public_cell(&self.source),
            "sponsor_outpoint":rpc_point(&self.sponsor_point),"sponsor_cell":public_cell(&self.sponsor),
            "expected_inputs":self.expected_inputs.iter().cloned()
                .map(ckb_jsonrpc_types::CellInput::from).collect::<Vec<_>>(),
            "median_time_ms":self.median_ms,"commitment_epoch":self.commitment_epoch,
            "tip_epoch":self.tip_epoch})
    }
}

#[async_trait::async_trait]
impl ChainVerifier for FixtureChain {
    async fn live_cell(&self, point: &OutPoint) -> Result<VerifiedCell, SignerError> {
        let cell = if point == &self.source_point {
            Some(&self.source)
        } else if point == &self.sponsor_point {
            Some(&self.sponsor)
        } else {
            None
        };
        self.log(
            "live_cell",
            json!({"outpoint":rpc_point(point)}),
            cell.map(public_cell)
                .unwrap_or_else(|| json!({"error":"unknown outpoint"})),
        )?;
        cell.cloned().ok_or_else(|| invalid("unknown outpoint"))
    }

    async fn verify_commitment_lineage(
        &self,
        source: Hash256,
        point: &OutPoint,
    ) -> Result<(), SignerError> {
        let accepted = source == self.ancestor && point == &self.source_point;
        self.log(
            "verify_commitment_lineage",
            json!({"source":source,"outpoint":rpc_point(point)}),
            json!({"accepted":accepted}),
        )?;
        if accepted {
            Ok(())
        } else {
            Err(invalid("unknown ancestry"))
        }
    }

    async fn verify_maturity(&self, inputs: &[CellInput]) -> Result<(), SignerError> {
        // Only the exact relative-epoch source and absolute-timestamp sponsor
        // are supported. Unknown or modified inputs fail this fixture boundary.
        let exact_inputs = inputs == self.expected_inputs.as_slice();
        let relative: u64 = self.expected_inputs[0].since().unpack();
        let absolute: u64 = self.expected_inputs[1].since().unpack();
        let delay = EpochNumberWithFraction::from_full_value(relative & 0x00ff_ffff_ffff_ffff);
        let accepted = exact_inputs
            && relative >> 56 == 0xa0
            && delay.index() == 0
            && delay.length() == 1
            && self.tip_epoch >= self.commitment_epoch + delay.number()
            && absolute >> 56 == 0x40
            && self.median_ms / 1000 > (absolute & 0x00ff_ffff_ffff_ffff);
        self.log(
            "verify_maturity",
            json!({"inputs":inputs.iter().cloned()
            .map(ckb_jsonrpc_types::CellInput::from).collect::<Vec<_>>()}),
            json!({"accepted":accepted,"median_time_ms":self.median_ms,
                "commitment_epoch":self.commitment_epoch,"tip_epoch":self.tip_epoch}),
        )?;
        if accepted {
            Ok(())
        } else {
            Err(invalid("input is not mature in fixed fixture"))
        }
    }

    async fn median_time_ms(&self) -> Result<u64, SignerError> {
        self.log(
            "median_time_ms",
            json!({}),
            json!({"median_time_ms":self.median_ms}),
        )?;
        Ok(self.median_ms)
    }
}

/// Create one remote commitment via public SDK validation and signing APIs.
async fn record_commitment(
    signer: &ChannelSigner<MemoryStore>,
    remote: &InMemorySigner,
    funding: &Transaction,
    parameters: &CommitmentParameters,
    version: u64,
    data: SettlementData,
    features: CommitmentContractFeatures,
) -> Result<RecoveryRecord> {
    let keys = signer.public_material().base_public_keys;
    let mut funding_keys = [keys.funding_pubkey, remote.funding_key.pubkey()];
    funding_keys.sort();
    let key_agg_ctx = KeyAggContext::new(funding_keys)?;
    let lock_ctx = KeyAggContext::new([keys.funding_pubkey, remote.funding_key.pubkey()])?;
    let point: musig2::secp::Point = lock_ctx.aggregated_pubkey();
    let mut args = blake2b_hash_with_salt(&point.serialize_xonly(), &[])[..20].to_vec();
    args.extend_from_slice(&parameters.delay_epoch);
    args.extend_from_slice(&version.to_be_bytes());
    args.extend_from_slice(&settlement_witness_hash(
        &data,
        true,
        features,
        keys.tlc_base_key,
        remote.tlc_base_key.pubkey(),
    ));
    args.push(0);
    if features.has_full_payment_hash() {
        args.push(features.bits());
    }
    let tx = TransactionBuilder::default()
        .input(CellInput::new(OutPoint::new(funding.calc_tx_hash(), 0), 0))
        .output(
            funding
                .raw()
                .outputs()
                .get(0)
                .context("funding output")?
                .as_builder()
                .capacity(LOCAL_AMOUNT + REMOTE_AMOUNT - CLOSE_FEE)
                .lock(
                    parameters
                        .commitment_lock
                        .clone()
                        .as_builder()
                        .args(args.pack())
                        .build(),
                )
                .build(),
        )
        .output_data(ckb_types::packed::Bytes::default())
        .build()
        .data();
    let slot = NonceSlot {
        purpose: NoncePurpose::Commitment,
        commitment_number: version,
    };
    let nonce = signer.get_musig2_nonce(slot).await?.public_nonce;
    let mut nonce_seed = [7; 32];
    nonce_seed[..8].copy_from_slice(&version.to_le_bytes());
    let remote_nonce = musig2::SecNonce::build(nonce_seed).build().public_nonce();
    let content = ChannelSigningContent::Musig2(Musig2SigningContent {
        slot,
        commitment_counter: Some(CommitmentCounter::Local),
        key_agg_ctx,
        agg_nonce: AggNonce::sum([nonce, remote_nonce.clone()]),
        content: Musig2SignableContent::CommitmentTransaction(tx),
    });
    let context = CommitmentContext {
        session: SigningSessionEvidence {
            peer_public_nonce: remote_nonce,
            peer_partial_signature: None,
        },
        transition: ChannelSigningTransition::SendCommitmentSigned,
        settlement: OwnedSettlementBinding {
            data,
            local_settlement_key: keys.tlc_base_key,
            remote_settlement_key: remote.tlc_base_key.pubkey(),
            for_remote: Some(true),
        },
    };
    let prepared = signer
        .prepare_commitment(content, context, ACCEPTED_AT_MS)
        .await?;
    signer.sign_commitment(prepared, ACCEPTED_AT_MS).await?;
    let mut records = signer
        .recovery_records()
        .await?
        .into_iter()
        .filter(|r| r.reference.for_remote && r.reference.version == version);
    let record = records
        .next()
        .context("missing newly verified recovery record")?;
    ensure!(records.next().is_none(), "ambiguous recovery record");
    Ok(record)
}

struct Baseline {
    signer: ChannelSigner<MemoryStore>,
    store: MemoryStore,
    chain: FixtureChain,
    request: OnchainSigningContent,
    authorization: OnchainSpendAuthorization,
    creation_index: u64,
    public: Value,
}

async fn baseline(feature: &str, features: CommitmentContractFeatures) -> Result<Baseline> {
    let store = MemoryStore::default();
    let root = RootSigner::create(RootKey::import([42; 32])?, store.clone()).await?;
    let signer = root.create_channel().await?;
    let remote = InMemorySigner::generate_from_seed(b"F2 fast fixture peer, never a live wallet");
    let keys = signer.public_material().base_public_keys;
    let mut funding_keys = [keys.funding_pubkey, remote.funding_key.pubkey()];
    funding_keys.sort();
    let ctx = KeyAggContext::new(funding_keys)?;
    let point: musig2::secp::Point = ctx.aggregated_pubkey();
    let funding_lock = Script::new_builder()
        .args(
            blake2b_hash_with_salt(&point.serialize_xonly(), &[])[..20]
                .to_vec()
                .pack(),
        )
        .build();
    let funding_input = OutPoint::new([7u8; 32].pack(), 0);
    let funding = TransactionBuilder::default()
        .input(CellInput::new(funding_input.clone(), 0))
        .output(
            CellOutput::new_builder()
                .capacity(LOCAL_AMOUNT + REMOTE_AMOUNT)
                .lock(funding_lock)
                .build(),
        )
        .output_data(ckb_types::packed::Bytes::default())
        .build()
        .data();
    let destination = Script::new_builder()
        .code_hash([9u8; 32].pack())
        .hash_type(1u8)
        .args([42u8; 20].pack())
        .build();
    let delay = 0xa000_0000_0000_0000u64 | EpochNumberWithFraction::new(1, 0, 1).full_value();
    let parameters = CommitmentParameters {
        remote_shutdown_script: Script::default(),
        remote_funding_key: remote.funding_key.pubkey(),
        remote_settlement_key: remote.tlc_base_key.pubkey(),
        commitment_lock: Script::new_builder()
            .code_hash([3u8; 32].pack())
            .hash_type(1u8)
            .build(),
        delay_epoch: delay.to_le_bytes(),
        epoch_duration_ms: 2_000,
        commitment_fee: CLOSE_FEE,
        local_amount: LOCAL_AMOUNT.into(),
        remote_amount: REMOTE_AMOUNT.into(),
        local_reserved_ckb_amount: 100 * AMOUNT,
        remote_reserved_ckb_amount: 100 * AMOUNT,
    };
    signer
        .approve_opening(
            &funding,
            0,
            destination.clone(),
            &[funding_input],
            parameters.clone(),
        )
        .await?;
    // The hash is a fixed public test value. No preimage is given to this signer.
    let payment_hash: Hash256 = [0x35u8; 32].into();
    let payment = PaymentAuthorization {
        payment_hash,
        hash_algorithm: HashAlgorithm::Sha256,
        inbound: false,
        amount: AMOUNT.into(),
        expires_at_ms: 10_000,
        min_tlc_expiry_delta_ms: 1_000,
        max_tlc_expiry_ms: 100_000,
    };
    signer.authorize_payment(payment.clone()).await?;
    let opening_record = record_commitment(
        &signer,
        &remote,
        &funding,
        &parameters,
        1,
        SettlementData {
            local_amount: LOCAL_AMOUNT.into(),
            remote_amount: REMOTE_AMOUNT.into(),
            tlcs: vec![],
        },
        features,
    )
    .await?;
    // Read k from the actual preceding history before creating this TLC.
    let creation_index = opening_record.reference.version;
    let creation_point = signer.get_commitment_point(creation_index);
    let local_public_key =
        try_derive_tlc_pubkey(&keys.tlc_base_key, &creation_point).map_err(anyhow::Error::msg)?;
    let remote_public_key = remote.derive_tlc_key(creation_index).pubkey();
    let tlc = SettlementTlc {
        tlc_id: TLCId::Offered(4),
        hash_algorithm: HashAlgorithm::Sha256,
        payment_amount: AMOUNT.into(),
        payment_hash,
        expiry: EXPIRY_MS,
        local_key: None,
        local_key_pubkey: Some(local_public_key),
        local_key_commitment_number: Some(creation_index),
        remote_key: remote_public_key,
    };
    let record = record_commitment(
        &signer,
        &remote,
        &funding,
        &parameters,
        opening_record.reference.version + 1,
        SettlementData {
            local_amount: (LOCAL_AMOUNT - AMOUNT).into(),
            remote_amount: REMOTE_AMOUNT.into(),
            tlcs: vec![tlc],
        },
        features,
    )
    .await?;
    ensure!(
        record.settlement.data.tlcs.len() == 1,
        "expected single verified TLC"
    );
    let verified_tlc = &record.settlement.data.tlcs[0];
    ensure!(
        verified_tlc.local_key.is_none(),
        "verified record unexpectedly contains a secret"
    );
    ensure!(
        verified_tlc.local_key_commitment_number == Some(creation_index)
            && verified_tlc.local_key_pubkey == Some(local_public_key),
        "TLC creation history changed"
    );
    ensure!(
        creation_index == 1 && record.reference.version == 2,
        "unexpected fixture history"
    );
    let body = settlement_data_to_witness(
        &record.settlement.data,
        true,
        features,
        record.settlement.local_settlement_key,
        record.settlement.remote_settlement_key,
    );
    let entry_len = 65 + features.payment_hash_len();
    let mut remaining = body.clone();
    remaining.drain(1..1 + entry_len);
    remaining[0] = 0;
    let source = record
        .transaction
        .raw()
        .outputs()
        .get(0)
        .context("commitment output")?;
    let original_args = source.lock().args().raw_data();
    let mut residual_args = original_args[..36].to_vec();
    residual_args.extend_from_slice(&blake2b_hash_with_salt(&remaining, &[])[..20]);
    residual_args.push(1);
    residual_args.extend_from_slice(&original_args[57..]);
    let residual = source
        .clone()
        .as_builder()
        .capacity(LOCAL_AMOUNT + REMOTE_AMOUNT - CLOSE_FEE - AMOUNT)
        .lock(
            source
                .lock()
                .as_builder()
                .args(residual_args.pack())
                .build(),
        )
        .build();
    let source_point = OutPoint::new(record.transaction.calc_tx_hash(), 0);
    let sponsor_point = OutPoint::new([88u8; 32].pack(), 0);
    let inputs = vec![
        CellInput::new(source_point.clone(), delay),
        CellInput::new(
            sponsor_point.clone(),
            0x4000_0000_0000_0000 | (EXPIRY_MS / 1000),
        ),
    ];
    let mut witness = vec![16, 0, 0, 0, 16, 0, 0, 0, 16, 0, 0, 0, 16, 0, 0, 0, 1];
    witness.extend_from_slice(&body);
    witness.extend_from_slice(&[0, 0]); // TLC array index zero; timeout, no preimage.
    witness.extend_from_slice(&[0; 65]);
    let transaction = TransactionBuilder::default()
        .set_inputs(inputs.clone())
        .output(residual)
        .output_data(ckb_types::packed::Bytes::default())
        .output(
            CellOutput::new_builder()
                .capacity(SPONSOR + AMOUNT - SPEND_FEE)
                .lock(destination.clone())
                .build(),
        )
        .output_data(ckb_types::packed::Bytes::default())
        .witness(witness.pack())
        .build()
        .data();
    let request = OnchainSigningContent {
        key_purpose: OnchainKeyPurpose::Tlc {
            commitment_number: creation_index,
        },
        transaction,
    };
    let authorization = OnchainSpendAuthorization {
        source: record.reference.clone(),
        destination: destination.clone(),
        fee: SPEND_FEE,
        additional_inputs: vec![sponsor_point.clone()],
        cell_deps: vec![],
    };
    let chain = FixtureChain {
        ancestor: record.reference.tx_hash,
        source_point,
        source: VerifiedCell {
            output: source,
            data: vec![],
        },
        sponsor_point,
        sponsor: VerifiedCell {
            output: CellOutput::new_builder()
                .capacity(SPONSOR)
                .lock(destination)
                .build(),
            data: vec![],
        },
        expected_inputs: inputs,
        median_ms: EXPIRY_MS + 1_000,
        commitment_epoch: 0,
        tip_epoch: 2,
        calls: Mutex::new(vec![]),
    };
    let public = json!({"type":"baseline","schema_version":1,"case_id":CASE_ID,"feature":feature,
        "feature_bits":features.bits(),"payment_hash_len":features.payment_hash_len(),
        "funding":rpc_transaction(&funding),"opening_parameters":parameters,
        "payment_authorization":payment,
        "creation":{"previous_reference":opening_record.reference,"tlc_id":verified_tlc.tlc_id,
            "derivation_index":creation_index,"commitment_point":hex_bytes(&creation_point.serialize()),
            "local_base_public_key":hex_bytes(&keys.tlc_base_key.serialize()),
            "local_public_key":hex_bytes(&local_public_key.serialize()),
            "remote_public_key":hex_bytes(&remote_public_key.serialize()),"witness_index":0},
        "record":{"reference":record.reference,"transaction":rpc_transaction(&record.transaction),
            "local_amount":record.settlement.data.local_amount.to_string(),
            "remote_amount":record.settlement.data.remote_amount.to_string(),
            "local_settlement_key":hex_bytes(&record.settlement.local_settlement_key.serialize()),
            "remote_settlement_key":hex_bytes(&record.settlement.remote_settlement_key.serialize()),
            "tlcs":[{"tlc_id":verified_tlc.tlc_id,"payment_hash":verified_tlc.payment_hash,
                "hash_algorithm":verified_tlc.hash_algorithm,"payment_amount":verified_tlc.payment_amount.to_string(),
                "expiry":verified_tlc.expiry,"inbound":verified_tlc.tlc_id.is_received() == record.reference.for_remote,
                "local_key_commitment_number":verified_tlc.local_key_commitment_number,
                "local_public_key":hex_bytes(&local_public_key.serialize()),
                "remote_public_key":hex_bytes(&remote_public_key.serialize()),
                "entry":hex_bytes(&body[1..1+entry_len])}]},
        "witness_body":hex_bytes(&body),"remaining_witness_body":hex_bytes(&remaining),
        "request":public_content(&request),"authorization":public_authorization(&authorization),
        "chain":chain.public_state(),"store_digest":digest(&store.snapshot()?),
        "digest_algorithm":"ckb_blake2b_256"});
    Ok(Baseline {
        signer,
        store,
        chain,
        request,
        authorization,
        creation_index,
        public,
    })
}

async fn prepare(
    feature: &str,
    name: &str,
    baseline: &Baseline,
    content: OnchainSigningContent,
) -> Result<()> {
    ensure!(
        baseline.chain.take_calls()?.is_empty(),
        "unreported chain calls"
    );
    let before = baseline.store.snapshot()?;
    let started = Instant::now();
    let result = baseline
        .signer
        .prepare_onchain(
            content.clone(),
            baseline.authorization.clone(),
            &baseline.chain,
        )
        .await;
    let elapsed_ms = started.elapsed().as_secs_f64() * 1000.0;
    let after = baseline.store.snapshot()?;
    let (returned_content, returned_authorization, error) = match &result {
        Ok(prepared) => {
            let ChannelSigningContent::Onchain(returned) = prepared.content() else {
                anyhow::bail!("SDK prepared the wrong signing intent");
            };
            (
                public_content(returned),
                public_authorization(
                    prepared
                        .onchain_authorization()
                        .context("SDK omitted on-chain authorization")?,
                ),
                Value::Null,
            )
        }
        Err(error) => {
            let debug = format!("{error:?}");
            let variant = debug.split(['(', '{']).next().unwrap_or(&debug).trim();
            let reason = match error {
                SignerError::InvalidContent(reason) => Some(reason.as_str()),
                _ => None,
            };
            (
                Value::Null,
                Value::Null,
                json!({"variant":variant,"reason":reason,
                "display":error.to_string(),"debug":debug}),
            )
        }
    };
    emit(
        json!({"type":"call","schema_version":1,"case_id":CASE_ID,"feature":feature,"name":name,
        "input":public_content(&content),"authorization":public_authorization(&baseline.authorization),
        "returned_content":returned_content,"returned_authorization":returned_authorization,"error":error,
        "elapsed_ms":elapsed_ms,"store_before_digest":digest(&before),"store_after_digest":digest(&after),
        "chain_calls":baseline.chain.take_calls()?}),
    )?;
    ensure!(before == after, "prepare_onchain changed signer store");
    if let Some(expected) = expected_reason(name) {
        ensure!(
            matches!(&result, Err(SignerError::InvalidContent(reason)) if reason == expected),
            "expected SDK InvalidContent({expected})"
        );
    } else {
        result.context("valid SDK preparation failed")?;
    }
    Ok(())
}

#[tokio::main(flavor = "current_thread")]
async fn main() -> Result<()> {
    ensure!(
        std::env::args_os().len() == 1,
        "this G2 helper takes no arguments"
    );
    let started = Instant::now();
    for (feature, features) in [
        ("legacy", CommitmentContractFeatures::LEGACY),
        (
            "full_hash",
            CommitmentContractFeatures::ONCHAIN_FULL_PAYMENT_HASH,
        ),
    ] {
        let baseline = baseline(feature, features).await?;
        emit(baseline.public.clone())?;
        let mut wrong_index = baseline.request.clone();
        wrong_index.key_purpose = OnchainKeyPurpose::Tlc {
            commitment_number: baseline.creation_index + 1,
        };
        let cases = [
            ("positive_before", baseline.request.clone()),
            ("wrong_tlc_index", wrong_index),
            (
                "wrong_tlc_hash",
                mutated_witness(&baseline.request, feature, "wrong_tlc_hash")?,
            ),
            (
                "wrong_tlc_amount",
                mutated_witness(&baseline.request, feature, "wrong_tlc_amount")?,
            ),
            (
                "wrong_tlc_direction",
                mutated_witness(&baseline.request, feature, "wrong_tlc_direction")?,
            ),
            ("wrong_tlc_residual", mutated_residual(&baseline.request)?),
            ("positive_after", baseline.request.clone()),
        ];
        for (name, content) in cases {
            prepare(feature, name, &baseline, content).await?;
        }
    }
    emit(
        json!({"type":"complete","schema_version":1,"case_id":CASE_ID,"features":2,"calls":14,
        "elapsed_ms":started.elapsed().as_secs_f64()*1000.0}),
    )
}
