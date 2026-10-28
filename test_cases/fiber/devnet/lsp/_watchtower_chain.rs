//! Test-only adapter for the repository's independently deployed Type ID contracts.
use anyhow::{ensure, Context, Result};
use ckb_types::{packed::*, prelude::*};
use fiber_lsp_sdk::{ChainVerifier, OnchainSpendAuthorization, SignerError, VerifiedCell};
use fiber_lsp_sdk_agent::{Agent, DevChain, FiberRpc, FileSignerStore, HttpFiberRpc};
use fiber_types::{CommitmentContractFeatures, Hash256};
use serde::Deserialize;
use serde_json::{json, Value};
use std::{
    collections::HashMap,
    io::Write,
    path::PathBuf,
    sync::{Arc, Mutex},
};

#[derive(Clone, Deserialize)]
pub struct Config {
    pub url: String,
    pub scripts: Value,
    pub contracts: PathBuf,
    pub audit: PathBuf,
}
#[derive(Clone)]
pub struct Chain {
    config: Config,
    delegate: DevChain,
    client: reqwest::Client,
    pub funding_deps: Vec<CellDep>,
    pub deps: Vec<CellDep>,
    pub funding: Option<OutPoint>,
    rounds: Arc<Mutex<HashMap<String, Vec<String>>>>,
}
impl Chain {
    pub async fn new(config: Config) -> Result<Self> {
        let mut chain = Self {
            delegate: DevChain::new(&config.url)?,
            config,
            client: reqwest::Client::builder()
                .no_proxy()
                .timeout(std::time::Duration::from_secs(10))
                .build()?,
            funding_deps: vec![],
            deps: vec![],
            funding: None,
            rounds: Arc::new(Mutex::new(HashMap::new())),
        };
        let funding = chain.contract("FundingLock", "funding-lock").await?;
        let commitment = chain.contract("CommitmentLock", "commitment-lock").await?;
        let auth: CellDep = serde_json::from_value::<ckb_jsonrpc_types::CellDep>(
            chain.config.scripts["FundingLock"]["cell_deps"][1]["cell_dep"].clone(),
        )?
        .into();
        ensure!(
            chain.config.scripts["FundingLock"]["cell_deps"][1]
                == chain.config.scripts["CommitmentLock"]["cell_deps"][1],
            "different auth deps"
        );
        chain.check_binary(&auth.out_point(), "auth").await?;
        let genesis = chain.call("get_block_by_number", json!(["0x0"])).await?;
        let cells: ckb_jsonrpc_types::TransactionView =
            serde_json::from_value(genesis["transactions"][0].clone())?;
        let groups: ckb_jsonrpc_types::TransactionView =
            serde_json::from_value(genesis["transactions"][1].clone())?;
        let group = OutPoint::new(groups.hash.pack(), 0);
        let live = chain.live_cell(&group).await?;
        let members = OutPointVec::from_slice(&live.data)?;
        ensure!(
            members.into_iter().collect::<Vec<_>>()
                == vec![
                    OutPoint::new(cells.hash.pack(), 3),
                    OutPoint::new(cells.hash.pack(), 1)
                ],
            "unexpected sighash group members"
        );
        for (index, name) in [(1, "secp256k1_blake160_sighash_all"), (3, "secp256k1_data")] {
            let cell = chain
                .live_cell(&OutPoint::new(cells.hash.pack(), index))
                .await?;
            let expected = ckb_system_scripts::BUNDLED_CELL
                .get(&format!("specs/cells/{name}"))
                .context("bundled system script")?;
            ensure!(
                cell.data == expected.as_ref(),
                "system contract bytes differ: {name}"
            );
        }
        chain.committed(&cells.hash.pack()).await?;
        chain.committed(&groups.hash.pack()).await?;
        chain.funding_deps = vec![funding, auth.clone()];
        chain.deps = vec![
            commitment,
            auth,
            CellDep::new_builder()
                .out_point(group)
                .dep_type(1u8)
                .build(),
        ];
        Ok(chain)
    }
    pub fn evidence(&self, value: Value) -> Result<()> {
        writeln!(
            std::fs::OpenOptions::new()
                .create(true)
                .append(true)
                .open(&self.config.audit)?,
            "{value}"
        )?;
        Ok(())
    }
    pub async fn call(&self, method: &str, params: Value) -> Result<Value> {
        let reply: Value = self
            .client
            .post(&self.config.url)
            .json(&json!({"jsonrpc":"2.0","id":1,"method":method,"params":params}))
            .send()
            .await?
            .error_for_status()?
            .json()
            .await?;
        self.evidence(json!({"method":method,"params":params,"reply":reply}))?;
        ensure!(reply.get("error").is_none(), "CKB {method}: {reply}");
        Ok(reply["result"].clone())
    }
    async fn contract(&self, name: &str, binary: &str) -> Result<CellDep> {
        let script: Script = serde_json::from_value::<ckb_jsonrpc_types::Script>(
            self.config.scripts[name]["cell_deps"][0]["type_id"].clone(),
        )?
        .into();
        let code: Script = serde_json::from_value::<ckb_jsonrpc_types::Script>(
            self.config.scripts[name]["script"].clone(),
        )?
        .into();
        ensure!(
            script.calc_script_hash() == code.code_hash(),
            "trusted Type ID/code hash mismatch"
        );
        let result = self.call("get_cells", json!([{"script":ckb_jsonrpc_types::Script::from(script),"script_type":"type","script_search_mode":"exact"},"asc","0x2"])).await?;
        let cells = result["objects"].as_array().context("indexer cells")?;
        ensure!(cells.len() == 1, "expected unique live Type ID {name}");
        let point: OutPoint =
            serde_json::from_value::<ckb_jsonrpc_types::OutPoint>(cells[0]["out_point"].clone())?
                .into();
        self.check_binary(&point, binary).await?;
        let live = self.live_cell(&point).await?;
        ensure!(
            live.output
                .type_()
                .to_opt()
                .context("missing Type ID")?
                .calc_script_hash()
                == code.code_hash(),
            "live Type ID mismatch"
        );
        Ok(CellDep::new_builder()
            .out_point(point)
            .dep_type(0u8)
            .build())
    }
    async fn check_binary(&self, point: &OutPoint, name: &str) -> Result<()> {
        let live = self.live_cell(point).await?;
        ensure!(
            live.data == std::fs::read(self.config.contracts.join(name))?,
            "contract bytes differ: {name}"
        );
        self.committed(&point.tx_hash()).await?;
        Ok(())
    }
    pub async fn committed(&self, hash: &Byte32) -> Result<Transaction> {
        let hash: ckb_types::H256 = hash.unpack();
        let reply = self.call("get_transaction", json!([hash])).await?;
        ensure!(
            reply["tx_status"]["status"] == "committed",
            "transaction not committed"
        );
        let tx: ckb_jsonrpc_types::TransactionView =
            serde_json::from_value(reply["transaction"].clone())?;
        let header = self
            .call("get_header", json!([reply["tx_status"]["block_hash"]]))
            .await?;
        let canonical = self
            .call("get_header_by_number", json!([header["number"]]))
            .await?;
        ensure!(
            !header.is_null()
                && canonical["hash"] == header["hash"]
                && header["hash"] == reply["tx_status"]["block_hash"],
            "non-canonical transaction"
        );
        let packed: Transaction = tx.inner.into();
        ensure!(
            tx.hash == hash && packed.calc_tx_hash() == hash.pack(),
            "transaction hash mismatch"
        );
        Ok(packed)
    }
    pub async fn lineage(&self, source: Hash256, point: &OutPoint) -> Result<()> {
        ensure!(
            point.index() == 0u32.pack(),
            "commitment output must be zero"
        );
        let mut current = point.clone();
        for _ in 0..128 {
            let tx = self.committed(&current.tx_hash()).await?;
            if tx.calc_tx_hash() == Byte32::from(source)
                || Hash256::from(fiber_types::compute_tx_message(&tx)) == source
            {
                ensure!(
                    tx.raw().cell_deps().into_iter().collect::<Vec<_>>() == self.funding_deps,
                    "wrong funding deps"
                );
                ensure!(
                    tx.raw().inputs().len() == 1 && tx.raw().outputs().len() == 1,
                    "unexpected commitment shape"
                );
                ensure!(
                    Some(
                        tx.raw()
                            .inputs()
                            .get(0)
                            .context("funding input")?
                            .previous_output()
                    ) == self.funding,
                    "unrelated funding input"
                );
                return Ok(());
            }
            let output = tx.raw().outputs().get(0).context("descendant output")?;
            let parent = tx
                .raw()
                .inputs()
                .get(0)
                .context("ancestor input")?
                .previous_output();
            ensure!(
                parent.index() == 0u32.pack(),
                "ancestor output must be zero"
            );
            let previous = self
                .committed(&parent.tx_hash())
                .await?
                .raw()
                .outputs()
                .get(0)
                .context("ancestor output")?;
            verify_link(&output, &previous)?;
            current = parent;
        }
        anyhow::bail!("ancestry exceeds 128 steps")
    }
}
fn verify_link(output: &CellOutput, previous: &CellOutput) -> Result<()> {
    let args = output.lock().args().raw_data();
    let old = previous.lock().args().raw_data();
    CommitmentContractFeatures::from_lock_args(&args).map_err(anyhow::Error::msg)?;
    CommitmentContractFeatures::from_lock_args(&old).map_err(anyhow::Error::msg)?;
    ensure!(
        output.lock().code_hash() == previous.lock().code_hash()
            && output.lock().hash_type() == previous.lock().hash_type()
            && output.type_() == previous.type_()
            && args.len() == old.len()
            && args[..36] == old[..36]
            && args[57..] == old[57..]
            && args[56] == 1,
        "invalid commitment descendant"
    );
    Ok(())
}

fn invalid(error: impl std::fmt::Display) -> SignerError {
    SignerError::InvalidContent(format!("independent deployed chain: {error}"))
}
#[async_trait::async_trait]
impl ChainVerifier for Chain {
    async fn live_cell(&self, point: &OutPoint) -> Result<VerifiedCell, SignerError> {
        self.delegate.live_cell(point).await
    }
    async fn verify_maturity(&self, inputs: &[CellInput]) -> Result<(), SignerError> {
        self.delegate.verify_maturity(inputs).await
    }
    async fn median_time_ms(&self) -> Result<u64, SignerError> {
        self.delegate.median_time_ms().await
    }
    async fn verify_commitment_lineage(
        &self,
        source: Hash256,
        point: &OutPoint,
    ) -> Result<(), SignerError> {
        self.lineage(source, point).await.map_err(invalid)
    }
}

pub async fn process(
    agent: &Agent<HttpFiberRpc, FileSignerStore>,
    rpc: &HttpFiberRpc,
    store: &std::path::Path,
    chain: &Chain,
    id: Hash256,
    check_only: bool,
) -> Result<Value> {
    let policies: Value =
        serde_json::from_slice(&std::fs::read(store.join("watchtower-approvals.json"))?)?;
    let policy = policies
        .get(format!("{id:#x}"))
        .context("no persisted watchtower approval")?;
    let destination: Script =
        serde_json::from_value::<ckb_jsonrpc_types::Script>(policy["destination"].clone())?.into();
    let max_fee = policy["max_fee"].as_u64().context("fee cap")?;
    let status = rpc
        .get_watchtower_signing_status(&agent.tenant_token()?, id.into())
        .await?
        .status;
    let fiber_json_types::WatchtowerSigningStatus::SignatureRequired {
        content,
        request_id,
        ..
    } = status
    else {
        return Ok(json!({"idle":true}));
    };
    ensure!(
        content.key_purpose == fiber_json_types::OnchainKeyPurpose::Settlement,
        "non-settlement work"
    );
    let tx: Transaction = content.transaction.clone().into();
    let first = tx
        .raw()
        .inputs()
        .get(0)
        .context("commitment input")?
        .previous_output();
    let signer = agent
        .open_channel(agent.binding(id).context("channel binding")?)
        .await?;
    let mut candidates = vec![];
    for record in signer.recovery_records().await? {
        // A remote commitment's aggregate signature belongs to the peer. The
        // SDK-verified record plus canonical, contract-valid chain lineage is
        // the settlement source; local aggregate storage is not a prerequisite.
        if !record.settlement.data.tlcs.is_empty() {
            continue;
        }
        let mut scoped = chain.clone();
        scoped.funding = Some(
            record
                .transaction
                .raw()
                .inputs()
                .get(0)
                .context("record funding")?
                .previous_output(),
        );
        if scoped
            .lineage(record.reference.tx_hash, &first)
            .await
            .is_ok()
        {
            candidates.push((record, scoped));
        }
    }
    ensure!(
        candidates.len() == 1,
        "expected unique verified ancestor, got {}",
        candidates.len()
    );
    let (record, scoped) = candidates.pop().unwrap();
    let mut total = 0u64;
    let mut sponsors = vec![];
    for (i, input) in tx.raw().inputs().into_iter().enumerate() {
        let cell = scoped.live_cell(&input.previous_output()).await?;
        if i > 0 {
            ensure!(
                cell.output.lock() == destination
                    && cell.output.type_().to_opt().is_none()
                    && cell.data.is_empty(),
                "unapproved sponsor input"
            );
            ensure!(
                !sponsors.contains(&input.previous_output()) && input.previous_output() != first,
                "duplicate sponsor"
            );
            sponsors.push(input.previous_output());
        }
        total = total
            .checked_add(cell.output.capacity().unpack())
            .context("capacity overflow")?;
    }
    for output in tx.raw().outputs() {
        total = total
            .checked_sub(output.capacity().unpack())
            .context("negative fee")?;
    }
    ensure!(total <= max_fee, "watchtower fee exceeds local cap");
    let auth = OnchainSpendAuthorization {
        source: record.reference.clone(),
        destination,
        fee: total,
        additional_inputs: sponsors,
        cell_deps: chain.deps.clone(),
    };
    let content = fiber_lsp_sdk::json::onchain_from_rpc(content);
    signer
        .prepare_onchain(content.clone(), auth.clone(), &scoped)
        .await?;
    {
        let mut rounds = chain
            .rounds
            .lock()
            .map_err(|_| anyhow::anyhow!("round lock"))?;
        let ids = rounds.entry(format!("{id:#x}")).or_default();
        let current = serde_json::to_string(&request_id)?;
        if !ids.contains(&current) {
            ensure!(
                ids.len() < 3,
                "more than three valid work reconstruction rounds"
            );
            ids.push(current);
        }
    }
    let mut checks = vec![];
    if check_only {
        for name in [
            "wrong_deps",
            "wrong_destination",
            "wrong_fee",
            "duplicate_sponsor",
        ] {
            let mut bad_content = content.clone();
            let mut bad = auth.clone();
            match name {
                "wrong_deps" => bad.cell_deps.clear(),
                "wrong_destination" => bad.destination = Script::default(),
                "wrong_fee" => bad.fee += 1,
                _ => {
                    let sponsor = auth
                        .additional_inputs
                        .first()
                        .context("selfcheck requires sponsor")?
                        .clone();
                    bad.additional_inputs.push(sponsor.clone());
                    let mut inputs: Vec<_> =
                        bad_content.transaction.raw().inputs().into_iter().collect();
                    inputs.push(CellInput::new(sponsor, 0));
                    bad_content.transaction = bad_content
                        .transaction
                        .clone()
                        .as_builder()
                        .raw(
                            bad_content
                                .transaction
                                .raw()
                                .as_builder()
                                .inputs(inputs)
                                .build(),
                        )
                        .build();
                }
            }
            let error = signer
                .prepare_onchain(bad_content, bad, &scoped)
                .await
                .err()
                .context("SDK accepted invalid authorization")?;
            let expected = match name {
                "wrong_deps" => "structure or dependencies",
                "wrong_destination" => "approved",
                "wrong_fee" => "fee",
                _ => "duplicate fee input",
            };
            ensure!(
                error.to_string().contains(expected),
                "wrong rejection for {name}: {error}"
            );
            checks.push(json!({"case":name,"error":error.to_string()}));
        }
        let original = record
            .transaction
            .raw()
            .outputs()
            .get(0)
            .context("record output")?;
        let mut args = original.lock().args().raw_data().to_vec();
        args[56] = 1;
        let next = original
            .clone()
            .as_builder()
            .lock(
                original
                    .lock()
                    .as_builder()
                    .args(args.clone().pack())
                    .build(),
            )
            .build();
        verify_link(&next, &original)?;
        for (name, offset) in [
            ("descendant_channel", 0),
            ("descendant_settled", 56),
            ("descendant_features", 57),
        ] {
            let mut bad = args.clone();
            if offset == bad.len() {
                bad.push(1);
            } else {
                bad[offset] ^= 1;
            }
            let output = next
                .clone()
                .as_builder()
                .lock(next.lock().as_builder().args(bad.pack()).build())
                .build();
            let error = verify_link(&output, &original)
                .err()
                .context("invalid descendant accepted")?;
            checks.push(json!({"case":name,"error":error.to_string()}));
        }
        let error = scoped
            .verify_maturity(&[CellInput::new(first.clone(), 1_000_000_000)])
            .await
            .err()
            .context("immature since accepted")?;
        ensure!(
            error.to_string().contains("not mature"),
            "wrong maturity rejection: {error}"
        );
        checks.push(json!({"case":"immature_since","error":error.to_string()}));
        let error = scoped
            .live_cell(scoped.funding.as_ref().unwrap())
            .await
            .err()
            .context("spent funding accepted")?;
        ensure!(
            error.to_string().contains("not live"),
            "wrong live rejection"
        );
        checks.push(json!({"case":"dead_input","error":error.to_string()}));
        let mut bad_chain = scoped.clone();
        bad_chain.funding = Some(OutPoint::default());
        let error = bad_chain
            .lineage(record.reference.tx_hash, &first)
            .await
            .err()
            .context("unrelated funding accepted")?;
        ensure!(
            error.to_string().contains("unrelated funding"),
            "wrong lineage rejection: {error}"
        );
        checks.push(json!({"case":"unrelated_funding","error":error.to_string()}));
        let error = scoped
            .lineage(record.reference.tx_hash, &OutPoint::new(first.tx_hash(), 1))
            .await
            .err()
            .context("nonzero commitment output accepted")?;
        ensure!(
            error.to_string().contains("output must be zero"),
            "wrong output rejection"
        );
        checks.push(json!({"case":"invalid_lineage_output","error":error.to_string()}));
    }
    let evidence = json!({"request_id":request_id,"authorization":auth,"source":record.reference,"checks":checks,"check_only":check_only});
    scoped.evidence(evidence.clone())?;
    if !check_only {
        agent.poll_watchtower_verified(id, auth, &scoped).await?;
    }
    Ok(evidence)
}
