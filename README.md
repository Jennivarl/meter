# METER

Pay for the uptime you got, not the uptime you were promised.

A service sold on "99.9% uptime" is paid for in advance and argued about afterwards. The buyer pays the full fee, the provider has a bad week, and the remedy is a support ticket asking for credit. METER inverts that. The buyer escrows the fee, the contract samples the provider's own health URL across the billing window under consensus, and when the window closes the provider is paid for the share of samples that found the service up. The rest goes back to the buyer, automatically, in the same transaction.

Every sample is a live HTTP fetch of a third-party URL that neither side controls once the plan is agreed, read independently by every validator.

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
| METER | [`0xa4a703F4be228c666aA0dDCbc28C46CfA8daAff3`](https://explorer-studio-dev.genlayer.com/address/0xa4a703F4be228c666aA0dDCbc28C46CfA8daAff3) |
| Tests | 173, `python -m pytest -q` |

---

## Every sample counts, and only a healthy one is paid

The tempting design has three buckets: up, down, and "could not tell" for a host the validators failed to reach or a status that might be about the route rather than the service. It is wrong, and the reason is the whole design.

A bucket that does not count is a lever, and the provider is the one holding it. Suppose unreachable samples are set aside. A server that answers three good samples and then goes completely dark stands at **3 up out of 3 counted**, and is paid in full for a month it spent offline. The same goes for any status a provider can serve on purpose: return a 403 while broken, and the broken hours vanish from the denominator.

So METER has two outcomes. A response that succeeded and contains the agreed marker is **up**. Everything else is **down**, with the reason kept: answered without the marker, answered 503, answered 403, could not be reached. The provider chose the URL and agreed to be measured from it; a URL the network cannot read is a sample against them.

**This is the opposite of how [VIGIL](https://github.com/Jennivarl/Vigil) treats the same fact, deliberately.** VIGIL hands over an inheritance when a page goes silent, so mistaking an unreachable host for silence would hand over an estate: there, an unreachable host must count for nothing. Here, ignoring it would pay for an outage. Which way an ambiguous reading falls is decided by who would be hurt by getting it wrong.

---

## The rules, and what each one stops

**The fee goes in before the provider accepts.** Otherwise a buyer could watch the first samples and fund only a plan that was going to cost little, leaving a provider who had been reliable unpaid. LEDGER refuses a fee once the plan is live.

**The window opens at acceptance.** Nobody types a start date, so nobody can choose one that happens to miss a known outage, and nothing is measured before both sides have agreed to the terms.

**Samples are at least ten minutes apart, across every caller.** Otherwise a party could take a burst of samples in one good minute and call it a month.

**Samples only exist inside the window.** One taken after the window closes is refused, so the tally LEDGER settles on is final and nothing can be added to it once money has moved.

**Three samples or nothing.** Below that, the provider is paid nothing and the buyer gets the whole fee back. Two samples cannot tell a flaky minute from a bad month, and billing on no evidence is paying for a promise again.

**The split is exact.** The provider gets `fee × up ÷ samples`, rounded down. The buyer gets everything else. The two parts always sum to exactly the fee, checked against five thousand random tallies, so no rounding can create or lose value, and the fraction left by rounding goes to the side that paid.

---

## What consensus derived, and what was copied

| stored field | where it comes from | derived or copied |
|---|---|---|
| each sample's outcome and reason | every validator fetched the agreed URL itself and reduced the answer to the same pair | derived |
| the URL fetched | built by the contract from the plan's host and path | derived |
| the up and down counts | the contract's own arithmetic over agreed samples | derived |
| sample timestamps, window open and close | the transactions' own `datetime` | derived |
| the provider's payment and the buyer's refund | `share()` over the final tally | derived |
| the host, path, marker, fee and window length | the buyer's proposal, accepted by the provider, immutable | theirs, immutably |

The leader's reading is used for one thing: as the proposal each validator checks against its own fetch, by exact equality on both the outcome and the reason.

---

## What a dishonest leader can try

| the lie | what it would buy | what happens | test |
|---|---|---|---|
| call an outage up | pays the provider for a broken service | rejected | `test_a_validator_rejects_a_leader_who_calls_an_outage_up` |
| call a healthy service down | refunds the buyer for a service they got | rejected | `test_a_validator_rejects_a_leader_who_calls_a_healthy_service_down` |
| agree on the outcome, change the reason | a 403 presented as a 500, or the reverse | rejected: the reason is compared too | `test_validators_must_agree_on_the_reason_not_only_the_outcome` |
| invent an outcome | anything outside up and down | rejected, and refused again before storage | `test_a_validator_rejects_an_outcome_the_contract_does_not_define` |
| crash instead of answering | stalls the round | rejected: a malformed result is a disagreement | `test_a_validator_rejects_a_leader_that_errored` |

---

## Every funded state has a way out

| state | the way out |
|---|---|
| funded, the provider never accepted | the buyer withdraws the plan in PLAN, then reclaims the whole fee in LEDGER |
| live, window closed, three or more samples | settle divides the fee by measured uptime |
| live, window closed, fewer than three samples | settle returns the whole fee to the buyer |

Settling and reclaiming can never both be open: one needs the plan `live`, the other needs it `withdrawn`. Reclaiming requires the buyer to withdraw first, which also stops the provider accepting afterwards, so the fee can never leave while a provider is still entitled to take the plan.

---

## Verified live on Studio Next

A real plan against **GitHub's own status API**, `https://www.githubstatus.com/api/v2/status.json`, healthy when it contains `All Systems Operational`. Nobody involved controls that page. The provider is a second wallet that accepted the terms itself. Every address in [`deploy/live.json`](deploy/live.json) runs the exact bundle committed here, which `deploy/verify.mjs` proves by hashing the source carried in each deploy transaction.

| step | transaction | result |
|---|---|---|
| Propose the plan | [`0x63adee4d...`](https://explorer-studio-dev.genlayer.com/tx/0x63adee4d362cf315ed738fb934e84d6e3bafe919946b3cdc1a6bb311ced9fe4a) | 0.02 GEN, a 30 minute window |
| Fund it | [`0x24ba0771...`](https://explorer-studio-dev.genlayer.com/tx/0x24ba0771acb2a01a31e4722221cd09ba5fa6bd0cbb1c1b09d9989b35e01d237b) | escrowed **before** acceptance |
| Provider accepts | [`0x90df9a4b...`](https://explorer-studio-dev.genlayer.com/tx/0x90df9a4b8a14c6c39ca8fb124481ff849dbbe658f3f3cb9e32cd6b5ad35c4d3d) | from the provider's own wallet; the window opens at this transaction's time |
| Settle, too early | [`0xd1855d71...`](https://explorer-studio-dev.genlayer.com/tx/0xd1855d716de9a57d71ab93db33761bceaed6aee7fecdca7cfc7db3a02793d4ef) | **refused**: the window is still open |
| Renew, too early | [`0x10ba7c0e...`](https://explorer-studio-dev.genlayer.com/tx/0x10ba7c0e3f9cce6b3985c5a2e0b756572da9bed429c2284e00d2c9e48f4e53bf) | GRADE **refused**: a window in progress is not a result |
| Sample 1 | [`0xf257f53e...`](https://explorer-studio-dev.genlayer.com/tx/0xf257f53e3493c9e76c862a49376dfc285470063e755b503988b84f88120cac60) | **up**: answered with the marker |
| Sample again, at once | [`0xc4cbae10...`](https://explorer-studio-dev.genlayer.com/tx/0xc4cbae10a2803b065e6fe60caa5040eea870e393d7b37be96d54dc69ba6e79ce) | **refused**, from the provider's wallet: samples must be 600 seconds apart, whoever calls |
| Sample 2 | [`0xb2ad284e...`](https://explorer-studio-dev.genlayer.com/tx/0xb2ad284e64eb0cc245c85b8f2d80704d1c8af175ef2b35fce73505469843882c) | **up**, 12 minutes later |
| Sample 3 | [`0x4ef4a552...`](https://explorer-studio-dev.genlayer.com/tx/0x4ef4a5528845cb484fcaa1515ea125ff87b490eb5d7f33913fd81ac65078c586) | **up**, 12 minutes later. Enough to bill |
| Sample after close | [`0xb6c10b7a...`](https://explorer-studio-dev.genlayer.com/tx/0xb6c10b7a3b8aab84055f243bb9d8b324228d6199518139fe66d890f23ec44946) | **refused**: the window has closed, so the tally is final |
| Settle | [`0x4de6f724...`](https://explorer-studio-dev.genlayer.com/tx/0x4de6f724124976a72719e7d8471b165a34a1205c30c39dea80d2b364f8b83346) | 3 of 3 up. Provider **0.228506 → 0.248506 GEN**, the whole fee. `committed` back to `0` |
| Renew | [`0xeebc15cb...`](https://explorer-studio-dev.genlayer.com/tx/0xeebc15cb820f2a17ce602b4e5effa74c552338ccd76a2f89c5fe2bc2249594fe) | GRADE opens: a closed window at 10000 basis points against a 9900 bar |

And the exit for a plan the provider never took, on a second plan:

| step | transaction | result |
|---|---|---|
| Propose and fund | [`0xf39ba778...`](https://explorer-studio-dev.genlayer.com/tx/0xf39ba77897f618d61a98319f09607e94e1333822ab51994c44d3f606e687930e), [`0xa1873da3...`](https://explorer-studio-dev.genlayer.com/tx/0xa1873da34add36cfbd2ce80c43ae4d0c253a494c8ee14a20822f6210ab598532) | 0.02 GEN held |
| Withdraw | [`0x23512e15...`](https://explorer-studio-dev.genlayer.com/tx/0x23512e155579cf009d5d46cc78983a39df31b8ae7ec81d66430c761fe6a1b7c5) | the provider can no longer accept it |
| Reclaim | [`0x2b51db1e...`](https://explorer-studio-dev.genlayer.com/tx/0x2b51db1e4cae265099375feea75961c84bf7771b70c31d167a03a876a7ab7a1a) | buyer **37.247265 → 37.267139 GEN**, the fee back less gas |

**What this run did not show:** a partial split. GitHub stayed healthy for the whole window, so every sample was up and the provider was paid in full. The proportional division is exercised by the test suite, including the five-thousand-tally check that the two parts always sum to the fee, but on chain only the full-payment end has been seen.

---

## Limits, stated plainly

- **It measures the URL both sides agreed on, nothing more.** A health endpoint the provider writes reports whatever the provider wants it to. A buyer should name a URL that exercises the real service, and a marker that only a working response contains.
- **Sampling is a sample, not a census.** An outage that starts and ends between two samples is not seen. Ten minutes is the floor between samples, not a schedule.
- **Both sides choose when to sample.** Anyone may sample, and the gap applies to everyone, so neither side can crowd the other out. But a buyer who never samples is trusting the provider's choice of moments. The remedy is to sample.
- **An unreachable host is billed against the provider.** That is the right default for a bill, for the reasons above, but it does mean a fault on the network side that every validator shares at once lands on the provider. Consensus makes a single validator's bad connection harmless; a shared one is not.
- **The window is at most a month and at least thirty minutes**, and one plan is one window. A recurring subscription is one plan per period.

---

## Running it

```sh
python -m venv .venv && .venv/Scripts/pip install -r requirements.txt
python -m deploy.build_bundle          # the four files that actually deploy
python -m pytest -q                    # 173 tests, no chain and no network
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
node deploy/verify.mjs                 # each live contract runs this exact bundle
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
test/                       173 tests
```

GenVM loads a single source file with no access to siblings, so each bundle pastes a contract together with the pure module it imports. Comments and docstrings are stripped from the deployed copy, because a deploy costs gas per byte. Edit the modules, never a bundle: a test regenerates them and fails if a committed copy has drifted.

## License

MIT
