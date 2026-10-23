# METER

Pay for the uptime you got, not the uptime you were promised.

A service sold on "99.9% uptime" is paid for in advance and argued about afterwards. The buyer pays the full fee, the provider has a bad week, and the remedy is a support ticket asking for credit. METER inverts that. The buyer escrows the fee, the contract samples the provider's own health URL in fixed slots across the billing window under consensus, and when the window closes the provider is paid for the share of slots that found the service up. The rest goes back to the buyer, automatically, in the same transaction.

Every sample is a live HTTP fetch of a third-party URL that neither side controls once the plan is agreed, read independently by every validator.

**This is a bill, not insurance.** [PERIL](https://github.com/Jennivarl/peril), an earlier project of mine, also watches for outages, but it is cover: a policyholder pays a premium into a pool and is paid a fixed sum if an outage happens. METER has no pool, no claim and no event. A buyer pays a provider for a service, and the amount is computed from many measurements of that service across the billing window. Any URL works, not only status pages.

| contract | what it does |
|---|---|
| **PLAN** | The terms: provider, URL, the marker a healthy response contains, the fee, the window length. Proposed by the buyer, accepted by the provider. |
| **METER** | The measurements. Each sample is one consensus round over a real fetch of the agreed URL. |
| **LEDGER** | The escrow. Divides the fee by what METER measured once the window has closed. |
| **GRADE** | The reference consumer: a renewal that only opens on a closed window that measured high enough. |

| | |
|---|---|
| Network | GenLayer Studio Next, chain id 61997, `https://studio-next.genlayer.com/api` |
| Engine | Consensus v0.6, GenVM v0.3, runner `py-genlayer:5jycge...` |
| PLAN | [`0x208c57714b3Dfb87a82f313C07c7184856c7843B`](https://explorer-studio-dev.genlayer.com/address/0x208c57714b3Dfb87a82f313C07c7184856c7843B) |
| METER | [`0xCA5Cb1a544fA990bDE788b6E1D275678b0228b2A`](https://explorer-studio-dev.genlayer.com/address/0xCA5Cb1a544fA990bDE788b6E1D275678b0228b2A) |
| LEDGER | [`0xEf7AeD6Bc18B3E82C92bB75BcEFd9266d095d6a1`](https://explorer-studio-dev.genlayer.com/address/0xEf7AeD6Bc18B3E82C92bB75BcEFd9266d095d6a1) |
| GRADE | [`0xc675643Ba40822435198aeAA5e3A042be134D4A6`](https://explorer-studio-dev.genlayer.com/address/0xc675643Ba40822435198aeAA5e3A042be134D4A6) |
| Tests | 187, `python -m pytest -q` |

---

## Every sample counts, and only a healthy one is paid

The tempting design has three buckets: up, down, and "could not tell" for a host the validators failed to reach or a status that might be about the route rather than the service. It is wrong, and the reason is the whole design.

A bucket that does not count is a lever, and the provider is the one holding it. Suppose unreachable samples are set aside. A server that answers three good samples and then goes completely dark stands at **3 up out of 3 counted**, and is paid in full for a month it spent offline. The same goes for any status a provider can serve on purpose: return a 403 while broken, and the broken hours vanish from the denominator.

So METER has two outcomes. A response that succeeded and contains the agreed marker is **up**. Everything else is **down**, with the reason kept: answered without the marker, answered 503, answered 403, could not be reached. The provider chose the URL and agreed to be measured from it; a URL the network cannot read is a sample against them.

**This is the opposite of how [VIGIL](https://github.com/Jennivarl/Vigil) treats the same fact, deliberately.** VIGIL hands over an inheritance when a page goes silent, so mistaking an unreachable host for silence would hand over an estate: there, an unreachable host must count for nothing. Here, ignoring it would pay for an outage. Which way an ambiguous reading falls is decided by who would be hurt by getting it wrong.

### Validators agree on whether it was down, not why

A healthy response looks the same from everywhere: a 200 containing the marker. A real outage does not. One validator sees a 502, another a 503, a third a timeout, and all three are right that the service was down. An earlier version of this contract required validators to agree on the reason as well as the outcome. That made outages fail consensus far more often than healthy samples, so outage samples quietly went unrecorded while healthy ones always landed, and every bill leaned toward the provider. Nothing about the money depends on the reason, so it is no longer compared, and because consensus no longer agrees on it, it is no longer stored. Only the outcome is written down.

---

## The rules, and what each one stops

**The fee goes in before the provider accepts.** Otherwise a buyer could watch the first samples and fund only a plan that was going to cost little, leaving a provider who had been reliable unpaid. LEDGER refuses a fee once the plan is live.

**The window opens at acceptance, and lasts an hour to a month.** Nobody types a start date, so nobody can choose one that happens to miss a known outage, and nothing is measured before both sides have agreed to the terms. An hour holds six slots, room for the minimum three readings with slack.

**When a reading may be taken is fixed in advance.** A steward caught that the earlier rule, samples at least ten minutes apart, still let either side choose its moments: a provider could sample only in good minutes, a buyer only in bad ones. Now the window is cut into **ten-minute slots** counted from acceptance. Each slot takes **at most one reading**, across every caller, and only in its **first four minutes**. The band is short and set before anyone knows how the service will behave in it, so there is no good moment to wait for.

**Every slot is billed, read or not.** The provider is paid for the share of the window's slots that were read and found up. A slot nobody read proves no service, so it is not paid: skipping the slots where the service was down cannot raise the provider's share, and the provider, who gains from every up reading, is the one with the reason to read every slot.

**Samples only exist inside the window.** One taken after the window closes is refused, so the tally LEDGER settles on is final and nothing can be added to it once money has moved.

**Three readings or nothing.** Below that, the provider is paid nothing and the buyer gets the whole fee back. Two samples cannot tell a flaky minute from a bad month, and billing on no evidence is paying for a promise again.

**The split is exact.** The provider gets `fee × up ÷ slots`, rounded down. The buyer gets everything else. The two parts always sum to exactly the fee, checked against five thousand random tallies, so no rounding can create or lose value, and the fraction left by rounding goes to the side that paid.

---

## What consensus derived, and what was copied

| stored field | where it comes from | derived or copied |
|---|---|---|
| each sample's outcome | every validator fetched the agreed URL itself and reached the same up or down | derived |
| the URL fetched | built by the contract from the plan's host and path | derived |
| the up and down counts | the contract's own arithmetic over agreed samples | derived |
| sample timestamps, window open and close | the transactions' own `datetime` | derived |
| which slot a reading belongs to, and the slot count | the window and the sampling transaction's own `datetime` | derived |
| the provider's payment and the buyer's refund | `share()` over the final tally | derived |
| the host, path, marker, fee and window length | the buyer's proposal, accepted by the provider, immutable | theirs, immutably |

The leader's reading is used for one thing: as the proposal each validator checks against its own fetch, by exact equality on the outcome. The reason a sample was down is visible in each validator's execution on the explorer; it is not written to the contract, because consensus did not agree on it.

---

## What a dishonest leader can try

| the lie | what it would buy | what happens | test |
|---|---|---|---|
| call an outage up | pays the provider for a broken service | rejected | `test_a_validator_rejects_a_leader_who_calls_an_outage_up` |
| call a healthy service down | refunds the buyer for a service they got | rejected | `test_a_validator_rejects_a_leader_who_calls_a_healthy_service_down` |
| hide an outage by disputing its reason | an outage that never reaches the tally, if validators had to agree on why | not possible: only the outcome is compared, so a 502 and a timeout are both down | `test_validators_agree_an_outage_was_down_whatever_each_of_them_saw` |
| invent an outcome | anything outside up and down | rejected, and refused again before storage | `test_a_validator_rejects_an_outcome_the_contract_does_not_define` |
| crash instead of answering | stalls the round | rejected: a malformed result is a disagreement | `test_a_validator_rejects_a_leader_that_errored` |

---

## Every funded state has a way out

| state | the way out |
|---|---|
| funded, the provider never accepted | the buyer withdraws the plan in PLAN, then reclaims the whole fee in LEDGER |
| live, window closed, three or more readings | settle divides the fee by the share of slots read up |
| live, window closed, fewer than three readings | settle returns the whole fee to the buyer |

Settling and reclaiming can never both be open: one needs the plan `live`, the other needs it `withdrawn`. Reclaiming requires the buyer to withdraw first, which also stops the provider accepting afterwards, so the fee can never leave while a provider is still entitled to take the plan.

---

## Verified live on Studio Next

Two plans against **GitHub's own status API**, `https://www.githubstatus.com/api/v2/status.json`, a page nobody involved controls, each counting a sample up when it contains `All Systems Operational`. The provider is a second wallet that accepted both plans itself. One-hour windows, so six ten-minute slots each. Every address in [`deploy/live.json`](deploy/live.json) runs the exact bundle committed here, which `deploy/verify.mjs` proves by hashing the source carried in each deploy transaction.

The plan was to read every slot of **github** and only the even slots of **skipped**. Then Studio Next itself stopped processing transactions from about 23:28 to 00:08 UTC, so slots 3 to 5 of both plans went unread, and the readings sent for them landed after the windows had closed. That is exactly the case the slot rule exists for, so it is shown as it happened.

| step | transaction | result |
|---|---|---|
| Propose, fund, accept: github | [`0x71c2582b...`](https://explorer-studio-dev.genlayer.com/tx/0x71c2582b8db2a5f639cc31479ee176050e4597f8810727a33376460069a8dc42) | 0.02 GEN, a one-hour window. [Funded](https://explorer-studio-dev.genlayer.com/tx/0x57f56d88bf231811c3c464628c5b44c11424805b201d6974e581ab23be3135d1) **before** the provider [accepted](https://explorer-studio-dev.genlayer.com/tx/0x953aae5ae38c05da6e97c70943cb3036134ac0aedfa23397324ff288ccf6623e) from its own wallet |
| Propose, fund, accept: skipped | [`0xe055a103...`](https://explorer-studio-dev.genlayer.com/tx/0xe055a103f6c532d6ea169c53bd4add6a98b9294ee199bd9f9c14bd9c500ae5e5) | the same terms. [Funded](https://explorer-studio-dev.genlayer.com/tx/0x870425419e7122acfae697f296e23e95dfc58d0230b369c0f9f33a6f2577f290), [accepted](https://explorer-studio-dev.genlayer.com/tx/0x159c4636c7a1b468d581e3da8b3df05d59940dac6d2d2915e2b2ac74e3e05d08) |
| github slot 0 | [`0xfb016d9c...`](https://explorer-studio-dev.genlayer.com/tx/0xfb016d9ceef60e98152d7ee7c618f28fddd6878e5836b5a2facb9e4a89d33133) | **up** |
| github slot 0, again | [`0xf1f21a2b...`](https://explorer-studio-dev.genlayer.com/tx/0xf1f21a2bd3f2fa9a1576dfe9c34cf89a24ac9333af1c9b37bbcf4470ecdb5acd) | **refused**, from the provider's wallet: *slot 0 already has its reading* |
| github, five minutes into slot 0 | [`0x6b268a12...`](https://explorer-studio-dev.genlayer.com/tx/0x6b268a12d7711191faa8ef440012da9c97dea5c8e294c861c76ebf5f4345c0e8) | **refused**: *a reading counts only in the first 240 seconds of each 600-second slot* |
| Settle github while open | [`0x2f5e2204...`](https://explorer-studio-dev.genlayer.com/tx/0x2f5e2204f63856ea01f7323f47039159fbb675cf2e41acf84cf662bf40c9a9ae) | **refused**: *the window is still open, so the tally is not final* |
| github slots 1 and 2 | [`0x8a6bd5a7...`](https://explorer-studio-dev.genlayer.com/tx/0x8a6bd5a74e8f46a8cd7c85e5169d0663e977c15dc625fb0b59c4727f8722163f) | **up**, and [**up**](https://explorer-studio-dev.genlayer.com/tx/0x637bb8e14dbf2a2616f2cf7ea6760a9b41e694c8c0dbdd7f5e694378bf0727a3) |
| skipped slots 0 and 2 | [`0xdaab3da7...`](https://explorer-studio-dev.genlayer.com/tx/0xdaab3da75ff5e42509d3edc4595cbc10e1e93ed6f89d0f90f51d57d4f92ca233) | **up**, and [**up**](https://explorer-studio-dev.genlayer.com/tx/0xd2349110eac9234501041ed7bcb17dd673b70430f39cf0ca8bba716e901eb152) |
| github slot 3, sent during the stall | [`0xc37b3ebd...`](https://explorer-studio-dev.genlayer.com/tx/0xc37b3ebd8d194f71a05bfb147502537943faf837171a2836afe083fd12e4eebd) | **refused** when it finally ran: *the window has closed*. Slots 4 and 5, and skipped's slot 4, the same |
| Settle github | [`0x03f06e88...`](https://explorer-studio-dev.genlayer.com/tx/0x03f06e889c8deb6b196e21e9e60c744504fa9155428ae7a2a175f77ebf0418fb) | *3 of 6 slots found the service up, 3 not read*: provider **0.01 GEN**, buyer **0.01 GEN** |
| Settle skipped | [`0xc73dfa95...`](https://explorer-studio-dev.genlayer.com/tx/0xc73dfa95d817d13028a50a6218a3690cf8707565969278345032418850962252) | *only 2 samples were taken and 3 are needed to bill*: the whole **0.02 GEN** back to the buyer |
| Renew on GRADE | [`0x49320a03...`](https://explorer-studio-dev.genlayer.com/tx/0x49320a0340c9b43fcaa971bb893af0ead4b03f257d0e5ed0c67bd7244809dcf7) | **refused**: *measured 5000 basis points, below the 9900 required* |

Afterwards LEDGER's `committed` is back to `0`.

**Settle github** is the fix doing its job. Every reading that landed was up. Under the old rule, a bill divided by the readings taken, that is three of three and a full payout for an hour in which half the slots were never measured. Divided by the slots, the provider is paid for the half that was shown. Nobody chose which slots went unread, and nobody could have: each slot opened and closed on a schedule fixed when the provider accepted.

**Settle skipped** is the minimum doing its job: two readings are not enough to bill on, so the buyer pays nothing.

What the samples do not record is *why* any reading was down. That is deliberate: consensus only agrees on the outcome, so only the outcome is stored. Each validator's own fetch is visible in its execution on the explorer.

---

## Limits, stated plainly

- **It measures the URL both sides agreed on, nothing more.** A health endpoint the provider writes reports whatever the provider wants it to. A buyer should name a URL that exercises the real service, and a marker that only a working response contains.
- **Sampling is a sample, not a census.** One reading per ten-minute slot, taken in its first four minutes. An outage that starts and ends inside the rest of a slot is not seen.
- **Somebody has to send each reading.** The schedule is fixed but the contract cannot wake itself. The provider has the reason to read every slot, because an unread slot is not paid; a buyer who also reads gets a say in which minute of the band is measured.
- **The first reading in a slot is the one that counts.** Either side may take it anywhere in the four-minute band. That is the timing choice left, and it is four minutes wide rather than the whole window.
- **An unreachable host is billed against the provider.** That is the right default for a bill, for the reasons above, but it does mean a fault on the network side that every validator shares at once lands on the provider. Consensus makes a single validator's bad connection harmless; a shared one is not.
- **A provider who accepts an unfunded plan is measured for nothing.** The fee must go in before acceptance, but PLAN cannot check that without reading LEDGER, and LEDGER already reads PLAN. `LEDGER.is_funded` is public and is the provider's check before accepting.
- **The window is at most a month and at least an hour**, and one plan is one window. A recurring subscription is one plan per period.

---

## Running it

```sh
python -m venv .venv && .venv/Scripts/pip install -r requirements.txt
python -m deploy.build_bundle          # the four files that actually deploy
python -m pytest -q                    # 187 tests, no chain and no network
```

The tests run the contracts in direct mode, in process, with every fetch answered from the test, so a test can make the service healthy, broken, behind an auth wall, or gone. An unmocked fetch raises rather than going out to the network, which is how a test reaches the "could not be reached" path.

```sh
npm install
export GENLAYER_KEYSTORE=~/.genlayer/keystores/mykey.json
export GENLAYER_PASSWORD=...
node deploy/deploy.mjs contracts/plan_bundle.py
node deploy/deploy.mjs contracts/meter_bundle.py  <plan address>
node deploy/deploy.mjs contracts/ledger_bundle.py <plan address> <meter address>
node deploy/deploy.mjs contracts/grade_bundle.py  <meter address> <plan id> <basis points>
node deploy/verify.mjs                 # no key needed: each live contract runs this exact bundle
```

Settling a plan that bills both sides sends two payments, so the transaction must reserve two funded external message allocations; see `deploy/chain.mjs`. Addresses live in [`deploy/live.json`](deploy/live.json). The password is read from the environment and is never stored in this repo.

---

## Layout

```
contracts/metering.py       the pure part: what a fetch means, the split, dates
contracts/plan.py           the terms both sides sign
contracts/meter.py          samples of the live service, under consensus
contracts/ledger.py         escrow and the division of the fee
contracts/grade.py          reference consumer: a renewal gated on a closed window
contracts/*_bundle.py       what actually deploys. Generated, never edited
deploy/build_bundle.py      builds them; a test fails if a committed one is stale
deploy/verify.mjs           prove a live contract runs this exact bundle
test/                       187 tests
```

GenVM loads a single source file with no access to siblings, so each bundle pastes a contract together with the pure module it imports. Comments and docstrings are stripped from the deployed copy, because a deploy costs gas per byte. Edit the modules, never a bundle: a test regenerates them and fails if a committed copy has drifted.

## License

MIT
